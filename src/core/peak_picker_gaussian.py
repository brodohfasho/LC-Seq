# src/core/peak_picker_gaussian.py
"""
Old-school peak detection: scipy local-maxima gate + Gaussian centroid refinement.

Returns **all** peaks that pass height, RT, and Gaussian-shape filters (not only the
latest-retained product peak used in the legacy Excel export notebooks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

try:
    from scipy.optimize import curve_fit
    from scipy.signal import find_peaks as scipy_find_peaks
except ImportError:  # pragma: no cover
    curve_fit = None  # type: ignore
    scipy_find_peaks = None  # type: ignore

from src.core.peak_picker_python import _compute_prominence, nearest_index, valley_bounds


@dataclass
class _GaussianPeak:
    rt: float
    intensity: float
    area: float
    prominence: float
    p_value: float
    left_idx: int
    right_idx: int


def _gaussian(x, amplitude: float, mean: float, stddev: float):
    """Match legacy notebook functional form (vectorized for scipy)."""
    return amplitude * np.exp(-((x - mean) / (2.0 * stddev)) ** 2)


def find_peaks_gaussian(
    rt: Sequence[float],
    intensity: Sequence[float],
    *,
    min_height_threshold_factor: float = 0.35,
    fit_width: float = 1.5,
    stddev_threshold: float = 2.0,
    minimum_rt: float = 0.0,
) -> List[_GaussianPeak]:
    """
    Detect peaks via scipy ``find_peaks`` and per-peak Gaussian fits.

    Args:
        rt: Retention times (ascending, same unit as ``fit_width`` / ``minimum_rt``).
        intensity: Counts parallel to ``rt``.
        min_height_threshold_factor: Min apex height as fraction of trace maximum.
        fit_width: Half-width of the Gaussian fit window (time units).
        stddev_threshold: Reject fits with fitted stddev >= this value.
        minimum_rt: Ignore candidates with apex RT below this value.

    Returns:
        All accepted Gaussian peaks sorted by RT.
    """
    if scipy_find_peaks is None or curve_fit is None:
        raise ImportError("scipy is required for old-school (Gaussian) peak picking")
    if len(rt) != len(intensity):
        raise ValueError("rt and intensity must have the same length")
    if len(rt) < 3:
        return []

    # Legacy 10–40 workflow sorted by RT before peak detection.
    order = sorted(range(len(rt)), key=lambda i: float(rt[i]))
    x = [float(rt[i]) for i in order]
    y = [float(intensity[i]) for i in order]
    y_max = max(y)
    if y_max <= 0:
        return []

    height_cutoff = y_max * min_height_threshold_factor
    candidate_idx, _ = scipy_find_peaks(y, height=height_cutoff)

    accepted: List[_GaussianPeak] = []
    for peak_idx in candidate_idx:
        peak_idx = int(peak_idx)
        if x[peak_idx] < minimum_rt:
            continue

        indices = [
            i for i, val in enumerate(x) if x[peak_idx] - fit_width < val < x[peak_idx] + fit_width
        ]
        if len(indices) < 3:
            continue

        fit_x = [x[i] for i in indices]
        fit_y = [y[i] for i in indices]
        initial_guess = [max(fit_y), x[peak_idx], max(float(np.std(fit_x)) / 2.0, 1e-6)]
        bounds = (
            [0.0, x[peak_idx] - fit_width, 0.0],
            [math.inf, x[peak_idx] + fit_width, math.inf],
        )

        try:
            popt, _pcov = curve_fit(
                _gaussian,
                np.asarray(fit_x, dtype=float),
                np.asarray(fit_y, dtype=float),
                p0=initial_guess,
                bounds=bounds,
                maxfev=1000,
            )
        except (RuntimeError, ValueError):
            continue

        amplitude, mean, stddev = float(popt[0]), float(popt[1]), float(popt[2])
        if not math.isfinite(amplitude) or not math.isfinite(mean) or not math.isfinite(stddev):
            continue
        if stddev <= 0.0 or stddev >= stddev_threshold or amplitude < height_cutoff:
            continue
        if mean < minimum_rt:
            continue

        apex_idx = nearest_index(x, mean)
        left, right = valley_bounds(y, apex_idx)
        area = float(sum(y[left : right + 1]))
        prominence = _compute_prominence(y, apex_idx)
        # Normalized residual at fit points → pseudo p-value for table display (not NB).
        fit_arr = np.asarray(fit_y, dtype=float)
        model = _gaussian(np.asarray(fit_x, dtype=float), amplitude, mean, stddev)
        rmse = float(np.sqrt(np.mean((fit_arr - model) ** 2))) if len(fit_arr) else 0.0
        p_display = min(1.0, rmse / max(amplitude, 1e-9))

        accepted.append(
            _GaussianPeak(
                rt=mean,
                intensity=float(y[peak_idx]),
                area=area,
                prominence=prominence,
                p_value=p_display,
                left_idx=left,
                right_idx=right,
            )
        )

    accepted.sort(key=lambda p: p.rt)
    return accepted
