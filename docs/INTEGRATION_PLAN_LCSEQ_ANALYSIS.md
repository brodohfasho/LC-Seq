# LC-Seq Analysis Integration Plan

**Status:** Approved decisions recorded — ready to implement Phase 0.  
**Audience:** Project owner + implementation agents.  
**Companion doc:** [`LC-Seq-New-master-ANALYSIS.md`](../LC-Seq-New-master-ANALYSIS.md) (feature inventory).

---

## 0. Owner Decisions (Resolved)

These answers from the project owner supersede earlier open questions. **Implement exactly as written.**

### 0.1 Building-block positions — BB columns, not compound ID strings

**Do not infer truncate positions by splitting the compound name.**

Pedigree and null-truncation logic must use **dedicated spreadsheet columns** (`BB1`, `BB2`, `BB3`, …) mapped in Configure Spreadsheet. This supports non-peptide DELs and avoids ambiguity when names contain `-` (cassette BBs).

**Naming convention (critical):**

| Concept | Convention |
|---------|------------|
| Peptide / DEL literature | Sequences written **N→C** (N-terminus first) |
| Spreadsheet coupling order | **BB1** = first coupled = **C-terminus**; **BB3** (in a 3-position library) = last coupled = **N-terminus** |
| Display compound name | Often written **BB3→BB1** (N→C reading order for humans) |
| **Kernel / adapter internal key** | Positional tuple in **N→C order**: `(BB3 value, BB2 value, BB1 value)` |

The adapter **reverses** the configured BB column list when building chromatogram keys and `bbs_per_position`, matching buddy’s `parse_xlsx` behavior (xlsx columns are C→N; kernel is N→C).

**Configure Spreadsheet (required for pedigree):**

- User selects which columns are `BB1 Name`, `BB2 Name`, `BB3 Name` (or however many positions exist).
- `library_n_positions` = number of mapped BB columns.
- `null_token` (default `AgxNull`) — value in a BB column meaning “position not filled.”

**Compound ID column** remains the human-readable label for tables/plots; it is **not** the pedigree lookup key.

### 0.2 Count channel — user chooses

No hardcoded default to “Deduplicated Count.” The user already controls count names via spreadsheet config. Every analysis UI must include a **Count channel** dropdown populated from `config.count_names`. Remember the last choice per session (optional: per-database in settings).

### 0.3 Time unit — user-selectable (seconds or minutes)

- Data in the database is stored as parsed floats (typically **seconds** in owner’s files).
- Analysis UI includes **Time unit: Seconds | Minutes** (radio or checkbox).
- **Tolerance** label updates with unit (e.g. “Tolerance (seconds)” vs “Tolerance (minutes)”).
- Adapter converts RT arrays to the selected unit **before** calling Rust (kernel is unit-agnostic but RT and tolerance must match).
- Default UI unit: **seconds** (owner’s data); user can switch to minutes for display and algorithm input.

### 0.4 Full-library pedigree scope — split-tree images

**Yes — this already exists in `LC-Seq-New-master`:**

| Piece | Location | Role |
|-------|----------|------|
| `evaluate_library()` | Rust + PyO3 | Walks null-truncation pedigree; pass/fail per **class** node (tiers 0..N−1) |
| `render_pruned_tree()` | `python/lcseq/render.py` | **Split-tree figure** via Graphviz (`twopi` = root centre, **tier rings** = coupling cycles) |
| CLI | `lcseq run … --out tree` | End-to-end: xlsx → evaluate → PNG |

**Tier = coupling cycle** in the pedigree: tier 0 = root (all-null), tier 1 = single-BB classes, tier 2 = two-BB classes, tier N = full compounds.

**Hiding the final (noisy) cycle:** When integrating, add `max_display_tier` (default `library_cycle_count - 1`) so a **3-cycle library** renders tiers 0–2 only — **no tier-3 compound leaf cluster**. Implementation: filter `NodeRecord` list before `render_pruned_tree` (`tier <= max_display_tier` or `kind == "class"` only). Full CSV export can still include all tiers.

This is **library-wide** pedigree plotting — distinct from **single-compound lineage** (`inspect_lineage` in debug.py), which stacks ancestor chromatograms for one compound.

### 0.5 Isoforms (linear / cyclized / variants)

When `compound_variant_column` is configured:

- Pedigree and lineage UIs include **Isoform** control: single variant | **All isoforms** | multi-select checkboxes.
- **Side-by-side comparison** is a first-class goal: run pedigree twice (e.g. linear vs cyclized) and show summary + tree exports **next to each other**, or two PNGs / two CSVs in one saved session folder.
- Pedigree chromatogram map is built **per isoform** — only rows matching the selected variant(s) enter that run. Comparing isoforms = two separate `evaluate_library` runs with filtered compounds, not one merged run.

### 0.6 Rust analysis engine — stay in Rust

Keep buddy’s Rust core for speed and correctness. See **§2.2.1 Plain-English: Rust build** below. Long-term: ship a **pre-built** analysis module with the app installer so scientists never run `maturin` themselves.

---

## 1. Goals (What We Are Building)

### 1.1 Chromatogram Visualizer — Peak Analysis Workspace

Scientists working on **one compound at a time** (initially) should be able to:

| Action | User-facing name (proposed) |
|--------|----------------------------|
| Auto-detect statistically significant peaks | **Pick peaks** |
| Sum signal under each peak (height, area, prominence) | **Integrate peaks** |
| Estimate background noise level | **Show baseline** |
| See how this truncate fits the DEL null-truncation pedigree | **Lineage analysis** (null analysis for one compound) |
| View a table of peaks with RT, height, area, % area, significance | **Peak table** |
| Export plot as PNG/SVG | **Export image** |
| Export peak table / lineage table as CSV | **Export CSV** |

**Scope constraint (v1):** One **primary compound ID** + one **count channel** per analysis session. Architecture must allow **batch pre-compute → browse results** in a later phase.

### 1.2 Library Data — Split-Tree (Pedigree) Analysis

Scientists should be able to run **full-library pedigree pruning** from Library Data:

