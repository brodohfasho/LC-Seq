# Export analysis bundle glossary

Files from **Export analysis bundle…** on the RT assignment tab.  
CSVs are **UTF-8 with BOM** (Excel-friendly for characters like β).

## Bundle contents

| File | Contents |
|------|----------|
| `split_tree_products.csv` | One row per full product (no null BBs) |
| `split_tree_audit_metadata.csv` | Run settings + counters (`field` / `value`) |
| `split_tree_summary_report.csv` | Pass/fail by BB1 hub, BB2, and BB1+BB2 arms |
| `split_tree_flagged_building_blocks.csv` | Residues in repeated majority-failure contexts |
| `grids/del_grid_bb1_*.xlsx` | BB2×BB3 matrices per BB1 (**3-cycle only**) |
| `product_prominence.csv` | Optional; only after **Pedigree** RT assignment |

No `grids/` folder for libraries with fewer than three cycles.

## Shared conventions

- **BB1…BBn** — coupling order (BB1 = C-terminus / first coupled).
- **bb*_index** — display indices (auto or BB index CSV); null token = 0, omitted from product rows.
- **rt (s|min)** — product RT in the audit `analysis_time_unit`.
- **rt_verified** / **pedigree_passed** — `TRUE`/`FALSE` text (blank pedigree if not run).

**Null RT threshold** ≠ Old-school **Minimum RT** (verification width vs picker cutoff).

## Key audit fields

`rt_analysis_mode` (`direct_pick` \| `pedigree`) · `peak_picking_algorithm` · `null_rt_threshold` · `count_channel` · picker parameters · `n_products` / `n_rt_verified` / `n_pedigree_passed`.

## Summary & flagged BB CSVs

**Summary** scopes: `cycle_1`, `cycle_2`, `cycle_1_and_2` (majority-fail arms). `majority_failed` when pass rate < 50%.

**Flagged BBs** aggregate hub / global / coupling failures with `commentary`.

## Grids (3-cycle)

One workbook per non-null BB1. Rows = BB2, columns = BB3. Cells: green fill (`PASS`), red fill (`FAIL`), or blank (no product).

## product_prominence.csv

Pedigree mode only. Columns include `compound_id`, `chosen_rt`, `prominence`, `passed`, `bb_cycle_*`, `channel`.
