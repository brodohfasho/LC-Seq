//! Multi-replicate Negative-Binomial peak detection model for class consensus.
//!
//! For a class with `n` replicate chromatograms, fit the joint model
//!
//! ```text
//! Yᵢⱼ ~ NB(μⱼ + αⱼ · φ(tᵢ; p*, σ), r)
//! ```
//!
//! across all reps simultaneously, with shared peak position `p*`, per-rep amplitudes
//! `αⱼ ≥ 0`, shared Gaussian peak width `σ`, and NB dispersion `r`. The MLE/score-test
//! estimate of `p*` IS the consensus rt: it explicitly weights both reproducibility
//! (via the shared `p*`) and statistical evidence strength (via the joint likelihood),
//! without introducing magnitude-vs-correctness or count-vs-significance heuristics.
//!
//! Pipeline:
//! 1. Active/excluded partition: reps with zero NB-significant peaks anywhere are
//!    excluded as failed-sequencing runs (don't count toward the score-test
//!    denominator, don't contribute to the model).
//! 2. Per-rep baselines: sigma-clipped (μⱼ, rⱼ) from `peaks::estimate_baseline`.
//! 3. `peak_model::fit_peak_model` runs the score test on a fine grid of candidate
//!    `p*` over [`threshold + tolerance`, max rt]. The score statistic
//!    `U(p*) = Σⱼ Σᵢ φ · (Y − μ) / Var(Y)` is asymptotically equivalent to the LRT
//!    but evaluates analytically — no inner amplitude optimisation.
//! 4. Pass iff: (a) the score-test p-value < α, AND (b) a strict majority of active
//!    reps contribute positively to `U(p̂*)` (i.e. they each contain signal at the
//!    consensus position above their baselines).
//! 5. `consensus_rt = p̂*` (score-test MLE of the shared peak position, sub-grid
//!    refined via parabolic interpolation around the best grid point) — serves as
//!    the prior center for the Bayesian meta-pick.
//! 6. `meta_pick` = MAP candidate combining the score-test prior with per-rep votes
//!    (earliest + statistical + democratic). This is the algorithm's chosen rt.
//! 7. `refined_picks` = per-rep NB-significant peak nearest `meta_pick` within ±FWHM.

use crate::evaluate::peak_model::{fit_peak_model, score_at};
use crate::evaluate::Chromatogram;
use crate::peaks::{estimate_baseline, Baseline, Peak};

/// Full-width-at-half-max of a Gaussian, in units of σ. FWHM = 2√(2 ln 2)·σ.
/// With σ = `tolerance`, the consensus-match window is ±FWHM·tolerance.
const FWHM_OVER_SIGMA: f64 = 2.354_820_045_030_949_5;

#[derive(Debug, Clone, PartialEq)]
pub struct ConsensusResult {
    /// True iff the algorithm's gate passed for this eclass. Multi-rep (n ≥ 2):
    /// score-test p < α AND a strict majority of reps-with-signal contribute
    /// positively to U(p̂*). Single-rep (n = 1): the rep's most-significant pick
    /// past vote_floor exists.
    pub passed: bool,
    /// True iff every replicate's chromatogram is statistically empty — the picker
    /// found zero NB-significant peaks anywhere in any rep's rt range. Sequencing
    /// failure, NOT a synthesis failure. When true, `passed` is false; nodes in this
    /// state should be excluded from pass-rate denominators.
    pub insufficient_data: bool,

    // === Stage 1: per-rep initial picks ===
    // Each is a Vec<Option<f64>> of length n_replicates, indexed by ORIGINAL replicate
    // index. `None` for any rep that was a sequencing failure (zero NB-sig peaks
    // anywhere) OR had no qualifying peak under the criterion.

    /// Per-rep earliest-rt NB-significant peak strictly past `threshold + tolerance`.
    pub initial_earliest_picks: Vec<Option<f64>>,
    /// Per-rep lowest-p-value NB-significant peak strictly past `threshold + tolerance`.
    pub initial_most_significant_picks: Vec<Option<f64>>,
    /// Per-rep NB-significant peak nearest the broadest-agreement position
    /// (`initial_democratic_position`) within ±tolerance.
    pub initial_democratic_picks: Vec<Option<f64>>,

    // === Stage 1: eclass-level aggregates (cross-rep, scalars) ===

