# src/models/analysis_settings.py
"""Runtime settings for chromatographic peak and pedigree analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

TimeUnit = Literal["seconds", "minutes"]


@dataclass
class AnalysisSettings:
    """User-selected parameters for one analysis run."""

    count_channel: str
    time_unit: TimeUnit = "seconds"
    alpha: float = 1e-3
    tolerance: float = 30.0
    selected_variants: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if not self.count_channel or not str(self.count_channel).strip():
            raise ValueError("count_channel is required")
        if self.alpha <= 0 or self.alpha > 1:
            raise ValueError("alpha must be in (0, 1]")
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if self.time_unit not in ("seconds", "minutes"):
            raise ValueError("time_unit must be 'seconds' or 'minutes'")

    @property
    def tolerance_label(self) -> str:
        unit = "min" if self.time_unit == "minutes" else "s"
        return f"{self.tolerance} {unit}"
