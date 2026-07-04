# tests/test_rt_assignment_export.py
"""Tests for RT analysis spreadsheet export."""

from __future__ import annotations

import pandas as pd

from src.core.del_cycle_tree.models import CompoundRtAssignment, DelCycleTreeData, VerifiedSequence
from src.core.rt_assignment_export import (
    EXPORT_NULL_RT_VERIFIED_COLUMN,
    assigned_rt_column_name,
    export_rt_analysis_from_database,
    format_null_rt_verified,
    parse_null_rt_verified_metadata,
    build_verification_overrides_from_metadata,
)
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def _config() -> SpreadsheetConfig:
    return SpreadsheetConfig(
        compound_id_column="Name",
        chromatographic_data_column="Chromatogram",
        compound_variant_column="Isoform",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token="AgxNull",
        selected_metadata_columns=["BB1", "BB2", "BB3", "Isoform"],
    )


def test_parse_null_rt_verified_metadata_accepts_export_tokens() -> None:
    assert parse_null_rt_verified_metadata("TRUE") is True
    assert parse_null_rt_verified_metadata("FALSE") is False
    assert parse_null_rt_verified_metadata("pass") is True
    assert parse_null_rt_verified_metadata("") is None


def test_export_from_database_rows_includes_rt_and_verification(tmp_path) -> None:
    config = _config()
    rows = [
        {
            "Name": "ProdA",
            "Isoform": "cyclized",
            "Chromatogram": "0,1\n1,5",
            "BB1": "A",
            "BB2": "B",
            "BB3": "C",
            "_storage_id": "ProdA\x1fcyclized",
        }
    ]
    assignments = [
        CompoundRtAssignment(
            compound_id="ProdA\x1fcyclized",
            assigned_rt=15.0,
            rt_source="peak_pick",
            null_rt_verified=True,
        )
    ]
    out = tmp_path / "export.xlsx"
    result = export_rt_analysis_from_database(
        out,
        config,
        rows,
        assignments,
        time_unit="minutes",
        rt_threshold=0.5,
    )
    assert result.rows_written == 1
    assert result.rows_assigned == 1
    assert result.rows_with_verification == 1
    df = pd.read_excel(out)
    assert assigned_rt_column_name("minutes") in df.columns
    assert df.loc[0, assigned_rt_column_name("minutes")] == 15.0
    assert str(df.loc[0, EXPORT_NULL_RT_VERIFIED_COLUMN]).upper() == "TRUE"
    assert df.loc[0, "null_rt_threshold"] == 0.5


def test_build_verification_overrides_from_metadata() -> None:
    config = _config()
    compounds = [
        Compound(
            compound_id="ProdA",
            metadata={
                "BB1": "A",
                "BB2": "B",
                "BB3": "C",
                EXPORT_NULL_RT_VERIFIED_COLUMN: "FALSE",
            },
        )
    ]
    overrides = build_verification_overrides_from_metadata(
        compounds,
        config,
        column=EXPORT_NULL_RT_VERIFIED_COLUMN,
    )
    assert overrides[("A", "B", "C")] is False


def test_build_assignments_from_del_cycle_tree() -> None:
    from src.core.del_cycle_tree.builder import flatten_del_tree_rts
    from src.core.del_cycle_tree.service import build_assignments_from_del_cycle_tree

    config = _config()
    del_data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={
            "A": {
                "B": {
                    "C": 15.0,
                    "D": 12.1,
                }
            }
        },
        pruned_tree={},
        verified_sequences={
            ("A", "B", "C"): VerifiedSequence(
                positions=("A", "B", "C"),
                rt=15.0,
                success=True,
            ),
            ("A", "B", "D"): VerifiedSequence(
                positions=("A", "B", "D"),
                rt=12.1,
                success=False,
            ),
        },
        full_null_rt=None,
        rt_source="peak_pick",
    )
    assert flatten_del_tree_rts(del_data.tree)[("A", "B", "C")] == 15.0
    compounds = [
        Compound(
            compound_id="p1",
            metadata={"BB1": "A", "BB2": "B", "BB3": "C"},
        ),
        Compound(
            compound_id="p2",
            metadata={"BB1": "A", "BB2": "B", "BB3": "D"},
        ),
    ]
    assignments = build_assignments_from_del_cycle_tree(compounds, config, del_data)
    by_id = {item.compound_id: item for item in assignments}
    assert by_id["p1"].assigned_rt == 15.0
    assert by_id["p1"].null_rt_verified is True
    assert by_id["p2"].null_rt_verified is False
    from src.core.rt_assignment_export import enrich_assignments_with_null_verification

    config = _config()
    compounds = [
        Compound(
            compound_id="ProdA",
            metadata={"BB1": "A", "BB2": "B", "BB3": "C"},
        )
    ]
    assignments = [
        CompoundRtAssignment(
            compound_id="ProdA",
            assigned_rt=15.0,
            rt_source="peak_pick",
        )
    ]
    del_data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={},
        pruned_tree={},
        verified_sequences={
            ("A", "B", "C"): VerifiedSequence(
                positions=("A", "B", "C"),
                rt=15.0,
                success=False,
            )
        },
        full_null_rt=None,
    )
    enriched = enrich_assignments_with_null_verification(
        assignments,
        compounds,
        config,
        del_data,
    )
    assert enriched[0].null_rt_verified is False
