# src/core/del_cycle_tree/positions.py
"""BB position helpers for DEL-cycle tree analysis."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.core.del_cycle_tree.models import DelCycleRow
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def positions_c_to_n(
    compound: Compound,
    config: SpreadsheetConfig,
) -> Optional[Tuple[str, ...]]:
    """
    Read BB1..BBn from compound metadata in coupling order (C→N).

    Missing values are filled with ``config.null_token``.
    """
    if not config.pedigree_configured():
        return None
    null = str(config.null_token).strip()
    cols = config.active_bb_position_columns()
    n = config.library_cycle_count
    if len(cols) != n:
        return None
    values: List[str] = []
    for col in cols:
        raw = compound.metadata.get(col)
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            values.append(null)
        else:
            text = str(raw).strip()
            values.append(text if text else null)
    return tuple(values)


def index_discovery_rows_from_compounds(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
) -> List[DelCycleRow]:
    """
    Placeholder rows covering every compound with BB metadata.

    Used to assign stable global display indices independent of which compounds
    happen to resolve an RT during pedigree or peak-picking passes.
    """
    rows: List[DelCycleRow] = []
    for compound in compounds:
        positions = positions_c_to_n(compound, config)
        if positions is None:
            continue
        rows.append(DelCycleRow(positions=positions, rt=0.0))
    return rows


def build_bb_index_by_level(
    rows: Sequence[Tuple[str, ...]],
    null_token: str,
) -> List[Dict[str, int]]:
    """1-based display indices per coupling cycle (C→N order)."""
    if not rows:
        return []
    n_levels = len(rows[0])
    indices: List[Dict[str, int]] = []
    for level in range(n_levels):
        seen: Dict[str, int] = {}
        ordered: List[str] = []
        for positions in rows:
            bb = positions[level]
            if bb == null_token or bb in seen:
                continue
            seen[bb] = 0
            ordered.append(bb)
        ordered.sort(key=lambda name: (-1 if name == null_token else 0, name.lower()))
        indices.append({name: i + 1 for i, name in enumerate(ordered)})
    return indices


def is_truncation_of(
    full: Tuple[str, ...],
    candidate: Tuple[str, ...],
    null_token: str,
) -> bool:
    """True when ``candidate`` is a strict null-truncation pattern of ``full``."""
    if len(full) != len(candidate) or full == candidate:
        return False
    saw_null = False
    for full_bb, cand_bb in zip(full, candidate):
        if cand_bb == null_token:
            saw_null = True
            continue
        if full_bb != cand_bb:
            return False
    return saw_null
