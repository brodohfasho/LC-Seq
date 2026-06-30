//! Peak picking with NB significance testing.
//!
//! Pipeline:
//! 1. Sigma-clip baseline → (μ, σ, dispersion r).
//! 2. Find local maxima (strict-left, ≥-right; plateau aware).
//! 3. For each maximum, walk to the first local minimum on each side → boundaries.
//! 4. Compute height, area over the window, prominence.
//! 5. Run dual upper-tail tests against the baseline:
//!    - height_test: `P(X ≥ height | NB(r, p_bg))`
//!    - area_test:   `P(X ≥ area   | NB(width × r, p_bg))` (sum of width iid NBs)
//!
//!    Accept the peak if `min(p_height, p_area) < α / 2` — Bonferroni correction for
//!    two tests at family-wise level α. Conservative for positively-correlated tests
//!    (height and area share the apex bin) but it gives the user-stated α as an upper
//!    bound on the per-peak false-positive rate.
//!
//! Returns peaks in ascending rt order with the surviving p-value attached.

use crate::peaks::baseline::{estimate_baseline, Baseline};
use crate::peaks::significance::p_at_least;

/// A picked peak with statistics. `intensity` is the peak height, `area` is the
/// summed signal over the valley-bounded window, `prominence` is the standard
/// scipy-style definition (height − max(left base, right base)).
#[derive(Debug, Clone, PartialEq)]
pub struct Peak {
    pub rt: f64,
    pub intensity: f64,
    pub area: f64,
    pub prominence: f64,
    pub p_value: f64,
}

/// Find peaks in a chromatogram.
///
/// `rt` and `intensity` are parallel arrays; `rt` must be ascending. `alpha` is the
/// per-peak family-wise FDR threshold across the two tests (height + area); each
/// individual test runs at `alpha / 2` (Bonferroni). Sensible defaults are
/// 0.001–0.01 for sequencing-derived chromatograms.
pub fn find_peaks(rt: &[f64], intensity: &[f64], alpha: f64) -> Vec<Peak> {
    assert_eq!(
        rt.len(),
        intensity.len(),
        "rt and intensity must have the same length"
    );
    if rt.len() < 3 {
        return Vec::new();
    }

    let baseline = estimate_baseline(intensity);
    let maxima = local_maxima(intensity);

    let mut peaks = Vec::with_capacity(maxima.len());
    for idx in maxima {
        let height = intensity[idx];
        if height <= baseline.mu {
            continue;
        }
        let (left, right) = valley_bounds(intensity, idx);
        let width = (right - left + 1) as f64;
        let area: f64 = intensity[left..=right].iter().sum();
        let prominence = compute_prominence(intensity, idx);

        let p_height = p_at_least(height, baseline.mu, baseline.dispersion_r);
        let p_area = p_at_least(area, baseline.mu * width, scaled_dispersion(&baseline, width));
        let p_value = p_height.min(p_area);

        // Bonferroni correction for two tests at family-wise level alpha.
        if p_value < alpha / 2.0 {
            peaks.push(Peak {
                rt: rt[idx],
                intensity: height,
                area,
                prominence,
                p_value,
            });
        }
    }
    peaks
}

/// Sum of `width` iid NB(r, p) is NB(width·r, p), so the dispersion scales linearly.
fn scaled_dispersion(b: &Baseline, width: f64) -> Option<f64> {
    b.dispersion_r.map(|r| r * width)
}

fn local_maxima(intensity: &[f64]) -> Vec<usize> {
    let n = intensity.len();
    if n < 3 {
        return Vec::new();
    }
    let mut peaks = Vec::new();
    let mut i = 1usize;
    while i < n - 1 {
        if intensity[i - 1] < intensity[i] {
            let mut j = i;
            while j + 1 < n && intensity[j + 1] == intensity[i] {
                j += 1;
            }
            if j + 1 < n && intensity[j + 1] < intensity[i] {
                peaks.push(i);
            }
            i = j + 1;
        } else {
            i += 1;
        }
    }
    peaks
}

/// Walk left/right from the peak until intensity stops descending. The endpoints are
/// the valley positions or the array edges.
fn valley_bounds(intensity: &[f64], peak_idx: usize) -> (usize, usize) {
    let n = intensity.len();
    let mut left = peak_idx;
    while left > 0 && intensity[left - 1] < intensity[left] {
        left -= 1;
    }
    let mut right = peak_idx;
    while right + 1 < n && intensity[right + 1] < intensity[right] {
        right += 1;
    }
    (left, right)
}

