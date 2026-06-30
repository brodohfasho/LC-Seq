# src/core/time_display.py
"""Convert chromatogram retention times between seconds and minutes for display."""

from __future__ import annotations

from typing import List, Sequence

from src.models.analysis_settings import TimeUnit


def convert_time_value(value: float, from_unit: TimeUnit, to_unit: TimeUnit) -> float:
    """
    Convert one retention time between units.

    Args:
        value: Time in ``from_unit``.
        from_unit: Unit the value is stored in (from spreadsheet configuration).
        to_unit: Unit to display or export.

    Returns:
        Converted time in ``to_unit``.
    """
    if from_unit == to_unit:
        return float(value)
    if from_unit == "seconds" and to_unit == "minutes":
        return float(value) / 60.0
    if from_unit == "minutes" and to_unit == "seconds":
        return float(value) * 60.0
    raise ValueError(f"Unsupported time unit conversion: {from_unit!r} -> {to_unit!r}")


def convert_time_series(
    times: Sequence[float],
    from_unit: TimeUnit,
    to_unit: TimeUnit,
) -> List[float]:
    """Convert a time axis from stored units to display units."""
    return [convert_time_value(t, from_unit, to_unit) for t in times]


def time_axis_label(unit: TimeUnit) -> str:
    """Axis label for chromatogram plots."""
    return "Time (min)" if unit == "minutes" else "Time (s)"
