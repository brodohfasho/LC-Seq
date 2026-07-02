# tests/test_pedigree_export.py
"""Tests for pedigree CSV export."""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.pedigree_export import (
    bb_cycle_columns_for_record,
    chosen_rt_for_record,
    export_pedigree_csv,
    export_product_prominence_csv,
    positions_n_to_c_from_record,
)
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import (
    EntryProductProminence,
    PedigreeAnalysisResult,
    PedigreeNodeRecord,
    PedigreeTierSummary,
    ProductProminenceSummary,
)


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


def test_positions_from_compound_id() -> None:
    record = PedigreeNodeRecord(
        id="F3_AgxNull_DNvl_AgxNull",
        label="AgxNull-DNvl-AgxNull",
        tier=3,
        kind="compound",
    )
    positions = positions_n_to_c_from_record(
        record,
        library_cycle_count=3,
        null_token="AgxNull",
    )
    assert positions == ["AgxNull", "DNvl", "AgxNull"]
    cols = bb_cycle_columns_for_record(
        record,
        library_cycle_count=3,
        null_token="AgxNull",
    )
    assert cols["bb_cycle_1"] == "AgxNull"
    assert cols["bb_cycle_2"] == "DNvl"
    assert cols["bb_cycle_3"] == "AgxNull"


def test_positions_from_class_id() -> None:
    record = PedigreeNodeRecord(
        id="C2_DNvl_DPhe",
        label="DNvl+DPhe",
        tier=2,
        kind="class",
    )
    positions = positions_n_to_c_from_record(
        record,
        library_cycle_count=3,
        null_token="AgxNull",
    )
    assert positions == ["AgxNull", "DNvl", "DPhe"]
    cols = bb_cycle_columns_for_record(
        record,
        library_cycle_count=3,
        null_token="AgxNull",
    )
    assert cols["bb_cycle_1"] == "DPhe"
    assert cols["bb_cycle_2"] == "DNvl"
    assert cols["bb_cycle_3"] == "AgxNull"


def test_cassette_bb_in_compound_id() -> None:
    record = PedigreeNodeRecord(
        id="F3_AgxNull_DLeu-DLeu-Pro_AgxNull",
        label="AgxNull-DLeu-DLeu-Pro-AgxNull",
        tier=3,
        kind="compound",
    )
    cols = bb_cycle_columns_for_record(
        record,
        library_cycle_count=3,
        null_token="AgxNull",
    )
    assert cols["bb_cycle_2"] == "DLeu-DLeu-Pro"


def test_export_pedigree_csv(tmp_path) -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    record = PedigreeNodeRecord(
        id="F2_A_B",
        label="A-B",
        tier=2,
        kind="compound",
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
        tier_summaries=[PedigreeTierSummary(tier=2, pass_count=1, fail_count=0, pruned_count=0)],
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
        n_compounds_loaded=1,
        n_chromatograms=1,
    )
    out = export_pedigree_csv(result, tmp_path / "nodes.csv")
    text = out.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert "bb_cycle_1" in header
    assert "bb_cycle_2" in header
    assert "F2_A_B" in text
    assert ",B," in text or ",B\n" in text


def test_export_product_prominence_includes_bb_cycles(tmp_path) -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    record = PedigreeNodeRecord(
        id="F2_A_B",
        label="A-B",
        tier=2,
        kind="compound",
        passed=True,
        members=["cmp1"],
    )
    result = PedigreeAnalysisResult(
        database_path=str(tmp_path / "db.db"),
        channel="Count",
        settings=settings,
        null_token="Null",
        library_cycle_count=2,
        records=[record],
        tier_summaries=[],
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
        n_compounds_loaded=1,
        n_chromatograms=1,
    )
    summary = ProductProminenceSummary(
        channel="Count",
        mean=10.0,
        std_dev=0.0,
        n_pass_with_prominence=1,
        n_compound_nodes=1,
        n_skipped=0,
        entries=[
            EntryProductProminence(
                compound_id="cmp1",
                node_id="F2_A_B",
                chosen_rt=30.0,
                prominence=12.0,
                passed=True,
            )
        ],
    )
    out = export_product_prominence_csv(summary, tmp_path / "prom.csv", result=result)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "bb_cycle_1" in lines[0]
    assert "cmp1" in lines[1]
    assert "B" in lines[1]
