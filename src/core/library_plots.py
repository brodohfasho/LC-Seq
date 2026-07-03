# src/core/library_plots.py
"""
Library-wide visualizations generated from a parsed :class:`LibraryScanData` artifact.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from src.core.library_metrics import LibraryScanData, PlotResult, entry_total_for_channel
from src.core.library_signal_quality import DEFAULT_SIGNAL_QUALITY_ALPHA

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

PLOT_TOTAL_COUNT_HISTOGRAM = "total_count_histogram"
PLOT_TOTAL_COUNT_PER_FRACTION = "total_count_per_fraction"
PLOT_MAX_COUNT_HISTOGRAM = "max_count_histogram"
PLOT_SNR_EXCESS_HISTOGRAM = "snr_excess_histogram"
PLOT_SNR_RATIO_HISTOGRAM = "snr_ratio_histogram"
PLOT_DYNAMIC_RANGE_HISTOGRAM = "dynamic_range_histogram"
PLOT_MAX_PROMINENCE_HISTOGRAM = "max_prominence_histogram"
PLOT_BASELINE_MU_HISTOGRAM = "baseline_mu_histogram"
PLOT_SIG_PEAK_COUNT_HISTOGRAM = "significant_peak_count_histogram"

DEFAULT_HISTOGRAM_BINS = 50
DEFAULT_SIGNAL_QUALITY_ALPHA = 0.001

# Matplotlib defaults are ~12 (title) and ~10 (axis labels); bump for readability.
PLOT_TITLE_FONTSIZE = 13
PLOT_AXIS_LABEL_FONTSIZE = 12
PLOT_LEGEND_FONTSIZE = 10

PLOT_TOTAL_COUNT_PER_FRACTION_TITLE = "Total sequencing count per fraction"


@dataclass(frozen=True)
class PlotDefinition:
    """Registry entry for a library-wide plot."""

    plot_id: str
    title: str
    help_text: str
    render_fn: Callable[..., Figure]
    category: str = "coverage"


def list_library_plot_definitions() -> List[PlotDefinition]:
    """Return registered plots in stable display order."""
    return [
        LIBRARY_PLOT_DEFINITIONS[PLOT_TOTAL_COUNT_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_TOTAL_COUNT_PER_FRACTION],
        LIBRARY_PLOT_DEFINITIONS[PLOT_MAX_COUNT_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_SNR_EXCESS_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_SNR_RATIO_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_DYNAMIC_RANGE_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_MAX_PROMINENCE_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_BASELINE_MU_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_SIG_PEAK_COUNT_HISTOGRAM],
    ]


def _integer_histogram_bins(values: Sequence[float]) -> np.ndarray:
    """Bin edges aligned to integer counts (0, 1, 2, …) for discrete distributions."""
    if not values:
        return np.array([-0.5, 0.5, 1.5])
    vmax = int(max(values))
    return np.arange(-0.5, vmax + 1.5, 1.0)


def _normal_pdf(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    """Gaussian PDF; returns zeros when σ is not positive."""
    if sigma <= 0:
        return np.zeros_like(x, dtype=float)
    return (1.0 / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _curve_height_at(x: float, n: int, bin_width: float, mu: float, sigma: float) -> float:
    """Scale a normal PDF to match histogram bar heights (count scale)."""
    return float(n * bin_width * _normal_pdf(np.array([x]), mu, sigma)[0])


def _overlay_distribution_reference(
    ax,
    values: Sequence[float],
    *,
    bin_edges: np.ndarray,
    bin_width: float,
) -> None:
    """
    Overlay a normal reference curve on the histogram and mark mean, median, and ±1 SD.

    The curve uses the sample mean and SD; markers sit on that curve at the corresponding
    x positions (appropriate as a smooth reference for continuous library metrics).
    """
    from matplotlib.lines import Line2D

    if len(values) == 0:
        return

    mean_val = float(statistics.mean(values))
    median_val = float(statistics.median(values))
    std_val = float(statistics.stdev(values)) if len(values) > 1 else 0.0
    n = len(values)

    x_min = float(bin_edges[0])
    x_max = float(bin_edges[-1])
    x_pad = max((x_max - x_min) * 0.05, bin_width)
    x_curve = np.linspace(x_min - x_pad, x_max + x_pad, 400)

    legend_handles: List[Line2D] = []

    if std_val > 0:
        y_curve = n * bin_width * _normal_pdf(x_curve, mean_val, std_val)
        ax.plot(
            x_curve,
            y_curve,
            color="#3D444D",
            linewidth=2.0,
            alpha=0.85,
            zorder=4,
        )

        marker_specs = (
            ("o", "#FF6B6B", mean_val, f"Mean: {mean_val:.4g}"),
            ("s", "#FFB347", median_val, f"Median: {median_val:.4g}"),
            ("^", "#888888", mean_val - std_val, f"μ − σ: {mean_val - std_val:.4g}"),
            ("v", "#888888", mean_val + std_val, f"μ + σ: {mean_val + std_val:.4g} (σ={std_val:.4g})"),
        )
        for marker, color, x_pos, label in marker_specs:
            y_pos = _curve_height_at(x_pos, n, bin_width, mean_val, std_val)
            ax.plot(
                x_pos,
                y_pos,
                marker=marker,
                color=color,
                markersize=7,
                linestyle="None",
                zorder=5,
            )
            legend_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker=marker,
                    color="w",
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=7,
                    linestyle="None",
                    label=label,
                )
            )
    else:
        ymax = ax.get_ylim()[1]
        y_mark = ymax * 0.92 if ymax > 0 else 1.0
        ax.plot(
            mean_val,
            y_mark,
            marker="o",
            color="#FF6B6B",
            markersize=7,
            linestyle="None",
            zorder=5,
        )
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor="#FF6B6B",
                markeredgecolor="#FF6B6B",
                markersize=7,
                linestyle="None",
                label=f"Mean / median: {mean_val:.4g}",
            )
        )

    legend_handles.append(
        Line2D([0], [0], color="none", label=f"n = {n:,}")
    )
    ax.legend(
        handles=legend_handles,
        loc="upper right",
        fontsize=PLOT_LEGEND_FONTSIZE,
        framealpha=0.9,
    )


def _render_histogram(
    ax,
    values: Sequence[float],
    *,
    color: str,
    xlabel: str,
    title: str,
    integer_bins: bool = False,
) -> None:
    """Render a histogram with a normal reference curve and summary markers."""
    if not values:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontsize=PLOT_TITLE_FONTSIZE)
        return
    if integer_bins:
        bins = _integer_histogram_bins(values)
        _, bin_edges, _ = ax.hist(
            values,
            bins=bins,
            color=color,
            edgecolor="white",
            alpha=0.9,
            align="mid",
            label="_nolegend_",
        )
        vmax = int(max(values))
        ax.set_xticks(list(range(vmax + 1)))
        ax.set_xlabel(xlabel, fontsize=PLOT_AXIS_LABEL_FONTSIZE)
    else:
        _, bin_edges, _ = ax.hist(
            values,
            bins=DEFAULT_HISTOGRAM_BINS,
            color=color,
            edgecolor="white",
            alpha=0.9,
            label="_nolegend_",
        )
        ax.set_xlabel(xlabel, fontsize=PLOT_AXIS_LABEL_FONTSIZE)
    bin_width = float(bin_edges[1] - bin_edges[0]) if len(bin_edges) > 1 else 1.0
    ax.set_ylabel("Entries", fontsize=PLOT_AXIS_LABEL_FONTSIZE)
    ax.set_title(title, fontsize=PLOT_TITLE_FONTSIZE)
    _overlay_distribution_reference(ax, values, bin_edges=bin_edges, bin_width=bin_width)


def list_library_plot_definitions_by_category(category: str) -> List[PlotDefinition]:
    """Return plots filtered by category (``coverage`` or ``signal``)."""
    return [p for p in list_library_plot_definitions() if p.category == category]


def _render_total_count_histogram(scan: LibraryScanData, channel: str, dpi: int) -> Figure:
    values = [entry_total_for_channel(entry, channel) for entry in scan.entries]
    values = [v for v in values if v is not None]
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=dpi)
    _render_histogram(
        ax,
        values,
        color="#4C9AFF",
        xlabel=f"Total {channel}",
        title=f"Total {channel} per entry",
    )
    fig.tight_layout()
    return fig


def _render_max_count_histogram(scan: LibraryScanData, channel: str, dpi: int) -> Figure:
    values: List[float] = []
    for entry in scan.entries:
        if channel not in entry.counts_by_channel:
            continue
        counts = entry.counts_by_channel[channel]
        if counts:
            values.append(float(max(counts)))
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=dpi)
    _render_histogram(
        ax,
        values,
        color="#3FB950",
        xlabel=f"Max {channel}",
        title=f"Peak {channel} per entry",
    )
    fig.tight_layout()
    return fig


def _library_total_per_fraction_index(
    scan: LibraryScanData,
    channel: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Sum sequencing counts at each fraction index across all scanned entries.

    Fraction index is the 1-based position in each entry's time-sorted chromatogram
    (first time point = fraction 1, second = fraction 2, …).
    """
    max_fractions = 0
    for entry in scan.entries:
        if channel in entry.counts_by_channel:
            max_fractions = max(max_fractions, len(entry.counts_by_channel[channel]))
    if max_fractions == 0:
        return np.array([]), np.array([]), 0

    totals = np.zeros(max_fractions, dtype=float)
    entries_used = 0
    for entry in scan.entries:
        if channel not in entry.counts_by_channel:
            continue
        counts = entry.counts_by_channel[channel]
        if not counts:
            continue
        entries_used += 1
        for index, value in enumerate(counts):
            totals[index] += float(value)

    indices = np.arange(1, max_fractions + 1, dtype=float)
    return indices, totals, entries_used


