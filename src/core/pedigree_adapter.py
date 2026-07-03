# src/core/pedigree_adapter.py
"""
Map database compounds to LC-Seq pedigree kernel inputs.

BB columns in the spreadsheet are in coupling order (C→N): BB1 = C-terminus,
BBn = N-terminus. The Rust kernel expects positional tuples in N→C order, so we
reverse the active BB column values when building keys.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.core.library_metrics import LibraryScanData, ScannedEntry
from src.core.time_display import convert_time_series
from src.models.analysis_settings import TimeUnit
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig

ChromatogramKey = Tuple[str, ...]
Chromatogram = Tuple[np.ndarray, np.ndarray]


def truncate_positions_from_metadata(
    compound: Compound,
    config: SpreadsheetConfig,
) -> Optional[ChromatogramKey]:
    """
    Read BB1..BBn from compound metadata and return N→C position tuple.

    Returns None if pedigree is not configured or required BB values are missing.
    """
    if not config.pedigree_configured():
        return None
    cols = config.bb_position_columns[: config.library_cycle_count]
    values_c_to_n: List[str] = []
    for col in cols:
        col = str(col).strip()
        if not col:
            return None
        raw = compound.metadata.get(col)
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            return None
        values_c_to_n.append(str(raw).strip())
    if len(values_c_to_n) != config.library_cycle_count:
        return None
    return tuple(reversed(values_c_to_n))


def class_key_from_positions(
    positions: Sequence[str],
    null_token: str,
) -> List[str]:
    """Non-null BB names in N→C order (padding-invariant class key)."""
    return [p for p in positions if p != null_token]


def filter_compounds_by_variant(
    compounds: Sequence[Compound],
    selected_variants: Optional[List[str]],
) -> List[Compound]:
    """Filter to isoform labels; None or ['all'] keeps every compound."""
    if not selected_variants or "all" in selected_variants:
        return list(compounds)
    want = {str(v).strip() for v in selected_variants}
    return [
        c
        for c in compounds
        if str(c.variant_label or "").strip() in want
    ]


def infer_bbs_per_position(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
) -> List[List[str]]:
    """Union of observed BB names at each N→C position index."""
    n = config.library_cycle_count
    sets: List[set[str]] = [set() for _ in range(n)]
    null = config.null_token
    for compound in compounds:
        pos = truncate_positions_from_metadata(compound, config)
        if pos is None or len(pos) != n:
            continue
        for i, bb in enumerate(pos):
            if bb != null:
                sets[i].add(bb)
    return [sorted(s) for s in sets]


def members_of_class(
    class_bbs: Sequence[str],
    chroms: Dict[ChromatogramKey, Chromatogram],
    null_token: str,
) -> List[Chromatogram]:
    """Chromatograms whose non-null N→C subsequence equals ``class_bbs``."""
    target = list(class_bbs)
    return [
        chrom
        for positions, chrom in chroms.items()
        if [p for p in positions if p != null_token] == target
    ]


def build_chromatogram_map(
    compounds: Sequence[Compound],
    channel: str,
    config: SpreadsheetConfig,
    *,
    time_unit: TimeUnit = "seconds",
) -> Dict[ChromatogramKey, Chromatogram]:
    """Build kernel chromatogram dict keyed by N→C position tuple."""
    stored_unit: TimeUnit = (
        "minutes" if config.analysis_time_unit == "minutes" else "seconds"
    )
    out: Dict[ChromatogramKey, Chromatogram] = {}
    for compound in compounds:
        key = truncate_positions_from_metadata(compound, config)
        if key is None:
            continue
        try:
            times, counts = compound.get_time_series(channel)
        except ValueError:
            continue
        if not times:
            continue
        if stored_unit != time_unit:
            times = convert_time_series(times, stored_unit, time_unit)
        rt = np.asarray(times, dtype=np.float64)
        intensity = np.asarray(counts, dtype=np.float64)
        out[key] = (rt, intensity)
    return out


def infer_bbs_per_position_from_map(
    chromatogram_map: Dict[ChromatogramKey, Chromatogram],
    config: SpreadsheetConfig,
) -> List[List[str]]:
    """Union of observed BB names at each N→C position from chromatogram keys."""
    n = config.library_cycle_count
    sets: List[set[str]] = [set() for _ in range(n)]
    null = config.null_token
    for positions in chromatogram_map:
        if len(positions) != n:
            continue
        for index, bb in enumerate(positions):
            if bb != null:
                sets[index].add(bb)
    return [sorted(s) for s in sets]


def compound_from_scan_entry(
    entry: ScannedEntry,
    metadata_stub: Compound,
) -> Compound:
    """Rebuild a ``Compound`` with chromatogram points taken from a scan entry."""
    channel_names = list(entry.counts_by_channel.keys())
    data_points = [
        ChromatographicDataPoint(
            time=float(entry.times[index]),
            counts={
                name: float(entry.counts_by_channel[name][index])
                for name in channel_names
            },
        )
        for index in range(len(entry.times))
    ]
    return Compound(
        compound_id=metadata_stub.compound_id,
        primary_compound_id=metadata_stub.primary_compound_id,
        variant_label=metadata_stub.variant_label,
        metadata=metadata_stub.metadata,
        data_points=data_points,
    )


def build_chromatogram_map_from_scan(
    scan: LibraryScanData,
    metadata_by_id: Dict[str, Compound],
    channel: str,
    config: SpreadsheetConfig,
    *,
    time_unit: TimeUnit = "seconds",
    selected_variants: Optional[List[str]] = None,
) -> Tuple[Dict[ChromatogramKey, Chromatogram], List[Compound]]:
    """
    Build pedigree chromatogram inputs from a library scan plus metadata stubs.

    Returns the chromatogram map and metadata-only compounds included after
    variant filtering (for prominence and reporting counts).
    """
    stored_unit: TimeUnit = (
        "minutes" if config.analysis_time_unit == "minutes" else "seconds"
    )
    filtered_stubs = filter_compounds_by_variant(
        list(metadata_by_id.values()),
        selected_variants,
    )
    allowed_ids = {str(compound.compound_id) for compound in filtered_stubs}
    stub_by_id = {str(compound.compound_id): compound for compound in filtered_stubs}

    out: Dict[ChromatogramKey, Chromatogram] = {}
    included_stubs: List[Compound] = []
    seen_ids: set[str] = set()

    for entry in scan.entries:
        compound_id = str(entry.compound_id)
        if compound_id not in allowed_ids:
            continue
        stub = stub_by_id.get(compound_id)
        if stub is None:
            continue
        key = truncate_positions_from_metadata(stub, config)
        if key is None:
            continue
        values = entry.counts_by_channel.get(channel)
        if not values or not entry.times:
            continue
        times = [float(value) for value in entry.times]
        counts = [float(value) for value in values]
        if stored_unit != time_unit:
            times = convert_time_series(times, stored_unit, time_unit)
        out[key] = (
            np.asarray(times, dtype=np.float64),
            np.asarray(counts, dtype=np.float64),
        )
        if compound_id not in seen_ids:
            included_stubs.append(stub)
            seen_ids.add(compound_id)

    return out, included_stubs


def compounds_with_scan_chromatograms(
    scan: LibraryScanData,
    metadata_stubs: Sequence[Compound],
    *,
    selected_variants: Optional[List[str]] = None,
) -> List[Compound]:
    """Attach scan chromatogram series to metadata stubs for downstream prominence."""
    filtered = filter_compounds_by_variant(list(metadata_stubs), selected_variants)
    allowed_ids = {str(compound.compound_id) for compound in filtered}
    stub_by_id = {str(compound.compound_id): compound for compound in filtered}
    compounds: List[Compound] = []
    for entry in scan.entries:
        compound_id = str(entry.compound_id)
        if compound_id not in allowed_ids:
            continue
        stub = stub_by_id.get(compound_id)
        if stub is None:
            continue
        compounds.append(compound_from_scan_entry(entry, stub))
    return compounds
