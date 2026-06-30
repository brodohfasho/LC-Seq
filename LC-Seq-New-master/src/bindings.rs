use crate::evaluate::consensus::consensus;
use crate::evaluate::{evaluate, Chromatogram, ChromatogramKey};
use crate::library::{build_pedigree, NodeKind};
use crate::peaks::find_peaks;
use numpy::PyReadonlyArray1;
use petgraph::Direction;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use std::collections::HashMap;

/// One row of the evaluated pedigree, exposed to Python as an attribute object.
#[pyclass]
#[derive(Debug, Clone)]
pub struct NodeRecord {
    /// Stable canonical id (DOT-safe). Examples: `"C0"` (root), `"C1_DNvl"`,
    /// `"C2_DNvl_DPhe"`, `"F3_DNvl_DPhe_DNvl"`. Class ids are prefixed with `C{tier}_`,
    /// compound ids with `F{tier}_`, separator is `_`.
    #[pyo3(get)]
    pub id: String,
    /// Human-readable label for figures: `"ROOT"`, `"DNvl+DPhe"` (a class), or
    /// `"DNvl-DPhe-DNvl"` (a compound).
    #[pyo3(get)]
    pub label: String,
    /// 0 = root, ascending up to N at the full compounds.
    #[pyo3(get)]
    pub tier: usize,
    /// `"class"` for tier 0..N-1, `"compound"` for tier N.
    #[pyo3(get)]
    pub kind: String,
    /// Human-readable display strings for the positional truncates this node represents
    /// (one per replicate). E.g. for class `{DNvl, DPhe}` at N=3 this is the up-to-six
    /// position permutations like `"DNvl-DPhe-AgxNull"`. Note: these display strings can
    /// be ambiguous if BB names contain `-`; the unambiguous lookup key is the position
    /// tuple, kept on the Rust side. Use this field for labels/exports, not for lookups.
    #[pyo3(get)]
    pub members: Vec<String>,
    /// `id`s of the immediate parent nodes (for tree rendering).
    #[pyo3(get)]
    pub parent_ids: Vec<String>,
    /// True iff the gate let us evaluate this node (i.e. all parents passed). False means
    /// the node was pruned without being scored.
    #[pyo3(get)]
    pub evaluated: bool,
    /// True iff this node passed the consensus gate. For multi-rep classes
    /// (n_replicates_with_signal ≥ 2): score-test p < α AND a strict majority of
    /// reps-with-signal contribute positively to U(p̂*). For root and single-rep
    /// classes: the rep's most-significant pick past vote_floor exists.
    #[pyo3(get)]
    pub passed: bool,
    /// True iff every replicate of this node was a sequencing failure (zero
    /// NB-significant peaks anywhere). Distinct from `!passed`: nodes in this state
    /// have no usable data and should be excluded from pass-rate denominators.
    /// `passed=False, insufficient_data=False` is a real synthesis-style failure
    /// (signal exists but no peak past threshold).
    #[pyo3(get)]
    pub insufficient_data: bool,

    // === Stage 1: per-rep initial picks ===
    /// Per-rep earliest-rt NB-significant peak past `effective_threshold + tolerance`.
    /// Indexed by ORIGINAL replicate index; `None` for sequencing-failure reps and
    /// reps with no qualifying peak.
    #[pyo3(get)]
    pub initial_earliest_picks: Vec<Option<f64>>,
    /// Per-rep lowest-p-value NB-significant peak past `effective_threshold + tolerance`.
    /// For root and single-rep classes (n_replicates_with_signal ≤ 1), `[0]` IS the
    /// algorithm's chosen rt for the node.
    #[pyo3(get)]
    pub initial_most_significant_picks: Vec<Option<f64>>,
    /// Per-rep NB-significant peak nearest `initial_democratic_position` within
    /// ±tolerance.
    #[pyo3(get)]
    pub initial_democratic_picks: Vec<Option<f64>>,