| Action | User-facing name (proposed) |
|--------|----------------------------|
| Run pedigree evaluation on entire loaded library | **Run pedigree analysis** |
| See pass/fail/pruned summary by tier | **Summary panel** |
| Export pruned tree as image (PNG) | **Export tree image** |
| Export node-level results as CSV | **Export pedigree CSV** |
| Re-open saved pedigree run | **Load last pedigree** |

**Design constraint:** Tree rendering and storage must be **modular** so a future interactive tree viewer (click node → open chromatograms) can replace “export PNG only” without rewriting the analysis core.

### 1.2.1 Library Data — Bulk Signal Quality Metrics

Before or in parallel with pedigree, Library Data should expose **library-wide chromatographic quality** (see **§1.4**):

| Action | User-facing name (proposed) |
|--------|----------------------------|
| Scan library + compute top-peak S/N statistics | **Signal-to-noise (bulk)** |
| View mean ± SD of baseline, peak height, S/N | **S/N summary card** |
| After pedigree: mean product-peak prominence | **Product peak prominence (pedigree)** |
| Relate counts to diversity × fractions | **Sequencing coverage** (extend existing fraction metrics) |

Bulk S/N uses the same **count channel** picker as other Library Data metrics. Results persist in `LibraryComputationSnapshot` like existing metric cards.

### 1.3 Embedded Scientist Help

Non-technical DEL scientists need **plain-English explanations** inside the app:

- What is a null truncate?
- How does peak picking work (baseline, significance)?
- What does integration mean here?
- What is pedigree / split-tree analysis and what do pass/fail colors mean?

Help must be reachable from **Peak Analysis** and **Library Data → Pedigree** via a **? Help** button, not buried in repo markdown.

### 1.4 Library Data — Signal Quality & Sequencing Depth (Owner Request)

Scientists need **library-wide quality metrics** to inform experimental design (how much sequencing depth is required for usable chromatographic resolution). This splits into two related questions:

| Question | What it measures | Primary metric(s) |
|----------|------------------|-------------------|
| **Chromatographic resolution** | Can we distinguish product signal from noise/background on individual traces? | Signal-to-noise, peak prominence, baseline statistics |
| **Sequencing coverage** | How many counts do we have per library member per fraction? | Total counts, mean count per fraction, coverage index |

These are **complementary**: high coverage with poor S/N suggests depth is not the bottleneck; low coverage with borderline S/N suggests more sequencing may help.

#### Approach A — Bulk “top peak vs baseline” S/N (implement first)

**Per entry (compound chromatogram), per count channel:**

1. Estimate baseline (σ-clipped median — same model as peak picking).
2. Find the **tallest local maximum** (or tallest statistically significant peak if α is applied).
3. Compute per-entry scalars, e.g.:
   - `peak_height` — apex intensity
   - `baseline_mu`, `baseline_sigma`
   - `snr_height = peak_height - baseline_mu` (excess signal)
   - `snr_ratio = (peak_height - baseline_mu) / baseline_sigma` when σ > 0

**Across the library:** mean, sample SD, median, and **n** (entries used / skipped), matching existing `library_metrics.py` card pattern.

**Pros:** Fast; reuses one library scan + existing peak/baseline code; no pedigree; answers “typical best peak above noise floor.”

**Cons:** The **highest peak is not always the product** (impurities, aggregates, bleed-through, odd elution). Library mean can be dominated by easy compounds. Treat as a **conservative library QC screen**, not ground truth for product resolution.

**Feasibility:** **Yes — implement now** as new metric card(s) in Library Data (Phase 2.5 below), piggybacking on `LibraryScanData` + `get_peak_picker_backend()`.

#### Approach B — Product-peak prominence via pedigree (implement after pedigree)

**Per entry where pedigree identifies a validated product peak** (chosen RT / PASS at leaf tier):

1. Measure **prominence** at the product apex (height minus higher adjacent valley — same as peak table).
2. Optionally also report product peak height − baseline, area, and pedigree score.

**Across library:** mean ± SD of product prominence; optionally **conditional** stats (only PASS compounds).

**Pros:** Biologically meaningful; aligns with DEL null-truncation logic; prominence is more robust than raw height − baseline when shoulders exist.

**Cons:** Requires pedigree run first; FAIL / insufficient-data compounds need explicit handling; isoforms need per-variant runs or filtering.

**Feasibility:** **Yes — after Phase 5** (or as Phase 5.7 add-on). Reuse `evaluate_library` node `chosen_rt` + existing prominence integration.

#### Other useful library-wide S/N proxies (future / optional)

| Metric | Role |
|--------|------|
| **Fraction of entries with ≥1 significant peak** (α) | “How many chromatograms show any real signal?” |
| **Distribution of baseline μ and σ** | Characterize noise floor across library |
| **Peaks per chromatogram** (significant maxima) | High counts may indicate noisy / fragmented traces |
| **Median prominence of all significant peaks** | Less biased than “max peak only” |
| **Dynamic range** `max(intensity) / baseline_mu` | Scale-free alternative to σ-normalized S/N |

#### Sequencing coverage metric (extend existing Library Data)

Partially covered today by **Total count per entry** and **Average count per fraction** (user-configurable fraction count, default 96).

**Proposed coverage index (v2):**

```
coverage_index = library_total_reads / (n_library_entries × n_fractions)
```

where `library_total_reads` = sum of per-entry total counts for the selected channel. Display alongside mean per-fraction count so scientists can relate **depth** to **S/N**.

**Library diversity:** use `entries_used` from scan (compound/variant rows in DB). Document that this is **observed diversity in this dataset**, not theoretical library size from synthesis.

---

## 2. Recommended Architecture

### 2.1 Layered Design

```
┌─────────────────────────────────────────────────────────────┐
│  UI Layer                                                    │
│  chromatogram_visualizer_window.py  (+ peak analysis UI)    │
│  library_data_window.py             (+ pedigree section)    │
│  peak_analysis_dialog.py / peak_results_panel.py            │
│  pedigree_results_panel.py                                  │
│  help_window.py                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Application services (pure Python, testable)               │
│  src/core/peak_analysis_service.py                          │
│  src/core/pedigree_service.py                               │
│  src/core/pedigree_adapter.py    ← DB/Compound → kernel     │
│  src/core/analysis_export.py     ← CSV / image helpers      │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Domain models                                               │
│  src/models/peak_result.py                                  │
│  src/models/pedigree_result.py                              │
│  src/models/analysis_settings.py                            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Algorithm backend (choose one path — see §2.2)             │
│  lcseq._native (Rust via maturin)  OR  python fallback      │
└─────────────────────────────────────────────────────────────┘
```

