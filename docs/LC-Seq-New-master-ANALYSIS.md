# LC-Seq-New-master: Comprehensive Feature Analysis

**Purpose:** Catalog every major capability in the buddy's `LC-Seq-New-master` codebase to support refactoring features into the main LC-Seq chromatography application.

**Date:** 2026-06-30

---

## Executive Summary

`LC-Seq-New-master` is a **pedigree-tree pruning engine** for DNA-encoded library (DEL) cyclic-peptide LC-MS chromatograms. It is **not** a general-purpose chromatography workstation; it is a specialized statistical pipeline that answers:

> *Given replicated chromatograms for every positional truncate in a combinatorial library, which building-block additions produce real, chromatographically consistent peaks as we walk from the all-null root toward full compounds?*

The "null truncation analysis" you referred to is the **core organizing principle** of this codebase: each compound is decomposed into **positional truncates** where unfilled positions are marked with a null token (e.g. `AgxNull`). These truncates form a **directed acyclic graph (pedigree)** from root → classes → full compounds. Retention-time monotonicity along parent→child edges prunes chemically implausible branches.

### Architecture

| Layer | Technology | Role |
|-------|------------|------|
| **Core algorithms** | Rust (`src/`) | Peak picking, baseline, score test, consensus, pedigree walk |
| **Python bindings** | PyO3 / maturin (`src/bindings.rs` → `lcseq._native`) | Expose Rust to Python |
| **Python frontend** | `python/lcseq/` | XLSX ingestion, CLI, tree rendering, debug plots |
| **Build** | `uv` + `maturin` | Python env + compiled extension |

Your main application (CustomTkinter GUI, SQLite database, library metrics) currently handles **data loading, visualization, and aggregate library statistics**. It does **not** yet implement the pedigree pruning, NB peak picker, multi-replicate consensus, or split-tree analysis found here.

---

## 1. Data Model: Null Truncates & Equivalence Classes

**Files:** `src/library/truncate.rs`, `src/library/pedigree.rs`

This is the conceptual heart of the "null analysis."

### 1.1 Positional Truncate (`Truncate`)

A truncate is an ordered N-tuple of building-block names in **N→C order**. Empty positions hold a configurable **null token** (default `AgxNull`).

Example for N=3:
```
AgxNull-DNvl-AgxNull   → tier 1, class [DNvl]
DNvl-DPhe-AgxNull      → tier 2, class [DNvl, DPhe]
DNvl-DPhe-DNvl         → tier 3, full compound
```

**Key properties:**
- `tier()` — count of non-null positions
- `class_key()` — non-null BBs in N→C order (padding-invariant, **order-sensitive**)
- `display()` — human-readable `BB1-BB2-BB3` string

### 1.2 Equivalence Class (`TruncateClass`)

Truncates with the same non-null BB sequence but different null-padding positions are **replicates of one equivalence class**. For tier k in an N-position library, a class has **C(N, k)** positional members (all ways to place k BBs).

Example: class `[DNvl, DPhe]` at N=3 has up to 6 members:
```
DNvl-DPhe-AgxNull, DNvl-AgxNull-DPhe, AgxNull-DNvl-DPhe, ...
```

Each member's chromatogram is one **replicate** in the consensus algorithm.

### 1.3 Pedigree DAG (`build_pedigree`)

**Function:** `build_pedigree(bbs_per_position, null_token) → Pedigree`

Builds a directed graph:

| Node kind | Tier | Meaning |
|-----------|------|---------|
| **Class** | 0..N-1 | Equivalence class of truncates sharing the same ordered BB subsequence |
| **Compound** | N | Single full compound (no nulls) |

**Construction steps:**
1. Cartesian product over `(allowed_BBs_at_position_i ∪ {null_token})` for each position
2. Group truncates by tier and class key
3. Wire edges: parent class = drop one non-null position from the ordered sequence

**Position restrictions:** Real DELs may allow different BB sets at each position. Pass `bbs_per_position: list[list[str]]` to enumerate only physically realizable truncates.

**Node metadata:**
- Stable DOT-safe IDs: `C0` (root), `C1_DNvl`, `C2_DNvl_DPhe`, `F3_DNvl_DPhe_DNvl`
- Human labels: `ROOT`, `DNvl+DPhe`, `DNvl-DPhe-DNvl`
- `members` — list of positional truncates (replicates)

