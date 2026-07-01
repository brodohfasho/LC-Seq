# src/core/lineage_ancestors.py
"""
Enumerate null-truncation ancestor classes for single-compound lineage analysis.

Mirrors ``inspect_lineage`` in LC-Seq-New-master ``python/lcseq/debug.py``.
"""

from __future__ import annotations

from typing import List, Sequence, Set, Tuple


def enumerate_lineage_ancestors(leaf_class_bbs: Sequence[str]) -> List[List[str]]:
    """
    Return ancestor class BB lists for a leaf, sorted by tier ascending (root first).

    Lineage = root + chemical ancestors (cassette singleton components) + structural
    ancestors (every ordered subsequence from dropping one BB) + the leaf itself.
    """
    leaf_seq = tuple(leaf_class_bbs)
    ancestors: Set[Tuple[str, ...]] = set()
    ancestors.add(())

    def add_structural(seq: Tuple[str, ...]) -> None:
        ancestors.add(seq)
        if not seq:
            return
        for i in range(len(seq)):
            child = seq[:i] + seq[i + 1 :]
            add_structural(child)

    add_structural(leaf_seq)

    def add_chemical(seq: Tuple[str, ...]) -> None:
        for bb in seq:
            if "-" in bb:
                for comp in bb.split("-"):
                    if (comp,) not in ancestors:
                        ancestors.add((comp,))
                        add_chemical((comp,))

    add_chemical(leaf_seq)

    return [list(c) for c in sorted(ancestors, key=lambda s: (len(s), s))]


def class_id_for(class_bbs: Sequence[str]) -> str:
    """Build canonical class ID the same way the Rust kernel does."""
    bbs = list(class_bbs)
    if not bbs:
        return "C0"
    return f"C{len(bbs)}_{'_'.join(bbs)}"


def compound_id_for(class_bbs: Sequence[str]) -> str:
    """Tier-N compound node id for a full sequence."""
    bbs = list(class_bbs)
    if not bbs:
        return "F0"
    return f"F{len(bbs)}_{'_'.join(bbs)}"
