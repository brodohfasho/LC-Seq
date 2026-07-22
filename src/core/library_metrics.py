# src/core/library_metrics.py
"""
Library-wide metrics computed over all compounds in the active database.

Workflow:
  1. **Scan** (slow): load each row, parse chromatogram data, sort by time.
  2. **Compute** (fast): derive scalar metrics from the scan artifact.
  3. **Plots** (moderate): see ``library_plots.py``.
"""

from __future__ import annotations

import logging
import statistics
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

from src.core.csv_io import CSV_EXPORT_ENCODING
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
    EntrySignalStats,
    SignalQualityComputeOptions,
    attach_signal_quality_to_entries,
)
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.models.compound import Compound
from src.models.compound_identity import split_compound_storage_id
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

DEFAULT_FRACTION_COUNT = 96

METRIC_TOTAL_COUNT_PER_ENTRY = "total_count_per_entry"
METRIC_AVG_COUNT_PER_FRACTION = "avg_count_per_fraction"
METRIC_LIBRARY_COVERAGE_INDEX = "library_coverage_index"

METRIC_BASELINE_MU = "baseline_mu_library"
METRIC_BASELINE_SIGMA = "baseline_sigma_library"
METRIC_TALLEST_SIG_PEAK_HEIGHT = "tallest_significant_peak_height_mean"
METRIC_TALLEST_SIG_SNR_EXCESS = "tallest_significant_snr_excess_mean"
METRIC_TALLEST_SIG_SNR_RATIO = "tallest_significant_snr_ratio_mean"
METRIC_TALLEST_SIG_DYNAMIC_RANGE = "tallest_significant_dynamic_range_mean"
METRIC_FRACTION_SIGNIFICANT = "fraction_with_significant_peak"
METRIC_SIG_PEAK_COUNT_MEAN = "significant_peak_count_mean"
METRIC_MAX_PROMINENCE_MEAN = "max_significant_prominence_mean"
METRIC_MEDIAN_PROMINENCE_MEAN = "median_significant_prominence_mean"

SIGNAL_QUALITY_METRIC_IDS = frozenset(
    {
        METRIC_BASELINE_MU,
        METRIC_BASELINE_SIGMA,
        METRIC_TALLEST_SIG_PEAK_HEIGHT,
        METRIC_TALLEST_SIG_SNR_EXCESS,
        METRIC_TALLEST_SIG_SNR_RATIO,
        METRIC_TALLEST_SIG_DYNAMIC_RANGE,
        METRIC_FRACTION_SIGNIFICANT,
        METRIC_SIG_PEAK_COUNT_MEAN,
        METRIC_MAX_PROMINENCE_MEAN,
        METRIC_MEDIAN_PROMINENCE_MEAN,
    }
)


@dataclass(frozen=True)
class ChannelAggregateStats:
    """Mean and sample SD of per-entry scalar values for one count channel."""

    count_name: str
    mean: float
    std_dev: float
    n: int


@dataclass
class ScannedEntry:
    """Parsed, time-sorted chromatogram series for one library entry."""

    compound_id: str
    times: List[float]
    counts_by_channel: Dict[str, List[float]]


@dataclass
class LibraryScanData:
    """Parsed library entries from a single scan (time-sorted per entry)."""

    entries: List[ScannedEntry] = field(default_factory=list)
    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0
    channel_names: List[str] = field(default_factory=list)
    signal_quality_options: Optional[SignalQualityComputeOptions] = None
    signal_quality_by_channel: Dict[str, List] = field(default_factory=dict)

    @property
    def signal_quality_alpha(self) -> Optional[float]:
        if self.signal_quality_options is None:
            return None
        return self.signal_quality_options.alpha
    source_database_name: str = ""
    scanned_at: Optional[datetime] = None

    def totals_by_channel(self, channel: str) -> List[float]:
        """Per-entry total count for one channel."""
        return [
            total
            for entry in self.entries
            if (total := entry_total_for_channel(entry, channel)) is not None
        ]


