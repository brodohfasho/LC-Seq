//! Sigma-clipped baseline estimation and Negative-Binomial dispersion.
//!
//! For sequencing-derived chromatograms each datapoint is an integer count drawn from
//! a count distribution. We estimate the background level by iteratively removing
//! positive outliers (peaks) at the `sigma` cutoff and taking the median + std of the
//! survivors. The dispersion `r` is then estimated by method of moments from the
//! baseline region — `r = μ²/(σ² − μ)`. If the data is under-dispersed (σ² ≤ μ),
//! we return `None` and the caller falls back to Poisson.

const DEFAULT_SIGMA: f64 = 2.0;
const MAX_ITER: usize = 10;
const MIN_BASELINE_POINTS: usize = 3;

/// Background statistics inferred from the chromatogram.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Baseline {
    pub mu: f64,
    pub sigma: f64,
    /// `None` ⇒ under-dispersed → caller should use Poisson(mu).
    pub dispersion_r: Option<f64>,
}

/// Sigma-clip the chromatogram to its baseline region and estimate (μ, σ, dispersion).
pub fn estimate_baseline(intensity: &[f64]) -> Baseline {
    let mut keep: Vec<f64> = intensity.iter().copied().filter(|x| !x.is_nan()).collect();
    if keep.len() < MIN_BASELINE_POINTS {
        return Baseline { mu: 0.0, sigma: 0.0, dispersion_r: None };
    }
    for _ in 0..MAX_ITER {
        let n = keep.len() as f64;
        let mean: f64 = keep.iter().sum::<f64>() / n;
        let var: f64 = keep.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n;
        let cutoff = mean + DEFAULT_SIGMA * var.sqrt();
        let new_keep: Vec<f64> = keep.iter().copied().filter(|&x| x <= cutoff).collect();
        if new_keep.len() == keep.len() || new_keep.len() < MIN_BASELINE_POINTS {
            break;
        }
        keep = new_keep;
    }
    let mu = median(&mut keep);
    let n = keep.len() as f64;
    let var: f64 = keep.iter().map(|x| (x - mu).powi(2)).sum::<f64>() / n;
    let sigma = var.sqrt();
    let dispersion_r = if var > mu && mu > 1e-9 {
        Some((mu * mu) / (var - mu))
    } else {
        None
    };
    Baseline { mu, sigma, dispersion_r }
}

fn median(data: &mut [f64]) -> f64 {
    data.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = data.len();
    if n.is_multiple_of(2) {
        (data[n / 2 - 1] + data[n / 2]) / 2.0
    } else {
        data[n / 2]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flat_zero_baseline() {
        let b = estimate_baseline(&[0.0, 0.0, 0.0, 0.0, 0.0]);
        assert_eq!(b.mu, 0.0);
        assert_eq!(b.sigma, 0.0);
        assert!(b.dispersion_r.is_none());
    }

    #[test]
    fn flat_baseline_at_value() {
        let b = estimate_baseline(&[5.0; 10]);
        assert_eq!(b.mu, 5.0);
        assert_eq!(b.sigma, 0.0);
        assert!(b.dispersion_r.is_none());
    }

    #[test]
    fn sigma_clip_removes_dominant_peak() {
        // Mostly baseline ~3 with one big peak.
        let signal = [3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0];
        let b = estimate_baseline(&signal);
        assert!(b.mu < 5.0, "baseline μ should be near 3, got {}", b.mu);
        assert!(b.sigma < 2.0, "baseline σ should be small, got {}", b.sigma);
    }

    #[test]
    fn overdispersed_returns_finite_r() {
        // Mean ~5, var ~10 (clearly overdispersed).
        let signal = vec![1.0, 2.0, 3.0, 5.0, 7.0, 8.0, 9.0, 5.0, 4.0, 6.0];
        let b = estimate_baseline(&signal);
        assert!(b.dispersion_r.is_some());
        assert!(b.dispersion_r.unwrap() > 0.0);
    }

    #[test]
    fn empty_input() {
        let b = estimate_baseline(&[]);
        assert_eq!(b.mu, 0.0);
        assert!(b.dispersion_r.is_none());
    }
}
