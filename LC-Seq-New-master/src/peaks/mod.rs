pub mod baseline;
pub mod picker;
pub mod significance;

pub use baseline::{estimate_baseline, Baseline};
pub use picker::{find_peaks, Peak};
pub use significance::p_at_least;