    // === Stage 1: eclass-level aggregates ===
    /// Eclass-level "broadest-agreement position" — the rt where the maximum number
    /// of reps-with-signal have a peak within ±tolerance. Stage-1 cross-rep aggregate.
    #[pyo3(get)]
    pub initial_democratic_position: Option<f64>,
    /// Score-test MLE of the shared peak position p̂* (sub-grid refined). Eclass-level
    /// stage-1 output; serves as the prior center in the Bayesian inference. None for
    /// root and single-rep classes (no cross-rep score test runs).
    #[pyo3(get)]
    pub score_test_rt: Option<f64>,
    /// Standard error of `score_test_rt` from the score-test Fisher information
    /// (`SE = 1/√I(p̂*)`). Asymptotic uncertainty on the MLE; surfaced as a
    /// diagnostic. The Bayesian step evaluates the score-test likelihood at each
    /// candidate independently — it does NOT use this SE as a prior width. None
    /// for n_replicates_with_signal ≤ 1.
    #[pyo3(get)]
    pub score_test_rt_se: Option<f64>,
    /// One-sided upper-tail p-value of the score test under the joint NB null. None
    /// for n_replicates_with_signal ≤ 1.
    #[pyo3(get)]
    pub score_test_p_value: Option<f64>,
    /// Per-rep contribution to U(p̂*). Outer Option = "score test ran" (None for n≤1
    /// or root); inner Option per rep = None for sequencing-failure reps, Some for
    /// reps-with-signal. Positive contributions support the consensus.
    #[pyo3(get)]
    pub per_rep_score_contribution: Option<Vec<Option<f64>>>,

    // === Stage 2: Bayesian inference outputs ===
    /// MAP candidate peak from the Bayesian inference combining the score-test prior
    /// with per-rep votes. The algorithm's chosen rt for multi-rep nodes. None for
    /// root and single-rep nodes (no Bayesian step runs).
    #[pyo3(get)]
    pub bayesian_pick: Option<f64>,
    /// Posterior probability of `bayesian_pick` (range [0, 1]).
    #[pyo3(get)]
    pub bayesian_pick_posterior: Option<f64>,
    /// Posterior probability of the second-best candidate. A small gap between this
    /// and `bayesian_pick_posterior` indicates ambiguity even when the top is high.
    #[pyo3(get)]
    pub bayesian_pick_runner_up_posterior: Option<f64>,
    /// Margin of `bayesian_pick` past the parent threshold, in units of `tolerance`:
    /// `(bayesian_pick - threshold) / tolerance`. Values near 1.0 indicate the
    /// boundary-of-parent-exclusion regime (a known borderline case).
    #[pyo3(get)]
    pub bayesian_pick_threshold_margin: Option<f64>,

    // === Stage 2: per-rep refined picks + supporting indicator ===
    /// Per-rep manifestation of `bayesian_pick`: rt of the highest-intensity sample
    /// on the rep's chromatogram within ±FWHM of `bayesian_pick`. NOT restricted to
    /// NB-significant peaks — every rep manifests the chosen answer somewhere, even
    /// when the per-rep picker missed the peak the joint score test found. None for
    /// sequencing-failure reps and for root / single-rep nodes.
    #[pyo3(get)]
    pub bayesian_refined_picks: Vec<Option<f64>>,
    /// Indices of replicates that have an NB-significant peak within ±FWHM of
    /// `bayesian_pick`. The "support indicator" — surfaces which reps individually
    /// corroborate the chosen answer (a strict subset of reps-with-signal). Empty
    /// for root / single-rep nodes and when `bayesian_pick` is None.
    #[pyo3(get)]
    pub bayesian_supporting_replicates: Vec<usize>,

    // === Replicate accounting ===
    /// Total number of replicates (members of the equivalence class).
    #[pyo3(get)]
    pub n_replicates: usize,
    /// Number of replicates whose chromatogram contained at least one NB-significant
    /// peak. Reps with zero detectable signal are sequencing failures and contribute
    /// to no aggregation.
    #[pyo3(get)]
    pub n_replicates_with_signal: usize,
    /// Indices of replicates excluded as sequencing failures.
    #[pyo3(get)]
    pub replicates_with_no_signal: Vec<usize>,

    /// Threshold the consensus rule used: `max(structural parent rts, cassette
    /// singleton-component rts)`. The vote floor applied to per-rep peaks is
    /// `effective_threshold + tolerance`. None for the root and unevaluated nodes.
    #[pyo3(get)]
    pub effective_threshold: Option<f64>,
}

