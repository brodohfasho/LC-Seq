# src/core/del_cycle_tree/service.py
"""Build DEL-cycle tree data from library compounds and pedigree results."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.data_store import DataStore
from src.core.del_cycle_tree.analyzer import (
    dedupe_rows_by_position,
    sort_rows,
    verify_reaction_sequences,
)
from src.core.del_cycle_tree.builder import create_tree, prune_tree
from src.core.del_cycle_tree.models import DelCycleRow, DelCycleTreeData
from src.core.del_cycle_tree.positions import build_bb_index_by_level, positions_c_to_n
from src.core.lcseq_backend import find_peaks_for_settings
from src.core.lineage_service import ProgressCallback, load_all_compounds
from src.core.pedigree_adapter import filter_compounds_by_variant
from src.core.pedigree_export import chosen_rt_for_record, positions_n_to_c_from_record
from src.core.time_display import convert_time_series
from src.models.analysis_settings import AnalysisSettings, TimeUnit
from src.models.compound import Compound
from src.models.pedigree_result import PedigreeAnalysisResult, PedigreeNodeRecord
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

# Fraction of overall DEL-tree work attributed to each phase.
_LOAD_PROGRESS_END = 0.30
_RT_PROGRESS_END = 0.88
_ANALYZE_PROGRESS_END = 0.97


def _report_fraction(
    progress_callback: Optional[ProgressCallback],
    fraction: float,
    status: str,
) -> None:
    """Report fine-grained progress on a 0–1000 scale (UI maps to 0–100%)."""
    if progress_callback is None:
        return
    clamped = min(1.0, max(0.0, fraction))
    progress_callback(int(round(clamped * 1000)), 1000, status)


def build_pedigree_rt_lookup(
    records: Sequence[PedigreeNodeRecord],
    config: SpreadsheetConfig,
) -> Dict[Tuple[str, ...], float]:
    """Map C→N position tuples to pedigree-chosen RT for compound nodes."""
    lookup: Dict[Tuple[str, ...], float] = {}
    for record in records:
        if record.kind != "compound":
            continue
        chosen = chosen_rt_for_record(record)
        if chosen is None:
            continue
        n_to_c = positions_n_to_c_from_record(
            record,
            library_cycle_count=config.library_cycle_count,
            null_token=config.null_token,
        )
        c_to_n = tuple(reversed(n_to_c))
        lookup[c_to_n] = float(chosen)
    return lookup


def _pick_rt_for_compound(
    compound: Compound,
    channel: str,
    settings: AnalysisSettings,
    time_unit: TimeUnit,
    config: SpreadsheetConfig,
) -> Optional[float]:
    try:
        times, counts = compound.get_time_series(channel)
    except ValueError:
        return None
    if len(times) < 3:
        return None
    stored_unit: TimeUnit = (
        "minutes" if config.analysis_time_unit == "minutes" else "seconds"
    )
    if stored_unit != time_unit:
        times = convert_time_series(times, stored_unit, time_unit)
    peaks = find_peaks_for_settings(times, counts, settings)
    if not peaks:
        return None
    return float(peaks[0].rt)


def build_del_cycle_rows(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    channel: str,
    settings: AnalysisSettings,
    time_unit: TimeUnit,
    *,
    pedigree_lookup: Optional[Dict[Tuple[str, ...], float]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = _LOAD_PROGRESS_END,
    progress_end: float = _RT_PROGRESS_END,
) -> Tuple[List[DelCycleRow], str]:
    """
    Build analysis rows with RT from pedigree when available, else peak picking.

    Returns:
        (rows, rt_source) where rt_source is ``pedigree`` or ``peak_pick``.
    """
    pedigree_lookup = pedigree_lookup or {}
    rows: List[DelCycleRow] = []
    used_pedigree = 0
    used_pick = 0
    total = len(compounds)
    span = max(progress_end - progress_start, 0.0)

    for index, compound in enumerate(compounds, start=1):
        positions = positions_c_to_n(compound, config)
        if positions is None:
            continue
        rt = pedigree_lookup.get(positions)
        if rt is None:
            rt = _pick_rt_for_compound(compound, channel, settings, time_unit, config)
            if rt is None:
                continue
            used_pick += 1
        else:
            used_pedigree += 1
        rows.append(DelCycleRow(positions=positions, rt=float(rt)))

        if progress_callback is not None and (
            index % 500 == 0 or index == total
        ):
            sub = index / total if total else 1.0
            _report_fraction(
                progress_callback,
                progress_start + span * sub,
                (
                    f"Resolving retention times… {index:,} / {total:,} "
                    f"({len(rows):,} with RT)"
                ),
            )

    if used_pedigree and used_pick:
        source = "pedigree+peak_pick"
    elif used_pedigree:
        source = "pedigree"
    else:
        source = "peak_pick"
    return dedupe_rows_by_position(rows), source


def build_del_cycle_tree_data(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    channel: str,
    time_unit: TimeUnit,
    *,
    rt_threshold: float,
    pedigree_result: Optional[PedigreeAnalysisResult] = None,
    isoform_label: str = "All",
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """Analyze compounds and return nested tree structures for rendering."""
    if not config.pedigree_configured():
        raise ValueError("BB position columns must be configured for DEL-cycle tree analysis.")

    n_cycles = config.library_cycle_count
    null_token = str(config.null_token).strip()

    filtered = filter_compounds_by_variant(
        list(compounds),
        None if isoform_label.strip().lower() == "all" else [isoform_label],
    )

    pedigree_lookup: Dict[Tuple[str, ...], float] = {}
    if pedigree_result is not None:
        pedigree_lookup = build_pedigree_rt_lookup(pedigree_result.records, config)

    _report_fraction(
        progress_callback,
        _LOAD_PROGRESS_END,
        f"Preparing retention times for {len(filtered):,} compound(s)…",
    )
    rows, rt_source = build_del_cycle_rows(
        filtered,
        config,
        channel,
        settings,
        time_unit,
        pedigree_lookup=pedigree_lookup,
        progress_callback=progress_callback,
    )
    if not rows:
        raise ValueError(
            "No compounds with BB positions and retention times were found. "
            "Run pedigree analysis or ensure chromatograms are loaded."
        )

    _report_fraction(progress_callback, _RT_PROGRESS_END, "Verifying reaction sequences…")
    sorted_rows = sort_rows(rows, null_token)

    def verify_progress(processed: int, total: int, status: str) -> None:
        if total <= 0:
            return
        span = _ANALYZE_PROGRESS_END - _RT_PROGRESS_END
        _report_fraction(
            progress_callback,
            _RT_PROGRESS_END + span * (processed / total),
            status,
        )

    verified = verify_reaction_sequences(
        sorted_rows,
        null_token=null_token,
        rt_threshold=rt_threshold,
        progress_callback=verify_progress if progress_callback else None,
    )
    _report_fraction(progress_callback, _ANALYZE_PROGRESS_END, "Building tree structure…")
    tree = create_tree(sorted_rows)
    pruned = prune_tree(tree, verified)

    null_positions = tuple(null_token for _ in range(n_cycles))
    full_null_rt = next(
        (row.rt for row in sorted_rows if row.positions == null_positions),
        None,
    )

    position_tuples = [row.positions for row in sorted_rows]
    bb_index = build_bb_index_by_level(position_tuples, null_token)
    bb1_names = sorted(
        tree.keys(),
        key=lambda name: (name == null_token, name.lower()),
    )

    n_verified = sum(1 for info in verified.values() if info.success)
    _report_fraction(
        progress_callback,
        0.99,
        f"Tree ready — {n_verified:,} verified product(s).",
    )
    return DelCycleTreeData(
        library_cycle_count=n_cycles,
        null_token=null_token,
        rt_threshold=float(rt_threshold),
        tree=tree,
        pruned_tree=pruned,
        verified_sequences=verified,
        full_null_rt=full_null_rt,
        bb_index_by_level=bb_index,
        bb1_names=bb1_names,
        n_rows=len(sorted_rows),
        n_verified=n_verified,
        rt_source=rt_source,
    )


def build_del_cycle_tree_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    channel: str,
    time_unit: TimeUnit,
    *,
    rt_threshold: float,
    pedigree_result: Optional[PedigreeAnalysisResult] = None,
    isoform_label: str = "All",
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """Thread-safe: open the database in the current thread, then build the DEL tree."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        def load_progress(processed: int, total: int, status: str) -> None:
            sub = processed / total if total else 1.0
            _report_fraction(
                progress_callback,
                _LOAD_PROGRESS_END * sub,
                status,
            )

        compounds = load_all_compounds(
            store,
            config,
            index_database=store.is_index_database(),
            progress_callback=load_progress,
        )
        return build_del_cycle_tree_data(
            compounds,
            config,
            settings,
            channel,
            time_unit,
            rt_threshold=rt_threshold,
            pedigree_result=pedigree_result,
            isoform_label=isoform_label,
            progress_callback=progress_callback,
        )
    finally:
        store.close()
