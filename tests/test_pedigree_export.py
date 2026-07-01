# tests/test_pedigree_export.py
"""Tests for pedigree CSV export."""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.pedigree_export import chosen_rt_for_record, export_pedigree_csv
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult, PedigreeNodeRecord, PedigreeTierSummary


def test_chosen_rt_prefers_bayesian() -> None:
    record = PedigreeNodeRecord(
        id="n",
        label="N",
        tier=1,
        kind="class",
        bayesian_pick=42.0,
        score_test_rt=40.0,
        initial_most_significant_picks=[39.0],
    )
    assert chosen_rt_for_record(record) == 42.0


def test_export_pedigree_csv(tmp_path) -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    record = PedigreeNodeRecord(
        id="C0",
        label="root",
        tier=0,
        kind="class",
        passed=True,
        members=["m1"],
    )
    result = PedigreeAnalysisResult(
        database_path=str(tmp_path / "db.db"),
        channel="Count",
        settings=settings,
        null_token="Null",
        library_cycle_count=2,
        records=[record],
        tier_summaries=[PedigreeTierSummary(tier=0, pass_count=1, fail_count=0, pruned_count=0)],
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
        n_compounds_loaded=1,
        n_chromatograms=1,
    )
    out = export_pedigree_csv(result, tmp_path / "nodes.csv")
    text = out.read_text(encoding="utf-8")
    assert "chosen_rt" in text.splitlines()[0]
    assert "C0" in text