    /// Eclass-level "broadest-agreement position" — the rt where the maximum number
    /// of reps-with-signal have a peak within ±tolerance. Stage-1 cross-rep aggregate;
    /// the cluster center used to compute `initial_democratic_picks`. None when no
    /// rep has any peak past `threshold + tolerance`.
    pub initial_democratic_position: Option<f64>,
    /// Score-test MLE of the shared peak position p̂* (sub-grid refined). Eclass-level
    /// stage-1 output; serves as the prior center in the Bayesian inference. None
    /// for n_replicates_with_signal ≤ 1 (no cross-rep score test possible).
    pub score_test_rt: Option<f64>,
    /// Standard error of `score_test_rt` from the score test's Fisher information
    /// (`SE = 1/√I(p̂*)`). Asymptotic uncertainty on the score-test MLE; surfaced
    /// as a diagnostic. NOT used as the Bayesian prior width — the Bayesian step
    /// evaluates the score-test likelihood at each candidate via `score_at`, which
    /// captures the full per-position detection landscape (not just the local SE
    /// approximation around the MLE). None for n_replicates_with_signal ≤ 1.
    pub score_test_rt_se: Option<f64>,
    /// One-sided upper-tail p-value of the score test under the joint NB null. None
    /// for n_replicates_with_signal ≤ 1.
    pub score_test_p_value: Option<f64>,
    /// Per-rep contribution to U(p̂*) — outer Option for "score test ran" (None for
    /// n ≤ 1 / root); inner Option per rep (None for sequencing-failure reps, Some
    /// for reps-with-signal). Positive contributions support the consensus; near-zero
    /// or negative contributions don't. Indexed by ORIGINAL replicate index.
    pub per_rep_score_contribution: Option<Vec<Option<f64>>>,

    // === Stage 2: Bayesian inference outputs (eclass-level) ===

    /// MAP candidate peak from the Bayesian inference combining the score-test prior
    /// with per-rep votes (initial earliest + most-significant + democratic). The
    /// algorithm's chosen rt for n_replicates_with_signal ≥ 2 nodes. None for n ≤ 1
    /// (no Bayesian step ran) or when there are no candidates past vote_floor.
    pub bayesian_pick: Option<f64>,
    /// Posterior probability of `bayesian_pick` (range [0, 1]). None when
    /// `bayesian_pick` is None.
    pub bayesian_pick_posterior: Option<f64>,
    /// Posterior probability of the second-best candidate. A small gap between this
    /// and `bayesian_pick_posterior` indicates genuine ambiguity. None when fewer
    /// than 2 candidates exist or when `bayesian_pick` is None.
    pub bayesian_pick_runner_up_posterior: Option<f64>,
    /// Margin of `bayesian_pick` past the parent threshold, in units of `tolerance`:
    /// `(bayesian_pick - threshold) / tolerance`. Values near 1.0 indicate the
    /// boundary-of-parent-exclusion regime (a known borderline case). None when
    /// `bayesian_pick` is None.
    pub bayesian_pick_threshold_margin: Option<f64>,

    // === Stage 2: per-rep refined picks ===

    /// Per-rep manifestation of `bayesian_pick`: for each rep, the rt of the highest-
    /// intensity sample on the rep's chromatogram within ±FWHM of `bayesian_pick`.
    /// Always populated for reps-with-signal when `bayesian_pick` is `Some` (every
    /// chromatogram has some intensity in the window). Computed from raw chromatograms,
    /// NOT restricted to NB-significant peaks — so reps where the per-rep picker
    /// missed the peak still get a meaningful per-rep manifestation. Indexed by
    /// ORIGINAL replicate index; `None` for sequencing-failure reps or when
    /// `bayesian_pick` is `None`.
    pub bayesian_refined_picks: Vec<Option<f64>>,
    /// Indices of replicates that have an NB-significant peak within ±FWHM of
    /// `bayesian_pick`. Subset of reps-with-signal. The "support indicator" — tells
    /// the consumer which reps individually corroborate the chosen answer (vs reps
    /// whose `bayesian_refined_picks[i]` is just the raw-chromatogram argmax in the
    /// window). Empty when `bayesian_pick` is `None`.
    pub bayesian_supporting_replicates: Vec<usize>,

    // === Replicate accounting ===

    /// Total number of replicates (members of the equivalence class).
    pub n_replicates: usize,
    /// Number of replicates whose chromatogram contained at least one NB-significant
    /// peak (anywhere — past or before threshold). Reps with zero detectable signal
    /// are sequencing failures and contribute to no aggregation.
    pub n_replicates_with_signal: usize,
    /// Indices of replicates excluded as sequencing failures (zero NB-significant
    /// peaks anywhere in their chromatogram).
    pub replicates_with_no_signal: Vec<usize>,
}

/// Output of the Bayesian inference combining the score-test prior with per-rep votes.
struct BayesianInferenceResult {
    /// MAP candidate rt.
    pick: f64,
    /// Posterior probability of the MAP candidate.
    posterior: f64,
    /// Posterior probability of the second-best candidate, or None if < 2 candidates.
    runner_up_posterior: Option<f64>,
}

