# tests/test_direct_pick_rt.py
"""Tests for Direct Pick product RT selection (CalculateRTs parity)."""

from __future__ import annotations

from src.core.lcseq_backend import select_direct_pick_product_rt
from src.models.analysis_settings import AnalysisSettings
from src.models.peak_result import PickedPeak


def _peak(
    rt: float,
    intensity: float = 100.0,
    *,
    area: float = 1.0,
    prominence: float = 1.0,
) -> PickedPeak:
    return PickedPeak(
        peak_index=1,
        rt=rt,
        intensity=intensity,
        area=area,
        prominence=prominence,
        p_value=0.01,
    )


def test_select_direct_pick_product_rt_uses_latest_peak_modern() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="modern",
    )
    peaks = [_peak(10.0), _peak(15.0), _peak(12.0)]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=200.0)
    assert rt == 15.0


def test_select_direct_pick_product_rt_uses_latest_peak_old_school() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
        gaussian_minimum_rt=0.0,
    )
    peaks = [_peak(8.0, intensity=80.0), _peak(18.0, intensity=90.0)]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=100.0)
    assert rt == 18.0


def test_select_direct_pick_product_rt_old_school_respects_minimum_rt() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
        gaussian_minimum_rt=600.0,
    )
    peaks = [_peak(500.0, intensity=80.0), _peak(700.0, intensity=90.0)]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=100.0)
    assert rt == 700.0


def test_select_direct_pick_product_rt_old_school_respects_amplitude_floor() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
        gaussian_minimum_rt=0.0,
    )
    peaks = [
        _peak(20.0, intensity=10.0),
        _peak(25.0, intensity=40.0),
    ]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=100.0)
    assert rt == 25.0


def test_select_direct_pick_product_rt_returns_none_when_no_candidates() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
        gaussian_minimum_rt=600.0,
    )
    peaks = [_peak(100.0, intensity=80.0)]
    assert (
        select_direct_pick_product_rt(peaks, settings, trace_max_intensity=100.0)
        is None
    )


def test_select_direct_pick_product_rt_respects_min_prominence() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="modern",
        min_prominence=10.0,
    )
    peaks = [
        _peak(10.0, prominence=20.0, area=50.0),
        _peak(20.0, prominence=2.0, area=50.0),
    ]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=200.0)
    assert rt == 10.0


def test_select_direct_pick_old_school_ignores_quality_filters() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
        gaussian_minimum_rt=0.0,
        min_prominence=100.0,
        min_pct_area=90.0,
    )
    peaks = [
        _peak(10.0, intensity=80.0, prominence=1.0, area=10.0),
        _peak(20.0, intensity=90.0, prominence=1.0, area=10.0),
    ]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=100.0)
    assert rt == 20.0


def test_select_direct_pick_product_rt_respects_min_pct_area() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="modern",
        min_pct_area=40.0,
    )
    peaks = [
        _peak(10.0, prominence=50.0, area=70.0),
        _peak(25.0, prominence=50.0, area=30.0),
    ]
    rt = select_direct_pick_product_rt(peaks, settings, trace_max_intensity=200.0)
    assert rt == 10.0


def test_select_direct_pick_product_rt_returns_none_when_quality_filters_all() -> None:
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="modern",
        min_prominence=100.0,
    )
    peaks = [_peak(15.0, prominence=5.0)]
    assert (
        select_direct_pick_product_rt(peaks, settings, trace_max_intensity=200.0)
        is None
    )