---

## 2. Peak Picking (Single Chromatogram)

**Files:** `src/peaks/picker.rs`, `src/peaks/baseline.rs`, `src/peaks/significance.rs`

**Python API:** `lcseq.find_peaks(rt, intensity, alpha) → list[PyPeak]`

### 2.1 Pipeline

```
intensity[] → sigma-clip baseline → local maxima → valley boundaries
           → height + area statistics → NB significance tests → filtered peaks
```

### 2.2 Baseline Estimation (`estimate_baseline`)

Designed for **sequencing-derived count chromatograms** (integer-like signals):

1. **Sigma-clipping** (default σ=2.0, max 10 iterations): iteratively remove positive outliers above `mean + 2σ`
2. Compute **median** (μ) and **std** (σ) of survivors
3. Estimate **Negative-Binomial dispersion** r via method of moments: `r = μ² / (σ² − μ)`
4. If under-dispersed (σ² ≤ μ), return `dispersion_r = None` → fall back to Poisson

### 2.3 Local Maxima Detection

- Strict-left, ≥-right criterion
- **Plateau-aware**: flat tops detected correctly
- Peaks below baseline μ are discarded immediately

### 2.4 Valley-Bounded Integration

For each maximum:
- Walk left/right until intensity stops descending → integration window
- **Height** = apex intensity
- **Area** = sum of intensities over window
- **Prominence** = scipy-style: `height − max(left_base, right_base)`

### 2.5 Negative-Binomial Significance Testing

Two upper-tail tests per peak:
- **Height test:** `P(X ≥ height | NB(r, p_bg))` where `p = r/(r+μ)`
- **Area test:** `P(X ≥ area | NB(width·r, p_bg))` (sum of width iid NBs)

**Acceptance rule:** `min(p_height, p_area) < α/2` (Bonferroni correction for two tests at family-wise level α).

**Fallback:** Poisson(μ) when dispersion unavailable.

### 2.6 Peak Output (`Peak` / `PyPeak`)

| Field | Meaning |
|-------|---------|
| `rt` | Retention time at apex |
| `intensity` | Peak height |
| `area` | Integrated area over valley bounds |
| `prominence` | Prominence above surrounding baseline |
| `p_value` | Surviving significance p-value |

Peaks returned in ascending RT order.

### 2.7 Tunable Parameters

| Parameter | Default (CLI) | Role |
|-----------|---------------|------|
| `alpha` | `1e-3` | Per-peak FDR threshold (height + area tests) |

---

## 3. Multi-Replicate Consensus (Per Equivalence Class)

**Files:** `src/evaluate/consensus.rs`, `src/evaluate/peak_model.rs`

**Python API:** `lcseq.diagnose_class(chromatograms, effective_threshold, tolerance, alpha)`

This is the algorithm that picks **one retention time per class** from multiple replicate chromatograms.

### 3.1 Replicate Partitioning

Before any aggregation:
- Reps with **zero NB-significant peaks anywhere** → **sequencing failures** (`insufficient_data` path)
- Only reps with signal participate in score test and Bayesian inference
- Sequencing failures are tracked in `replicates_with_no_signal` and excluded from denominators

### 3.2 Parent Threshold & Vote Floor

Given parent's chosen RT as `effective_threshold`:

```
vote_floor = effective_threshold + FWHM_OVER_SIGMA × tolerance
           ≈ effective_threshold + 2.355 × tolerance
```

**Rationale:** Child peaks must be chromatographically distinguishable from the parent's right downslope (resolution criterion Rs ≈ 1.0). Peaks at or before `vote_floor` are excluded from per-rep picks.

A pale red **parent-exclusion band** at `effective_threshold ± tolerance` is visualized in debug plots.

### 3.3 Stage 1: Per-Replicate Initial Picks

For each replicate with signal, three independent pick criteria (all peaks must be past `vote_floor`):

| Criterion | Selection rule |
|-----------|----------------|
| **Earliest** | Smallest RT among qualifying peaks |
| **Most significant** | Lowest p-value among qualifying peaks |
| **Democratic** | Peak nearest the class-wide "broadest-agreement position" within ±tolerance |

**Democratic position** (`initial_democratic_position`): among all candidate RTs from all reps, pick the position where the **maximum number of distinct reps** have a peak within ±tolerance. Ties → earliest RT.

