# tests/test_del_cycle_tree.py
"""Tests for DEL-cycle split-tree analysis."""

from __future__ import annotations

from src.core.del_cycle_tree.analyzer import (
    dedupe_rows_by_position,
    sort_rows,
    verify_reaction_sequences,
    verify_sequence,
)
from src.core.del_cycle_tree.builder import create_tree, prune_tree
from src.core.del_cycle_tree.models import DelCycleRow


def test_verify_sequence_rejects_near_truncation_rt() -> None:
    null = "AgxNull"
    lookup = {
        (null, null, null): 10.0,
        ("A", null, null): 12.0,
        ("A", "B", "C"): 12.1,
    }
    assert not verify_sequence(
        ("A", "B", "C"),
        12.1,
        lookup,
        null_token=null,
        rt_threshold=0.5,
    )
    assert verify_sequence(
        ("A", "B", "C"),
        15.0,
        lookup,
        null_token=null,
        rt_threshold=0.5,
    )


def test_prune_tree_keeps_only_verified_products() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow((null, null, null), 10.0),
        DelCycleRow(("A", null, null), 12.0),
        DelCycleRow(("A", "B", "C"), 15.0),
        DelCycleRow(("A", "B", "D"), 12.2),
    ]
    verified = verify_reaction_sequences(rows, null_token=null, rt_threshold=0.5)
    tree = create_tree(rows)
    pruned = prune_tree(tree, verified)
    assert "A" in pruned
    assert "B" in pruned["A"]
    assert pruned["A"]["B"]["C"] == 15.0
    assert "D" not in pruned["A"]["B"]


def test_sort_rows_handles_null_and_named_bbs() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow(("B", null, null), 1.0),
        DelCycleRow((null, "A", null), 2.0),
        DelCycleRow((null, null, null), 3.0),
    ]
    sorted_rows = sort_rows(rows, null_token=null)
    assert [row.positions for row in sorted_rows] == [
        (null, null, null),
        (null, "A", null),
        ("B", null, null),
    ]


def test_verify_sequence_ignores_unrelated_lookup_entries() -> None:
    """Verification must only compare positional truncations, not every library row."""
    null = "AgxNull"
    lookup = {
        (null, null, null): 10.0,
        ("A", null, null): 12.0,
        ("A", "B", "C"): 15.0,
    }
    # Pad lookup with unrelated full products that are not truncations of (A, B, C).
    for index in range(1000):
        lookup[(f"X{index}", f"Y{index}", f"Z{index}")] = float(index)

    assert verify_sequence(
        ("A", "B", "C"),
        15.0,
        lookup,
        null_token=null,
        rt_threshold=0.5,
    )


def test_dedupe_rows_by_position_keeps_last_rt() -> None:
    rows = [
        DelCycleRow(("A", "B", "C"), 10.0),
        DelCycleRow(("A", "B", "C"), 20.0),
    ]
    deduped = dedupe_rows_by_position(rows)
    assert len(deduped) == 1
    assert deduped[0].rt == 20.0
