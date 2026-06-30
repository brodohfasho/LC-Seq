"""Tests for `lcseq.io.parse_xlsx`.

Includes one slow test that parses the full ~100MB master xlsx — gated behind a `slow`
mark so the fast suite still runs quickly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lcseq.io import _parse_datapoints, _unit_factor, parse_xlsx

XLSX = Path(__file__).resolve().parent.parent.parent / "data" / "LDEL_ssPID_10-40_Master3.0.xlsx"
ROOT = ("AgxNull", "AgxNull", "AgxNull")


# ---- unit conversion ----

def test_unit_factor_identity():
    assert _unit_factor("seconds", "seconds") == 1.0
    assert _unit_factor("minutes", "minutes") == 1.0


def test_unit_factor_seconds_to_minutes():
    assert _unit_factor("seconds", "minutes") == pytest.approx(1 / 60)


def test_unit_factor_minutes_to_seconds():
    assert _unit_factor("minutes", "seconds") == 60.0


# ---- datapoint decoding ----

def test_parse_datapoints_empty():
    rt, intensity = _parse_datapoints(None, "scaled", 1.0)
    assert rt.size == 0
    assert intensity.size == 0


def test_parse_datapoints_picks_correct_channel():
    s = "100:5;3, 200:10;7"
    rt, raw = _parse_datapoints(s, "raw", 1.0)
    _, scaled = _parse_datapoints(s, "scaled", 1.0)
    assert list(rt) == [100.0, 200.0]
    assert list(raw) == [5.0, 10.0]
    assert list(scaled) == [3.0, 7.0]


def test_parse_datapoints_sorts_by_rt():
    s = "300:30;3, 100:10;1, 200:20;2"
    rt, intensity = _parse_datapoints(s, "raw", 1.0)
    assert list(rt) == [100.0, 200.0, 300.0]
    assert list(intensity) == [10.0, 20.0, 30.0]


def test_parse_datapoints_applies_unit_factor():
    s = "60:5;3, 120:10;7"
    rt, _ = _parse_datapoints(s, "raw", 1 / 60)  # seconds -> minutes
    assert list(rt) == [1.0, 2.0]


# ---- full-file parse (slow) ----

@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists(), reason="master xlsx not present")
def test_parse_xlsx_linear_default():
    bbs_per_position, chroms = parse_xlsx(XLSX)
    assert len(bbs_per_position) == 3
    # At least one BB at each position (there's data here).
    assert all(len(b) > 0 for b in bbs_per_position)
    assert ROOT in chroms
    rt, intensity = chroms[ROOT]
    assert rt.dtype == np.float64
    assert intensity.dtype == np.float64
    assert rt.size > 0
    # Source rt is in seconds: root chromatogram spans roughly 600..3600 s.
    assert 500 < rt[0] < 800
    assert 3000 < rt[-1] < 4000


@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists(), reason="master xlsx not present")
def test_parse_xlsx_unit_conversion_to_minutes():
    _, chroms_s = parse_xlsx(XLSX)
    _, chroms_m = parse_xlsx(XLSX, unit="minutes")
    rt_s, _ = chroms_s[ROOT]
    rt_m, _ = chroms_m[ROOT]
    assert np.allclose(rt_m, rt_s / 60.0)


@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists(), reason="master xlsx not present")
def test_parse_xlsx_channel_choice_changes_intensities():
    _, raw_chroms = parse_xlsx(XLSX, channel="raw")
    _, scaled_chroms = parse_xlsx(XLSX, channel="scaled")
    _, raw_intensity = raw_chroms[ROOT]
    _, scaled_intensity = scaled_chroms[ROOT]
    # Both non-empty, and at least one timepoint differs.
    assert raw_intensity.size > 0 and scaled_intensity.size > 0
    assert not np.array_equal(raw_intensity, scaled_intensity)


@pytest.mark.slow
@pytest.mark.skipif(not XLSX.exists(), reason="master xlsx not present")
def test_parse_xlsx_lid_filter_picks_different_chromatograms():
    """Both libraries share the same Common_Names (same compound set, different
    conditions), so the chromatogram dicts have the same keys. But the underlying
    chromatograms differ — verify that for the all-null root."""
    _, chroms_linear = parse_xlsx(XLSX, lid="DEL-0044")
    _, chroms_cyclic = parse_xlsx(XLSX, lid="DEL-0045")
    assert ROOT in chroms_linear and ROOT in chroms_cyclic
    _, intensity_linear = chroms_linear[ROOT]
    _, intensity_cyclic = chroms_cyclic[ROOT]
    # The two libraries' root chromatograms cannot be identical.
    assert not np.array_equal(intensity_linear, intensity_cyclic)
