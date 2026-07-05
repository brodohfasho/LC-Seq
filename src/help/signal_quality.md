# Library signal quality (bulk metrics)

## Purpose

**Library Analysis** summarizes **chromatographic quality across the whole library** to help judge sequencing depth and noise. Metrics and plots live on the **Library QC metrics** and **Library QC visualizations** tabs.

## Prerequisites

1. Open **Library Analysis** from the main screen (requires configured spreadsheet and database).
2. Set **Peak significance α**, **Min prominence**, **Min % area**, and **Fraction count** on the **Library QC metrics** sidebar (signal-quality parameters are shared with RT assignment when you use the RT assignment sidebar values for pedigree runs).
3. Click **Run library scan** in the top bar.

## Bulk top-peak metrics (Approach A)

For each compound trace the program:

1. Estimates baseline μ and σ.
2. Finds **statistically significant peaks** with the **modern** picker (p < α).
3. Applies **min prominence** and **min % area** filters when configured.
4. Uses the **tallest remaining significant peak** for height, SNR, and dynamic range.

**Important:** The tallest peak is not always the DEL product. Treat these as library-wide screening values.

## Pedigree-validated prominence

After **Run RT assignment** in **Pedigree** mode, **`product_prominence.csv`** in the **Export analysis bundle** lists prominence at the pedigree-chosen product RT for passed full compounds only.

That metric is **not** shown on the QC metrics tab; compare bulk scan metrics with bundle prominence when judging product signal.

## Coverage metrics

**Total count per entry** and **average count per fraction** relate to sequencing depth. **Library coverage index** combines them into one number per channel.

## α and fraction count

Set **Peak significance α** on the **Library QC metrics** sidebar before **Run library scan**. Fraction count is used for coverage index (default 96).

See `docs/LIBRARY_SIGNAL_QUALITY.md` in the repository for formal definitions.
