# tests/test_lineage_ancestors.py
"""Tests for lineage ancestor enumeration."""

from __future__ import annotations

from src.core.lineage_ancestors import (
    class_id_for,
    enumerate_lineage_ancestors,
)


class TestEnumerateLineageAncestors:
    def test_single_bb_leaf_includes_root_and_leaf(self) -> None:
        ancestors = enumerate_lineage_ancestors(["Ala"])
        assert [] in ancestors
        assert ["Ala"] in ancestors

    def test_two_bb_structural_ancestors(self) -> None:
        ancestors = enumerate_lineage_ancestors(["A", "B"])
        keys = {tuple(a) for a in ancestors}
        assert () in keys
        assert ("A",) in keys
        assert ("B",) in keys
        assert ("A", "B") in keys

    def test_cassette_splits_chemical_ancestor(self) -> None:
        ancestors = enumerate_lineage_ancestors(["X-Y"])
        keys = {tuple(a) for a in ancestors}
        assert ("X",) in keys
        assert ("Y",) in keys

    def test_class_id_for(self) -> None:
        assert class_id_for([]) == "C0"
        assert class_id_for(["Ala", "Gly"]) == "C2_Ala_Gly"
