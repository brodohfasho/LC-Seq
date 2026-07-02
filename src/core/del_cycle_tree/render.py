# src/core/del_cycle_tree/render.py
"""Matplotlib rendering for DEL-cycle split trees."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from src.core.del_cycle_tree.models import DelCycleTreeData, DelCycleTreeView, VerifiedSequence

TreeNode = Union[str, Tuple[Any, ...]]
PRUNED_COLOR = "lightcoral"
ACTIVE_COLOR = "powderblue"
ROOT_COLOR = "lightgray"


def render_del_cycle_tree_figure(
    data: DelCycleTreeData,
    *,
    view: DelCycleTreeView,
    branch_bb1: Optional[str] = None,
    color_by_rt: bool = False,
    figsize: Tuple[float, float] = (12.0, 12.0),
) -> plt.Figure:
    """Build a matplotlib figure for the requested DEL-cycle tree view."""
    if view == DelCycleTreeView.FULL:
        return _render_full_tree(data, color_by_rt=color_by_rt, figsize=figsize)
    if not branch_bb1:
        raise ValueError("branch_bb1 is required for branch view")
    if branch_bb1 not in data.tree:
        raise ValueError(f"BB1 branch not found: {branch_bb1}")
    return _render_branch_tree(
        data,
        branch_bb1=branch_bb1,
        color_by_rt=color_by_rt,
        figsize=figsize,
    )


def _render_full_tree(
    data: DelCycleTreeData,
    *,
    color_by_rt: bool,
    figsize: Tuple[float, float],
) -> plt.Figure:
    """Root → BB1 → BB2 overview (deepest cycle omitted, matching legacy notebook)."""
    n_cycles = data.library_cycle_count
    if n_cycles < 2:
        raise ValueError("DEL-cycle tree requires at least two coupling cycles")

    graph = nx.Graph()
    root: TreeNode = (0, data.null_token)
    graph.add_node(root, color=ROOT_COLOR, edgecolor="k")
    node_sizes: Dict[TreeNode, int] = {root: 700}

    for bb1_name in data.tree.keys():
        bb1_node: TreeNode = (1, bb1_name)
        pruned = _is_pruned(data, bb1_name=bb1_name)
        graph.add_node(
            bb1_node,
            color=PRUNED_COLOR if pruned else ACTIVE_COLOR,
            edgecolor="r" if pruned else "k",
        )
        graph.add_edge(root, bb1_node, color="r" if pruned else "k")
        node_sizes[bb1_node] = 500

        bb2_dict = data.tree.get(bb1_name, {})
        if not isinstance(bb2_dict, dict):
            continue
        for bb2_name in bb2_dict.keys():
            bb2_node: TreeNode = (2, bb1_name, bb2_name)
            pruned_bb2 = _is_pruned(data, bb1_name=bb1_name, bb2_name=bb2_name)
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
            node_sizes[bb2_node] = 300

    positions = _sunflower_fractal_layout(graph, root, node_sizes)
    return _draw_graph(
        graph,
        positions,
        node_sizes,
        data,
        color_by_rt=color_by_rt,
        figsize=figsize,
        title="DEL-cycle tree (full)",
    )


def _render_branch_tree(
    data: DelCycleTreeData,
    *,
    branch_bb1: str,
    color_by_rt: bool,
    figsize: Tuple[float, float],
) -> plt.Figure:
    """BB1 → BB2 → … branch for one BB1 root."""
    graph = nx.Graph()
    bb1_node: TreeNode = (1, branch_bb1)
    pruned_bb1 = _is_pruned(data, bb1_name=branch_bb1)
    graph.add_node(
        bb1_node,
        color=PRUNED_COLOR if pruned_bb1 else ACTIVE_COLOR,
    )
    node_sizes: Dict[TreeNode, int] = {bb1_node: 700}

    subtree = data.tree.get(branch_bb1, {})
    if isinstance(subtree, dict):
        _add_branch_nodes(
            graph,
            node_sizes,
            data,
            parent_node=bb1_node,
            subtree=subtree,
            path=(branch_bb1,),
            depth=2,
            color_by_rt=color_by_rt,
        )

    positions = _sunflower_fractal_layout(graph, bb1_node, node_sizes)
    return _draw_graph(
        graph,
        positions,
        node_sizes,
        data,
        color_by_rt=color_by_rt,
        figsize=figsize,
        title=f"DEL-cycle branch — {branch_bb1}",
    )


def _add_branch_nodes(
    graph: nx.Graph,
    node_sizes: Dict[TreeNode, int],
    data: DelCycleTreeData,
    *,
    parent_node: TreeNode,
    subtree: Dict[str, Any],
    path: Tuple[str, ...],
    depth: int,
    color_by_rt: bool,
) -> None:
    """Recursively add nodes for one BB1 branch down to product leaves."""
    n_cycles = data.library_cycle_count
    size_by_depth = {2: 500, 3: 400, 4: 300}

    for bb_name, child in subtree.items():
        current_path = path + (bb_name,)
        node: TreeNode = (depth,) + current_path
        is_leaf = depth >= n_cycles or not isinstance(child, dict)
        pruned = _path_pruned(data, current_path, is_leaf=is_leaf)

        if color_by_rt and is_leaf and not pruned and len(current_path) == n_cycles:
            node_color = _rt_color(
                _verified_rt(data, positions=current_path),
                data.full_null_rt,
            )
        else:
            node_color = PRUNED_COLOR if pruned else ACTIVE_COLOR

        graph.add_node(node, color=node_color)
        graph.add_edge(parent_node, node, color="r" if pruned else "k")
        node_sizes[node] = size_by_depth.get(depth, 300)

        if isinstance(child, dict) and depth < n_cycles:
            _add_branch_nodes(
                graph,
                node_sizes,
                data,
                parent_node=node,
                subtree=child,
                path=current_path,
                depth=depth + 1,
                color_by_rt=color_by_rt,
            )


def _path_pruned(
    data: DelCycleTreeData,
    path: Tuple[str, ...],
    *,
    is_leaf: bool,
) -> bool:
    if len(path) == 1:
        return _is_pruned(data, bb1_name=path[0])
    if len(path) == 2:
        return _is_pruned(data, bb1_name=path[0], bb2_name=path[1])
    if is_leaf and len(path) == data.library_cycle_count:
        return not _sequence_verified(data, path)
    if len(path) >= 3:
        return _is_pruned(
            data,
            bb1_name=path[0],
            bb2_name=path[1],
            leaf_name=path[2],
        )
    return False


def _draw_graph(
    graph: nx.Graph,
    positions: Dict[TreeNode, Tuple[float, float]],
    node_sizes: Dict[TreeNode, int],
    data: DelCycleTreeData,
    *,
    color_by_rt: bool,
    figsize: Tuple[float, float],
    title: str,
) -> plt.Figure:
    edge_colors = [graph.edges[u, v].get("color", "k") for u, v in graph.edges()]
    node_colors = [graph.nodes[node].get("color", ACTIVE_COLOR) for node in graph.nodes()]
    node_edgecolors = []
    for node in graph.nodes():
        if isinstance(node, tuple) and node[0] == 0:
            node_edgecolors.append("k")
        elif graph.nodes[node].get("edgecolor"):
            node_edgecolors.append(graph.nodes[node]["edgecolor"])
        else:
            node_edgecolors.append(
                "r" if _node_is_pruned(data, node) else "k"
            )

    figure, _axis = plt.subplots(figsize=figsize)
    nx.draw_networkx_nodes(
        graph,
        positions,
        node_color=node_colors,
        node_size=[node_sizes.get(node, 300) for node in graph.nodes()],
        edgecolors=node_edgecolors,
        linewidths=0.6,
    )
    nx.draw_networkx_edges(graph, positions, edge_color=edge_colors, width=0.6)

    for node, (x_coord, y_coord) in positions.items():
        label = _node_label(data, node)
        if label is None:
            continue
        fontsize = 12 if (isinstance(node, tuple) and node[0] <= 1) else 10
        if isinstance(node, tuple) and node[0] >= 3:
            fontsize = 8
        plt.text(
            x_coord,
            y_coord,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight="bold",
        )

    plt.title(title)
    plt.axis("off")
    figure.tight_layout()
    return figure


def _node_label(data: DelCycleTreeData, node: TreeNode) -> Optional[str]:
    if not isinstance(node, tuple):
        return None
    level = int(node[0])
    if level == 0:
        return "0"
    if level - 1 >= len(data.bb_index_by_level):
        return None
    if level >= len(node):
        return None
    index_map = data.bb_index_by_level[level - 1]
    bb_name = str(node[level])
    label = index_map.get(bb_name)
    return str(label) if label is not None else None


def _node_is_pruned(data: DelCycleTreeData, node: TreeNode) -> bool:
    if not isinstance(node, tuple):
        return False
    level = int(node[0])
    if level == 1:
        return _is_pruned(data, bb1_name=str(node[1]))
    if level == 2 and len(node) >= 3:
        return _is_pruned(data, bb1_name=str(node[1]), bb2_name=str(node[2]))
    if level >= 3:
        parts = tuple(str(part) for part in node[1:])
        if len(parts) == 3:
            return _is_pruned(
                data,
                bb1_name=parts[0],
                bb2_name=parts[1],
                leaf_name=parts[2],
            )
        if len(parts) == 4:
            return not _sequence_verified(data, parts)
    return False


def _is_pruned(
    data: DelCycleTreeData,
    *,
    bb1_name: str,
    bb2_name: Optional[str] = None,
    leaf_name: Optional[str] = None,
) -> bool:
    if bb1_name not in data.pruned_tree:
        return True
    if bb2_name is None:
        return False
    level2 = data.pruned_tree.get(bb1_name, {})
    if not isinstance(level2, dict) or bb2_name not in level2:
        return True
    if leaf_name is None:
        return False
    level3 = level2.get(bb2_name, {})
    if isinstance(level3, dict):
        return leaf_name not in level3
    return leaf_name != bb2_name


def _sequence_verified(data: DelCycleTreeData, positions: Tuple[str, ...]) -> bool:
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

    def node_depth(node: TreeNode) -> int:
        if isinstance(node, tuple):
            return int(node[0])
        return 0

    def children(node: TreeNode) -> List[TreeNode]:
        return [
            neighbor
            for neighbor in graph.neighbors(node)
            if node_depth(neighbor) > node_depth(node)
        ]

    def sunflower_arrangement(
        count: int,
        min_radius: float,
        max_radius: float,
    ) -> List[Tuple[float, float]]:
        coords: List[Tuple[float, float]] = []
        golden_angle = np.pi * (3.0 - np.sqrt(5.0))
        for index in range(count):
            radius = np.sqrt(index / max(count, 1)) * (max_radius - min_radius) + min_radius
            theta = index * golden_angle
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