**Rule:** UI never calls Rust directly. UI → service → backend adapter. This keeps GUI refactors isolated from algorithm changes.

### 2.2 Algorithm Backend Decision

| Option | Recommendation |
|--------|----------------|
| **A. Vendor `LC-Seq-New-master` as submodule, build with maturin** | **Preferred** — validated algorithms, score test + pedigree parity |
| B. Port algorithms to NumPy | High drift risk; only if Rust build is impossible |
| C. Subprocess `lcseq` CLI | Poor UX; avoid |

**Implementation pattern:**

```python
# src/core/lcseq_backend.py
def get_backend() -> LcseqBackend:
    try:
        from lcseq import find_peaks, evaluate_library, diagnose_class
        return NativeLcseqBackend(...)
    except ImportError:
        return UnavailableBackend(...)  # clear error in UI
```

**Build integration (dev + CI):**

1. Keep buddy repo at `LC-Seq-New-master/` (or git submodule `vendor/lcseq`).
2. Add `maturin develop --release` to developer setup docs.
3. Add optional `requirements-analysis.txt` noting `lcseq` is built locally, not PyPI.
4. App launches even if extension missing; analysis buttons show “Install analysis engine” message with build instructions.

#### 2.2.1 Plain-English: What “Rust build” means

The heavy math (peak picking, pedigree pruning) lives in **Rust** — a compiled language that runs much faster than Python for this workload. Python (your GUI) **calls into** that compiled piece, like a plugin.

| Who | What they do |
|-----|----------------|
| **Developer / you (once per machine)** | Install Rust tools, run one command (`maturin develop`) that compiles `LC-Seq-New-master` and links it to your Python venv. Takes a few minutes the first time. |
| **End-user scientist (ideal future)** | Double-click the LC-Seq installer; the compiled analysis plugin is **already included**. No Rust, no terminal. |
| **End-user scientist (interim)** | If the plugin is missing, the app still opens; analysis buttons explain that the “analysis engine” needs to be installed (IT or developer runs the build once). |

**Your preference:** Stay in Rust. Do **not** reimplement algorithms in Python. Plan for **prebuilt binaries** in a later packaging phase (PyInstaller / installer bundles the `lcseq` `.pyd` on Windows).

### 2.3 Data Adapter (Critical Path)

Buddy’s kernel expects:

```python
bbs_per_position: list[list[str]]   # allowed BBs per position, N→C
chromatograms: dict[tuple[str, ...], (rt: ndarray, intensity: ndarray)]
null_token: str
```

Your app stores:

```python
Compound(compound_id, metadata, data_points[{time, counts}])
```

**Adapter responsibilities** (`src/core/pedigree_adapter.py`):

1. **Read positional truncate from BB metadata columns** (required for pedigree)
   - Config provides ordered list `bb_position_columns`, e.g. `["BB1 Name", "BB2 Name", "BB3 Name"]` in **spreadsheet coupling order (C→N: BB1 = C-term)**.
   - For each compound row: `values_c_to_n = [metadata[col] for col in bb_position_columns]`.
   - **Kernel key (N→C):** `positions = tuple(reversed(values_c_to_n))`.
   - Skip row if any required BB cell is blank (unless importing as empty chromatogram — document behavior).
2. **Variant / isoform filter**
   - `filter_compounds_by_variant(compounds, selected_variants: list[str] | None)` — `None` or `"all"` means no filter; otherwise only matching `variant_label` rows.
3. **Build `chromatograms` dict** — key = N→C position tuple, value = `(rt, intensity)` for user-selected count channel.
4. **Build `bbs_per_position`** — for each index `i` in N→C order, union of non-null BB names observed at that position across filtered library rows.
5. **Time unit conversion** — if user selects minutes, divide RT by 60 when source is seconds (or honor `config.analysis_time_unit_source` if we store source unit in config later).

**Validation errors (show in UI):**

- BB columns not configured → pedigree/lineage disabled with link to Configure Spreadsheet.
- Row missing BB metadata → excluded from pedigree with count in summary “skipped rows.”

### 2.4 SpreadsheetConfig Extensions

Add DEL-specific fields to `SpreadsheetConfig`:

| Field | Default | Purpose |
|-------|---------|---------|
| `null_token` | `"AgxNull"` | Token in BB columns for unfilled positions |
| `library_cycle_count` | `3` | **2, 3, or 4** coupling cycles; controls how many of the four BB slots are active |
| `bb_position_columns` | four slots | BB1 (C-term) … BB4 (N-term); unused slots empty when cycle count < 4 |
| `analysis_time_unit` | `"seconds"` | Default time unit in analysis UI |
| `compound_variant_column` | (existing) | Isoform label column — already supported |

**Removed / deprioritized:** parsing compound ID by delimiter for pedigree (display-only).

**Configure Spreadsheet dialog:** new section **“DEL / Pedigree settings”**:

- Map each position: Position 1 (C-term) → column, Position 2 → column, …
- Or multi-select ordered list of BB column headers from spreadsheet
- Null token
- Help blurb: “BB1 is the first building block coupled (C-terminus). The analysis engine uses N→C order internally.”

Persist in existing config JSON via `to_dict` / `from_dict`.

### 2.4.1 AnalysisSettings (runtime UI, not spreadsheet)

| Field | Default | Purpose |
|-------|---------|---------|
| `count_channel` | *(none — user must pick)* | Which count series to analyze |
| `time_unit` | from config (`seconds`) | Seconds or minutes for this run |
| `alpha` | `1e-3` | Significance |
| `tolerance` | `30` if seconds, `0.5` if minutes | Replicate agreement window **in selected time unit** |
| `selected_variants` | `["all"]` or list of variant labels | Isoform filter for pedigree |

### 2.5 Result Persistence (Mirror Library Data Pattern)

Follow `library_metrics_store.py` conventions:

```
output/
  peak_analysis/
    .session/<db_stem>/
    <db_stem>_<timestamp>.json          # single-compound or batch cache
  pedigree_analysis/
    <db_stem>_<timestamp>.json
    <db_stem>_<timestamp>_tree.png
```

**Snapshot types:**

- `PeakAnalysisSnapshot` — compound_id, channel, settings, peaks[], baseline, lineage nodes (optional)
- `PedigreeAnalysisSnapshot` — settings, node records[], summary counts, tree_image_path, **`variant_label`** (or `comparison_id` when side-by-side)
- `PedigreeComparisonSnapshot` — optional wrapper holding 2+ `PedigreeAnalysisSnapshot` for linear vs cyclized

Enables: **Load last**, browse saved, batch pre-compute without holding everything in RAM, **isoform comparison** sessions.

---

## 3. UI Design Sketches

### 3.1 Chromatogram Visualizer — Toolbar Addition

Add a **“Peak Analysis”** button cluster in the plot toolbar area (next to existing export controls):

```
[ Peak Analysis ▼ ]  →  opens slide-out panel OR modeless side panel
```

**Panel sections (accordion):**

1. **Settings** — count channel (dropdown, required), time unit (seconds / minutes), α, tolerance (labeled with unit), [? Help]
2. **Actions**
   - `Pick peaks` — runs picker, overlays vertical markers + shaded integration windows
   - `Show baseline` — horizontal line at μ, optional shaded ±σ band
   - `Clear analysis` — remove overlays + table
3. **Lineage (null analysis)** — enabled when compound ID parses as valid truncate
   - `Analyze lineage` — opens **Lineage Analysis** window (stacked chromatogram panels per ancestor tier, like buddy’s `inspect_lineage`)
   - Export lineage figure / CSV
4. **Peak table** — `ttk.Treeview` below plot OR docked right (resizable)
5. **Export** — `Save plot…`, `Save peak table CSV…`

**Plot overlay conventions:**

| Element | Style |
|---------|--------|
| Picked peaks | Orange triangles at apex |
| Integration window | Light orange vertical band (valley bounds) |
| Baseline μ | Dashed grey horizontal |
| Lineage chosen RT (per tier) | Green vertical (from pedigree eval) |

**Single compound + single channel:** Disable “Pick peaks” if multiple series visible; show hint “Select one count channel for analysis.”

### 3.2 Lineage Analysis Window (Null Analysis for One Compound)

New window: `src/ui/lineage_analysis_window.py`

- Multi-panel matplotlib figure (shared x-axis): root → … → selected compound
- Each panel title: tier, class label, PASS/FAIL, chosen RT
- Reuses buddy diagnostic semantics via `diagnose_class` per tier (not reimplemented in Python)
- Buttons: **Export PNG**, **Export CSV**, **Open in Visualizer** (jump to that class’s replicate set)

**CSV columns (lineage export):**

`tier`, `class_label`, `node_id`, `status`, `chosen_rt`, `effective_threshold`, `n_replicates`, `n_with_signal`, `score_test_p`, `bayesian_posterior`, `member_compound_ids`

### 3.3 Library Data — Pedigree Section

Add new control block below existing metrics/plots:

```
── Pedigree (split-tree) analysis ──────────────────────────
  Count channel: [ user selects ▼ ]
  Time unit: ( ) Seconds  ( ) Minutes
  Tolerance: [ 30 ]  (units follow selection above)
  Significance (α): [0.001]
  Isoform: [ All ▼ ]  or ☑ Linear  ☑ Cyclized  (when variant column configured)
  [? Help]

  [ Run pedigree analysis ]   [ Compare isoforms side-by-side ]   (when 2+ variants selected)
  [ Export tree PNG ]   [ Export CSV ]   [ Load last ]   [ Browse saved… ]

  Status: No pedigree run yet.
  Summary: tier 0 pass=1 fail=0 pruned=0 | tier 1 …
  [Side-by-side: Linear summary | Cyclized summary] + thumbnails when comparing
```

**Compare isoforms:** Runs one pedigree per selected variant on the same channel/settings; displays two summaries and two tree images (or tabbed). Saved session folder: `pedigree_analysis/<db>_compare_linear_cyclized_<timestamp>/`.

**Worker thread** — same pattern as `_on_scan`: background thread, progress bar, marshal results to main thread.

**Do not block** on graphviz missing: show error “Install Graphviz to export tree images” with link in help doc.

---

## 4. Phased Implementation Plan

Each phase ends with **manual test checklist** + **automated tests**. Complete phases in order.

---

### Phase 0 — Foundation (No UI Yet)

**Objective:** Build plumbing so later phases only wire UI.

#### Step 0.1 — Vendor and build Rust extension

1. Confirm `LC-Seq-New-master/` layout matches analysis doc.
2. Document in `docs/DEVELOPER_SETUP.md`:
   - Install Rust toolchain
   - `cd LC-Seq-New-master && uv sync && maturin develop --release`
   - Verify: `python -c "import lcseq; print(lcseq.find_peaks)"`
3. Add smoke test `tests/test_lcseq_backend_available.py` (skip if not built).

#### Step 0.2 — Backend adapter module

Create `src/core/lcseq_backend.py`:

- `LcseqBackend` protocol: `find_peaks`, `diagnose_class`, `evaluate_library`
- `NativeLcseqBackend` wrapping `lcseq`
- `is_available() -> bool`
- Uniform exception type `AnalysisEngineError`

#### Step 0.3 — Domain models

Create `src/models/peak_result.py`:

```python
@dataclass
class PickedPeak:
    rt: float
    intensity: float
    area: float
    prominence: float
    p_value: float
    pct_area: float          # computed after all peaks picked
    left_rt: float           # integration bounds (for plotting)
    right_rt: float

@dataclass
class BaselineEstimate:
    mu: float
    sigma: float
    dispersion_r: float | None

@dataclass
class PeakAnalysisResult:
    compound_id: str
    channel: str
    settings: AnalysisSettings
    peaks: list[PickedPeak]
    baseline: BaselineEstimate
    computed_at: datetime
```

Create `src/models/analysis_settings.py`:

```python
@dataclass
class AnalysisSettings:
    alpha: float = 1e-3
    tolerance: float = 0.5      # minutes
    null_token: str = "AgxNull"
    time_unit: str = "minutes"
```

