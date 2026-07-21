# tests/test_library_metrics.py
"""
Tests for library-wide metrics and plots.
"""

from pathlib import Path

from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    METRIC_LIBRARY_COVERAGE_INDEX,
    METRIC_TOTAL_COUNT_PER_ENTRY,
    MetricResult,
    ScannedEntry,
    compound_total_counts,
    compute_library_metrics,
    compute_metrics_from_scan,
    export_metrics_summary_csv,
    run_library_computation,
    scan_library,
)
from src.core.library_plots import (
    PLOT_TOTAL_COUNT_HISTOGRAM,
    PLOT_TOTAL_COUNT_PER_FRACTION,
    generate_plots,
)
from src.core.library_metrics_store import (
    database_paths_match,
    load_snapshot,
    save_snapshot,
)
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def _compound(cid: str, totals_by_time: list) -> Compound:
    """Build compound from list of (time, {count: value})."""
    points = [
        ChromatographicDataPoint(time=t, counts=counts) for t, counts in totals_by_time
    ]
    return Compound(compound_id=cid, data_points=points)


class TestCompoundTotalCounts:
    def test_sums_across_time_points(self) -> None:
        c = _compound(
            "A",
            [
                (0.0, {"Count": 10.0, "Alt": 1.0}),
                (1.0, {"Count": 20.0, "Alt": 2.0}),
            ],
        )
        totals = compound_total_counts(c, ["Count", "Alt"])
        assert totals["Count"] == 30.0
        assert totals["Alt"] == 3.0


