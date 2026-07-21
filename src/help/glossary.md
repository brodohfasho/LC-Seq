# Glossary

**α (alpha)** — Significance cutoff for **Modern** peak picking. Lower = stricter. Height and area tests both use α/2.

**Direct pick mode** — RT assignment that peak-picks each product RT without a full pedigree walk (**paper Methods**; typically with Old-school picking).

**Equivalence class** — Truncates that share the same non-null BB sequence (padding-invariant).

**Index database** — SQLite file storing raw chromatogram text; parsed on demand.

**Isoform** — Variant of the same primary ID (e.g. linear vs cyclized) when a variant column is configured.

**Library Analysis** — Dashboard for library scan, QC, RT assignment, pedigree and split-tree views (formerly “Library Data”).

**Minimum RT** — Old-school picker cutoff: ignore signal below this RT. **Not** the null RT threshold.

**Modern peak picking** — NB/Poisson significance on local maxima (default). Parameters: α, min prominence, min % area. Added after the accompanying paper.

**Null RT threshold** — Max allowed RT difference vs truncation references for verification / parent exclusion. Set on **Library Analysis → RT assignment**.

**Null token** — Placeholder BB for an unfilled position (e.g. `AgxNull`).

**Old-school peak picking** — Height gate + Gaussian centroid fit (**paper Methods**). Parameters: min height factor, fit width, max σ, minimum RT.

**Pedigree mode** — RT assignment via full-library null-truncation walk (Rust `evaluate_library`). Post-paper improvement.

**Pedigree visualization** — Radial / tier-ring figure of the null-truncation pedigree.

**Product peak prominence** — Prominence at the pedigree-chosen product RT for passed full compounds (`product_prominence.csv` in the analysis bundle).

**Prominence** — Peak height minus the higher adjacent valley. Also a post-detection quality filter.

**Replicate** — One library member of a BB class (multiple rows if isoforms are configured).

**Retention time (RT)** — Elution time. Keep the same unit (seconds or minutes) across RT settings.

**RT assignment** — Library-wide step that resolves product RTs (**Pedigree** or **Direct pick**) and feeds split-tree / exports.

**SNR excess** — Peak height − baseline μ.

**SNR ratio** — SNR excess ÷ baseline σ.

**Split-tree visualization** — Combinatorial BB tree (full library or BB1 branch) built after RT assignment.

**Tier** — Coupling depth in the pedigree. Tier 0 = all-null root; highest tier = full products.