Create `src/models/pedigree_result.py` — thin wrapper around node dicts matching `NodeRecord` fields.

#### Step 0.4 — Pedigree adapter

Create `src/core/pedigree_adapter.py`:

| Function | Description |
|----------|-------------|
| `truncate_positions_from_metadata(compound, config) -> tuple[str, ...] \| None` | Read BB columns, reverse to N→C tuple |
| `infer_bbs_per_position(compounds, config) -> list[list[str]]` | Scan library in N→C index order |
| `build_chromatogram_map(compounds, channel, config, time_unit) -> dict` | Kernel input |
| `filter_by_variant(compounds, selected_variants) -> list[Compound]` | Isoform filter |
| `class_key_from_positions(positions, null_token) -> list[str]` | Non-null BBs in N→C order |

**Tests:** `tests/test_pedigree_adapter.py` with synthetic `Compound` metadata:

```python
metadata = {"BB1 Name": "AgxNull", "BB2 Name": "DNvl", "BB3 Name": "AgxNull"}
# → N→C tuple ("AgxNull", "DNvl", "AgxNull") after reverse of [BB1,BB2,BB3]
```

Include regression test: cassette BB name `DLeu-DLeu-Pro` in one BB column does not split on `-`.

#### Step 0.5 — SpreadsheetConfig extension

1. Add fields from §2.4 (`bb_position_columns`, `null_token`, `analysis_time_unit`).
2. Update `configure_spreadsheet_dialog.py` — **DEL / Pedigree** section: map BB1 (C-term) through BBn (N-term) columns.
3. Migration: missing keys in saved JSON → defaults; empty `bb_position_columns` = pedigree features hidden.

**Exit criteria Phase 0:**

- [ ] `pytest tests/test_pedigree_adapter.py tests/test_lcseq_backend_available.py` pass
- [ ] Can run in Python REPL: load compound from DB → adapter → `find_peaks` → list of peaks

---

### Phase 1 — Peak Picking in Visualizer (MVP)

**Objective:** User clicks **Pick peaks** on one compound, sees overlays + table, exports CSV/PNG.

#### Step 1.1 — Peak analysis service

Create `src/core/peak_analysis_service.py`:

```python
def analyze_peaks(compound: Compound, channel: str, settings: AnalysisSettings) -> PeakAnalysisResult:
    # extract rt, intensity via compound.get_time_series(channel)
    # call backend.find_peaks
    # compute pct_area per peak
    # estimate baseline via backend or exposed estimate_baseline (add to bindings if needed)
```

If baseline not exposed from Python, add thin `estimate_baseline` pyfunction to buddy `bindings.rs` **or** reimplement sigma-clip in Python service (document parity risk).

#### Step 1.2 — Export helpers

Create `src/core/analysis_export.py`:

- `peaks_to_dataframe(result) -> pd.DataFrame`
- `export_peaks_csv(result, path)`
- `export_figure_png(fig, path)`

#### Step 1.3 — UI panel

Create `src/ui/peak_analysis_panel.py` (CTk frame embeddable in visualizer):

- Settings widgets bound to `AnalysisSettings`
- Action buttons calling service on **currently selected table row** + **selected single channel**
- `PeakTable` widget (Treeview columns: `#`, RT, Height, Area, %Area, Prominence, p-value)
- Wire export buttons to `filedialog.asksaveasfilename`

#### Step 1.4 — Integrate into visualizer

Modify `chromatogram_visualizer_window.py`:

1. Add **Peak Analysis** toggle button in `_build_bottom_controls` or new toolbar row.
2. Show/hide `PeakAnalysisPanel` in grid row (adjust `grid_rowconfigure` weights).
3. On pick peaks: store `PeakAnalysisResult` on window state; call `_redraw_plot()` with overlays.
4. Extend `_redraw_plot` to draw peak markers and integration spans when analysis active.
5. Guard: if 0 or >1 count channels checked, disable pick with tooltip explanation.

#### Step 1.5 — Tests

- `tests/test_peak_analysis_service.py` — synthetic Gaussian peak chromatogram
- Manual: open visualizer → one compound → pick peaks → export CSV → verify columns

**Exit criteria Phase 1:**

- [ ] Peak table matches exported CSV
- [ ] %Area sums to ~100% for peaks with non-overlapping windows
- [ ] PNG export includes peak markers
- [ ] Works on index DB (on-demand parse path)

---

### Phase 2 — Baseline Display + Integration Polish

#### Step 2.1 — Show baseline action

- Draw μ line + optional light band (μ ± σ) on plot
- Add baseline row to peak table footer or separate read-only field: `Baseline μ = X, σ = Y`

#### Step 2.2 — Integrate peaks clarity

- Rename UI label **Integrate peaks** is automatic with pick — add help text: “Area is summed between valley boundaries on each side of the peak.”
- Table column tooltips via `attach_tooltip` on headers

#### Step 2.3 — Persist single-compound analysis

Create `src/core/peak_analysis_store.py` (mirror `library_metrics_store`):

- Save/load `PeakAnalysisSnapshot` JSON keyed by database + compound + channel

Add **“Load saved analysis”** if snapshot exists for current compound.

**Exit criteria Phase 2:**

- [ ] Baseline visible and documented in help
- [ ] Snapshot round-trip works

---

### Phase 2.5 — Library-Wide Signal-to-Noise (Bulk) in Library Data

**Objective:** Add bulk chromatographic S/N metrics to Library Data **before** lineage/pedigree, using Approach A (§1.4).

**Prerequisite:** Phase 1 peak/baseline engine (Rust or Python fallback) — **done**.

#### Step 2.5.1 — Per-entry S/N computation

Extend `library_metrics.py` (or `library_signal_quality.py` called from it):

```python
@dataclass
class EntrySignalStats:
    compound_id: str
    peak_height: float
    baseline_mu: float
    baseline_sigma: float
    snr_excess: float          # peak_height - baseline_mu
    snr_ratio: Optional[float] # snr_excess / baseline_sigma if sigma > 0
    peak_rt: float
    used_significance_filter: bool  # optional: only tallest *significant* peak
```

For each `ScannedEntry` in an existing library scan:

