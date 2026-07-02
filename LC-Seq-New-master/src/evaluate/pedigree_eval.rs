use crate::evaluate::consensus::{consensus, ConsensusResult};
use crate::library::{NodeKind, Pedigree};
use crate::peaks::{pick_peaks_with_quality, Peak, PeakPickerConfig, PeakQualityParams};
use petgraph::graph::NodeIndex;
use petgraph::Direction;
use rayon::prelude::*;
use std::collections::HashMap;

/// Outcome of evaluating one pedigree node. Mirrors [`ConsensusResult`] field-by-field
/// (with `effective_threshold` added for transparency on the parent-derived threshold
/// the consensus rule used). See [`ConsensusResult`] for full field semantics.
#[derive(Debug, Clone, PartialEq)]
pub struct NodeOutcome {
    pub passed: bool,
    pub insufficient_data: bool,

    // Stage 1: per-rep initial picks
    pub initial_earliest_picks: Vec<Option<f64>>,
    pub initial_most_significant_picks: Vec<Option<f64>>,
    pub initial_democratic_picks: Vec<Option<f64>>,

    // Stage 1: eclass-level aggregates
    pub initial_democratic_position: Option<f64>,
    pub score_test_rt: Option<f64>,
    pub score_test_rt_se: Option<f64>,
    pub score_test_p_value: Option<f64>,
    pub per_rep_score_contribution: Option<Vec<Option<f64>>>,

    // Stage 2: Bayesian inference outputs
    pub bayesian_pick: Option<f64>,
    pub bayesian_pick_posterior: Option<f64>,
    pub bayesian_pick_runner_up_posterior: Option<f64>,
    pub bayesian_pick_threshold_margin: Option<f64>,

    // Stage 2: per-rep refined picks + supporting indicator
    pub bayesian_refined_picks: Vec<Option<f64>>,
    pub bayesian_supporting_replicates: Vec<usize>,

    // Replicate accounting
    pub n_replicates: usize,
    pub n_replicates_with_signal: usize,
    pub replicates_with_no_signal: Vec<usize>,

    /// Threshold the consensus rule used: max(structural parent rts, chemical-
    /// monotonicity component rts for cassette BBs). The vote floor applied to
    /// per-rep peaks is `effective_threshold + tolerance`. None for the root.
    pub effective_threshold: Option<f64>,
}

/// A single chromatogram (parallel rt and intensity arrays).
pub type Chromatogram = (Vec<f64>, Vec<f64>);

/// Key for the chromatograms map: the per-position BB names as a tuple, in N→C order.
/// E.g. `["AgxNull", "DLeu", "AgxNull"]`. Using a Vec<String> instead of a joined string
/// avoids collisions when BB names themselves contain the separator character (e.g.
/// the cassette BBs like `"DLeu-DLeu-Pro"`).
pub type ChromatogramKey = Vec<String>;

