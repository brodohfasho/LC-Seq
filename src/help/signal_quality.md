# Library signal quality

Bulk chromatographic QC across the whole library (**Library QC metrics** / **visualizations** tabs).

## Prerequisites

1. Open **Library Analysis** (config + DB ready).
2. Set picker / α / prominence / % area / fraction count on the **Library QC metrics** sidebar.
3. **Run library scan**.

Modern or Old-school picking can be selected on the QC sidebar (same engines as Peak Analysis).

## What “top peak” means

For each compound the scan estimates baseline, finds significant peaks, applies filters, then uses the **tallest remaining significant peak** for height / SNR / dynamic range.

That peak is **not always the DEL product** — treat values as library-wide screening, not product ID.

## Coverage

**Total count**, **avg per fraction**, and **library coverage index** reflect sequencing depth. Fraction count (default 96) feeds the coverage index.

## Pedigree prominence (separate)

After **Pedigree** RT assignment, **`product_prominence.csv`** in the analysis bundle reports prominence at the **validated product RT** for passed compounds. It is not a QC metrics card.

Formal definitions: `docs/LIBRARY_SIGNAL_QUALITY.md` in the repository.
