# tests/test_bb_index_csv.py
"""Tests for optional building-block index CSV parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.bb_index_csv import (
    detect_building_blocks_from_dataframe,
    format_validation_report,
    parse_bb_index_csv,
    validate_bb_index_map,
)
from src.core.del_cycle_tree.bb_index_scheme import build_global_bb_index_map
from src.core.del_cycle_tree.models import DelCycleRow
from src.models.spreadsheet_config import SpreadsheetConfig


def test_parse_bb_index_csv_with_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "index.csv"
    csv_path.write_text("name,index\nLA03,30\nLA18,31\n", encoding="utf-8")
    index_map, errors = parse_bb_index_csv(csv_path)
    assert not errors
    assert index_map == {"LA03": 30, "LA18": 31}


def test_validate_detects_missing_in_csv() -> None:
    result = validate_bb_index_map(
        {"LA03": 30},
        ["LA03", "LA18", "DPhe"],
        null_token="AgxNull",
    )
    assert not result.ok
    assert "LA18" in result.missing_in_csv
    assert "DPhe" in result.missing_in_csv


def test_validate_ok_when_all_detected_present() -> None:
    result = validate_bb_index_map(
        {"LA03": 30, "LA18": 31, "DPhe": 4},
        ["LA03", "LA18", "DPhe"],
        null_token="AgxNull",
    )
    assert result.ok
    assert not result.missing_in_csv


def test_validate_notes_null_defaults_to_zero() -> None:
    result = validate_bb_index_map({"LA03": 30}, ["LA03"], null_token="AgxNull")
    assert any("index 0" in note for note in result.notes)


def test_detect_building_blocks_from_dataframe() -> None:
    df = pd.DataFrame(
        {
            "BB1": ["LA03", "AgxNull", "LA18"],
            "BB2": ["DPhe", "LA03", "AgxNull"],
        }
    )
    names = detect_building_blocks_from_dataframe(
        df,
        bb_columns=["BB1", "BB2"],
        null_token="AgxNull",
    )
    assert names == {"LA03", "LA18", "DPhe"}


def test_override_map_used_in_tree_build() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow(("LA03", null, null), 1.0),
        DelCycleRow(("LA18", null, null), 2.0),
    ]
    auto = build_global_bb_index_map(rows, null)
    override = build_global_bb_index_map(
        rows,
        null,
        override_map={"LA03": 30, "LA18": 31},
    )
    assert auto["LA03"] != 30 or auto["LA18"] != 31
    assert override["LA03"] == 30
    assert override["LA18"] == 31


def test_spreadsheet_config_roundtrip_bb_index_map() -> None:
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        bb_index_map={"LA03": 30, "LA18": 31},
        bb_index_csv_path="C:/tmp/index.csv",
    )
    restored = SpreadsheetConfig.from_dict(config.to_dict())
    assert restored.bb_index_map == {"LA03": 30, "LA18": 31}
    assert restored.bb_index_csv_path == "C:/tmp/index.csv"
    assert restored.uses_bb_index_csv()


def test_format_validation_report_lists_missing() -> None:
    result = validate_bb_index_map({"LA03": 30}, ["LA03", "LA18"], null_token="AgxNull")
    text = format_validation_report(result)
    assert "LA18" in text


def test_parse_bb_index_csv_preserves_greek_beta(tmp_path: Path) -> None:
    name = "\u03b2Homoleu"
    csv_path = tmp_path / "index.csv"
    csv_path.write_text(f"name,index\n{name},17\n", encoding="utf-8")
    index_map, errors = parse_bb_index_csv(csv_path)
    assert not errors
    assert index_map[name] == 17
    result = validate_bb_index_map(index_map, [name], null_token="AgxNull")
    assert result.ok


def test_validate_case_insensitive_match() -> None:
    result = validate_bb_index_map(
        {"lahomoleu": 5},
        ["LAHomoleu"],
        null_token="AgxNull",
    )
    assert result.ok


def test_encoding_mismatch_hint() -> None:
    beta = "\u03b2Homoleu"
    result = validate_bb_index_map(
        {"?Homoleu": 17},
        [beta],
        null_token="AgxNull",
    )
    assert not result.ok
    text = format_validation_report(result)
    assert "UTF-8" in text or "xlsx" in text