/// Compute the Bayesian inference over candidate peaks.
///
/// **Prior**: at each candidate k, the joint NB score-test likelihood ratio for
/// "peak at k" vs "no peak at k" — `log_prior(k) = max(z(k), 0)² / 2` where
/// `z(k) = U(k)/√I(k)` is the score-test z-statistic at k, computed by `score_at`
/// from the active reps' chromatograms. Asymptotically, this IS the joint NB log-
/// likelihood ratio; using it directly (rather than a Gaussian-on-MLE asymptotic
/// approximation) means each candidate is weighted by how strongly the joint cross-
/// rep detection actually supports a peak there. The `max(z, 0)` floor distinguishes
/// peak-detection (z > 0) from anti-peak / dip detection (z < 0); only positive
/// detection contributes prior weight.
///
/// **Vote model (evidence)**: each per-rep criterion (earliest, most-significant,
/// democratic) is an independent observation of the eclass peak position. NO dedup:
/// a rep where all three criteria converge on the same rt contributes three
/// cooperative votes there — stronger evidence than a rep where criteria split.
/// Reps with no signal contribute nothing.
///
/// **Candidate set**: union of every per-rep vote position plus `score_test_rt`
/// (so the joint-NB MLE is always considered as a candidate). Deduplicated to
/// distinct positions within `sigma_obs` for posterior evaluation.
///
/// **Posterior at candidate k**:
/// ```text
/// log_posterior(k) = max(z(k), 0)² / 2
///                  + Σⱼ Σ_{v ∈ rep_j_votes} (-½ (v - k)² / σ_obs²)
/// ```
///
/// Returns `Some(BayesianInferenceResult)` or `None` if there are no candidates.
fn bayesian_inference(
    active_chroms: &[Chromatogram],
    active_baselines: &[Baseline],
    sigma: f64,
    earliest: &[Option<f64>],
    most_significant: &[Option<f64>],
    democratic: &[Option<f64>],
    vote_floor: f64,
    score_test_rt: f64,
    sigma_obs: f64,
) -> Option<BayesianInferenceResult> {
    // Per-rep vote sets: union of (earliest, most-significant, democratic) for each
    // rep, NOT deduplicated. Each criterion is an independent observation; voting
    // power scales with how many criteria converge for a rep AND with cross-rep
    // cooperation at a position. Empty vote sets correspond to reps with no signal
    // past vote_floor under any criterion.
    let n_reps = earliest.len();
    let votes_per_rep: Vec<Vec<f64>> = (0..n_reps)
        .map(|j| {
            [earliest, most_significant, democratic]
                .iter()
                .filter_map(|arr| arr.get(j).copied().flatten())
                .collect()
        })
        .collect();

    // Candidate positions: union of every per-rep vote (not deduplicated yet) plus
    // score_test_rt (the joint-NB MLE). Dedup distinct positions within sigma_obs
    // so we evaluate the posterior once per chemical peak — this dedup is over
    // CANDIDATES (positions), not VOTES (observations); the votes themselves
    // remain undeduplicated above.
    let mut candidates: Vec<f64> = votes_per_rep.iter().flatten().copied().collect();
    if score_test_rt > vote_floor {
        candidates.push(score_test_rt);
    }
    if candidates.is_empty() {
        return None;
    }
    candidates.sort_by(|a, b| a.partial_cmp(b).unwrap());
    candidates.dedup_by(|a, b| (*a - *b).abs() < sigma_obs);

    // Posterior ∝ joint-NB-prior × per-rep-vote evidence at each candidate.
    //   prior(k)    = exp(z(k)²/2)  — joint NB likelihood ratio at k via score_at
    //   evidence(k) = Σ over all votes of Gaussian log-likelihood (independent obs)
    let inv_var_obs = 1.0 / (sigma_obs * sigma_obs);
    let mut log_posteriors: Vec<f64> = candidates
        .iter()
        .map(|&k| {
            // Joint NB score-test detection strength at k.
            let (u, info, _) = score_at(active_chroms, active_baselines, sigma, k);
            let z = if info > 0.0 { u / info.sqrt() } else { 0.0 };
            let z_pos = z.max(0.0);
            let log_prior = 0.5 * z_pos * z_pos;
            // Per-rep vote evidence: each vote is an independent observation.
            let log_evidence: f64 = votes_per_rep
                .iter()
                .flat_map(|votes| votes.iter())
                .map(|&v| -0.5 * (v - k).powi(2) * inv_var_obs)
                .sum();
            log_prior + log_evidence
        })
        .collect();

    // Softmax-normalize to get probabilities.
    let max_log = log_posteriors.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let mut sum = 0.0;
    for lp in log_posteriors.iter_mut() {
        *lp = (*lp - max_log).exp();
        sum += *lp;
    }
    if sum <= 0.0 {
        return None;
    }
    // Find MAP and runner-up.
    let mut best_idx = 0;
    let mut second_idx: Option<usize> = None;
    for i in 1..log_posteriors.len() {
        if log_posteriors[i] > log_posteriors[best_idx] {
            second_idx = Some(best_idx);
            best_idx = i;
        } else if let Some(s) = second_idx {
            if log_posteriors[i] > log_posteriors[s] {
                second_idx = Some(i);
            }
        } else {
            second_idx = Some(i);
        }
    }
    Some(BayesianInferenceResult {
        pick: candidates[best_idx],
        posterior: log_posteriors[best_idx] / sum,
        runner_up_posterior: second_idx.map(|s| log_posteriors[s] / sum),
    })
}

