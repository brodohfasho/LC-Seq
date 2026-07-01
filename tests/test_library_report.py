# tests/test_library_report.py
"""
Tests for library PDF report generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("reportlab")

from src.core.library_metrics import (  # noqa: E402
    METRIC_LIBRARY_COVERAGE_INDEX,
    METRIC_TOTAL_COUNT_PER_ENTRY,
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    MetricResult,
    PlotResult,
    ScannedEntry,
    compute_metrics_from_scan,
)
from src.core.library_plots import PLOT_TOTAL_COUNT_HISTOGRAM, generate_plots  # noqa: E402
from src.core.library_report import generate_library_report_pdf  # noqa: E402


def _flat_entry(compound_id: str, counts: list[float]) -> ScannedEntry:
    times = [float(i) for i in range(len(counts))]
    return ScannedEntry(
        compound_id=compound_id,
        times=times,
        counts_by_channel={"Count": counts},
    )


class TestLibraryReportPdf:
    def test_generates_pdf_with_metrics_and_plot(self, tmp_path: Path) -> None:
        entries = [
            _flat_entry("A", [10.0, 20.0]),
            _flat_entry("B", [30.0, 40.0]),
        ]
        from src.core.library_metrics import LibraryScanData

        scan = LibraryScanData(
            entries=entries,
            entries_used=2,
            entries_attempted=2,
            channel_names=["Count"],
        )
        metric_results = compute_metrics_from_scan(
            scan,
            [METRIC_TOTAL_COUNT_PER_ENTRY, METRIC_LIBRARY_COVERAGE_INDEX],
            channels=["Count"],
            fraction_count=96,
        )
        plot_dir = tmp_path / "plots"
        plots = generate_plots(
            scan,
            [PLOT_TOTAL_COUNT_HISTOGRAM],
            ["Count"],
            plot_dir,
        )
        snapshot = LibraryComputationSnapshot(
            processed_at=datetime.now(timezone.utc),
            database_path=str(tmp_path / "test.db"),
            database_kind="full",
            fraction_count=96,
            selected_channels=["Count"],
            selected_metrics=[METRIC_TOTAL_COUNT_PER_ENTRY],
            selected_plots=[PLOT_TOTAL_COUNT_HISTOGRAM],
            entries_attempted=2,
            entries_used=2,
            entries_skipped=0,
            metric_results=metric_results,
            plot_results=plots,
            signal_quality_alpha=0.001,
        )
        pdf_path = tmp_path / "report.pdf"
        result = generate_library_report_pdf(snapshot, pdf_path, plot_results=plots)
        assert result.is_file()
        assert result.stat().st_size > 1000

    def test_generates_minimal_pdf_metrics_only(self, tmp_path: Path) -> None:
        snapshot = LibraryComputationSnapshot(
            processed_at=datetime.now(timezone.utc),
            database_path=str(tmp_path / "test.db"),
            database_kind="full",
            fraction_count=96,
            selected_channels=["Count"],
            selected_metrics=[METRIC_TOTAL_COUNT_PER_ENTRY],
            metric_results=[
                MetricResult(
                    metric_id=METRIC_TOTAL_COUNT_PER_ENTRY,
                    title="Total count per entry",
                    help_text="test",
                    channels=[
                        ChannelAggregateStats(
                            count_name="Count",
                            mean=25.0,
                            std_dev=5.0,
                            n=2,
                        )
                    ],
                )
            ],
        )
        pdf_path = tmp_path / "minimal.pdf"
        generate_library_report_pdf(snapshot, pdf_path)
        assert pdf_path.is_file()
