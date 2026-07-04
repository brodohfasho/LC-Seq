# src/core/del_cycle_tree/service.py
"""Build DEL-cycle tree data from library compounds and pedigree results."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.data_store import DataStore
from src.core.del_cycle_tree.analyzer import dedupe_rows_by_position
from src.core.del_cycle_tree.builder import create_tree, flatten_del_tree_rts, prune_tree
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
    CompoundRtAssignment,
    DelCycleRow,
    DelCycleRtResolution,
    DelCycleTreeData,
    MetadataRtColumnInfo,
    VerifiedSequence,
)
from src.core.del_cycle_tree.positions import index_discovery_rows_from_compounds, positions_c_to_n
from src.core.lcseq_backend import find_peaks_for_settings, select_direct_pick_product_rt
from src.core.library_metrics import LibraryScanData
from src.core.lineage_service import (
    ProgressCallback,
    load_all_compound_metadata,
    load_all_compounds,
)
from src.core.pedigree_adapter import filter_compounds_by_variant
from src.core.pedigree_export import chosen_rt_for_record, positions_n_to_c_from_record
from src.core.rt_assignment_export import (
    build_verification_overrides_from_metadata,
    parse_null_rt_verified_metadata,
)
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
    trace_max = max(float(c) for c in counts) if counts else 0.0
    return select_direct_pick_product_rt(
        peaks,
        settings,
        trace_max_intensity=trace_max,
    )


def _rt_from_metadata(compound: Compound, config: SpreadsheetConfig) -> Optional[float]:
    """Read precomputed cyclized RT from spreadsheet metadata when configured."""
    candidates = [
        name
        for name in config.selected_metadata_columns
        if "cyclized" in str(name).lower() and "rt" in str(name).lower()
    ]
    for column in candidates:
        rt = rt_from_metadata_column(compound, column)
        if rt is not None:
            return rt
    return None


_MISSING_RT_STRINGS = frozenset(
    {"", "na", "n/a", "nan", "-", "--", "none", "null", ".", "#n/a", "#na"}
)


def _is_valid_metadata_rt(value: float) -> bool:
    return math.isfinite(value)


def rt_from_metadata_column(compound: Compound, column_name: str) -> Optional[float]:
    """Parse a numeric RT from one named metadata column.

    Empty, missing, NaN, and non-numeric cells return ``None`` so callers can skip
    the row without failing the whole split-tree build.
    """
    column = str(column_name).strip()
    if not column:
        return None
    raw = compound.metadata.get(column)
    if raw is None:
        return None
    if isinstance(raw, float):
        return float(raw) if _is_valid_metadata_rt(raw) else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.lower() in _MISSING_RT_STRINGS:
            return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return None
    return parsed if _is_valid_metadata_rt(parsed) else None


def registered_metadata_column_names(config: SpreadsheetConfig) -> List[str]:
    """Return configured metadata columns in spreadsheet order (no name heuristics)."""
    exclude = {
        config.compound_id_column,
        config.chromatographic_data_column,
    }
    exclude.update(config.active_bb_position_columns())
    variant_col = config.compound_variant_column
    if variant_col:
        exclude.add(str(variant_col).strip())

    columns: List[str] = []
    for name in config.selected_metadata_columns or []:
        column = str(name).strip()
        if column and column not in exclude and column not in columns:
            columns.append(column)
    return columns


def validate_registered_metadata_columns(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
) -> List[MetadataRtColumnInfo]:
    """
    Count numeric values for each registered metadata column in config order.

    Does not infer or rank columns by RT-like names.
    """
    columns = registered_metadata_column_names(config)
    if not columns:
        return []

    numeric_counts = {column: 0 for column in columns}
    bb_counts = {column: 0 for column in columns}
    verified_counts = {column: 0 for column in columns}
    verified_bb_counts = {column: 0 for column in columns}
    n_scanned = len(compounds)

    for compound in compounds:
        has_bb = positions_c_to_n(compound, config) is not None
        for column in columns:
            if rt_from_metadata_column(compound, column) is not None:
                numeric_counts[column] += 1
                if has_bb:
                    bb_counts[column] += 1
            if parse_null_rt_verified_metadata(compound.metadata.get(column)) is not None:
                verified_counts[column] += 1
                if has_bb:
                    verified_bb_counts[column] += 1

    return [
        MetadataRtColumnInfo(
            column_name=column,
            n_numeric_values=numeric_counts[column],
            n_compounds_scanned=n_scanned,
            n_with_bb_positions=bb_counts[column],
            n_verified_values=verified_counts[column],
            n_verified_with_bb_positions=verified_bb_counts[column],
        )
        for column in columns
    ]


def count_metadata_rt_values(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    column_name: str,
) -> Tuple[int, int]:
    """
    Count compounds with BB positions and compounds with RT in ``column_name``.

    Returns:
        (n_with_bb_positions, n_with_rt_in_column)
    """
    with_bb = 0
    with_rt = 0
    for compound in compounds:
        if positions_c_to_n(compound, config) is None:
            continue
        with_bb += 1
        if rt_from_metadata_column(compound, column_name) is not None:
            with_rt += 1
    return with_bb, with_rt


def build_del_cycle_rows_from_metadata_column(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    rt_column: str,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = _LOAD_PROGRESS_END,
    progress_end: float = _RT_PROGRESS_END,
) -> Tuple[List[DelCycleRow], DelCycleRtResolution]:
    """Build DEL rows using only the selected spreadsheet RT column (no peak pick)."""
    column = str(rt_column).strip()
    if not column:
        raise ValueError("Select a spreadsheet RT column before generating the split-tree.")

    rows: List[DelCycleRow] = []
    total = len(compounds)
    span = max(progress_end - progress_start, 0.0)
    n_skipped_no_bb = 0
    n_skipped_empty_rt = 0

    for index, compound in enumerate(compounds, start=1):
        positions = positions_c_to_n(compound, config)
        if positions is None:
            n_skipped_no_bb += 1
            continue
        rt = rt_from_metadata_column(compound, column)
        if rt is None:
            n_skipped_empty_rt += 1
            continue
        rows.append(DelCycleRow(positions=positions, rt=float(rt)))

        if progress_callback is not None and (index % 500 == 0 or index == total):
            sub = index / total if total else 1.0
            _report_fraction(
                progress_callback,
                progress_start + span * sub,
                (
                    f"Reading metadata RTs… {index:,} / {total:,} "
                    f"({len(rows):,} with RT, {n_skipped_empty_rt:,} empty skipped)"
                ),
            )

    if not rows:
        raise ValueError(
            f"No compounds with numeric RT values were found in column “{column}”. "
            f"Scanned {total:,} compound(s); skipped {n_skipped_empty_rt:,} with empty "
            f"or non-numeric RT and {n_skipped_no_bb:,} without BB positions. "
            "Rows with empty RT cells are ignored — ensure at least some compounds "
            "have assigned RTs, or choose a different column."
        )

    deduped = dedupe_rows_by_position(rows)
    return deduped, DelCycleRtResolution(
        rt_source="metadata",
        peak_picking_algorithm="",
        n_rt_from_metadata=len(deduped),
    )


def build_del_cycle_tree_from_metadata_column(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    rt_column: str,
    *,
    verified_column: str,
    rt_threshold: float,
    isoform_label: str = "All",
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """
    Build a split-tree from spreadsheet RT metadata only.

    Skips peak picking / pedigree RT assignment but still runs notebook null
    verification (``verify_reaction_sequences_notebook``). Pass/fail coloring
    for full products uses ``verified_column`` when present; truncation
    intermediates must have RT values in ``rt_column`` for verification to work.
    """
    if not config.pedigree_configured():
        raise ValueError("BB position columns must be configured for split-tree analysis.")

    filtered = filter_compounds_by_variant(
        list(compounds),
        None if isoform_label.strip().lower() == "all" else [isoform_label],
    )
    index_discovery_rows = index_discovery_rows_from_compounds(filtered, config)
    _report_fraction(
        progress_callback,
        _LOAD_PROGRESS_END,
        f"Reading RT column “{rt_column}” for {len(filtered):,} compound(s)…",
    )
    rows, resolution = build_del_cycle_rows_from_metadata_column(
        filtered,
        config,
        rt_column,
        progress_callback=progress_callback,
    )
    verification_overrides = build_verification_overrides_from_metadata(
        filtered,
        config,
        column=verified_column,
    )
    return _finalize_del_cycle_tree(
        rows,
        config,
        rt_threshold=rt_threshold,
        rt_source=resolution.rt_source,
        rt_resolution=resolution,
        index_discovery_rows=index_discovery_rows,
        verification_success_overrides=verification_overrides or None,
        progress_callback=progress_callback,
    )


def build_del_cycle_tree_from_metadata_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    rt_column: str,
    *,
    verified_column: str,
    rt_threshold: float,
    isoform_label: str = "All",
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """Thread-safe metadata-only split-tree build."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        def load_progress(processed: int, total: int, status: str) -> None:
            sub = processed / total if total else 1.0
            _report_fraction(
                progress_callback,
                _LOAD_PROGRESS_END * sub,
                status,
            )

        compounds = load_all_compound_metadata(
            store,
            metadata_columns=config.selected_metadata_columns,
            progress_callback=load_progress,
        )
        return build_del_cycle_tree_from_metadata_column(
            compounds,
            config,
            rt_column,
            verified_column=verified_column,
            rt_threshold=rt_threshold,
            isoform_label=isoform_label,
            progress_callback=progress_callback,
        )
    finally:
        store.close()


