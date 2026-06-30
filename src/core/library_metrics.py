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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

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
class MetricDefinition:
    """Registry entry for an extensible library-wide calculation."""

    metric_id: str
    title: str
    help_text: str
    compute_fn: Callable[[LibraryScanData, Sequence[str], int], List[ChannelAggregateStats]]


def _compute_total_count_per_entry(
    scan: LibraryScanData,
    channels: Sequence[str],
    fraction_count: int,
) -> List[ChannelAggregateStats]:
    del fraction_count
    values = {name: scan.totals_by_channel(name) for name in channels}
    return _channel_stats_from_values(channels, values)


def _compute_avg_count_per_fraction(
    scan: LibraryScanData,
    channels: Sequence[str],
    fraction_count: int,
) -> List[ChannelAggregateStats]:
    if fraction_count <= 0:
        return _channel_stats_from_values(channels, {name: [] for name in channels})
    inv_fraction = 1.0 / float(fraction_count)
    values = {
        name: [v * inv_fraction for v in scan.totals_by_channel(name)] for name in channels
    }
    return _channel_stats_from_values(channels, values)


LIBRARY_METRIC_DEFINITIONS: Dict[str, MetricDefinition] = {
    METRIC_TOTAL_COUNT_PER_ENTRY: MetricDefinition(
        metric_id=METRIC_TOTAL_COUNT_PER_ENTRY,
        title="Total count per entry — library mean ± SD",
        help_text=(
            "For each compound, all count values are summed across time points. "
            "Mean and sample standard deviation are taken across the library."
        ),
        compute_fn=_compute_total_count_per_entry,
    ),
    METRIC_AVG_COUNT_PER_FRACTION: MetricDefinition(
        metric_id=METRIC_AVG_COUNT_PER_FRACTION,
        title="Average sequencing count per fraction — library mean ± SD",
        help_text=(
            "For each compound, total count ÷ fraction count gives the average count "
            "per fraction. Mean and sample SD of those per-compound averages are shown here."
        ),
        compute_fn=_compute_avg_count_per_fraction,
    ),
}


def list_library_metric_definitions() -> List[MetricDefinition]:
    """Return registered metrics in stable display order."""
    return [
        LIBRARY_METRIC_DEFINITIONS[METRIC_TOTAL_COUNT_PER_ENTRY],
        LIBRARY_METRIC_DEFINITIONS[METRIC_AVG_COUNT_PER_FRACTION],
    ]


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
) -> List[MetricResult]:
    """Compute selected metrics from an existing scan (fast aggregation only)."""
    selected_channels = [name for name in channels if name in scan.channel_names]
    results: List[MetricResult] = []
    for metric_id in metric_ids:
        definition = LIBRARY_METRIC_DEFINITIONS.get(metric_id)
        if definition is None:
            logger.warning("Unknown library metric id: %s", metric_id)
            continue
        title = definition.title
        if metric_id == METRIC_AVG_COUNT_PER_FRACTION:
            title = f"{definition.title} ({fraction_count})"
        channel_stats = definition.compute_fn(scan, selected_channels, fraction_count)
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
) -> LibraryComputationSnapshot:
    """Build a snapshot with metrics computed from an existing scan."""
    metrics = metric_ids if metric_ids is not None else [
        m.metric_id for m in list_library_metric_definitions()
    ]
    metric_results = compute_metrics_from_scan(
        scan,
        metrics,
        channels=channel_names,
        fraction_count=fraction_count,
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
    )


def run_library_computation_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    *,
    channel_names: Sequence[str],
    metric_ids: Sequence[str],
    fraction_count: int = DEFAULT_FRACTION_COUNT,
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


ChannelTotalCountStats = ChannelAggregateStats
