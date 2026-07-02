# src/core/peak_analysis_service.py
"""Peak picking and integration for a single compound chromatogram."""

from __future__ import annotations

from typing import List

from src.core.lcseq_backend import (
    AnalysisEngineError,
    find_peaks_for_settings,
    get_peak_picker_backend,
    prepare_rt_for_settings,
)
from src.core.peak_picker_python import nearest_index, valley_bounds
from src.core.peak_quality_filter import apply_peak_quality_filter
from src.models.analysis_settings import AnalysisSettings
from src.models.compound import Compound
from src.models.peak_result import PeakAnalysisBatchResult, PeakAnalysisResult, PickedPeak


def _apply_pct_area(peaks: List[PickedPeak]) -> None:
    total = sum(p.area for p in peaks)
    if total <= 0:
        return
    for p in peaks:
        p.pct_area = 100.0 * p.area / total


def _add_integration_bounds_from_intensity(
    rt: List[float],
    intensity: List[float],
    peaks: List[PickedPeak],
) -> None:
    for p in peaks:
        idx = nearest_index(rt, p.rt)
        left, right = valley_bounds(intensity, idx)
        p.left_rt = float(rt[left])
        p.right_rt = float(rt[right])


def analyze_peaks(
    compound: Compound,
    settings: AnalysisSettings,
) -> PeakAnalysisResult:
    """
    Pick and integrate peaks on one compound trace.

    Raises:
        AnalysisEngineError: Missing data or invalid input.
    """
    if not compound.data_points:
        raise AnalysisEngineError("Compound has no chromatogram data")

    try:
        times, counts = compound.get_time_series(settings.count_channel)
    except ValueError as exc:
        raise AnalysisEngineError(str(exc)) from exc

    if len(times) < 3:
        raise AnalysisEngineError("Need at least 3 time points for peak picking")

    rt = prepare_rt_for_settings(times, settings, stored_time_unit=settings.stored_time_unit)
    intensity = [float(c) for c in counts]

    all_peaks = find_peaks_for_settings(rt, intensity, settings)
    _add_integration_bounds_from_intensity(rt, intensity, all_peaks)
    _apply_pct_area(all_peaks)

    baseline = get_peak_picker_backend().estimate_baseline(intensity)
    backend_name = (
        "old-school (Gaussian)"
        if settings.uses_old_school_peak_picker
        else get_peak_picker_backend().info().name
    )
    result = PeakAnalysisResult(
        compound_id=compound.compound_id,
        channel=settings.count_channel,
        settings=settings,
        peaks=[],
        all_peaks=all_peaks,
        baseline=baseline,
        primary_compound_id=compound.primary_compound_id,
        variant_label=compound.variant_label,
        backend_name=backend_name,
    )
    return apply_peak_quality_filter(result, allow_null_truncation_rescue=False)


def estimate_baseline_for_compound(
    compound: Compound,
    settings: AnalysisSettings,
) -> PeakAnalysisResult:
    """Estimate baseline only (no peak picking) for one compound trace."""
    if not compound.data_points:
        raise AnalysisEngineError("Compound has no chromatogram data")
    try:
        _times, counts = compound.get_time_series(settings.count_channel)
    except ValueError as exc:
        raise AnalysisEngineError(str(exc)) from exc
    intensity = [float(c) for c in counts]
    backend = get_peak_picker_backend()
    baseline = backend.estimate_baseline(intensity)
    return PeakAnalysisResult(
        compound_id=compound.compound_id,
        channel=settings.count_channel,
        settings=settings,
        peaks=[],
        baseline=baseline,
        primary_compound_id=compound.primary_compound_id,
        variant_label=compound.variant_label,
        backend_name=backend.info().name,
    )


def analyze_peaks_batch(
    compounds: List[Compound],
    settings: AnalysisSettings,
) -> PeakAnalysisBatchResult:
    """
    Pick and integrate peaks on multiple compound traces (same count channel).

    Skips compounds that fail and raises if none succeed.
    """
    if not compounds:
        raise AnalysisEngineError("No compounds selected")

    results: List[PeakAnalysisResult] = []
    errors: List[str] = []
    backend_name = "unknown"
    for compound in compounds:
        try:
            one = analyze_peaks(compound, settings)
            results.append(one)
            backend_name = one.backend_name
        except AnalysisEngineError as exc:
            label = compound.primary_compound_id or compound.compound_id
            if compound.variant_label:
                label = f"{label} ({compound.variant_label})"
            errors.append(f"{label}: {exc}")

    if not results:
        detail = "; ".join(errors) if errors else "unknown error"
        raise AnalysisEngineError(f"Peak picking failed for all compounds: {detail}")

    return PeakAnalysisBatchResult(
        settings=settings,
        channel=settings.count_channel,
        results=results,
        backend_name=backend_name,
    )


def estimate_baselines_batch(
    compounds: List[Compound],
    settings: AnalysisSettings,
) -> PeakAnalysisBatchResult:
    """Estimate per-trace baselines without peak picking."""
    if not compounds:
        raise AnalysisEngineError("No compounds selected")

    results: List[PeakAnalysisResult] = []
    errors: List[str] = []
    backend_name = "unknown"
    for compound in compounds:
        try:
            one = estimate_baseline_for_compound(compound, settings)
            results.append(one)
            backend_name = one.backend_name
        except AnalysisEngineError as exc:
            label = compound.primary_compound_id or compound.compound_id
            if compound.variant_label:
                label = f"{label} ({compound.variant_label})"
            errors.append(f"{label}: {exc}")

    if not results:
        detail = "; ".join(errors) if errors else "unknown error"
        raise AnalysisEngineError(f"Baseline estimation failed for all compounds: {detail}")

    return PeakAnalysisBatchResult(
        settings=settings,
        channel=settings.count_channel,
        results=results,
        backend_name=backend_name,
    )
