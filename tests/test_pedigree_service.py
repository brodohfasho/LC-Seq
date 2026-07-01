# tests/test_pedigree_service.py
"""Tests for full-library pedigree analysis service."""

from __future__ import annotations

import pytest

from src.core.pedigree_backend import pedigree_backend_available
from src.core.pedigree_service import run_pedigree_analysis_for_path, summarize_by_tier
from src.models.analysis_settings import AnalysisSettings
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.pedigree_result import PedigreeNodeRecord
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


def test_summarize_by_tier_counts() -> None:
    records = [
        PedigreeNodeRecord(id="r", label="root", tier=0, kind="class", passed=True),
        PedigreeNodeRecord(
            id="a", label="A", tier=1, kind="class", evaluated=True, passed=False
        ),
        PedigreeNodeRecord(id="x", label="X", tier=2, kind="compound", evaluated=False),
    ]
    summaries = summarize_by_tier(records)
    by_tier = {s.tier: s for s in summaries}
    assert by_tier[0].pass_count == 1
    assert by_tier[1].fail_count == 1
    assert by_tier[2].pruned_count == 1


@pytest.mark.skipif(not pedigree_backend_available(), reason="Rust lcseq not built")
class TestPedigreeServiceIntegration:
    def test_run_pedigree_tiny_library(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = _config_2cycle()
        db_path = tmp_path / "pedigree.db"
        store = DataStore(db_path=db_path, use_memory=False)

        def _compound(cid: str, bb1: str, bb2: str, peak_rt: float, height: float) -> Compound:
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

        for c in [
            _compound("root", "Null", "Null", 10.0, 50.0),
            _compound("A", "A", "Null", 20.0, 80.0),
            _compound("AB", "A", "B", 30.0, 120.0),
        ]:
            assert store.add_compound(c, [])
        store.conn.commit()
        store.close()

        settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
        result = run_pedigree_analysis_for_path(db_path, config, settings)
        assert result.records
        assert result.tier_summaries
        assert result.n_chromatograms == 3
        assert any(s.tier == 0 for s in result.tier_summaries)
