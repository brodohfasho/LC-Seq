# src/core/del_cycle_tree/analyzer.py
"""RT verification for DEL-cycle positional trees."""

from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from src.core.del_cycle_tree.models import DelCycleRow, VerifiedSequence
from src.core.lineage_service import ProgressCallback


def sort_rows(rows: Sequence[DelCycleRow], null_token: str) -> List[DelCycleRow]:
    """Sort rows by BB names with nulls first at each level."""

    def sort_key(row: DelCycleRow) -> Tuple[Tuple[int, str], ...]:
        parts: List[Tuple[int, str]] = []
        for bb in row.positions:
            if bb == null_token:
                parts.append((0, ""))
            else:
                parts.append((1, bb.lower()))
        return tuple(parts)

    return sorted(rows, key=sort_key)


def dedupe_rows_by_position(rows: Sequence[DelCycleRow]) -> List[DelCycleRow]:
    """Keep one row per position tuple (last occurrence wins)."""
    by_position: Dict[Tuple[str, ...], DelCycleRow] = {}
    for row in rows:
        by_position[row.positions] = row
    return list(by_position.values())


def rows_by_positions(rows: Sequence[DelCycleRow]) -> Dict[Tuple[str, ...], float]:
    """Map exact position tuple to RT (last row wins on duplicates)."""
    out: Dict[Tuple[str, ...], float] = {}
    for row in rows:
        out[row.positions] = float(row.rt)
    return out


def _positional_truncation_patterns(
    positions: Tuple[str, ...],
    null_token: str,
) -> Iterator[Tuple[str, ...]]:
    """
    Yield every strict positional null-truncation of ``positions``.

  Each pattern replaces one or more coupling positions with ``null_token``
    while keeping the remaining BB names fixed.
    """
    n = len(positions)
    for mask in range(1, 1 << n):
        pattern = tuple(
            null_token if (mask >> level) & 1 else positions[level]
            for level in range(n)
        )
        if pattern != positions:
            yield pattern


def verify_sequence(
    positions: Tuple[str, ...],
    rt: float,
    lookup: Dict[Tuple[str, ...], float],
    *,
    null_token: str,
    rt_threshold: float,
) -> bool:
    """
    Verify a full product sequence against null and truncation RTs.

    Fails when the product RT is within ``rt_threshold`` of any positional
    truncation row present in ``lookup``.
    """
    for pattern in _positional_truncation_patterns(positions, null_token):
        other_rt = lookup.get(pattern)
        if other_rt is not None and abs(rt - other_rt) <= rt_threshold:
            return False
    return True


def verify_reaction_sequences(
    rows: Sequence[DelCycleRow],
    *,
    null_token: str,
    rt_threshold: float,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[Tuple[str, ...], VerifiedSequence]:
    """Verify every full (non-null) product sequence in the dataset."""
    lookup = rows_by_positions(rows)
    full_products = [
        (positions, rt)
        for positions, rt in lookup.items()
        if not any(bb == null_token for bb in positions)
    ]
    total = len(full_products)
    verified: Dict[Tuple[str, ...], VerifiedSequence] = {}

    for index, (positions, rt) in enumerate(full_products, start=1):
        success = verify_sequence(
            positions,
            rt,
            lookup,
            null_token=null_token,
            rt_threshold=rt_threshold,
        )
        verified[positions] = VerifiedSequence(
            positions=positions,
            rt=rt,
            success=success,
        )
        if progress_callback is not None and (
            index % 5000 == 0 or index == total
        ):
            progress_callback(
                index,
                total,
                f"Verifying reaction sequences… {index:,} / {total:,}",
            )

    return verified
