# src/core/lcseq_backend.py
"""Analysis engine backend: Rust ``lcseq`` when built, Python fallback otherwise."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple

from src.core.peak_picker_python import estimate_baseline as py_estimate_baseline
from src.core.peak_picker_python import find_peaks as py_find_peaks
from src.core.time_display import convert_time_series
from src.models.analysis_settings import TimeUnit
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


_cached_backend: Optional[PeakPickerBackend] = None


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
    if is_native_backend_available():
        _cached_backend = NativeLcseqBackend()
        logger.info("Using Rust lcseq analysis engine")
    else:
        _cached_backend = PythonLcseqBackend()
        logger.warning("lcseq Rust extension not found; using Python fallback")
    return _cached_backend


def convert_times(
    times: Sequence[float],
    from_unit: TimeUnit,
    to_unit: TimeUnit,
) -> List[float]:
    """Convert stored chromatogram times between seconds and minutes."""
    return convert_time_series(times, from_unit, to_unit)
