# src/core/del_cycle_tree/builder.py
"""Nested tree construction and pruning for DEL-cycle libraries."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

from src.core.del_cycle_tree.models import DelCycleRow, VerifiedSequence
from src.core.del_cycle_tree.bb_index_scheme import normalize_bb_name


def create_tree(rows: Sequence[DelCycleRow]) -> Dict[str, Any]:
    """
    Build nested BB1→BB2→…→BBn tree with RT values at leaves.

    Interior levels are dicts; the deepest level maps BB name → RT.
    """
    tree: Dict[str, Any] = {}
    if not rows:
        return tree
    depth = len(rows[0].positions)
    for row in rows:
        node: Dict[str, Any] = tree
        for level, bb in enumerate(row.positions):
            bb_key = normalize_bb_name(bb)
            is_leaf = level == depth - 1
            if is_leaf:
                node[bb_key] = float(row.rt)
            else:
                if bb_key not in node or not isinstance(node.get(bb_key), dict):
                    node[bb_key] = {}
                node = node[bb_key]
    return tree


def prune_tree(
    tree: Dict[str, Any],
    verified_sequences: Dict[tuple, VerifiedSequence],
) -> Dict[str, Any]:
    """Keep only verified full-product leaves and their ancestral branches."""
    pruned: Dict[str, Any] = defaultdict(lambda: defaultdict(dict))

    for positions, info in verified_sequences.items():
        if not info.success:
            continue
        if not positions:
            continue
        cursor = tree
        path: List[str] = []
        for bb in positions:
            bb_key = normalize_bb_name(bb)
            if bb_key not in cursor:
                break
            path.append(bb_key)
            value = cursor[bb_key]
            if isinstance(value, dict):
                cursor = value
            else:
                if len(path) == len(positions):
                    _set_nested(pruned, path, float(value))
                break
    return _freeze_nested(pruned)


def _set_nested(target: Dict[str, Any], path: List[str], rt: float) -> None:
    node = target
    for bb in path[:-1]:
        if bb not in node or not isinstance(node[bb], dict):
            node[bb] = {}
        node = node[bb]
    node[path[-1]] = rt


def _freeze_nested(node: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in node.items():
        if isinstance(value, defaultdict):
            out[key] = _freeze_nested(dict(value))
        elif isinstance(value, dict):
            out[key] = _freeze_nested(value)
        else:
            out[key] = value
    return out


def flatten_del_tree_rts(
    tree: Dict[str, Any],
    *,
    prefix: Tuple[str, ...] = (),
) -> Dict[Tuple[str, ...], float]:
    """Collect every leaf RT in a nested DEL tree keyed by C→N position tuple."""
    lookup: Dict[Tuple[str, ...], float] = {}
    for name, child in tree.items():
        path = prefix + (normalize_bb_name(name),)
        if isinstance(child, dict):
            lookup.update(flatten_del_tree_rts(child, prefix=path))
        else:
            lookup[path] = float(child)
    return lookup
