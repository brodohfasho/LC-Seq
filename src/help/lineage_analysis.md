# Lineage analysis

## What it is

**Lineage analysis** shows how one full product fits the null-truncation pedigree. You see a stack of chromatograms from **root → leaf** (all-null → your compound).

## How to run it

1. Plot **one or more compounds** in the Chromatogram Visualizer.
2. Optionally **Pick peaks** first (fills **Suspected peak ID** after analysis).
3. Click **Analyze lineage** (runs in the background for all plotted compounds).
4. Click **View lineage** to open the viewer. With multiple compounds, pick from the **Compounds** list on the left.

## Batch export

When several compounds were analyzed, use **Export all figures…**, **Export combined CSV…**, **Export CSVs per compound…**, or **Export all to folder…** in the lineage viewer.

## PASS / FAIL

Each tier is evaluated for retention-time consistency with its parent:

- **PASS** — a valid product peak was found past the parent threshold.
- **FAIL** — signal existed but no acceptable peak past the parent.
- **INSUFFICIENT DATA** — not enough sequencing signal to call peaks.

## Threshold lines

- **Red dotted** — parent exclusion zone (± tolerance).
- **Green** — chosen / score-test retention time.
- **Purple dashed** — refined pick when multiple replicates support it.

## Settings

- **Count channel** — which count trace to analyze.
- **Tolerance** — how close RTs must be (same unit as time display).
- **α** — peak significance for replicate peak calling.

## Export

From the lineage viewer: export PNG/PDF/SVG (vector) or CSV summary per tier.
