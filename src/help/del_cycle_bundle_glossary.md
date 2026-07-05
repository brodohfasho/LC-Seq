# Export analysis bundle glossary

This guide describes the files written by **Export analysis bundle…** on the RT assignment tab. Field definitions are the same for every export; only row counts and grid files depend on your library.

## Bundle contents

| File | Description |
|------|-------------|
| `del_cycle_products.csv` | One row per full-length product (no null building blocks). |
| `del_cycle_audit_metadata.csv` | Run configuration, metadata, and audit counters (key/value rows). |
| `del_cycle_summary_report.csv` | Pass/fail statistics by cycle-1 hub, cycle-2 BB, and BB1+BB2 arms. |
| `del_cycle_flagged_building_blocks.csv` | Residues flagged repeatedly as majority-failure contexts. |
| `grids/del_grid_bb1_*.xlsx` | Color-coded BB2 × BB3 matrices, one workbook per cycle-1 BB (**3-cycle libraries only**). |
| `product_prominence.csv` | Optional. Included automatically when **Pedigree** RT assignment produced product prominence (no separate export button). |

For libraries with fewer than three coupling cycles, no `grids/` folder is created.

## Conventions used in all tables

**BB1, BB2, BB3, BB4** — Building-block names at each coupling cycle (spreadsheet order). BB1 is the first coupled position (C-terminus in peptide/DEL convention). Active columns match your library depth (`bb_cycle_1` … `bb_cycle_N`).

**bb1_index … bb4_index** — Display index for tree labeling (from automatic alphabetical order or your optional BB index CSV). The null token uses index 0 and is omitted from product rows.

**rt (s)** or **rt (min)** — Retention time for the full product in the analysis time unit recorded in the audit metadata (`analysis_time_unit`).

**rt_verified** — `TRUE` / `FALSE` — product RT matches expected truncation pattern within the configured null RT threshold (notebook-style DEL-cycle verification).

**pedigree_passed** — `TRUE` / `FALSE` when pedigree split-tree analysis marked the product as passed; blank if pedigree was not run for this library.

**TRUE / FALSE** — Text booleans in CSV files (not 0/1).

## del_cycle_products.csv

| Field | Definition |
|-------|------------|
| `bb_cycle_1` … `bb_cycle_N` | Building-block name at each coupling cycle. |
| `rt (s)` or `rt (min)` | Product retention time in the active analysis time unit (column name matches `analysis_time_unit` in the audit file). |
| `rt_verified` | RT verification outcome (`TRUE` / `FALSE`). |
| `pedigree_passed` | Pedigree pass outcome (`TRUE` / `FALSE`), or blank if unavailable. |
| `bb1_index` … `bb4_index` | Display index for the BB name in that coupling column. |

## del_cycle_audit_metadata.csv

Two columns: `field`, `value`. One row per metadata key. When you export after an RT assignment run, this file records the **same parameters shown on the RT assignment tab** plus summary counters from the analysis.

### Run configuration (when exported from Library Analysis)

| Field | Definition |
|-------|------------|
| `exported_at_utc` | ISO timestamp when the bundle was written. |
| `library_cycle_count` | Number of coupling cycles (2–4). |
| `null_token` | Spreadsheet token for unused coupling positions. |
| `analysis_time_unit` | `seconds` or `minutes` — unit for RT assignment inputs and for time-scaled picker parameters. |
| `count_channel` | Count channel used for peak picking / RT resolution. |
| `peak_picking_algorithm` | `modern` or `old_school`. |
| `rt_analysis_mode` | `direct_pick` (direct pick) or `pedigree` (full-library pedigree RT assignment). |
| `modern_alpha` | Modern picker significance α (modern mode only). |
| `min_prominence` | Minimum peak prominence filter (modern mode only). |
| `min_pct_area` | Minimum peak area percent filter (modern mode only). |
| `gaussian_min_height_factor` | Old-school min height factor (old-school mode only). |
| `gaussian_fit_width_seconds` or `gaussian_fit_width_minutes` | Old-school Gaussian fit width in the active time unit. |
| `gaussian_max_sigma_seconds` or `gaussian_max_sigma_minutes` | Old-school maximum Gaussian σ in the active time unit. |
| `gaussian_minimum_rt_seconds` or `gaussian_minimum_rt_minutes` | Old-school **Minimum RT** picker cutoff in the active time unit (peaks below this RT are ignored). |
| `null_rt_threshold` | **Null RT Threshold** on the RT assignment tab — maximum allowed RT difference between a full product and its expected truncation references for null verification to pass. |
| `null_rt_threshold_unit` | Unit for `null_rt_threshold` (`seconds` or `minutes`). |

**Important:** `null_rt_threshold` is **not** the old-school **Minimum RT** picker setting. For example, with time unit **seconds**, a Null RT Threshold of **30** means verification passes when the product RT is more than 30 seconds away from conflicting truncation RTs; a Minimum RT of **600** means peak picking ignores chromatogram signal below 600 s.

| Field | Definition |
|-------|------------|
| `rt_threshold` | Legacy alias for `null_rt_threshold` (same numeric value). Kept for older scripts. |

### Analysis counters