1. Run `estimate_baseline(intensity)` on selected channel.
2. Find tallest local maximum (optionally restrict to peaks with p < α using same picker as visualizer).
3. Store per-entry scalars; skip entries with &lt; 3 points.

#### Step 2.5.2 — Library aggregate metrics (new cards)

Register in `LIBRARY_METRIC_DEFINITIONS`:

| `metric_id` | Card title | Aggregates |
|-------------|------------|------------|
| `snr_excess_top_peak` | Top-peak signal above baseline — mean ± SD | mean, SD, n of `snr_excess` |
| `snr_ratio_top_peak` | Top-peak S/N ratio (÷ baseline σ) — mean ± SD | mean, SD, n of `snr_ratio` |
| `baseline_mu_library` | Baseline level — mean ± SD | mean, SD of `baseline_mu` |
| `peak_height_top` | Tallest peak height — mean ± SD | mean, SD of `peak_height` |

Optional: export per-entry CSV (`library_snr_per_entry.csv`) from Library Data.

#### Step 2.5.3 — UI

- Add metric checkboxes on Library Data scan dialog (default: S/N cards on for new runs).
- In-card help text explaining Approach A limitations (§1.4).
- User selects **one count channel** for S/N (or compute all configured channels like total-count metric).

#### Step 2.5.4 — Sequencing coverage (light touch)

- Document relationship to existing **avg count per fraction** card.
- Optional new card: **Library coverage index** = sum(entry totals) / (n_entries × fraction_count).

#### Step 2.5.5 — Tests

- `tests/test_library_snr_metrics.py` — synthetic chromatograms with known baseline + Gaussian peak
- Verify mean S/N matches hand calculation on fixture

**Exit criteria Phase 2.5:**

- [x] Scan 1k+ entries without UI freeze (background thread, existing pattern)
- [x] Mean ± SD displayed per channel; skipped entries counted
- [x] Help text states this is **bulk top-peak** S/N, not pedigree-validated product peak
- [x] Metric checkboxes (coverage + signal), α and fraction count controls
- [x] Per-entry signal CSV export
- [x] Signal histogram plots (SNR excess, baseline μ, significant peak count)
- [x] Formal definitions in `docs/LIBRARY_SIGNAL_QUALITY.md`
- [x] `tests/test_library_signal_quality.py`

---

### Phase 2.6 — Generate Library Report (PDF)

**Objective:** One-click **Generate library report** from Library Data that produces a well-organized PDF with methodology summary, selected metric cards, and embedded plots.

**Prerequisite:** Phase 2.5 signal-quality metrics and plots — **done**.

#### Step 2.6.1 — Report content model

Assemble from `LibraryComputationSnapshot` + session plot PNGs:

| Section | Source |
|---------|--------|
| Title page | Database name, timestamp, entry counts, α, fraction count |
| Methodology | Short summary + link to `docs/LIBRARY_SIGNAL_QUALITY.md` |
| Coverage metrics | Selected coverage cards (tables) |
| Signal quality | Selected signal cards with α noted |
| Plots | Embedded PNGs from `plot_results` |
| Per-entry appendix | Optional: attach exported CSV path or summary stats |

#### Step 2.6.2 — PDF engine

Use **reportlab** or **matplotlib PdfPages** (prefer reportlab for multi-section layout). New module: `src/core/library_report.py`.

```python
def generate_library_report_pdf(
    snapshot: LibraryComputationSnapshot,
    output_path: Path,
    *,
    plot_results: Sequence[PlotResult],
) -> Path: ...
```

#### Step 2.6.3 — UI

- Button: **Generate library report…** on Library Data (enabled when snapshot exists).
- File save dialog → PDF path.
- Progress on background thread for large libraries.

#### Step 2.6.4 — Tests

- `tests/test_library_report.py` — minimal snapshot → PDF file exists, page count ≥ 1.

**Exit criteria Phase 2.6:**

- [ ] PDF opens in standard viewer with title, metrics tables, and at least one plot when plots were generated
- [ ] Methodology section states Approach A vs future pedigree prominence (Phase 5.7)
- [ ] α and fraction count recorded on title page

---

### Phase 3 — Lineage (Null) Analysis per Compound

**Objective:** From visualizer, user runs **Analyze lineage** for selected compound.

#### Step 3.1 — Lineage service

Create `src/core/lineage_service.py`:

```python
def analyze_lineage(
    data_store: DataStore,
    compound: Compound,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
) -> LineageAnalysisResult:
    # 1. Leaf class key from compound's BB metadata (N→C), not compound ID string
    # 2. Enumerate ancestors (structural + chemical/cassette)
    # 3. evaluate_library on library filtered by selected isoform + channel
    # 4. Extract NodeRecords for ancestry chain
    # 5. For each tier panel: gather member chromatograms + effective_threshold
```

**Performance:** Pre-build `chromatogram_map` once per database scan; lineage only filters nodes. Consider requiring Library Data scan cache or lazy-build with progress dialog for first run.

#### Step 3.2 — Lineage window UI

Create `src/ui/lineage_analysis_window.py`:

- Call `lineage_service.analyze_lineage`
- Render multi-panel figure (port plotting approach from `LC-Seq-New-master/python/lcseq/debug.py` but feed from service data)
- Export PNG / CSV buttons

#### Step 3.3 — Visualizer integration

- **Analyze lineage** button in Peak Analysis panel (enabled when truncate parses)
- Menu item: **Analysis → Lineage for selected compound**

#### Step 3.4 — Tests

- `tests/test_lineage_service.py` with tiny synthetic library (2 BBs, N=2) — mock backend if needed
- Manual: pick full compound → lineage shows root + intermediates + leaf

**Exit criteria Phase 3:**

- [ ] Lineage CSV opens in Excel with readable columns
- [ ] Thresholds match full pedigree run for same compound
- [ ] Scientist help section “Null truncates & lineage” linked from window

---

### Phase 4 — Batch Peak Analysis (Optional but Planned)

**Objective:** Pre-compute peaks for many compounds → browse quickly.

#### Step 4.1 — Batch service

`batch_peak_analysis(data_store, compound_ids, channel, settings, progress_cb) -> dict[str, PeakAnalysisResult]`

Run in background thread from visualizer or library data.

