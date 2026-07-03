# src/core/library_report_assets.py
"""Render pedigree and DEL-cycle figures for library PDF reports."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt

from src.core.del_cycle_tree import DelCycleTreeData, DelCycleTreeView, render_del_cycle_tree_figure
from src.core.del_cycle_tree.bb_index_scheme import lookup_bb_display_index
from src.core.library_report_models import (
    LibraryReportPedigreeBranchFigure,
    LibraryReportPedigreeFigures,
)
from src.core.pedigree_render import PedigreeTreeRenderOptions, render_pedigree_tree_matplotlib
from src.models.pedigree_result import PedigreeAnalysisResult

logger = logging.getLogger(__name__)

REPORT_DPI = 160
REPORT_TIER_FIGSIZE = (10.0, 10.0)
REPORT_DEL_FULL_FIGSIZE = (11.0, 11.0)
REPORT_DEL_BRANCH_FIGSIZE = (8.0, 8.0)
BRANCHES_PER_GRID_PAGE = 6
BRANCH_GRID_COLS = 2
BRANCH_GRID_ROWS = 3


def session_report_assets_dir(database_path: Path) -> Path:
    """Working directory for report figure PNGs for one database session."""
    from src.core.database_library import sanitize_database_stem
    from src.core.library_metrics_store import get_library_data_dir

    stem = sanitize_database_stem(database_path.stem)
    directory = get_library_data_dir() / ".session" / stem / "report_assets"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_figure(fig: object, path: Path, *, dpi: int = REPORT_DPI) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(  # type: ignore[union-attr]
        str(path),
        format="png",
        bbox_inches="tight",
        facecolor="white",
        dpi=dpi,
    )
    plt.close(fig)  # type: ignore[arg-type]
    return path


def bb_index_reference_rows(
    bb_index_global: Dict[str, int],
    *,
    null_token: str = "",
) -> List[Tuple[int, str]]:
    """Sorted (index, building-block name) pairs for report reference tables."""
    rows = sorted(
        ((index, name) for name, index in bb_index_global.items()),
        key=lambda pair: pair[0],
    )
    null_token = null_token.strip()
    if null_token and not any(index == 0 for index, _ in rows):
        rows.insert(0, (0, null_token))
    return rows


def build_pedigree_tier_report_figure(
    pedigree_result: PedigreeAnalysisResult,
    *,
    tree_opts: PedigreeTreeRenderOptions,
    output_dir: Path,
) -> Tuple[Path, str]:
    """Render the pedigree tier-ring figure for the report."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tier_path = output_dir / "pedigree_tier_ring.png"
    render_pedigree_tree_matplotlib(
        pedigree_result.records,
        tier_path,
        max_display_tier=tree_opts.max_display_tier,
        include_failed=tree_opts.include_failed,
        show_rt=tree_opts.show_rt,
        dpi=REPORT_DPI,
    )
    tier_caption = (
        f"Pedigree tier-ring — max tier {tree_opts.max_display_tier}, "
        f"failed nodes {'shown' if tree_opts.include_failed else 'hidden'}, "
        f"{len(pedigree_result.records):,} nodes."
    )
    return tier_path, tier_caption