/// Evaluate the pedigree.
///
/// For root: peak-pick its chromatogram, take the highest-amplitude peak; that rt becomes
/// the threshold passed down. Pass iff a qualifying peak exists.
///
/// For tier 1..=N: gate on all parent nodes being present and passed; threshold = max of
/// parent consensus rts; run [`consensus`] on the peaks of each member chromatogram.
///
/// Pruned subtrees are simply absent from the returned map.
pub fn evaluate(
    pedigree: &Pedigree,
    chromatograms: &HashMap<ChromatogramKey, Chromatogram>,
    tolerance: f64,
    picker: &PeakPickerConfig,
    quality: PeakQualityParams,
) -> HashMap<NodeIndex, NodeOutcome> {
    let mut out: HashMap<NodeIndex, NodeOutcome> = HashMap::new();

    // Group node indices by tier. The pedigree builder only emits parent→child edges
    // that cross exactly one tier, so tier order IS a valid topological order — and
    // within a tier, nodes are independent (their parents are all settled by then),
    // which is exactly the precondition for parallelism via rayon below.
    let mut by_tier: Vec<Vec<NodeIndex>> = Vec::new();
    for ix in pedigree.node_indices() {
        let tier = pedigree[ix].tier;
        if by_tier.len() <= tier {
            by_tier.resize(tier + 1, Vec::new());
        }
        by_tier[tier].push(ix);
    }

    // Tier 0 (root): single member, n=1 path. Pick by criterion to match field
    // semantics: most-significant = lowest p-value, earliest = smallest rt.
    // No cross-rep score test, no Bayesian inference (the call IS the most-
    // significant pick; it surfaces via initial_most_significant_picks[0]).
    if let Some(roots) = by_tier.first() {
        for &ix in roots {
            let node = &pedigree[ix];
            let member = &node.members[0];
            let allow_rescue = quality_rescue_for_node(pedigree, ix);
            let peaks = pick_for(
                &member.positions,
                chromatograms,
                picker,
                quality,
                allow_rescue,
            );
            let most_significant_pick = peaks
                .iter()
                .min_by(|a, b| a.p_value.partial_cmp(&b.p_value).unwrap())
                .map(|p| p.rt);
            let earliest_pick = peaks
                .iter()
                .min_by(|a, b| a.rt.partial_cmp(&b.rt).unwrap())
                .map(|p| p.rt);
            let n_replicates_with_signal = if peaks.is_empty() { 0 } else { 1 };
            out.insert(
                ix,
                NodeOutcome {
                    passed: most_significant_pick.is_some(),
                    insufficient_data: peaks.is_empty(),
                    initial_earliest_picks: vec![earliest_pick],
                    initial_most_significant_picks: vec![most_significant_pick],
                    initial_democratic_picks: vec![None],
                    initial_democratic_position: None,
                    score_test_rt: None,
                    score_test_rt_se: None,
                    score_test_p_value: None,
                    per_rep_score_contribution: None,
                    bayesian_pick: None,
                    bayesian_pick_posterior: None,
                    bayesian_pick_runner_up_posterior: None,
                    bayesian_pick_threshold_margin: None,
                    bayesian_refined_picks: vec![None],
                    bayesian_supporting_replicates: Vec::new(),
                    n_replicates: 1,
                    n_replicates_with_signal,
                    replicates_with_no_signal: Vec::new(),
                    effective_threshold: None,
                },
            );
        }
    }

    // Tier 1, two passes: simple-BB singletons FIRST (so their consensus rts are known
    // before cassette singletons need them as a chemical-monotonicity threshold). A
    // "cassette" is a multi-residue BB whose name contains '-'; e.g. `"DLeu-DLeu-Pro"`.
    // The chemistry: in RPLC, peptide retention is monotone in residue composition —
    // adding any residue moves you LATER, never earlier. So a cassette's RT must be
    // ≥ max(its singleton-component RTs) + tolerance. We enforce this by augmenting
    // the threshold computed from structural parents with these chemical constraints.
    let empty_singletons = HashMap::new();
    if by_tier.len() > 1 {
        let tier1 = by_tier[1].clone();
        let (singletons, cassettes): (Vec<_>, Vec<_>) =
            tier1.into_iter().partition(|&ix| !class_contains_cassette(&pedigree[ix]));

        let pass_a: Vec<(NodeIndex, NodeOutcome)> = singletons
            .par_iter()
            .filter_map(|&ix| {
                evaluate_one(
                    ix,
                    pedigree,
                    &out,
                    chromatograms,
                    tolerance,
                    picker,
                    quality,
                    &empty_singletons,
                )
            })
            .collect();
        for (ix, outcome) in pass_a {
            out.insert(ix, outcome);
        }

        let singleton_rt = build_singleton_rt_map(&out, pedigree);
        let pass_b: Vec<(NodeIndex, NodeOutcome)> = cassettes
            .par_iter()
            .filter_map(|&ix| {
                evaluate_one(
                    ix,
                    pedigree,
                    &out,
                    chromatograms,
                    tolerance,
                    picker,
                    quality,
                    &singleton_rt,
                )
            })
            .collect();
        for (ix, outcome) in pass_b {
            out.insert(ix, outcome);
        }
    }

    // Tiers 2+: full singleton-RT map, augment thresholds for any class containing a
    // cassette BB. Compounds (tier N) inherit the chemical constraint transitively
    // through their structural parents' already-augmented chosen rts, so we don't
    // need to handle them specially.
    let singleton_rt = build_singleton_rt_map(&out, pedigree);
    for tier_nodes in by_tier.iter().skip(2) {
        let new_outcomes: Vec<(NodeIndex, NodeOutcome)> = tier_nodes
            .par_iter()
            .filter_map(|&ix| {
                evaluate_one(
                    ix,
                    pedigree,
                    &out,
                    chromatograms,
                    tolerance,
                    picker,
                    quality,
                    &singleton_rt,
                )
            })
            .collect();
        for (ix, outcome) in new_outcomes {
            out.insert(ix, outcome);
        }
    }

    out
}

