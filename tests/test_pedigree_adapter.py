# tests/test_pedigree_adapter.py
"""Tests for BB-column → N→C truncate mapping."""

from __future__ import annotations

from src.core.pedigree_adapter import (
    build_chromatogram_map_from_scan,
    infer_bbs_per_position_from_map,
    truncate_positions_from_metadata,
)
from src.core.library_metrics import LibraryScanData, ScannedEntry
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


def test_build_chromatogram_map_from_scan_uses_cached_series() -> None:
    cfg = _config_3cycle()
    scan = LibraryScanData(
        channel_names=["Count"],
        entries=[
            ScannedEntry(
                compound_id="AB",
                times=[0.0, 10.0, 20.0],
                counts_by_channel={"Count": [1.0, 50.0, 1.0]},
            )
        ],
        entries_used=1,
        entries_attempted=1,
    )
    metadata = {
        "AB": Compound(
            compound_id="AB",
            metadata={
                "BB1 Name": "A",
                "BB2 Name": "B",
                "BB3 Name": "AgxNull",
            },
            data_points=[],
        )
    }
    chrom_map, stubs = build_chromatogram_map_from_scan(
        scan,
        metadata,
        "Count",
        cfg,
        time_unit="seconds",
    )
    assert len(stubs) == 1
    assert ("AgxNull", "B", "A") == next(iter(chrom_map))
    rt, intensity = chrom_map[("AgxNull", "B", "A")]
    assert list(rt) == [0.0, 10.0, 20.0]
    assert list(intensity) == [1.0, 50.0, 1.0]


def test_infer_bbs_per_position_from_map() -> None:
    import numpy as np

    cfg = _config_3cycle()
    chrom_map = {
        ("AgxNull", "B", "A"): (np.array([0.0]), np.array([1.0])),
        ("AgxNull", "C", "A"): (np.array([0.0]), np.array([1.0])),
    }
    bbs = infer_bbs_per_position_from_map(chrom_map, cfg)
    assert bbs[0] == []
    assert sorted(bbs[1]) == ["B", "C"]
    assert bbs[2] == ["A"]
