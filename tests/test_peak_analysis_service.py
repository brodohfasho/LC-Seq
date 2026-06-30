# tests/test_peak_analysis_service.py
"""Tests for peak picking on single compounds."""

from __future__ import annotations

import pytest

from src.core.peak_analysis_service import analyze_peaks, analyze_peaks_batch
from src.models.analysis_settings import AnalysisSettings
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound


def _gaussian_chrom(n: int, center: float, amp: float, baseline: float = 3.0) -> Compound:
    points = []
    for i in range(n):
        t = float(i)
        y = baseline + amp * (0.5 ** abs(t - center))
        if abs(t - center) < 0.01:
            y = baseline + amp
        points.append(ChromatographicDataPoint(time=t, counts={"Count": y}))
    return Compound(compound_id="test", data_points=points)


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_analyze_peaks_finds_clear_peak():
    compound = _gaussian_chrom(25, 12.0, 200.0)
    settings = AnalysisSettings(count_channel="Count", alpha=0.01)
    result = analyze_peaks(compound, settings)
    assert len(result.peaks) >= 1
    assert result.peaks[0].area > 0
    assert result.peaks[0].pct_area > 0
    assert result.baseline is not None
    assert result.baseline.mu < 20


def test_analyze_peaks_requires_data():
    compound = Compound(compound_id="empty", data_points=[])
    settings = AnalysisSettings(count_channel="Count")
    with pytest.raises(Exception):
        analyze_peaks(compound, settings)


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_analyze_peaks_batch_multiple_compounds():
    c1 = _gaussian_chrom(25, 8.0, 180.0, baseline=3.0)
    c1.compound_id = "cmp_a"
    c2 = _gaussian_chrom(25, 16.0, 220.0, baseline=4.0)
    c2.compound_id = "cmp_b"
    settings = AnalysisSettings(count_channel="Count", alpha=0.01)
    batch = analyze_peaks_batch([c1, c2], settings)
    assert len(batch.results) == 2
    assert batch.total_peak_count >= 2
    assert batch.result_for_compound("cmp_a") is not None
    assert batch.result_for_compound("cmp_b") is not None
