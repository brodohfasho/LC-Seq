# src/core/del_cycle_tree/service.py
"""Build DEL-cycle tree data from library compounds and pedigree results."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.data_store import DataStore
from src.core.del_cycle_tree.analyzer import dedupe_rows_by_position
from src.core.del_cycle_tree.builder import create_tree, prune_tree
from src.core.del_cycle_tree.bb_index_scheme import (
    build_bb_name_canonical_map,
    build_global_bb_index_map,
    canonicalize_lookup_keys,
    canonicalize_positions,
    merge_bb_name_canonical_maps,
    normalize_bb_name,
)
from src.core.del_cycle_tree.notebook_analyzer import (
    create_full_compound_dict,
    create_truncated_compound_dict,
    sort_rows_notebook,
    verify_reaction_sequences_notebook,
)
from src.core.del_cycle_tree.models import (
    DelCycleRow,
    DelCycleRtResolution,
    DelCycleTreeData,
    VerifiedSequence,
)
from src.core.del_cycle_tree.positions import index_discovery_rows_from_compounds, positions_c_to_n
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


def build_pedigree_passed_lookup(
    records: Sequence[PedigreeNodeRecord],
    config: SpreadsheetConfig,
) -> Dict[Tuple[str, ...], bool]:
    """Map full-product C→N tuples to pedigree pass/fail for DEL-tree coloring."""
    null_token = str(config.null_token).strip()
    n_cycles = config.library_cycle_count
    lookup: Dict[Tuple[str, ...], bool] = {}
    for record in records:
        if record.tier != n_cycles or record.kind != "compound":
            continue
        n_to_c = positions_n_to_c_from_record(
            record,
            library_cycle_count=n_cycles,
            null_token=null_token,
        )
        c_to_n = tuple(reversed(n_to_c))
        if any(bb == null_token for bb in c_to_n):
            continue
        lookup[c_to_n] = bool(record.passed)
    return lookup


def build_pedigree_rt_lookup(
    records: Sequence[PedigreeNodeRecord],
    config: SpreadsheetConfig,
) -> Dict[Tuple[str, ...], float]:
    """
    Map C→N position tuples to pedigree-chosen RTs for DEL-cycle tree analysis.

    Includes class and compound nodes (passed and failed) so verification can
    mark failed branches and the renderer can show pruned/coral coloring.
    """
    lookup: Dict[Tuple[str, ...], float] = {}
    for record in records:
        if record.tier == 0:
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
        existing = lookup.get(c_to_n)
        if existing is None or (record.passed and not _rt_matches(existing, chosen)):
            lookup[c_to_n] = float(chosen)
    return lookup


def _rt_matches(left: float, right: float, *, epsilon: float = 1e-9) -> bool:
    return abs(left - right) <= epsilon


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


def _rt_from_metadata(compound: Compound, config: SpreadsheetConfig) -> Optional[float]:
    """Read precomputed cyclized RT from spreadsheet metadata when configured."""
    candidates = [
        name
        for name in config.selected_metadata_columns
        if "cyclized" in str(name).lower() and "rt" in str(name).lower()
    ]
    for column in candidates:
        raw = compound.metadata.get(column)
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def build_del_cycle_rows(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    channel: str,
    settings: AnalysisSettings,
    time_unit: TimeUnit,
    *,
    pedigree_lookup: Optional[Dict[Tuple[str, ...], float]] = None,
    pedigree_lookup_canonical: Optional[Dict[str, str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = _LOAD_PROGRESS_END,
    progress_end: float = _RT_PROGRESS_END,
) -> Tuple[List[DelCycleRow], DelCycleRtResolution]:
    """
    Build analysis rows with RT from metadata, pedigree, or peak picking.

    Priority: spreadsheet cyclized RT metadata → pedigree chosen RT → peak pick.
    ``pedigree+peak_pick`` means some rows used pedigree RTs (class/compound nodes)
    and others used the configured peak picker (typically null-truncation rows).
    """
    pedigree_lookup = pedigree_lookup or {}
    null_token = normalize_bb_name(config.null_token)
    rows: List[DelCycleRow] = []
    used_pedigree = 0
    used_pick = 0
    used_metadata = 0
    total = len(compounds)
    span = max(progress_end - progress_start, 0.0)
    picker = settings.peak_picking_algorithm

    for index, compound in enumerate(compounds, start=1):
        positions = positions_c_to_n(compound, config)
        if positions is None:
            continue
        rt = _rt_from_metadata(compound, config)
        if rt is not None:
            used_metadata += 1
        else:
            lookup_key = positions
            if pedigree_lookup and pedigree_lookup_canonical:
                lookup_key = canonicalize_positions(
                    tuple(normalize_bb_name(bb) for bb in positions),
                    null_token=null_token,
                    canonical_by_lower=pedigree_lookup_canonical,
                )
            rt = pedigree_lookup.get(lookup_key)
            if rt is None and lookup_key is not positions:
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

    if used_metadata and (used_pedigree or used_pick):
        source = "cyclized_rt+mixed"
    elif used_metadata:
        source = "cyclized_rt"
    elif used_pedigree and used_pick:
        source = "pedigree+peak_pick"
    elif used_pedigree:
        source = "pedigree"
    else:
        source = "peak_pick"
    return dedupe_rows_by_position(rows), DelCycleRtResolution(
        rt_source=source,
        peak_picking_algorithm=picker,
        n_rt_from_pedigree=used_pedigree,
        n_rt_from_peak_pick=used_pick,
        n_rt_from_metadata=used_metadata,
    )


def _finalize_del_cycle_tree(
    rows: Sequence[DelCycleRow],
    config: SpreadsheetConfig,
    *,
    rt_threshold: float,
    rt_source: str,
    rt_resolution: Optional[DelCycleRtResolution] = None,
    pedigree_passed_lookup: Optional[Dict[Tuple[str, ...], bool]] = None,
    index_discovery_rows: Optional[Sequence[DelCycleRow]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """Sort, verify (notebook logic), and nest rows into ``DelCycleTreeData``."""
    null_token = normalize_bb_name(config.null_token)
    n_cycles = config.library_cycle_count

    if not rows:
        raise ValueError(
            "No compounds with BB positions and retention times were found. "
            "Run pedigree analysis or ensure chromatograms are loaded."
        )

    discovery_rows = list(index_discovery_rows or rows)
    discovery_canonical = build_bb_name_canonical_map(discovery_rows, null_token)
    row_canonical = build_bb_name_canonical_map(rows, null_token)
    canonical_by_lower = merge_bb_name_canonical_maps(discovery_canonical, row_canonical)
    bb_index_global = build_global_bb_index_map(
        discovery_rows,
        null_token,
        override_map=config.bb_index_override(),
    )
    normalized_rows = [
        DelCycleRow(
            canonicalize_positions(
                tuple(normalize_bb_name(bb) for bb in row.positions),
                null_token=null_token,
                canonical_by_lower=canonical_by_lower,
            ),
            row.rt,
        )
        for row in rows
    ]
    sorted_rows = sort_rows_notebook(normalized_rows, bb_index_global, null_token)

    def verify_progress(processed: int, total: int, status: str) -> None:
        if total <= 0:
            return
        span = _ANALYZE_PROGRESS_END - _RT_PROGRESS_END
        _report_fraction(
            progress_callback,
            _RT_PROGRESS_END + span * (processed / total),
            status,
        )

    _report_fraction(progress_callback, _RT_PROGRESS_END, "Building truncation RT library…")
    truncated_dict = create_truncated_compound_dict(sorted_rows, null_token, n_cycles)
    full_compound_dict = create_full_compound_dict(sorted_rows, truncated_dict)
    verified = verify_reaction_sequences_notebook(
        full_compound_dict,
        null_token=null_token,
        n_cycles=n_cycles,
        rt_threshold=rt_threshold,
        progress_callback=verify_progress if progress_callback else None,
    )
    _report_fraction(progress_callback, _ANALYZE_PROGRESS_END, "Building tree structure…")
    tree = create_tree(sorted_rows)
    pruned = prune_tree(tree, verified)

    pedigree_passed_lookup = pedigree_passed_lookup or {}
    if pedigree_passed_lookup:
        pedigree_passed_lookup = canonicalize_lookup_keys(
            pedigree_passed_lookup,
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
    pedigree_verified = {
        positions: VerifiedSequence(
            positions=positions,
            rt=info.rt,
            success=pedigree_passed_lookup.get(positions, False),
        )
        for positions, info in verified.items()
        if len(positions) == n_cycles and not any(bb == null_token for bb in positions)
    }
    pedigree_pruned = prune_tree(tree, pedigree_verified) if pedigree_passed_lookup else {}

    null_positions = tuple(null_token for _ in range(n_cycles))
    full_null_rt = next(
        (row.rt for row in sorted_rows if row.positions == null_positions),
        None,
    )

    bb1_names = sorted(
        tree.keys(),
        key=lambda name: (name == null_token, name.lower()),
    )

    n_verified = sum(1 for info in verified.values() if info.success)
    n_pedigree_passed = sum(1 for passed in pedigree_passed_lookup.values() if passed)
    n_agree = 0
    for positions, info in verified.items():
        if len(positions) != n_cycles or any(bb == null_token for bb in positions):
            continue
        ped_passed = pedigree_passed_lookup.get(positions)
        if ped_passed is None:
            continue
        if bool(info.success) == bool(ped_passed):
            n_agree += 1
    resolution = rt_resolution or DelCycleRtResolution(
        rt_source=rt_source,
        peak_picking_algorithm="",
    )
    _report_fraction(
        progress_callback,
        0.99,
        f"Tree ready — {n_verified:,} RT-verified product(s).",
    )
    return DelCycleTreeData(
        library_cycle_count=n_cycles,
        null_token=null_token,
        rt_threshold=float(rt_threshold),
        tree=tree,
        pruned_tree=pruned,
        verified_sequences=verified,
        full_null_rt=full_null_rt,
        bb_index_global=bb_index_global,
        truncation_library=full_compound_dict,
        bb1_names=bb1_names,
        n_rows=len(sorted_rows),
        n_verified=n_verified,
        rt_source=resolution.rt_source,
        peak_picking_algorithm=resolution.peak_picking_algorithm,
        n_rt_from_pedigree=resolution.n_rt_from_pedigree,
        n_rt_from_peak_pick=resolution.n_rt_from_peak_pick,
        n_rt_from_metadata=resolution.n_rt_from_metadata,
        n_rt_verified_pedigree_agree=n_agree,
        pedigree_passed_by_product=dict(pedigree_passed_lookup),
        pedigree_pruned_tree=pedigree_pruned,
        n_pedigree_passed=n_pedigree_passed,
    )


def build_del_cycle_tree_from_pedigree(
    pedigree_result: PedigreeAnalysisResult,
    config: SpreadsheetConfig,
    *,
    rt_threshold: float,
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """
    Build a DEL-cycle tree from pedigree RT rows only.

    Prefer ``build_del_cycle_tree_data`` with full library compounds when null
  truncation rows are required for notebook-faithful verification.
    """
    if not config.pedigree_configured():
        raise ValueError("BB position columns must be configured for DEL-cycle tree analysis.")

    _report_fraction(
        progress_callback,
        _LOAD_PROGRESS_END,
        "Building DEL-cycle tree from pedigree results…",
    )
    lookup = build_pedigree_rt_lookup(pedigree_result.records, config)
    passed_lookup = build_pedigree_passed_lookup(pedigree_result.records, config)
    rows = [
        DelCycleRow(positions=positions, rt=rt)
        for positions, rt in lookup.items()
    ]
    resolution = DelCycleRtResolution(
        rt_source="pedigree",
        peak_picking_algorithm=pedigree_result.settings.peak_picking_algorithm,
        n_rt_from_pedigree=len(rows),
    )
    _report_fraction(
        progress_callback,
        _RT_PROGRESS_END,
        f"Prepared {len(rows):,} pedigree RT row(s)…",
    )
    return _finalize_del_cycle_tree(
        rows,
        config,
        rt_threshold=rt_threshold,
        rt_source=resolution.rt_source,
        rt_resolution=resolution,
        pedigree_passed_lookup=passed_lookup,
        progress_callback=progress_callback,
    )


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

    null_token = normalize_bb_name(config.null_token)
    index_discovery_rows = index_discovery_rows_from_compounds(filtered, config)
    discovery_canonical = build_bb_name_canonical_map(index_discovery_rows, null_token)

    pedigree_lookup: Dict[Tuple[str, ...], float] = {}
    pedigree_passed_lookup: Dict[Tuple[str, ...], bool] = {}
    if pedigree_result is not None:
        pedigree_lookup = build_pedigree_rt_lookup(pedigree_result.records, config)
        pedigree_passed_lookup = build_pedigree_passed_lookup(
            pedigree_result.records, config
        )
        if pedigree_lookup:
            pedigree_lookup = canonicalize_lookup_keys(
                pedigree_lookup,
                null_token=null_token,
                canonical_by_lower=discovery_canonical,
            )
        if pedigree_passed_lookup:
            pedigree_passed_lookup = canonicalize_lookup_keys(
                pedigree_passed_lookup,
                null_token=null_token,
                canonical_by_lower=discovery_canonical,
            )

    _report_fraction(
        progress_callback,
        _LOAD_PROGRESS_END,
        f"Preparing retention times for {len(filtered):,} compound(s)…",
    )
    rows, resolution = build_del_cycle_rows(
        filtered,
        config,
        channel,
        settings,
        time_unit,
        pedigree_lookup=pedigree_lookup,
        pedigree_lookup_canonical=discovery_canonical if pedigree_lookup else None,
        progress_callback=progress_callback,
    )
    if not rows:
        raise ValueError(
            "No compounds with BB positions and retention times were found. "
            "Run pedigree analysis or ensure chromatograms are loaded."
        )

    return _finalize_del_cycle_tree(
        rows,
        config,
        rt_threshold=rt_threshold,
        rt_source=resolution.rt_source,
        rt_resolution=resolution,
        pedigree_passed_lookup=pedigree_passed_lookup,
        index_discovery_rows=index_discovery_rows,
        progress_callback=progress_callback,
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
