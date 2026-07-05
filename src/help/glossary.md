# Glossary

**Retention time (RT)** — Time when a compound elutes from the column. Use the same unit as **Null RT threshold** and other RT settings (seconds or minutes).

**Null RT threshold** — Maximum allowed RT difference between a full product and its expected truncation references for null verification to pass. Configured on **Library Analysis → RT assignment**. Also used as the parent exclusion width in lineage and pedigree evaluation (± threshold around the parent RT).

**α (alpha)** — Significance cutoff for **modern** peak picking. Lower = stricter. Both height and area tests must pass at α/2.

**Modern peak picking** — NB/Poisson significance on local maxima (default). Parameters: α, min prominence, min % area.

**Old-school peak picking** — Legacy scipy height gate + Gaussian centroid fit. Parameters: min height factor, Gaussian fit width, max σ, minimum RT.

**Minimum RT** — Old-school picker cutoff: ignore chromatogram signal below this RT. **Not** the same as null RT threshold.

**Replicate** — One encoded library member with the same BB class (may appear as multiple rows if you have isoforms).

**Null token** — Placeholder BB value for an unfilled position (e.g. `AgxNull`).

**Tier** — Coupling cycle in the pedigree. Tier 0 = all-null root; highest tier = full products.

**Equivalence class** — Set of truncates sharing the same non-null BB sequence (padding-invariant).

**Prominence** — Peak height minus the higher adjacent valley. Used as a quality filter and, after pedigree RT assignment, measured at the validated product RT in `product_prominence.csv`.

**Product peak prominence** — Prominence at the pedigree-chosen product RT for passed full compounds. Exported in the analysis bundle when pedigree RT assignment was run.

**SNR excess** — Peak height minus baseline μ.

**SNR ratio** — SNR excess divided by baseline σ.

**Library Analysis** — Dashboard for library scan, QC metrics/plots, RT assignment, pedigree visualization, and split-tree visualization (formerly “Library Data”).

**RT assignment** — Library-wide step that resolves product RTs (pedigree or direct pick) and builds DEL-cycle verification data.

**Index database** — SQLite file storing raw chromatogram text; parsed on demand (slower first access).

**Isoform** — Variant of the same compound (e.g. linear vs cyclized) when a variant column is configured.
