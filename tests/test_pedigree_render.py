# tests/test_pedigree_render.py
"""Tests for pedigree tree rendering."""

from __future__ import annotations

import pytest

from src.core.pedigree_render import (
    filter_records_for_display,
    graphviz_available,
    render_pedigree_tree,
    render_pedigree_tree_matplotlib,
)
from src.models.pedigree_result import PedigreeNodeRecord

_TINY_TREE = [
    PedigreeNodeRecord(
        id="C0",
        label="root",
        tier=0,
        kind="class",
        passed=True,
        parent_ids=[],
    ),
    PedigreeNodeRecord(
        id="C1",
        label="class A",
        tier=1,
        kind="class",
        passed=True,
        parent_ids=["C0"],
        score_test_rt=12.0,
    ),
]


def test_filter_records_for_display() -> None:
    records = [
        PedigreeNodeRecord(id="r", label="root", tier=0, kind="class"),
        PedigreeNodeRecord(id="c", label="leaf", tier=3, kind="compound"),
    ]
    filtered = filter_records_for_display(records, max_display_tier=2)
    assert len(filtered) == 1
    assert filtered[0].tier == 0


def test_render_pedigree_tree_matplotlib(tmp_path) -> None:
    out = render_pedigree_tree_matplotlib(_TINY_TREE, tmp_path / "tree.png", max_display_tier=1)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_render_pedigree_tree_always_produces_image(tmp_path) -> None:
    result = render_pedigree_tree(_TINY_TREE, tmp_path / "tree.png", max_display_tier=1)
    assert result.path.is_file()
    assert result.engine in ("graphviz", "matplotlib")


@pytest.mark.skipif(not graphviz_available(), reason="Graphviz not installed")
def test_render_pedigree_tree_graphviz_when_available(tmp_path) -> None:
    result = render_pedigree_tree(_TINY_TREE, tmp_path / "tree_gv.png", max_display_tier=1)
    assert result.engine == "graphviz"
    assert result.path.suffix.lower() == ".png"
