# Lineage analysis (Chromatogram Visualizer)

AKA Pedigree analysis - "Lineage Analysis" is a per-compound view of the null-truncation path: stacked chromatograms from **root → leaf**. View the synthetic lineage of a single compound by walking from the true null (null-null-null) to the complete molecule.

## How to run

1. Plot compound(s) in the **Chromatogram Visualizer**.
2. Click **prepare lineage** and wait for the calculation to finish.
3. With a compound(s) still selected in the compound window, click **Analyze lineage**.
4. Select **View lineage**.

Peak picking settings come from the peak panel (**Modern** / **Old-school**).

## PASS / FAIL

| Status | Meaning |
|--------|---------|
| **PASS** | Valid product peak beyond the last detected null truncate |
| **FAIL** | Valid product peak that overlaps exactly with a detected null truncate |
| **INSUFFICIENT DATA** | Not enough signal to call peaks |

## Threshold lines

- **Red dotted** — parent exclusion (± null RT threshold)
- **Green** — chosen / score-test RT
- **Purple dashed** — refined multi-replicate pick

## Export

PNG / PDF / SVG figures; CSV per tier. Multi-compound: **Export all…** / combined CSV options in the lineage viewer.

For library-wide Null RT threshold and RT assignment, use **Library Analysis → RT assignment**.
