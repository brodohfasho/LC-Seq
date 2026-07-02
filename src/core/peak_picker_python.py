# src/core/peak_picker_python.py
"""
Pure-Python peak picker mirroring LC-Seq-New-master ``peaks/`` (baseline, picker, significance).

Used when the Rust ``lcseq`` extension is not built. Install Rust + maturin for the
production engine (see docs/DEVELOPER_SETUP.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

try:
    from scipy.stats import nbinom, poisson
except ImportError:  # pragma: no cover
    nbinom = None  # type: ignore
    poisson = None  # type: ignore

DEFAULT_SIGMA: float = 2.0
MAX_ITER: int = 10
MIN_BASELINE_POINTS: int = 3
DEFAULT_ROLLING_HALF_WINDOW: int = 30
MAX_ROLLING_EXPAND: int = 4


@dataclass
class _Baseline:
    mu: float
    sigma: float
    dispersion_r: Optional[float]


@dataclass
class _Peak:
    rt: float
    intensity: float
    area: float
    prominence: float
    p_value: float
    left_idx: int
    right_idx: int


def _median(data: List[float]) -> float:
    data = sorted(data)
    n = len(data)
    if n == 0:
        return 0.0
    if n % 2 == 0:
        return (data[n // 2 - 1] + data[n // 2]) / 2.0
    return data[n // 2]


def _baseline_from_values(keep: List[float]) -> _Baseline:
    """Sigma-clip a sample set and estimate (μ, σ, dispersion r)."""
    if len(keep) < MIN_BASELINE_POINTS:
        return _Baseline(mu=0.0, sigma=0.0, dispersion_r=None)
    for _ in range(MAX_ITER):
        n = len(keep)
        mean = sum(keep) / n
        var = sum((x - mean) ** 2 for x in keep) / n
        cutoff = mean + DEFAULT_SIGMA * math.sqrt(var)
        new_keep = [x for x in keep if x <= cutoff]
        if len(new_keep) == len(keep) or len(new_keep) < MIN_BASELINE_POINTS:
            break
        keep = new_keep
    mu = _median(keep)
    n = len(keep)
    var = sum((x - mu) ** 2 for x in keep) / n
    sigma = math.sqrt(var)
    dispersion_r = (mu * mu) / (var - mu) if var > mu and mu > 1e-9 else None
    return _Baseline(mu=mu, sigma=sigma, dispersion_r=dispersion_r)


def estimate_baseline(intensity: Sequence[float]) -> _Baseline:
    """Sigma-clipped global baseline (matches Rust ``peaks/baseline.rs``)."""
    keep = [float(x) for x in intensity if not math.isnan(x)]
    return _baseline_from_values(keep)


def _rolling_baseline_samples(
    intensity: Sequence[float],
    center: int,
    exclude_left: int,
    exclude_right: int,
    half_window: int,
) -> List[float]:
    """Collect non-NaN intensities in a window around ``center``, excluding the peak valley."""
    n = len(intensity)
    start = max(0, center - half_window)
    end = min(n - 1, center + half_window)
    samples: List[float] = []
    for idx in range(start, end + 1):
        if idx < exclude_left or idx > exclude_right:
            value = float(intensity[idx])
            if not math.isnan(value):
                samples.append(value)
    return samples


def estimate_rolling_baseline(
    intensity: Sequence[float],
    peak_idx: int,
    exclude_left: int,
    exclude_right: int,
) -> _Baseline:
    """Rolling sigma-clipped baseline for one candidate peak (matches Rust ``baseline.rs``)."""
    if len(intensity) == 0:
        return _Baseline(mu=0.0, sigma=0.0, dispersion_r=None)
    n = len(intensity)
    half = min(DEFAULT_ROLLING_HALF_WINDOW, n // 2)
    if half == 0 and n >= MIN_BASELINE_POINTS:
        half = 1
    for _ in range(MAX_ROLLING_EXPAND + 1):
        samples = _rolling_baseline_samples(
            intensity, peak_idx, exclude_left, exclude_right, half
        )
        if len(samples) >= MIN_BASELINE_POINTS:
            return _baseline_from_values(samples)
        if half >= n // 2:
            break
        half = min(half * 2, n // 2)
    return estimate_baseline(intensity)


def _scaled_dispersion(baseline: _Baseline, width: float) -> Optional[float]:
    if baseline.dispersion_r is not None:
        return baseline.dispersion_r * width
    return None


def _poisson_upper(k: int, mu: float) -> float:
    if poisson is None:
        raise ImportError("scipy is required for the Python analysis fallback")
    if k <= 0:
        return 1.0
    return float(1.0 - poisson.cdf(k - 1, mu))


def p_at_least(k: float, mu: float, dispersion_r: Optional[float]) -> float:
    """Upper tail P(X >= k) under NB or Poisson fallback."""
    if k <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    if poisson is None or nbinom is None:
        raise ImportError("scipy is required for the Python analysis fallback")
    k_int = max(1, int(round(k)))
    if dispersion_r is not None and math.isfinite(dispersion_r) and dispersion_r > 1e-6:
        p = dispersion_r / (dispersion_r + mu)
        try:
            surv = 1.0 - float(nbinom.cdf(k_int - 1, dispersion_r, p))
        except Exception:
            surv = _poisson_upper(k_int, mu)
    else:
        surv = _poisson_upper(k_int, mu)
    return max(0.0, min(1.0, surv))


def _local_maxima(intensity: Sequence[float]) -> List[int]:
    n = len(intensity)
    if n < 3:
        return []
    peaks: List[int] = []
    i = 1
    while i < n - 1:
        if intensity[i - 1] < intensity[i]:
            j = i
            while j + 1 < n and intensity[j + 1] == intensity[i]:
                j += 1
            if j + 1 < n and intensity[j + 1] < intensity[i]:
                peaks.append(i)
            i = j + 1
        else:
            i += 1
    return peaks


def valley_bounds(intensity: Sequence[float], peak_idx: int) -> Tuple[int, int]:
    left = peak_idx
    while left > 0 and intensity[left - 1] < intensity[left]:
        left -= 1
    right = peak_idx
    while right + 1 < len(intensity) and intensity[right + 1] < intensity[right]:
        right += 1
    return left, right


def _compute_prominence(intensity: Sequence[float], peak_idx: int) -> float:
    h = float(intensity[peak_idx])
    left_min = h
    k = peak_idx
    while k > 0:
        k -= 1
        if intensity[k] > h:
            break
        if intensity[k] < left_min:
            left_min = float(intensity[k])
    right_min = h
    k = peak_idx
    while k + 1 < len(intensity):
        k += 1
        if intensity[k] > h:
            break
        if intensity[k] < right_min:
            right_min = float(intensity[k])
    return h - max(left_min, right_min)


def nearest_index(rt: Sequence[float], target: float) -> int:
    best = 0
    best_d = abs(float(rt[0]) - target)
    for i, t in enumerate(rt):
        d = abs(float(t) - target)
        if d < best_d:
            best_d = d
            best = i
    return best


def prominence_at_rt(
    rt: Sequence[float],
    intensity: Sequence[float],
    target_rt: float,
) -> Optional[float]:
    """Return peak prominence at the time point nearest ``target_rt``."""
    if len(rt) != len(intensity) or len(rt) < 3:
        return None
    idx = nearest_index(rt, target_rt)
    return _compute_prominence(intensity, idx)


def find_peaks(
    rt: Sequence[float],
    intensity: Sequence[float],
    alpha: float,
) -> List[_Peak]:
    """NB-significance peak picker (matches Rust ``peaks/picker.rs``)."""
    if len(rt) != len(intensity):
        raise ValueError("rt and intensity must have the same length")
    if len(rt) < 3:
        return []
    maxima = _local_maxima(intensity)
    peaks: List[_Peak] = []
    for idx in maxima:
        left, right = valley_bounds(intensity, idx)
        baseline = estimate_rolling_baseline(intensity, idx, left, right)
        height = float(intensity[idx])
        if height <= baseline.mu:
            continue
        width = float(right - left + 1)
        area = float(sum(float(intensity[i]) for i in range(left, right + 1)))
        prominence = _compute_prominence(intensity, idx)
        p_height = p_at_least(height, baseline.mu, baseline.dispersion_r)
        p_area = p_at_least(area, baseline.mu * width, _scaled_dispersion(baseline, width))
        p_value = min(p_height, p_area)
        if p_height < alpha / 2.0 and p_area < alpha / 2.0:
            peaks.append(
                _Peak(
                    rt=float(rt[idx]),
                    intensity=height,
                    area=area,
                    prominence=prominence,
                    p_value=p_value,
                    left_idx=left,
                    right_idx=right,
                )
            )
    return peaks