#### Step 4.2 — Browse UI

- Dropdown: “Cached analysis for channel X” → jump compound to compound
- Filter: “only compounds with ≥1 peak”
- Store in `output/peak_analysis/<db>_batch_<timestamp>.json`

**Exit criteria Phase 4:**

- [ ] 100 compounds batch without UI freeze
- [ ] Switching table row loads cached result instantly

---

### Phase 5 — Full Pedigree Analysis in Library Data

**Objective:** Run split-tree on entire library; export tree PNG + CSV.

#### Step 5.1 — Pedigree service

Create `src/core/pedigree_service.py`:

```python
def run_pedigree_analysis(
    data_store: DataStore,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    channel: str,
    progress_cb,
) -> PedigreeAnalysisResult:
    chroms = build_chromatogram_map(...)
    bbs = infer_bbs_per_position(...)
    records = backend.evaluate_library(bbs, null_token, chroms, tolerance, alpha)
    summary = summarize_by_tier(records)
    return PedigreeAnalysisResult(records=records, summary=summary, ...)
```

#### Step 5.2 — Tree renderer module (modular)

Create `src/core/pedigree_render.py`:

- Primary: wrap buddy’s `render_pruned_tree` if graphviz installed
- Interface: `PedigreeRenderer.render(records, out_path, options) -> Path`
- Stub: `NullPedigreeRenderer` raising clear error if graphviz missing
- **Future:** `InteractivePedigreeRenderer` placeholder protocol for canvas-based tree

#### Step 5.3 — Pedigree store

Create `src/core/pedigree_analysis_store.py`:

- Save JSON (all node fields) + copy tree PNG
- `load_last`, `browse_saved` like library metrics

#### Step 5.4 — Library Data UI

Modify `library_data_window.py`:

1. Add pedigree control panel (§3.3)
2. `_on_run_pedigree` — thread + progress
3. Display summary labels + optional CTkImage thumbnail
4. Wire export / load / browse

#### Step 5.5 — CSV export schema

`pedigree_nodes.csv` columns:

`id`, `label`, `tier`, `kind`, `evaluated`, `passed`, `insufficient_data`, `chosen_rt`, `effective_threshold`, `score_test_rt`, `score_test_p`, `bayesian_pick`, `bayesian_posterior`, `n_replicates`, `n_replicates_with_signal`, `members`

#### Step 5.6 — Tests

- `tests/test_pedigree_service.py` — tiny fixture library
- `tests/test_pedigree_render.py` — skip if no graphviz
- Manual: run on sub-library (filter by metadata or temp “max compounds” dev setting); export PNG

**Exit criteria Phase 5:**

- [ ] Tier summary printed matches buddy CLI `_summarise` on same data
- [ ] Tree PNG color legend matches help doc
- [ ] 128k library: document expected runtime; consider sub-library filter for v1

#### Step 5.7 — Product-peak prominence (pedigree-validated S/N)

**Depends on:** Phase 5 pedigree run (Approach B, §1.4).

After `evaluate_library`, for each **leaf / product** node with `chosen_rt` and PASS (or evaluated with signal):

1. Map `chosen_rt` to nearest time index on that compound’s chromatogram.
2. Compute **prominence** (same as visualizer peak table).
3. Aggregate library mean ± SD of product prominence; report n_pass / n_total.

New Library Data metric card: **Product peak prominence (pedigree)** — enabled only when a pedigree snapshot exists for the same DB + channel, or computed in same session after pedigree completes.

Optional: compare bulk S/N (Phase 2.5) vs pedigree prominence in one dashboard view (“bulk vs validated”).

---

### Phase 6 — Embedded Help System

**Objective:** Plain-English docs inside the app.

#### Step 6.1 — Help content files

Create `src/help/` (or `docs/help/` bundled in package):

| File | Topic |
|------|--------|
| `peak_picking.md` | Baseline, NB test, what α means |
| `integration.md` | Area, height, % area |
| `null_truncates.md` | DEL truncates, BB1–BB3 vs display names, equivalence classes, null token |
| `lineage_analysis.md` | Ancestor chain, thresholds, PASS/FAIL |
| `pedigree_analysis.md` | Split-tree, pruning, colors, cassette BBs |
| `glossary.md` | RT, tolerance, replicate, sequencing failure |

Write at **~8th grade reading level**; use DEL examples (`AgxNull-DNvl-AgxNull`); avoid “Bayesian”, say “combines evidence from replicates”.

#### Step 6.2 — Help viewer window

Create `src/ui/help_window.py`:

- Read markdown files
- Render as CTkTextbox with simple formatting **or** lightweight HTML via `tkhtmlview` if acceptable dependency — **default: plain text + headings** to avoid new deps
- Sidebar topic list
- Deep-link: `HelpWindow.open_topic("peak_picking")`

#### Step 6.3 — Contextual help hooks

- `?` button in Peak Analysis panel → `peak_picking` + `integration`
- `?` in Lineage window → `lineage_analysis`
- `?` in Pedigree section → `pedigree_analysis`
- Main menu: **Help → Analysis guide**

#### Step 6.4 — Metric-style help_text

Extend `AnalysisSettings` / UI with one-line `help_text` strings (pattern from `library_metrics.py`) for tooltips on α, tolerance.

**Exit criteria Phase 6:**

- [ ] Scientist can answer “why did my compound fail?” using only in-app help
- [ ] No broken links between help topics

---

## 5. File / Module Checklist (New & Modified)

### New files

| Path | Phase |
|------|-------|
| `src/core/lcseq_backend.py` | 0 |
| `src/core/pedigree_adapter.py` | 0 |
| `src/core/peak_analysis_service.py` | 1 |
| `src/core/lineage_service.py` | 3 |
| `src/core/pedigree_service.py` | 5 |
| `src/core/pedigree_render.py` | 5 |
| `src/core/analysis_export.py` | 1 |
| `src/core/peak_analysis_store.py` | 2 |
| `src/core/pedigree_analysis_store.py` | 5 |
| `src/models/peak_result.py` | 0 |
| `src/models/pedigree_result.py` | 0 |
| `src/models/analysis_settings.py` | 0 |
| `src/ui/peak_analysis_panel.py` | 1 |
| `src/ui/lineage_analysis_window.py` | 3 |
| `src/ui/help_window.py` | 6 |
| `src/help/*.md` | 6 |
| `tests/test_pedigree_adapter.py` | 0 |
| `tests/test_peak_analysis_service.py` | 1 |
| `tests/test_lineage_service.py` | 3 |
| `tests/test_pedigree_service.py` | 5 |
| `docs/DEVELOPER_SETUP.md` | 0 |