def _per_entry_mean_per_fraction(
    scan: LibraryScanData,
    channel: str,
) -> List[float]:
    """Mean count per fraction index, averaged across entries that have that index."""
    max_fractions = 0
    for entry in scan.entries:
        if channel in entry.counts_by_channel:
            max_fractions = max(max_fractions, len(entry.counts_by_channel[channel]))
    if max_fractions == 0:
        return []

    means: List[float] = []
    for index in range(max_fractions):
        values: List[float] = []
        for entry in scan.entries:
            if channel not in entry.counts_by_channel:
                continue
            counts = entry.counts_by_channel[channel]
            if index < len(counts):
                values.append(float(counts[index]))
        if values:
            means.append(float(statistics.mean(values)))
    return means


def _render_total_count_per_fraction(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
) -> Figure:
    indices, totals, entries_used = _library_total_per_fraction_index(scan, channel)
    fig, ax = plt.subplots(figsize=(7.0, 4.0), dpi=dpi)
    if indices.size == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    else:
        ax.plot(indices, totals, color="#FF7B72", linewidth=1.6)
        ax.fill_between(indices, 0, totals, color="#FF7B72", alpha=0.15)
        ax.set_xlabel("Fraction index", fontsize=PLOT_AXIS_LABEL_FONTSIZE)
        ax.set_ylabel(f"Total {channel}", fontsize=PLOT_AXIS_LABEL_FONTSIZE)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0), useMathText=True)
        ax.set_title(
            f"{PLOT_TOTAL_COUNT_PER_FRACTION_TITLE} ({channel}, "
            f"{entries_used:,} entries)",
            fontsize=PLOT_TITLE_FONTSIZE,
        )

        library_total = float(np.sum(totals))
        per_fraction_means = _per_entry_mean_per_fraction(scan, channel)
        if per_fraction_means:
            avg_per_fraction = float(statistics.mean(per_fraction_means))
            sd_per_fraction = (
                float(statistics.stdev(per_fraction_means))
                if len(per_fraction_means) > 1
                else 0.0
            )
            stats_lines = (
                f"Library total count: {library_total:,.4g}\n"
                f"Mean count per fraction: {avg_per_fraction:,.4g} ± {sd_per_fraction:,.4g}"
            )
        else:
            stats_lines = f"Library total count: {library_total:,.4g}"

        ax.text(
            0.98,
            0.98,
            stats_lines,
            transform=ax.transAxes,
            va="top",
            ha="right",
            fontsize=9,
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "alpha": 0.9,
                "edgecolor": "#cccccc",
            },
        )
    fig.tight_layout()
    return fig


