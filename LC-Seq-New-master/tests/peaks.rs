//! Integration tests for the NB-based peak picker on synthetic chromatograms.
//!
//! Each test puts the signal on a small constant baseline (~3 counts) so the sigma-clipping
//! step has something to estimate from. With a true zero baseline the NB test would mark
//! every local max as significant (P(X≥1 | μ=0) = 0 by convention).

use lcseq::peaks::find_peaks;

const ALPHA: f64 = 1e-3;
const BASELINE: f64 = 3.0;

/// Synthetic Gaussian peak (height `amp`, width `sigma`, mean `mu`) layered onto a
/// constant baseline of `BASELINE` counts.
fn gaussian_on_baseline(n: usize, mu: f64, sigma: f64, amp: f64) -> (Vec<f64>, Vec<f64>) {
    let rt: Vec<f64> = (0..n).map(|i| i as f64).collect();
    let intensity: Vec<f64> = rt
        .iter()
        .map(|&t| {
            let z = (t - mu) / sigma;
            BASELINE + amp * (-0.5 * z * z).exp()
        })
        .collect();
    (rt, intensity)
}

#[test]
fn picks_one_gaussian() {
    let (rt, intensity) = gaussian_on_baseline(101, 50.0, 5.0, 100.0);
    let peaks = find_peaks(&rt, &intensity, ALPHA);
    assert_eq!(peaks.len(), 1);
    assert!((peaks[0].rt - 50.0).abs() < 1e-6);
    assert!(peaks[0].p_value < ALPHA);
}

#[test]
fn picks_two_well_separated_gaussians() {
    let (rt, mut intensity) = gaussian_on_baseline(201, 50.0, 4.0, 80.0);
    let (_, second) = gaussian_on_baseline(201, 150.0, 4.0, 60.0);
    for i in 0..intensity.len() {
        // `second` already includes its own BASELINE; subtract it once so the combined
        // chromatogram still has BASELINE under the troughs, not 2 * BASELINE.
        intensity[i] += second[i] - BASELINE;
    }
    let peaks = find_peaks(&rt, &intensity, ALPHA);
    assert_eq!(peaks.len(), 2);
    assert!((peaks[0].rt - 50.0).abs() < 1e-6);
    assert!((peaks[1].rt - 150.0).abs() < 1e-6);
}

#[test]
fn alpha_drops_subthreshold_gaussian() {
    // Big Gaussian of height 100 and a small one of height 4 (basically baseline-level).
    let (rt, mut intensity) = gaussian_on_baseline(201, 50.0, 4.0, 100.0);
    let (_, small) = gaussian_on_baseline(201, 150.0, 4.0, 4.0);
    for i in 0..intensity.len() {
        intensity[i] += small[i] - BASELINE;
    }
    let peaks = find_peaks(&rt, &intensity, ALPHA);
    // The big one is unmistakable; the small one shouldn't survive the NB test.
    assert!(peaks.iter().any(|p| (p.rt - 50.0).abs() < 1e-6));
    assert!(!peaks.iter().any(|p| (p.rt - 150.0).abs() < 1e-6),
            "expected small bump near baseline to be filtered, picks={:?}", peaks);
}
