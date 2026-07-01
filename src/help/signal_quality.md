# Library signal quality (bulk metrics)

## Purpose

These metrics summarize **chromatographic quality across the whole library** to help judge sequencing depth and noise.

## Bulk top-peak metrics (Approach A)

For each compound trace the program:

1. Estimates baseline μ and σ.
2. Finds **statistically significant peaks** (p < α).
3. Uses the **tallest significant peak** for height, SNR, and dynamic range.

**Important:** The tallest peak is not always the DEL product. Treat these as library-wide screening values.

## Pedigree-validated prominence

After **Run pedigree analysis**, see **Product peak prominence** on the Pedigree tab. That metric uses the RT chosen by pedigree for passed products only.

## Coverage metrics

**Total count per entry** and **average count per fraction** relate to sequencing depth. **Library coverage index** combines them into one number per channel.

## α and fraction count

Set **Peak significance α** on the Library Data sidebar before **Run library scan**. Fraction count is used for coverage index (default 96).

See `docs/LIBRARY_SIGNAL_QUALITY.md` in the repository for formal definitions.