def entry_total_for_channel(entry: ScannedEntry, channel: str) -> Optional[float]:
    """Sum counts across time for one channel on a scanned entry."""
    values = entry.counts_by_channel.get(channel)
    if values is None:
        return None
    return float(sum(values))


def library_coverage_index(
    entries: Sequence[ScannedEntry],
    channel: str,
    fraction_count: int,
) -> Optional[float]:
    """Sum of per-entry totals ÷ (n_entries × fraction_count)."""
    if fraction_count <= 0:
        return None
    totals = [
        t
        for entry in entries
        if (t := entry_total_for_channel(entry, channel)) is not None
    ]
    if not totals:
        return None
    return float(sum(totals)) / (len(totals) * float(fraction_count))


@dataclass
class MetricResult:
    """Computed values for one library metric."""

    metric_id: str
    title: str
    help_text: str
    channels: List[ChannelAggregateStats] = field(default_factory=list)


@dataclass
class PlotResult:
    """A generated library plot (PNG on disk)."""

    plot_id: str
    title: str
    help_text: str
    channel: str
    image_path: Optional[Path] = None


@dataclass
class LibraryComputationSnapshot:
    """Full result set from one scan session, including provenance for save/load."""

    processed_at: datetime
    database_path: str
    database_kind: str
    fraction_count: int
    selected_channels: List[str]
    selected_metrics: List[str]
    selected_plots: List[str] = field(default_factory=list)
    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0
    metric_results: List[MetricResult] = field(default_factory=list)
    plot_results: List[PlotResult] = field(default_factory=list)
    signal_quality_options: SignalQualityComputeOptions = field(
        default_factory=SignalQualityComputeOptions
    )

    @property
    def signal_quality_alpha(self) -> float:
        return self.signal_quality_options.alpha

    @property
    def database_name(self) -> str:
        return Path(self.database_path).name


@dataclass
class TotalCountLibraryStats:
    """Legacy wrapper: total-count metric only."""

    channels: List[ChannelAggregateStats] = field(default_factory=list)
    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0


@dataclass
class LibraryMetricsResult:
    """Legacy: all metrics from a single scan (all channels)."""

    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0
    total_count_per_entry: List[ChannelAggregateStats] = field(default_factory=list)
    avg_count_per_fraction: List[ChannelAggregateStats] = field(default_factory=list)
    fraction_count: int = DEFAULT_FRACTION_COUNT


@dataclass(frozen=True)
class MetricComputeOptions:
    """Parameters shared by library metric compute functions."""

    fraction_count: int = DEFAULT_FRACTION_COUNT
    signal_quality: SignalQualityComputeOptions = field(
        default_factory=SignalQualityComputeOptions
    )


@dataclass(frozen=True)
class MetricDefinition:
    """Registry entry for an extensible library-wide calculation."""

    metric_id: str
    title: str
    help_text: str
    compute_fn: Callable[
        [LibraryScanData, Sequence[str], MetricComputeOptions],
        List[ChannelAggregateStats],
    ]
    category: str = "general"


