# tests/test_pedigree_adapter.py
"""Tests for BB-column → N→C truncate mapping."""

from __future__ import annotations

from src.core.pedigree_adapter import truncate_positions_from_metadata
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def _config_3cycle() -> SpreadsheetConfig:
    return SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1 Name", "BB2 Name", "BB3 Name", ""],
        null_token="AgxNull",
    )


def test_truncate_positions_reverses_bb_columns_to_n_to_c():
    cfg = _config_3cycle()
    compound = Compound(
        compound_id="display-name",
        metadata={
            "BB1 Name": "AgxNull",
            "BB2 Name": "DNvl",
            "BB3 Name": "AgxNull",
        },
        data_points=[],
    )
    positions = truncate_positions_from_metadata(compound, cfg)
    assert positions == ("AgxNull", "DNvl", "AgxNull")


def test_cassette_bb_not_split():
    cfg = _config_3cycle()
    compound = Compound(
        compound_id="x",
        metadata={
            "BB1 Name": "AgxNull",
            "BB2 Name": "DLeu-DLeu-Pro",
            "BB3 Name": "AgxNull",
        },
        data_points=[],
    )
    positions = truncate_positions_from_metadata(compound, cfg)
    assert positions[1] == "DLeu-DLeu-Pro"
