# tests/test_pedigree_product_prominence.py
"""Tests for pedigree-validated product peak prominence (Phase 5.7)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.pedigree_analysis_store import load_pedigree_result, result_to_dict, save_pedigree_result
from src.core.pedigree_export import export_product_prominence_csv
from src.core.pedigree_product_prominence import compute_product_prominence_summary
from src.models.analysis_settings import AnalysisSettings
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.pedigree_result import (
    EntryProductProminence,
    PedigreeAnalysisResult,
    PedigreeNodeRecord,
    PedigreeTierSummary,
    ProductProminenceSummary,
)
from src.models.spreadsheet_config import SpreadsheetConfig


def _config_2cycle() -> SpreadsheetConfig:
    return SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=2,
        bb_position_columns=["BB1", "BB2", "", ""],
        null_token="Null",
        analysis_time_unit="seconds",
    )


def _compound_with_peak(cid: str, bb1: str, bb2: str, peak_rt: float, height: float) -> Compound:
    points = [
        ChromatographicDataPoint(time=t, counts={"Count": v})
        for t, v in [
            (0.0, 1.0),
            (peak_rt - 1, 1.0),
            (peak_rt, height),
            (peak_rt + 1, 1.0),
            (60.0, 1.0),
        ]
    ]
    return Compound(
        compound_id=cid,
        metadata={"BB1": bb1, "BB2": bb2},
        data_points=points,
    )


def test_compute_product_prominence_summary_passed_compound() -> None:
    config = _config_2cycle()
    compound = _compound_with_peak("AB", "A", "B", peak_rt=30.0, height=200.0)
    record = PedigreeNodeRecord(
        id="c_ab",
        label="Null-A-B",
        tier=2,
        kind="compound",
        members=["AB"],
        passed=True,
        bayesian_pick=30.0,
    )
    summary = compute_product_prominence_summary(
        [record],
        [compound],
        config,
        "Count",
    )
    assert summary.n_pass_with_prominence == 1
    assert summary.n_compound_nodes == 1
    assert summary.n_skipped == 0
    assert len(summary.entries) == 1
    assert summary.entries[0].compound_id == "AB"
    assert summary.entries[0].prominence > 0


def test_compute_product_prominence_skips_failed_nodes() -> None:
    config = _config_2cycle()
    compound = _compound_with_peak("AB", "A", "B", peak_rt=30.0, height=200.0)
    record = PedigreeNodeRecord(
        id="c_ab",
        label="Null-A-B",
        tier=2,
        kind="compound",
        members=["AB"],
        passed=False,
        bayesian_pick=30.0,
    )
    summary = compute_product_prominence_summary(
        [record],
        [compound],
        config,
        "Count",
    )
    assert summary.n_pass_with_prominence == 0
    assert summary.n_skipped == 1


def test_export_product_prominence_csv(tmp_path) -> None:
    summary = ProductProminenceSummary(
        channel="Count",
        mean=50.0,
        std_dev=5.0,
        n_pass_with_prominence=1,
        n_compound_nodes=1,
        n_skipped=0,
        entries=[
            EntryProductProminence(
                compound_id="AB",
                node_id="c_ab",
                chosen_rt=30.0,
                prominence=55.0,
                passed=True,
            )
        ],
    )
    out = export_product_prominence_csv(summary, tmp_path / "prominence.csv")
    text = out.read_text(encoding="utf-8-sig")
    assert "prominence" in text.splitlines()[0]
    assert "AB" in text


def test_product_prominence_snapshot_round_trip(tmp_path) -> None:
    settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
    prom = ProductProminenceSummary(
        channel="Count",
        mean=10.0,
        std_dev=1.0,
        n_pass_with_prominence=1,
        n_compound_nodes=1,
        n_skipped=0,
        entries=[
            EntryProductProminence(
                compound_id="AB",
                node_id="c_ab",
                chosen_rt=30.0,
                prominence=12.0,
                passed=True,
            )
        ],
    )
    result = PedigreeAnalysisResult(
        database_path=str(tmp_path / "db.db"),
        channel="Count",
        settings=settings,
        null_token="Null",
        library_cycle_count=2,
        records=[],
        tier_summaries=[PedigreeTierSummary(tier=0, pass_count=0, fail_count=0, pruned_count=0)],
        backend_name="test",
        computed_at=datetime.now(timezone.utc),
        n_compounds_loaded=1,
        n_chromatograms=1,
        product_prominence=prom,
    )
    json_path = save_pedigree_result(result, tmp_path / "snap.json")
    loaded = load_pedigree_result(json_path)
    assert loaded.product_prominence is not None
    assert loaded.product_prominence.mean == 10.0
    assert loaded.product_prominence.entries[0].compound_id == "AB"

    payload = result_to_dict(result)
    assert "product_prominence" in payload