def _ensure_signal_quality(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: SignalQualityComputeOptions,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Populate ``scan.signal_quality_by_channel`` when needed."""
    if (
        scan.signal_quality_options == options
        and scan.signal_quality_by_channel
        and all(ch in scan.signal_quality_by_channel for ch in channels)
    ):
        if progress_callback is not None:
            total = max(len(scan.entries) * len(channels), 1)
            progress_callback(total, total, "Signal quality cache ready")
        return
    scan.signal_quality_by_channel = attach_signal_quality_to_entries(
        scan.entries,
        channels,
        options=options,
        progress_callback=progress_callback,
    )
    scan.signal_quality_options = options


def _signal_stats_for_channel(
    scan: LibraryScanData, channel: str
) -> List[EntrySignalStats]:
    return list(scan.signal_quality_by_channel.get(channel, []))


def ensure_scan_signal_quality(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: SignalQualityComputeOptions,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    """Populate per-entry signal stats on ``scan`` when needed (cached by picker settings)."""
    _ensure_signal_quality(
        scan,
        channels,
        options,
        progress_callback=progress_callback,
    )


def _compute_total_count_per_entry(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: MetricComputeOptions,
) -> List[ChannelAggregateStats]:
    del options
    values = {name: scan.totals_by_channel(name) for name in channels}
    return _channel_stats_from_values(channels, values)


def _compute_avg_count_per_fraction(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: MetricComputeOptions,
) -> List[ChannelAggregateStats]:
    fraction_count = options.fraction_count
    if fraction_count <= 0:
        return _channel_stats_from_values(channels, {name: [] for name in channels})
    inv_fraction = 1.0 / float(fraction_count)
    values = {
        name: [v * inv_fraction for v in scan.totals_by_channel(name)] for name in channels
    }
    return _channel_stats_from_values(channels, values)


def _compute_library_coverage_index(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: MetricComputeOptions,
) -> List[ChannelAggregateStats]:
    channels_out: List[ChannelAggregateStats] = []
    for name in channels:
        idx = library_coverage_index(scan.entries, name, options.fraction_count)
        if idx is None:
            channels_out.append(ChannelAggregateStats(count_name=name, mean=0.0, std_dev=0.0, n=0))
        else:
            channels_out.append(
                ChannelAggregateStats(count_name=name, mean=idx, std_dev=0.0, n=scan.entries_used)
            )
    return channels_out


def _compute_signal_metric(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: MetricComputeOptions,
    accessor: Callable[[EntrySignalStats], Optional[float]],
    *,
    skip_none: bool = False,
) -> List[ChannelAggregateStats]:
    _ensure_signal_quality(scan, channels, options.signal_quality)
    values: Dict[str, List[float]] = {}
    for name in channels:
        vals: List[float] = []
        for stats in _signal_stats_for_channel(scan, name):
            raw = accessor(stats)
            if raw is None:
                if skip_none:
                    continue
            else:
                vals.append(float(raw))
        values[name] = vals
    return _channel_stats_from_values(channels, values)


def _compute_fraction_significant(
    scan: LibraryScanData,
    channels: Sequence[str],
    options: MetricComputeOptions,
) -> List[ChannelAggregateStats]:
    return _compute_signal_metric(
        scan,
        channels,
        options,
        lambda s: 1.0 if s.has_significant_peak else 0.0,
    )


_BASELINE_ALGORITHM = (
    "Baseline μ and σ use the same σ-clipped median as Chromatogram Visualizer: "
    "iteratively remove points above mean+2σ, then take the median of remaining "
    "points as μ and their sample standard deviation as σ."
)

_SIGNIFICANT_PEAK_NOTE = (
    "Peaks are first required to pass the peak picker's significance test "
    "(modern α, or old-school Gaussian criteria). Optional min prominence and "
    "min % area filters then drop weak detections before counting or ranking "
    "peaks (same post-filters as RT assignment / Chromatogram Visualizer)."
)

_SIGNIFICANT_PEAK_HEIGHT_NOTE = (
    "The tallest significant peak is the highest apex among peaks that remain "
    "after significance and quality filters—it may not be the DEL product."
)

LIBRARY_METRIC_DEFINITIONS: Dict[str, MetricDefinition] = {
    METRIC_TOTAL_COUNT_PER_ENTRY: MetricDefinition(
        metric_id=METRIC_TOTAL_COUNT_PER_ENTRY,
        title="Total count per entry — library mean ± SD",
        help_text=(
            "For each compound, all count values are summed across time points. "
            "Mean and sample standard deviation are taken across the library."
        ),
        compute_fn=_compute_total_count_per_entry,
        category="coverage",
    ),
    METRIC_AVG_COUNT_PER_FRACTION: MetricDefinition(
        metric_id=METRIC_AVG_COUNT_PER_FRACTION,
        title="Average sequencing count per fraction — library mean ± SD",
        help_text=(
            "For each compound, total count ÷ fraction count gives the average count "
            "per fraction. Mean and sample SD of those per-compound averages are shown here."
        ),
        compute_fn=_compute_avg_count_per_fraction,
        category="coverage",
    ),
    METRIC_LIBRARY_COVERAGE_INDEX: MetricDefinition(
        metric_id=METRIC_LIBRARY_COVERAGE_INDEX,
        title="Library coverage index",
        help_text=(
            "Σ(entry total counts) ÷ (n_entries × fraction count). Single index per channel "
            "summarizing average sequencing depth per library member per fraction."
        ),
        compute_fn=_compute_library_coverage_index,
        category="coverage",
    ),
    METRIC_BASELINE_MU: MetricDefinition(
        metric_id=METRIC_BASELINE_MU,
        title="Baseline level (μ) — library mean ± SD",
        help_text=(
            "Per entry: σ-clipped median noise floor before peak heights are measured. "
            f"{_BASELINE_ALGORITHM}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.baseline_mu
        ),
        category="signal",
    ),
    METRIC_BASELINE_SIGMA: MetricDefinition(
        metric_id=METRIC_BASELINE_SIGMA,
        title="Baseline spread (σ) — library mean ± SD",
        help_text=(
            "Per entry: sample standard deviation of baseline points retained after "
            f"σ-clipping. {_BASELINE_ALGORITHM}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.baseline_sigma
        ),
        category="signal",
    ),
    METRIC_TALLEST_SIG_PEAK_HEIGHT: MetricDefinition(
        metric_id=METRIC_TALLEST_SIG_PEAK_HEIGHT,
        title="Tallest significant peak height — library mean ± SD",
        help_text=(
            "Per entry: apex height of the tallest peak with p-value < α. Zero when no "
            f"significant peaks. {_SIGNIFICANT_PEAK_HEIGHT_NOTE} {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.tallest_significant_peak_height
        ),
        category="signal",
    ),
    METRIC_TALLEST_SIG_SNR_EXCESS: MetricDefinition(
        metric_id=METRIC_TALLEST_SIG_SNR_EXCESS,
        title="Tallest significant peak SNR excess — library mean ± SD",
        help_text=(
            "Per entry: tallest significant peak height minus baseline μ (signal above the "
            f"noise floor in count units). {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.tallest_significant_snr_excess
        ),
        category="signal",
    ),
    METRIC_TALLEST_SIG_SNR_RATIO: MetricDefinition(
        metric_id=METRIC_TALLEST_SIG_SNR_RATIO,
        title="Tallest significant peak SNR ratio (÷ σ) — library mean ± SD",
        help_text=(
            "Per entry: (tallest significant peak height − baseline μ) ÷ baseline σ. "
            f"Entries with σ ≈ 0 are skipped. {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.tallest_significant_snr_ratio, skip_none=True
        ),
        category="signal",
    ),
    METRIC_TALLEST_SIG_DYNAMIC_RANGE: MetricDefinition(
        metric_id=METRIC_TALLEST_SIG_DYNAMIC_RANGE,
        title="Dynamic range (significant peak ÷ μ) — library mean ± SD",
        help_text=(
            "Per entry: tallest significant peak height divided by baseline μ. Entries "
            f"with μ ≈ 0 are skipped. {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.tallest_significant_dynamic_range, skip_none=True
        ),
        category="signal",
    ),
    METRIC_FRACTION_SIGNIFICANT: MetricDefinition(
        metric_id=METRIC_FRACTION_SIGNIFICANT,
        title="Fraction with ≥1 significant peak",
        help_text=(
            "Per entry: 1 if at least one significant peak exists, else 0. The library "
            f"mean equals the fraction of entries with any significant peak. {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=_compute_fraction_significant,
        category="signal",
    ),
    METRIC_SIG_PEAK_COUNT_MEAN: MetricDefinition(
        metric_id=METRIC_SIG_PEAK_COUNT_MEAN,
        title="Significant peaks per entry — library mean ± SD",
        help_text=(
            "Per entry: number of peaks that pass the configured picker and quality "
            f"filters (significance, min prominence, min % area). {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: float(s.significant_peak_count)
        ),
        category="signal",
    ),
    METRIC_MAX_PROMINENCE_MEAN: MetricDefinition(
        metric_id=METRIC_MAX_PROMINENCE_MEAN,
        title="Max prominence (significant peaks) — library mean ± SD",
        help_text=(
            "Per entry: maximum prominence among significant peaks (apex height minus the "
            "higher adjacent valley). Zero if no significant peaks. "
            f"{_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan, ch, opt, lambda s: s.max_significant_prominence
        ),
        category="signal",
    ),
    METRIC_MEDIAN_PROMINENCE_MEAN: MetricDefinition(
        metric_id=METRIC_MEDIAN_PROMINENCE_MEAN,
        title="Median prominence (significant peaks) — library mean ± SD",
        help_text=(
            "Per entry: median prominence among significant peaks. Entries with no "
            f"significant peaks are excluded. {_SIGNIFICANT_PEAK_NOTE}"
        ),
        compute_fn=lambda scan, ch, opt: _compute_signal_metric(
            scan,
            ch,
            opt,
            lambda s: s.median_significant_prominence,
            skip_none=True,
        ),
        category="signal",
    ),
}


def list_library_metric_definitions() -> List[MetricDefinition]:
    """Return registered metrics in stable display order."""
    order = [
        METRIC_TOTAL_COUNT_PER_ENTRY,
        METRIC_LIBRARY_COVERAGE_INDEX,
        METRIC_BASELINE_MU,
        METRIC_BASELINE_SIGMA,
        METRIC_TALLEST_SIG_PEAK_HEIGHT,
        METRIC_TALLEST_SIG_SNR_EXCESS,
        METRIC_TALLEST_SIG_SNR_RATIO,
        METRIC_TALLEST_SIG_DYNAMIC_RANGE,
        METRIC_FRACTION_SIGNIFICANT,
        METRIC_SIG_PEAK_COUNT_MEAN,
        METRIC_MAX_PROMINENCE_MEAN,
        METRIC_MEDIAN_PROMINENCE_MEAN,
    ]
    return [LIBRARY_METRIC_DEFINITIONS[mid] for mid in order]


def list_library_metric_definitions_by_category(category: str) -> List[MetricDefinition]:
    """Return metrics filtered by category (``coverage`` or ``signal``)."""
    return [m for m in list_library_metric_definitions() if m.category == category]


def compound_total_counts(compound: Compound, count_names: Sequence[str]) -> Dict[str, float]:
    """
    Sum count values across all time points for each configured channel.

    Args:
        compound: Parsed compound with data points.
        count_names: Count channel names to sum.

    Returns:
        Mapping count name → sum over time (missing values treated as 0).
    """
    totals = {name: 0.0 for name in count_names}
    for dp in compound.data_points:
        for name in count_names:
            val = dp.get_count(name)
            if val is not None:
                totals[name] += float(val)
    return totals


def _sorted_entry_series(
    compound: Compound,
    channel_names: Sequence[str],
) -> tuple[List[float], Dict[str, List[float]]]:
    """Extract time-sorted parallel arrays for each count channel."""
    points = sorted(compound.data_points, key=lambda dp: dp.time)
    times = [float(dp.time) for dp in points]
    counts_by_channel: Dict[str, List[float]] = {name: [] for name in channel_names}
    for dp in points:
        for name in channel_names:
            val = dp.get_count(name)
            counts_by_channel[name].append(float(val) if val is not None else 0.0)
    return times, counts_by_channel


def _hydrate_index_compound(
    store: DataStore,
    config: SpreadsheetConfig,
    processor: DataProcessor,
    compound: Compound,
) -> Optional[Compound]:
    """Parse raw chromatogram text for index-database rows."""
    if compound.data_points:
        return compound
    raw = store.get_raw_chromatogram(str(compound.compound_id))
    if not raw:
        return None
    primary = str(compound.primary_compound_id or "").strip()
    if not primary:
        primary, _ = split_compound_storage_id(str(compound.compound_id))
    row_data: Dict[str, object] = {
        config.compound_id_column: primary,
        config.chromatographic_data_column: raw,
    }
    if config.compound_variant_column:
        row_data[config.compound_variant_column] = (
            str(compound.variant_label) if compound.variant_label is not None else ""
        )
    for key, val in compound.metadata.items():
        row_data[key] = val
    series = pd.Series(row_data)
    parsed, _res = processor.parse_dataframe_row_to_compound(series, config, 0)
    return parsed


def _channel_stats_from_values(
    count_names: Sequence[str],
    values_by_channel: Dict[str, List[float]],
) -> List[ChannelAggregateStats]:
    channels: List[ChannelAggregateStats] = []
    for name in count_names:
        values = values_by_channel[name]
        n = len(values)
        if n == 0:
            channels.append(ChannelAggregateStats(count_name=name, mean=0.0, std_dev=0.0, n=0))
        elif n == 1:
            channels.append(
                ChannelAggregateStats(count_name=name, mean=values[0], std_dev=0.0, n=1)
            )
        else:
            channels.append(
                ChannelAggregateStats(
                    count_name=name,
                    mean=statistics.mean(values),
                    std_dev=statistics.stdev(values),
                    n=n,
                )
            )
    return channels


def scan_library(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    channel_names: Optional[Sequence[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryScanData:
    """
    Scan every library entry: load row, parse chromatogram, sort by time.

    This is the time-consuming step for large libraries (especially index databases).
    """
    channels = list(channel_names) if channel_names else list(config.count_names)
    channels = [name for name in channels if name]
    scan = LibraryScanData(channel_names=list(channels))
    if not channels:
        return scan

    compound_ids = store.get_all_compound_ids()
    total = len(compound_ids)
    scan.entries_attempted = total
    processor = DataProcessor()

    def emit(processed: int, status: str) -> None:
        if progress_callback:
            progress_callback(processed, total, status)

    emit(0, "Scanning library…")

    for i, cid in enumerate(compound_ids, start=1):
        base = store.get_compound(cid)
        if base is None:
            scan.entries_skipped += 1
            if i % 50 == 0 or i == total:
                emit(i, f"Scanned {i:,} / {total:,} entries…")
            continue

        compound = base
        if index_database:
            compound = _hydrate_index_compound(store, config, processor, base)
        if compound is None or not compound.data_points:
            scan.entries_skipped += 1
            if i % 50 == 0 or i == total:
                emit(i, f"Scanned {i:,} / {total:,} entries…")
            continue

        times, counts_by_channel = _sorted_entry_series(compound, channels)
        scan.entries.append(
            ScannedEntry(
                compound_id=str(compound.compound_id),
                times=times,
                counts_by_channel=counts_by_channel,
            )
        )
        scan.entries_used += 1

        if i % 50 == 0 or i == total:
            emit(i, f"Scanned {i:,} / {total:,} entries…")

    emit(total, "Scan complete")
    return scan


def compute_metrics_from_scan(
    scan: LibraryScanData,
    metric_ids: Sequence[str],
    *,
    channels: Sequence[str],
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    signal_quality: Optional[SignalQualityComputeOptions] = None,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[MetricResult]:
    """Compute selected metrics from an existing scan (fast aggregation only)."""
    sq = signal_quality or SignalQualityComputeOptions(alpha=signal_quality_alpha)
    options = MetricComputeOptions(fraction_count=fraction_count, signal_quality=sq)
    selected_channels = [name for name in channels if name in scan.channel_names]
    metric_list = list(metric_ids)
    needs_signal = any(mid in SIGNAL_QUALITY_METRIC_IDS for mid in metric_list)
    if needs_signal:
        _ensure_signal_quality(
            scan,
            selected_channels,
            sq,
            progress_callback=progress_callback,
        )

    results: List[MetricResult] = []
    total_metrics = len(metric_list)
    for index, metric_id in enumerate(metric_list, start=1):
        definition = LIBRARY_METRIC_DEFINITIONS.get(metric_id)
        if definition is None:
            logger.warning("Unknown library metric id: %s", metric_id)
            continue
        if progress_callback is not None:
            progress_callback(
                index,
                total_metrics,
                f"Aggregating: {definition.title[:48]}…",
            )
        title = definition.title
        if metric_id == METRIC_AVG_COUNT_PER_FRACTION:
            title = f"{definition.title} ({fraction_count})"
        elif metric_id in SIGNAL_QUALITY_METRIC_IDS:
            if sq.peak_picking_algorithm == "old_school":
                title = f"{definition.title} (old-school Gaussian)"
            else:
                filter_bits = [f"α={sq.alpha:g}"]
                if sq.min_prominence > 0:
                    filter_bits.append(f"prom≥{sq.min_prominence:g}")
                if sq.min_pct_area > 0:
                    filter_bits.append(f"%area≥{sq.min_pct_area:g}")
                title = f"{definition.title} ({', '.join(filter_bits)})"
        channel_stats = definition.compute_fn(scan, selected_channels, options)
        results.append(
            MetricResult(
                metric_id=metric_id,
                title=title,
                help_text=definition.help_text,
                channels=channel_stats,
            )
        )
    return results


def build_snapshot_from_scan(
    scan: LibraryScanData,
    *,
    database_path: Path,
    database_kind: str,
    channel_names: Sequence[str],
    metric_ids: Optional[Sequence[str]] = None,
    plot_ids: Optional[Sequence[str]] = None,
    plot_results: Optional[Sequence[PlotResult]] = None,
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    signal_quality: Optional[SignalQualityComputeOptions] = None,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryComputationSnapshot:
    """Build a snapshot with metrics computed from an existing scan."""
    sq = signal_quality or SignalQualityComputeOptions(alpha=signal_quality_alpha)
    metrics = metric_ids if metric_ids is not None else [
        m.metric_id for m in list_library_metric_definitions()
    ]
    metric_results = compute_metrics_from_scan(
        scan,
        metrics,
        channels=channel_names,
        fraction_count=fraction_count,
        signal_quality=sq,
        progress_callback=progress_callback,
    )
    return LibraryComputationSnapshot(
        processed_at=datetime.now(timezone.utc),
        database_path=str(database_path.resolve()),
        database_kind=database_kind,
        fraction_count=fraction_count,
        selected_channels=list(channel_names),
        selected_metrics=list(metrics),
        selected_plots=list(plot_ids or []),
        entries_attempted=scan.entries_attempted,
        entries_used=scan.entries_used,
        entries_skipped=scan.entries_skipped,
        metric_results=metric_results,
        plot_results=list(plot_results or []),
        signal_quality_options=sq,
    )


def scan_library_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    *,
    channel_names: Optional[Sequence[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryScanData:
    """Thread-safe: open DB in current thread and scan."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        return scan_library(
            store,
            config,
            index_database=store.is_index_database(),
            channel_names=channel_names,
            progress_callback=progress_callback,
        )
    finally:
        store.close()