#[pymethods]
impl NodeRecord {
    fn __repr__(&self) -> String {
        // Show the algorithm's chosen rt regardless of which path produced it: prefer
        // bayesian_pick, fall back to score_test_rt, then to the root/n=1 most-
        // significant pick at index 0.
        let chosen = self
            .bayesian_pick
            .or(self.score_test_rt)
            .or_else(|| self.initial_most_significant_picks.first().copied().flatten());
        format!(
            "NodeRecord(id='{}', tier={}, kind='{}', evaluated={}, passed={}, insufficient_data={}, chosen_rt={:?})",
            self.id, self.tier, self.kind, self.evaluated, self.passed, self.insufficient_data, chosen
        )
    }
}

/// Run the LC-Seq pedigree evaluation on a position-restricted library.
///
/// Parameters
/// ----------
/// bbs_per_position : list[list[str]]
///     The set of BB names physically allowed at each position, in N→C order. The
///     pedigree is built only over realizable positional truncates (Cartesian product
///     of these sets, each unioned with `null_token`). For an unrestricted library,
///     pass the same set N times.
/// null_token : str
///     The token that marks an unfilled position (e.g. `"AgxNull"`).
/// chromatograms : dict[tuple[str, ...], tuple[np.ndarray, np.ndarray]]
///     Maps positional truncate (key = tuple of per-position BB names in N→C order, e.g.
///     `("AgxNull", "DLeu", "AgxNull")`) to a `(rt, intensity)` pair of 1-D float64 numpy
///     arrays. `rt` must be ascending. Tuple keys avoid collisions when BB names contain
///     the `-` character (which can happen with cassette BBs like `"DLeu-DLeu-Pro"`).
///     rt and tolerance must share the same unit (both are opaque numbers in the kernel).
/// tolerance : float
///     ± window size for replicate-pick agreement; cluster diameter is `2 * tolerance`.
/// alpha : float
///     Per-peak FDR threshold for the NB significance test (e.g. 1e-3). A peak is kept
///     iff `min(p_height, p_area) < alpha`.
///
///
/// Returns
/// -------
/// list[NodeRecord]
///     One record per pedigree node, in petgraph insertion order.
#[pyfunction]
#[pyo3(signature = (bbs_per_position, null_token, chromatograms, tolerance, alpha))]
pub fn evaluate_library<'py>(
    py: Python<'py>,
    bbs_per_position: Vec<Vec<String>>,
    null_token: String,
    chromatograms: Bound<'py, PyDict>,
    tolerance: f64,
    alpha: f64,
) -> PyResult<Vec<NodeRecord>> {
    // Materialise the chromatograms into owned Rust data so we can release the GIL.
    let mut chroms: HashMap<ChromatogramKey, Chromatogram> =
        HashMap::with_capacity(chromatograms.len());
    for (k, v) in chromatograms.iter() {
        let key: ChromatogramKey = k.extract().map_err(|_| {
            PyValueError::new_err(
                "chromatogram dict keys must be tuples of position-name strings",
            )
        })?;
        let key_repr = key.join("|"); // for error messages only
        let tup = v.downcast::<PyTuple>().map_err(|_| {
            PyValueError::new_err(format!(
                "chromatogram for '{}' must be a (rt, intensity) tuple",
                key_repr
            ))
        })?;
        if tup.len() != 2 {
            return Err(PyValueError::new_err(format!(
                "chromatogram for '{}' must have length 2; got {}",
                key_repr,
                tup.len()
            )));
        }
        let rt: PyReadonlyArray1<f64> = tup.get_item(0)?.extract().map_err(|_| {
            PyValueError::new_err(format!(
                "chromatogram '{}': rt must be a 1-D float64 numpy array",
                key_repr
            ))
        })?;
        let intensity: PyReadonlyArray1<f64> = tup.get_item(1)?.extract().map_err(|_| {
            PyValueError::new_err(format!(
                "chromatogram '{}': intensity must be a 1-D float64 numpy array",
                key_repr
            ))
        })?;
        let rt_arr = rt.as_array();
        let intensity_arr = intensity.as_array();
        if rt_arr.len() != intensity_arr.len() {
            return Err(PyValueError::new_err(format!(
                "chromatogram '{}': rt len {} != intensity len {}",
                key_repr,
                rt_arr.len(),
                intensity_arr.len()
            )));
        }
        chroms.insert(key, (rt_arr.to_vec(), intensity_arr.to_vec()));
    }

    py.allow_threads(move || {
        let pedigree = build_pedigree(&bbs_per_position, &null_token);
        let outcomes = evaluate(&pedigree, &chroms, tolerance, alpha);

        let mut records = Vec::with_capacity(pedigree.node_count());
        for ix in pedigree.node_indices() {
            let node = &pedigree[ix];
            let parent_ids: Vec<String> = pedigree
                .neighbors_directed(ix, Direction::Incoming)
                .map(|p| pedigree[p].id())
                .collect();
            let kind_str = match &node.kind {
                NodeKind::Class(_) => "class",
                NodeKind::Compound(_) => "compound",
            }
            .to_string();
            let members: Vec<String> = node.members.iter().map(|m| m.display()).collect();
            let outcome = outcomes.get(&ix);
            records.push(NodeRecord {
                id: node.id(),
                label: node.label(),
                tier: node.tier,
                kind: kind_str,
                members,
                parent_ids,
                evaluated: outcome.is_some(),
                passed: outcome.map(|o| o.passed).unwrap_or(false),
                insufficient_data: outcome.map(|o| o.insufficient_data).unwrap_or(false),
                initial_earliest_picks: outcome
                    .map(|o| o.initial_earliest_picks.clone())
                    .unwrap_or_default(),
                initial_most_significant_picks: outcome
                    .map(|o| o.initial_most_significant_picks.clone())
                    .unwrap_or_default(),
                initial_democratic_picks: outcome
                    .map(|o| o.initial_democratic_picks.clone())
                    .unwrap_or_default(),
                initial_democratic_position: outcome.and_then(|o| o.initial_democratic_position),
                score_test_rt: outcome.and_then(|o| o.score_test_rt),
                score_test_rt_se: outcome.and_then(|o| o.score_test_rt_se),
                score_test_p_value: outcome.and_then(|o| o.score_test_p_value),
                per_rep_score_contribution: outcome
                    .and_then(|o| o.per_rep_score_contribution.clone()),
                bayesian_pick: outcome.and_then(|o| o.bayesian_pick),
                bayesian_pick_posterior: outcome.and_then(|o| o.bayesian_pick_posterior),
                bayesian_pick_runner_up_posterior: outcome
                    .and_then(|o| o.bayesian_pick_runner_up_posterior),
                bayesian_pick_threshold_margin: outcome
                    .and_then(|o| o.bayesian_pick_threshold_margin),
                bayesian_refined_picks: outcome
                    .map(|o| o.bayesian_refined_picks.clone())
                    .unwrap_or_default(),
                bayesian_supporting_replicates: outcome
                    .map(|o| o.bayesian_supporting_replicates.clone())
                    .unwrap_or_default(),
                n_replicates: outcome.map(|o| o.n_replicates).unwrap_or(0),
                n_replicates_with_signal: outcome
                    .map(|o| o.n_replicates_with_signal)
                    .unwrap_or(0),
                replicates_with_no_signal: outcome
                    .map(|o| o.replicates_with_no_signal.clone())
                    .unwrap_or_default(),
                effective_threshold: outcome.and_then(|o| o.effective_threshold),
            });
        }
        Ok(records)
    })
}

