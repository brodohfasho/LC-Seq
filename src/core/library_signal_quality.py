# src/core/library_signal_quality.py
"""
Per-entry and library-wide chromatographic signal quality (significant peaks).

Formal definitions: dev/LIBRARY_SIGNAL_QUALITY.md
"""

from __future__ import annotations

import csv
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from src.core.csv_io import CSV_EXPORT_ENCODING
from src.core.lcseq_backend import (
    _attach_integration_bounds,
    find_peaks_for_settings,
    get_peak_picker_backend,
)
from src.core.peak_picker_gaussian import find_peaks_gaussian
from src.core.peak_quality_filter import filter_detected_peaks
from src.models.analysis_settings import (
    DEFAULT_GAUSSIAN_MIN_HEIGHT_FACTOR,
    DEFAULT_GAUSSIAN_FIT_WIDTH_MINUTES,
    DEFAULT_GAUSSIAN_MINIMUM_RT_MINUTES,
    DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES,
    AnalysisSettings,
    TimeUnit,
)
from src.models.peak_result import PickedPeak

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

DEFAULT_SIGNAL_QUALITY_ALPHA = 0.001
MIN_POINTS_FOR_SIGNAL = 3


@dataclass(frozen=True)
class SignalQualityComputeOptions:
    """Peak-picker settings for library QC signal metrics and plots."""

    peak_picking_algorithm: str = "modern"
    alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA
    time_unit: TimeUnit = "seconds"
    min_prominence: float = 0.0
    min_pct_area: float = 0.0
    gaussian_min_height_factor: float = DEFAULT_GAUSSIAN_MIN_HEIGHT_FACTOR
    gaussian_fit_width: float = DEFAULT_GAUSSIAN_FIT_WIDTH_MINUTES
    gaussian_stddev_threshold: float = DEFAULT_GAUSSIAN_STDDEV_THRESHOLD_MINUTES
    gaussian_minimum_rt: float = DEFAULT_GAUSSIAN_MINIMUM_RT_MINUTES

    def cache_key(self) -> tuple:
        return (
            self.peak_picking_algorithm,
            round(float(self.alpha), 12),
            self.time_unit,
            round(float(self.min_prominence), 12),
            round(float(self.min_pct_area), 12),
            round(float(self.gaussian_min_height_factor), 12),
            round(float(self.gaussian_fit_width), 12),
            round(float(self.gaussian_stddev_threshold), 12),
            round(float(self.gaussian_minimum_rt), 12),
        )

    def picker_label(self) -> str:
        if self.peak_picking_algorithm == "old_school":
            return "old-school Gaussian"
        return "modern NB"

    def to_analysis_settings(self, channel: str) -> AnalysisSettings:
        """Build settings for shared peak-picking helpers."""
        return AnalysisSettings(
            count_channel=channel,
            time_unit=self.time_unit,
            chromatogram_time_unit=self.time_unit,
            peak_picking_algorithm=self.peak_picking_algorithm,  # type: ignore[arg-type]
            alpha=self.alpha,
            min_prominence=float(self.min_prominence),
            min_pct_area=float(self.min_pct_area),
            gaussian_min_height_factor=self.gaussian_min_height_factor,
            gaussian_fit_width=self.gaussian_fit_width,
            gaussian_stddev_threshold=self.gaussian_stddev_threshold,
            gaussian_minimum_rt=self.gaussian_minimum_rt,
        )


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
    peak_picking_algorithm: str = "modern"


def _pick_peaks_for_signal_quality(
    times: Sequence[float],
    intensity: Sequence[float],
    channel: str,
    options: SignalQualityComputeOptions,
) -> List[PickedPeak]:
    """Detect peaks, then apply modern-only prominence / % area quality filters."""
    settings = options.to_analysis_settings(channel)
    if options.peak_picking_algorithm == "old_school":
        raw = find_peaks_gaussian(
            times,
            intensity,
            min_height_threshold_factor=settings.gaussian_min_height_factor,
            fit_width=settings.gaussian_fit_width,
            stddev_threshold=settings.gaussian_stddev_threshold,
            minimum_rt=settings.gaussian_minimum_rt,
        )
        picked = _attach_integration_bounds(times, raw)
    else:
        backend = get_peak_picker_backend()
        picked = backend.find_peaks(times, intensity, options.alpha)
    return filter_detected_peaks(picked, settings)


def compute_entry_signal_stats(
    entry,
    channel: str,
    *,
    options: Optional[SignalQualityComputeOptions] = None,
    alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    min_prominence: float = 0.0,
    min_pct_area: float = 0.0,
) -> Optional[EntrySignalStats]:
    """
    Compute signal-quality scalars for one scanned entry.

    Peak height, SNR, dynamic range, and significant-peak counts use peaks that
    pass picker detection and the configured min prominence / min % area
    filters (shared with Chromatogram Visualizer / RT assignment).
    """
    if options is None:
        options = SignalQualityComputeOptions(
            alpha=alpha,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
        )

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

    picked = _pick_peaks_for_signal_quality(times, intensity, channel, options)
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

    report_alpha = options.alpha if options.peak_picking_algorithm == "modern" else 0.0
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
        signal_quality_alpha=report_alpha,
        peak_picking_algorithm=options.peak_picking_algorithm,
    )


def attach_signal_quality_to_entries(
    entries: Sequence,
    channels: Sequence[str],
    *,
    options: Optional[SignalQualityComputeOptions] = None,
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
    if options is None:
        options = SignalQualityComputeOptions(
            alpha=alpha,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
        )
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
            stats = compute_entry_signal_stats(entry, channel, options=options)
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
    options: SignalQualityComputeOptions,
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
    meta = (
        f"peak_picking_algorithm={options.peak_picking_algorithm}; "
        f"signal_quality_alpha={options.alpha:g}; "
        f"min_prominence={options.min_prominence:g}; "
        f"min_pct_area={options.min_pct_area:g}; "
        f"time_unit={options.time_unit}; "
        "definitions=dev/LIBRARY_SIGNAL_QUALITY.md"
    )
    with out.open("w", encoding=CSV_EXPORT_ENCODING, newline="") as fh:
        fh.write(f"# {meta}\n")
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out
