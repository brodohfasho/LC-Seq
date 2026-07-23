# tests/test_del_cycle_render.py
"""Tests for DEL-cycle split-tree matplotlib rendering."""

from __future__ import annotations

import networkx as nx

from src.core.del_cycle_tree.models import DelCycleTreeView
from src.core.del_cycle_tree.render import (
    LEAF_NODE_SIZE,
    _assign_node_sizes,
    _figsize_scale,
    _should_label_node,
)


def test_figsize_scale_matches_notebook_reference() -> None:
    assert _figsize_scale((40.0, 40.0)) == 1.0
    assert _figsize_scale((12.0, 12.0)) == 0.3


def test_branch_leaf_nodes_smaller_than_hubs() -> None:
    graph = nx.Graph()
    bb1 = (1, "A")
    bb2 = (2, "A", "B")
    bb3_c = (3, "A", "B", "C")
    bb3_d = (3, "A", "B", "D")
    for node in (bb1, bb2, bb3_c, bb3_d):
        graph.add_node(node)
    graph.add_edge(bb1, bb2)
    graph.add_edge(bb2, bb3_c)
    graph.add_edge(bb2, bb3_d)

    sizes = _assign_node_sizes(graph, view=DelCycleTreeView.BRANCH, figsize=(12.0, 12.0))
    assert sizes[bb1] > sizes[bb2] > sizes[bb3_c]
    assert sizes[bb3_c] == max(20, int(LEAF_NODE_SIZE * _figsize_scale((12.0, 12.0))))


def test_branch_labels_only_on_cluster_hubs() -> None:
    graph = nx.Graph()
    bb1 = (1, "A")
    bb2 = (2, "A", "B")
    leaf = (3, "A", "B", "C")
    for node in (bb1, bb2, leaf):
        graph.add_node(node)
    graph.add_edge(bb1, bb2)
    graph.add_edge(bb2, leaf)

    assert _should_label_node(graph, bb1, view=DelCycleTreeView.BRANCH)
    assert _should_label_node(graph, bb2, view=DelCycleTreeView.BRANCH)
    assert not _should_label_node(graph, leaf, view=DelCycleTreeView.BRANCH)


def test_branch_root_labeled_even_without_children() -> None:
    graph = nx.Graph()
    bb1 = (1, "Lonely")
    graph.add_node(bb1)
    assert _should_label_node(graph, bb1, view=DelCycleTreeView.BRANCH)


def test_sunflower_first_child_not_on_east_axis() -> None:
    from src.core.del_cycle_tree.render import _sunflower_fractal_layout

    graph = nx.Graph()
    root = (1, "A")
    child = (2, "A", "B")
    graph.add_node(root)
    graph.add_node(child)
    graph.add_edge(root, child)
    sizes = {root: 500, child: 100}
    positions = _sunflower_fractal_layout(graph, root, sizes)
    rx, ry = positions[root]
    cx, cy = positions[child]
    assert abs(cy - ry) > 1e-6 or abs(cx - rx) > 1e-6
    assert not (abs(cy - ry) < 1e-6 and cx > rx)


def test_node_label_uses_case_insensitive_global_index() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import _node_label

    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={},
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"la18": 12, "AlaMe": 1, "LA03": 30},
        bb_index_by_level=[{"LA18": 1}, {"AlaMe": 1, "LA18": 2}],
    )
    assert _node_label(data, (1, "LA18")) == "12"
    assert _node_label(data, (2, "LA18", "AlaMe")) == "1"
    assert _node_label(data, (1, "LA03")) == "30"


def test_node_label_ignores_per_level_index_fallback() -> None:
    """Full-tree labels must match the global reference table, not per-cycle maps."""
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import _node_label

    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={},
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"Leu": 3, "DLeu": 2},
        bb_index_by_level=[{"Leu": 1, "DLeu": 2}, {"Leu": 1}],
    )
    assert _node_label(data, (1, "Leu")) == "3"
    assert _node_label(data, (2, "Leu", "DLeu")) == "2"


def test_full_tree_labels_bb1_hubs_only() -> None:
    graph = nx.Graph()
    root = (0, "AgxNull")
    bb1 = (1, "A")
    bb2 = (2, "A", "B")
    for node in (root, bb1, bb2):
        graph.add_node(node)
    graph.add_edge(root, bb1)
    graph.add_edge(bb1, bb2)

    assert not _should_label_node(graph, root, view=DelCycleTreeView.FULL)
    assert _should_label_node(graph, bb1, view=DelCycleTreeView.FULL)
    assert not _should_label_node(graph, bb2, view=DelCycleTreeView.FULL)


def test_full_tree_figure_labels_bb1_with_global_index() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import render_del_cycle_tree_figure

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={
            "LA03": {"DPhe": {"X": 1.0}},
            "Leu": {"DPhe": {"Y": 2.0}},
        },
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "LA03": 30, "Leu": 12, "X": 20, "Y": 21},
        bb1_names=[null, "LA03", "Leu"],
    )
    figure = render_del_cycle_tree_figure(
        data,
        view=DelCycleTreeView.FULL,
        show_figure_title=False,
        figsize=(8.0, 8.0),
    )
    labels = {text.get_text() for text in figure.axes[0].texts}
    assert "30" in labels
    assert "12" in labels
    assert "4" not in labels
    assert "0" not in labels
    from src.core.del_cycle_tree.render import _node_label

    assert _node_label(data, (0, null)) is None
    assert _node_label(data, (1, "LA03")) == "30"
    assert _node_label(data, (2, "LA03", "DPhe")) == "4"
    import matplotlib.pyplot as plt

    plt.close(figure)


