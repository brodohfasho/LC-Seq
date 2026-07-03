# src/core/del_cycle_tree/notebook_analyzer.py
"""
Notebook-faithful DEL-cycle RT verification (Null_Tree_Analysis_v1_0).

Ports ``CompoundAnalyzer`` truncation dictionaries and ``verify_sequence`` logic
from the legacy Jupyter notebook.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.del_cycle_tree.models import DelCycleRow, VerifiedSequence
from src.core.lineage_service import ProgressCallback

CompoundDict = Dict[Tuple[str, ...], List[Tuple[Tuple[str, ...], float]]]


def sort_rows_notebook(
    rows: Sequence[DelCycleRow],
    name_to_index: Dict[str, int],
    null_token: str,
) -> List[DelCycleRow]:
    """Sort rows like the notebook ``_sort_dataframe`` (nulls first per column)."""

    def sort_key(row: DelCycleRow) -> Tuple[Tuple[int, float], ...]:
        parts: List[Tuple[int, float]] = []
        for bb in row.positions:
            if bb == null_token:
                parts.append((0, -1.0))
            else:
                parts.append((1, float(name_to_index.get(bb, float("inf")))))
        return tuple(parts)

    return sorted(rows, key=sort_key)


def _compound_key(perm: Tuple[str, ...], null_token: str) -> Tuple[str, ...]:
    return tuple(sorted({bb for bb in perm if bb != null_token}))


def _generate_permutations(
    anchor_bb: str,
    other_bbs: Sequence[str],
    null_token: str,
    n_cycles: int,
) -> List[Tuple[str, ...]]:
    """All 1- and 2-BB positional patterns containing ``anchor_bb`` (notebook logic)."""
    patterns: List[Tuple[str, ...]] = []
    for position in range(n_cycles):
        single = [null_token] * n_cycles
        single[position] = anchor_bb
        patterns.append(tuple(single))
    for position_a in range(n_cycles):
        for position_b in range(n_cycles):
            if position_a == position_b:
                continue
            for other in other_bbs:
                double = [null_token] * n_cycles
                double[position_a] = anchor_bb
                double[position_b] = other
                patterns.append(tuple(double))
    return patterns


def _analyze_building_blocks(
    null_rows: Sequence[DelCycleRow],
    null_token: str,
    n_cycles: int,
) -> Dict[str, Dict[Tuple[str, ...], dict]]:
    """Notebook ``_analyze_building_blocks`` using the last coupling column as anchor."""
    anchor_values = sorted(
        {row.positions[-1] for row in null_rows if row.positions[-1] != null_token},
        key=str.lower,
    )
    other_bbs = list(anchor_values)
    existing = {row.positions: float(row.rt) for row in null_rows}
    analysis_results: Dict[str, Dict[Tuple[str, ...], dict]] = {}

    for anchor in anchor_values:
        permutations = _generate_permutations(anchor, other_bbs, null_token, n_cycles)
        compound_groups: Dict[Tuple[str, ...], List[Tuple[Tuple[str, ...], float]]] = (
            defaultdict(list)
        )
        for perm in permutations:
            rt = existing.get(perm)
            if rt is None:
                continue
            key = _compound_key(perm, null_token)
            compound_groups[key].append((perm, rt))

        anchor_results: Dict[Tuple[str, ...], dict] = {}
        for compound_key, perms_rts in compound_groups.items():
            perms, rts = zip(*perms_rts)
            anchor_results[compound_key] = {
                "permutations": list(perms),
                "rt_values": list(rts),
            }
        if anchor_results:
            analysis_results[anchor] = anchor_results
    return analysis_results


def _reorganize_results(
    results: Dict[str, Dict[Tuple[str, ...], dict]],
    null_token: str,
) -> CompoundDict:
    """Notebook ``_reorganize_results``."""
    reorganized: CompoundDict = {}
    for anchor, compounds in results.items():
        for compound_key, data in compounds.items():
            if len(compound_key) == 1:
                key: Tuple[str, ...] = (anchor,)
            elif len(compound_key) == 2:
                other = compound_key[1] if compound_key[0] == anchor else compound_key[0]
                key = (anchor, other)
            else:
                continue
            bucket = reorganized.setdefault(key, [])
            for perm, rt in zip(data["permutations"], data["rt_values"]):
                non_null_elements = [bb for bb in perm if bb != null_token]
                if tuple(non_null_elements) == key:
                    bucket.append((perm, float(rt)))
    return reorganized


def create_truncated_compound_dict(
    rows: Sequence[DelCycleRow],
    null_token: str,
    n_cycles: int,
) -> CompoundDict:
    """Rows with at least one null BB → reorganized truncation RT library."""
    null_rows = [row for row in rows if any(bb == null_token for bb in row.positions)]
    if not null_rows:
        return {}
    raw = _analyze_building_blocks(null_rows, null_token, n_cycles)
    return _reorganize_results(raw, null_token)


def create_full_compound_dict(
    sorted_rows: Sequence[DelCycleRow],
    truncated_dict: CompoundDict,
) -> CompoundDict:
    """Merge truncated dict with every sorted row (notebook ``_create_full_compound_dict``)."""
    full_dict: CompoundDict = {key: list(entries) for key, entries in truncated_dict.items()}
    for row in sorted_rows:
        if row.positions not in full_dict:
            full_dict[row.positions] = [(row.positions, float(row.rt))]
    return full_dict


def _abbreviation_truncations(positions: Tuple[str, ...]) -> List[Tuple[str, ...]]:
    """All non-empty index combinations → tuple of BB names (notebook verify list)."""
    n = len(positions)
    truncations: List[Tuple[str, ...]] = []
    for size in range(1, n):
        for combo in combinations(range(n), size):
            truncations.append(tuple(positions[index] for index in combo))
    return truncations


def verify_sequence_notebook(
    positions: Tuple[str, ...],
    rt: float,
    full_compound_dict: CompoundDict,
    *,
    null_token: str,
    rt_threshold: float,
) -> bool:
    """Notebook ``verify_sequence`` for a full product tuple."""
    null_positions = tuple(null_token for _ in positions)
    null_entries = full_compound_dict.get(null_positions, [])
    null_rt = null_entries[0][1] if null_entries else None

    if any(bb == null_token for bb in positions):
        if null_rt is not None and abs(rt - null_rt) <= rt_threshold:
            return False

    for truncation in _abbreviation_truncations(positions):
        if truncation not in full_compound_dict:
            continue
        for _perm, truncation_rt in full_compound_dict[truncation]:
            if truncation_rt is not None and abs(rt - truncation_rt) <= rt_threshold:
                return False
    return True


def verify_reaction_sequences_notebook(
    full_compound_dict: CompoundDict,
    *,
    null_token: str,
    n_cycles: int,
    rt_threshold: float,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[Tuple[str, ...], VerifiedSequence]:
    """Verify every full-length product tuple in the compound dictionary (notebook logic)."""
    full_products: List[Tuple[Tuple[str, ...], float]] = []
    for positions, entries in full_compound_dict.items():
        if len(positions) != n_cycles:
            continue
        full_products.append((positions, float(entries[0][1])))

    total = len(full_products)
    verified: Dict[Tuple[str, ...], VerifiedSequence] = {}
    for index, (positions, rt) in enumerate(full_products, start=1):
        success = verify_sequence_notebook(
            positions,
            rt,
            full_compound_dict,
            null_token=null_token,
            rt_threshold=rt_threshold,
        )
        verified[positions] = VerifiedSequence(
            positions=positions,
            rt=rt,
            success=success,
        )
        if progress_callback is not None and (index % 5000 == 0 or index == total):
            progress_callback(
                index,
                total,
                f"Verifying reaction sequences… {index:,} / {total:,}",
            )
    return verified
