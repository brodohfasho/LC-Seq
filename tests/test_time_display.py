# tests/test_time_display.py
"""Tests for retention-time unit conversion."""

from __future__ import annotations

import pytest

from src.core.time_display import convert_time_value, convert_time_series, time_axis_label


def test_same_unit_is_identity():
    assert convert_time_value(120.0, "seconds", "seconds") == 120.0
    assert convert_time_value(2.0, "minutes", "minutes") == 2.0


def test_seconds_to_minutes():
    assert convert_time_value(120.0, "seconds", "minutes") == pytest.approx(2.0)


def test_minutes_to_seconds():
    assert convert_time_value(2.5, "minutes", "seconds") == pytest.approx(150.0)


def test_convert_series():
    assert convert_time_series([0.0, 60.0, 120.0], "seconds", "minutes") == [0.0, 1.0, 2.0]


def test_axis_labels():
    assert time_axis_label("seconds") == "Time (s)"
    assert time_axis_label("minutes") == "Time (min)"
