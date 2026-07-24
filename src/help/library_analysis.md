# Library Analysis Module

**Library Analysis** is a module that can be accessed from the main screen after a spreadsheet is loaded and configured and a database is successfully constructed. **Library Analysis** performs several critical library-wide analyses, including QC metrics (signal-to-noise assessment, compound representation across fractions, etc.), RT assignment, and assessment of library-wide reactivity through split-tree analysis.

## Tabs

1. Library QC Metrics - Calculates various QC metrics to gauge the quality of your LC-seq experiment (signal to noise ratio, counts per fraction, etc.)
2. Library QC Visualizations - Plots displaying per-fraction data related to the library QC metrics. Requires the user to calculate library QC metrics prior to generating the visualizations.
3. RT Assignment - Primary module which picks retention times for each LC-seq chromatogram. Two modes analytical modes (direct pick, pedigree) and two peak picking modes (modern, old school).
4. Pedigree Visualization - Visualization of library-wide pedgiree analysis.
5. Split-tree Visualization - Visualization of split-tree analysis.

## Analysis modes (RT assignment)

| Mode | Role |
|------|------|
| **Direct pick** | Picks the latest-eluting (highest RT), signficant peak as the product peak. |
| **Pedigree** | Full-library null-truncation walk - picks retention times by progressing from the true null (null-null-null) to the respective double truncates, single truncates, and then finally to the complete molecule. |

**Direct pick** was developed as the initial framework for picking product peaks across the library.
**Pedigree** is much more sophisticated and uses full null-progression logic to provide a more accurate and robust method for determinging the peak most likely associated with the complete molecule.

*We strongly advise the user to use Pedigree analysis for automated library-wide RT assignment, if possible (requires null encoding at each position).*

## Exports 

- **Export RTs…** — spreadsheet of assigned RTs / verification columns  
- **Export analysis bundle…** — split-tree CSVs, optional grids, audit file (see **Export analysis bundle glossary**)  
- **Various Plot Exports** - Most plots (Library QC, Pedigree, Split Tree) can be exported, including the zoomed-in BB1 nodes of the split-tree plot.