fn compute_prominence(intensity: &[f64], peak_idx: usize) -> f64 {
    let h = intensity[peak_idx];
    let mut left_min = h;
    let mut k = peak_idx;
    while k > 0 {
        k -= 1;
        if intensity[k] > h {
            break;
        }
        if intensity[k] < left_min {
            left_min = intensity[k];
        }
    }
    let mut right_min = h;
    let mut k = peak_idx;
    while k + 1 < intensity.len() {
        k += 1;
        if intensity[k] > h {
            break;
        }
        if intensity[k] < right_min {
            right_min = intensity[k];
        }
    }
    h - left_min.max(right_min)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn empty_yields_no_peaks() {
        assert!(find_peaks(&[], &[], 0.001).is_empty());
    }

    #[test]
    fn flat_zero_signal_yields_no_peaks() {
        let rt: Vec<f64> = (0..20).map(|i| i as f64).collect();
        let intensity = vec![0.0; 20];
        assert!(find_peaks(&rt, &intensity, 0.001).is_empty());
    }

    #[test]
    fn single_clear_peak_above_baseline() {
        // Baseline ~3, peak height 100.
        let rt: Vec<f64> = (0..15).map(|i| i as f64).collect();
        let intensity = vec![3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0, 2.0, 3.0];
        let peaks = find_peaks(&rt, &intensity, 0.001);
        assert_eq!(peaks.len(), 1);
        assert!(approx(peaks[0].rt, 6.0));
        assert!(approx(peaks[0].intensity, 100.0));
        assert!(peaks[0].p_value < 0.001);
    }

    #[test]
    fn two_separated_peaks() {
        let rt: Vec<f64> = (0..21).map(|i| i as f64).collect();
        let intensity = vec![
            2.0, 3.0, 2.0, 1.0, 2.0, 50.0, 2.0, 1.0, 2.0, 3.0, 2.0,
            1.0, 2.0, 80.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 2.0,
        ];
        let peaks = find_peaks(&rt, &intensity, 0.001);
        assert_eq!(peaks.len(), 2);
        assert!(approx(peaks[0].rt, 5.0));
        assert!(approx(peaks[1].rt, 13.0));
    }

    #[test]
    fn small_noise_peak_filtered_out() {
        // Baseline ~3, real peak height 100, plus a noise "peak" of height 4 (same as baseline σ range).
        let rt: Vec<f64> = (0..21).map(|i| i as f64).collect();
        let intensity = vec![
            3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0,
            2.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0, 2.0, 3.0, 2.0,
        ];
        let peaks = find_peaks(&rt, &intensity, 0.001);
        assert_eq!(peaks.len(), 1);
        assert!(approx(peaks[0].rt, 6.0));
    }

    #[test]
    fn returned_peaks_in_ascending_rt() {
        let rt: Vec<f64> = (0..30).map(|i| i as f64).collect();
        let mut intensity = vec![2.0; 30];
        intensity[5] = 50.0;
        intensity[15] = 60.0;
        intensity[25] = 40.0;
        let peaks = find_peaks(&rt, &intensity, 0.001);
        for w in peaks.windows(2) {
            assert!(w[0].rt < w[1].rt);
        }
    }

    #[test]
    fn area_test_catches_broad_peak_with_modest_height() {
        // A wide bump (height = 8 above baseline ~2 for many points).
        // Each point alone might not be height-significant, but the area is.
        let rt: Vec<f64> = (0..21).map(|i| i as f64).collect();
        let intensity = vec![
            2.0, 2.0, 3.0, 4.0, 6.0, 7.0, 8.0, 7.0, 6.0, 4.0, 3.0,
            2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0,
        ];
        let peaks = find_peaks(&rt, &intensity, 0.05);
        assert!(!peaks.is_empty(), "expected at least the broad bump to be picked");
    }

    #[test]
    fn alpha_controls_strictness() {
        let rt: Vec<f64> = (0..15).map(|i| i as f64).collect();
        let intensity = vec![3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0, 2.0, 3.0];
        let strict = find_peaks(&rt, &intensity, 1e-12);
        let loose = find_peaks(&rt, &intensity, 0.5);
        assert!(loose.len() >= strict.len());
    }

    #[test]
    #[should_panic]
    fn mismatched_length_panics() {
        let _ = find_peaks(&[0.0, 1.0, 2.0], &[0.0, 1.0], 0.001);
    }
}
