# src/core/lcseq_backend.py
"""Analysis engine backend: Rust ``lcseq`` when built, Python fallback otherwise."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple

from src.core.peak_picker_gaussian import find_peaks_gaussian
from src.core.peak_picker_python import estimate_baseline as py_estimate_baseline
from src.core.peak_picker_python import find_peaks as py_find_peaks
from src.core.time_display import convert_time_series
from src.models.analysis_settings import AnalysisSettings, TimeUnit
from src.models.peak_result import BaselineEstimate, PickedPeak

logger = logging.getLogger(__name__)


class AnalysisEngineError(RuntimeError):
    """Raised when peak/pedigree analysis cannot run."""


@dataclass
class BackendInfo:
    name: str
    is_native: bool
    detail: str


class PeakPickerBackend(Protocol):
    def info(self) -> BackendInfo: ...

    def find_peaks(
        self,
        rt: Sequence[float],
        intensity: Sequence[float],
        alpha: float,
    ) -> List[PickedPeak]: ...

    def estimate_baseline(self, intensity: Sequence[float]) -> BaselineEstimate: ...


def _attach_integration_bounds(
    rt: Sequence[float],
    raw_peaks: list,
    *,
    left_attr: str = "left_idx",
    right_attr: str = "right_idx",
) -> List[PickedPeak]:
    out: List[PickedPeak] = []
    for i, p in enumerate(raw_peaks):
        left_i = getattr(p, left_attr, 0)
        right_i = getattr(p, right_attr, 0)
        left_rt = float(rt[left_i]) if rt else p.rt
        right_rt = float(rt[right_i]) if rt else p.rt
        out.append(
            PickedPeak(
                peak_index=i + 1,
                rt=float(p.rt),
                intensity=float(p.intensity),
                area=float(p.area),
                prominence=float(p.prominence),
                p_value=float(p.p_value),
                left_rt=left_rt,
                right_rt=right_rt,
            )
        )
    return out


class NativeLcseqBackend:
    """Rust extension from LC-Seq-New-master."""

    def info(self) -> BackendInfo:
        return BackendInfo(
            name="lcseq (Rust)",
            is_native=True,
            detail="Production analysis engine",
        )

    def find_peaks(
        self,
        rt: Sequence[float],
        intensity: Sequence[float],
        alpha: float,
    ) -> List[PickedPeak]:
        import numpy as np

        from lcseq import find_peaks as native_find_peaks

        rt_arr = np.asarray(rt, dtype=np.float64)
        int_arr = np.asarray(intensity, dtype=np.float64)
        native = native_find_peaks(rt_arr, int_arr, alpha)
        peaks: List[PickedPeak] = []
        for i, p in enumerate(native):
            peaks.append(
                PickedPeak(
                    peak_index=i + 1,
                    rt=float(p.rt),
                    intensity=float(p.intensity),
                    area=float(p.area),
                    prominence=float(p.prominence),
                    p_value=float(p.p_value),
                )
            )
        return peaks

    def estimate_baseline(self, intensity: Sequence[float]) -> BaselineEstimate:
        b = py_estimate_baseline(intensity)
        return BaselineEstimate(mu=b.mu, sigma=b.sigma, dispersion_r=b.dispersion_r)


class PythonLcseqBackend:
    """Pure-Python mirror of Rust picker (for dev / when Rust is not built)."""

    def info(self) -> BackendInfo:
        return BackendInfo(
            name="Python fallback",
            is_native=False,
            detail="Install Rust + maturin for the production engine (see docs/DEVELOPER_SETUP.md)",
        )

    def find_peaks(
        self,
        rt: Sequence[float],
        intensity: Sequence[float],
        alpha: float,
    ) -> List[PickedPeak]:
        raw = py_find_peaks(rt, intensity, alpha)
        return _attach_integration_bounds(rt, raw)

    def estimate_baseline(self, intensity: Sequence[float]) -> BaselineEstimate:
        b = py_estimate_baseline(intensity)
        return BaselineEstimate(mu=b.mu, sigma=b.sigma, dispersion_r=b.dispersion_r)


def select_direct_pick_product_rt(
    peaks: Sequence[PickedPeak],
    settings: AnalysisSettings,
    *,
    trace_max_intensity: float,
) -> Optional[float]:
    """
    Choose the product RT for Direct Pick assignment (CalculateRTs.ipynb rule).

    Legacy notebooks fit Gaussians to all significant peaks, then assign the
    cyclized product as the **latest** retention time among accepted fits
    (``best_mean`` loop in ``docs/archive/notebooks/CalculateRTs.ipynb``).
    """
    if not peaks:
        return None

    candidates: Sequence[PickedPeak] = peaks
    if settings.uses_old_school_peak_picker:
        factor, _, _, minimum_rt = settings.gaussian_picker_params()
        height_cutoff = trace_max_intensity * factor
        candidates = [
            p
            for p in peaks
            if p.rt >= minimum_rt and p.intensity >= height_cutoff
        ]

    if not candidates:
        return None
    return float(max(candidates, key=lambda p: p.rt).rt)


def find_peaks_for_settings(
    rt: Sequence[float],
    intensity: Sequence[float],
    settings: AnalysisSettings,
) -> List[PickedPeak]:
    """Pick peaks using the algorithm selected in ``settings``."""
    if settings.uses_old_school_peak_picker:
        factor, fit_width, stddev_thr, min_rt = settings.gaussian_picker_params()
        raw = find_peaks_gaussian(
            rt,
            intensity,
            min_height_threshold_factor=factor,
            fit_width=fit_width,
            stddev_threshold=stddev_thr,
            minimum_rt=min_rt,
        )
        return _attach_integration_bounds(rt, raw)

    backend = get_peak_picker_backend()
    return backend.find_peaks(rt, intensity, settings.alpha)


def prepare_rt_for_settings(
    times: Sequence[float],
    settings: AnalysisSettings,
    *,
    stored_time_unit: TimeUnit,
) -> List[float]:
    """Convert chromatogram times to ``settings.time_unit`` when needed."""
    rt = [float(t) for t in times]
    if stored_time_unit != settings.time_unit:
        return convert_time_series(rt, stored_time_unit, settings.time_unit)
    return rt


_cached_backend: Optional[PeakPickerBackend] = None

# Canonical probe: late peak on a low local baseline after high early elution.
# Stale lcseq builds that still use a global Poisson picker fail this check.
_PARITY_PROBE_RT = [float(i) for i in range(120)]
_PARITY_PROBE_INTENSITY = [45.0] * 40 + [3.0] * 80
_PARITY_PROBE_INTENSITY[85] = 120.0
_PARITY_PROBE_INTENSITY[84] = 40.0
_PARITY_PROBE_INTENSITY[86] = 40.0
_PARITY_PROBE_ALPHA = 0.001


def _native_peak_picker_matches_python() -> bool:
    """Return True when the installed lcseq picker matches the Python reference."""
    try:
        import numpy as np
        from lcseq import find_peaks as native_find_peaks
    except ImportError:
        return False

    py_raw = py_find_peaks(_PARITY_PROBE_RT, _PARITY_PROBE_INTENSITY, _PARITY_PROBE_ALPHA)
    native = native_find_peaks(
        np.asarray(_PARITY_PROBE_RT, dtype=np.float64),
        np.asarray(_PARITY_PROBE_INTENSITY, dtype=np.float64),
        _PARITY_PROBE_ALPHA,
    )
    if len(py_raw) != len(native):
        logger.error(
            "lcseq peak picker parity failed: expected %d peaks, native returned %d",
            len(py_raw),
            len(native),
        )
        return False
    for py_peak, native_peak in zip(py_raw, native):
        if abs(float(py_peak.rt) - float(native_peak.rt)) > 1e-6:
            logger.error(
                "lcseq peak picker parity failed: rt mismatch %.6f vs %.6f",
                py_peak.rt,
                native_peak.rt,
            )
            return False
        if abs(float(py_peak.p_value) - float(native_peak.p_value)) > 1e-6:
            logger.error(
                "lcseq peak picker parity failed: p-value mismatch at rt %.1f",
                py_peak.rt,
            )
            return False
    return True


def is_native_backend_available() -> bool:
    try:
        import lcseq  # noqa: F401

        return True
    except ImportError:
        return False


def get_peak_picker_backend() -> PeakPickerBackend:
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend
    if is_native_backend_available() and _native_peak_picker_matches_python():
        _cached_backend = NativeLcseqBackend()
        logger.info("Using Rust lcseq analysis engine")
    else:
        if is_native_backend_available():
            logger.warning(
                "lcseq extension is installed but failed peak-picker parity check; "
                "using Python fallback. Rebuild LC-Seq-New-master with maturin "
                "(close the app first) — see docs/DEVELOPER_SETUP.md."
            )
        else:
            logger.warning("lcseq Rust extension not found; using Python fallback")
        _cached_backend = PythonLcseqBackend()
    return _cached_backend


def convert_times(
    times: Sequence[float],
    from_unit: TimeUnit,
    to_unit: TimeUnit,
) -> List[float]:
    """Convert stored chromatogram times between seconds and minutes."""
    return convert_time_series(times, from_unit, to_unit)
