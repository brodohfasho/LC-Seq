pub mod baseline;
pub mod gaussian;
pub mod picker;
pub mod picker_config;
pub mod quality;
pub mod significance;

pub use baseline::{estimate_baseline, Baseline};
pub use gaussian::{find_peaks_gaussian, GaussianPeakParams};
pub use picker::{find_peaks, Peak};
pub use picker_config::{find_peaks_with_config, PeakPickerConfig, PeakPickerMode};
pub use quality::{filter_peaks_by_quality, pick_peaks_with_quality, PeakQualityParams};
pub use significance::p_at_least;
