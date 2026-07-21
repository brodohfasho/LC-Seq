# Lineage analysis

Per-compound view of the null-truncation path: stacked chromatograms from **root → leaf**.

## How to run

1. Plot compound(s) in the **Chromatogram Visualizer**.
2. Open **Peak analysis**; optionally **Pick peaks**.
3. **Analyze lineage** (background; all plotted compounds).
4. **View lineage** — pick a compound from the list if several were analyzed.

Picker settings come from the peak panel (**Modern** / **Old-school**).

## PASS / FAIL

| Status | Meaning |
|--------|---------|
| **PASS** | Valid product peak past the parent threshold |
| **FAIL** | Signal present but no acceptable peak past parent |
| **INSUFFICIENT DATA** | Not enough signal to call peaks |

## Threshold lines

- **Red dotted** — parent exclusion (± null RT threshold)
- **Green** — chosen / score-test RT
- **Purple dashed** — refined multi-replicate pick

## Export

PNG / PDF / SVG figures; CSV per tier. Multi-compound: **Export all…** / combined CSV options in the lineage viewer.

For library-wide Null RT threshold and RT assignment, use **Library Analysis → RT assignment**.
