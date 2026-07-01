# src/models/peak_result.py
"""Results from single-chromatogram peak picking and integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from src.models.analysis_settings import AnalysisSettings


@dataclass
class BaselineEstimate:
    """Background noise model for a chromatogram."""

    mu: float
    sigma: float
    dispersion_r: Optional[float] = None


@dataclass
class PickedPeak:
    """One detected peak with integration statistics."""

    peak_index: int
    rt: float
    intensity: float
    area: float
    prominence: float
    p_value: float
    pct_area: float = 0.0
    left_rt: float = 0.0
    right_rt: float = 0.0
    suspected_peak_id: Optional[str] = None


@dataclass
class PeakAnalysisResult:
    """Full peak-pick output for one compound and count channel."""

    compound_id: str
    channel: str
    settings: AnalysisSettings
    peaks: List[PickedPeak] = field(default_factory=list)
    baseline: Optional[BaselineEstimate] = None
    primary_compound_id: Optional[str] = None
    variant_label: Optional[str] = None
    plot_color: str = "#ffa657"
    backend_name: str = "unknown"
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_area(self) -> float:
        return sum(p.area for p in self.peaks)


@dataclass
class PeakAnalysisBatchResult:
    """Peak-pick output for one or more overlaid compounds on the same count channel."""

    settings: AnalysisSettings
    channel: str
    results: List[PeakAnalysisResult] = field(default_factory=list)
    backend_name: str = "unknown"
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_peak_count(self) -> int:
        return sum(len(r.peaks) for r in self.results)

    def result_for_compound(self, compound_id: str) -> Optional[PeakAnalysisResult]:
        key = str(compound_id).strip()
        for entry in self.results:
            if str(entry.compound_id).strip() == key:
                return entry
        return None