def build_del_cycle_rows(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    channel: str,
    settings: AnalysisSettings,
    time_unit: TimeUnit,
    *,
    pedigree_lookup: Optional[Dict[Tuple[str, ...], float]] = None,
    pedigree_lookup_canonical: Optional[Dict[str, str]] = None,
    use_metadata_rt: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    progress_start: float = _LOAD_PROGRESS_END,
    progress_end: float = _RT_PROGRESS_END,
) -> Tuple[List[DelCycleRow], DelCycleRtResolution]:
    """
    Build analysis rows with RT from metadata, pedigree, or peak picking.

    When ``use_metadata_rt`` is False (RT assignment runs), spreadsheet metadata
    is ignored and RTs come only from pedigree lookup and/or peak picking.
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
        rt: Optional[float] = None
        if use_metadata_rt:
            rt = _rt_from_metadata(compound, config)
            if rt is not None:
                used_metadata += 1
        if rt is None:
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


def resolve_compound_rt_assignments(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    channel: str,
    settings: AnalysisSettings,
    time_unit: TimeUnit,
    *,
    pedigree_result: Optional[PedigreeAnalysisResult] = None,
    isoform_label: str = "All",
    use_metadata_rt: bool = True,
) -> List[CompoundRtAssignment]:
    """
    Resolve assigned RT per compound storage id for spreadsheet export.

    When ``use_metadata_rt`` is False, only pedigree and peak-pick sources are used.
    """
    filtered = filter_compounds_by_variant(
        list(compounds),
        None if isoform_label.strip().lower() == "all" else [isoform_label],
    )
    null_token = normalize_bb_name(config.null_token)
    index_discovery_rows = index_discovery_rows_from_compounds(filtered, config)
    discovery_canonical = build_bb_name_canonical_map(index_discovery_rows, null_token)

    pedigree_lookup: Dict[Tuple[str, ...], float] = {}
    if pedigree_result is not None:
        pedigree_lookup = build_pedigree_rt_lookup(pedigree_result.records, config)
        if pedigree_lookup:
            pedigree_lookup = canonicalize_lookup_keys(
                pedigree_lookup,
                null_token=null_token,
                canonical_by_lower=discovery_canonical,
            )

    assignments: List[CompoundRtAssignment] = []
    for compound in filtered:
        positions = positions_c_to_n(compound, config)
        if positions is None:
            continue
        rt: Optional[float] = None
        source = "metadata"
        if use_metadata_rt:
            rt = _rt_from_metadata(compound, config)
        if rt is None:
            source = "peak_pick"
            lookup_key = positions
            if pedigree_lookup and discovery_canonical:
                lookup_key = canonicalize_positions(
                    tuple(normalize_bb_name(bb) for bb in positions),
                    null_token=null_token,
                    canonical_by_lower=discovery_canonical,
                )
            rt = pedigree_lookup.get(lookup_key)
            if rt is None and lookup_key is not positions:
                rt = pedigree_lookup.get(positions)
            if rt is None:
                rt = _pick_rt_for_compound(compound, channel, settings, time_unit, config)
                if rt is None:
                    continue
                source = "peak_pick"
            else:
                source = "pedigree"
        assignments.append(
            CompoundRtAssignment(
                compound_id=compound.compound_id,
                assigned_rt=float(rt),
                rt_source=source,
            )
        )
    return assignments


def build_assignments_from_del_cycle_tree(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    del_data: DelCycleTreeData,
    *,
    pedigree_result: Optional[PedigreeAnalysisResult] = None,
) -> List[CompoundRtAssignment]:
    """
    Build per-compound RT export rows from an existing session split-tree.

    Reuses RTs and null verification from the prior RT assignment run instead of
    re-running peak picking across the full library.
    """
    null_token = normalize_bb_name(config.null_token)
    n_cycles = config.library_cycle_count
    position_rts = flatten_del_tree_rts(del_data.tree)

    index_discovery_rows = index_discovery_rows_from_compounds(compounds, config)
    discovery_canonical = build_bb_name_canonical_map(index_discovery_rows, null_token)
    row_canonical = build_bb_name_canonical_map(
        [DelCycleRow(positions=pos, rt=rt) for pos, rt in position_rts.items()],
        null_token,
    )
    canonical_by_lower = merge_bb_name_canonical_maps(discovery_canonical, row_canonical)

    pedigree_lookup: Dict[Tuple[str, ...], float] = {}
    if pedigree_result is not None:
        pedigree_lookup = build_pedigree_rt_lookup(pedigree_result.records, config)
        if pedigree_lookup:
            pedigree_lookup = canonicalize_lookup_keys(
                pedigree_lookup,
                null_token=null_token,
                canonical_by_lower=discovery_canonical,
            )

    assignments: List[CompoundRtAssignment] = []
    for compound in compounds:
        positions = positions_c_to_n(compound, config)
        if positions is None:
            continue
        canonical = canonicalize_positions(
            tuple(normalize_bb_name(bb) for bb in positions),
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
        rt = position_rts.get(canonical)
        if rt is None and canonical != positions:
            rt = position_rts.get(positions)
        if rt is None:
            continue

        source = del_data.rt_source or "peak_pick"
        ped_rt = pedigree_lookup.get(canonical)
        if ped_rt is None and canonical != positions:
            ped_rt = pedigree_lookup.get(positions)
        if ped_rt is not None and abs(float(ped_rt) - float(rt)) <= 1e-6:
            source = "pedigree"
        elif source not in ("pedigree", "peak_pick", "metadata"):
            source = "peak_pick"

        null_verified: Optional[bool] = None
        if len(positions) == n_cycles and not any(
            normalize_bb_name(bb) == null_token for bb in positions
        ):
            info = del_data.verified_sequences.get(canonical)
            if info is None and canonical != positions:
                info = del_data.verified_sequences.get(positions)
            if info is not None:
                null_verified = bool(info.success)

        assignments.append(
            CompoundRtAssignment(
                compound_id=compound.compound_id,
                assigned_rt=float(rt),
                rt_source=source,
                null_rt_verified=null_verified,
            )
        )
    return assignments


def _load_compounds_for_rt_assignment(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    scan: Optional[LibraryScanData] = None,
    isoform_label: str = "All",
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Compound]:
    """
    Load compounds for RT assignment.

    When a cached library scan is available, chromatograms are taken from the scan
    and only metadata is read from SQLite. Otherwise compounds are loaded fully
    from the database (including on-demand chromatogram parsing for index DBs).
    """
    from src.core.pedigree_adapter import compounds_with_scan_chromatograms

    variants = (
        None if isoform_label.strip().lower() == "all" else [isoform_label.strip()]
    )
    if scan is not None:
        def load_progress(processed: int, total: int, status: str) -> None:
            sub = processed / total if total else 1.0
            _report_fraction(
                progress_callback,
                _LOAD_PROGRESS_END * sub * 0.5,
                status,
            )

        metadata = load_all_compound_metadata(
            store,
            metadata_columns=config.selected_metadata_columns,
            progress_callback=load_progress,
        )
        _report_fraction(
            progress_callback,
            _LOAD_PROGRESS_END * 0.5,
            "Attaching chromatograms from library scan…",
        )
        return compounds_with_scan_chromatograms(
            scan,
            metadata,
            selected_variants=variants,
        )

    def load_progress(processed: int, total: int, status: str) -> None:
        sub = processed / total if total else 1.0
        _report_fraction(
            progress_callback,
            _LOAD_PROGRESS_END * sub,
            status,
        )

    return load_all_compounds(
        store,
        config,
        index_database=store.is_index_database(),
        progress_callback=load_progress,
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
    verification_success_overrides: Optional[Dict[Tuple[str, ...], bool]] = None,
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
    if verification_success_overrides:
        for positions, success in verification_success_overrides.items():
            existing = verified.get(positions)
            rt_value = existing.rt if existing is not None else next(
                (row.rt for row in sorted_rows if row.positions == positions),
                0.0,
            )
            verified[positions] = VerifiedSequence(
                positions=positions,
                rt=float(rt_value),
                success=bool(success),
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
    use_metadata_rt: bool = True,
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
        use_metadata_rt=use_metadata_rt,
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
    scan: Optional[LibraryScanData] = None,
    use_metadata_rt: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> DelCycleTreeData:
    """Thread-safe: open the database in the current thread, then build the DEL tree."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        compounds = _load_compounds_for_rt_assignment(
            store,
            config,
            scan=scan,
            isoform_label=isoform_label,
            progress_callback=progress_callback,
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
            use_metadata_rt=use_metadata_rt,
            progress_callback=progress_callback,
        )
    finally:
        store.close()


def resolve_compound_rt_assignments_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    channel: str,
    time_unit: TimeUnit,
    *,
    pedigree_result: Optional[PedigreeAnalysisResult] = None,
    isoform_label: str = "All",
    scan: Optional[LibraryScanData] = None,
    use_metadata_rt: bool = True,
) -> List[CompoundRtAssignment]:
    """Open the database in the current thread and resolve per-compound RT assignments."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        compounds = _load_compounds_for_rt_assignment(
            store,
            config,
            scan=scan,
            isoform_label=isoform_label,
        )
        return resolve_compound_rt_assignments(
            compounds,
            config,
            channel,
            settings,
            time_unit,
            pedigree_result=pedigree_result,
            isoform_label=isoform_label,
            use_metadata_rt=use_metadata_rt,
        )
    finally:
        store.close()
