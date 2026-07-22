# tests/test_library_signal_quality.py
"""
Tests for per-entry and library-wide signal-quality metrics.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.core.library_metrics import (
    METRIC_TALLEST_SIG_SNR_EXCESS,
    METRIC_TALLEST_SIG_SNR_RATIO,
    ScannedEntry,
    compute_metrics_from_scan,
    library_coverage_index,
)
from src.core.library_signal_quality import (
    SignalQualityComputeOptions,
    attach_signal_quality_to_entries,
    compute_entry_signal_stats,
    export_per_entry_signal_csv,
)


def _flat_entry(compound_id: str, counts: list[float]) -> ScannedEntry:
    times = [float(i) for i in range(len(counts))]
    return ScannedEntry(
        compound_id=compound_id,
        times=times,
        counts_by_channel={"Count": counts},
    )


class TestComputeEntrySignalStats:
    def test_flat_trace_baseline_and_no_significant_peaks(self) -> None:
        entry = _flat_entry("A", [5.0, 5.0, 5.0, 5.0])
        stats = compute_entry_signal_stats(entry, "Count", alpha=0.001)
        assert stats is not None
        assert stats.baseline_mu == pytest.approx(5.0, rel=1e-3)
        assert stats.tallest_significant_peak_height == pytest.approx(0.0, abs=1e-6)
        assert stats.tallest_significant_snr_excess == pytest.approx(-5.0, rel=1e-3)
        assert stats.significant_peak_count == 0

    def test_single_spike_increases_significant_snr(self) -> None:
        entry = _flat_entry("B", [1.0, 1.0, 50.0, 1.0, 1.0])
        stats = compute_entry_signal_stats(entry, "Count", alpha=0.05)
        assert stats is not None
        assert stats.tallest_significant_peak_height == pytest.approx(50.0)
        assert stats.tallest_significant_snr_excess > 0.0
        assert stats.tallest_significant_snr_ratio is not None
        assert stats.tallest_significant_snr_ratio > 1.0
        assert stats.significant_peak_count >= 1

    def test_too_few_points_returns_none(self) -> None:
        entry = _flat_entry("C", [1.0, 2.0])
        assert compute_entry_signal_stats(entry, "Count") is None

    def test_min_prominence_reduces_significant_peak_count(self) -> None:
        # Two well-separated spikes on a flat baseline; both pass a loose α.
        counts = [1.0] * 5 + [80.0] + [1.0] * 8 + [25.0] + [1.0] * 5
        entry = _flat_entry("D", counts)
        unfiltered = compute_entry_signal_stats(
            entry,
            "Count",
            options=SignalQualityComputeOptions(alpha=0.05),
        )
        filtered = compute_entry_signal_stats(
            entry,
            "Count",
            options=SignalQualityComputeOptions(alpha=0.05, min_prominence=40.0),
        )
        assert unfiltered is not None and filtered is not None
        assert unfiltered.significant_peak_count >= 2
        assert filtered.significant_peak_count < unfiltered.significant_peak_count
        assert filtered.significant_peak_count >= 1
        assert filtered.tallest_significant_peak_height == pytest.approx(80.0)

    def test_min_pct_area_reduces_significant_peak_count(self) -> None:
        counts = [1.0] * 5 + [80.0] + [1.0] * 8 + [25.0] + [1.0] * 5
        entry = _flat_entry("E", counts)
        unfiltered = compute_entry_signal_stats(
            entry,
            "Count",
            options=SignalQualityComputeOptions(alpha=0.05),
        )
        filtered = compute_entry_signal_stats(
            entry,
            "Count",
            options=SignalQualityComputeOptions(alpha=0.05, min_pct_area=50.0),
        )
        assert unfiltered is not None and filtered is not None
        assert unfiltered.significant_peak_count >= 2
        assert filtered.significant_peak_count < unfiltered.significant_peak_count

    def test_options_to_analysis_settings_passes_quality_filters(self) -> None:
        opts = SignalQualityComputeOptions(
            alpha=0.01, min_prominence=5.0, min_pct_area=3.0
        )
        settings = opts.to_analysis_settings("Count")
        assert settings.min_prominence == 5.0
        assert settings.min_pct_area == 3.0
        assert settings.alpha == 0.01
        assert "5" in str(opts.cache_key())
        assert opts.cache_key() != SignalQualityComputeOptions(alpha=0.01).cache_key()


class TestLibraryAggregates:
    def test_mean_snr_excess_from_scan(self) -> None:
        entries = [
            _flat_entry("A", [1.0, 1.0, 10.0, 1.0]),
            _flat_entry("B", [2.0, 2.0, 2.0, 2.0]),
        ]
        from src.core.library_metrics import LibraryScanData

        scan = LibraryScanData(
            entries=entries,
            entries_used=2,
            entries_attempted=2,
            channel_names=["Count"],
        )
        results = compute_metrics_from_scan(
            scan,
            [METRIC_TALLEST_SIG_SNR_EXCESS, METRIC_TALLEST_SIG_SNR_RATIO],
            channels=["Count"],
            signal_quality_alpha=0.001,
        )
        snr_result = next(
            r for r in results if r.metric_id == METRIC_TALLEST_SIG_SNR_EXCESS
        )
        assert snr_result.channels[0].n == 2

    def test_library_coverage_index(self) -> None:
        entries = [
            _flat_entry("A", [96.0]),
            _flat_entry("B", [48.0]),
        ]
        idx = library_coverage_index(entries, "Count", fraction_count=96)
        assert idx == pytest.approx((96.0 + 48.0) / (2 * 96))


class TestExportCsv:
    def test_export_writes_header_and_rows(self, tmp_path: Path) -> None:
        entries = [_flat_entry("X", [1.0, 2.0, 80.0, 2.0])]
        stats = attach_signal_quality_to_entries(entries, ["Count"], alpha=0.05)
        out = tmp_path / "signal.csv"
        export_per_entry_signal_csv(
            stats, out, options=SignalQualityComputeOptions(alpha=0.05)
        )
        text = out.read_text(encoding="utf-8-sig")
        assert "signal_quality_alpha=0.05" in text
        assert "min_prominence=" in text
        assert "min_pct_area=" in text
        with out.open(encoding="utf-8-sig") as fh:
            lines = [line for line in fh if not line.startswith("#")]
        import io

        rows = list(csv.DictReader(io.StringIO("".join(lines))))
        assert len(rows) == 1
        assert rows[0]["compound_id"] == "X"
        assert float(rows[0]["tallest_significant_snr_excess"]) > 0.0