/// True iff this node's class multiset contains a cassette BB (a BB whose name
/// contains the residue separator `-`).
fn class_contains_cassette(node: &crate::library::PedigreeNode) -> bool {
    match &node.kind {
        NodeKind::Class(c) => c.bbs.iter().any(|bb| bb.contains('-')),
        _ => false,
    }
}

/// The algorithm's chosen rt for this node, regardless of which pipeline path
/// produced it. For multi-rep nodes with a successful Bayesian step: `bayesian_pick`.
/// For multi-rep nodes where the Bayesian step found no candidates: `score_test_rt`.
/// For root and single-rep nodes: the rep's most-significant pick. Used internally
/// as the parent threshold when gating children.
fn chosen_rt(outcome: &NodeOutcome) -> Option<f64> {
    outcome
        .bayesian_pick
        .or(outcome.score_test_rt)
        .or_else(|| {
            outcome
                .initial_most_significant_picks
                .first()
                .copied()
                .flatten()
        })
}

/// Build {singleton_BB_name → chosen_rt} from the tier-1 outcome map. Only
/// non-cassette singletons (BBs without `-`) contribute, since these are the
/// per-residue chemical "anchors" we use to constrain cassette retention.
fn build_singleton_rt_map(
    outcomes: &HashMap<NodeIndex, NodeOutcome>,
    pedigree: &Pedigree,
) -> HashMap<String, f64> {
    let mut map = HashMap::new();
    for (&ix, outcome) in outcomes {
        if !outcome.passed || pedigree[ix].tier != 1 {
            continue;
        }
        if let NodeKind::Class(c) = &pedigree[ix].kind {
            if c.bbs.len() == 1 && !c.bbs[0].contains('-') {
                if let Some(rt) = chosen_rt(outcome) {
                    map.insert(c.bbs[0].clone(), rt);
                }
            }
        }
    }
    map
}

fn quality_rescue_for_node(pedigree: &Pedigree, ix: NodeIndex) -> bool {
    matches!(&pedigree[ix].kind, NodeKind::Class(_))
}

