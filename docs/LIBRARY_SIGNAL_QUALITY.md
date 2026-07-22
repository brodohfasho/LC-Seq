# Library signal quality metrics — definitions

How **Library Analysis** computes bulk chromatographic signal-quality statistics (top-peak vs baseline). Pedigree-validated **product peak prominence** is available separately after **Pedigree** RT assignment (`product_prominence.csv` in the analysis bundle).

All signal-quality metrics share:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| **α (alpha)** | `0.001` | Significance threshold for *significant* peaks. A local maximum is kept only if `p-value < α`, where p-value is the minimum of height and area tail tests under the baseline noise model (same engine as Chromatogram Visualizer → Peak Analysis). **Lower α → fewer significant peaks.** |
| **Min prominence** | `5` | After detection, drop peaks below this prominence (`0` = off). Same post-filter as RT assignment / Chromatogram Visualizer. |
| **Min % area** | `3` | After detection, drop peaks below this share of total detected peak area (`0` = off). |
| **Baseline** | σ-clipped median | Same algorithm as peak picking: iterative removal of points above `mean + 2σ`, then median → **μ**; sample σ of kept points → **σ**. |
| **Minimum points** | 3 | Entries with fewer than 3 time points are skipped for signal metrics. |

Peak picking algorithm (**Modern** or **Old-school**) is chosen on the Library QC / RT assignment sidebars. The accompanying paper used **Old-school** picking.

---

## Per-entry calculations (each compound × count channel)

### Tallest peak (not necessarily significant)

1. Find all **local maxima** on the raw count trace.
2. **Tallest peak height** = maximum intensity at those maxima (0 if none).
3. **Tallest peak RT** = retention time at that apex.

### Bulk signal-to-noise (top peak)

| Scalar | Formula |
|--------|---------|
| **SNR excess** | `tallest_peak_height − baseline_μ` |
| **SNR ratio** | `(tallest_peak_height − baseline_μ) / baseline_σ` when σ > 0 |
| **Dynamic range** | `tallest_peak_height / baseline_μ` when μ > 0 |

**Note:** The tallest peak may be an impurity or artifact, not the DEL product.

### Significant peaks (α- and quality-filter-dependent)

1. Run the full peak picker with the configured **α** (Modern) or Old-school parameters.
2. Apply shared **min prominence** / **min % area** filters (same as RT assignment).
3. **Significant peak count** = number of peaks remaining.
4. **Has significant peak** = count ≥ 1.
5. **Max significant prominence** = max prominence among significant peaks (0 if none).
6. **Median significant prominence** = median prominence among significant peaks (empty if none).
7. **Tallest significant peak height** = max apex height among significant peaks (0 if none).
8. **Tallest significant SNR excess** = tallest significant height − baseline_μ.

Baseline μ/σ are estimated from the raw trace and are **not** affected by these peak filters.

Prominence = apex height minus the higher of the two adjacent valley intensities (same as the peak table).

---

## Library-wide aggregates

For each metric below, LC-Seq computes **mean**, **sample standard deviation**, and **n** (entries with valid values) per selected count channel.

| Metric ID | Card title | Per-entry source |
|-----------|------------|------------------|
| `baseline_mu_library` | Baseline level (μ) | `baseline_μ` |
| `baseline_sigma_library` | Baseline spread (σ) | `baseline_σ` |
| `peak_height_top` | Tallest peak height | tallest local maximum |
| `snr_excess_top_peak` | Top-peak SNR excess | SNR excess |
| `snr_ratio_top_peak` | Top-peak SNR ratio | SNR ratio |
| `dynamic_range_top_peak` | Dynamic range (top peak) | dynamic range |
| `fraction_with_significant_peak` | Fraction with ≥1 significant peak | 1.0 if has peak else 0.0 (mean = fraction) |
| `significant_peak_count_mean` | Significant peaks per entry | significant peak count |
| `max_significant_prominence_mean` | Max prominence (significant peaks) | max significant prominence |
| `median_significant_prominence_mean` | Median prominence (significant peaks) | median significant prominence (skipped if none) |
| `tallest_significant_snr_excess_mean` | Top significant peak SNR excess | tallest significant SNR excess |

### Sequencing coverage

| Metric ID | Formula |
|-----------|---------|
| `total_count_per_entry` | Sum of counts across time per entry |
| `avg_count_per_fraction` | `total_count_per_entry / fraction_count` |
| `library_coverage_index` | `Σ(entry totals) / (n_entries × fraction_count)` |

**fraction_count** defaults to 96 (user-configurable in Library Analysis → Library QC metrics).

---

## Related exports

- **Per-entry signal CSV** from Library Analysis (one row per compound; α, picker, and quality-filter settings in the header comment).
- **Library report PDF** — metrics, plots, and optional pedigree / split-tree sections.
- **`product_prominence.csv`** — prominence at pedigree-chosen product RTs after **Pedigree** RT assignment (inside **Export analysis bundle…**).

See in-app help (**Library signal quality**, **Peak picking**, **Export analysis bundle glossary**).