### Modified files

| Path | Change |
|------|--------|
| `src/models/spreadsheet_config.py` | DEL fields |
| `src/ui/configure_spreadsheet_dialog.py` | DEL settings UI |
| `src/ui/chromatogram_visualizer_window.py` | Peak analysis panel + overlays |
| `src/ui/library_data_window.py` | Pedigree section |
| `src/ui/main_screen.py` | Help menu (optional) |
| `requirements.txt` or new `requirements-analysis.txt` | numpy (already via pandas), graphviz optional |
| Buddy `src/bindings.rs` | Optional: `estimate_baseline` export |

---

## 6. Parameters & Defaults (User-Facing)

Expose in UI with tooltips + help links:

| Parameter | Default | Label |
|-----------|---------|-------|
| α (alpha) | `0.001` | Significance threshold |
| Tolerance | `30` s or `0.5` min | Replicate agreement — **must match time unit** |
| Time unit | `seconds` | Seconds or minutes (user toggle) |
| Null token | `AgxNull` | From config (read-only in analysis UI) |
| Count channel | *(user selects)* | No implicit default |
| Isoform | All (if variants configured) | Which variant rows to include |

**Validation:**

- α in (0, 1]
- tolerance > 0
- Warn if time span < 3 points (“too few data points for peak picking”)

---

## 7. Error Handling & Edge Cases

| Situation | UX |
|-----------|-----|
| Rust extension not built | Modal with build instructions; analysis buttons disabled |
| Graphviz missing | Pedigree runs; tree export disabled with message; CSV still works |
| BB columns not configured | Pedigree/lineage disabled; link to Configure Spreadsheet |
| Row missing BB metadata | Excluded from run; count shown in summary |
| Index DB slow first load | Progress bar “Loading chromatograms…” |
| Full library pedigree (~128k rows) | Allowed in v1 with progress bar + cancel; expect minutes; optional filters later |
| Multiple variants (linear/cyclized) | User selects variant(s); side-by-side = multiple runs in one session |
| Cassette BB names with `-` | Stored whole in BB column; tuple keys — never split compound ID on `-` |

---

## 8. Testing Strategy

### Automated

- Unit tests for adapter, services (mock backend)
- Integration tests when `lcseq` available (mark `@pytest.mark.analysis`)
- Golden-file CSV comparison for tiny fixture library

### Manual scientist checklist (per release)

1. Load real index DB → visualizer → one compound → pick peaks → export CSV
2. Same compound → lineage → PNG matches expectations
3. Library Data → pedigree on Val/Phe/Leu subset → tree PNG + CSV
4. Open help from each analysis screen; confirm plain language
5. Load last pedigree snapshot after restart

---

## 9. Owner Q&A Archive (Elaborations)

### Q4 — What “full library pedigree on 128k compounds” meant

Pedigree analysis loads **every compound row** in your database, peak-picks each chromatogram, and walks the **entire null-truncation tree** (thousands of class nodes, not 128k leaves individually in the tree, but 128k chromatograms to read and pick).

On a large index database this means:

- **Long first run** — parsing chromatogram text for ~128k entries (similar to “Scan library” you already have).
- **Heavy CPU** — Rust makes the math fast, but I/O and parsing still take time.
- **Huge tree image** — a PNG of the full library tree may be unreadable; CSV export is still valuable.

**Decision:** v1 allows **full-database run** with honest progress UI (“Loading chromatogram 42,000 / 128,502…”, “Evaluating tier 2…”). Optional filters (subset of BBs, metadata query) can come later for quicker exploratory runs — not required to ship v1.

### Q6 — Rust build (summary)

See **§2.2.1**. Scientists should not need Rust long-term; developers compile once until we bundle prebuilt analysis in the installer.

### Resolved decisions table

| # | Decision |
|---|----------|
| 1 | **BB1/BB2/BB3 columns** are source of truth; reverse C→N columns to N→C for kernel; compound ID is display-only |
| 2 | **User picks count channel** every time (no hardcoded deduplicated default) |
| 3 | **Time unit toggle** seconds/minutes in analysis UI; tolerance follows unit |
| 4 | **Full library run OK** in v1 with progress; filters optional later |
| 5 | **Isoform select + side-by-side** comparison for pedigree (separate runs per variant) |
| 6 | **Stay in Rust**; bundle prebuilt plugin for end users when packaging |

---

## 10. Suggested Agent Execution Order

When approved, assign agents **one phase at a time**:

```
Phase 0 → Phase 1 → Phase 2 → Phase 2.5 (library bulk S/N) → Phase 2.6 (PDF report) → Phase 6 (help for peak + S/N)
       → Phase 3 (lineage) → Phase 5 (pedigree + product prominence §5.7) → Phase 6 (pedigree help)
       → Phase 4 (batch peaks) when single-compound path is stable
```

**Rationale:** Bulk S/N (2.5) informs experimental design immediately and reuses the peak engine; pedigree-validated prominence (5.7) refines the same question after lineage/pedigree infrastructure exists.

**Phase 6 can start in parallel** after Phase 0 (help content does not require UI).

Each agent handoff should include:

- Phase number and step IDs completed
- pytest output
- Screenshots or exported CSV/PNG paths from manual test
- Open questions encountered

---

## 11. Success Criteria (Overall)

The integration is complete when a DEL scientist can:

1. Open a chromatogram, pick peaks, read % integration, export table — **without reading Rust code**.
2. Run **Library Data → bulk S/N** and interpret mean top-peak signal vs baseline for sequencing-depth decisions.
3. Run lineage analysis on a compound, understand PASS/FAIL from colors + help text.
4. Run library pedigree from Library Data, export tree image + CSV, reload later; view **product-peak prominence** where pedigree validates product RT.
5. Get plain-English explanations for every analysis button they use.

---

*End of integration plan.*
