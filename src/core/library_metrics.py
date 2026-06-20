# src/core/library_metrics.py
"""
Library-wide metrics computed over all compounds in the active database.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
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

# Sequencing fractions per compound (average count per fraction = total count / this value).
DEFAULT_FRACTION_COUNT = 96


@dataclass(frozen=True)
class ChannelAggregateStats:
    """Mean and sample SD of per-entry scalar values for one count channel."""

    count_name: str
    mean: float
    std_dev: float
    n: int


@dataclass
class TotalCountLibraryStats:
    """Aggregate of total-count-per-entry statistics across the library."""

    channels: List[ChannelAggregateStats] = field(default_factory=list)
    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0


@dataclass
class LibraryMetricsResult:
    """All library metrics from a single scan of the database."""

    entries_attempted: int = 0
    entries_used: int = 0
    entries_skipped: int = 0
    total_count_per_entry: List[ChannelAggregateStats] = field(default_factory=list)
    avg_count_per_fraction: List[ChannelAggregateStats] = field(default_factory=list)
    fraction_count: int = DEFAULT_FRACTION_COUNT


def compound_total_counts(compound: Compound, count_names: Sequence[str]) -> Dict[str, float]:
    """
    Sum count values across all time points for each configured channel.

    Args:
        compound: Parsed compound with data points.
        count_names: Configured count channel names.

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


def compute_library_metrics(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    fraction_count: int = DEFAULT_FRACTION_COUNT,
    progress_callback: Optional[ProgressCallback] = None,
) -> LibraryMetricsResult:
    """
    Scan the library once and compute total-count and per-fraction average metrics.

    Per entry and count channel:
      - total = sum of counts over all time points
      - avg per fraction = total / fraction_count (e.g. 96 sequencing fractions)

    Across entries: sample mean and SD for each scalar, per channel.
    """
    count_names = list(config.count_names)
    if not count_names or fraction_count <= 0:
        return LibraryMetricsResult(fraction_count=max(fraction_count, DEFAULT_FRACTION_COUNT))

    compound_ids = store.get_all_compound_ids()
    total = len(compound_ids)
    processor = DataProcessor()
    total_sums: Dict[str, List[float]] = {name: [] for name in count_names}
    fraction_avgs: Dict[str, List[float]] = {name: [] for name in count_names}
    used = 0
    skipped = 0
    inv_fraction = 1.0 / float(fraction_count)

    def emit(processed: int, status: str) -> None:
        if progress_callback:
            progress_callback(processed, total, status)

    emit(0, "Computing library metrics…")

    for i, cid in enumerate(compound_ids, start=1):
        base = store.get_compound(cid)
        if base is None:
            skipped += 1
            if i % 50 == 0 or i == total:
                emit(i, f"Processed {i:,} / {total:,} entries…")
            continue

        compound = base
        if index_database:
            compound = _hydrate_index_compound(store, config, processor, base)
        if compound is None or not compound.data_points:
            skipped += 1
            if i % 50 == 0 or i == total:
                emit(i, f"Processed {i:,} / {total:,} entries…")
            continue

        totals = compound_total_counts(compound, count_names)
        for name in count_names:
            entry_total = totals[name]
            total_sums[name].append(entry_total)
            fraction_avgs[name].append(entry_total * inv_fraction)
        used += 1

        if i % 50 == 0 or i == total:
            emit(i, f"Processed {i:,} / {total:,} entries…")

    emit(total, "Complete")
    return LibraryMetricsResult(
        entries_attempted=total,
        entries_used=used,
        entries_skipped=skipped,
        total_count_per_entry=_channel_stats_from_values(count_names, total_sums),
        avg_count_per_fraction=_channel_stats_from_values(count_names, fraction_avgs),
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
    """
    Compute all library metrics using a DB connection opened in the **current** thread.
    """
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
