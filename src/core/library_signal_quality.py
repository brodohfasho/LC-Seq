# src/core/library_signal_quality.py
"""
Per-entry and library-wide chromatographic signal quality (significant peaks).

Formal definitions: docs/LIBRARY_SIGNAL_QUALITY.md
"""

from __future__ import annotations

import csv
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from src.core.lcseq_backend import get_peak_picker_backend
from src.core.peak_quality_filter import filter_detected_peaks
from src.models.analysis_settings import AnalysisSettings

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

DEFAULT_SIGNAL_QUALITY_ALPHA = 0.001
MIN_POINTS_FOR_SIGNAL = 3


@dataclass(frozen=True)
class EntrySignalStats:
    """Per-compound signal metrics on one count channel."""

    compound_id: str
    channel: str
    baseline_mu: float
    baseline_sigma: float
    significant_peak_count: int
    has_significant_peak: bool
    max_significant_prominence: float
    median_significant_prominence: Optional[float]
    tallest_significant_peak_height: float
    tallest_significant_peak_rt: float
    tallest_significant_snr_excess: float
    tallest_significant_snr_ratio: Optional[float]
    tallest_significant_dynamic_range: Optional[float]
    signal_quality_alpha: float


def compute_entry_signal_stats(
    entry,
    channel: str,
    *,
    alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    min_prominence: float = 0.0,
    min_pct_area: float = 0.0,
) -> Optional[EntrySignalStats]:
    """
    Compute signal-quality scalars for one scanned entry.

    Peak height, SNR, and dynamic range use the tallest statistically significant peak.
  """
    if channel not in entry.counts_by_channel:
        return None
    intensity = [float(x) for x in entry.counts_by_channel[channel]]
    times = [float(t) for t in entry.times]
    if len(intensity) < MIN_POINTS_FOR_SIGNAL or len(times) != len(intensity):
        return None

    backend = get_peak_picker_backend()
    baseline = backend.estimate_baseline(intensity)
    mu = float(baseline.mu)
    sigma = float(baseline.sigma)

    picked = backend.find_peaks(times, intensity, alpha)
    quality_settings = AnalysisSettings(
        count_channel=channel,
        alpha=alpha,
        min_prominence=min_prominence,
        min_pct_area=min_pct_area,
    )
    picked = filter_detected_peaks(picked, quality_settings)
    sig_count = len(picked)
    prominences = [float(p.prominence) for p in picked]
    max_prom = max(prominences) if prominences else 0.0
    med_prom = float(statistics.median(prominences)) if prominences else None

    if picked:
        tallest_peak = max(picked, key=lambda p: float(p.intensity))
        tallest_sig_height = float(tallest_peak.intensity)
        tallest_sig_rt = float(tallest_peak.rt)
    else:
        tallest_sig_height = 0.0
        tallest_sig_rt = float(times[0]) if times else 0.0

    tallest_sig_snr = tallest_sig_height - mu
    tallest_sig_ratio: Optional[float] = None
    if sigma > 1e-12:
        tallest_sig_ratio = tallest_sig_snr / sigma
    tallest_sig_dynamic: Optional[float] = None
    if mu > 1e-12:
        tallest_sig_dynamic = tallest_sig_height / mu

    return EntrySignalStats(
        compound_id=str(entry.compound_id),
        channel=channel,
        baseline_mu=mu,
        baseline_sigma=sigma,
        significant_peak_count=sig_count,
        has_significant_peak=sig_count > 0,
        max_significant_prominence=max_prom,
        median_significant_prominence=med_prom,
        tallest_significant_peak_height=tallest_sig_height,
        tallest_significant_peak_rt=tallest_sig_rt,
        tallest_significant_snr_excess=tallest_sig_snr,
        tallest_significant_snr_ratio=tallest_sig_ratio,
        tallest_significant_dynamic_range=tallest_sig_dynamic,
        signal_quality_alpha=alpha,
    )


def attach_signal_quality_to_entries(
    entries: Sequence,
    channels: Sequence[str],
    *,
    alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    min_prominence: float = 0.0,
    min_pct_area: float = 0.0,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, List[EntrySignalStats]]:
    """
    Compute per-entry signal stats for all entries and channels.

    Returns:
        Mapping channel name → list of stats (one per entry that could be computed).
    """
    out: Dict[str, List[EntrySignalStats]] = {ch: [] for ch in channels}
    total = len(entries) * len(channels)
    done = 0

    def emit() -> None:
        if progress_callback is None:
            return
        status = f"Signal quality: {done:,} / {total:,} entry×channel pairs"
        progress_callback(done, total, status)

    for channel in channels:
        for entry in entries:
            stats = compute_entry_signal_stats(
                entry,
                channel,
                alpha=alpha,
                min_prominence=min_prominence,
                min_pct_area=min_pct_area,
            )
            if stats is not None:
                out[channel].append(stats)
            done += 1
            if done % 25 == 0 or done == total:
                emit()
    return out


def export_per_entry_signal_csv(
    stats_by_channel: Dict[str, List[EntrySignalStats]],
    path: str | Path,
    *,
    alpha: float,
) -> Path:
    """Write one row per compound per channel with all per-entry signal scalars."""
    out = Path(path)
    rows: List[dict] = []
    for channel, stats_list in stats_by_channel.items():
        for s in stats_list:
            rows.append(
                {
                    "compound_id": s.compound_id,
                    "channel": channel,
                    "baseline_mu": s.baseline_mu,
                    "baseline_sigma": s.baseline_sigma,
                    "significant_peak_count": s.significant_peak_count,
                    "has_significant_peak": int(s.has_significant_peak),
                    "max_significant_prominence": s.max_significant_prominence,
                    "median_significant_prominence": (
                        s.median_significant_prominence
                        if s.median_significant_prominence is not None
                        else ""
                    ),
                    "tallest_significant_peak_height": s.tallest_significant_peak_height,
                    "tallest_significant_peak_rt": s.tallest_significant_peak_rt,
                    "tallest_significant_snr_excess": s.tallest_significant_snr_excess,
                    "tallest_significant_snr_ratio": (
                        s.tallest_significant_snr_ratio
                        if s.tallest_significant_snr_ratio is not None
                        else ""
                    ),
                    "tallest_significant_dynamic_range": (
                        s.tallest_significant_dynamic_range
                        if s.tallest_significant_dynamic_range is not None
                        else ""
                    ),
                }
            )

    fieldnames = [
        "compound_id",
        "channel",
        "baseline_mu",
        "baseline_sigma",
        "significant_peak_count",
        "has_significant_peak",
        "max_significant_prominence",
        "median_significant_prominence",
        "tallest_significant_peak_height",
        "tallest_significant_peak_rt",
        "tallest_significant_snr_excess",
        "tallest_significant_snr_ratio",
        "tallest_significant_dynamic_range",
    ]
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            f"# signal_quality_alpha={alpha}; definitions=docs/LIBRARY_SIGNAL_QUALITY.md\n"
        )
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out
