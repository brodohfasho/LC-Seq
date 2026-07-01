# src/core/lineage_render.py
"""
Matplotlib rendering for single-compound lineage analysis panels.

Values come from Rust ``diagnose_class`` via :mod:`pedigree_backend` — no Python
re-implementation of consensus logic.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from src.core.pedigree_adapter import Chromatogram
from src.core.pedigree_backend import get_pedigree_backend
from src.core.plot_text import configure_plot_fonts, sanitize_plot_text
from src.models.pedigree_result import LineageAnalysisResult, LineagePanel

_LINEAGE_LAYOUT_ATTR = "_lineage_export_layout"


def _legend_handles() -> Tuple[list, list]:
    handles = [
        Line2D([0], [0], color="gray", alpha=0.55, linewidth=1.0, label="rep trace"),
        Line2D(
            [0],
            [0],
            color="gray",
            alpha=0.25,
            linewidth=0.7,
            linestyle=":",
            label="excluded rep (no signal)",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markersize=5,
            color="gray",
            markeredgecolor="black",
            markeredgewidth=0.4,
            label="NB-significant peak",
        ),
        Line2D(
            [0],
            [0],
            marker="<",
            linestyle="none",
            markersize=10,
            markerfacecolor="none",
            markeredgecolor="black",
            label="initial earliest pick",
        ),
        Line2D(
            [0],
            [0],
            marker="*",
            linestyle="none",
            markersize=12,
            markerfacecolor="none",
            markeredgecolor="black",
            label="initial most-significant pick",
        ),
        Line2D(
            [0],
            [0],
            marker="D",
            linestyle="none",
            markersize=8,
            markerfacecolor="none",
            markeredgecolor="black",
            label="initial democratic pick",
        ),
        Line2D(
            [0],
            [0],
            marker="s",
            linestyle="none",
            markersize=7,
            markerfacecolor="gray",
            markeredgecolor="black",
            markeredgewidth=1.5,
            label="bayesian-refined pick (supporting)",
        ),
        Line2D(
            [0],
            [0],
            color="red",
            linestyle=":",
            linewidth=1.5,
            label="effective_threshold",
        ),
        Patch(facecolor="red", alpha=0.07, label="parent-exclusion (±tol)"),
        Line2D(
            [0],
            [0],
            color="#2ca02c",
            linewidth=2.0,
            label="score_test_rt / chosen rt",
        ),
        Patch(facecolor="#2ca02c", alpha=0.10, label="score_test_rt ± SE"),
        Line2D(
            [0],
            [0],
            color="#9467bd",
            linestyle="--",
            linewidth=2.5,
            label="bayesian_pick",
        ),
        Patch(facecolor="#9467bd", alpha=0.10, label="bayesian_pick ± FWHM"),
    ]
    return handles, [h.get_label() for h in handles]


def _write_panel_header(
    header_ax: plt.Axes,
    *,
    heading: str,
    status: str,
    stats_line: str,
) -> None:
    """Render tier label and stats in a dedicated strip above the chromatogram."""
    header_ax.set_axis_off()
    header_ax.text(
        0.0,
        0.72,
        sanitize_plot_text(heading),
        fontsize=10,
        fontweight="bold",
        va="top",
        ha="left",
        transform=header_ax.transAxes,
    )
    header_ax.text(
        0.0,
        0.08,
        sanitize_plot_text(f"{status}  |  {stats_line}"),
        fontsize=8.5,
        va="bottom",
        ha="left",
        transform=header_ax.transAxes,
        color="#444444",
    )


def plot_class_panel(
    replicates: Sequence[Chromatogram],
    *,
    effective_threshold: float = 0.0,
    tolerance: float,
    alpha: float,
    title: str = "",
    ax: plt.Axes,
    header_ax: Optional[plt.Axes] = None,
    xlim: Optional[Tuple[float, float]] = None,
    time_unit: str = "seconds",
    show_xlabel: bool = True,
) -> None:
    """Draw one equivalence-class panel on ``ax``."""
    backend = get_pedigree_backend()
    rep_list = [
        (np.asarray(rt, dtype=np.float64), np.asarray(intensity, dtype=np.float64))
        for rt, intensity in replicates
    ]
    diag = backend.diagnose_class(rep_list, effective_threshold, tolerance, alpha)

    import lcseq

    n_rep = len(rep_list)
    cmap = plt.get_cmap("tab10" if n_rep <= 10 else "tab20")
    excluded = set(diag.replicates_with_no_signal)

    for i, (rt, intensity) in enumerate(rep_list):
        if rt.size == 0:
            continue
        color = cmap(i % cmap.N)
        is_excluded = i in excluded
        ax.plot(
            rt,
            intensity,
            color=color,
            alpha=0.25 if is_excluded else 0.55,
            linewidth=0.7 if is_excluded else 1.0,
            linestyle=":" if is_excluded else "-",
        )
        if is_excluded:
            continue
        peaks = lcseq.find_peaks(rt, intensity, alpha)
        if peaks:
            ax.plot(
                [p.rt for p in peaks],
                [p.intensity for p in peaks],
                "o",
                color=color,
                markersize=5,
                alpha=0.7,
                markeredgecolor="black",
                markeredgewidth=0.4,
            )

        def _y_at(rt_val: float) -> float:
            return next((p.intensity for p in peaks if abs(p.rt - rt_val) < 1e-9), 0.0)

        earliest = (
            diag.initial_earliest_picks[i] if i < len(diag.initial_earliest_picks) else None
        )
        if earliest is not None:
            ax.plot(
                earliest,
                _y_at(earliest),
                "<",
                markersize=12,
                markerfacecolor="none",
                markeredgecolor=color,
                markeredgewidth=1.6,
                alpha=0.85,
            )
        most_sig = (
            diag.initial_most_significant_picks[i]
            if i < len(diag.initial_most_significant_picks)
            else None
        )
        if most_sig is not None:
            ax.plot(
                most_sig,
                _y_at(most_sig),
                "*",
                markersize=16,
                markerfacecolor="none",
                markeredgecolor=color,
                markeredgewidth=1.6,
                alpha=0.85,
            )
        democratic = (
            diag.initial_democratic_picks[i]
            if i < len(diag.initial_democratic_picks)
            else None
        )
        if democratic is not None:
            ax.plot(
                democratic,
                _y_at(democratic),
                "D",
                markersize=10,
                markerfacecolor="none",
                markeredgecolor=color,
                markeredgewidth=1.6,
                alpha=0.85,
            )
        refined = (
            diag.bayesian_refined_picks[i] if i < len(diag.bayesian_refined_picks) else None
        )
        if refined is not None:
            y_refined = float(np.interp(refined, rt, intensity))
            in_support = i in diag.bayesian_supporting_replicates
            ax.plot(
                refined,
                y_refined,
                "s",
                color=color,
                markersize=8,
                markeredgecolor="black",
                markeredgewidth=1.5 if in_support else 0.4,
                alpha=0.95,
            )

    ax.axvspan(
        effective_threshold - tolerance,
        effective_threshold + tolerance,
        color="red",
        alpha=0.07,
    )
    ax.axvline(effective_threshold, color="red", linestyle=":", linewidth=1.5)

    if diag.initial_democratic_position is not None:
        y_min, y_max = ax.get_ylim()
        tick_y = y_min + 0.02 * (y_max - y_min)
        ax.plot(
            diag.initial_democratic_position,
            tick_y,
            "|",
            color="black",
            markersize=14,
            markeredgewidth=2.0,
        )

    is_multi_rep = diag.score_test_rt is not None and diag.bayesian_pick is not None
    single_rep_chosen: Optional[float] = None

    if diag.score_test_rt is not None:
        if (
            is_multi_rep
            and diag.score_test_rt_se is not None
            and diag.score_test_rt_se > 0
        ):
            ax.axvspan(
                diag.score_test_rt - diag.score_test_rt_se,
                diag.score_test_rt + diag.score_test_rt_se,
                color="#2ca02c",
                alpha=0.10,
            )
        ax.axvline(diag.score_test_rt, color="#2ca02c", linewidth=2.0)
    elif diag.initial_most_significant_picks:
        single_rep_chosen = diag.initial_most_significant_picks[0]
        if single_rep_chosen is not None:
            ax.axvline(single_rep_chosen, color="#2ca02c", linewidth=2.0)

    if is_multi_rep and diag.bayesian_pick is not None:
        match_window = 2.3548 * tolerance
        ax.axvspan(
            diag.bayesian_pick - match_window,
            diag.bayesian_pick + match_window,
            color="#9467bd",
            alpha=0.10,
        )
        ax.axvline(diag.bayesian_pick, color="#9467bd", linestyle="--", linewidth=2.5)

    if diag.insufficient_data:
        status = "INSUFFICIENT_DATA"
    elif diag.passed:
        status = "PASS"
    else:
        status = "FAIL"

    title_bits = [
        f"n={diag.n_replicates_with_signal}/{diag.n_replicates}",
        f"thr={effective_threshold:.3f}",
    ]
    if diag.score_test_rt is not None:
        title_bits.append(f"score_rt={diag.score_test_rt:.3f}")
        if diag.score_test_rt_se is not None:
            title_bits.append(f"±SE={diag.score_test_rt_se:.2f}")
    elif single_rep_chosen is not None:
        title_bits.append(f"chosen={single_rep_chosen:.3f}")
    if diag.score_test_p_value is not None:
        title_bits.append(f"p={diag.score_test_p_value:.1e}")
    if diag.bayesian_pick is not None:
        bayes = f"bayes={diag.bayesian_pick:.3f}"
        if diag.bayesian_pick_posterior is not None:
            bayes += f" (post={diag.bayesian_pick_posterior:.2f})"
        title_bits.append(bayes)

    heading = title if title else f"tier panel"
    stats_line = "  |  ".join(title_bits)
    if header_ax is not None:
        _write_panel_header(header_ax, heading=heading, status=status, stats_line=stats_line)
    else:
        full_title = f"{sanitize_plot_text(heading)}\n{status}  {stats_line}"
        ax.set_title(full_title, fontsize=8.5, loc="left", pad=10)

    unit = "min" if time_unit == "minutes" else "s"
    if show_xlabel:
        ax.set_xlabel(f"retention time ({unit})", fontsize=9)
    else:
        ax.set_xlabel("")
    ax.set_ylabel("intensity", fontsize=9)
    ax.tick_params(labelsize=8)
    if xlim is not None:
        ax.set_xlim(*xlim)
    ax.grid(True, alpha=0.25)
    if not show_xlabel:
        ax.tick_params(labelbottom=False)


def render_lineage_figure(
    result: LineageAnalysisResult,
    chromatogram_map: dict,
    *,
    null_token: str = "AgxNull",
    panel_height: float = 2.9,
    header_height: float = 0.62,
    legend_height: float = 1.35,
    width: float = 10.5,
    dpi: int = 120,
) -> Figure:
    """
    Render lineage panels root → leaf in a tall vertical stack.

    Legend and per-tier headers sit outside the chromatogram axes so annotations
    do not overlap trace data. Intended for scrollable viewing and vector export.
    """
    from src.core.pedigree_adapter import members_of_class

    configure_plot_fonts()
    settings = result.settings
    panels: List[LineagePanel] = result.panels
    n = len(panels)
    if n == 0:
        fig, ax = plt.subplots(figsize=(width, panel_height), dpi=dpi)
        ax.set_title("No lineage panels to display")
        return fig

    fig_h = legend_height + n * (header_height + panel_height) + 0.45
    fig = plt.figure(figsize=(width, fig_h), dpi=dpi)
    row_count = 1 + 2 * n
    height_ratios = [legend_height] + [header_height, panel_height] * n
    gs = GridSpec(
        row_count,
        1,
        figure=fig,
        height_ratios=height_ratios,
        hspace=0.38,
        left=0.09,
        right=0.97,
        top=0.97,
        bottom=0.03,
    )

    legend_ax = fig.add_subplot(gs[0, 0])
    legend_ax.set_axis_off()
    handles, labels = _legend_handles()
    legend_ax.legend(
        handles,
        labels,
        loc="upper left",
        ncol=3,
        fontsize=8,
        frameon=True,
        framealpha=0.95,
        title="Legend",
        title_fontsize=9,
        borderpad=0.8,
        columnspacing=1.1,
        handletextpad=0.5,
    )
    legend_ax.text(
        0.0,
        1.02,
        sanitize_plot_text(f"Lineage — {result.compound_id}  ({result.channel})"),
        fontsize=12,
        fontweight="bold",
        va="bottom",
        ha="left",
        transform=legend_ax.transAxes,
    )

    xlim: Optional[Tuple[float, float]] = None
    all_rts: List[float] = []
    for panel in panels:
        members = members_of_class(panel.class_bbs, chromatogram_map, null_token)
        for rt, _ in members:
            if rt.size:
                all_rts.extend(float(x) for x in rt)
    if all_rts:
        pad = (max(all_rts) - min(all_rts)) * 0.05 or 1.0
        xlim = (min(all_rts) - pad, max(all_rts) + pad)

    share_ax: Optional[plt.Axes] = None
    for idx, panel in enumerate(panels):
        header_ax = fig.add_subplot(gs[1 + 2 * idx, 0])
        plot_ax = fig.add_subplot(gs[2 + 2 * idx, 0], sharex=share_ax)
        if share_ax is None:
            share_ax = plot_ax

        members = members_of_class(panel.class_bbs, chromatogram_map, null_token)
        if panel.tier == 0:
            label = "tier 0  ROOT"
            plot_class_panel(
                members or [],
                effective_threshold=0.0,
                tolerance=settings.tolerance,
                alpha=settings.alpha,
                title=label,
                ax=plot_ax,
                header_ax=header_ax,
                xlim=xlim,
                time_unit=settings.time_unit,
                show_xlabel=(idx == n - 1),
            )
        else:
            bb_label = ", ".join(panel.class_bbs) if panel.class_bbs else "(root)"
            label = f"tier {panel.tier}  {{{sanitize_plot_text(bb_label)}}}  ({panel.n_replicates} reps)"
            plot_class_panel(
                members,
                effective_threshold=panel.effective_threshold,
                tolerance=settings.tolerance,
                alpha=settings.alpha,
                title=label,
                ax=plot_ax,
                header_ax=header_ax,
                xlim=xlim,
                time_unit=settings.time_unit,
                show_xlabel=(idx == n - 1),
            )

    setattr(fig, _LINEAGE_LAYOUT_ATTR, True)
    return fig


def is_lineage_export_figure(fig: Figure) -> bool:
    """Return True when ``fig`` was produced by :func:`render_lineage_figure``."""
    return bool(getattr(fig, _LINEAGE_LAYOUT_ATTR, False))
