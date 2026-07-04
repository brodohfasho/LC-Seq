# tests/test_metadata_column_merge.py
"""Tests for merging indexed SQL metadata columns into compound metadata."""

from __future__ import annotations

import json
import sqlite3

from src.core.data_store import DataStore
from src.core.del_cycle_tree.service import (
    registered_metadata_column_names,
    validate_registered_metadata_columns,
)
from src.core.lineage_service import load_all_compound_metadata
from src.models.spreadsheet_config import SpreadsheetConfig


def test_merge_row_metadata_columns_fills_missing_json_values(tmp_path) -> None:
    db_path = tmp_path / "merge_meta.db"
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        store.create_metadata_columns(["Cyclized RT (min)"], create_indexes=False)
        cursor = store.conn.cursor()
        cursor.execute(
            """
            INSERT INTO compounds (
                compound_id, metadata_json, data_point_count,
                primary_compound_id, compound_variant, raw_chromatographic_data,
                Cyclized_RT__min_
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("C1", json.dumps({"BB1 Name": "A"}), 0, "C1", None, "", "12.5"),
        )
        store.conn.commit()

        compounds = load_all_compound_metadata(
            store,
            metadata_columns=["Cyclized RT (min)"],
        )
        assert len(compounds) == 1
        assert compounds[0].metadata["Cyclized RT (min)"] == "12.5"
    finally:
        store.close()


def test_validate_registered_metadata_counts_sql_backed_values(tmp_path) -> None:
    db_path = tmp_path / "validate_meta.db"
    store = DataStore(db_path=db_path, use_memory=False)
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1 Name", "BB2 Name", "BB3 Name", ""],
        null_token="AgxNull",
        selected_metadata_columns=["BB1 Name", "Cyclized RT (min)"],
    )
    try:
        store.create_metadata_columns(
            ["BB1 Name", "Cyclized RT (min)"],
            create_indexes=False,
        )
        cursor = store.conn.cursor()
        cursor.execute(
            """
            INSERT INTO compounds (
                compound_id, metadata_json, data_point_count,
                primary_compound_id, compound_variant, raw_chromatographic_data,
                BB1_Name, Cyclized_RT__min_
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "C1",
                json.dumps({}),
                0,
                "C1",
                None,
                "",
                "Leu",
                "18.2",
            ),
        )
        store.conn.commit()

        compounds = load_all_compound_metadata(
            store,
            metadata_columns=config.selected_metadata_columns,
        )
        validated = validate_registered_metadata_columns(compounds, config)
        rt_info = next(
            info for info in validated if info.column_name == "Cyclized RT (min)"
        )
        assert rt_info.n_numeric_values == 1
        assert rt_info.n_compounds_scanned == 1
        assert "Cyclized RT (min)" in registered_metadata_column_names(config)
    finally:
        store.close()