/// One peak from the NB picker, exposed to Python for debugging / visualization.
#[pyclass]
#[derive(Debug, Clone)]
pub struct PyPeak {
    #[pyo3(get)]
    pub rt: f64,
    #[pyo3(get)]
    pub intensity: f64,
    #[pyo3(get)]
    pub area: f64,
    #[pyo3(get)]
    pub prominence: f64,
    #[pyo3(get)]
    pub p_value: f64,
}

#[pymethods]
impl PyPeak {
    fn __repr__(&self) -> String {
        format!(
            "Peak(rt={:.4}, intensity={:.2}, prominence={:.2}, p={:.2e})",
            self.rt, self.intensity, self.prominence, self.p_value
        )
    }
}

/// Run the NB-significance peak picker on a single chromatogram. Useful for debugging
/// and visualization — the same picker that `evaluate_library` runs internally.
#[pyfunction]
#[pyo3(name = "find_peaks", signature = (rt, intensity, alpha))]
pub fn find_peaks_py<'py>(
    rt: PyReadonlyArray1<'py, f64>,
    intensity: PyReadonlyArray1<'py, f64>,
    alpha: f64,
) -> PyResult<Vec<PyPeak>> {
    let rt_arr = rt.as_array();
    let intensity_arr = intensity.as_array();
    if rt_arr.len() != intensity_arr.len() {
        return Err(PyValueError::new_err(format!(
            "rt len {} != intensity len {}",
            rt_arr.len(),
            intensity_arr.len()
        )));
    }
    let rt_vec: Vec<f64> = rt_arr.to_vec();
    let intensity_vec: Vec<f64> = intensity_arr.to_vec();
    Ok(find_peaks(&rt_vec, &intensity_vec, alpha)
        .into_iter()
        .map(|p| PyPeak {
            rt: p.rt,
            intensity: p.intensity,
            area: p.area,
            prominence: p.prominence,
            p_value: p.p_value,
        })
        .collect())
}