/// Run the multi-replicate score-test consensus on one class's replicates.
///
/// `chromatograms_per_replicate` and `peaks_per_replicate` must align by index.
/// `threshold` is the parent's consensus rt; per-rep candidate peaks must lie strictly
/// past `threshold + tolerance`. `tolerance` is the Gaussian peak-shape σ used by the
/// score test and the ± window for the per-rep democratic pick. `alpha` is the
/// per-peak FDR threshold for the score-test gate.
pub fn consensus(
    chromatograms_per_replicate: &[Chromatogram],
    peaks_per_replicate: &[Vec<Peak>],
    threshold: f64,
    tolerance: f64,
    alpha: f64,
) -> ConsensusResult {
    assert_eq!(
        chromatograms_per_replicate.len(),
        peaks_per_replicate.len(),
        "chromatograms and peaks must align by index"
    );

    let n_total = peaks_per_replicate.len();

    // 0. Partition reps into "with signal" vs "no signal" (sequencing failures).
    //    A rep with zero NB-significant peaks anywhere is a sequencing failure —
    //    not data. It contributes to no aggregation: not the score-test denominator,
    //    not the Bayesian likelihood, not the democratic position. It is recorded
    //    in `replicates_with_no_signal` for transparency.
    let active_indices: Vec<usize> = (0..n_total)
        .filter(|&i| !peaks_per_replicate[i].is_empty())
        .collect();
    let replicates_with_no_signal: Vec<usize> = (0..n_total)
        .filter(|&i| peaks_per_replicate[i].is_empty())
        .collect();

    let n = active_indices.len();
    // Vote floor is offset from the parent threshold by ONE FWHM of the score-test
    // peak-shape kernel (σ = tolerance). FWHM = 2√(2 ln 2)·σ ≈ 2.3548·σ is the
    // chromatographic resolution criterion (Rs = 1.0, half-overlapping peaks): a
    // child peak must be at least one FWHM past the parent's apex to be
    // chromatographically distinguishable from the parent's right downslope.
    // Offsets smaller than this admit "peaks" that are actually still on the
    // parent peak's body, biasing the score test toward the parent's tail.
    let vote_floor = threshold + FWHM_OVER_SIGMA * tolerance;

    // === Stage 1: per-rep initial picks ===
    // One pick per rep per criterion, indexed by ORIGINAL replicate index.
    // None for sequencing-failure reps and reps with no qualifying peak.
    let initial_most_significant_picks: Vec<Option<f64>> = (0..n_total)
        .map(|i| {
            if peaks_per_replicate[i].is_empty() {
                None
            } else {
                peaks_per_replicate[i]
                    .iter()
                    .filter(|p| p.rt > vote_floor)
                    .min_by(|a, b| a.p_value.partial_cmp(&b.p_value).unwrap())
                    .map(|p| p.rt)
            }
        })
        .collect();
    let initial_earliest_picks: Vec<Option<f64>> = (0..n_total)
        .map(|i| {
            if peaks_per_replicate[i].is_empty() {
                None
            } else {
                peaks_per_replicate[i]
                    .iter()
                    .filter(|p| p.rt > vote_floor)
                    .min_by(|a, b| a.rt.partial_cmp(&b.rt).unwrap())
                    .map(|p| p.rt)
            }
        })
        .collect();
    // Democratic: per-rep peak nearest the broadest-agreement cluster center.
    // The center itself is the eclass-level `initial_democratic_position` (Stage 1
    // cross-rep aggregate). Each rep then takes its nearest peak within ±tolerance.
    let active_peaks_past_floor: Vec<Vec<f64>> = (0..n_total)
        .map(|i| {
            peaks_per_replicate[i]
                .iter()
                .filter(|p| p.rt > vote_floor)
                .map(|p| p.rt)
                .collect()
        })
        .collect();
    let (initial_democratic_position, initial_democratic_picks): (Option<f64>, Vec<Option<f64>>) =
        match best_supported_position(&active_peaks_past_floor, tolerance) {
            Some((center, _)) => (
                Some(center),
                active_peaks_past_floor
                    .iter()
                    .map(|peaks| nearest_within_window(peaks, center, tolerance))
                    .collect(),
            ),
            None => (None, vec![None; n_total]),
        };

    // n = 0: every rep was a sequencing failure (or there are no reps). INSUFFICIENT
    // DATA — the eclass cannot be assessed.
    if n == 0 {
        let insufficient = n_total > 0;
        return ConsensusResult {
            passed: false,
            insufficient_data: insufficient,
            initial_earliest_picks,
            initial_most_significant_picks,
            initial_democratic_picks,
            initial_democratic_position,
            score_test_rt: None,
            score_test_rt_se: None,
            score_test_p_value: None,
            per_rep_score_contribution: None,
            bayesian_pick: None,
            bayesian_pick_posterior: None,
            bayesian_pick_runner_up_posterior: None,
            bayesian_pick_threshold_margin: None,
            bayesian_refined_picks: vec![None; n_total],
            bayesian_supporting_replicates: Vec::new(),
            n_replicates: n_total,
            n_replicates_with_signal: 0,
            replicates_with_no_signal,
        };
    }

    // n = 1: single rep with signal. No cross-rep score test, no Bayesian inference.
    // The eclass call IS just the rep's most-significant pick past vote_floor;
    // pass iff that pick exists. No Bayesian step → no refined picks.
    if n == 1 {
        let only = active_indices[0];
        let passed = initial_most_significant_picks[only].is_some();
        return ConsensusResult {
            passed,
            insufficient_data: false,
            initial_earliest_picks,
            initial_most_significant_picks,
            initial_democratic_picks,
            initial_democratic_position,
            score_test_rt: None,
            score_test_rt_se: None,
            score_test_p_value: None,
            per_rep_score_contribution: None,
            bayesian_pick: None,
            bayesian_pick_posterior: None,
            bayesian_pick_runner_up_posterior: None,
            bayesian_pick_threshold_margin: None,
            bayesian_refined_picks: vec![None; n_total],
            bayesian_supporting_replicates: Vec::new(),
            n_replicates: n_total,
            n_replicates_with_signal: n,
            replicates_with_no_signal,
        };
    }
    let majority = n / 2 + 1;

    // Active reps' chromatograms + per-rep baselines for the NB peak model.
    let active_chroms: Vec<Chromatogram> = active_indices
        .iter()
        .map(|&i| chromatograms_per_replicate[i].clone())
        .collect();
    let active_baselines: Vec<Baseline> = active_chroms
        .iter()
        .map(|(_, intensity)| estimate_baseline(intensity))
        .collect();

    // Search range for p*: from the parent-exclusion zone's far edge (vote_floor) to
    // the maximum rt observed in any active replicate.
    let p_max = active_chroms
        .iter()
        .filter_map(|(rt, _)| rt.last().copied())
        .fold(f64::NEG_INFINITY, f64::max);
    if p_max <= vote_floor {
        // Reps-with-signal exist (so it's not INSUFFICIENT_DATA), but their entire rt
        // range sits at/before the parent-exclusion zone — there's no rt window to
        // search. Genuine synthesis-style FAIL.
        return ConsensusResult {
            passed: false,
            insufficient_data: false,
            initial_earliest_picks,
            initial_most_significant_picks,
            initial_democratic_picks,
            initial_democratic_position,
            score_test_rt: None,
            score_test_rt_se: None,
            score_test_p_value: None,
            per_rep_score_contribution: None,
            bayesian_pick: None,
            bayesian_pick_posterior: None,
            bayesian_pick_runner_up_posterior: None,
            bayesian_pick_threshold_margin: None,
            bayesian_refined_picks: vec![None; n_total],
            bayesian_supporting_replicates: Vec::new(),
            n_replicates: n_total,
            n_replicates_with_signal: n,
            replicates_with_no_signal,
        };
    }

    // Coarse grid step: half the typical sample spacing of the data, capped at 0.1.
    let grid_step = active_chroms
        .iter()
        .filter_map(|(rt, _)| {
            if rt.len() >= 2 {
                Some((rt[1] - rt[0]).abs() * 0.5)
            } else {
                None
            }
        })
        .fold(f64::INFINITY, f64::min)
        .min(0.1)
        .max(0.01);

    // Fit the joint multi-replicate peak model. The Gaussian peak-shape sigma is set
    // to `tolerance` — i.e. the user's "how far apart can the same peak be across
    // reps" specification IS the natural width of the kernel. Returns the score-test
    // estimate of the shared peak position p*, the score statistic, p-value, and
    // per-rep contributions.
    let fit = fit_peak_model(
        &active_chroms,
        &active_baselines,
        tolerance,
        vote_floor,
        p_max,
        grid_step,
    );
    let Some(fit) = fit else {
        return ConsensusResult {
            passed: false,
            insufficient_data: false,
            initial_earliest_picks,
            initial_most_significant_picks,
            initial_democratic_picks,
            initial_democratic_position,
            score_test_rt: None,
            score_test_rt_se: None,
            score_test_p_value: None,
            per_rep_score_contribution: None,
            bayesian_pick: None,
            bayesian_pick_posterior: None,
            bayesian_pick_runner_up_posterior: None,
            bayesian_pick_threshold_margin: None,
            bayesian_refined_picks: vec![None; n_total],
            bayesian_supporting_replicates: Vec::new(),
            n_replicates: n_total,
            n_replicates_with_signal: n,
            replicates_with_no_signal,
        };
    };

    // Score-test outputs: rt (prior center), SE (prior width), p-value (gate signal),
    // per-rep contributions (transparency on which reps drove the consensus). Floor
    // SE to one grid step to avoid a pathologically tight prior when Fisher info is
    // very large. Map per-rep score from active-only back to ORIGINAL replicate
    // index, with None at sequencing-failure indices.
    let score_test_rt = fit.p_star.max(vote_floor);
    let score_test_rt_se = (1.0 / fit.info.max(1e-12)).sqrt().max(grid_step);
    let score_test_p_value = fit.p_value;
    let mut per_rep_score: Vec<Option<f64>> = vec![None; n_total];
    for (k, &orig_i) in active_indices.iter().enumerate() {
        per_rep_score[orig_i] = Some(fit.per_rep_score[k]);
    }

    // Pass gate: (a) score test significant at α, AND (b) strict majority of
    // reps-with-signal contribute positively to U(p̂*).
    let supporting_reps = fit.per_rep_score.iter().filter(|&&s| s > 0.0).count();
    let model_passes = score_test_p_value < alpha && supporting_reps >= majority;

    if !model_passes {
        return ConsensusResult {
            passed: false,
            insufficient_data: false,
            initial_earliest_picks,
            initial_most_significant_picks,
            initial_democratic_picks,
            initial_democratic_position,
            score_test_rt: Some(score_test_rt),
            score_test_rt_se: Some(score_test_rt_se),
            score_test_p_value: Some(score_test_p_value),
            per_rep_score_contribution: Some(per_rep_score),
            bayesian_pick: None,
            bayesian_pick_posterior: None,
            bayesian_pick_runner_up_posterior: None,
            bayesian_pick_threshold_margin: None,
            bayesian_refined_picks: vec![None; n_total],
            bayesian_supporting_replicates: Vec::new(),
            n_replicates: n_total,
            n_replicates_with_signal: n,
            replicates_with_no_signal,
        };
    }

    // Bayesian inference: posterior over candidate peaks combining the score-test
    // prior with per-rep votes. The MAP candidate IS the algorithm's chosen rt.
    let bayes = bayesian_inference(
        &active_chroms,
        &active_baselines,
        tolerance,
        &initial_earliest_picks,
        &initial_most_significant_picks,
        &initial_democratic_picks,
        vote_floor,
        score_test_rt,
        tolerance,
    );
    let (bayesian_pick, bayesian_pick_posterior, bayesian_pick_runner_up_posterior) = match &bayes {
        Some(b) => (Some(b.pick), Some(b.posterior), b.runner_up_posterior),
        None => (None, None, None),
    };
    let bayesian_pick_threshold_margin =
        bayesian_pick.map(|rt| (rt - threshold) / tolerance);

    // Stage 2: per-rep refined picks AND per-rep supporting indicator.
    //
    // bayesian_refined_picks[i] = rt of the highest-intensity sample on rep i's
    // CHROMATOGRAM within ±FWHM of the chosen answer. NOT restricted to NB-significant
    // peaks: every rep manifests the chosen answer somewhere, even when the per-rep
    // picker missed the peak the joint score test found. FWHM = 2√(2 ln 2)·σ ≈ 2.3548·σ.
    //
    // bayesian_supporting_replicates = subset of active reps that ALSO have an
    // NB-significant peak in the same window. The "support indicator" — surfaces which
    // reps individually corroborate the answer (vs reps whose refined pick is just the
    // chromatogram's argmax in the window with no per-rep statistical significance).
    //
    // Match target prefers bayesian_pick; falls back to score_test_rt when the Bayesian
    // step found no candidates (so refined picks still surface what the prior points at).
    let match_window = FWHM_OVER_SIGMA * tolerance;
    let match_target = bayesian_pick.unwrap_or(score_test_rt);
    let mut bayesian_refined_picks: Vec<Option<f64>> = vec![None; n_total];
    let mut bayesian_supporting_replicates: Vec<usize> = Vec::new();
    for &orig_i in &active_indices {
        let (rt_arr, intensity_arr) = &chromatograms_per_replicate[orig_i];
        let mut best_rt: Option<f64> = None;
        let mut best_intensity = f64::NEG_INFINITY;
        for (&t, &y) in rt_arr.iter().zip(intensity_arr.iter()) {
            if (t - match_target).abs() <= match_window && y > best_intensity {
                best_intensity = y;
                best_rt = Some(t);
            }
        }
        bayesian_refined_picks[orig_i] = best_rt;

        // Supporting iff this rep has an NB-significant peak in the same window.
        if peaks_per_replicate[orig_i]
            .iter()
            .any(|p| (p.rt - match_target).abs() <= match_window)
        {
            bayesian_supporting_replicates.push(orig_i);
        }
    }

    ConsensusResult {
        passed: true,
        insufficient_data: false,
        initial_earliest_picks,
        initial_most_significant_picks,
        initial_democratic_picks,
        initial_democratic_position,
        score_test_rt: Some(score_test_rt),
        score_test_rt_se: Some(score_test_rt_se),
        score_test_p_value: Some(score_test_p_value),
        per_rep_score_contribution: Some(per_rep_score),
        bayesian_pick,
        bayesian_pick_posterior,
        bayesian_pick_runner_up_posterior,
        bayesian_pick_threshold_margin,
        bayesian_refined_picks,
        bayesian_supporting_replicates,
        n_replicates: n_total,
        n_replicates_with_signal: n,
        replicates_with_no_signal,
    }
}