| Field | Definition |
|-------|------------|
| `rt_source` | How product RTs were resolved (`peak_pick`, `pedigree`, `metadata`, or mixed labels). |
| `peak_picking_algorithm` | Algorithm recorded on the DEL tree (may differ from audit config if data were reused). |
| `n_rt_from_pedigree` | Products whose RT came from pedigree analysis. |
| `n_rt_from_peak_pick` | Products whose RT came from direct peak picking. |
| `n_rt_from_metadata` | Products whose RT came from spreadsheet metadata. |
| `n_rt_verified_pedigree_agree` | Products where RT verification and pedigree pass agree. |
| `full_null_rt` | RT (s) of the all-null truncation reference. |
| `n_products` | Full product rows in `del_cycle_products.csv`. |
| `n_rt_verified` | Products passing RT verification. |
| `n_pedigree_passed` | Products passing pedigree analysis. |

## del_cycle_summary_report.csv

| Field | Definition |
|-------|------------|
| `scope` | `cycle_1` = all products under one BB1; `cycle_2` = all products with one BB2; `cycle_1_and_2` = one BB1+BB2 arm (only majority-fail arms). |
| `bb_cycle_1` | Cycle-1 building-block name (when applicable). |
| `bb_cycle_2` | Cycle-2 building-block name (when applicable). |
| `bb1_index` | Display index for `bb_cycle_1`. |
| `bb2_index` | Display index for `bb_cycle_2`. |
| `total_products` | Full products in this grouping. |
| `n_rt_verified_pass` | Products passing RT verification. |
| `n_rt_verified_fail` | Products failing RT verification. |
| `pass_pct` | 100 × pass / total (one decimal). |
| `majority_failed` | `TRUE` when `pass_pct` < 50% (majority of products failed verification). |
| `flag_reason` | Short explanation when `majority_failed` is `TRUE`. |

## del_cycle_flagged_building_blocks.csv

| Field | Definition |
|-------|------------|
| `bb_name` | Building-block residue name. |
| `bb_index` | Display index for `bb_name`. |
| `coupling_cycle` | `1` or `2` — which cycle this row summarizes. |
| `total_products` | Products containing this BB at `coupling_cycle`. |
| `n_rt_verified_pass` | Pass count for those products. |
| `n_rt_verified_fail` | Fail count for those products. |
| `pass_pct` | Overall pass rate for this BB at this cycle. |
| `library_pass_pct` | Library-wide RT verification pass rate. |
| `pass_pct_vs_library` | `pass_pct` minus `library_pass_pct` (negative = worse than average). |
| `n_independent_flags` | Count of separate majority-failure contexts (hub, global, couplings). |
| `flagged_as_cycle_1_hub` | `TRUE` if failed as a cycle-1 root hub. |
| `flagged_as_cycle_2_global` | `TRUE` if failed globally at cycle 2. |
| `n_flagged_cycle1_cycle2_couplings` | Number of failed BB1+BB2 arms involving this residue. |
| `flagged_coupling_details` | Semicolon-separated list of failed coupling arms. |
| `commentary` | Plain-language summary of why this BB was flagged. |

## grids/ — BB2 × BB3 Excel workbooks (3-cycle libraries)

One `.xlsx` file per non-null cycle-1 BB (filename: `del_grid_bb1_{index}_{name}.xlsx`). Sheet name: **RT verified**.

**Layout**

- Row 1 (columns B onward): cycle-3 BB names (BB3).
- Column A (rows 2 onward): cycle-2 BB names (BB2).
- Cell (BB2 row, BB3 column): one full product BB1+BB2+BB3 combination.

**Cell values and colors**

| Value / fill | Meaning |
|--------------|---------|
| `PASS` on green fill | RT verification succeeded for that triplet. |
| `FAIL` on red fill | Product exists but RT verification failed. |
| (blank) | No full product row for that combination in the library. |

**How to read**

Pick one workbook (fixed BB1). Scan across a row to see which BB3 partners work with a given BB2; scan down a column for all BB2 partners with a given BB3. Red clusters highlight problematic coupling neighborhoods.

Open in Excel or compatible spreadsheet software to see fill colors.

## product_prominence.csv (optional)

Written when **Run RT assignment** used **Pedigree** mode and prominence could be measured at validated product RTs. **Direct pick** runs do not produce this file (no pedigree node records). There is no standalone “Export product prominence” menu item — use **Export analysis bundle…**.

| Field | Definition |
|-------|------------|
| `compound_id` | Library compound identifier. |
| `node_id` | Pedigree tree node id for the full product. |
| `chosen_rt` | Retention time chosen by pedigree evaluation (active time unit). |
| `prominence` | Peak prominence at `chosen_rt` on the compound chromatogram (counts). |
| `passed` | `1` if the product passed pedigree; `0` otherwise (file lists passed products with measured prominence). |
| `bb_cycle_1` … `bb_cycle_N` | Building-block names at each coupling cycle. |
| `channel` | Count channel used for the pedigree run. |

## Related help

Use **Help** on the RT assignment tab for split-tree visualization and this glossary. Pedigree tier-ring details are under **Pedigree analysis** and **Split-tree figure**.