/// Full diagnostic dump for one equivalence class, exposing every intermediate value
/// the consensus algorithm sees so debug visualizations can plot what the algorithm
/// actually does (no Python re-implementation drift). Mirrors `NodeRecord` but
/// includes derived fields (e.g. `supporting_indices`) that are useful for plotting.
#[pyclass]
#[derive(Debug, Clone)]
pub struct ClassDiagnostic {
    #[pyo3(get)]
    pub passed: bool,
    #[pyo3(get)]
    pub insufficient_data: bool,

    // Stage 1: per-rep initial picks
    #[pyo3(get)]
    pub initial_earliest_picks: Vec<Option<f64>>,
    #[pyo3(get)]
    pub initial_most_significant_picks: Vec<Option<f64>>,
    #[pyo3(get)]
    pub initial_democratic_picks: Vec<Option<f64>>,

    // Stage 1: eclass-level aggregates
    #[pyo3(get)]
    pub initial_democratic_position: Option<f64>,
    #[pyo3(get)]
    pub score_test_rt: Option<f64>,
    #[pyo3(get)]
    pub score_test_rt_se: Option<f64>,
    #[pyo3(get)]
    pub score_test_p_value: Option<f64>,
    #[pyo3(get)]
    pub per_rep_score_contribution: Option<Vec<Option<f64>>>,

    // Stage 2: Bayesian inference outputs
    #[pyo3(get)]
    pub bayesian_pick: Option<f64>,
    #[pyo3(get)]
    pub bayesian_pick_posterior: Option<f64>,
    #[pyo3(get)]
    pub bayesian_pick_runner_up_posterior: Option<f64>,
    #[pyo3(get)]
    pub bayesian_pick_threshold_margin: Option<f64>,

    // Stage 2: per-rep refined picks + supporting indicator
    #[pyo3(get)]
    pub bayesian_refined_picks: Vec<Option<f64>>,
    /// Indices of replicates with an NB-significant peak within ±FWHM of
    /// `bayesian_pick`. The reps that individually corroborate the chosen answer.
    /// Subset of reps-with-signal; not all reps with a refined pick (since refined
    /// picks now come from raw chromatograms, not just NB-significant peaks).
    #[pyo3(get)]
    pub bayesian_supporting_replicates: Vec<usize>,

    // Replicate accounting
    #[pyo3(get)]
    pub n_replicates: usize,
    #[pyo3(get)]
    pub n_replicates_with_signal: usize,
    #[pyo3(get)]
    pub replicates_with_no_signal: Vec<usize>,
}