def test_full_tree_figure_reports_progress() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import render_del_cycle_tree_figure

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={
            "LA03": {"DPhe": {"X": 1.0}},
            "Leu": {"DPhe": {"Y": 2.0}},
        },
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "LA03": 30, "Leu": 12, "X": 20, "Y": 21},
        bb1_names=[null, "LA03", "Leu"],
    )
    updates: list[tuple[float, str]] = []

    def on_progress(fraction: float, status: str) -> None:
        updates.append((fraction, status))

    figure = render_del_cycle_tree_figure(
        data,
        view=DelCycleTreeView.FULL,
        show_figure_title=False,
        figsize=(8.0, 8.0),
        progress_callback=on_progress,
    )
    import matplotlib.pyplot as plt

    plt.close(figure)
    assert updates
    assert updates[-1][0] == 1.0
    fractions = [fraction for fraction, _status in updates]
    assert fractions == sorted(fractions)
    assert any("layout" in status.lower() or "graph" in status.lower() for _f, status in updates)


def test_full_tree_bb1_labels_match_branch_roots() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import _node_label, render_del_cycle_tree_figure

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={
            null: {"DPhe": {"N": 1.0}},
            "LA03": {"DPhe": {"X": 2.0}, "Leu": {"Y": 3.0}},
            "Leu": {"DPhe": {"Z": 4.0}},
        },
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "LA03": 30, "Leu": 12, "N": 5, "X": 20, "Y": 21, "Z": 22},
        bb1_names=[null, "LA03", "Leu"],
    )
    import matplotlib.pyplot as plt

    for bb1_name in data.bb1_names:
        if bb1_name == null:
            continue
        full_label = _node_label(data, (1, bb1_name))
        branch_fig = render_del_cycle_tree_figure(
            data,
            view=DelCycleTreeView.BRANCH,
            branch_bb1=bb1_name,
            show_figure_title=False,
            figsize=(6.0, 6.0),
        )
        branch_labels = {text.get_text() for text in branch_fig.axes[0].texts}
        assert full_label is not None
        assert full_label in branch_labels
        assert _node_label(data, (1, bb1_name)) == full_label
        plt.close(branch_fig)


def test_root_hub_unlabeled_null_bb1_still_zero() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import _node_label

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={null: {"DPhe": {"N": 1.0}}},
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "N": 5},
        bb1_names=[null],
    )
    assert _node_label(data, (0, null)) is None
    assert _node_label(data, (1, null)) == "0"


def test_coupling_bb_name_matches_notebook_depth_rules() -> None:
    from src.core.del_cycle_tree.render import _coupling_bb_name

    assert _coupling_bb_name((1, "LA03")) == "LA03"
    assert _coupling_bb_name((2, "LA03", "DPhe")) == "DPhe"


def test_pass_pct_cutoff_controls_hub_coloring() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData, VerifiedSequence
    from src.core.del_cycle_tree.render import (
        COLOR_MODE_NOTEBOOK,
        _path_fails_pass_cutoff,
    )

    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={"A": {"B": {"C": 1.0, "D": 2.0, "E": 3.0, "F": 4.0}}},
        pruned_tree={},
        verified_sequences={
            ("A", "B", "C"): VerifiedSequence(("A", "B", "C"), 1.0, True),
            ("A", "B", "D"): VerifiedSequence(("A", "B", "D"), 2.0, True),
            ("A", "B", "E"): VerifiedSequence(("A", "B", "E"), 3.0, False),
            ("A", "B", "F"): VerifiedSequence(("A", "B", "F"), 4.0, False),
        },
        full_null_rt=10.0,
    )
    hub_path = ("A", "B")
    kwargs = {"is_leaf": False, "color_mode": COLOR_MODE_NOTEBOOK}
    assert not _path_fails_pass_cutoff(data, hub_path, pass_pct_cutoff=0.0, **kwargs)
    assert not _path_fails_pass_cutoff(data, hub_path, pass_pct_cutoff=50.0, **kwargs)
    assert _path_fails_pass_cutoff(data, hub_path, pass_pct_cutoff=51.0, **kwargs)
    assert _path_fails_pass_cutoff(data, hub_path, pass_pct_cutoff=100.0, **kwargs)


def test_full_tree_excludes_null_bb1_arm() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import render_del_cycle_tree_figure

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={
            null: {"DPhe": {"N": 1.0}},
            "LA03": {"DPhe": {"X": 2.0}},
        },
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "LA03": 30, "N": 5, "X": 20},
        bb1_names=[null, "LA03"],
    )
    import matplotlib.pyplot as plt

    figure = render_del_cycle_tree_figure(
        data,
        view=DelCycleTreeView.FULL,
        show_figure_title=False,
        figsize=(8.0, 8.0),
    )
    labels = {text.get_text() for text in figure.axes[0].texts}
    assert "0" not in labels
    assert "30" in labels
    plt.close(figure)


def test_branch_tree_excludes_null_clusters() -> None:
    from src.core.del_cycle_tree.models import DelCycleTreeData
    from src.core.del_cycle_tree.render import render_del_cycle_tree_figure

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={
            "LA03": {
                "DPhe": {"X": 2.0},
                null: {"N": 1.0},
            },
        },
        pruned_tree={},
        verified_sequences={},
        full_null_rt=10.0,
        bb_index_global={"DPhe": 4, "LA03": 30, "N": 5, "X": 20},
        bb1_names=["LA03"],
    )
    import matplotlib.pyplot as plt

    figure = render_del_cycle_tree_figure(
        data,
        view=DelCycleTreeView.BRANCH,
        branch_bb1="LA03",
        show_figure_title=False,
        figsize=(8.0, 8.0),
    )
    labels = {text.get_text() for text in figure.axes[0].texts}
    assert "0" not in labels
    assert "30" in labels
    assert "4" in labels
    plt.close(figure)
