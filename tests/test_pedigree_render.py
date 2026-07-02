# tests/test_pedigree_render.py
"""Tests for pedigree tree rendering."""

from __future__ import annotations

import pytest

from src.core.pedigree_render import (
    build_default_tree_render_options,
    build_pedigree_tree_matplotlib_figure,
    build_pedigree_tree_preview_figure,
    build_pedigree_tree_raster_figure,
    filter_records_for_display,
    graphviz_available,
    render_pedigree_tree,
    render_pedigree_tree_matplotlib,
    suggest_include_failed,
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


def test_build_pedigree_tree_matplotlib_figure() -> None:
    fig = build_pedigree_tree_matplotlib_figure(_TINY_TREE, max_display_tier=1)
    assert fig.axes
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_build_pedigree_tree_raster_figure(tmp_path) -> None:
    png = render_pedigree_tree_matplotlib(_TINY_TREE, tmp_path / "tree.png", max_display_tier=1)
    fig = build_pedigree_tree_raster_figure(png)
    assert fig.axes
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_build_pedigree_tree_preview_figure_graphviz_path(tmp_path) -> None:
    png = render_pedigree_tree_matplotlib(_TINY_TREE, tmp_path / "tree.png", max_display_tier=1)
    fig = build_pedigree_tree_preview_figure(
        _TINY_TREE,
        png,
        render_engine="graphviz",
        max_display_tier=1,
    )
    assert fig.axes
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_render_pedigree_tree_always_produces_image(tmp_path) -> None:
    result = render_pedigree_tree(_TINY_TREE, tmp_path / "tree.png", max_display_tier=1)
    assert result.path.is_file()
    assert result.engine in ("graphviz", "matplotlib")


def test_suggest_include_failed_dense_tree() -> None:
    records = [
        PedigreeNodeRecord(
            id=f"n{i}",
            label=f"N{i}",
            tier=1,
            kind="class",
            passed=(i % 2 == 0),
            evaluated=True,
        )
        for i in range(600)
    ]
    assert suggest_include_failed(records, max_display_tier=1) is False
    assert suggest_include_failed(records[:10], max_display_tier=1) is True


def test_build_default_tree_render_options() -> None:
    records = [
        PedigreeNodeRecord(id="C0", label="root", tier=0, kind="class", passed=True),
        PedigreeNodeRecord(id="C1", label="A", tier=1, kind="class", passed=True, evaluated=True),
    ]
    opts = build_default_tree_render_options(records, library_cycle_count=3)
    assert opts.max_display_tier == 2
    assert opts.show_rt is True


@pytest.mark.skipif(not graphviz_available(), reason="Graphviz not installed")
def test_render_pedigree_tree_graphviz_when_available(tmp_path) -> None:
    result = render_pedigree_tree(_TINY_TREE, tmp_path / "tree_gv.png", max_display_tier=1)
    assert result.engine == "graphviz"
    assert result.path.suffix.lower() == ".png"