/// Evaluate a single non-root node. Returns `None` if any parent failed the gate.
fn evaluate_one(
    ix: NodeIndex,
    pedigree: &Pedigree,
    outcomes_so_far: &HashMap<NodeIndex, NodeOutcome>,
    chromatograms: &HashMap<ChromatogramKey, Chromatogram>,
    tolerance: f64,
    picker: &PeakPickerConfig,
    quality: PeakQualityParams,
    singleton_rt: &HashMap<String, f64>,
) -> Option<(NodeIndex, NodeOutcome)> {
    let parents: Vec<NodeIndex> = pedigree
        .neighbors_directed(ix, Direction::Incoming)
        .collect();
    if parents.is_empty() {
        return None; // non-root with no parents: malformed graph; skip
    }

    // Gate: every parent must have an outcome AND have passed.
    let mut threshold = f64::NEG_INFINITY;
    for &p in &parents {
        let parent_outcome = outcomes_so_far.get(&p)?;
        if !parent_outcome.passed {
            return None;
        }
        let prt = chosen_rt(parent_outcome)?;
        if prt > threshold {
            threshold = prt;
        }
    }

    // Augment threshold with chemical-monotonicity constraints from cassette BB
    // decomposition. For each cassette BB in this class's multiset, look up each of
    // its singleton-component RTs; the cassette as a whole must elute at least as
    // late as any of its individual residues. This is the same threshold mechanism
    // we already use, applied to the chemical (residue-decomposition) parents in
    // addition to the structural (one-BB-fewer-multiset) parents.
    if let NodeKind::Class(c) = &pedigree[ix].kind {
        for bb in &c.bbs {
            if bb.contains('-') {
                for component in bb.split('-') {
                    if let Some(&srt) = singleton_rt.get(component) {
                        if srt > threshold {
                            threshold = srt;
                        }
                    }
                }
            }
        }
    }

    // Gather each member's chromatogram (cloning for owned data we can hand to the
    // consensus routine; missing → empty placeholder, which the consensus then treats
    // as an excluded replicate). Peak-pick each, then call the consensus.
    let node = &pedigree[ix];
    let chroms_per_member: Vec<Chromatogram> = node
        .members
        .iter()
        .map(|m| chromatograms.get(&m.positions).cloned().unwrap_or_default())
        .collect();
    let allow_rescue = quality_rescue_for_node(pedigree, ix);
    let peaks_per_member: Vec<Vec<Peak>> = chroms_per_member
        .iter()
        .map(|(rt, intensity)| {
            pick_peaks_with_quality(rt, intensity, picker, quality, allow_rescue)
        })
        .collect();

    let ConsensusResult {
        passed,
        insufficient_data,
        initial_earliest_picks,
        initial_most_significant_picks,
        initial_democratic_picks,
        initial_democratic_position,
        score_test_rt,
        score_test_rt_se,
        score_test_p_value,
        per_rep_score_contribution,
        bayesian_pick,
        bayesian_pick_posterior,
        bayesian_pick_runner_up_posterior,
        bayesian_pick_threshold_margin,
        bayesian_refined_picks,
        bayesian_supporting_replicates,
        n_replicates,
        n_replicates_with_signal,
        replicates_with_no_signal,
    } = consensus(
        &chroms_per_member,
        &peaks_per_member,
        threshold,
        tolerance,
        picker.modern_alpha(),
    );

    let outcome = NodeOutcome {
        passed,
        insufficient_data,
        initial_earliest_picks,
        initial_most_significant_picks,
        initial_democratic_picks,
        initial_democratic_position,
        score_test_rt,
        score_test_rt_se,
        score_test_p_value,
        per_rep_score_contribution,
        bayesian_pick,
        bayesian_pick_posterior,
        bayesian_pick_runner_up_posterior,
        bayesian_pick_threshold_margin,
        bayesian_refined_picks,
        bayesian_supporting_replicates,
        n_replicates,
        n_replicates_with_signal,
        replicates_with_no_signal,
        effective_threshold: Some(threshold),
    };

    // For terminal nodes that legitimately have no peaks (passed=false), still return the
    // outcome so the diagnostic info is preserved. Only "gate failed" returns None.
    Some((ix, outcome))
}

fn pick_for(
    truncate_positions: &[String],
    chromatograms: &HashMap<ChromatogramKey, Chromatogram>,
    picker: &PeakPickerConfig,
    quality: PeakQualityParams,
    allow_null_truncation_rescue: bool,
) -> Vec<Peak> {
    match chromatograms.get(truncate_positions) {
        Some((rt, intensity)) => pick_peaks_with_quality(
            rt,
            intensity,
            picker,
            quality,
            allow_null_truncation_rescue,
        ),
        None => Vec::new(),
    }
}

