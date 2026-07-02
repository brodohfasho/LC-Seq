# tests/test_peak_picker_python.py
"""Tests for the pure-Python peak picker (rolling baseline + NB significance)."""

from __future__ import annotations

import pytest

from src.core.peak_picker_python import (
    estimate_rolling_baseline,
    find_peaks,
)


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_single_clear_peak_above_baseline():
    rt = [float(i) for i in range(15)]
    intensity = [3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0, 2.0, 3.0]
    peaks = find_peaks(rt, intensity, 0.001)
    assert len(peaks) == 1
    assert abs(peaks[0].rt - 6.0) < 1e-9
    assert abs(peaks[0].intensity - 100.0) < 1e-9
    assert peaks[0].p_value < 0.001


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_rolling_baseline_finds_late_peak_after_early_elution():
    """Early general elution should not suppress late peaks on a low local baseline."""
    rt = [float(i) for i in range(120)]
    intensity = [45.0] * 40 + [3.0] * 80
    intensity[85] = 120.0
    intensity[84] = 40.0
    intensity[86] = 40.0
    peaks = find_peaks(rt, intensity, 0.001)
    assert any(abs(p.rt - 85.0) < 1e-6 for p in peaks), f"expected late peak, picks={peaks}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_rolling_baseline_filters_tail_wiggles_on_low_global_mu():
    """Tiny tail wiggles should not all pass when local baseline is very flat."""
    rt = [float(i) for i in range(80)]
    intensity = [30.0] * 15 + [1.0] * 65
    for i in range(50, 80, 7):
        intensity[i] = 3.0
    intensity[60] = 80.0
    peaks = find_peaks(rt, intensity, 0.001)
    assert any(abs(p.rt - 60.0) < 1e-6 for p in peaks), f"expected real late peak, picks={peaks}"
    assert len(peaks) <= 2, f"expected tail wiggles filtered, picks={peaks}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_rolling_baseline_uses_local_flat_region():
    intensity = [45.0] * 40 + [3.0] * 60
    intensity[80] = 100.0
    late_local = estimate_rolling_baseline(intensity, 80, 79, 81)
    early_local = estimate_rolling_baseline(intensity, 20, 19, 21)
    assert late_local.mu < 8.0, f"late rolling μ should reflect ~3 count floor, got {late_local.mu}"
    assert early_local.mu > 10.0, f"early rolling μ should reflect ~45 count elution, got {early_local.mu}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_rolling_baseline_excludes_peak_valley():
    intensity = [3.0, 4.0, 3.0, 2.0, 3.0, 4.0, 100.0, 4.0, 3.0, 2.0, 3.0, 4.0, 3.0]
    local = estimate_rolling_baseline(intensity, 6, 5, 7)
    assert local.mu < 8.0, f"peak valley should be excluded, got μ={local.mu}"
