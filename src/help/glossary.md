# Glossary

**Retention time (RT)** — Time when a compound elutes from the column. Must use the same unit as **tolerance** (seconds or minutes).

**Tolerance** — Allowed RT difference when matching peaks across replicates or parent/child tiers.

**α (alpha)** — Significance cutoff for peak picking. Lower = stricter.

**Replicate** — One encoded library member with the same BB class (may appear as multiple rows if you have isoforms).

**Null token** — Placeholder BB value for an unfilled position (e.g. `AgxNull`).

**Tier** — Coupling cycle in the pedigree. Tier 0 = all-null root; highest tier = full products.

**Equivalence class** — Set of truncates sharing the same non-null BB sequence (padding-invariant).

**Prominence** — Peak height minus the higher adjacent valley. Robust measure of how visible a peak is.

**SNR excess** — Peak height minus baseline μ.

**SNR ratio** — SNR excess divided by baseline σ.

**Index database** — SQLite file storing raw chromatogram text; parsed on demand (slower first access).

**Isoform** — Variant of the same compound (e.g. linear vs cyclized) when a variant column is configured.
