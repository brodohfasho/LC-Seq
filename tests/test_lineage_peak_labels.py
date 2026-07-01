# tests/test_lineage_peak_labels.py
"""Tests for mapping lineage picks to peak table labels."""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.lineage_peak_labels import (
    apply_lineage_labels_to_batch,
    is_intended_product_label,
    match_peak_to_assignment,
    suspected_id_for_panel,
)
from src.models.analysis_settings import AnalysisSettings
from src.models.peak_result import (
    PeakAnalysisBatchResult,
    PeakAnalysisResult,
    PickedPeak,
)
from src.models.pedigree_result import LineageAnalysisResult, LineagePanel, PedigreeNodeRecord


def _record(**kwargs) -> PedigreeNodeRecord:
    defaults = dict(
        id="C1_A",
        label="A",
        tier=1,
        kind="class",
        score_test_rt=20.0,
        passed=True,
        evaluated=True,
    )
    defaults.update(kwargs)
    return PedigreeNodeRecord(**defaults)


def _panel(class_bbs, tier, rt, leaf=False) -> LineagePanel:
    rec = _record(
        id=f"C{len(class_bbs)}_{'_'.join(class_bbs) or 'root'}",
        tier=tier,
        score_test_rt=rt,
    )
    return LineagePanel(
        class_bbs=list(class_bbs),
        tier=tier,
        n_replicates=3,
        effective_threshold=0.0 if tier == 0 else 10.0,
        record=rec,
    )


def test_suspected_id_labels() -> None:
    leaf = ["B", "A"]
    intended = suspected_id_for_panel(_panel(leaf, 2, 30.0), leaf_class_bbs=leaf)
    assert intended.startswith("intended product")
    assert is_intended_product_label(intended)
    assert not is_intended_product_label("null truncation (A)")
    assert not is_intended_product_label("unknown")
    assert suspected_id_for_panel(_panel(["A"], 1, 20.0), leaf_class_bbs=leaf).startswith(
        "null truncation"
    )
    assert suspected_id_for_panel(_panel([], 0, 10.0), leaf_class_bbs=leaf).startswith("root")


def test_match_peak_within_tolerance() -> None:
    assignments = [(20.0, "null truncation (A)", 1), (30.0, "intended product (B-A)", 2)]
    label = match_peak_to_assignment(
        20.5,
        assignments,
        stored_time_unit="seconds",
        lineage_time_unit="seconds",
        tolerance=5.0,
    )
    assert label == "null truncation (A)"


def test_apply_lineage_labels_to_batch() -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    leaf_bbs = ["B", "A"]
    result = LineageAnalysisResult(
        compound_id="AB",
        leaf_class_bbs=leaf_bbs,
        channel="Count",
        settings=settings,
        panels=[
            _panel([], 0, 10.0),
            _panel(["A"], 1, 20.0),
            _panel(leaf_bbs, 2, 30.0),
        ],
        records_by_id={},
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
    )
    batch = PeakAnalysisBatchResult(
        settings=settings,
        channel="Count",
        results=[
            PeakAnalysisResult(
                compound_id="AB",
                channel="Count",
                settings=settings,
                peaks=[
                    PickedPeak(1, 20.0, 100.0, 50.0, 10.0, 0.001, 80.0),
                    PickedPeak(2, 30.0, 120.0, 60.0, 12.0, 0.001, 20.0),
                    PickedPeak(3, 55.0, 40.0, 20.0, 5.0, 0.01, 0.0),
                ],
            )
        ],
    )
    updated = apply_lineage_labels_to_batch(
        batch, result, "AB", stored_time_unit="seconds"
    )
    peaks = updated.results[0].peaks
    assert peaks[0].suspected_peak_id == "null truncation (A)"
    assert peaks[1].suspected_peak_id == "intended product (B-A)"
    assert peaks[2].suspected_peak_id == "unknown"
