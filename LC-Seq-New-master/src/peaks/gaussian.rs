//! Old-school peak detection: height-gated local maxima + Gaussian centroid refinement.
//!
//! Returns all peaks that pass height, RT, and Gaussian-shape filters (not only the
//! latest-retained product peak from the legacy Excel export notebooks).

use crate::peaks::picker::{compute_prominence, valley_bounds, Peak};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GaussianPeakParams {
    pub min_height_factor: f64,
    pub fit_width: f64,
    pub stddev_threshold: f64,
    pub minimum_rt: f64,
}

impl Default for GaussianPeakParams {
    fn default() -> Self {
        Self {
            min_height_factor: 0.35,
            fit_width: 1.5,
            stddev_threshold: 2.0,
            minimum_rt: 10.0,
        }
    }
}

fn gaussian(x: f64, amplitude: f64, mean: f64, stddev: f64) -> f64 {
    if stddev <= 0.0 {
        return 0.0;
    }
    amplitude * (-((x - mean) / (2.0 * stddev)).powi(2)).exp()
}

fn population_std(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let n = values.len() as f64;
    let mean = values.iter().sum::<f64>() / n;
    let var = values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n;
    var.sqrt()
}

fn nearest_index(rt: &[f64], target: f64) -> usize {
    let mut best = 0usize;
    let mut best_d = (rt[0] - target).abs();
    for (i, &t) in rt.iter().enumerate() {
        let d = (t - target).abs();
        if d < best_d {
            best_d = d;
            best = i;
        }
    }
    best
}

