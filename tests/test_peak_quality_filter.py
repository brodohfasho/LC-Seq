# tests/test_peak_quality_filter.py
"""Tests for prominence / % area peak quality filtering."""

from __future__ import annotations

from src.core.peak_quality_filter import (
    filter_detected_peaks,
    finalize_peaks,
    is_null_truncation_label,
    passes_quality_thresholds,
)
from src.models.analysis_settings import AnalysisSettings
from src.models.peak_result import PickedPeak


def _peak(prom: float, pct: float, label: str | None = None) -> PickedPeak:
    return PickedPeak(
        peak_index=1,
        rt=100.0,
        intensity=50.0,
        area=100.0,
        prominence=prom,
        p_value=1e-6,
        pct_area=pct,
        suspected_peak_id=label,
    )


def test_passes_quality_thresholds_respects_prominence_and_pct():
    settings = AnalysisSettings(
        count_channel="Count",
        min_prominence=5.0,
        min_pct_area=3.0,
    )
    assert passes_quality_thresholds(_peak(10.0, 5.0), settings)
    assert not passes_quality_thresholds(_peak(2.0, 5.0), settings)
    assert not passes_quality_thresholds(_peak(10.0, 1.0), settings)


def test_finalize_without_rescue_filters_weak_peaks():
    settings = AnalysisSettings(count_channel="Count", min_prominence=5.0, min_pct_area=3.0)
    peaks = [
        _peak(20.0, 50.0),
        _peak(2.0, 2.0, "null truncation (DNvl)"),
    ]
    out = finalize_peaks(peaks, settings, allow_null_truncation_rescue=False)
    assert len(out) == 1
    assert out[0].prominence == 20.0


def test_finalize_rescues_null_truncation_match():
    settings = AnalysisSettings(count_channel="Count", min_prominence=5.0, min_pct_area=3.0)
    rescued = _peak(2.0, 2.0, "null truncation (DNvl)")
    out = finalize_peaks([rescued], settings, allow_null_truncation_rescue=True)
    assert len(out) == 1
    assert out[0].suspected_peak_id == rescued.suspected_peak_id


def test_filter_detected_peaks_computes_pct_area():
    settings = AnalysisSettings(
        count_channel="Count",
        min_prominence=5.0,
        min_pct_area=31.0,
    )
    peaks = [
        PickedPeak(
            peak_index=1,
            rt=1.0,
            intensity=20.0,
            area=70.0,
            prominence=20.0,
            p_value=1e-6,
        ),
        PickedPeak(
            peak_index=2,
            rt=2.0,
            intensity=10.0,
            area=30.0,
            prominence=10.0,
            p_value=1e-6,
        ),
    ]
    out = filter_detected_peaks(peaks, settings)
    assert len(out) == 1
    assert out[0].area == 70.0


def test_null_truncation_label_helper():
    assert is_null_truncation_label("null truncation (DNvl-DPhe)")
    assert not is_null_truncation_label("intended product (DNvl-DPhe-LA03)")
    assert not is_null_truncation_label("unknown")
