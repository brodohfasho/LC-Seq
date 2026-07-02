//! Validation against a small slice of the real DEL-0044 (linear) dataset.
//!
//! Fixture is produced by `scripts/extract_real_fixture.py`. Run with
//! `cargo test --test real_data -- --nocapture` to see the per-node outcomes printed.

use lcseq::evaluate::{evaluate, Chromatogram, ChromatogramKey, NodeOutcome};
use lcseq::library::{build_pedigree, NodeKind};
use lcseq::peaks::{find_peaks, PeakPickerConfig, PeakQualityParams};
use petgraph::graph::NodeIndex;
use serde_json::Value;
use std::collections::HashMap;
use std::fs;

const FIXTURE: &str = "tests/fixtures/real_sample.json";
const TOLERANCE_S: f64 = 30.0;
const ALPHA: f64 = 1e-3;

fn load_fixture() -> (Vec<String>, usize, String, HashMap<ChromatogramKey, Chromatogram>) {
    let raw = fs::read_to_string(FIXTURE).expect("missing fixture; run scripts/extract_real_fixture.py");
    let v: Value = serde_json::from_str(&raw).unwrap();

    let bbs: Vec<String> = v["building_blocks"]
        .as_array().unwrap()
        .iter().map(|s| s.as_str().unwrap().to_string()).collect();
    let n = v["n_positions"].as_u64().unwrap() as usize;
    let null_token = v["null_token"].as_str().unwrap().to_string();

    let mut chroms: HashMap<ChromatogramKey, Chromatogram> = HashMap::new();
    for (name, c) in v["chromatograms"].as_object().unwrap() {
        let rt: Vec<f64> = c["rt"].as_array().unwrap().iter()
            .map(|x| x.as_f64().unwrap()).collect();
        let scaled: Vec<f64> = c["scaled"].as_array().unwrap().iter()
            .map(|x| x.as_i64().unwrap() as f64).collect();
        // Fixture is keyed by the dash-joined Common_Name; for DNvl/DPhe that's unambiguous.
        let key: ChromatogramKey = name.split('-').map(String::from).collect();
        chroms.insert(key, (rt, scaled));
    }
    (bbs, n, null_token, chroms)
}

fn print_picker_results(chroms: &HashMap<ChromatogramKey, Chromatogram>) {
    let mut names: Vec<&ChromatogramKey> = chroms.keys().collect();
    names.sort();
    eprintln!("\n=== peak picker on real chromatograms (scaled channel, alpha={}) ===", ALPHA);
    for name in names {
        let (rt, intensity) = &chroms[name];
        let peaks = find_peaks(rt, intensity, ALPHA);
        eprintln!(
            "  {:<35}  n_pts={:>3}, n_peaks={:>2}, peaks=[{}]",
            name.join("-"),
            rt.len(),
            peaks.len(),
            peaks.iter()
                .map(|p| format!("rt={:.0} I={:.0} prom={:.0}", p.rt, p.intensity, p.prominence))
                .collect::<Vec<_>>()
                .join(", ")
        );
    }
}

fn print_eval_results(
    pedigree: &lcseq::library::Pedigree,
    outcomes: &HashMap<NodeIndex, NodeOutcome>,
) {
    eprintln!("\n=== evaluator outcomes ===");
    let mut by_tier: Vec<Vec<NodeIndex>> = Vec::new();
    for ix in pedigree.node_indices() {
        let t = pedigree[ix].tier;
        if by_tier.len() <= t { by_tier.resize(t + 1, Vec::new()); }
        by_tier[t].push(ix);
    }
    for (tier, nodes) in by_tier.iter().enumerate() {
        eprintln!("  tier {}:", tier);
        for &ix in nodes {
            let label = match &pedigree[ix].kind {
                NodeKind::Class(c) if c.is_root() => "ROOT".to_string(),
                NodeKind::Class(c) => format!("class {{{}}}", c.bbs.join(",")),
                NodeKind::Compound(t) => format!("compound {}", t.display()),
            };
            match outcomes.get(&ix) {
                None => eprintln!("    {:<45}  PRUNED (gate)", label),
                Some(o) => {
                    // Show the algorithm's chosen rt regardless of pipeline path.
                    let chosen = o
                        .bayesian_pick
                        .or(o.score_test_rt)
                        .or_else(|| {
                            o.initial_most_significant_picks.first().copied().flatten()
                        });
                    eprintln!(
                        "    {:<45}  passed={:<5} chosen_rt={:?}  refined={:?}",
                        label, o.passed, chosen, o.bayesian_refined_picks
                    )
                }
            }
        }
    }
}

#[test]
fn picker_finds_peaks_in_every_chromatogram() {
    let (_bbs, _n, _nt, chroms) = load_fixture();
    print_picker_results(&chroms);
    // Every chromatogram in our fixture has visible signal — the picker should find ≥1 peak.
    for (name, (rt, intensity)) in &chroms {
        let peaks = find_peaks(rt, intensity, ALPHA);
        assert!(!peaks.is_empty(), "no peaks found in {} (max intensity = {:?})",
            name.join("-"), intensity.iter().cloned().fold(f64::MIN, f64::max));
        // Sanity: every picked peak must lie within the chromatogram's rt range.
        for p in &peaks {
            assert!(p.rt >= rt[0] && p.rt <= rt[rt.len() - 1]);
            assert!(p.intensity > 0.0);
        }
    }
}

#[test]
fn evaluate_real_fixture() {
    let (bbs, n, null_token, chroms) = load_fixture();
    // Real-data fixture is a contrived sub-library where every BB appears at every position.
    let g = build_pedigree(&vec![bbs.clone(); n], &null_token);
    eprintln!(
        "\nPedigree built: |BBs|={}, N={}, nodes={}",
        bbs.len(),
        n,
        g.node_count()
    );

    let outcomes = evaluate(
        &g,
        &chroms,
        TOLERANCE_S,
        &PeakPickerConfig::modern(ALPHA),
        PeakQualityParams::default(),
    );
    print_eval_results(&g, &outcomes);

    // Root must have a peak — its chromatogram is non-trivial.
    let root = g.node_indices().find(|&ix| g[ix].tier == 0).unwrap();
    let root_outcome = &outcomes[&root];
    assert!(root_outcome.passed, "root failed unexpectedly: {:?}", root_outcome);
    // Root is the n=1 path: chosen rt lives in initial_most_significant_picks[0].
    let root_rt = root_outcome.initial_most_significant_picks[0].unwrap();
    assert!(root_rt > 0.0);

    // Every passing outcome's chosen rt is >= the root rt: descendants must be at
    // least as retained as the root threshold. Helper: prefer bayesian_pick, then
    // score_test_rt, then n=1 single pick.
    let chosen_rt = |o: &NodeOutcome| -> Option<f64> {
        o.bayesian_pick
            .or(o.score_test_rt)
            .or_else(|| o.initial_most_significant_picks.first().copied().flatten())
    };
    for (&ix, o) in &outcomes {
        if ix == root || !o.passed { continue; }
        let rt = chosen_rt(o).unwrap();
        assert!(
            rt >= root_rt,
            "node {} has chosen rt {} < root_rt {}",
            g[ix].id(), rt, root_rt
        );
    }
}