/// Among `peaks`, return the one nearest `target` with `|p − target| ≤ tolerance`.
/// Ties on distance go to the earlier rt.
fn nearest_within_window(peaks: &[f64], target: f64, tolerance: f64) -> Option<f64> {
    let mut best: Option<f64> = None;
    let mut best_dist = f64::INFINITY;
    for &p in peaks {
        let d = (p - target).abs();
        if d > tolerance {
            continue;
        }
        if d < best_dist || (d == best_dist && p < best.unwrap()) {
            best_dist = d;
            best = Some(p);
        }
    }
    best
}

/// Find the candidate position with the broadest distinct-rep support. Candidates are
/// drawn from the union of all reps' peaks past the vote floor; for each, count how
/// many reps have at least one peak within ±tol of it. Ties broken by the EARLIEST
/// position (preserves the original dimerization-protection prior).
///
/// Returns `(position, count)` or `None` if there are no peaks at all.
fn best_supported_position(
    active_peaks: &[Vec<f64>],
    tolerance: f64,
) -> Option<(f64, usize)> {
    let mut candidates: Vec<f64> = active_peaks
        .iter()
        .flat_map(|peaks| peaks.iter().copied())
        .collect();
    if candidates.is_empty() {
        return None;
    }
    candidates.sort_by(|a, b| a.partial_cmp(b).unwrap());
    candidates.dedup_by(|a, b| (*a - *b).abs() < 1e-9);

    let mut best_count: usize = 0;
    let mut best_pos: Option<f64> = None;
    for cand in candidates {
        let count = active_peaks
            .iter()
            .filter(|peaks| peaks.iter().any(|&p| (p - cand).abs() <= tolerance))
            .count();
        if count > best_count {
            best_count = count;
            best_pos = Some(cand);
        }
        // Iterating ascending → ties on count automatically go to the earliest.
    }
    best_pos.map(|p| (p, best_count))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pk(rt: f64) -> Peak {
        Peak { rt, intensity: 100.0, area: 1000.0, prominence: 80.0, p_value: 1e-6 }
    }

    /// Build a triangular synthetic chromatogram on a uniform grid centred on `mu` with
    /// half-width 1 sample at the apex (height `amp` at `mu`, half-amp at neighbors,
    /// zero elsewhere). Returns the chromatogram + the matching pre-picked Peak.
    fn replicate(grid: &[f64], mu: f64, amp: f64) -> (Chromatogram, Vec<Peak>) {
        let intensity: Vec<f64> = grid
            .iter()
            .map(|&t| {
                let d = (t - mu).abs();
                if d < 1e-9 {
                    amp
                } else if d < 0.51 {
                    amp * 0.5
                } else {
                    0.0
                }
            })
            .collect();
        (
            (grid.to_vec(), intensity),
            vec![Peak {
                rt: mu,
                intensity: amp,
                area: amp * 2.0,
                prominence: amp,
                p_value: 1e-6,
            }],
        )
    }

    fn approx(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() < tol
    }

    #[test]
    fn empty_replicates_yields_fail() {
        let r = consensus(&[], &[], 0.0, 0.5, 1e-3);
        assert!(!r.passed);
        assert!(r.score_test_rt.is_none());
        assert!(r.bayesian_refined_picks.is_empty());
    }

    #[test]
    fn three_aligned_replicates_pass() {
        let grid: Vec<f64> = (0..21).map(|i| i as f64 * 0.5).collect();
        let r1 = replicate(&grid, 5.0, 100.0);
        let r2 = replicate(&grid, 5.0, 100.0);
        let r3 = replicate(&grid, 5.0, 100.0);
        let chroms = vec![r1.0, r2.0, r3.0];
        let peaks = vec![r1.1, r2.1, r3.1];
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(r.passed);
        assert!(approx(r.score_test_rt.unwrap(), 5.0, 0.05));
        assert_eq!(r.bayesian_refined_picks, vec![Some(5.0), Some(5.0), Some(5.0)]);
    }

    #[test]
    fn three_replicates_with_subsample_offsets_pass() {
        // Replicates picked at 5.0, 5.5, 5.5 (grid-quantized). Score-test MLE should
        // give a score_test_rt between 5.0 and 5.5; each replicate is within tolerance.
        let grid: Vec<f64> = (0..21).map(|i| i as f64 * 0.5).collect();
        let r1 = replicate(&grid, 5.0, 100.0);
        let r2 = replicate(&grid, 5.5, 100.0);
        let r3 = replicate(&grid, 5.5, 100.0);
        let chroms = vec![r1.0, r2.0, r3.0];
        let peaks = vec![r1.1, r2.1, r3.1];
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(r.passed);
        let crt = r.score_test_rt.unwrap();
        assert!(crt >= 5.0 && crt <= 5.5, "score_test_rt {} not in [5.0, 5.5]", crt);
        for p in &r.bayesian_refined_picks {
            assert!(p.is_some());
        }
    }

    #[test]
    fn outlier_minority_still_passes() {
        // 5 replicates at 5.0, 1 outlier at 10.0. Score test pulls toward 5.0;
        // outlier rep is excluded from the supporting set (no NB-significant peak
        // in the FWHM window of bayesian_pick) but still gets a refined pick from
        // its raw chromatogram (the rt of max intensity in the window — likely
        // baseline noise since the outlier's actual peak is at 10.0).
        let grid: Vec<f64> = (0..31).map(|i| i as f64 * 0.5).collect();
        let chroms_peaks: Vec<_> = [5.0, 5.0, 5.0, 5.0, 5.0, 10.0]
            .iter()
            .map(|&mu| replicate(&grid, mu, 100.0))
            .collect();
        let chroms: Vec<_> = chroms_peaks.iter().map(|(c, _)| c.clone()).collect();
        let peaks: Vec<_> = chroms_peaks.iter().map(|(_, p)| p.clone()).collect();
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(r.passed);
        assert!(approx(r.score_test_rt.unwrap(), 5.0, 0.1));
        // Outlier rep is NOT in the supporting set (no NB-sig peak near 5.0).
        assert!(!r.bayesian_supporting_replicates.contains(&5));
        // Five reps with peaks at 5.0 ARE in the supporting set.
        for i in 0..5 {
            assert!(r.bayesian_supporting_replicates.contains(&i),
                    "rep {} should be in supporting set", i);
        }
    }

    #[test]
    fn no_clustered_majority_fails() {
        // 6 replicates split 3 / 3 across two distant rt's; majority = 4; both clusters
        // attract only 3 → fail.
        let grid: Vec<f64> = (0..31).map(|i| i as f64 * 0.5).collect();
        let chroms_peaks: Vec<_> = [5.0, 5.0, 5.0, 12.0, 12.0, 12.0]
            .iter()
            .map(|&mu| replicate(&grid, mu, 100.0))
            .collect();
        let chroms: Vec<_> = chroms_peaks.iter().map(|(c, _)| c.clone()).collect();
        let peaks: Vec<_> = chroms_peaks.iter().map(|(_, p)| p.clone()).collect();
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(!r.passed);
        assert!(r.bayesian_pick.is_none());
    }

    #[test]
    fn empty_chromatogram_replicate_is_excluded() {
        // 3 replicates total: 2 at 5.0, 1 with empty chromatogram (no NB-significant
        // peaks anywhere). The empty rep is a sequencing failure; n_replicates_with_signal
        // is 2, both cluster at p̂*=5.0 → passes. bayesian_refined_picks[2] stays None.
        let grid: Vec<f64> = (0..21).map(|i| i as f64 * 0.5).collect();
        let r1 = replicate(&grid, 5.0, 100.0);
        let r2 = replicate(&grid, 5.0, 100.0);
        let chroms = vec![r1.0, r2.0, (Vec::new(), Vec::new())];
        let peaks = vec![r1.1, r2.1, Vec::new()];
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(r.passed);
        assert!(approx(r.score_test_rt.unwrap(), 5.0, 0.1));
        assert_eq!(r.bayesian_refined_picks[2], None);
        assert_eq!(r.n_replicates, 3);
        assert_eq!(r.n_replicates_with_signal, 2);
        assert_eq!(r.replicates_with_no_signal, vec![2]);
    }

    #[test]
    fn one_replicate_with_early_noise_does_not_anchor_consensus() {
        // Broadest-agreement rule: one replicate has a small early noise peak AND the
        // real later peak; two replicates have only the real later peak. The candidate
        // at 2.0 gets only 1-of-3 support (just the noisy rep). The candidate at 5.0
        // gets 3-of-3. 5.0 wins → bayesian pick at the real peak.
        let grid: Vec<f64> = (0..21).map(|i| i as f64 * 0.5).collect();
        let mut noisy_chrom = replicate(&grid, 5.0, 100.0).0;
        for (i, &t) in noisy_chrom.0.iter().enumerate() {
            if (t - 2.0).abs() < 1e-9 {
                noisy_chrom.1[i] = 30.0;
            }
        }
        let noisy_peaks = vec![pk(2.0), pk(5.0)];
        let clean1 = replicate(&grid, 5.0, 100.0);
        let clean2 = replicate(&grid, 5.0, 100.0);
        let chroms = vec![noisy_chrom, clean1.0, clean2.0];
        let peaks = vec![noisy_peaks, clean1.1, clean2.1];
        let r = consensus(&chroms, &peaks, 1.0, 0.5, 1e-3);
        assert!(r.passed);
        let crt = r.score_test_rt.unwrap();
        assert!(crt > 4.0, "score_test_rt pulled to early noise: {}", crt);
        assert_eq!(r.bayesian_refined_picks[0], Some(5.0));
        assert_eq!(r.bayesian_refined_picks[1], Some(5.0));
        assert_eq!(r.bayesian_refined_picks[2], Some(5.0));
    }

}
