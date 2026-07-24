# src/core/pedigree_backend.py
"""Rust pedigree engine wrapper (evaluate_library, diagnose_class)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import numpy as np

from src.core.lcseq_backend import AnalysisEngineError, is_native_backend_available
from src.core.pedigree_adapter import Chromatogram, ChromatogramKey
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeNodeRecord

logger = logging.getLogger(__name__)

ChromatogramInput = Tuple[np.ndarray, np.ndarray]


def picker_kwargs_from_settings(settings: AnalysisSettings) -> Dict[str, Any]:
    """Keyword arguments for lcseq peak-picker mode (modern vs old-school)."""
    factor, fit_width, stddev_thr, min_rt = settings.gaussian_picker_params()
    return {
        "peak_picking_algorithm": settings.peak_picking_algorithm,
        "gaussian_min_height_factor": factor,
        "gaussian_fit_width": fit_width,
        "gaussian_stddev_threshold": stddev_thr,
        "gaussian_minimum_rt": min_rt,
    }


class PedigreeBackend(Protocol):
    def info(self) -> str: ...

    def evaluate_library(
        self,
        bbs_per_position: List[List[str]],
        null_token: str,
        chromatograms: Dict[ChromatogramKey, ChromatogramInput],
        tolerance: float,
        alpha: float,
        min_prominence: float = 0.0,
        min_pct_area: float = 0.0,
        *,
        settings: Optional[AnalysisSettings] = None,
    ) -> List[PedigreeNodeRecord]: ...

    def diagnose_class(
        self,
        replicates: Sequence[ChromatogramInput],
        effective_threshold: float,
        tolerance: float,
        alpha: float,
        min_prominence: float = 0.0,
        min_pct_area: float = 0.0,
        allow_null_truncation_rescue: bool = True,
        *,
        settings: Optional[AnalysisSettings] = None,
    ): ...


def _record_from_native(node) -> PedigreeNodeRecord:
    return PedigreeNodeRecord(
        id=str(node.id),
        label=str(node.label),
        tier=int(node.tier),
        kind=str(node.kind),
        members=[str(m) for m in node.members],
        parent_ids=[str(p) for p in getattr(node, "parent_ids", [])],
        evaluated=bool(node.evaluated),
        passed=bool(node.passed),
        insufficient_data=bool(node.insufficient_data),
        effective_threshold=_optional_float(node.effective_threshold),
        score_test_rt=_optional_float(node.score_test_rt),
        score_test_rt_se=_optional_float(node.score_test_rt_se),
        score_test_p_value=_optional_float(node.score_test_p_value),
        bayesian_pick=_optional_float(node.bayesian_pick),
        bayesian_pick_posterior=_optional_float(node.bayesian_pick_posterior),
        n_replicates=int(node.n_replicates),
        n_replicates_with_signal=int(node.n_replicates_with_signal),
        initial_most_significant_picks=[
            float(x)
            for x in (node.initial_most_significant_picks or [])
            if x is not None
        ],
    )


def _optional_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class NativePedigreeBackend:
    """Rust ``lcseq`` pedigree evaluation."""

    def info(self) -> str:
        return "lcseq (Rust)"

    def evaluate_library(
        self,
        bbs_per_position: List[List[str]],
        null_token: str,
        chromatograms: Dict[ChromatogramKey, ChromatogramInput],
        tolerance: float,
        alpha: float,
        min_prominence: float = 0.0,
        min_pct_area: float = 0.0,
        *,
        settings: Optional[AnalysisSettings] = None,
    ) -> List[PedigreeNodeRecord]:
        import lcseq

        py_chroms = {
            key: (np.asarray(rt, dtype=np.float64), np.asarray(intensity, dtype=np.float64))
            for key, (rt, intensity) in chromatograms.items()
        }
        picker_kwargs: Dict[str, Any] = {}
        if settings is not None:
            picker_kwargs = picker_kwargs_from_settings(settings)
            min_prominence, min_pct_area = settings.effective_quality_params()
        try:
            native = lcseq.evaluate_library(
                bbs_per_position=bbs_per_position,
                null_token=null_token,
                chromatograms=py_chroms,
                tolerance=tolerance,
                alpha=alpha,
                min_prominence=min_prominence,
                min_pct_area=min_pct_area,
                **picker_kwargs,
            )
        except TypeError as exc:
            if settings is not None and settings.uses_old_school_peak_picker:
                raise AnalysisEngineError(
                    "Old-school pedigree peak picking requires a rebuilt lcseq extension. "
                    "See dev/DEVELOPER_SETUP.md (maturin develop in LC-Seq-New-master)."
                ) from exc
            native = lcseq.evaluate_library(
                bbs_per_position=bbs_per_position,
                null_token=null_token,
                chromatograms=py_chroms,
                tolerance=tolerance,
                alpha=alpha,
                min_prominence=min_prominence,
                min_pct_area=min_pct_area,
            )
        return [_record_from_native(node) for node in native]

    def diagnose_class(
        self,
        replicates: Sequence[ChromatogramInput],
        effective_threshold: float,
        tolerance: float,
        alpha: float,
        min_prominence: float = 0.0,
        min_pct_area: float = 0.0,
        allow_null_truncation_rescue: bool = True,
        *,
        settings: Optional[AnalysisSettings] = None,
    ):
        import lcseq

        payload = [
            (np.asarray(rt, dtype=np.float64), np.asarray(intensity, dtype=np.float64))
            for rt, intensity in replicates
        ]
        picker_kwargs: Dict[str, Any] = {}
        if settings is not None:
            picker_kwargs = picker_kwargs_from_settings(settings)
            min_prominence, min_pct_area = settings.effective_quality_params()
        try:
            return lcseq.diagnose_class(
                payload,
                effective_threshold,
                tolerance,
                alpha,
                min_prominence=min_prominence,
                min_pct_area=min_pct_area,
                allow_null_truncation_rescue=allow_null_truncation_rescue,
                **picker_kwargs,
            )
        except TypeError as exc:
            if settings is not None and settings.uses_old_school_peak_picker:
                raise AnalysisEngineError(
                    "Old-school lineage peak picking requires a rebuilt lcseq extension. "
                    "See dev/DEVELOPER_SETUP.md."
                ) from exc
            return lcseq.diagnose_class(
                payload,
                effective_threshold,
                tolerance,
                alpha,
                min_prominence=min_prominence,
                min_pct_area=min_pct_area,
                allow_null_truncation_rescue=allow_null_truncation_rescue,
            )


_cached_pedigree_backend: Optional[PedigreeBackend] = None


def get_pedigree_backend() -> PedigreeBackend:
    """Return the Rust pedigree backend or raise with install instructions."""
    global _cached_pedigree_backend
    if _cached_pedigree_backend is not None:
        return _cached_pedigree_backend
    if not is_native_backend_available():
        raise AnalysisEngineError(
            "Lineage and pedigree analysis require the Rust lcseq extension. "
            "See dev/DEVELOPER_SETUP.md to build LC-Seq-New-master with maturin."
        )
    _cached_pedigree_backend = NativePedigreeBackend()
    logger.info("Using Rust lcseq pedigree engine")
    return _cached_pedigree_backend


def pedigree_backend_available() -> bool:
    return is_native_backend_available()
