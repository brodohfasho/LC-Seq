//! Post-detection quality filters (prominence, percent area).

use crate::peaks::{find_peaks_with_config, Peak, PeakPickerConfig};

/// User-controlled cutoffs applied after statistical peak detection.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PeakQualityParams {
    pub min_prominence: f64,
    pub min_pct_area: f64,
}

impl Default for PeakQualityParams {
    fn default() -> Self {
        Self {
            min_prominence: 0.0,
            min_pct_area: 0.0,
        }
    }
}

impl PeakQualityParams {
    pub fn is_disabled(self) -> bool {
        self.min_prominence <= 0.0 && self.min_pct_area <= 0.0
    }
}

/// Filter detected peaks by prominence and % area.
///
/// When `allow_null_truncation_rescue` is true, all statistically detected peaks are
/// retained (intermediate null-truncation classes in pedigree evaluation).
pub fn filter_peaks_by_quality(
    peaks: Vec<Peak>,
    params: PeakQualityParams,
    allow_null_truncation_rescue: bool,
) -> Vec<Peak> {
    if allow_null_truncation_rescue || params.is_disabled() {
        return peaks;
    }
    let total_area: f64 = peaks.iter().map(|p| p.area).sum();
    if total_area <= 1e-12 {
        return peaks;
    }
    peaks
        .into_iter()
        .filter(|p| peak_passes_quality(p, params, total_area))
        .collect()
}

fn peak_passes_quality(peak: &Peak, params: PeakQualityParams, total_area: f64) -> bool {
    if params.min_prominence > 0.0 && peak.prominence < params.min_prominence {
        return false;
    }
    if params.min_pct_area > 0.0 {
        let pct = 100.0 * peak.area / total_area;
        if pct < params.min_pct_area {
            return false;
        }
    }
    true
}

/// Detect peaks and apply optional quality filtering.
pub fn pick_peaks_with_quality(
    rt: &[f64],
    intensity: &[f64],
    picker: &PeakPickerConfig,
    params: PeakQualityParams,
    allow_null_truncation_rescue: bool,
) -> Vec<Peak> {
    let detected = find_peaks_with_config(rt, intensity, picker);
    filter_peaks_by_quality(detected, params, allow_null_truncation_rescue)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn peak(prom: f64, area: f64) -> Peak {
        Peak {
            rt: 1.0,
            intensity: prom + 10.0,
            area,
            prominence: prom,
            p_value: 1e-6,
        }
    }

    #[test]
    fn filter_disabled_returns_all() {
        let peaks = vec![peak(2.0, 10.0), peak(20.0, 90.0)];
        let out = filter_peaks_by_quality(peaks.clone(), PeakQualityParams::default(), false);
        assert_eq!(out.len(), peaks.len());
    }

    #[test]
    fn filter_by_prominence() {
        let peaks = vec![peak(2.0, 50.0), peak(20.0, 50.0)];
        let params = PeakQualityParams {
            min_prominence: 5.0,
            min_pct_area: 0.0,
        };
        let out = filter_peaks_by_quality(peaks, params, false);
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].prominence, 20.0);
    }

    #[test]
    fn null_truncation_rescue_keeps_weak_peaks() {
        let peaks = vec![peak(2.0, 50.0), peak(20.0, 50.0)];
        let params = PeakQualityParams {
            min_prominence: 5.0,
            min_pct_area: 0.0,
        };
        let out = filter_peaks_by_quality(peaks, params, true);
        assert_eq!(out.len(), 2);
    }
}
