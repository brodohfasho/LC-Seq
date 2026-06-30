//! Multi-replicate Negative-Binomial peak detection via the score statistic.
//!
//! Generative model — for each replicate `j` and each rt bin `i`:
//!
//! ```text
//! Yᵢⱼ ~ NB(λᵢⱼ, r)
//! λᵢⱼ = μⱼ + αⱼ · φ(tᵢ; p*, σ)
//! ```
//!
//! where `μⱼ` is the per-rep baseline (sigma-clipped scalar), `αⱼ ≥ 0` is the per-rep
//! peak amplitude, `φ(t; p*, σ) = exp(-(t−p*)² / (2σ²))` is a shared Gaussian peak
//! shape, `p*` is the SHARED peak position (the parameter we want to estimate, i.e.
//! the consensus rt), and `r` is the NB dispersion.
//!
//! We test `H₀: αⱼ = 0 ∀j` against `H₁: αⱼ > 0` via the score statistic at each
//! candidate `p*`:
//!
//! ```text
//! U(p*) = Σⱼ Σᵢ φᵢⱼ · (Yᵢⱼ − μⱼ) / Var(Yᵢⱼ)              (template-matched signal)
//! I(p*) = Σⱼ Σᵢ φᵢⱼ² / Var(Yᵢⱼ)                          (Fisher information)
//! z(p*) = U(p*) / √I(p*)  ~ N(0, 1) under H₀
//! ```
//!
//! Under NB(μ, r), Var = μ + μ²/r. We pick `p̂* = argmax_p U(p)` and use a one-sided
//! upper-tail normal test for significance. This is asymptotically equivalent to the
//! likelihood ratio test but requires no inner amplitude optimisation — the score
//! evaluates analytically at each candidate `p*`.

use crate::evaluate::Chromatogram;
use crate::peaks::Baseline;
use statrs::distribution::{ContinuousCDF, Normal};

/// Result of fitting the multi-replicate peak model.
#[derive(Debug, Clone)]
pub struct PeakModelFit {
    /// Estimated shared peak position (the consensus rt).
    pub p_star: f64,
    /// Score statistic U(p̂*).
    pub score: f64,
    /// Fisher information I(p̂*).
    pub info: f64,
    /// z-statistic = U / √I, asymptotically N(0, 1) under H₀.
    pub z_stat: f64,
    /// One-sided upper-tail p-value of the score test.
    pub p_value: f64,
    /// Each replicate's signed contribution to U(p̂*). Positive = the rep's signal
    /// supports a peak at `p*`. Reps with negligible / negative contributions don't
    /// count toward the consensus.
    pub per_rep_score: Vec<f64>,
}

/// Default Gaussian width for the peak shape, in the same units as rt.
/// Tuned for a 0.5-min-sampled chromatogram (FWHM ≈ 0.7 min, σ ≈ 0.3 min).
pub const DEFAULT_SIGMA: f64 = 0.3;