### 3.4 Stage 1: Joint Score Test (n ≥ 2 reps with signal)

**File:** `src/evaluate/peak_model.rs`

**Generative model** (per replicate j, time bin i):

```
Yᵢⱼ ~ NB(μⱼ + αⱼ · φ(tᵢ; p*, σ), r)
φ(t; p*, σ) = exp(−(t−p*)² / (2σ²))    [Gaussian peak shape]
```

**Hypothesis test:** H₀: no shared peak (αⱼ = 0) vs H₁: shared peak at p*

**Score statistic** at candidate p*:
```
U(p*) = Σⱼ Σᵢ φᵢⱼ · (Yᵢⱼ − μⱼ) / Var(Yᵢⱼ)
I(p*) = Σⱼ Σᵢ φᵢⱼ² / Var(Yᵢⱼ)
z(p*) = U(p*) / √I(p*)  ~ N(0,1) under H₀
```

**Search:** Coarse grid from `vote_floor` to max RT (step = half sample spacing, capped at 0.1), then **parabolic sub-grid refinement** around best point.

**Outputs:**
- `score_test_rt` — MLE of shared peak position p̂*
- `score_test_rt_se` — `1/√I(p̂*)` (diagnostic; not used as Bayesian prior width)
- `score_test_p_value` — one-sided upper-tail normal test
- `per_rep_score_contribution` — each rep's signed U contribution at p̂*

**Pass gate (multi-rep):**
1. `score_test_p_value < alpha`
2. Strict majority of reps-with-signal have **positive** score contribution at p̂*

### 3.5 Stage 2: Bayesian Meta-Pick (n ≥ 2, after score test passes)

Combines score-test prior with per-rep vote evidence.

**Prior at candidate k:**
```
log_prior(k) = max(z(k), 0)² / 2
```
where `z(k) = U(k)/√I(k)` evaluated via `score_at()` — the joint NB log-likelihood ratio landscape.

**Evidence:** Each per-rep vote (earliest, most-significant, democratic) is an **independent Gaussian observation** centered at the vote RT with width `σ_obs = tolerance`. Votes are **not deduplicated** — a rep where all three criteria agree contributes three cooperative votes.

**Candidate set:** Union of all vote positions + `score_test_rt`, deduplicated within `σ_obs`.

**Posterior:** Softmax over `log_prior + log_evidence`.

