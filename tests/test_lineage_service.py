# tests/test_lineage_service.py
"""Tests for lineage analysis service (requires Rust lcseq when integration tests run)."""

from __future__ import annotations

import pytest

from src.core.lcseq_backend import is_native_backend_available
from src.core.lineage_service import analyze_lineage_for_path
from src.core.pedigree_backend import pedigree_backend_available
from src.models.analysis_settings import AnalysisSettings
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
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


@pytest.mark.skipif(not pedigree_backend_available(), reason="Rust lcseq not built")
class TestLineageServiceIntegration:
    def test_analyze_lineage_tiny_library(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = _config_2cycle()
        db_path = tmp_path / "lineage.db"
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

        leaf = store.get_compound("AB")
        assert leaf is not None
        settings = AnalysisSettings(count_channel="Count", alpha=0.05, tolerance=5.0)
        result = analyze_lineage_for_path(db_path, leaf, config, settings)
        assert result.compound_id == "AB"
        assert result.panels
        assert result.leaf_class_bbs == ["B", "A"]

        store.close()
