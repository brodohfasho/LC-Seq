# Library pedigree analysis

Evaluates the **entire library** on the null-truncation tree: each class must show a consistent peak **after** its parent (within **Null RT threshold**).

## How to run

**Library Analysis → RT assignment → Analysis mode: Pedigree → Run RT assignment.**

Requires BB columns configured (**DEL library setup**) and a prior library scan. Needs the Rust `lcseq` engine.

**Paper note:** accompanying paper used **Direct pick** + **Old-school** picking. Pedigree mode is a later improvement.

## Outputs

| Tab / action | Result |
|--------------|--------|
| **Pedigree visualization** | Radial / tier-ring figure + tier summary |
| **Split-tree visualization** | Combinatorial BB tree (also works after Direct pick) |
| **Export pedigree CSV…** | One row per node (`bb_cycle_*` columns) |
| **Export tree PNG…** | Pedigree figure |
| **Export analysis bundle…** | Split-tree CSVs + optional `product_prominence.csv` |
| **Save results** | JSON snapshot + tree image |

## Colors (pedigree figure)

Grey = root · Light/dark green = passed class/compound · Red = synthesis failure · Yellow = insufficient data.

Without Graphviz, LC-Seq uses a matplotlib tier-ring preview. Display controls: **Pedigree visualization figure**.

## Product prominence

After Pedigree RT assignment, prominence at the chosen product RT for **passed** full compounds goes into **`product_prominence.csv`** (analysis bundle only — no separate button). Bulk QC “tallest peak” metrics may not be the product.

## Sidebar settings

Count channel · time unit · Modern/Old-school picker · Null RT threshold · min prominence / min % area · optional isoform filter.

Large index DBs may take minutes on first parse.
