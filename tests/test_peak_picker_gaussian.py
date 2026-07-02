# tests/test_peak_picker_gaussian.py
"""Tests for old-school Gaussian peak picking."""

from __future__ import annotations

import pytest

from src.core.peak_picker_gaussian import find_peaks_gaussian
from src.models.analysis_settings import AnalysisSettings


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Gaussian peak picking",
)
def test_gaussian_returns_multiple_peaks_not_single_latest():
    rt = [float(i) for i in range(40)]
    intensity = [2.0] * 40
    for idx, height in ((10, 50.0), (11, 40.0), (12, 30.0), (30, 45.0), (31, 35.0), (32, 25.0)):
        intensity[idx] = height
    peaks = find_peaks_gaussian(
        rt,
        intensity,
        min_height_threshold_factor=0.35,
        fit_width=3.0,
        stddev_threshold=5.0,
        minimum_rt=0.0,
    )
    assert len(peaks) >= 2, f"expected multiple peaks for null analysis, got {peaks}"


def test_analysis_settings_gaussian_defaults_seconds():
    g = AnalysisSettings.default_gaussian_params("seconds")
    assert g["gaussian_fit_width"] == 90.0
    assert g["gaussian_stddev_threshold"] == 120.0
    assert g["gaussian_minimum_rt"] == 600.0
    assert g["gaussian_min_height_factor"] == 0.35


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Gaussian peak picking",
)
def test_gaussian_respects_minimum_rt():
    rt = [float(i) for i in range(30)]
    intensity = [2.0] * 30
    intensity[5] = 80.0
    intensity[6] = 60.0
    intensity[25] = 90.0
    intensity[26] = 70.0
    peaks = find_peaks_gaussian(
        rt,
        intensity,
        min_height_threshold_factor=0.35,
        fit_width=3.0,
        stddev_threshold=5.0,
        minimum_rt=20.0,
    )
    assert peaks, "expected at least one late peak"
    assert all(p.rt >= 20.0 for p in peaks)
