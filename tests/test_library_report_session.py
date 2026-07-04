# tests/test_library_report_session.py
"""Tests for session-artifact library report assembly (Option A)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.core.library_metrics import (
    METRIC_TOTAL_COUNT_PER_ENTRY,
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    MetricResult,
)
from src.core.library_report_models import LibraryReportOptions
from src.core.library_report_session import (
    LibraryQcMetricsArtifact,
    LibraryReportSession,
    build_report_snapshot,
    missing_report_sections,
)


def _minimal_snapshot() -> LibraryComputationSnapshot:
    return LibraryComputationSnapshot(
        processed_at=datetime.now(timezone.utc),
        database_path="/tmp/test.db",
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
        entries_attempted=2,
        entries_used=2,
    )


class TestLibraryReportSession:
    def test_available_sections_requires_metric_ids(self) -> None:
        session = LibraryReportSession(
            database_path="/tmp/test.db",
            database_name="test.db",
            database_kind="full",
            qc_metrics=LibraryQcMetricsArtifact(
                generated_at=datetime.now(timezone.utc),
                snapshot=_minimal_snapshot(),
                metric_ids=[],
                channels=["Count"],
            ),
        )
        assert session.available_section_keys() == []

    def test_missing_report_sections_when_artifact_absent(self) -> None:
        session = LibraryReportSession(
            database_path="/tmp/test.db",
            database_name="test.db",
            database_kind="full",
        )
        options = LibraryReportOptions(
            include_metrics=True,
            include_plots=True,
            include_rt_assignment=False,
            include_pedigree_viz=False,
            include_splittree=False,
            metric_ids=[METRIC_TOTAL_COUNT_PER_ENTRY],
            channels=["Count"],
        )
        missing = missing_report_sections(options, session)
        assert len(missing) == 2
        assert any("Summary metrics" in note for note in missing)
        assert any("Visualizations" in note for note in missing)

    def test_build_report_snapshot_from_metrics_artifact(self) -> None:
        snap = _minimal_snapshot()
        session = LibraryReportSession(
            database_path=str(Path("/tmp/test.db")),
            database_name="test.db",
            database_kind="full",
            scan_entries_used=2,
            qc_metrics=LibraryQcMetricsArtifact(
                generated_at=snap.processed_at,
                snapshot=snap,
                metric_ids=[METRIC_TOTAL_COUNT_PER_ENTRY],
                channels=["Count"],
            ),
        )
        built = build_report_snapshot(session)
        assert built.database_path.endswith("test.db")
        assert built.metric_results
        assert built.selected_metrics == [METRIC_TOTAL_COUNT_PER_ENTRY]
