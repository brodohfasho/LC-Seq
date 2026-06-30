# src/core/library_plots.py
"""
Library-wide visualizations generated from a parsed :class:`LibraryScanData` artifact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from src.core.library_metrics import LibraryScanData, PlotResult, entry_total_for_channel

logger = logging.getLogger(__name__)

PLOT_TOTAL_COUNT_HISTOGRAM = "total_count_histogram"
PLOT_MEAN_CHROMATOGRAM = "mean_chromatogram"
PLOT_MAX_COUNT_HISTOGRAM = "max_count_histogram"

DEFAULT_HISTOGRAM_BINS = 50
DEFAULT_CHROMATOGRAM_BINS = 120


@dataclass(frozen=True)
class PlotDefinition:
    """Registry entry for a library-wide plot."""

    plot_id: str
    title: str
    help_text: str
    render_fn: Callable[[LibraryScanData, str, int], Figure]


def list_library_plot_definitions() -> List[PlotDefinition]:
    """Return registered plots in stable display order."""
    return [
        LIBRARY_PLOT_DEFINITIONS[PLOT_TOTAL_COUNT_HISTOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_MEAN_CHROMATOGRAM],
        LIBRARY_PLOT_DEFINITIONS[PLOT_MAX_COUNT_HISTOGRAM],
    ]


def _render_total_count_histogram(scan: LibraryScanData, channel: str, dpi: int) -> Figure:
    values = [entry_total_for_channel(entry, channel) for entry in scan.entries]
    values = [v for v in values if v is not None]
    fig, ax = plt.subplots(figsize=(7.0, 4.0), dpi=dpi)
    if not values:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    else:
        ax.hist(values, bins=DEFAULT_HISTOGRAM_BINS, color="#4C9AFF", edgecolor="white", alpha=0.9)
        ax.set_xlabel(f"Total {channel}")
        ax.set_ylabel("Entries")
    ax.set_title(f"Total {channel} per entry")
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
    fig, ax = plt.subplots(figsize=(7.0, 4.0), dpi=dpi)
    if not values:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    else:
        ax.hist(values, bins=DEFAULT_HISTOGRAM_BINS, color="#3FB950", edgecolor="white", alpha=0.9)
        ax.set_xlabel(f"Max {channel}")
        ax.set_ylabel("Entries")
    ax.set_title(f"Peak {channel} per entry")
    fig.tight_layout()
    return fig


def _binned_mean_chromatogram(
    scan: LibraryScanData,
    channel: str,
    *,
    n_bins: int = DEFAULT_CHROMATOGRAM_BINS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    all_times: List[float] = []
    for entry in scan.entries:
        all_times.extend(entry.times)
    if not all_times:
        return np.array([]), np.array([]), np.array([])

    t_min = float(min(all_times))
    t_max = float(max(all_times))
    if t_max <= t_min:
        t_max = t_min + 1.0

    bin_edges = np.linspace(t_min, t_max, n_bins + 1)
    bin_sums = np.zeros(n_bins, dtype=float)
    bin_counts = np.zeros(n_bins, dtype=float)
    span = t_max - t_min

    for entry in scan.entries:
        if channel not in entry.counts_by_channel:
            continue
        for time_val, count_val in zip(entry.times, entry.counts_by_channel[channel]):
            idx = int((float(time_val) - t_min) / span * n_bins)
            idx = min(max(idx, 0), n_bins - 1)
            bin_sums[idx] += float(count_val)
            bin_counts[idx] += 1.0

    centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    means = np.divide(
        bin_sums,
        bin_counts,
        out=np.full(n_bins, np.nan),
        where=bin_counts > 0,
    )
    return centers, means, bin_counts


def _render_mean_chromatogram(scan: LibraryScanData, channel: str, dpi: int) -> Figure:
    centers, means, counts = _binned_mean_chromatogram(scan, channel)
    fig, ax = plt.subplots(figsize=(7.0, 4.0), dpi=dpi)
    if centers.size == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
    else:
        valid = ~np.isnan(means)
        ax.plot(centers[valid], means[valid], color="#FF7B72", linewidth=1.6, label="Mean")
        ax.fill_between(centers[valid], 0, means[valid], color="#FF7B72", alpha=0.15)
        ax.set_xlabel("Time")
        ax.set_ylabel(channel)
        n_used = int(np.sum(counts > 0))
        ax.set_title(f"Mean library chromatogram ({channel}, n={n_used:,} time bins used)")
    fig.tight_layout()
    return fig


LIBRARY_PLOT_DEFINITIONS: Dict[str, PlotDefinition] = {
    PLOT_TOTAL_COUNT_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_TOTAL_COUNT_HISTOGRAM,
        title="Total count distribution",
        help_text="Histogram of per-entry total count summed across all time points.",
        render_fn=_render_total_count_histogram,
    ),
    PLOT_MEAN_CHROMATOGRAM: PlotDefinition(
        plot_id=PLOT_MEAN_CHROMATOGRAM,
        title="Mean library chromatogram",
        help_text="Average count vs time using shared time bins across all scanned entries.",
        render_fn=_render_mean_chromatogram,
    ),
    PLOT_MAX_COUNT_HISTOGRAM: PlotDefinition(
        plot_id=PLOT_MAX_COUNT_HISTOGRAM,
        title="Peak count distribution",
        help_text="Histogram of the maximum count value observed per entry.",
        render_fn=_render_max_count_histogram,
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
) -> List[PlotResult]:
    """
    Render selected plots for each channel and write PNG files to ``output_dir``.

    Returns:
        List of :class:`PlotResult` with ``image_path`` set for each generated file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[PlotResult] = []
    for plot_id in plot_ids:
        definition = LIBRARY_PLOT_DEFINITIONS.get(plot_id)
        if definition is None:
            logger.warning("Unknown library plot id: %s", plot_id)
            continue
        for channel in channels:
            if channel not in scan.channel_names:
                continue
            fig = definition.render_fn(scan, channel, dpi)
            filename = _safe_plot_filename(plot_id, channel)
            target = output_dir / filename
            try:
                fig.savefig(target, format="png", bbox_inches="tight")
            finally:
                plt.close(fig)
            results.append(
                PlotResult(
                    plot_id=plot_id,
                    title=f"{definition.title} — {channel}",
                    help_text=definition.help_text,
                    channel=channel,
                    image_path=target,
                )
            )
    return results
