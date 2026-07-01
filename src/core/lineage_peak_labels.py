# src/core/lineage_peak_labels.py
"""
Map picked peaks to suspected lineage identities from pedigree evaluation.

After lineage analysis, each peak on the target compound chromatogram can be
matched to a pedigree-chosen retention time and labeled as intended product,
null truncation, or unknown.
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple

from src.core.plot_text import sanitize_plot_text
from src.core.time_display import convert_time_value
from src.models.analysis_settings import TimeUnit
from src.models.peak_result import PeakAnalysisBatchResult, PeakAnalysisResult, PickedPeak
from src.models.pedigree_result import LineageAnalysisResult, LineagePanel, PedigreeNodeRecord


def chosen_rt_for_record(record: PedigreeNodeRecord) -> Optional[float]:
    """Return the pedigree-chosen RT for a node, if any."""
    if record.score_test_rt is not None:
        return float(record.score_test_rt)
    if record.bayesian_pick is not None:
        return float(record.bayesian_pick)
    if record.initial_most_significant_picks:
        return float(record.initial_most_significant_picks[0])
    return None


def _class_display_name(class_bbs: Sequence[str]) -> str:
    if not class_bbs:
        return "root"
    return sanitize_plot_text("-".join(class_bbs))


def suspected_id_for_panel(
    panel: LineagePanel,
    *,
    leaf_class_bbs: Sequence[str],
) -> str:
    """Human-readable suspected identity for one lineage tier."""
    name = _class_display_name(panel.class_bbs)
    if list(panel.class_bbs) == list(leaf_class_bbs):
        return f"intended product ({name})"
    if not panel.class_bbs:
        return "root (all null)"
    return f"null truncation ({name})"


def is_intended_product_label(suspected_peak_id: Optional[str]) -> bool:
    """Return True when a peak label denotes the lineage intended product."""
    return bool(suspected_peak_id and suspected_peak_id.startswith("intended product"))


def lineage_rt_assignments(
    result: LineageAnalysisResult,
) -> List[Tuple[float, str, int]]:
    """
    Return (chosen_rt, suspected_id, tier) for each panel with a chosen RT.

    RT values are in the lineage analysis time unit.
    """
    assignments: List[Tuple[float, str, int]] = []
    for panel in result.panels:
        chosen = chosen_rt_for_record(panel.record)
        if chosen is None:
            continue
        label = suspected_id_for_panel(panel, leaf_class_bbs=result.leaf_class_bbs)
        assignments.append((chosen, label, panel.tier))
    return assignments


def match_peak_to_assignment(
    peak_rt_stored: float,
    assignments: Sequence[Tuple[float, str, int]],
    *,
    stored_time_unit: TimeUnit,
    lineage_time_unit: TimeUnit,
    tolerance: float,
) -> str:
    """
    Match one peak RT to the closest lineage assignment within tolerance.

    ``tolerance`` is in lineage time units (same as pedigree evaluation).
    """
    peak_rt_lineage = convert_time_value(peak_rt_stored, stored_time_unit, lineage_time_unit)
    tol_stored = convert_time_value(tolerance, lineage_time_unit, stored_time_unit)
    best_label = "unknown"
    best_dist = tol_stored + 1.0
    best_tier = -1

    for chosen_rt, label, tier in assignments:
        dist = abs(peak_rt_lineage - chosen_rt)
        if dist > tolerance:
            continue
        dist_stored = abs(peak_rt_stored - convert_time_value(chosen_rt, lineage_time_unit, stored_time_unit))
        if dist_stored < best_dist or (dist_stored == best_dist and tier > best_tier):
            best_dist = dist_stored
            best_tier = tier
            best_label = label

    return best_label


def label_peaks_from_lineage(
    entry: PeakAnalysisResult,
    result: LineageAnalysisResult,
    *,
    stored_time_unit: TimeUnit,
) -> PeakAnalysisResult:
    """Return a copy of ``entry`` with ``suspected_peak_id`` set on each peak."""
    if result.channel != entry.channel:
        return entry

    assignments = lineage_rt_assignments(result)
    if not assignments:
        labeled = [replace(peak, suspected_peak_id="unknown") for peak in entry.peaks]
        return replace(entry, peaks=labeled)

    lineage_unit: TimeUnit = result.settings.time_unit
    tolerance = float(result.settings.tolerance)
    labeled_peaks: List[PickedPeak] = []
    for peak in entry.peaks:
        label = match_peak_to_assignment(
            peak.rt,
            assignments,
            stored_time_unit=stored_time_unit,
            lineage_time_unit=lineage_unit,
            tolerance=tolerance,
        )
        labeled_peaks.append(replace(peak, suspected_peak_id=label))

    return replace(entry, peaks=labeled_peaks)


def apply_lineage_labels_to_batch(
    batch: PeakAnalysisBatchResult,
    result: LineageAnalysisResult,
    compound_id: str,
    *,
    stored_time_unit: TimeUnit,
) -> PeakAnalysisBatchResult:
    """Apply suspected peak IDs to one compound in a peak-pick batch."""
    key = str(compound_id).strip()
    updated: List[PeakAnalysisResult] = []
    changed = False
    for entry in batch.results:
        if str(entry.compound_id).strip() != key:
            updated.append(entry)
            continue
        labeled = label_peaks_from_lineage(entry, result, stored_time_unit=stored_time_unit)
        updated.append(labeled)
        changed = True

    if not changed:
        return batch

    return PeakAnalysisBatchResult(
        settings=batch.settings,
        channel=batch.channel,
        results=updated,
        backend_name=batch.backend_name,
        computed_at=batch.computed_at,
    )
