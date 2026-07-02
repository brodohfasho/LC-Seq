//! Peak-picker mode selection (modern NB vs old-school Gaussian).

use crate::peaks::gaussian::{find_peaks_gaussian, GaussianPeakParams};
use crate::peaks::picker::find_peaks;

#[derive(Debug, Clone, PartialEq)]
pub enum PeakPickerMode {
    Modern { alpha: f64 },
    OldSchool(GaussianPeakParams),
}

impl PeakPickerMode {
    pub fn modern(alpha: f64) -> Self {
        Self::Modern { alpha }
    }

    pub fn old_school(params: GaussianPeakParams) -> Self {
        Self::OldSchool(params)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PeakPickerConfig {
    pub mode: PeakPickerMode,
}

impl PeakPickerConfig {
    pub fn modern(alpha: f64) -> Self {
        Self {
            mode: PeakPickerMode::modern(alpha),
        }
    }

    pub fn old_school(params: GaussianPeakParams) -> Self {
        Self {
            mode: PeakPickerMode::old_school(params),
        }
    }

    pub fn modern_alpha(&self) -> f64 {
        match &self.mode {
            PeakPickerMode::Modern { alpha } => *alpha,
            PeakPickerMode::OldSchool(_) => 0.001,
        }
    }
}

impl Default for PeakPickerConfig {
    fn default() -> Self {
        Self::modern(0.001)
    }
}

use crate::peaks::Peak;

pub fn find_peaks_with_config(
    rt: &[f64],
    intensity: &[f64],
    picker: &PeakPickerConfig,
) -> Vec<Peak> {
    match &picker.mode {
        PeakPickerMode::Modern { alpha } => find_peaks(rt, intensity, *alpha),
        PeakPickerMode::OldSchool(params) => find_peaks_gaussian(rt, intensity, *params),
    }
}
