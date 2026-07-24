# src/core/pedigree_render.py
"""
Render pruned pedigree split-tree figures.

Uses Graphviz (``lcseq.render.render_pruned_tree``) when the ``dot`` binary is
available; otherwise falls back to a matplotlib tier-ring layout so tree images
still appear without a system Graphviz install.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from src.models.pedigree_result import PedigreeNodeRecord

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


def _report_progress(
    callback: Optional[ProgressCallback],
    fraction: float,
    status: str,
) -> None:
    if callback is not None:
        callback(min(1.0, max(0.0, fraction)), status)

# Above this visible-node count, default to passed-only tree (fewer crossing edges).
AUTO_PASSED_ONLY_NODE_THRESHOLD = 500

_COLOR_ROOT = "#d0d0d0"
_COLOR_CLASS = "#cfe8cf"
_COLOR_COMPOUND = "#a6d8a6"
_COLOR_FAILED = "#e57373"
_COLOR_INSUFFICIENT_DATA = "#fce8a3"

_WINDOWS_DOT_CANDIDATES = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Graphviz" / "bin" / "dot.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Graphviz"
    / "bin"
    / "dot.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Graphviz" / "bin" / "dot.exe",
)


@dataclass(frozen=True)
class PedigreeTreeRenderResult:
    """Output path and renderer used for a pedigree tree image."""

    path: Path
    engine: str
    detail: str = ""


@dataclass(frozen=True)
class PedigreeTreeRenderOptions:
    """User-facing knobs for split-tree figure layout."""

    max_display_tier: Optional[int]
    include_failed: bool = True
    show_rt: bool = True


def max_tier_in_records(records: Sequence[PedigreeNodeRecord]) -> int:
    """Highest tier index present in pedigree node records."""
    if not records:
        return 0
    return max(record.tier for record in records)


def count_visible_pedigree_nodes(
    records: Sequence[PedigreeNodeRecord],
    *,
    include_failed: bool = True,
    max_display_tier: Optional[int] = None,
) -> int:
    """Count nodes that would appear in a tree figure with the given options."""
    return len(
        visible_pedigree_nodes(
            records,
            include_failed=include_failed,
            max_display_tier=max_display_tier,
        )
    )


def suggest_include_failed(
    records: Sequence[PedigreeNodeRecord],
    *,
    max_display_tier: Optional[int],
    threshold: int = AUTO_PASSED_ONLY_NODE_THRESHOLD,
) -> bool:
    """Return False when the full trim view would exceed ``threshold`` visible nodes."""
    with_failed = count_visible_pedigree_nodes(
        records,
        include_failed=True,
        max_display_tier=max_display_tier,
    )
    return with_failed <= threshold


def default_max_display_tier_for_tree(
    library_cycle_count: int,
    records: Sequence[PedigreeNodeRecord],
) -> int:
    """Default max tier for tree display (hide final compound ring when possible)."""
    if library_cycle_count > 0:
        return max(0, library_cycle_count - 1)
    return max_tier_in_records(records)


def build_default_tree_render_options(
    records: Sequence[PedigreeNodeRecord],
    *,
    library_cycle_count: int,
    auto_passed_only: bool = True,
) -> PedigreeTreeRenderOptions:
    """Initial tree display options after a pedigree run."""
    max_tier = default_max_display_tier_for_tree(library_cycle_count, records)
    include_failed = True
    if auto_passed_only:
        include_failed = suggest_include_failed(records, max_display_tier=max_tier)
    return PedigreeTreeRenderOptions(
        max_display_tier=max_tier,
        include_failed=include_failed,
        show_rt=True,
    )


def find_graphviz_dot() -> Optional[Path]:
    """Locate the Graphviz ``dot`` executable on PATH or common install dirs."""
    found = shutil.which("dot")
    if found:
        return Path(found)
    for candidate in _WINDOWS_DOT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def configure_graphviz() -> bool:
    """
    Point the Python graphviz package at ``dot`` and prepend its bin dir to PATH.

    Supports graphviz ``<0.21`` (``set_graphviz_dot``) and ``0.21+``
    (``backend.DOT_BINARY``). Returns True when configuration succeeded.
    """
    dot = find_graphviz_dot()
    if dot is None:
        return False
    try:
        import graphviz

        if hasattr(graphviz, "set_graphviz_dot"):
            graphviz.set_graphviz_dot(str(dot))
        else:
            import graphviz.backend as graphviz_backend

            graphviz_backend.DOT_BINARY = Path(dot)
    except Exception as exc:
        logger.warning("Could not configure graphviz Python bindings: %s", exc)
        return False
    bin_dir = str(dot.parent)
    path_env = os.environ.get("PATH", "")
    if bin_dir.lower() not in path_env.lower():
        os.environ["PATH"] = bin_dir + os.pathsep + path_env
    return True


def graphviz_available() -> bool:
    """Return True when Graphviz can be used for rendering."""
    try:
        import graphviz  # noqa: F401
    except ImportError:
        return False
    return find_graphviz_dot() is not None


def graphviz_missing_banner() -> str:
    """Inline banner text when only the matplotlib fallback is available."""
    return (
        "Graphviz not found — showing matplotlib tier-ring preview. "
        "Install Graphviz for higher-quality pedigree tree layout "
        "(see dev/DEVELOPER_SETUP.md)."
    )


def graphviz_missing_export_prompt() -> str:
    """Yes/No dialog body when exporting a tree without Graphviz."""
    return (
        "Graphviz is not installed. Export will use the matplotlib tier-ring "
        "layout instead of the native Graphviz pedigree tree.\n\n"
        "Install Graphviz and ensure ``dot`` is on PATH for the preferred layout "
        "(see dev/DEVELOPER_SETUP.md).\n\n"
        "Continue with the matplotlib export?"
    )


def graphviz_install_hint() -> str:
    """Short user-facing hint when only the matplotlib fallback is available."""
    if graphviz_available():
        return ""
    return graphviz_missing_banner()


def filter_records_for_display(
    records: Sequence[PedigreeNodeRecord],
    *,
    max_display_tier: Optional[int] = None,
) -> List[PedigreeNodeRecord]:
    """Optionally hide tiers above ``max_display_tier`` (e.g. final compound cluster)."""
    if max_display_tier is None:
        return list(records)
    return [record for record in records if record.tier <= max_display_tier]


def visible_pedigree_nodes(
    records: Sequence[PedigreeNodeRecord],
    *,
    include_failed: bool = True,
    max_display_tier: Optional[int] = None,
) -> Dict[str, PedigreeNodeRecord]:
    """Nodes shown in tree figures (matches ``lcseq.render`` visibility rules)."""
    filtered = filter_records_for_display(records, max_display_tier=max_display_tier)
    return {
        record.id: record
        for record in filtered
        if record.passed or (include_failed and record.evaluated)
    }


def _node_color(record: PedigreeNodeRecord) -> str:
    if record.tier == 0:
        return _COLOR_ROOT
    if record.passed:
        return _COLOR_COMPOUND if record.kind == "compound" else _COLOR_CLASS
    if record.insufficient_data:
        return _COLOR_INSUFFICIENT_DATA
    return _COLOR_FAILED


def _chosen_rt(record: PedigreeNodeRecord) -> Optional[float]:
    if record.bayesian_pick is not None:
        return record.bayesian_pick
    if record.score_test_rt is not None:
        return record.score_test_rt
    picks = record.initial_most_significant_picks
    return float(picks[0]) if picks else None


def _node_label(record: PedigreeNodeRecord, *, show_rt: bool) -> str:
    label = record.label
    if show_rt and record.passed:
        chosen = _chosen_rt(record)
        if chosen is not None:
            label = f"{record.label}\nrt={chosen:.1f}"
    return label


def render_pedigree_tree_graphviz(
    records: Sequence[PedigreeNodeRecord],
    out_path: Path,
    *,
    fmt: str = "png",
    max_display_tier: Optional[int] = None,
    include_failed: bool = True,
    show_rt: bool = True,
) -> Path:
    """Render via ``lcseq.render.render_pruned_tree`` (requires Graphviz)."""
    if not configure_graphviz():
        raise RuntimeError("Graphviz dot executable is not available.")

    from lcseq.render import render_pruned_tree

    visible = list(
        visible_pedigree_nodes(
            records,
            include_failed=include_failed,
            max_display_tier=max_display_tier,
        ).values()
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stem = out_path.with_suffix("")
    rendered = render_pruned_tree(
        visible,
        stem,
        fmt=fmt,
        layout="twopi",
        include_failed=include_failed,
        show_rt=show_rt,
        keep_dot=False,
    )
    return Path(rendered)


def build_pedigree_tree_matplotlib_figure(
    records: Sequence[PedigreeNodeRecord],
    *,
    max_display_tier: Optional[int] = None,
    include_failed: bool = True,
    show_rt: bool = True,
    dpi: int = 150,
    progress_callback: Optional[ProgressCallback] = None,
) -> Figure:
    """
    Matplotlib tier-ring figure for in-app pan/zoom (no Graphviz required).

    Places each tier on a concentric ring (root at centre), matching the
    split-tree colour scheme used by the Rust renderer.
    """
    _report_progress(progress_callback, 0.05, "Filtering visible pedigree nodes…")
    visible = visible_pedigree_nodes(
        records,
        include_failed=include_failed,
        max_display_tier=max_display_tier,
    )
    if not visible:
        raise ValueError("No pedigree nodes to render.")

    _report_progress(progress_callback, 0.12, "Computing concentric ring layout…")
    by_tier: Dict[int, List[PedigreeNodeRecord]] = defaultdict(list)
    for record in visible.values():
        by_tier[record.tier].append(record)

    positions: Dict[str, Tuple[float, float]] = {}
    max_tier = max(by_tier)
    ring_gap = 1.35
    for tier in sorted(by_tier):
        nodes = sorted(by_tier[tier], key=lambda r: r.label.lower())
        count = len(nodes)
        radius = 0.15 if tier == 0 and max_tier == 0 else 0.35 + tier * ring_gap
        for index, node in enumerate(nodes):
            if count == 1:
                angle = -math.pi / 2
            else:
                angle = (2.0 * math.pi * index / count) - (math.pi / 2)
            positions[node.id] = (radius * math.cos(angle), radius * math.sin(angle))

    node_count = len(visible)
    fig_size = min(24.0, max(8.0, 6.0 + math.sqrt(node_count) * 0.12))
    fig, ax = plt.subplots(figsize=(fig_size, fig_size), dpi=dpi)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("white")

    visible_list = list(visible.values())
    edge_total = max(len(visible_list), 1)
    edge_step = max(1, edge_total // 40)
    _report_progress(progress_callback, 0.25, f"Drawing edges (0/{edge_total:,})…")
    for index, record in enumerate(visible_list):
        for parent_id in record.parent_ids:
            if parent_id not in positions:
                continue
            x1, y1 = positions[parent_id]
            x2, y2 = positions[record.id]
            ax.plot(
                [x1, x2],
                [y1, y2],
                color="#888888",
                linewidth=0.35 if node_count > 500 else 0.6,
                alpha=0.7,
                zorder=1,
            )
        if index % edge_step == 0 or index + 1 == edge_total:
            fraction = 0.25 + 0.40 * ((index + 1) / edge_total)
            _report_progress(
                progress_callback,
                fraction,
                f"Drawing edges ({index + 1:,}/{edge_total:,})…",
            )

    _report_progress(progress_callback, 0.70, "Drawing nodes…")
    xs: List[float] = []
    ys: List[float] = []
    colors: List[str] = []
    sizes: List[float] = []
    for record in visible_list:
        x, y = positions[record.id]
        xs.append(x)
        ys.append(y)
        colors.append(_node_color(record))
        if node_count > 5000:
            sizes.append(4.0)
        elif node_count > 500:
            sizes.append(10.0)
        elif record.tier == 0:
            sizes.append(80.0)
        else:
            sizes.append(36.0)

    ax.scatter(xs, ys, c=colors, s=sizes, edgecolors="#333333", linewidths=0.2, zorder=2)

    label_limit = 250
    if node_count <= label_limit:
        _report_progress(progress_callback, 0.82, "Adding node labels…")
        for record in visible_list:
            x, y = positions[record.id]
            text = _node_label(record, show_rt=show_rt)
            fontsize = 5 if node_count > 80 else 7
            ax.text(
                x,
                y,
                text,
                fontsize=fontsize,
                ha="center",
                va="center",
                zorder=3,
                clip_on=True,
            )

    _report_progress(progress_callback, 0.92, "Finishing figure…")
    legend_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_ROOT, markersize=8, label="root"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_CLASS, markersize=8, label="passed class"),
        plt.Line2D(
            [0], [0], marker="o", color="w", markerfacecolor=_COLOR_COMPOUND, markersize=8, label="passed compound"
        ),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=_COLOR_FAILED, markersize=8, label="failed"),
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=_COLOR_INSUFFICIENT_DATA,
            markersize=8,
            label="insufficient data",
        ),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper left",
        fontsize=7,
        framealpha=0.9,
        borderpad=0.6,
    )
    ax.set_title(
        f"Pedigree split-tree ({node_count:,} nodes, matplotlib preview)",
        fontsize=11,
        pad=12,
    )
    _report_progress(progress_callback, 1.0, "Pedigree figure ready…")
    return fig


def build_pedigree_tree_raster_figure(image_path: Path) -> Figure:
    """
    Wrap a rendered tree image (e.g. Graphviz PNG) for matplotlib pan/zoom.

    The on-disk export is raster PNG; zoom reveals pixel detail but supports navigation.
    """
    from PIL import Image

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Pedigree tree image not found: {path}")

    img = Image.open(path)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    arr = np.asarray(img)
    height, width = arr.shape[0], arr.shape[1]
    max_inches = 14.0
    aspect = width / height if height else 1.0
    if aspect >= 1.0:
        fig_w = min(max_inches, max(6.0, width / 100.0))
        fig_h = max(6.0, fig_w / aspect)
    else:
        fig_h = min(max_inches, max(6.0, height / 100.0))
        fig_w = max(6.0, fig_h * aspect)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)
    ax.imshow(arr, interpolation="nearest")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_title("Pedigree split-tree (Graphviz PNG — use toolbar to pan/zoom)", fontsize=11, pad=8)
    return fig


def build_pedigree_tree_preview_figure(
    records: Sequence[PedigreeNodeRecord],
    image_path: Optional[Path],
    *,
    render_engine: Optional[str] = None,
    max_display_tier: Optional[int] = None,
    include_failed: bool = True,
    show_rt: bool = True,
) -> Figure:
    """
    Build an interactive matplotlib figure for the pedigree tab preview.

    The in-app preview always uses the matplotlib tier-ring renderer so tree
    display options (include failed, max tier, show RT) apply immediately.
    ``image_path`` / ``render_engine`` are ignored here; Graphviz exports remain
    available via Export tree and the saved session PNG.
    """
    _ = image_path, render_engine
    return build_pedigree_tree_matplotlib_figure(
        records,
        max_display_tier=max_display_tier,
        include_failed=include_failed,
        show_rt=show_rt,
    )


def render_pedigree_tree_matplotlib(
    records: Sequence[PedigreeNodeRecord],
    out_path: Path,
    *,
    fmt: str = "png",
    max_display_tier: Optional[int] = None,
    include_failed: bool = True,
    show_rt: bool = True,
    dpi: int = 150,
    progress_callback: Optional[ProgressCallback] = None,
) -> Path:
    """Save the matplotlib tier-ring pedigree tree to disk."""

    def build_progress(fraction: float, status: str) -> None:
        _report_progress(progress_callback, 0.05 + 0.80 * fraction, status)

    fig = build_pedigree_tree_matplotlib_figure(
        records,
        max_display_tier=max_display_tier,
        include_failed=include_failed,
        show_rt=show_rt,
        dpi=dpi,
        progress_callback=build_progress if progress_callback is not None else None,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image_fmt = (fmt or "png").lower().lstrip(".")
    if image_fmt not in ("png", "pdf", "svg"):
        image_fmt = "png"
    if out_path.suffix.lower() != f".{image_fmt}":
        out_path = out_path.with_suffix(f".{image_fmt}")
    _report_progress(progress_callback, 0.90, "Saving pedigree image…")
    fig.savefig(out_path, format=image_fmt, bbox_inches="tight", facecolor="white", dpi=dpi)
    plt.close(fig)
    _report_progress(progress_callback, 1.0, "Pedigree image saved…")
    return out_path


def render_pedigree_tree(
    records: Sequence[PedigreeNodeRecord],
    out_path: Path,
    *,
    fmt: str = "png",
    max_display_tier: Optional[int] = None,
    include_failed: bool = True,
    show_rt: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> PedigreeTreeRenderResult:
    """
    Render a pedigree tree image, preferring Graphviz when available.

    Always attempts rendering (matplotlib fallback when Graphviz is missing).
    """
    out_path = Path(out_path)
    _report_progress(progress_callback, 0.02, "Selecting pedigree layout engine…")
    if configure_graphviz():
        try:
            _report_progress(
                progress_callback,
                0.12,
                "Laying out pedigree with Graphviz (this can take a while)…",
            )
            rendered = render_pedigree_tree_graphviz(
                records,
                out_path,
                fmt=fmt,
                max_display_tier=max_display_tier,
                include_failed=include_failed,
                show_rt=show_rt,
            )
            _report_progress(progress_callback, 1.0, "Graphviz pedigree image ready…")
            return PedigreeTreeRenderResult(
                path=rendered,
                engine="graphviz",
                detail="Rendered with Graphviz (twopi layout).",
            )
        except Exception as exc:
            logger.warning(
                "Graphviz pedigree render failed (%s); using matplotlib fallback.",
                exc,
                exc_info=True,
            )
            _report_progress(
                progress_callback,
                0.15,
                "Graphviz failed — falling back to matplotlib preview…",
            )

    rendered = render_pedigree_tree_matplotlib(
        records,
        out_path,
        fmt=fmt,
        max_display_tier=max_display_tier,
        include_failed=include_failed,
        show_rt=show_rt,
        progress_callback=progress_callback,
    )
    detail = graphviz_install_hint()
    return PedigreeTreeRenderResult(
        path=rendered,
        engine="matplotlib",
        detail=detail or "Rendered with matplotlib tier-ring preview.",
    )
