# Library pedigree (split-tree)

## What it is

**Pedigree analysis** evaluates the **entire library** at once. It walks every equivalence class from the all-null root through each coupling tier and decides which branches are chemically consistent (retention time increases along the synthesis path).

In **Library Analysis**, choose **Pedigree** under **Analysis mode** on the **RT assignment** tab, then **Run RT assignment**. Results feed the **Pedigree visualization** and **Split-tree visualization** tabs and DEL-cycle exports.

## Split-tree figure

The tree places the **root at the centre** with tiers in rings outward. Colors:

- **Grey** — root (all null)
- **Light / dark green** — passed class or compound
- **Red** — synthesis failure (signal but no valid peak past parent)
- **Yellow** — insufficient data (no usable peaks in replicates)

Without Graphviz installed, LC-Seq shows a **matplotlib tier-ring preview** with the same colors.

See **Pedigree split-tree figure** for display controls and layout details.

## Tier summary

The **Pedigree visualization** tab lists pass / fail / pruned counts per tier. **Pruned** nodes were never evaluated because a parent failed.

## Product peak prominence

After **Pedigree** RT assignment, LC-Seq measures **prominence** at the chosen product RT for each **passed full compound**. This is more meaningful than “tallest peak on the trace” because the RT comes from pedigree validation.

Compare with **Library Analysis → Library QC metrics / visualizations**, which use the tallest significant peak from the library scan and may not be the product.

**Export:** prominence is written to **`product_prominence.csv`** inside **Export analysis bundle…** on the RT assignment tab (when pedigree assignment produced prominence data). There is no separate prominence export button in the current UI.

## Settings (RT assignment sidebar)

- **Count channel** and **Time unit**
- **Peak picking** — **Modern** or **Old-school** (see **Peak picking** help)
- **Null RT threshold** — verification and parent/child RT matching width
- **Min prominence** / **Min % area** — quality filters (shared with modern picker and scan QC when set on this tab)
- Optional **isoform** filter when a variant column is configured

## Export

From **Library Analysis**:

| Action | Output |
|--------|--------|
| **Export pedigree CSV…** (Pedigree visualization tab) | One row per node, with **bb_cycle_1** … **bb_cycle_N** columns |
| **Export tree PNG…** | Split-tree figure (Graphviz or matplotlib) |
| **Export RTs…** (RT assignment tab) | Spreadsheet with assigned RTs and verification columns |
| **Export analysis bundle…** | DEL-cycle CSVs, grids (3-cycle), audit metadata, and optional **product_prominence.csv** |
| **Save results** / **Load last** / **Browse…** | JSON snapshot + tree image for session restore |

## Large libraries

Index databases with 100k+ rows may take several minutes on first run while compounds are parsed.

Use **Help ▾** on the RT assignment tab for split-tree figure details and the **Export analysis bundle glossary**.
