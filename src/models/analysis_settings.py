# src/models/analysis_settings.py
"""Runtime settings for chromatographic peak and pedigree analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

TimeUnit = Literal["seconds", "minutes"]
PeakPickingAlgorithm = Literal["modern", "old_school"]

# Legacy notebook defaults (CalculateRTs / PlotChromatograms_Gaussians; RT axis in minutes).
DEFAULT_GAUSSIAN_MIN_HEIGHT_FACTOR = 0.35
DEFAULT_GAUSSIAN_FIT_WIDTH_MINUTES = 1.5
DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES = 2.0
DEFAULT_GAUSSIAN_MINIMUM_RT_MINUTES = 10.0

# Modern picker defaults (α + post-detection quality filters).
DEFAULT_MODERN_ALPHA = 0.001
DEFAULT_MIN_PROMINENCE = 5.0
DEFAULT_MIN_PCT_AREA = 3.0

# Back-compat alias (σ threshold in minutes).
DEFAULT_GAUSSIAN_STDDEV_THRESHOLD = DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES


@dataclass
class AnalysisSettings:
    """User-selected parameters for one analysis run."""

    count_channel: str
    time_unit: TimeUnit = "seconds"
    peak_picking_algorithm: PeakPickingAlgorithm = "modern"
    alpha: float = 1e-3
    tolerance: float = 30.0
    min_prominence: float = 0.0
    min_pct_area: float = 0.0
    selected_variants: Optional[List[str]] = None
    chromatogram_time_unit: Optional[TimeUnit] = None
    # Old-school (Gaussian) parameters — interpreted in ``time_unit``.
    gaussian_min_height_factor: float = DEFAULT_GAUSSIAN_MIN_HEIGHT_FACTOR
    gaussian_fit_width: float = DEFAULT_GAUSSIAN_FIT_WIDTH_MINUTES
    gaussian_stddev_threshold: float = DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES
    gaussian_minimum_rt: float = DEFAULT_GAUSSIAN_MINIMUM_RT_MINUTES

    def __post_init__(self) -> None:
        if not self.count_channel or not str(self.count_channel).strip():
            raise ValueError("count_channel is required")
        if self.peak_picking_algorithm not in ("modern", "old_school"):
            raise ValueError("peak_picking_algorithm must be 'modern' or 'old_school'")
        if self.alpha <= 0 or self.alpha > 1:
            raise ValueError("alpha must be in (0, 1]")
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if self.min_prominence < 0:
            raise ValueError("min_prominence must be >= 0")
        if self.min_pct_area < 0 or self.min_pct_area > 100:
            raise ValueError("min_pct_area must be in [0, 100]")
        if self.time_unit not in ("seconds", "minutes"):
            raise ValueError("time_unit must be 'seconds' or 'minutes'")
        if not 0.0 < self.gaussian_min_height_factor <= 1.0:
            raise ValueError("gaussian_min_height_factor must be in (0, 1]")
        if self.gaussian_fit_width <= 0:
            raise ValueError("gaussian_fit_width must be positive")
        if self.gaussian_stddev_threshold <= 0:
            raise ValueError("gaussian_stddev_threshold must be positive")
        if self.gaussian_minimum_rt < 0:
            raise ValueError("gaussian_minimum_rt must be >= 0")
        if self.chromatogram_time_unit is not None and self.chromatogram_time_unit not in (
            "seconds",
            "minutes",
        ):
            raise ValueError("chromatogram_time_unit must be 'seconds' or 'minutes'")

    @property
    def stored_time_unit(self) -> TimeUnit:
        return self.chromatogram_time_unit or self.time_unit

    @property
    def tolerance_label(self) -> str:
        unit = "min" if self.time_unit == "minutes" else "s"
        return f"{self.tolerance} {unit}"

    @property
    def uses_modern_peak_picker(self) -> bool:
        return self.peak_picking_algorithm == "modern"

    @property
    def uses_old_school_peak_picker(self) -> bool:
        return self.peak_picking_algorithm == "old_school"

    def effective_quality_params(self) -> tuple[float, float]:
        """
        Min prominence / min % area for engines.

        These post-filters apply only with the modern picker. Old-school uses its
        own height / Gaussian / minimum-RT gates instead.
        """
        if self.uses_old_school_peak_picker:
            return (0.0, 0.0)
        return (float(self.min_prominence), float(self.min_pct_area))

    def gaussian_picker_params(self) -> tuple[float, float, float, float]:
        """Return ``(min_height_factor, fit_width, stddev_threshold, minimum_rt)`` in ``time_unit``."""
        return (
            self.gaussian_min_height_factor,
            self.gaussian_fit_width,
            self.gaussian_stddev_threshold,
            self.gaussian_minimum_rt,
        )

    @classmethod
    def default_gaussian_minimum_rt(cls, time_unit: TimeUnit) -> float:
        return DEFAULT_GAUSSIAN_MINIMUM_RT_MINUTES * (
            1.0 if time_unit == "minutes" else 60.0
        )

    @classmethod
    def default_gaussian_fit_width(cls, time_unit: TimeUnit) -> float:
        return DEFAULT_GAUSSIAN_FIT_WIDTH_MINUTES * (1.0 if time_unit == "minutes" else 60.0)

    @classmethod
    def default_gaussian_stddev_threshold(cls, time_unit: TimeUnit) -> float:
        """Legacy notebooks used σ < 2 min; scale when RT axis is in seconds."""
        return DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES * (
            1.0 if time_unit == "minutes" else 60.0
        )

    @classmethod
    def default_gaussian_params(cls, time_unit: TimeUnit) -> dict[str, float]:
        """All old-school picker defaults for the active time unit."""
        return {
            "gaussian_min_height_factor": DEFAULT_GAUSSIAN_MIN_HEIGHT_FACTOR,
            "gaussian_fit_width": cls.default_gaussian_fit_width(time_unit),
            "gaussian_stddev_threshold": cls.default_gaussian_stddev_threshold(time_unit),
            "gaussian_minimum_rt": cls.default_gaussian_minimum_rt(time_unit),
        }

    @classmethod
    def default_modern_alpha(cls) -> float:
        return DEFAULT_MODERN_ALPHA

    @classmethod
    def default_quality_params(cls) -> tuple[float, float]:
        return DEFAULT_MIN_PROMINENCE, DEFAULT_MIN_PCT_AREA