def _signal_stats_for_channel(
    scan: LibraryScanData,
    channel: str,
    signal_quality_alpha: float,
) -> List:
    """Reuse scan signal-quality cache when parameters match; otherwise compute once."""
    min_prominence = scan.signal_quality_min_prominence or 0.0
    min_pct_area = scan.signal_quality_min_pct_area or 0.0
    if (
        scan.signal_quality_alpha is not None
        and abs(scan.signal_quality_alpha - signal_quality_alpha) < 1e-12
        and scan.signal_quality_min_prominence == min_prominence
        and scan.signal_quality_min_pct_area == min_pct_area
        and channel in scan.signal_quality_by_channel
    ):
        return list(scan.signal_quality_by_channel[channel])
    from src.core.library_metrics import ensure_scan_signal_quality

    ensure_scan_signal_quality(
        scan,
        [channel],
        signal_quality_alpha,
        min_prominence=min_prominence,
        min_pct_area=min_pct_area,
    )
    return list(scan.signal_quality_by_channel.get(channel, []))


def _render_signal_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float,
    value_fn: Callable,
    xlabel: str,
    title: str,
    color: str,
    integer_bins: bool = False,
    skip_none: bool = False,
) -> Figure:
    stats_list = _signal_stats_for_channel(scan, channel, signal_quality_alpha)
    values: List[float] = []
    for stats in stats_list:
        raw = value_fn(stats)
        if skip_none and raw is None:
            continue
        values.append(float(raw))
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=dpi)
    _render_histogram(
        ax,
        values,
        color=color,
        xlabel=xlabel,
        title=f"{title} (α={signal_quality_alpha:g})",
        integer_bins=integer_bins,
    )
    fig.tight_layout()
    return fig


