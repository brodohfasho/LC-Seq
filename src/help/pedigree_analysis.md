# Library pedigree analysis

Evaluates the **entire library** on the null-truncation tree: each class must show a consistent peak **after** its parent (within **Null RT threshold**).

## How to run

**Library Analysis → RT assignment → Analysis mode: Pedigree → Run RT assignment.**

Requires BB columns configured (**Spreadsheet Configuration and Database Build**). Needs the Rust `lcseq` engine.

RT assignment does not generate or open the figure automatically. After it finishes, open
**Pedigree visualization**, choose the display options, and click **Generate plot**.

## Outputs

| Tab / action | Result |
|--------------|--------|
| **Pedigree visualization → Generate plot** | Radial / tier-ring figure + tier summary |
| **Split-tree visualization** | Combinatorial BB tree (also works after Direct pick) |
| **Export pedigree CSV…** | One row per node (`bb_cycle_*` columns) |
| **Export tree PNG…** | Pedigree figure |
| **Export analysis bundle…** | Split-tree CSVs + optional `product_prominence.csv` |

## Colors (pedigree figure)

Grey = root · Light/dark green = passed class/compound · Red = synthesis failure · Yellow = insufficient data.

Without Graphviz, LC-Seq uses a matplotlib tier-ring preview. Display controls: **Pedigree visualization figure**.

## Sidebar settings

Count channel · time unit · Modern/Old-school picker · Null RT threshold · (modern) min prominence / min % area · optional isoform filter.

Large index DBs may take minutes on first parse.
