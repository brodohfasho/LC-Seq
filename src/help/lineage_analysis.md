# Lineage analysis

## What it is

**Lineage analysis** shows how one full product fits the null-truncation pedigree. You see a stack of chromatograms from **root → leaf** (all-null → your compound).

## How to run it

1. Plot **one or more compounds** in the **Chromatogram Visualizer**.
2. Open the **Peak analysis** panel; optionally **Pick peaks** first (fills **Suspected peak ID** after analysis).
3. Click **Analyze lineage** (runs in the background for all plotted compounds).
4. Click **View lineage** to open the viewer. With multiple compounds, pick from the **Compounds** list on the left.

Peak picking uses the algorithm and quality filters set in the peak panel (**Modern** or **Old-school**). See **Peak picking** help for the difference.

## Batch export

When several compounds were analyzed, use **Export all figures…**, **Export combined CSV…**, **Export CSVs per compound…**, or **Export all to folder…** in the lineage viewer.

## PASS / FAIL

Each tier is evaluated for retention-time consistency with its parent:

- **PASS** — a valid product peak was found past the parent threshold.
- **FAIL** — signal existed but no acceptable peak past the parent.
- **INSUFFICIENT DATA** — not enough sequencing signal to call peaks.

## Threshold lines

- **Red dotted** — parent exclusion zone (± null RT threshold; fixed defaults in the peak panel unless you run library-wide RT assignment with custom settings).
- **Green** — chosen / score-test retention time.
- **Purple dashed** — refined pick when multiple replicates support it.

## Settings (peak panel)

- **Count channel** — which count trace to analyze.
- **Peak picking algorithm** — modern (α) or old-school (Gaussian parameters).
- **Min prominence** / **Min % area** — quality filters after detection.

For library-wide analysis with an explicit **Null RT threshold**, use **Library Analysis → RT assignment**.

## Export

From the lineage viewer: export PNG/PDF/SVG (vector) or CSV summary per tier.