def run_library_computation(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    database_kind: str,
    database_path: Path,
    channel_names: Sequence[str],
    metric_ids: Sequence[str],
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryComputationSnapshot:
    """Scan the library and compute the selected metrics."""
    scan = scan_library(
        store,
        config,
        index_database=index_database,
        channel_names=channel_names,
        progress_callback=progress_callback,
    )
    return build_snapshot_from_scan(
        scan,
        database_path=database_path,
        database_kind=database_kind,
        channel_names=channel_names,
        metric_ids=metric_ids,
        fraction_count=fraction_count,
        signal_quality_alpha=signal_quality_alpha,
    )


def run_library_computation_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    *,
    channel_names: Sequence[str],
    metric_ids: Sequence[str],
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    signal_quality_alpha: float = DEFAULT_SIGNAL_QUALITY_ALPHA,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryComputationSnapshot:
    """Thread-safe entry: opens DB in the current thread, runs scan + compute."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        kind = "index" if store.is_index_database() else "full"
        return run_library_computation(
            store,
            config,
            index_database=store.is_index_database(),
            database_kind=kind,
            database_path=db_path,
            channel_names=channel_names,
            metric_ids=metric_ids,
            fraction_count=fraction_count,
            signal_quality_alpha=signal_quality_alpha,
            progress_callback=progress_callback,
        )
    finally:
        store.close()


def compute_library_metrics(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryMetricsResult:
    """Legacy: scan all channels and compute all registered metrics."""
    channel_names = list(config.count_names)
    scan = scan_library(
        store,
        config,
        index_database=index_database,
        channel_names=channel_names,
        progress_callback=progress_callback,
    )
    metric_ids = [m.metric_id for m in list_library_metric_definitions()]
    metrics = compute_metrics_from_scan(
        scan,
        metric_ids,
        channels=channel_names,
        fraction_count=fraction_count,
    )
    total_stats = next(
        (m.channels for m in metrics if m.metric_id == METRIC_TOTAL_COUNT_PER_ENTRY),
        [],
    )
    frac_stats = next(
        (m.channels for m in metrics if m.metric_id == METRIC_AVG_COUNT_PER_FRACTION),
        [],
    )
    return LibraryMetricsResult(
        entries_attempted=scan.entries_attempted,
        entries_used=scan.entries_used,
        entries_skipped=scan.entries_skipped,
        total_count_per_entry=total_stats,
        avg_count_per_fraction=frac_stats,
        fraction_count=fraction_count,
    )


def compute_total_count_library_stats(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    progress_callback: Optional[ProgressCallback] = None,
) -> TotalCountLibraryStats:
    """Legacy wrapper: total-count metric only."""
    full = compute_library_metrics(
        store,
        config,
        index_database=index_database,
        progress_callback=progress_callback,
    )
    return TotalCountLibraryStats(
        channels=full.total_count_per_entry,
        entries_attempted=full.entries_attempted,
        entries_used=full.entries_used,
        entries_skipped=full.entries_skipped,
    )


def compute_library_metrics_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    *,
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryMetricsResult:
    """Legacy: all metrics, thread-safe path entry."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        return compute_library_metrics(
            store,
            config,
            index_database=store.is_index_database(),
            fraction_count=fraction_count,
            progress_callback=progress_callback,
        )
    finally:
        store.close()


