# src/core/del_cycle_tree/render.py
"""Matplotlib rendering for combinatorial split-tree figures."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from src.core.del_cycle_tree.bb_index_scheme import lookup_bb_display_index, normalize_bb_name
from src.core.del_cycle_tree.models import DelCycleTreeData, DelCycleTreeView, VerifiedSequence

TreeNode = Union[str, Tuple[Any, ...]]
PRUNED_COLOR = "lightcoral"
ACTIVE_COLOR = "powderblue"
ROOT_COLOR = "lightgray"
COLOR_MODE_NOTEBOOK = "notebook"
COLOR_MODE_PEDIGREE = "pedigree"
ProgressCallback = Callable[[float, str], None]

# Notebook ``visualize_*`` uses figsize=(40, 40) with these point sizes.
NOTEBOOK_REFERENCE_FIGSIZE = 40.0
FULL_TREE_HUB_SIZES = {0: 700, 1: 500, 2: 150}
BRANCH_HUB_SIZES = {1: 700, 2: 500, 3: 400, 4: 320, 5: 280}
LEAF_NODE_SIZE = 90
HUB_LABEL_FONT = {0: 12, 1: 12, 2: 10, 3: 9, 4: 8, 5: 7}


def _report_progress(
    callback: Optional[ProgressCallback],
    fraction: float,
    status: str,
) -> None:
    if callback is not None:
        callback(min(1.0, max(0.0, fraction)), status)


def _figsize_scale(figsize: Tuple[float, float]) -> float:
    """Scale node sizes so they match notebook proportions at any figure size."""
    return min(figsize) / NOTEBOOK_REFERENCE_FIGSIZE


def _node_depth(node: TreeNode) -> int:
    if isinstance(node, tuple):
        return int(node[0])
    return 0


def _tree_children(graph: nx.Graph, node: TreeNode) -> List[TreeNode]:
    depth = _node_depth(node)
    return [
        neighbor
        for neighbor in graph.neighbors(node)
        if _node_depth(neighbor) > depth
    ]


def _should_label_node(
    graph: nx.Graph,
    node: TreeNode,
    *,
    view: DelCycleTreeView,
) -> bool:
    """Label cluster hubs; peripheral leaves stay unnumbered."""
    depth = _node_depth(node)
    if view == DelCycleTreeView.FULL:
        # Full-tree overview numbers BB1 branches only (same as branch roots / CSV bb1_index).
        # BB2 outer-ring nodes stay unlabeled so global indices are not misread as BB1 ids.
        return depth == 1
    if depth == 1:
        return True
    return bool(_tree_children(graph, node))


def _structural_hub_nodes(
    graph: nx.Graph,
    *,
    view: DelCycleTreeView,
) -> List[TreeNode]:
    """Nodes drawn as large hubs (distinct from which hubs receive numeric labels)."""
    if view == DelCycleTreeView.FULL:
        return [node for node in graph.nodes() if _node_depth(node) <= 2]
    return [
        node
        for node in graph.nodes()
        if _should_label_node(graph, node, view=view)
    ]


def _node_display_size(
    graph: nx.Graph,
    node: TreeNode,
    *,
    view: DelCycleTreeView,
    figsize: Tuple[float, float],
) -> int:
    """Hub nodes stay large; peripheral leaves shrink to reduce overlap."""
    scale = _figsize_scale(figsize)
    depth = _node_depth(node)
    if view == DelCycleTreeView.FULL:
        base = FULL_TREE_HUB_SIZES.get(depth, 300)
    elif _tree_children(graph, node):
        base = BRANCH_HUB_SIZES.get(depth, max(180, 520 - depth * 80))
    else:
        base = LEAF_NODE_SIZE
    return max(20, int(base * scale))


def _label_fontsize(
    node: TreeNode,
    *,
    figsize: Tuple[float, float],
    view: DelCycleTreeView,
) -> int:
    depth = _node_depth(node)
    scale = _figsize_scale(figsize)
    base = HUB_LABEL_FONT.get(depth, 8)
    if view == DelCycleTreeView.FULL and depth == 1:
        base = 14
    return max(6, int(base * max(0.75, scale * 2.5)))


def _assign_node_sizes(
    graph: nx.Graph,
    *,
    view: DelCycleTreeView,
    figsize: Tuple[float, float],
) -> Dict[TreeNode, int]:
    return {
        node: _node_display_size(graph, node, view=view, figsize=figsize)
        for node in graph.nodes()
    }


def render_del_cycle_tree_figure(
    data: DelCycleTreeData,
    *,
    view: DelCycleTreeView,
    branch_bb1: Optional[str] = None,
    color_by_rt: bool = False,
    color_mode: str = COLOR_MODE_NOTEBOOK,
    pass_pct_cutoff: float = 0.0,
    figsize: Tuple[float, float] = (12.0, 12.0),
    show_figure_title: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> plt.Figure:
    """Build a matplotlib figure for the requested split-tree view."""
    if view == DelCycleTreeView.FULL:
        return _render_full_tree(
            data,
            color_by_rt=color_by_rt,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
            figsize=figsize,
            show_figure_title=show_figure_title,
            progress_callback=progress_callback,
        )
    if not branch_bb1:
        raise ValueError("branch_bb1 is required for branch view")
    if branch_bb1 not in data.tree:
        raise ValueError(f"BB1 branch not found: {branch_bb1}")
    return _render_branch_tree(
        data,
        branch_bb1=branch_bb1,
        color_by_rt=color_by_rt,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
        figsize=figsize,
        show_figure_title=show_figure_title,
        progress_callback=progress_callback,
    )


def _render_full_tree(
    data: DelCycleTreeData,
    *,
    color_by_rt: bool,
    color_mode: str,
    pass_pct_cutoff: float,
    figsize: Tuple[float, float],
    show_figure_title: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> plt.Figure:
    """Root → BB1 → BB2 overview (deepest cycle omitted, matching legacy notebook)."""
    n_cycles = data.library_cycle_count
    if n_cycles < 2:
        raise ValueError("Split-tree requires at least two coupling cycles")

    _report_progress(progress_callback, 0.08, "Building full split-tree graph…")
    graph = nx.Graph()
    root: TreeNode = (0, data.null_token)
    graph.add_node(root, color=ROOT_COLOR, edgecolor="k")
    null = data.null_token

    bb1_list = [name for name in data.bb1_names if name in data.tree and name != null]
    bb1_total = max(len(bb1_list), 1)
    for index, bb1_name in enumerate(bb1_list):
        bb1_node: TreeNode = (1, bb1_name)
        pruned = _path_fails_pass_cutoff(
            data,
            (bb1_name,),
            is_leaf=False,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
        )
        graph.add_node(
            bb1_node,
            color=PRUNED_COLOR if pruned else ACTIVE_COLOR,
            edgecolor="r" if pruned else "k",
        )
        graph.add_edge(root, bb1_node, color="r" if pruned else "k")

        bb2_dict = data.tree.get(bb1_name, {})
        if not isinstance(bb2_dict, dict):
            continue
        for bb2_name in bb2_dict.keys():
            bb2_node: TreeNode = (2, bb1_name, bb2_name)
            pruned_bb2 = _path_fails_pass_cutoff(
                data,
                (bb1_name, bb2_name),
                is_leaf=False,
                color_mode=color_mode,
                pass_pct_cutoff=pass_pct_cutoff,
            )
            graph.add_node(
                bb2_node,
                color=PRUNED_COLOR if pruned_bb2 else ACTIVE_COLOR,
                edgecolor="r" if pruned_bb2 else "k",
            )
            graph.add_edge(
                bb1_node,
                bb2_node,
                color="r" if pruned_bb2 else "k",
            )
        if index % max(1, bb1_total // 20) == 0 or index + 1 == bb1_total:
            _report_progress(
                progress_callback,
                0.08 + 0.32 * ((index + 1) / bb1_total),
                f"Building full split-tree graph ({index + 1}/{bb1_total})…",
            )

    _report_progress(progress_callback, 0.45, "Computing node sizes…")
    node_sizes = _assign_node_sizes(graph, view=DelCycleTreeView.FULL, figsize=figsize)
    _report_progress(progress_callback, 0.58, "Computing sunflower layout…")
    positions = _sunflower_fractal_layout(graph, root, node_sizes)
    _report_progress(progress_callback, 0.72, "Drawing split-tree figure…")
    figure = _draw_graph(
        graph,
        positions,
        node_sizes,
        data,
        color_by_rt=color_by_rt,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
        figsize=figsize,
        view=DelCycleTreeView.FULL,
        title="Split-tree (full)" if show_figure_title else "",
    )
    _report_progress(progress_callback, 1.0, "Split-tree figure ready…")
    return figure


def _render_branch_tree(
    data: DelCycleTreeData,
    *,
    branch_bb1: str,
    color_by_rt: bool,
    color_mode: str,
    pass_pct_cutoff: float,
    figsize: Tuple[float, float],
    show_figure_title: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> plt.Figure:
    """BB1 → BB2 → … branch for one BB1 root."""
    null = data.null_token
    if branch_bb1 == null:
        raise ValueError("Null BB1 branch is not rendered")

    _report_progress(
        progress_callback,
        0.08,
        f"Building branch graph for {branch_bb1}…",
    )
    graph = nx.Graph()
    bb1_node: TreeNode = (1, branch_bb1)
    pruned_bb1 = _path_fails_pass_cutoff(
        data,
        (branch_bb1,),
        is_leaf=False,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
    )
    graph.add_node(
        bb1_node,
        color=PRUNED_COLOR if pruned_bb1 else ACTIVE_COLOR,
    )

    subtree = data.tree.get(branch_bb1, {})
    if isinstance(subtree, dict):
        _add_branch_nodes(
            graph,
            data,
            parent_node=bb1_node,
            subtree=subtree,
            path=(branch_bb1,),
            depth=2,
            color_by_rt=color_by_rt,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
        )

    _report_progress(progress_callback, 0.45, "Computing branch node sizes…")
    node_sizes = _assign_node_sizes(graph, view=DelCycleTreeView.BRANCH, figsize=figsize)
    _report_progress(progress_callback, 0.58, "Computing branch layout…")
    positions = _sunflower_fractal_layout(graph, bb1_node, node_sizes)
    _report_progress(progress_callback, 0.72, "Drawing branch figure…")
    figure = _draw_graph(
        graph,
        positions,
        node_sizes,
        data,
        color_by_rt=color_by_rt,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
        figsize=figsize,
        view=DelCycleTreeView.BRANCH,
        title=f"Split-tree branch — {branch_bb1}" if show_figure_title else "",
    )
    _report_progress(progress_callback, 1.0, "Split-tree figure ready…")
    return figure


def _add_branch_nodes(
    graph: nx.Graph,
    data: DelCycleTreeData,
    *,
    parent_node: TreeNode,
    subtree: Dict[str, Any],
    path: Tuple[str, ...],
    depth: int,
    color_by_rt: bool,
    color_mode: str,
    pass_pct_cutoff: float,
) -> None:
    """Recursively add nodes for one BB1 branch down to product leaves."""
    n_cycles = data.library_cycle_count
    null = data.null_token

    for bb_name, child in subtree.items():
        if bb_name == null:
            continue
        current_path = path + (bb_name,)
        node: TreeNode = (depth,) + current_path
        is_leaf = depth >= n_cycles or not isinstance(child, dict)
        pruned = _path_fails_pass_cutoff(
            data,
            current_path,
            is_leaf=is_leaf,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
        )

        if color_by_rt and is_leaf and not pruned and len(current_path) == n_cycles:
            node_color = _rt_color(
                _verified_rt(data, positions=current_path),
                data.full_null_rt,
            )
        else:
            node_color = PRUNED_COLOR if pruned else ACTIVE_COLOR

        graph.add_node(node, color=node_color)
        graph.add_edge(parent_node, node, color="r" if pruned else "k")

        if isinstance(child, dict) and depth < n_cycles:
            _add_branch_nodes(
                graph,
                data,
                parent_node=node,
                subtree=child,
                path=current_path,
                depth=depth + 1,
                color_by_rt=color_by_rt,
                color_mode=color_mode,
                pass_pct_cutoff=pass_pct_cutoff,
            )


def _subtree_at_path(tree: Dict[str, Any], prefix: Tuple[str, ...]) -> Any:
    """Return nested tree node at ``prefix``, or ``None`` if missing."""
    node: Any = tree
    for bb in prefix:
        if not isinstance(node, dict) or bb not in node:
            return None
        node = node[bb]
    return node


def _iter_full_product_paths(
    subtree: Dict[str, Any],
    prefix: Tuple[str, ...],
    n_cycles: int,
) -> List[Tuple[str, ...]]:
    """Collect full-length product position tuples under ``prefix``."""
    paths: List[Tuple[str, ...]] = []
    if len(prefix) >= n_cycles:
        return paths
    if not isinstance(subtree, dict):
        return paths

    def walk(node: Any, current: Tuple[str, ...]) -> None:
        if len(current) == n_cycles:
            paths.append(current)
            return
        if not isinstance(node, dict):
            return
        for bb_name, child in node.items():
            next_path = current + (normalize_bb_name(bb_name),)
            if len(next_path) == n_cycles:
                paths.append(next_path)
            elif isinstance(child, dict):
                walk(child, next_path)

    walk(subtree, prefix)
    return paths


def _prefix_pass_stats(
    data: DelCycleTreeData,
    prefix: Tuple[str, ...],
    *,
    color_mode: str,
) -> Tuple[int, int]:
    """Return (passed, total) full products under ``prefix``."""
    subtree = _subtree_at_path(data.tree, prefix)
    if not isinstance(subtree, dict):
        return 0, 0
    passed = 0
    total = 0
    null = data.null_token
    for path in _iter_full_product_paths(subtree, prefix, data.library_cycle_count):
        if any(bb == null for bb in path):
            continue
        total += 1
        if _sequence_passes(data, path, color_mode=color_mode):
            passed += 1
    return passed, total


def _path_fails_pass_cutoff(
    data: DelCycleTreeData,
    path: Tuple[str, ...],
    *,
    is_leaf: bool,
    color_mode: str,
    pass_pct_cutoff: float,
) -> bool:
    """
    True when a node should render as failed (coral).

    Leaf products fail individually. Hubs fail when the pass rate among descendant
    full products is below ``pass_pct_cutoff``. A cutoff of 0 keeps legacy behavior
    (blue when at least one descendant passes).
    """
    if is_leaf and len(path) == data.library_cycle_count:
        return not _sequence_passes(data, path, color_mode=color_mode)
    passed, total = _prefix_pass_stats(data, path, color_mode=color_mode)
    if total == 0:
        return True
    if pass_pct_cutoff <= 0:
        return passed == 0
    return (100.0 * passed / total) < pass_pct_cutoff


def _path_pruned(
    data: DelCycleTreeData,
    path: Tuple[str, ...],
    *,
    is_leaf: bool,
    color_mode: str,
    pass_pct_cutoff: float = 0.0,
) -> bool:
    return _path_fails_pass_cutoff(
        data,
        path,
        is_leaf=is_leaf,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
    )


def _draw_graph(
    graph: nx.Graph,
    positions: Dict[TreeNode, Tuple[float, float]],
    node_sizes: Dict[TreeNode, int],
    data: DelCycleTreeData,
    *,
    color_by_rt: bool,
    color_mode: str,
    pass_pct_cutoff: float,
    figsize: Tuple[float, float],
    view: DelCycleTreeView,
    title: str,
) -> plt.Figure:
    edge_colors = [graph.edges[u, v].get("color", "k") for u, v in graph.edges()]
    structural_hubs = _structural_hub_nodes(graph, view=view)
    labeled_nodes = [
        node
        for node in graph.nodes()
        if _should_label_node(graph, node, view=view)
    ]
    leaf_nodes = [node for node in graph.nodes() if node not in structural_hubs]

    def _node_colors(nodes: List[TreeNode]) -> List[str]:
        return [graph.nodes[node].get("color", ACTIVE_COLOR) for node in nodes]

    def _node_edgecolors(nodes: List[TreeNode]) -> List[str]:
        colors: List[str] = []
        for node in nodes:
            if isinstance(node, tuple) and node[0] == 0:
                colors.append("k")
            elif graph.nodes[node].get("edgecolor"):
                colors.append(graph.nodes[node]["edgecolor"])
            else:
                colors.append(
                    "r"
                    if _node_is_pruned(
                        data,
                        node,
                        color_mode=color_mode,
                        pass_pct_cutoff=pass_pct_cutoff,
                    )
                    else "k"
                )
        return colors

    figure, axis = plt.subplots(figsize=figsize)

    if leaf_nodes:
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=leaf_nodes,
            node_color=_node_colors(leaf_nodes),
            node_size=[node_sizes.get(node, LEAF_NODE_SIZE) for node in leaf_nodes],
            edgecolors=_node_edgecolors(leaf_nodes),
            linewidths=0.5,
            ax=axis,
        )

    nx.draw_networkx_edges(graph, positions, edge_color=edge_colors, width=0.6, ax=axis)

    if structural_hubs:
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=structural_hubs,
            node_color=_node_colors(structural_hubs),
            node_size=[node_sizes.get(node, 300) for node in structural_hubs],
            edgecolors=_node_edgecolors(structural_hubs),
            linewidths=0.8,
            ax=axis,
        )

    for node in sorted(labeled_nodes, key=_node_depth, reverse=True):
        label = _node_label(data, node)
        if label is None:
            continue
        x_coord, y_coord = positions[node]
        depth = _node_depth(node)
        axis.text(
            x_coord,
            y_coord,
            label,
            ha="center",
            va="center",
            fontsize=_label_fontsize(node, figsize=figsize, view=view),
            fontweight="bold",
            zorder=20 + depth,
        )

    if title:
        axis.set_title(title)
    axis.axis("off")
    figure.tight_layout()
    return figure


def _coupling_bb_name(node: TreeNode) -> Optional[str]:
    """
    Building-block name at this hub's coupling depth.

    Matches the legacy notebook ``visualize_full_tree`` extraction:
    depth 1 → BB1 (``node[1]``), depth 2 → BB2 (``node[2]``), etc.
    """
    if not isinstance(node, tuple) or len(node) < 2:
        return None
    depth = int(node[0])
    if depth <= 0:
        return None
    if len(node) <= depth:
        return None
    return normalize_bb_name(node[depth])


def _node_label(data: DelCycleTreeData, node: TreeNode) -> Optional[str]:
    if not isinstance(node, tuple):
        return None
    level = int(node[0])
    # Depth-0 hub is a layout anchor only (null foundation), not a numbered BB.
    if level == 0:
        return None
    bb_name = _coupling_bb_name(node)
    if not bb_name:
        return None
    index = lookup_bb_display_index(
        bb_name,
        data.bb_index_global,
        null_token=data.null_token,
    )
    if index is None:
        return None
    return str(index)


def _node_is_pruned(
    data: DelCycleTreeData,
    node: TreeNode,
    *,
    color_mode: str,
    pass_pct_cutoff: float,
) -> bool:
    if not isinstance(node, tuple) or len(node) < 2:
        return False
    path = tuple(str(part) for part in node[1:])
    if not path:
        return False
    is_leaf = len(path) == data.library_cycle_count
    return _path_fails_pass_cutoff(
        data,
        path,
        is_leaf=is_leaf,
        color_mode=color_mode,
        pass_pct_cutoff=pass_pct_cutoff,
    )


def _active_pruned_tree(data: DelCycleTreeData, color_mode: str) -> Dict[str, Any]:
    if color_mode == COLOR_MODE_PEDIGREE and data.pedigree_passed_by_product:
        return data.pedigree_pruned_tree
    return data.pruned_tree


def _is_pruned(
    data: DelCycleTreeData,
    *,
    bb1_name: str,
    bb2_name: Optional[str] = None,
    leaf_name: Optional[str] = None,
    color_mode: str = COLOR_MODE_NOTEBOOK,
) -> bool:
    pruned_tree = _active_pruned_tree(data, color_mode)
    if bb1_name not in pruned_tree:
        return True
    if bb2_name is None:
        return False
    level2 = pruned_tree.get(bb1_name, {})
    if not isinstance(level2, dict) or bb2_name not in level2:
        return True
    if leaf_name is None:
        return False
    level3 = level2.get(bb2_name, {})
    if isinstance(level3, dict):
        return leaf_name not in level3
    return leaf_name != bb2_name


def _sequence_passes(
    data: DelCycleTreeData,
    positions: Tuple[str, ...],
    *,
    color_mode: str,
) -> bool:
    if color_mode == COLOR_MODE_PEDIGREE and data.pedigree_passed_by_product:
        return bool(data.pedigree_passed_by_product.get(positions, False))
    info = data.verified_sequences.get(positions)
    return bool(info and info.success)


def _verified_rt(
    data: DelCycleTreeData,
    *,
    positions: Tuple[str, ...],
) -> Optional[float]:
    info = data.verified_sequences.get(positions)
    return info.rt if info else None


def _rt_color(rt: Optional[float], full_null_rt: Optional[float]) -> str:
    if rt is None:
        return "lightgray"
    if full_null_rt is None:
        return ACTIVE_COLOR
    rt_diff = rt - full_null_rt
    max_diff = 10.0
    normalized = float(np.clip(rt_diff / max_diff, -1.0, 1.0))
    if normalized > 0:
        return plt.get_cmap("Reds")(normalized)
    return plt.get_cmap("Blues")(-normalized)


def _sunflower_fractal_layout(
    graph: nx.Graph,
    root: TreeNode,
    node_sizes: Dict[TreeNode, int],
) -> Dict[TreeNode, Tuple[float, float]]:
    """Recursive sunflower layout scaled by node depth."""

    def children(node: TreeNode) -> List[TreeNode]:
        return _tree_children(graph, node)

    def sunflower_arrangement(
        count: int,
        min_radius: float,
        max_radius: float,
    ) -> List[Tuple[float, float]]:
        coords: List[Tuple[float, float]] = []
        if count <= 0:
            return coords
        golden_angle = np.pi * (3.0 - np.sqrt(5.0))
        for index in range(count):
            # Offset indexing avoids placing the first child on the parent's east
            # axis (i=0, theta=0), which otherwise appears as a red dot beside hubs.
            t = (index + 0.5) / count
            radius = np.sqrt(t) * (max_radius - min_radius) + min_radius
            theta = (index + 0.5) * golden_angle
            coords.append((radius * np.cos(theta), radius * np.sin(theta)))
        return coords

    def depth_scaling(depth: int) -> float:
        return 0.5**depth

    def recursive_layout(
        node: TreeNode,
        center: np.ndarray,
        available_radius: float,
        depth: int,
    ) -> Dict[TreeNode, Tuple[float, float]]:
        child_nodes = children(node)
        layout: Dict[TreeNode, Tuple[float, float]] = {node: (float(center[0]), float(center[1]))}
        if not child_nodes:
            return layout
        scaling = depth_scaling(depth)
        min_child_radius = available_radius * 0.1 * scaling
        max_child_radius = available_radius * 0.35 * scaling
        child_positions = sunflower_arrangement(
            len(child_nodes),
            min_child_radius,
            max_child_radius,
        )
        for child, offset in zip(child_nodes, child_positions):
            child_center = center + np.array(offset)
            child_available = (max_child_radius - min_child_radius) * scaling
            layout.update(
                recursive_layout(child, child_center, child_available, depth + 1)
            )
        return layout

    raw_layout = recursive_layout(root, np.array([0.0, 0.0]), 1.0, 0)
    max_distance = max(np.linalg.norm(np.array(pos)) for pos in raw_layout.values())
    if max_distance <= 0:
        return raw_layout
    return {
        node: (pos[0] / max_distance, pos[1] / max_distance)
        for node, pos in raw_layout.items()
    }
