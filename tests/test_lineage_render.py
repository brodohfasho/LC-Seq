# tests/test_lineage_render.py
"""Tests for lineage figure layout."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timezone

import pytest

from src.core.lineage_render import is_lineage_export_figure, render_lineage_figure
from src.core.pedigree_backend import pedigree_backend_available
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import LineageAnalysisResult, LineagePanel, PedigreeNodeRecord


def _empty_result() -> LineageAnalysisResult:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    return LineageAnalysisResult(
        compound_id="X",
        leaf_class_bbs=["A"],
        channel="Count",
        settings=settings,
        panels=[],
        records_by_id={},
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
    )


def test_empty_lineage_figure() -> None:
    fig = render_lineage_figure(_empty_result(), {})
    assert fig is not None
    assert not is_lineage_export_figure(fig)


@pytest.mark.skipif(not pedigree_backend_available(), reason="Rust lcseq not built")
def test_lineage_figure_marks_export_layout() -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    rec = PedigreeNodeRecord(id="C0", label="root", tier=0, kind="class", passed=True)
    panel = LineagePanel(class_bbs=[], tier=0, n_replicates=0, effective_threshold=0.0, record=rec)
    result = LineageAnalysisResult(
        compound_id="X",
        leaf_class_bbs=["A"],
        channel="Count",
        settings=settings,
        panels=[panel],
        records_by_id={"C0": rec},
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
    )
    fig = render_lineage_figure(result, {})
    assert is_lineage_export_figure(fig)
    assert len(fig.axes) >= 2
