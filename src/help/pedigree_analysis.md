# Library pedigree (split-tree)

## What it is

**Pedigree analysis** evaluates the **entire library** at once. It walks every equivalence class from the all-null root through each coupling tier and decides which branches are chemically consistent (retention time increases along the synthesis path).

## Split-tree figure

The tree places the **root at the centre** with tiers in rings outward. Colors:

- **Grey** — root (all null)
- **Light / dark green** — passed class or compound
- **Red** — synthesis failure (signal but no valid peak past parent)
- **Yellow** — insufficient data (no usable peaks in replicates)

Without Graphviz installed, LC-Seq shows a **matplotlib tier-ring preview** with the same colors.

## Tier summary

The **Pedigree** tab lists pass / fail / pruned counts per tier. **Pruned** nodes were never evaluated because a parent failed.

## Product peak prominence (Phase 5.7)

After pedigree runs, LC-Seq measures **prominence** at the chosen product RT for each **passed full compound**. This is more meaningful than “tallest peak on the trace” because the RT comes from pedigree validation.

Compare with **Library Data → signal quality** bulk metrics, which use the tallest significant peak and may not be the product.

## Settings

Same as lineage: count channel, time unit, tolerance, α. Optional **isoform** filter when a variant column is configured.

## Export

- **Export pedigree CSV** — one row per node.
- **Export tree PNG** — save figure (Graphviz or matplotlib).
- **Save pedigree** — JSON snapshot + tree image for **Load last** / **Browse**.

## Large libraries

Index databases with 100k+ rows may take several minutes on first run while compounds are parsed.
