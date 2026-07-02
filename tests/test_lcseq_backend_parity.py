# tests/test_lcseq_backend_parity.py
"""Guard against stale or mismatched lcseq native peak-picker builds."""

from __future__ import annotations

import pytest

from src.core import lcseq_backend
from src.core.lcseq_backend import (
    _native_peak_picker_matches_python,
    get_peak_picker_backend,
    is_native_backend_available,
)
from src.core.peak_picker_python import find_peaks as py_find_peaks


@pytest.mark.skipif(
    not is_native_backend_available(),
    reason="lcseq native extension not installed",
)
@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_native_peak_picker_matches_python_reference():
    assert _native_peak_picker_matches_python()


@pytest.mark.skipif(
    not is_native_backend_available(),
    reason="lcseq native extension not installed",
)
@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("scipy"),
    reason="scipy required for Python analysis fallback",
)
def test_get_peak_picker_backend_uses_native_when_parity_passes():
    lcseq_backend._cached_backend = None
    backend = get_peak_picker_backend()
    assert backend.info().is_native is True


def test_rolling_baseline_probe_python_reference_picks_late_peak():
    rt = [float(i) for i in range(120)]
    intensity = [45.0] * 40 + [3.0] * 80
    intensity[85] = 120.0
    intensity[84] = 40.0
    intensity[86] = 40.0
    peaks = py_find_peaks(rt, intensity, 0.001)
    assert any(abs(p.rt - 85.0) < 1e-6 for p in peaks)
