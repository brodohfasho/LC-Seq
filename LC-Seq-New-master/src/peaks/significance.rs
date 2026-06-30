//! Negative-Binomial / Poisson upper-tail tests for peak significance.
//!
//! For a baseline with mean μ and dispersion r, the count `k` is significant if
//! `P(X ≥ k | NB(r, p))` is below the user's α. Here `p = r / (r + μ)` is the
//! parameterisation where `mean = r(1-p)/p`.
//!
//! When `r` is unavailable (under-dispersed baseline) we fall back to Poisson(μ).
//! When μ is zero or `k` is non-positive, edge cases short-circuit.

use statrs::distribution::{DiscreteCDF, NegativeBinomial, Poisson};

/// Upper tail: `P(X ≥ k)` under NB(r, p) with `p = r / (r + mu)`. If `r` is `None`,
/// falls back to Poisson(mu). Returns 1.0 for k ≤ 0; returns 0.0 if μ ≤ 0 (any positive
/// observation is unconditionally significant against a zero baseline).
pub fn p_at_least(k: f64, mu: f64, dispersion_r: Option<f64>) -> f64 {
    if k <= 0.0 {
        return 1.0;
    }
    if mu <= 0.0 {
        return 0.0;
    }
    let k_int = k.round().max(1.0) as u64;
    let surv = match dispersion_r {
        Some(r) if r.is_finite() && r > 1e-6 => {
            let p = r / (r + mu);
            match NegativeBinomial::new(r, p) {
                Ok(nb) => 1.0 - nb.cdf(k_int.saturating_sub(1)),
                Err(_) => return poisson_upper(k_int, mu),
            }
        }
        _ => poisson_upper(k_int, mu),
    };
    surv.clamp(0.0, 1.0)
}

fn poisson_upper(k: u64, mu: f64) -> f64 {
    match Poisson::new(mu) {
        Ok(pois) => 1.0 - pois.cdf(k.saturating_sub(1)),
        Err(_) => 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() < tol
    }

    #[test]
    fn k_zero_is_p_one() {
        assert_eq!(p_at_least(0.0, 5.0, Some(2.0)), 1.0);
    }

    #[test]
    fn zero_mean_makes_any_observation_significant() {
        assert_eq!(p_at_least(1.0, 0.0, Some(2.0)), 0.0);
    }

    #[test]
    fn high_count_far_above_mean_is_significant() {
        // NB with μ=5, r=2 → P(X ≥ 100) is essentially 0.
        let p = p_at_least(100.0, 5.0, Some(2.0));
        assert!(p < 1e-9, "expected p ≈ 0, got {}", p);
    }

    #[test]
    fn count_at_mean_is_not_significant() {
        // NB with μ=10, r=5 → P(X ≥ 10) is around the median range.
        let p = p_at_least(10.0, 10.0, Some(5.0));
        assert!(p > 0.1, "expected p > 0.1, got {}", p);
    }

    #[test]
    fn poisson_fallback_when_dispersion_none() {
        // Poisson(5) → P(X ≥ 100) ≈ 0.
        let p = p_at_least(100.0, 5.0, None);
        assert!(p < 1e-9);
    }

    #[test]
    fn poisson_p_value_matches_known_value() {
        // Poisson(2): P(X ≥ 5) = 1 - cdf(4) ≈ 0.0527
        let p = p_at_least(5.0, 2.0, None);
        assert!(approx(p, 0.0527, 0.001), "got {}", p);
    }
}