/// Convenience: filter the outcome map to only passed nodes (i.e. the pruned tree).
pub fn passed_only(
    outcomes: &HashMap<NodeIndex, NodeOutcome>,
) -> HashMap<NodeIndex, NodeOutcome> {
    outcomes
        .iter()
        .filter(|(_, o)| o.passed)
        .map(|(k, v)| (*k, v.clone()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::library::{build_pedigree, NodeKind};

    fn s(x: &str) -> String {
        x.to_string()
    }

    /// Test convenience: an unrestricted library where every position admits all `bbs`.
    fn unrestricted(bbs: &[&str], n: usize) -> Vec<Vec<String>> {
        let owned: Vec<String> = bbs.iter().map(|b| b.to_string()).collect();
        vec![owned; n]
    }

    /// Make a triangular peak (height 10) at integer-rt position `at`, on a baseline of 0,
    /// with a chromatogram running from 0 to `n-1` integer rt steps.
    fn chrom_with_peak_at(at: f64, n: usize, height: f64) -> Chromatogram {
        let rt: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let intensity: Vec<f64> = rt
            .iter()
            .map(|&t| {
                let d = (t - at).abs();
                if d <= 1.0 { height * (1.0 - d) } else { 0.0 }
            })
            .collect();
        (rt, intensity)
    }

    fn flat_chrom(n: usize) -> Chromatogram {
        let rt: Vec<f64> = (0..n).map(|i| i as f64).collect();
        let intensity = vec![0.0; n];
        (rt, intensity)
    }

    /// Build a chromatograms-key from a slice of position-name string slices.
    fn key(parts: &[&str]) -> ChromatogramKey {
        parts.iter().map(|p| p.to_string()).collect()
    }

    #[test]
    fn root_picks_lowest_p_value_peak() {
        // 1-BB library, N=1: root + one tier-1 compound. Root has two peaks
        // sitting on a non-zero baseline (so the NB significance test produces
        // discriminable p-values). Under the n=1 most-significant criterion,
        // the lowest-p-value (most-significant) peak wins; the tall peak at
        // rt=15 has a more significant prominence over baseline than the
        // small peak at rt=5, so rt=15 wins.
        const BASELINE: f64 = 3.0;
        let g = build_pedigree(&unrestricted(&["A"], 1), "AgxNull");
        let mut chroms = HashMap::new();
        let rt: Vec<f64> = (0..41).map(|i| i as f64).collect();
        // Triangular peaks of width 1 sample at the apex.
        let intensity: Vec<f64> = rt.iter().map(|&t| {
            let mut y = BASELINE;
            // small peak at rt=5
            let d5 = (t - 5.0).abs();
            if d5 < 1e-9 { y += 6.0; } else if d5 < 1.01 { y += 3.0; }
            // tall peak at rt=15
            let d15 = (t - 15.0).abs();
            if d15 < 1e-9 { y += 60.0; } else if d15 < 1.01 { y += 30.0; }
            y
        }).collect();
        chroms.insert(key(&["AgxNull"]), (rt, intensity));
        chroms.insert(key(&["A"]), flat_chrom(41));

        let out = evaluate(&g, &chroms, 1.0, &PeakPickerConfig::modern(1.0), PeakQualityParams::default());
        let root = g.node_indices().find(|&ix| g[ix].tier == 0).unwrap();
        let r = &out[&root];
        assert!(r.passed);
        // Root's chosen rt lives in initial_most_significant_picks[0] (n=1 path).
        assert_eq!(r.initial_most_significant_picks, vec![Some(15.0)]);
        // Earliest pick is a separate criterion (smallest rt past floor) — should be rt=5.
        assert_eq!(r.initial_earliest_picks, vec![Some(5.0)]);
    }

    #[test]
    fn root_no_peaks_prunes_everything() {
        let g = build_pedigree(&unrestricted(&["A", "B"], 2), "AgxNull");
        let mut chroms = HashMap::new();
        // All chromatograms flat.
        for ix in g.node_indices() {
            for m in &g[ix].members {
                chroms.insert(m.positions.clone(), flat_chrom(20));
            }
        }
        let out = evaluate(&g, &chroms, 1.0, &PeakPickerConfig::modern(1.0), PeakQualityParams::default());
        let root = g.node_indices().find(|&ix| g[ix].tier == 0).unwrap();
        assert!(!out[&root].passed);
        // Every other node either absent (gate failed) or present with passed=false.
        for ix in g.node_indices() {
            if ix == root {
                continue;
            }
            assert!(out.get(&ix).map(|o| !o.passed).unwrap_or(true));
        }
    }

    #[test]
    fn failed_class_prunes_its_subtree() {
        // 2-BB N=2 library. Root passes at rt=5. Class {A} passes at rt=10, class {B} fails.
        // → tier-2 compounds AB, BA, BB should all be pruned (any parent is {B} which failed,
        //   except AA whose only parent is {A}).
        let bbs = vec![s("A"), s("B")];
        let g = build_pedigree(&vec![bbs.clone(); 2], "AgxNull");

        let mut chroms = HashMap::new();
        // Root: peak at rt=5
        chroms.insert(key(&["AgxNull", "AgxNull"]), chrom_with_peak_at(5.0, 30, 9.0));
        // {A} class members: both have a peak at rt=10
        chroms.insert(key(&["A", "AgxNull"]), chrom_with_peak_at(10.0, 30, 9.0));
        chroms.insert(key(&["AgxNull", "A"]), chrom_with_peak_at(10.0, 30, 9.0));
        // {B} class members: flat (no peaks past root rt=5)
        chroms.insert(key(&["B", "AgxNull"]), flat_chrom(30));
        chroms.insert(key(&["AgxNull", "B"]), flat_chrom(30));
        // Tier-2 compounds: AA passes at rt=15, others have peaks but their parent {B} fails
        chroms.insert(key(&["A", "A"]), chrom_with_peak_at(15.0, 30, 9.0));
        chroms.insert(key(&["A", "B"]), chrom_with_peak_at(15.0, 30, 9.0));
        chroms.insert(key(&["B", "A"]), chrom_with_peak_at(15.0, 30, 9.0));
        chroms.insert(key(&["B", "B"]), chrom_with_peak_at(15.0, 30, 9.0));

        let out = evaluate(&g, &chroms, 2.0, &PeakPickerConfig::modern(1.0), PeakQualityParams::default());

        // Helpers to find nodes by class key or compound positions.
        let class_node = |key: &[&str]| -> NodeIndex {
            g.node_indices()
                .find(|&ix| matches!(&g[ix].kind, NodeKind::Class(c)
                    if c.bbs == key.iter().map(|s| s.to_string()).collect::<Vec<_>>()))
                .unwrap()
        };
        let compound_node = |positions: &[&str]| -> NodeIndex {
            g.node_indices()
                .find(|&ix| matches!(&g[ix].kind, NodeKind::Compound(t)
                    if t.positions == positions.iter().map(|s| s.to_string()).collect::<Vec<_>>()))
                .unwrap()
        };

        let root = class_node(&[]);
        let a = class_node(&["A"]);
        let b = class_node(&["B"]);
        let aa = compound_node(&["A", "A"]);
        let ab = compound_node(&["A", "B"]);
        let ba = compound_node(&["B", "A"]);
        let bb = compound_node(&["B", "B"]);

        assert!(out[&root].passed);
        assert!(out[&a].passed, "class {{A}} should pass");
        assert!(!out[&b].passed, "class {{B}} should fail");

        // AA's only tier-1 parent is {A} (passed) → AA evaluated, passes.
        assert!(out.contains_key(&aa));
        assert!(out[&aa].passed);

        // AB / BA both have parents {A} and {B}; {B} failed → gate fails → not in map.
        assert!(!out.contains_key(&ab), "AB should be pruned (parent {{B}} failed)");
        assert!(!out.contains_key(&ba), "BA should be pruned (parent {{B}} failed)");
        // BB's only parent is {B} (failed) → pruned.
        assert!(!out.contains_key(&bb), "BB should be pruned (parent {{B}} failed)");
    }

    #[test]
    fn threshold_is_max_of_parent_rts() {
        // 2-BB N=2 library. Root rt=5. {A} passes at rt=10, {B} passes at rt=20.
        // Compound AB has parents {A} (rt=10) and {B} (rt=20) → threshold=20.
        // AB's chromatograms must have a peak past 20 to pass.
        let g = build_pedigree(&unrestricted(&["A", "B"], 2), "AgxNull");

        let mut chroms = HashMap::new();
        chroms.insert(key(&["AgxNull", "AgxNull"]), chrom_with_peak_at(5.0, 40, 9.0));
        chroms.insert(key(&["A", "AgxNull"]), chrom_with_peak_at(10.0, 40, 9.0));
        chroms.insert(key(&["AgxNull", "A"]), chrom_with_peak_at(10.0, 40, 9.0));
        chroms.insert(key(&["B", "AgxNull"]), chrom_with_peak_at(20.0, 40, 9.0));
        chroms.insert(key(&["AgxNull", "B"]), chrom_with_peak_at(20.0, 40, 9.0));
        // AB / BA have a peak at rt=15 (past {A}'s 10 but NOT past {B}'s 20) → must fail.
        chroms.insert(key(&["A", "B"]), chrom_with_peak_at(15.0, 40, 9.0));
        chroms.insert(key(&["B", "A"]), chrom_with_peak_at(15.0, 40, 9.0));
        // AA has parents only {A}; rt=15 is past 10 → passes.
        chroms.insert(key(&["A", "A"]), chrom_with_peak_at(15.0, 40, 9.0));
        // BB has parents only {B}; rt=25 is past 20 → passes.
        chroms.insert(key(&["B", "B"]), chrom_with_peak_at(25.0, 40, 9.0));

        let out = evaluate(&g, &chroms, 2.0, &PeakPickerConfig::modern(1.0), PeakQualityParams::default());

        let compound_node = |positions: &[&str]| -> NodeIndex {
            g.node_indices()
                .find(|&ix| matches!(&g[ix].kind, NodeKind::Compound(t)
                    if t.positions == positions.iter().map(|s| s.to_string()).collect::<Vec<_>>()))
                .unwrap()
        };
        let ab = compound_node(&["A", "B"]);
        let ba = compound_node(&["B", "A"]);
        let aa = compound_node(&["A", "A"]);
        let bb = compound_node(&["B", "B"]);

        assert!(out[&aa].passed);
        assert!(out[&bb].passed);
        assert!(!out[&ab].passed, "AB peak at 15 < threshold 20 (max of parents)");
        assert!(!out[&ba].passed);
    }

    #[test]
    fn passed_only_filters_correctly() {
        let g = build_pedigree(&unrestricted(&["A"], 1), "AgxNull");
        let mut chroms = HashMap::new();
        chroms.insert(key(&["AgxNull"]), chrom_with_peak_at(5.0, 30, 9.0));
        chroms.insert(key(&["A"]), flat_chrom(30)); // fails
        let out = evaluate(&g, &chroms, 1.0, &PeakPickerConfig::modern(1.0), PeakQualityParams::default());
        let pruned = passed_only(&out);
        assert_eq!(pruned.len(), 1); // just root
    }
}
