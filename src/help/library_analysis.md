# Library Analysis overview

**Library Analysis** is the library-wide dashboard (main screen, after spreadsheet + database are ready). It is separate from the **Chromatogram Visualizer** (per-compound plots).

## Tabs (recommended order)

| Tab | What it does | Needs |
|-----|--------------|--------|
| **Library QC metrics** | Metric cards (coverage, SNR, …); loads chromatograms as needed | Config + DB |
| **Library QC visualizations** | Library-level plots; reuses or loads chromatogram cache | Config + DB |
| **RT assignment** | Assign product RTs: **Direct pick** or **Pedigree** | DB + BB columns |
| **Pedigree visualization** | Null-truncation pedigree figure (tier-ring / Graphviz) | Pedigree RT run |
| **Split-tree visualization** | Combinatorial BB tree (full / BB1 branch) | Either RT mode |

## Typical workflow

1. Configure DEL fields if needed (**Configure Spreadsheet → 5 — DEL / Pedigree**). See **DEL library setup**.
2. **Calculate metrics** / **Generate plots** (chromatograms load automatically and stay cached).
3. Review QC metrics / plots.
4. **Run RT assignment** (sidebar: mode + peak picker).
5. Open Pedigree and/or Split-tree tabs and click **Generate plot**; export as needed.

Use **Clear cached chromatograms** on the metrics sidebar to free memory/disk or force a fresh reload for the **current** library. Only one chromatogram cache (`.pkl`) is kept on disk—loading a new library’s QC cache replaces any previous one. **Generate report…** is on the top bar.

## Analysis modes (RT assignment)

| Mode | Role |
|------|------|
| **Direct pick** | Peak-pick each product RT (**paper Methods**, usually with **Old-school** picking) |
| **Pedigree** | Full-library null-truncation walk (post-paper; requires Rust `lcseq`) |

## Exports (RT assignment tab)

- **Export RTs…** — spreadsheet of assigned RTs / verification columns  
- **Export analysis bundle…** — split-tree CSVs, optional grids, audit file (see **Export analysis bundle glossary**)  

Session caches live under `output/library_data/.session/` (see INSTALL.md for moving between machines).
