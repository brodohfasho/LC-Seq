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


def build_chromatogram_map(
    compounds: Sequence[Compound],
    channel: str,
    config: SpreadsheetConfig,
) -> Dict[ChromatogramKey, Chromatogram]:
    """Build kernel chromatogram dict keyed by N→C position tuple."""
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
        rt = np.asarray(times, dtype=np.float64)
        intensity = np.asarray(counts, dtype=np.float64)
        out[key] = (rt, intensity)
    return out