/// Coarse-grid search for `p*` followed by a parabolic refinement around the best grid
/// point. `p_min` is the lower bound (typically `effective_threshold + tolerance`);
/// `p_max` is the upper bound (typically the chromatogram's max rt).
pub fn fit_peak_model(
    chromatograms: &[Chromatogram],
    baselines: &[Baseline],
    sigma: f64,
    p_min: f64,
    p_max: f64,
    grid_step: f64,
) -> Option<PeakModelFit> {
    assert_eq!(chromatograms.len(), baselines.len(), "chroms / baselines must align");
    if chromatograms.is_empty() || p_max <= p_min {
        return None;
    }

    // Coarse grid of candidate positions.
    let n_steps = (((p_max - p_min) / grid_step).ceil() as usize).max(1);
    let mut best_score = f64::NEG_INFINITY;
    let mut best_p = p_min;
    let mut best_info = 0.0;
    let mut best_per_rep = vec![0.0; chromatograms.len()];

    for k in 0..=n_steps {
        let p = p_min + (k as f64) * grid_step;
        if p > p_max {
            break;
        }
        let (score, info, per_rep) = score_at(chromatograms, baselines, sigma, p);
        if score > best_score {
            best_score = score;
            best_p = p;
            best_info = info;
            best_per_rep = per_rep;
        }
    }

    // Parabolic refinement around best_p (using grid neighbours).
    let p_left = (best_p - grid_step).max(p_min);
    let p_right = (best_p + grid_step).min(p_max);
    if p_left < best_p && best_p < p_right {
        let (s_l, _, _) = score_at(chromatograms, baselines, sigma, p_left);
        let (s_r, _, _) = score_at(chromatograms, baselines, sigma, p_right);
        let denom = s_l - 2.0 * best_score + s_r;
        if denom < -1e-12 {
            // Parabolic vertex: offset in units of grid step, clamped to ±0.5.
            let offset = 0.5 * (s_l - s_r) / denom;
            let offset = offset.clamp(-0.5, 0.5);
            let p_refined = best_p + offset * grid_step;
            let (score_r, info_r, per_rep_r) =
                score_at(chromatograms, baselines, sigma, p_refined);
            if score_r > best_score {
                best_score = score_r;
                best_p = p_refined;
                best_info = info_r;
                best_per_rep = per_rep_r;
            }
        }
    }

    let z_stat = if best_info > 0.0 {
        best_score / best_info.sqrt()
    } else {
        0.0
    };
    let p_value = if z_stat > 0.0 {
        normal_upper_tail(z_stat)
    } else {
        0.5
    };

    Some(PeakModelFit {
        p_star: best_p,
        score: best_score,
        info: best_info,
        z_stat,
        p_value,
        per_rep_score: best_per_rep,
    })
}

/// Score and Fisher information at a single candidate `p*`, plus per-rep contributions.
/// Public to the crate so consensus-stage code can evaluate the joint NB score test
/// at arbitrary candidate positions (not just the MLE).
pub(crate) fn score_at(
    chromatograms: &[Chromatogram],
    baselines: &[Baseline],
    sigma: f64,
    p_star: f64,
) -> (f64, f64, Vec<f64>) {
    let mut score = 0.0;
    let mut info = 0.0;
    let mut per_rep = vec![0.0; chromatograms.len()];
    let two_sigma_sq = 2.0 * sigma * sigma;

    // Numerical floor for baseline mean. Production sigma-clipping never returns 0,
    // but synthetic test chromatograms with all-zero baselines would divide by zero.
    const MU_FLOOR: f64 = 0.5;
    for (j, ((rt, intensity), baseline)) in
        chromatograms.iter().zip(baselines.iter()).enumerate()
    {
        let mu = baseline.mu.max(MU_FLOOR);
        let r = baseline.dispersion_r.unwrap_or(1e6);
        let var = mu + mu * mu / r;
        if var <= 0.0 {
            continue;
        }
        let mut rep_contrib = 0.0;
        for i in 0..rt.len() {
            let dt = rt[i] - p_star;
            // Cut off the kernel beyond 4σ to save work; contribution is ~exp(-8) ≈ 3e-4.
            if dt.abs() > 4.0 * sigma {
                continue;
            }
            let phi = (-(dt * dt) / two_sigma_sq).exp();
            let residual = intensity[i] - mu;
            rep_contrib += phi * residual / var;
            info += (phi * phi) / var;
        }
        per_rep[j] = rep_contrib;
        score += rep_contrib;
    }

    (score, info, per_rep)
}

