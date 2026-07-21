# Library Analysis overview

**Library Analysis** is the library-wide dashboard (main screen, after spreadsheet + database are ready). It is separate from the **Chromatogram Visualizer** (per-compound plots).

## Tabs (recommended order)

| Tab | What it does | Needs |
|-----|--------------|--------|
| **Library QC metrics** | Scan chromatograms; metric cards (coverage, SNR, …) | Config + DB |
| **Library QC visualizations** | Library-level plots from the scan | Scan |
| **RT assignment** | Assign product RTs: **Direct pick** or **Pedigree** | Scan + BB columns |
| **Pedigree visualization** | Null-truncation pedigree figure (tier-ring / Graphviz) | Pedigree RT run |
| **Split-tree visualization** | Combinatorial BB tree (full / BB1 branch) | Either RT mode |

## Typical workflow

1. Configure DEL fields if needed (**Configure Spreadsheet → 5 — DEL / Pedigree**). See **DEL library setup**.
2. **Run library scan** (top bar).
3. Review QC metrics / plots.
4. **Run RT assignment** (sidebar: mode + peak picker).
5. Open Pedigree and/or Split-tree tabs; export as needed.

## Analysis modes (RT assignment)

| Mode | Role |
|------|------|
| **Direct pick** | Peak-pick each product RT (**paper Methods**, usually with **Old-school** picking) |
| **Pedigree** | Full-library null-truncation walk (post-paper; requires Rust `lcseq`) |

## Exports (RT assignment tab)

- **Export RTs…** — spreadsheet of assigned RTs / verification columns  
- **Export analysis bundle…** — split-tree CSVs, optional grids, audit file (see **Export analysis bundle glossary**)  
- **Save results** — pedigree JSON + tree image for later reload  

Session caches live under `output/library_data/.session/` (see INSTALL.md for moving between machines).