**Outputs:**
- `bayesian_pick` — MAP candidate (algorithm's chosen RT for multi-rep nodes)
- `bayesian_pick_posterior` — posterior probability of MAP
- `bayesian_pick_runner_up_posterior` — second-best (ambiguity indicator)
- `bayesian_pick_threshold_margin` — `(bayesian_pick − threshold) / tolerance`

### 3.6 Stage 2: Refined Per-Rep Picks

For each active replicate:
- `bayesian_refined_picks[i]` — RT of **highest-intensity sample** on raw chromatogram within ±FWHM of chosen answer (not restricted to NB-significant peaks)
- `bayesian_supporting_replicates` — reps that **also** have an NB-significant peak in the same window (corroboration indicator)

### 3.7 Single-Replicate Path (n = 1)

No score test, no Bayesian step. The class passes iff the rep's **most-significant pick** past vote_floor exists. Chosen RT = `initial_most_significant_picks[0]`.

### 3.8 Tunable Parameters

| Parameter | Default (CLI) | Role |
|-----------|---------------|------|
| `tolerance` | 30 s (or 0.5 min) | Replicate agreement window; also Gaussian σ for score test |
| `alpha` | `1e-3` | Score-test gate threshold (same α family as peak picker) |

---

## 4. Pedigree Evaluation & Tree Pruning

**Files:** `src/evaluate/pedigree_eval.rs`

**Python API:** `lcseq.evaluate_library(bbs_per_position, null_token, chromatograms, tolerance, alpha) → list[NodeRecord]`

This is the **library-wide split-tree analysis**.

### 4.1 Evaluation Order

Nodes processed **tier by tier** (topological order):
- **Tier 0 (root):** Single all-null chromatogram. Pick most-significant peak (lowest p-value). That RT becomes the threshold for children.
- **Tier 1:** Two-pass evaluation:
  1. **Singleton BB classes** first (non-cassette)
  2. **Cassette BB classes** second (need singleton RT anchors)
- **Tiers 2..N:** Parallel evaluation (rayon) with full singleton RT map

### 4.2 Parent Gating

A node is **evaluated** only if:
1. Every structural parent node has `passed = true`
2. Parent chosen RTs are known

A node is **pruned** (absent from results or `evaluated = false`) if any parent failed.

**Threshold for children:**
```
effective_threshold = max(structural_parent_rts, cassette_component_rts)
```

### 4.3 Chemical Monotonicity (Cassette BBs)

**Cassette** = multi-residue building block whose name contains `-` (e.g. `DLeu-DLeu-Pro`).

**Chemistry constraint:** In RPLC, adding residues never decreases retention. A cassette's RT must be ≥ each singleton component's RT.

**Implementation:**
1. After tier-1 singletons pass, build `singleton_rt_map: {BB_name → chosen_rt}`
2. For classes containing cassette BBs, augment threshold with `max(component_rts)` for each `-`-split component

### 4.4 Node Outcome States

| State | `passed` | `insufficient_data` | Meaning |
|-------|----------|---------------------|---------|
| **Pass** | true | false | Valid peak past parent threshold |
| **Synthesis failure** | false | false | Signal exists but no qualifying peak |
| **Sequencing failure** | false | true | Zero NB-significant peaks in all reps |
| **Pruned** | false | false | Parent failed; node never scored |

### 4.5 NodeRecord (Full Output Schema)

Each pedigree node returns a rich record. Key fields for UI integration:

**Identity:** `id`, `label`, `tier`, `kind` (`"class"` | `"compound"`), `members`, `parent_ids`

**Status:** `evaluated`, `passed`, `insufficient_data`

**Stage 1 picks:** `initial_earliest_picks`, `initial_most_significant_picks`, `initial_democratic_picks`, `initial_democratic_position`

**Score test:** `score_test_rt`, `score_test_rt_se`, `score_test_p_value`, `per_rep_score_contribution`

**Bayesian:** `bayesian_pick`, `bayesian_pick_posterior`, `bayesian_pick_runner_up_posterior`, `bayesian_pick_threshold_margin`

**Refined:** `bayesian_refined_picks`, `bayesian_supporting_replicates`

**Accounting:** `n_replicates`, `n_replicates_with_signal`, `replicates_with_no_signal`, `effective_threshold`

### 4.6 Utility: `passed_only()`

Rust helper to filter outcome map to passed nodes only (the pruned tree).

---

## 5. Python I/O Layer

**File:** `python/lcseq/io.py`

### 5.1 `parse_xlsx(path, ...)`

Parses the **LDEL master xlsx** format into kernel input.

**Inputs:**
| Parameter | Default | Role |
|-----------|---------|------|
| `lid` | `"DEL-0044"` | Library/condition filter column |
| `null_token` | `"AgxNull"` | Unfilled position marker |
| `channel` | `"scaled"` | `"raw"` = sig1, `"scaled"` = sig2 |
| `source_unit` | `"seconds"` | Time unit in file |
| `unit` | `"seconds"` | Output RT unit |

**Column mapping:**
- `lid` — row filter
- `all_datapoints` — `time:sig1;sig2, time:sig1;sig2, ...`
- `BB1 Name`, `BB2 Name`, `BB3 Name` — reversed to N→C order at parse boundary

**Outputs:**
- `bbs_per_position: list[list[str]]` — observed BBs per position (drives pedigree enumeration)
- `chromatograms: dict[tuple[str,...], (rt ndarray, intensity ndarray)]` — tuple keys avoid `-` collision in cassette names

### 5.2 Data Format Notes

- XLSX stores BB columns in synthetic/C→N order; parser reverses to N→C
- Tuple keys (not dash-joined strings) are required for cassette BBs like `DLeu-DLeu-Pro`
- Time unit conversion happens at I/O boundary; Rust kernel is unit-agnostic

---

## 6. Command-Line Interface

**File:** `python/lcseq/cli.py`

**Entry point:** `lcseq run <xlsx> [options]`

### 6.1 Pipeline

```
parse_xlsx → [optional --bbs filter] → evaluate_library → [optional render_pruned_tree]
```

### 6.2 CLI Options

| Flag | Default | Role |
|------|---------|------|
| `--lid` | `DEL-0044` | Library ID filter |
| `--null-token` | `AgxNull` | Null position token |
| `--channel` | `scaled` | Signal channel |
| `--source-unit` | `seconds` | File time unit |
| `--unit` | `seconds` | Operating unit |
| `--tolerance` | `30.0` | In `--unit` |
| `--alpha` | `1e-3` | Significance threshold |
| `--bbs` | all | Sub-library filter |
| `--out` | none | Tree figure output stem |
| `--format` | `png` | Graphviz format |
| `--layout` | `twopi` | Graphviz engine |
| `--no-failed` | off | Hide failed nodes |
| `--no-rt-labels` | off | Omit RT from labels |
| `--keep-dot` | off | Keep `.dot` source |

### 6.3 Summary Output

Per-tier counts: `pass`, `fail`, `pruned` — printed to stdout.

---

## 7. Visualization

### 7.1 Pruned Tree Rendering

**File:** `python/lcseq/render.py`  
**Function:** `render_pruned_tree(records, out_path, ...)`

Graphviz-based pedigree figure with color coding:

| Color | Meaning |
|-------|---------|
| Grey | Root |
| Light green | Passed class |
| Deeper green | Passed compound |
| Red | Synthesis failure (signal, no peak past parent) |
| Pale yellow | Sequencing failure (no usable data) |

Gate-pruned descendants are never rendered. Supports `twopi` (radial) and `dot` (hierarchical) layouts.

### 7.2 Per-Class Debug Plots

**File:** `python/lcseq/debug.py`

| Function | Purpose |
|----------|---------|
| `plot_class(replicates, effective_threshold, tolerance, alpha)` | Single-class diagnostic overlay |
| `inspect_class(xlsx, class_bbs, ...)` | Pull class from xlsx + plot with canonical threshold |
| `inspect_classes(xlsx, classes, ...)` | Multi-panel stack by tier |
| `inspect_lineage(xlsx, leaf_class_bbs, ...)` | Full ancestor chain from root to leaf |

**Plot layers** (all values from Rust via `diagnose_class`, no Python reimplementation):
- Per-rep chromatogram traces
- NB-significant peak markers
- Per-rep initial picks (earliest ◀, most-significant ★, democratic ◆)
- Parent-exclusion zone (red band)
- Score-test RT + SE band (green)
- Bayesian pick + FWHM band (purple)
- Bayesian-refined picks (squares; thick border = supporting rep)

---

## 8. Native Python API Surface (Integration Reference)

All exported from `lcseq` package:

```python
from lcseq import (
    evaluate_library,   # Full pedigree evaluation
    find_peaks,         # Single-chromatogram NB picker
    diagnose_class,     # Single-class consensus diagnostics
    parse_xlsx,         # LDEL xlsx → kernel input
    render_pruned_tree, # Graphviz tree figure
    NodeRecord,         # Per-node outcome
    PyPeak,             # Picked peak
    ClassDiagnostic,    # diagnose_class result
)
```

**Build requirement:** `maturin develop --release` (Rust toolchain required).

---

## 9. Testing Infrastructure

### 9.1 Rust Tests

| File | Coverage |
|------|----------|
| `src/peaks/picker.rs` (unit) | Peak detection edge cases |
| `src/peaks/baseline.rs` (unit) | Sigma-clip baseline |
| `src/peaks/significance.rs` (unit) | NB/Poisson p-values |
| `src/evaluate/consensus.rs` (unit) | Multi-rep consensus scenarios |
| `src/evaluate/peak_model.rs` (unit) | Score test fitting |
| `src/evaluate/pedigree_eval.rs` (unit) | Gating, pruning, thresholds |
| `src/library/truncate.rs` (unit) | Class keys, parents |
| `src/library/pedigree.rs` (unit) | Graph structure counts |
| `tests/peaks.rs` | Integration peak tests |
| `tests/consensus.rs` | Integration consensus tests |
| `tests/library.rs` | Integration pedigree tests |
| `tests/real_data.rs` | Real fixture validation |

### 9.2 Python Tests

| File | Coverage |
|------|----------|
| `python/tests/test_bindings.py` | PyO3 round-trip |
| `python/tests/test_io.py` | XLSX parsing |
| `python/tests/test_render.py` | Tree rendering |
| `python/tests/test_e2e.py` | Full CLI (marked `slow`, needs master xlsx) |

### 9.3 Fixtures

- `tests/fixtures/real_sample.json` — small real-data slice (ships with repo)
- `scripts/extract_real_fixture.py` — regenerates fixture from master xlsx
- Master xlsx `data/LDEL_ssPID_10-40_Master3.0.xlsx` — **gitignored**, required for slow tests

---

## 10. Performance Characteristics

- **Parallelism:** `rayon` parallelizes within-tier node evaluation
- **GIL release:** `evaluate_library` releases Python GIL during Rust computation
- **Memory:** Chromatograms cloned into owned Rust `Vec<f64>` at Python boundary
- **XLSX parse:** ~25 s for full master file (noted in pytest markers)

---

## 11. What This Codebase Does NOT Include

Important gaps when planning integration into your GUI app:

| Missing capability | Notes |
|--------------------|-------|
| **Interactive manual peak editing** | All picking is automatic |
| **SQLite / database integration** | Expects in-memory dict or xlsx |
| **GUI** | CLI + matplotlib/graphviz only |
| **Mass spec / compound ID by m/z** | RT-only analysis |
| **Your spreadsheet config system** | Hard-coded LDEL xlsx column names |
| **Batch export of integrations** | Returns RT picks and peak stats, not a full integration report table |
| **Non-DEL library shapes** | Pedigree assumes combinatorial null-truncate structure |
| **Real-time plotting in app** | Debug plots are standalone matplotlib scripts |
| **User-adjustable baseline method** | Sigma-clip + NB is fixed |
| **Peak deconvolution** | No EMG/Gaussian fitting for overlapping peaks |

---

## 12. Feature → Your Application: Integration Map

Below is a suggested mapping from buddy's features to potential UI actions in your chromatography software.

### 12.1 High-Value Features to Extract

| Buddy feature | Suggested UI action | Integration complexity |
|---------------|--------------------|-----------------------|
| `find_peaks` | **"Auto peak pick"** button on chromatogram viewer | Medium — call Rust via maturin or port to Python |
| Peak area/height/prominence | Show integration table per picked peak | Low — data already in `PyPeak` |
| `diagnose_class` | **"Analyze class"** panel when viewing replicate group | Medium |
| `evaluate_library` | **"Run pedigree analysis"** on loaded library | High — needs chromatogram dict + BB structure |
| `render_pruned_tree` | **"Show split tree"** window/tab | Medium — needs graphviz or custom tree widget |
| `inspect_lineage` | **"Show lineage"** for selected compound | Medium |
| Pass/fail/insufficient_data | Color-code library table rows | Low |
| `effective_threshold` + parent gating | Explain why compound failed in tooltip | Low |

### 12.2 Data Adapter Work Required

Your app uses **SQLite + SpreadsheetConfig**; buddy's code expects:

```python
bbs_per_position: list[list[str]]      # BB sets per position
chromatograms: dict[tuple, (rt, intensity)]
null_token: str
```

You will need an adapter that:
1. Maps compound IDs → positional truncate tuples (N→C BB names per position)
2. Extracts RT/intensity arrays from your parsed `DataPoint` / `ScannedEntry` format
3. Builds `bbs_per_position` from library metadata
4. Handles null token naming (`AgxNull` or your convention)

### 12.3 Integration Approaches

| Approach | Pros | Cons |
|----------|------|------|
| **A. PyO3 extension as dependency** | Exact algorithm parity, fast | Requires Rust build chain for distribution |
| **B. Port algorithms to Python/NumPy** | No Rust dependency | Risk of drift from validated Rust; score test is non-trivial |
| **C. Subprocess CLI** | Quick prototype | Poor UX, no per-peak interactivity |
| **D. FFI shared library** | Fast, language-agnostic | Same build complexity as A |

**Recommendation:** Start with **A** for parity on critical paths (`find_peaks`, `evaluate_library`), wrap in a thin Python service layer your GUI calls.

### 12.4 Suggested Phased Rollout

**Phase 1 — Single chromatogram**
- `find_peaks` on active chromatogram
- Overlay peaks, show area/height/p-value in table
- User-adjustable `alpha`

**Phase 2 — Replicate group**
- Group compounds by equivalence class (same non-null BB sequence)
- `diagnose_class` with threshold from user or parent selection
- Debug plot in modal window

**Phase 3 — Library-wide pedigree**
- Build chromatogram dict from database scan
- `evaluate_library` with tolerance/alpha settings dialog
- Tree view + pass-rate summary (like CLI `_summarise`)
- Export `NodeRecord` CSV

**Phase 4 — Workflow integration**
- One-click "null truncation analysis" from Library Data window
- Link tree node click → open chromatogram viewer for class members
- Cache results in `library_metrics_store`-style snapshots

---

## 13. Key Algorithm Parameters (User-Facing)

| Parameter | Typical value | User should understand |
|-----------|---------------|------------------------|
| `tolerance` | 0.5 min (30 s) | "How far apart can the same peak be across replicates?" Also sets score-test peak width. |
| `alpha` | 0.001 | "How strict is peak significance?" Lower = fewer peaks. |
| `null_token` | `AgxNull` | Must match your library's empty-position naming. |
| `channel` | scaled (sig2) | Which signal column to analyze. |

---

## 14. Glossary

| Term | Definition |
|------|------------|
| **Truncate** | Positional partial compound with nulls at unfilled sites |
| **Equivalence class** | Set of truncates sharing the same ordered non-null BB sequence |
| **Pedigree** | DAG of classes and compounds from root to full library |
| **Tier** | Number of non-null positions in a truncate |
| **Vote floor** | Minimum RT for child peaks (parent RT + ~2.35× tolerance) |
| **Score test** | Rao score test for shared peak across replicates |
| **Bayesian pick** | MAP RT combining score-test prior and per-rep votes |
| **Cassette BB** | Multi-residue building block (name contains `-`) |
| **Chemical monotonicity** | Later elution when more residues are present |
| **Pruning** | Skipping evaluation of descendants of failed nodes |
| **Sequencing failure** | No statistically significant peaks in any replicate |
| **Synthesis failure** | Peaks exist but none qualify past parent threshold |

---

## 15. File Inventory

```
LC-Seq-New-master/
├── Cargo.toml                    # Rust crate config (petgraph, rayon, statrs, pyo3)
├── pyproject.toml                # Python package + maturin build
├── README.md                     # Setup and overview
├── src/
│   ├── lib.rs                    # Module root
│   ├── bindings.rs               # PyO3 API (evaluate_library, find_peaks, diagnose_class)
│   ├── peaks/
│   │   ├── mod.rs
│   │   ├── baseline.rs           # Sigma-clip NB baseline
│   │   ├── picker.rs             # Peak picking pipeline
│   │   └── significance.rs       # NB/Poisson upper-tail tests
│   ├── evaluate/
│   │   ├── mod.rs
│   │   ├── consensus.rs          # Multi-rep consensus + Bayesian inference
│   │   ├── peak_model.rs         # Joint NB score test
│   │   └── pedigree_eval.rs      # Tier-by-tier pedigree walk + pruning
│   └── library/
│       ├── mod.rs
│       ├── truncate.rs           # Truncate + TruncateClass data types
│       └── pedigree.rs           # Pedigree DAG builder
├── python/lcseq/
│   ├── __init__.py               # Public exports
│   ├── cli.py                    # `lcseq run` command
│   ├── io.py                     # LDEL xlsx parser
│   ├── render.py                 # Graphviz tree renderer
│   └── debug.py                  # Matplotlib diagnostic plots
├── python/tests/                 # pytest suite
├── tests/                        # Rust integration tests + fixtures
└── scripts/
    └── extract_real_fixture.py   # Fixture generator
```

---

## 16. Comparison with Your Current LC-Seq Application

| Capability | Your app (`src/`) | LC-Seq-New-master |
|------------|-------------------|-------------------|
| Spreadsheet loading | ✅ Configurable columns | ✅ Fixed LDEL xlsx schema |
| SQLite database | ✅ Full + index modes | ❌ |
| Chromatogram viewer | ✅ Interactive multi-series | ❌ (matplotlib debug only) |
| Library scan + metrics | ✅ Totals, averages, plots | ❌ |
| Auto peak picking | ❌ | ✅ NB significance picker |
| Peak integration | ❌ (max count only) | ✅ Area, height, prominence |
| Null truncate model | ❌ | ✅ Core data model |
| Pedigree / split tree | ❌ | ✅ Full DAG + pruning |
| Multi-replicate consensus | ❌ | ✅ Score test + Bayesian |
| Cassette monotonicity | ❌ | ✅ Chemical RT constraints |
| Pass/fail per library node | ❌ | ✅ With failure mode classification |

---

*End of analysis. This document should be treated as the authoritative inventory before beginning feature extraction.*
