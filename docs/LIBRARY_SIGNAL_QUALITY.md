# Library Signal Quality Metrics — Definitions

This document defines **how** Library Data computes bulk chromatographic signal-quality
statistics. These are **Approach A** metrics (bulk top-peak vs baseline). Pedigree-validated
product-peak prominence is planned for Phase 5.7.

All signal-quality metrics share:

| Parameter | Default | Meaning |
|-----------|---------|---------|
| **α (alpha)** | `0.001` | Significance threshold for *significant* peaks. A local maximum is kept only if `p-value < α`, where p-value is the minimum of height and area tail tests under the baseline noise model (same engine as Chromatogram Visualizer → Pick peaks). **Lower α → fewer significant peaks.** |
| **Baseline** | σ-clipped median | Same algorithm as peak picking: iterative removal of points above `mean + 2σ`, then median → **μ**; sample σ of kept points → **σ**. |
| **Minimum points** | 3 | Entries with fewer than 3 time points are skipped for signal metrics. |

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

### Significant peaks (α-dependent)

1. Run the full peak picker with the configured **α**.
2. **Significant peak count** = number of peaks returned.
3. **Has significant peak** = count ≥ 1.
4. **Max significant prominence** = max prominence among significant peaks (0 if none).
5. **Median significant prominence** = median prominence among significant peaks (empty if none).
6. **Tallest significant peak height** = max apex height among significant peaks (0 if none).
7. **Tallest significant SNR excess** = tallest significant height − baseline_μ.

Prominence = apex height minus the higher of the two adjacent valley intensities (same as peak table).

---

## Library-wide aggregates

For each metric below, LC-Seq computes **mean**, **sample standard deviation**, and **n**
(entries with valid values) per selected count channel.

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

### Sequencing coverage (existing + index)

| Metric ID | Formula |
|-----------|---------|
| `total_count_per_entry` | Sum of counts across time per entry |
| `avg_count_per_fraction` | `total_count_per_entry / fraction_count` |
| `library_coverage_index` | `Σ(entry totals) / (n_entries × fraction_count)` |

**fraction_count** defaults to 96 (user-configurable in Library Data).

---

## Exports

- **Per-entry CSV** (`Export per-entry signal CSV…`): one row per compound with all per-entry scalars and α recorded in the header comment.
- **PDF library report** (planned Phase 2.6): formatted report with metrics, plots, and methodology summary.

---

## Future (Phase 5.7)

**Product peak prominence (pedigree):** prominence at pedigree `chosen_rt` for PASS compounds only.