/// Run the full consensus pipeline on one class and return all diagnostic intermediates.
/// Use this to visualize what the algorithm sees (per-rep earliest/statistical/democratic
/// picks, score-test consensus rt + SE, Bayesian meta-pick + confidence, refined picks).
///
/// `chromatograms` is a list of `(rt, intensity)` tuples — one per replicate of the class.
/// `effective_threshold` MUST be the threshold the algorithm actually used for this node
/// (read it from `NodeRecord.effective_threshold` after calling `evaluate_library`). Do
/// NOT pass a guessed threshold like the parent's raw rt — that produces a divergent
/// answer because cassette-monotonicity augmentation lives at the pedigree level, not
/// the per-class level.
#[pyfunction]
#[pyo3(signature = (chromatograms, effective_threshold, tolerance, alpha))]
pub fn diagnose_class<'py>(
    chromatograms: Bound<'py, PyList>,
    effective_threshold: f64,
    tolerance: f64,
    alpha: f64,
) -> PyResult<ClassDiagnostic> {
    // Materialize chromatograms into owned Rust data.
    let mut chroms: Vec<Chromatogram> = Vec::with_capacity(chromatograms.len());
    for item in chromatograms.iter() {
        let tup = item.downcast::<PyTuple>().map_err(|_| {
            PyValueError::new_err("each chromatogram must be a (rt, intensity) tuple")
        })?;
        if tup.len() != 2 {
            return Err(PyValueError::new_err(format!(
                "chromatogram tuple must have length 2; got {}",
                tup.len()
            )));
        }
        let rt: PyReadonlyArray1<f64> = tup.get_item(0)?.extract().map_err(|_| {
            PyValueError::new_err("rt must be a 1-D float64 numpy array")
        })?;
        let intensity: PyReadonlyArray1<f64> = tup.get_item(1)?.extract().map_err(|_| {
            PyValueError::new_err("intensity must be a 1-D float64 numpy array")
        })?;
        let rt_v = rt.as_array().to_vec();
        let intensity_v = intensity.as_array().to_vec();
        if rt_v.len() != intensity_v.len() {
            return Err(PyValueError::new_err(
                "rt and intensity arrays must have equal length",
            ));
        }
        chroms.push((rt_v, intensity_v));
    }

    // Pick peaks per replicate (same picker the evaluator uses).
    let peaks_per: Vec<Vec<crate::peaks::Peak>> = chroms
        .iter()
        .map(|(rt, intensity)| find_peaks(rt, intensity, alpha))
        .collect();

    // Run the actual consensus and capture intermediates.
    let result = consensus(&chroms, &peaks_per, effective_threshold, tolerance, alpha);

    Ok(ClassDiagnostic {
        passed: result.passed,
        insufficient_data: result.insufficient_data,
        initial_earliest_picks: result.initial_earliest_picks,
        initial_most_significant_picks: result.initial_most_significant_picks,
        initial_democratic_picks: result.initial_democratic_picks,
        initial_democratic_position: result.initial_democratic_position,
        score_test_rt: result.score_test_rt,
        score_test_rt_se: result.score_test_rt_se,
        score_test_p_value: result.score_test_p_value,
        per_rep_score_contribution: result.per_rep_score_contribution,
        bayesian_pick: result.bayesian_pick,
        bayesian_pick_posterior: result.bayesian_pick_posterior,
        bayesian_pick_runner_up_posterior: result.bayesian_pick_runner_up_posterior,
        bayesian_pick_threshold_margin: result.bayesian_pick_threshold_margin,
        bayesian_refined_picks: result.bayesian_refined_picks,
        bayesian_supporting_replicates: result.bayesian_supporting_replicates,
        n_replicates: result.n_replicates,
        n_replicates_with_signal: result.n_replicates_with_signal,
        replicates_with_no_signal: result.replicates_with_no_signal,
    })
}


#[pyfunction]
fn _hello() -> &'static str {
    "lcseq native extension is alive"
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NodeRecord>()?;
    m.add_class::<PyPeak>()?;
    m.add_class::<ClassDiagnostic>()?;
    m.add_function(wrap_pyfunction!(evaluate_library, m)?)?;
    m.add_function(wrap_pyfunction!(find_peaks_py, m)?)?;
    m.add_function(wrap_pyfunction!(diagnose_class, m)?)?;
    m.add_function(wrap_pyfunction!(_hello, m)?)?;
    Ok(())
}