def _render_snr_excess_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.tallest_significant_snr_excess,
        xlabel="SNR excess (tallest significant peak − μ)",
        title=f"Tallest significant peak SNR excess — {channel}",
        color="#A371F7",
    )


def _render_snr_ratio_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.tallest_significant_snr_ratio,
        xlabel="SNR ratio ((tallest significant peak − μ) ÷ σ)",
        title=f"Tallest significant peak SNR ratio — {channel}",
        color="#BC8CFF",
        skip_none=True,
    )


def _render_dynamic_range_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.tallest_significant_dynamic_range,
        xlabel="Dynamic range (tallest significant peak ÷ μ)",
        title=f"Tallest significant peak dynamic range — {channel}",
        color="#79C0FF",
        skip_none=True,
    )


def _render_max_prominence_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.max_significant_prominence,
        xlabel="Max prominence (significant peaks)",
        title=f"Max significant peak prominence — {channel}",
        color="#56D364",
    )


def _render_baseline_mu_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.baseline_mu,
        xlabel="Baseline μ",
        title=f"Baseline level — {channel}",
        color="#D29922",
    )


def _render_sig_peak_count_histogram(
    scan: LibraryScanData,
    channel: str,
    dpi: int,
    *,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
) -> Figure:
    return _render_signal_histogram(
        scan,
        channel,
        dpi,
        signal_quality_alpha=signal_quality_alpha,
        value_fn=lambda s: s.significant_peak_count,
        xlabel="Significant peak count",
        title=f"Significant peaks per entry — {channel}",
        color="#58A6FF",
        integer_bins=True,
    )


