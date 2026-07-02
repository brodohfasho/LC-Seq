# src/core/peak_quality_filter.py
"""
Quality filtering for detected peaks (prominence, % area).

Statistical detection returns all significant peaks in ``all_peaks``; this module
produces the displayed/finalized subset in ``peaks``. After lineage analysis, peaks
that match a null-truncation assignment can be rescued even when they fail quality
thresholds.
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional

from src.models.analysis_settings import AnalysisSettings
from src.models.peak_result import PeakAnalysisResult, PickedPeak


def is_null_truncation_label(suspected_peak_id: Optional[str]) -> bool:
    """Return True when a peak is assigned to a null-truncation lineage tier."""
    return bool(suspected_peak_id and suspected_peak_id.startswith("null truncation"))


def passes_quality_thresholds(peak: PickedPeak, settings: AnalysisSettings) -> bool:
    """Return True when a peak meets user prominence and % area cutoffs."""
    if settings.min_prominence > 0 and peak.prominence < settings.min_prominence:
        return False
    if settings.min_pct_area > 0 and peak.pct_area < settings.min_pct_area:
        return False
    return True


def finalize_peaks(
    all_peaks: List[PickedPeak],
    settings: AnalysisSettings,
    *,
    allow_null_truncation_rescue: bool = False,
) -> List[PickedPeak]:
    """
    Build the displayed peak list from the full detected set.

    Peaks pass when they meet quality thresholds, or (optionally) when lineage
    analysis assigned them to a null truncation within tolerance.
    """
    finalized: List[PickedPeak] = []
    for peak in all_peaks:
        if passes_quality_thresholds(peak, settings):
            finalized.append(peak)
        elif allow_null_truncation_rescue and is_null_truncation_label(peak.suspected_peak_id):
            finalized.append(peak)
    return finalized


def apply_peak_quality_filter(
    entry: PeakAnalysisResult,
    *,
    allow_null_truncation_rescue: bool = False,
) -> PeakAnalysisResult:
    """Recompute ``entry.peaks`` from ``entry.all_peaks`` using current settings."""
    source = entry.all_peaks if entry.all_peaks else entry.peaks
    displayed = finalize_peaks(
        source,
        entry.settings,
        allow_null_truncation_rescue=allow_null_truncation_rescue,
    )
    return replace(entry, all_peaks=source, peaks=displayed)


def annotate_pct_area(peaks: List[PickedPeak]) -> None:
    """Set ``pct_area`` on each peak from the detected peak list."""
    total = sum(p.area for p in peaks)
    if total <= 1e-12:
        return
    for peak in peaks:
        peak.pct_area = 100.0 * peak.area / total


def filter_detected_peaks(
    peaks: List[PickedPeak],
    settings: AnalysisSettings,
) -> List[PickedPeak]:
    """Apply prominence and % area filters to statistically detected peaks."""
    if settings.min_prominence <= 0 and settings.min_pct_area <= 0:
        return peaks
    annotate_pct_area(peaks)
    return [p for p in peaks if passes_quality_thresholds(p, settings)]


def apply_peak_quality_filter_batch(
    results: List[PeakAnalysisResult],
    settings: AnalysisSettings,
    *,
    allow_null_truncation_rescue: bool = False,
) -> List[PeakAnalysisResult]:
    """Apply quality filtering to each result in a batch."""
    updated: List[PeakAnalysisResult] = []
    for entry in results:
        entry = replace(entry, settings=settings)
        updated.append(
            apply_peak_quality_filter(
                entry,
                allow_null_truncation_rescue=allow_null_truncation_rescue,
            )
        )
    return updated
