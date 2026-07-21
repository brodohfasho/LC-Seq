# tests/test_lineage_batch_export.py
"""Tests for multi-compound lineage batch export."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.core.lineage_batch_export import (
    export_lineage_csv_combined,
    export_lineage_csv_separate,
    safe_export_stem,
)
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import (
    LineageAnalysisResult,
    LineageBatchResult,
    LineagePanel,
    PedigreeNodeRecord,
)
from src.models.spreadsheet_config import SpreadsheetConfig


def _minimal_result(compound_id: str) -> LineageAnalysisResult:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    record = PedigreeNodeRecord(
        id="C0",
        label="root",
        tier=0,
        kind="class",
        passed=True,
    )
    panel = LineagePanel(
        class_bbs=[],
        tier=0,
        n_replicates=1,
        effective_threshold=0.0,
        record=record,
    )
    return LineageAnalysisResult(
        compound_id=compound_id,
        leaf_class_bbs=["A", "B"],
        channel="Count",
        settings=settings,
        panels=[panel],
        records_by_id={"C0": record},
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
    )


def test_safe_export_stem() -> None:
    assert safe_export_stem("AB-123") == "AB-123"
    assert "/" not in safe_export_stem("foo/bar")


def test_export_lineage_csv_combined(tmp_path) -> None:
    results = [_minimal_result("c1"), _minimal_result("c2")]
    out = export_lineage_csv_combined(results, tmp_path / "all.csv")
    text = out.read_text(encoding="utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0].startswith("compound_id")
    assert "c1" in text
    assert "c2" in text
    assert len(lines) == 3  # header + 2 rows


def test_export_lineage_csv_separate(tmp_path) -> None:
    results = [_minimal_result("c1"), _minimal_result("c2")]
    paths = export_lineage_csv_separate(results, tmp_path)
    assert len(paths) == 2
    assert all(p.is_file() for p in paths)


def test_lineage_batch_result_model() -> None:
    r1 = _minimal_result("a")
    batch = LineageBatchResult(results=(r1,), failed=(("b", "missing BB"),))
    assert batch.success_count == 1
    assert batch.failure_count == 1
    assert batch.result_for("a") is r1
    assert batch.result_for("missing") is None


def test_export_lineage_csv_combined_empty_raises() -> None:
    with pytest.raises(ValueError, match="No lineage"):
        export_lineage_csv_combined([], "x.csv")