def compute_total_count_library_stats_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> TotalCountLibraryStats:
    """Legacy wrapper: total-count metric only, thread-safe path entry."""
    full = compute_library_metrics_for_path(db_path, config, progress_callback=progress_callback)
    return TotalCountLibraryStats(
        channels=full.total_count_per_entry,
        entries_attempted=full.entries_attempted,
        entries_used=full.entries_used,
        entries_skipped=full.entries_skipped,
    )


def export_metrics_summary_csv(
    snapshot: LibraryComputationSnapshot,
    path: str | Path,
) -> Path:
    """Write one row per channel per calculated metric to a CSV file."""
    out = Path(path)
    fieldnames = [
        "metric_id",
        "metric_title",
        "channel",
        "mean",
        "std_dev",
        "n",
    ]
    with out.open("w", encoding=CSV_EXPORT_ENCODING, newline="") as fh:
        fh.write(
            f"# database={snapshot.database_name}; "
            f"database_kind={snapshot.database_kind}; "
            f"entries_used={snapshot.entries_used}; "
            f"entries_attempted={snapshot.entries_attempted}; "
            f"fraction_count={snapshot.fraction_count}; "
            f"signal_quality_alpha={snapshot.signal_quality_alpha:g}\n"
        )
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for metric in snapshot.metric_results:
            for channel in metric.channels:
                writer.writerow(
                    {
                        "metric_id": metric.metric_id,
                        "metric_title": metric.title,
                        "channel": channel.count_name,
                        "mean": channel.mean,
                        "std_dev": channel.std_dev,
                        "n": channel.n,
                    }
                )
    return out


ChannelTotalCountStats = ChannelAggregateStats