class TestTotalCountLibraryStats:
    def test_mean_and_sample_stdev(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = SpreadsheetConfig(
            compound_id_column="id",
            chromatographic_data_column="data",
            delimiters=[","],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Count"],
        )
        db_path = tmp_path / "lib.db"
        store = DataStore(db_path=db_path, use_memory=False)
        c1 = _compound("c1", [(0.0, {"Count": 10.0}), (1.0, {"Count": 20.0})])
        c2 = _compound("c2", [(0.0, {"Count": 40.0})])
        assert store.add_compound(c1, [])
        assert store.add_compound(c2, [])
        store.conn.commit()
        store.close()

        store2 = DataStore(db_path=db_path, use_memory=False)
        result = compute_library_metrics(store2, config, index_database=False)
        store2.close()

        assert result.entries_used == 2
        assert result.entries_skipped == 0

        ch_total = result.total_count_per_entry[0]
        assert ch_total.count_name == "Count"
        assert ch_total.n == 2
        assert ch_total.mean == 35.0
        assert result.fraction_count == DEFAULT_FRACTION_COUNT


class TestScanArtifact:
    def test_scan_stores_sorted_time_series(self, tmp_path) -> None:
        from src.core.data_store import DataStore
        from src.core.library_metrics import _sorted_entry_series

        config = SpreadsheetConfig(
            compound_id_column="id",
            chromatographic_data_column="data",
            delimiters=[","],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Count"],
        )
        c1 = _compound("c1", [(0.5, {"Count": 2.0}), (1.0, {"Count": 3.0}), (2.0, {"Count": 1.0})])
        times, counts = _sorted_entry_series(c1, ["Count"])
        assert times == [0.5, 1.0, 2.0]
        assert counts["Count"] == [2.0, 3.0, 1.0]

        db_path = tmp_path / "lib.db"
        store = DataStore(db_path=db_path, use_memory=False)
        assert store.add_compound(c1, [])
        store.conn.commit()

        scan = scan_library(store, config, index_database=False, channel_names=["Count"])
        store.close()

        assert scan.entries_used == 1
        entry = scan.entries[0]
        assert entry.times == [0.5, 1.0, 2.0]
        assert entry.counts_by_channel["Count"] == [2.0, 3.0, 1.0]

    def test_metrics_derived_from_scan_entries(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = SpreadsheetConfig(
            compound_id_column="id",
            chromatographic_data_column="data",
            delimiters=[","],
            time_column_index=0,
            count_column_indices=[1, 2],
            count_names=["Count", "Alt"],
        )
        db_path = tmp_path / "lib.db"
        store = DataStore(db_path=db_path, use_memory=False)
        assert store.add_compound(_compound("c1", [(0.0, {"Count": 10.0, "Alt": 100.0})]), [])
        store.conn.commit()

        scan = scan_library(store, config, index_database=False, channel_names=["Count"])
        metrics = compute_metrics_from_scan(
            scan,
            [METRIC_TOTAL_COUNT_PER_ENTRY],
            channels=["Count"],
        )
        store.close()

        assert len(metrics) == 1
        assert metrics[0].channels[0].mean == 10.0


class TestLibraryPlots:
    def test_generate_histogram_plot(self, tmp_path) -> None:
        from src.core.library_metrics import LibraryScanData

        scan = LibraryScanData(
            entries=[
                ScannedEntry("a", [0.0, 1.0], {"Count": [1.0, 2.0]}),
                ScannedEntry("b", [0.0], {"Count": [10.0]}),
            ],
            entries_used=2,
            entries_attempted=2,
            channel_names=["Count"],
        )
        out = tmp_path / "plots"
        plots = generate_plots(scan, [PLOT_TOTAL_COUNT_HISTOGRAM], ["Count"], out)
        assert len(plots) == 1
        assert plots[0].image_path is not None
        assert plots[0].image_path.is_file()

    def test_generate_total_count_per_fraction_plot(self, tmp_path) -> None:
        from src.core.library_metrics import LibraryScanData

        scan = LibraryScanData(
            entries=[
                ScannedEntry("a", [0.0, 1.0], {"Count": [1.0, 2.0]}),
                ScannedEntry("b", [0.0, 1.0], {"Count": [10.0, 20.0]}),
            ],
            entries_used=2,
            entries_attempted=2,
            channel_names=["Count"],
        )
        out = tmp_path / "plots"
        plots = generate_plots(scan, [PLOT_TOTAL_COUNT_PER_FRACTION], ["Count"], out)
        assert len(plots) == 1
        assert plots[0].image_path is not None
        assert plots[0].image_path.is_file()

    def test_generate_all_registered_plot_types(self, tmp_path) -> None:
        from src.core.library_metrics import LibraryScanData
        from src.core.library_plots import list_library_plot_definitions

        scan = LibraryScanData(
            entries=[
                ScannedEntry("a", [0.0, 1.0, 2.0], {"Count": [1.0, 50.0, 2.0]}),
                ScannedEntry("b", [0.0, 1.0], {"Count": [2.0, 30.0]}),
            ],
            entries_used=2,
            entries_attempted=2,
            channel_names=["Count"],
        )
        plot_ids = [p.plot_id for p in list_library_plot_definitions()]
        out = tmp_path / "all_plots"
        plots = generate_plots(scan, plot_ids, ["Count"], out, signal_quality_alpha=0.01)
        assert len(plots) == len(plot_ids)
        for result in plots:
            assert result.image_path is not None, result.title
            assert result.image_path.is_file(), result.title


class TestLibraryMetricsStore:
    def test_save_and_load_roundtrip(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = SpreadsheetConfig(
            compound_id_column="id",
            chromatographic_data_column="data",
            delimiters=[","],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Count"],
        )
        db_path = tmp_path / "sample_lib.db"
        store = DataStore(db_path=db_path, use_memory=False)
        snapshot = run_library_computation(
            store,
            config,
            index_database=False,
            database_kind="full",
            database_path=db_path,
            channel_names=["Count"],
            metric_ids=[METRIC_TOTAL_COUNT_PER_ENTRY, METRIC_LIBRARY_COVERAGE_INDEX],
        )
        store.close()

        out_dir = tmp_path / "library_data"
        out_dir.mkdir()
        target = out_dir / "sample_lib_20260101_120000.json"
        save_snapshot(snapshot, target)
        loaded = load_snapshot(target)

        assert loaded.database_name == "sample_lib.db"
        assert loaded.selected_metrics == snapshot.selected_metrics
        assert len(loaded.metric_results) == 2
        assert database_paths_match(str(db_path), db_path)

    def test_export_metrics_summary_csv(self, tmp_path) -> None:
        from datetime import datetime, timezone

        snapshot = LibraryComputationSnapshot(
            processed_at=datetime.now(timezone.utc),
            database_path=str(tmp_path / "lib.db"),
            database_kind="full",
            fraction_count=96,
            selected_channels=["Count"],
            selected_metrics=[METRIC_TOTAL_COUNT_PER_ENTRY],
            metric_results=[
                MetricResult(
                    metric_id=METRIC_TOTAL_COUNT_PER_ENTRY,
                    title="Total count",
                    help_text="help",
                    channels=[ChannelAggregateStats("Count", 10.0, 2.0, 5)],
                )
            ],
        )
        out = tmp_path / "metrics.csv"
        export_metrics_summary_csv(snapshot, out)
        text = out.read_text(encoding="utf-8-sig")
        assert "metric_id" in text
        assert METRIC_TOTAL_COUNT_PER_ENTRY in text
        assert "Count" in text