fn local_maxima_above_height(intensity: &[f64], height_cutoff: f64) -> Vec<usize> {
    let n = intensity.len();
    if n < 3 {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut i = 1usize;
    while i < n - 1 {
        if intensity[i - 1] < intensity[i] {
            let mut j = i;
            while j + 1 < n && intensity[j + 1] == intensity[i] {
                j += 1;
            }
            if j + 1 < n && intensity[j + 1] < intensity[i] && intensity[i] >= height_cutoff {
                out.push(i);
            }
            i = j + 1;
        } else {
            i += 1;
        }
    }
    out
}

fn sse(amplitude: f64, mean: f64, stddev: f64, fit_x: &[f64], fit_y: &[f64]) -> f64 {
    fit_x
        .iter()
        .zip(fit_y.iter())
        .map(|(&x, &y)| {
            let err = y - gaussian(x, amplitude, mean, stddev);
            err * err
        })
        .sum()
}

/// Bounded coordinate-refinement Gaussian fit (matches scipy ``curve_fit`` intent).
fn fit_gaussian(fit_x: &[f64], fit_y: &[f64], peak_x: f64, fit_width: f64) -> Option<(f64, f64, f64)> {
    if fit_x.len() < 3 {
        return None;
    }
    let y_max = fit_y.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let mut amplitude = y_max;
    let mut mean = peak_x;
    let mut stddev = (population_std(fit_x) / 2.0).max(1e-6);

    let amp_min = 0.0;
    let amp_max = f64::INFINITY;
    let mean_min = peak_x - fit_width;
    let mean_max = peak_x + fit_width;
    let std_min = 1e-6;
    let std_max = f64::INFINITY;

    let mut best = sse(amplitude, mean, stddev, fit_x, fit_y);
    let step_amp = (y_max / 10.0).max(1.0);
    let step_mean = (fit_width / 20.0).max(1e-4);
    let step_std = (stddev / 10.0).max(1e-4);

    for _ in 0..200 {
        let mut improved = false;
        for (delta, idx) in [
            (step_amp, 0usize),
            (-step_amp, 0),
            (step_mean, 1),
            (-step_mean, 1),
            (step_std, 2),
            (-step_std, 2),
        ] {
            let (mut a, mut m, mut s) = (amplitude, mean, stddev);
            match idx {
                0 => a = (a + delta).clamp(amp_min, amp_max),
                1 => m = (m + delta).clamp(mean_min, mean_max),
                2 => s = (s + delta).clamp(std_min, std_max),
                _ => {}
            }
            let trial = sse(a, m, s, fit_x, fit_y);
            if trial < best {
                best = trial;
                amplitude = a;
                mean = m;
                stddev = s;
                improved = true;
            }
        }
        if !improved {
            break;
        }
    }

    if !mean.is_finite() || !amplitude.is_finite() || !stddev.is_finite() {
        return None;
    }
    Some((amplitude, mean, stddev))
}

/// Detect peaks using the legacy scipy/Gaussian workflow.
pub fn find_peaks_gaussian(
    rt: &[f64],
    intensity: &[f64],
    params: GaussianPeakParams,
) -> Vec<Peak> {
    assert_eq!(
        rt.len(),
        intensity.len(),
        "rt and intensity must have the same length"
    );
    if rt.len() < 3 {
        return Vec::new();
    }

    let mut order: Vec<usize> = (0..rt.len()).collect();
    order.sort_by(|&a, &b| rt[a].partial_cmp(&rt[b]).unwrap_or(std::cmp::Ordering::Equal));
    let rt: Vec<f64> = order.iter().map(|&i| rt[i]).collect();
    let intensity: Vec<f64> = order.iter().map(|&i| intensity[i]).collect();

    let y_max = intensity.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    if y_max <= 0.0 {
        return Vec::new();
    }

    let height_cutoff = y_max * params.min_height_factor;
    let candidates = local_maxima_above_height(&intensity, height_cutoff);
    let mut accepted = Vec::new();

    for peak_idx in candidates {
        if rt[peak_idx] < params.minimum_rt {
            continue;
        }

        let indices: Vec<usize> = rt
            .iter()
            .enumerate()
            .filter(|(_, &t)| t > rt[peak_idx] - params.fit_width && t < rt[peak_idx] + params.fit_width)
            .map(|(i, _)| i)
            .collect();
        if indices.len() < 3 {
            continue;
        }

        let fit_x: Vec<f64> = indices.iter().map(|&i| rt[i]).collect();
        let fit_y: Vec<f64> = indices.iter().map(|&i| intensity[i]).collect();

        let Some((amplitude, mean, stddev)) =
            fit_gaussian(&fit_x, &fit_y, rt[peak_idx], params.fit_width)
        else {
            continue;
        };

        if stddev >= params.stddev_threshold || amplitude < height_cutoff || mean < params.minimum_rt {
            continue;
        }

        let apex_idx = nearest_index(&rt, mean);
        let (left, right) = valley_bounds(&intensity, apex_idx);
        let area: f64 = intensity[left..=right].iter().sum();
        let prominence = compute_prominence(&intensity, apex_idx);
        let rmse = (best_rmse(&fit_x, &fit_y, amplitude, mean, stddev)).sqrt();
        let p_display = (rmse / amplitude.max(1e-9)).min(1.0);

        accepted.push(Peak {
            rt: mean,
            intensity: intensity[peak_idx],
            area,
            prominence,
            p_value: p_display,
        });
    }

    accepted.sort_by(|a, b| a.rt.partial_cmp(&b.rt).unwrap());
    accepted
}

fn best_rmse(fit_x: &[f64], fit_y: &[f64], amplitude: f64, mean: f64, stddev: f64) -> f64 {
    if fit_x.is_empty() {
        return 0.0;
    }
    sse(amplitude, mean, stddev, fit_x, fit_y) / fit_x.len() as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn returns_multiple_peaks_not_just_latest() {
        let rt: Vec<f64> = (0..40).map(|i| i as f64).collect();
        let mut intensity = vec![2.0; 40];
        intensity[10] = 50.0;
        intensity[11] = 40.0;
        intensity[12] = 30.0;
        intensity[30] = 45.0;
        intensity[31] = 35.0;
        intensity[32] = 25.0;
        let params = GaussianPeakParams {
            minimum_rt: 0.0,
            ..Default::default()
        };
        let peaks = find_peaks_gaussian(&rt, &intensity, params);
        assert!(
            peaks.len() >= 2,
            "expected multiple gaussian peaks, got {:?}",
            peaks
        );
    }
}