fn normal_upper_tail(z: f64) -> f64 {
    let n = Normal::new(0.0, 1.0).expect("standard normal");
    (1.0 - n.cdf(z)).clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn baseline(mu: f64, r: Option<f64>) -> Baseline {
        Baseline { mu, sigma: (mu + r.map_or(0.0, |rr| mu * mu / rr)).sqrt(), dispersion_r: r }
    }

    /// Build a chromatogram with a Gaussian peak at `mu_t` over a `n`-bin uniform grid.
    fn gaussian_chrom(n: usize, mu_t: f64, sigma: f64, amp: f64, baseline_mu: f64)
        -> Chromatogram
    {
        let rt: Vec<f64> = (0..n).map(|i| i as f64 * 0.5).collect();
        let intensity: Vec<f64> = rt.iter()
            .map(|&t| baseline_mu + amp * (-(t - mu_t).powi(2) / (2.0 * sigma * sigma)).exp())
            .collect();
        (rt, intensity)
    }

    #[test]
    fn fits_single_replicate_peak() {
        let chrom = gaussian_chrom(40, 10.0, 0.3, 100.0, 3.0);
        let b = baseline(3.0, Some(2.0));
        let fit = fit_peak_model(&[chrom], &[b], 0.3, 0.0, 20.0, 0.1).unwrap();
        assert!((fit.p_star - 10.0).abs() < 0.2, "p_star = {}", fit.p_star);
        assert!(fit.p_value < 1e-6, "p_value should be tiny: {}", fit.p_value);
    }

    #[test]
    fn finds_shared_position_across_replicates() {
        // 3 replicates, all with peaks at rt ≈ 12.0 ± slight jitter.
        let r = vec![Some(2.0); 3];
        let bs: Vec<Baseline> = r.iter().map(|&r| baseline(3.0, r)).collect();
        let chroms = vec![
            gaussian_chrom(40, 12.0, 0.3, 100.0, 3.0),
            gaussian_chrom(40, 11.8, 0.3, 100.0, 3.0),
            gaussian_chrom(40, 12.2, 0.3, 100.0, 3.0),
        ];
        let fit = fit_peak_model(&chroms, &bs, 0.3, 5.0, 18.0, 0.1).unwrap();
        assert!((fit.p_star - 12.0).abs() < 0.2, "p_star = {}", fit.p_star);
        // All three reps should contribute positively.
        assert!(fit.per_rep_score.iter().all(|&s| s > 0.0));
    }

    #[test]
    fn prefers_shared_high_signal_over_tight_low_signal() {
        // The DLeu pattern: 2 reps have a HUGE peak at 12.0–12.5 (with spread); 3 reps
        // have a SMALL coincident peak at 16.0. Score test should pick 12 because the
        // high-signal residuals dominate even with imperfect rt agreement.
        let r = vec![Some(2.0); 3];
        let bs: Vec<Baseline> = r.iter().map(|&r| baseline(3.0, r)).collect();
        let make_two_peak = |mu_big: f64| {
            let rt: Vec<f64> = (0..50).map(|i| i as f64 * 0.5).collect();
            let mut intensity = vec![3.0; 50];
            for (i, &t) in rt.iter().enumerate() {
                intensity[i] += 800.0 * (-(t - mu_big).powi(2) / (2.0 * 0.3_f64.powi(2))).exp();
                intensity[i] += 25.0  * (-(t - 16.0).powi(2)  / (2.0 * 0.3_f64.powi(2))).exp();
            }
            (rt, intensity)
        };
        let chroms = vec![
            make_two_peak(12.0),
            make_two_peak(12.5),
            make_two_peak(13.0),
        ];
        let fit = fit_peak_model(&chroms, &bs, 0.4, 5.0, 25.0, 0.1).unwrap();
        // Should find the high-signal region (~12–13), NOT the tight-but-tiny 16.
        assert!(fit.p_star > 11.0 && fit.p_star < 14.0,
                "p_star = {} (expected near 12)", fit.p_star);
    }

    #[test]
    fn null_signal_returns_high_p_value() {
        let r = vec![Some(2.0); 3];
        let bs: Vec<Baseline> = r.iter().map(|&r| baseline(3.0, r)).collect();
        // No peaks — just baseline.
        let chroms: Vec<Chromatogram> = (0..3)
            .map(|_| {
                let rt: Vec<f64> = (0..40).map(|i| i as f64 * 0.5).collect();
                let intensity = vec![3.0; 40];
                (rt, intensity)
            })
            .collect();
        let fit = fit_peak_model(&chroms, &bs, 0.3, 0.0, 20.0, 0.1).unwrap();
        // Score should be near zero, p_value should be far from significance.
        assert!(fit.p_value > 0.1, "p_value = {}", fit.p_value);
    }
}