LIBRARY_PLOT_DEFINITIONS: Dict[str, PlotDefinition] = {
    PLOT_TOTAL_COUNT_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_TOTAL_COUNT_HISTOGRAM,
        title="Total count distribution",
        help_text="Histogram of per-entry total count summed across all time points.",
        render_fn=_render_total_count_histogram,
    ),
    PLOT_TOTAL_COUNT_PER_FRACTION: PlotDefinition(
        plot_id=PLOT_TOTAL_COUNT_PER_FRACTION,
        title=PLOT_TOTAL_COUNT_PER_FRACTION_TITLE,
        help_text=(
            "At each fraction index (1…N in time-sorted order), the sum of sequencing "
            "counts across all library entries."
        ),
        render_fn=_render_total_count_per_fraction,
    ),
    PLOT_MAX_COUNT_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_MAX_COUNT_HISTOGRAM,
        title="Peak count distribution",
        help_text="Histogram of the maximum count value observed per entry.",
        render_fn=_render_max_count_histogram,
    ),
    PLOT_SNR_EXCESS_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_SNR_EXCESS_HISTOGRAM,
        title="Tallest significant peak SNR excess distribution",
        help_text=(
            "Histogram of per-entry SNR excess for the tallest statistically significant "
            "peak (apex height minus baseline μ)."
        ),
        render_fn=_render_snr_excess_histogram,
        category="signal",
    ),
    PLOT_SNR_RATIO_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_SNR_RATIO_HISTOGRAM,
        title="Tallest significant peak SNR ratio distribution",
        help_text=(
            "Histogram of per-entry SNR ratio for the tallest significant peak: "
            "(height − baseline μ) ÷ baseline σ. Entries with σ ≈ 0 are omitted."
        ),
        render_fn=_render_snr_ratio_histogram,
        category="signal",
    ),
    PLOT_DYNAMIC_RANGE_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_DYNAMIC_RANGE_HISTOGRAM,
        title="Dynamic range distribution",
        help_text=(
            "Histogram of per-entry dynamic range for the tallest significant peak: "
            "apex height ÷ baseline μ. Entries with μ ≈ 0 are omitted."
        ),
        render_fn=_render_dynamic_range_histogram,
        category="signal",
    ),
    PLOT_MAX_PROMINENCE_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_MAX_PROMINENCE_HISTOGRAM,
        title="Max prominence distribution",
        help_text=(
            "Histogram of per-entry maximum prominence among statistically significant "
            "peaks (apex height minus the higher of the two adjacent minima)."
        ),
        render_fn=_render_max_prominence_histogram,
        category="signal",
    ),
    PLOT_BASELINE_MU_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_BASELINE_MU_HISTOGRAM,
        title="Baseline μ distribution",
        help_text=(
            "Histogram of per-entry baseline μ from the σ-clipped median noise model "
            "(iteratively remove points above mean+2σ, median of remainder)."
        ),
        render_fn=_render_baseline_mu_histogram,
        category="signal",
    ),
    PLOT_SIG_PEAK_COUNT_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_SIG_PEAK_COUNT_HISTOGRAM,
        title="Significant peak count distribution",
        help_text=(
            "Histogram of significant peak counts per entry. A peak counts when the "
            "picker's height or area p-value is below α. Lower α → fewer peaks."
        ),
        render_fn=_render_sig_peak_count_histogram,
        category="signal",
    ),
}


def _safe_plot_filename(plot_id: str, channel: str) -> str:
    safe_channel = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel)
    return f"{plot_id}_{safe_channel}.png"


def generate_plots(
    scan: LibraryScanData,
    plot_ids: Sequence[str],
    channels: Sequence[str],
    output_dir: Path,
    *,
    dpi: int = 120,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    min_prominence: float = 0.0,
    min_pct_area: float = 0.0,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[PlotResult]:
    """
    Render selected plots for each channel and write PNG files to ``output_dir``.

    Returns:
        List of :class:`PlotResult` with ``image_path`` set for each generated file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[PlotResult] = []

    jobs: List[tuple[str, PlotDefinition, str]] = []
    for plot_id in plot_ids:
        definition = LIBRARY_PLOT_DEFINITIONS.get(plot_id)
        if definition is None:
            logger.warning("Unknown library plot id: %s", plot_id)
            continue
        for channel in channels:
            if channel in scan.channel_names:
                jobs.append((plot_id, definition, channel))

    signal_channels = {
        channel
        for _pid, definition, channel in jobs
        if definition.category == "signal"
    }
    if signal_channels:
        from src.core.library_metrics import ensure_scan_signal_quality

        ensure_scan_signal_quality(
            scan,
            list(signal_channels),
            signal_quality_alpha,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            progress_callback=progress_callback,
        )

    total_jobs = len(jobs)
    for job_index, (plot_id, definition, channel) in enumerate(jobs, start=1):
        if progress_callback is not None:
            progress_callback(
                job_index,
                total_jobs,
                f"Rendering: {definition.title} — {channel}",
            )
        target = output_dir / _safe_plot_filename(plot_id, channel)
        try:
            if definition.category == "signal":
                fig = definition.render_fn(
                    scan, channel, dpi, signal_quality_alpha=signal_quality_alpha
                )
            else:
                fig = definition.render_fn(scan, channel, dpi)
            try:
                fig.savefig(target, format="png", bbox_inches="tight")
            finally:
                plt.close(fig)
            image_path = target.resolve()
        except Exception as exc:
            logger.error(
                "Failed to render plot %s for channel %s: %s",
                plot_id,
                channel,
                exc,
                exc_info=True,
            )
            image_path = None
            title = f"{definition.title} — {channel} (render failed)"
            help_text = f"{definition.help_text} Error: {exc}"
        else:
            title = f"{definition.title} — {channel}"
            help_text = definition.help_text

        results.append(
            PlotResult(
                plot_id=plot_id,
                title=title,
                help_text=help_text,
                channel=channel,
                image_path=image_path,
            )
        )
    return results