def build_del_cycle_report_figures(
    del_data: DelCycleTreeData,
    *,
    del_color_mode: str,
    del_color_by_rt: bool,
    del_pass_pct_cutoff: float = 0.0,
    output_dir: Path,
) -> LibraryReportPedigreeFigures:
    """Render DEL-cycle full tree and BB1 branch plots for the report."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    del_full_path = output_dir / "del_cycle_full.png"
    del_fig = render_del_cycle_tree_figure(
        del_data,
        view=DelCycleTreeView.FULL,
        color_by_rt=del_color_by_rt,
        color_mode=del_color_mode,
        pass_pct_cutoff=del_pass_pct_cutoff,
        figsize=REPORT_DEL_FULL_FIGSIZE,
    )
    _save_figure(del_fig, del_full_path)
    del_full_caption = (
        f"DEL-cycle full tree — {del_data.n_verified:,} RT-verified products, "
        f"RT source: {del_data.rt_source}, threshold {del_data.rt_threshold:g}."
    )

    null = del_data.null_token
    branch_names = [name for name in del_data.bb1_names if name != null]
    branch_figures: List[LibraryReportPedigreeBranchFigure] = []
    for bb1_name in branch_names:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in bb1_name)
        branch_path = output_dir / f"del_branch_{safe}.png"
        try:
            branch_fig = render_del_cycle_tree_figure(
                del_data,
                view=DelCycleTreeView.BRANCH,
                branch_bb1=bb1_name,
                color_by_rt=del_color_by_rt,
                color_mode=del_color_mode,
                pass_pct_cutoff=del_pass_pct_cutoff,
                figsize=REPORT_DEL_BRANCH_FIGSIZE,
                show_figure_title=False,
            )
            _save_figure(branch_fig, branch_path)
            bb1_index = lookup_bb_display_index(
                bb1_name,
                del_data.bb_index_global,
                null_token=del_data.null_token,
            )
            branch_figures.append(
                LibraryReportPedigreeBranchFigure(
                    bb1_name=bb1_name,
                    image_path=branch_path,
                    bb1_index=bb1_index,
                )
            )
        except Exception as exc:
            logger.warning("Could not render DEL branch %s: %s", bb1_name, exc)

    return LibraryReportPedigreeFigures(
        del_full_tree_path=del_full_path,
        del_full_tree_caption=del_full_caption,
        del_branch_figures=branch_figures,
        bb_index_reference=bb_index_reference_rows(
            del_data.bb_index_global,
            null_token=del_data.null_token,
        ),
        null_token=del_data.null_token,
    )


def merge_report_pedigree_figures(
    *parts: Optional[LibraryReportPedigreeFigures],
) -> Optional[LibraryReportPedigreeFigures]:
    """Combine partial pedigree/DEL figure bundles into one report payload."""
    merged = LibraryReportPedigreeFigures()
    for part in parts:
        if part is None:
            continue
        if part.tier_ring_path is not None:
            merged.tier_ring_path = part.tier_ring_path
            merged.tier_ring_caption = part.tier_ring_caption
        if part.del_full_tree_path is not None:
            merged.del_full_tree_path = part.del_full_tree_path
            merged.del_full_tree_caption = part.del_full_tree_caption
        if part.del_branch_figures:
            merged.del_branch_figures = list(part.del_branch_figures)
        if part.bb_index_reference:
            merged.bb_index_reference = list(part.bb_index_reference)
        if part.null_token:
            merged.null_token = part.null_token
    if (
        merged.tier_ring_path is None
        and merged.del_full_tree_path is None
        and not merged.del_branch_figures
    ):
        return None
    return merged


def build_pedigree_report_figures(
    pedigree_result: PedigreeAnalysisResult,
    del_data: DelCycleTreeData,
    *,
    tree_opts: PedigreeTreeRenderOptions,
    del_color_mode: str,
    del_color_by_rt: bool,
    del_pass_pct_cutoff: float = 0.0,
    output_dir: Path,
) -> LibraryReportPedigreeFigures:
    """Render tier-ring, DEL full tree, and all BB1 branch plots for the report."""
    output_dir = Path(output_dir)
    tier_path, tier_caption = build_pedigree_tier_report_figure(
        pedigree_result,
        tree_opts=tree_opts,
        output_dir=output_dir,
    )
    del_part = build_del_cycle_report_figures(
        del_data,
        del_color_mode=del_color_mode,
        del_color_by_rt=del_color_by_rt,
        del_pass_pct_cutoff=del_pass_pct_cutoff,
        output_dir=output_dir,
    )
    return merge_report_pedigree_figures(
        LibraryReportPedigreeFigures(
            tier_ring_path=tier_path,
            tier_ring_caption=tier_caption,
        ),
        del_part,
    ) or LibraryReportPedigreeFigures(
        tier_ring_path=tier_path,
        tier_ring_caption=tier_caption,
    )
