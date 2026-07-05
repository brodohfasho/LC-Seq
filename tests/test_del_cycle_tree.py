# tests/test_del_cycle_tree.py
"""Tests for DEL-cycle split-tree analysis."""

from __future__ import annotations

from src.core.del_cycle_tree.analyzer import dedupe_rows_by_position
from src.core.del_cycle_tree.builder import create_tree, prune_tree
from src.core.del_cycle_tree.models import DelCycleRow, DelCycleTreeData, VerifiedSequence
from src.core.del_cycle_tree.bb_index_scheme import build_global_bb_index_map
from src.core.del_cycle_tree.notebook_analyzer import (
    create_full_compound_dict,
    sort_rows_notebook,
    verify_reaction_sequences_notebook,
    verify_sequence_notebook,
)


def test_sequence_passes_honors_verify_success_for_metadata_rt_source() -> None:
    """Metadata split-trees must use null verify success for pass/fail, not mere presence."""
    from src.core.del_cycle_tree.models import VerifiedSequence
    from src.core.del_cycle_tree.render import COLOR_MODE_NOTEBOOK, _sequence_passes

    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={},
        pruned_tree={},
        verified_sequences={
            ("A", "B", "C"): VerifiedSequence(
                positions=("A", "B", "C"),
                rt=12.1,
                success=False,
            ),
            ("A", "B", "D"): VerifiedSequence(
                positions=("A", "B", "D"),
                rt=15.0,
                success=True,
            ),
        },
        full_null_rt=None,
        rt_source="metadata",
    )
    assert not _sequence_passes(
        data,
        ("A", "B", "C"),
        color_mode=COLOR_MODE_NOTEBOOK,
    )
    assert _sequence_passes(
        data,
        ("A", "B", "D"),
        color_mode=COLOR_MODE_NOTEBOOK,
    )


def test_verify_sequence_rejects_near_truncation_rt() -> None:
    null = "AgxNull"
    truncated = {
        (null, null, null): [((null, null, null), 10.0)],
        ("A",): [(("A", null, null), 12.0)],
        ("A", "B"): [(("A", "B", null), 12.0)],
    }
    full_dict = create_full_compound_dict(
        [
            DelCycleRow((null, null, null), 10.0),
            DelCycleRow(("A", null, null), 12.0),
            DelCycleRow(("A", "B", "C"), 12.1),
            DelCycleRow(("A", "B", "D"), 15.0),
        ],
        truncated,
    )
    assert not verify_sequence_notebook(
        ("A", "B", "C"),
        12.1,
        full_dict,
        null_token=null,
        rt_threshold=0.5,
    )
    assert verify_sequence_notebook(
        ("A", "B", "D"),
        15.0,
        full_dict,
        null_token=null,
        rt_threshold=0.5,
    )


def test_prune_tree_keeps_only_verified_products() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow((null, null, null), 10.0),
        DelCycleRow(("A", null, null), 12.0),
        DelCycleRow(("A", "B", null), 12.0),
        DelCycleRow(("A", "B", "C"), 15.0),
        DelCycleRow(("A", "B", "D"), 12.2),
    ]
    truncated = {
        (null, null, null): [((null, null, null), 10.0)],
        ("A",): [(("A", null, null), 12.0)],
        ("A", "B"): [(("A", "B", null), 12.0)],
    }
    full_dict = create_full_compound_dict(rows, truncated)
    verified = verify_reaction_sequences_notebook(
        full_dict,
        null_token=null,
        n_cycles=3,
        rt_threshold=0.5,
    )
    tree = create_tree(rows)
    pruned = prune_tree(tree, verified)
    assert verified[("A", "B", "C")].success
    assert not verified[("A", "B", "D")].success
    assert "A" in pruned
    assert "B" in pruned["A"]
    assert pruned["A"]["B"]["C"] == 15.0
    assert "D" not in pruned["A"]["B"]


def test_sort_rows_notebook_puts_nulls_first() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow(("B", null, null), 1.0),
        DelCycleRow((null, "A", null), 2.0),
        DelCycleRow((null, null, null), 3.0),
    ]
    bb_index = build_global_bb_index_map(rows, null)
    sorted_rows = sort_rows_notebook(rows, bb_index, null_token=null)
    assert [row.positions for row in sorted_rows] == [
        (null, null, null),
        (null, "A", null),
        ("B", null, null),
    ]


def test_dedupe_rows_by_position_keeps_last_rt() -> None:
    rows = [
        DelCycleRow(("A", "B", "C"), 10.0),
        DelCycleRow(("A", "B", "C"), 20.0),
    ]
    deduped = dedupe_rows_by_position(rows)
    assert len(deduped) == 1
    assert deduped[0].rt == 20.0


def test_build_global_bb_index_is_alphabetical() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow(("LA18", null, null), 1.0),
        DelCycleRow(("AlaMe", null, null), 2.0),
        DelCycleRow((null, "Leu", null), 3.0),
    ]
    index_map = build_global_bb_index_map(rows, null)
    assert index_map["AlaMe"] < index_map["LA18"] < index_map["Leu"]


def test_bb_index_uses_full_library_discovery_rows() -> None:
    """Index map must not shrink to the RT-resolved subset (pedigree vs peak-pick)."""
    from src.core.del_cycle_tree.service import _finalize_del_cycle_tree
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
        bb_index_map={"LA03": 30, "Leu": 12, "AlaMe": 5},
    )
    discovery_rows = [
        DelCycleRow(("LA03", null, null), 0.0),
        DelCycleRow(("Leu", null, null), 0.0),
        DelCycleRow(("AlaMe", null, null), 0.0),
    ]
    rt_rows = [DelCycleRow(("Leu", "DPhe", "X"), 1.0)]
    data = _finalize_del_cycle_tree(
        rt_rows,
        config,
        rt_threshold=0.5,
        rt_source="test",
        index_discovery_rows=discovery_rows,
    )
    assert data.bb_index_global["LA03"] == 30
    assert data.bb_index_global["Leu"] == 12
    assert data.bb_index_global["AlaMe"] == 5


def test_case_variants_canonicalize_to_one_tree_branch() -> None:
    from src.core.del_cycle_tree.bb_index_scheme import (
        build_bb_name_canonical_map,
        canonicalize_positions,
    )
    from src.core.del_cycle_tree.service import _finalize_del_cycle_tree
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    rows = [
        DelCycleRow(("LA03", null, null), 1.0),
        DelCycleRow(("la03", "DPhe", null), 2.0),
        DelCycleRow(("LA03", "Leu", "Prod"), 3.0),
    ]
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
    )
    canonical = build_bb_name_canonical_map(rows, null)
    assert canonical["la03"] == "LA03"
    assert canonicalize_positions(
        ("la03", "dphe", null),
        null_token=null,
        canonical_by_lower=canonical,
    ) == ("LA03", "DPhe", null)

    data = _finalize_del_cycle_tree(rows, config, rt_threshold=0.5, rt_source="test")
    assert list(data.tree.keys()).count("LA03") == 1
    assert "la03" not in data.tree
    assert data.bb_index_global["LA03"] == data.bb_index_global.get("LA03")
    assert len([name for name in data.bb_index_global if name.lower() == "la03"]) == 1


def test_build_pedigree_rt_lookup_includes_class_and_failed_nodes() -> None:
    from src.core.del_cycle_tree.service import build_pedigree_rt_lookup
    from src.models.pedigree_result import PedigreeNodeRecord
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
    )
    records = [
        PedigreeNodeRecord(
            id="C0",
            label="root",
            tier=0,
            kind="class",
        ),
        PedigreeNodeRecord(
            id="C1_A",
            label="A",
            tier=1,
            kind="class",
            score_test_rt=12.0,
            evaluated=True,
            passed=True,
        ),
        PedigreeNodeRecord(
            id="F3_A_B_C",
            label="A-B-C",
            tier=3,
            kind="compound",
            score_test_rt=15.0,
            evaluated=True,
            passed=True,
        ),
        PedigreeNodeRecord(
            id="F3_A_B_D",
            label="failed product",
            tier=3,
            kind="compound",
            score_test_rt=12.1,
            evaluated=True,
            passed=False,
        ),
    ]
    lookup = build_pedigree_rt_lookup(records, config)
    assert lookup[("A", null, null)] == 12.0
    assert lookup[("C", "B", "A")] == 15.0
    assert lookup[("D", "B", "A")] == 12.1


def test_build_pedigree_passed_lookup_maps_full_products() -> None:
    from src.core.del_cycle_tree.service import build_pedigree_passed_lookup
    from src.models.pedigree_result import PedigreeNodeRecord
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
    )
    records = [
        PedigreeNodeRecord(
            id="F3_A_B_C",
            label="pass",
            tier=3,
            kind="compound",
            passed=True,
        ),
        PedigreeNodeRecord(
            id="F3_A_B_D",
            label="fail",
            tier=3,
            kind="compound",
            passed=False,
        ),
    ]
    passed = build_pedigree_passed_lookup(records, config)
    assert passed[("C", "B", "A")] is True
    assert passed[("D", "B", "A")] is False


def test_pedigree_color_mode_uses_empty_pruned_tree() -> None:
    """Pedigree mode must not fall back to notebook tree when all products fail."""
    from src.core.del_cycle_tree.render import (
        COLOR_MODE_NOTEBOOK,
        COLOR_MODE_PEDIGREE,
        _active_pruned_tree,
    )

    null = "AgxNull"
    data = DelCycleTreeData(
        library_cycle_count=3,
        null_token=null,
        rt_threshold=0.5,
        tree={"A": {"B": {"C": 15.0}}},
        pruned_tree={"A": {"B": {"C": 15.0}}},
        verified_sequences={},
        full_null_rt=10.0,
        pedigree_passed_by_product={("C", "B", "A"): False},
        pedigree_pruned_tree={},
    )
    assert _active_pruned_tree(data, COLOR_MODE_NOTEBOOK) == data.pruned_tree
    assert _active_pruned_tree(data, COLOR_MODE_PEDIGREE) == {}


def test_pedigree_pruned_tree_uses_pass_fail() -> None:
    null = "AgxNull"
    rows = [
        DelCycleRow((null, null, null), 10.0),
        DelCycleRow(("A", "B", "C"), 15.0),
        DelCycleRow(("A", "B", "D"), 16.0),
    ]
    tree = create_tree(rows)
    verified = {
        ("A", "B", "C"): VerifiedSequence(("A", "B", "C"), 15.0, True),
        ("A", "B", "D"): VerifiedSequence(("A", "B", "D"), 16.0, True),
    }
    pedigree_verified = {
        ("A", "B", "C"): VerifiedSequence(("A", "B", "C"), 15.0, True),
        ("A", "B", "D"): VerifiedSequence(("A", "B", "D"), 16.0, False),
    }
    assert "D" in prune_tree(tree, verified)["A"]["B"]
    assert "D" not in prune_tree(tree, pedigree_verified)["A"]["B"]


def test_rt_from_metadata_column_skips_empty_and_invalid_values() -> None:
    import math

    from src.core.del_cycle_tree.service import rt_from_metadata_column
    from src.models.compound import Compound

    compound = Compound(
        compound_id="C1",
        metadata={
            "rt_empty": "",
            "rt_space": "   ",
            "rt_na": "N/A",
            "rt_nan_str": "nan",
            "rt_nan_float": float("nan"),
            "rt_good_str": " 12.5 ",
            "rt_good_float": 8.0,
        },
    )
    assert rt_from_metadata_column(compound, "rt_empty") is None
    assert rt_from_metadata_column(compound, "rt_space") is None
    assert rt_from_metadata_column(compound, "rt_na") is None
    assert rt_from_metadata_column(compound, "rt_nan_str") is None
    assert rt_from_metadata_column(compound, "rt_nan_float") is None
    assert rt_from_metadata_column(compound, "rt_missing") is None
    assert rt_from_metadata_column(compound, "rt_good_str") == 12.5
    assert rt_from_metadata_column(compound, "rt_good_float") == 8.0
    assert not math.isnan(rt_from_metadata_column(compound, "rt_good_float") or 0.0)


def test_build_del_cycle_rows_from_metadata_skips_empty_rt() -> None:
    from src.core.del_cycle_tree.service import build_del_cycle_rows_from_metadata_column
    from src.models.compound import Compound
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
        selected_metadata_columns=["assigned_rt"],
    )
    compounds = [
        Compound(
            compound_id="with_rt",
            metadata={"BB1": "A", "BB2": "B", "BB3": "C", "assigned_rt": 15.0},
        ),
        Compound(
            compound_id="empty_rt",
            metadata={"BB1": "A", "BB2": "B", "BB3": "D"},
        ),
        Compound(
            compound_id="blank_rt",
            metadata={"BB1": "A", "BB2": "B", "BB3": "E", "assigned_rt": ""},
        ),
    ]
    rows, resolution = build_del_cycle_rows_from_metadata_column(
        compounds,
        config,
        "assigned_rt",
    )
    assert len(rows) == 1
    assert rows[0].positions == ("A", "B", "C")
    assert rows[0].rt == 15.0
    assert resolution.rt_source == "metadata"
    assert resolution.n_rt_from_metadata == 1


def test_build_del_cycle_rows_skips_metadata_when_disabled() -> None:
    import numpy as np

    from src.core.del_cycle_tree.service import build_del_cycle_rows
    from src.models.analysis_settings import AnalysisSettings
    from src.models.chromatographic_data_point import ChromatographicDataPoint
    from src.models.compound import Compound
    from src.models.spreadsheet_config import SpreadsheetConfig

    null = "AgxNull"
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token=null,
        selected_metadata_columns=["Cyclized RT (min)"],
        analysis_time_unit="minutes",
    )
    times = np.linspace(0.0, 30.0, 60)
    counts = np.exp(-((times - 15.0) ** 2) / 4.0)
    points = [
        ChromatographicDataPoint(time=float(t), counts={"Count": float(c)})
        for t, c in zip(times, counts)
    ]
    compound = Compound(
        compound_id="C1",
        metadata={
            "BB1": "A",
            "BB2": "B",
            "BB3": "C",
            "Cyclized RT (min)": 99.0,
        },
        data_points=points,
    )
    settings = AnalysisSettings(
        count_channel="Count",
        time_unit="minutes",
        peak_picking_algorithm="old_school",
    )
    rows_default, resolution_default = build_del_cycle_rows(
        [compound],
        config,
        "Count",
        settings,
        "minutes",
    )
    assert len(rows_default) == 1
    assert rows_default[0].rt == 99.0
    assert resolution_default.n_rt_from_metadata == 1

    rows_fresh, resolution_fresh = build_del_cycle_rows(
        [compound],
        config,
        "Count",
        settings,
        "minutes",
        use_metadata_rt=False,
    )
    assert len(rows_fresh) == 1
    assert abs(rows_fresh[0].rt - 15.0) < 1.0
    assert resolution_fresh.n_rt_from_metadata == 0
    assert resolution_fresh.n_rt_from_peak_pick == 1


def test_validate_registered_metadata_columns_counts_verification_values() -> None:
    from src.core.del_cycle_tree.service import validate_registered_metadata_columns
    from src.models.compound import Compound
    from src.models.spreadsheet_config import SpreadsheetConfig

    config = SpreadsheetConfig(
        compound_id_column="Name",
        chromatographic_data_column="Chromatogram",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token="AgxNull",
        selected_metadata_columns=["assigned_rt", "verify_status"],
    )
    compounds = [
        Compound(
            compound_id="ProdA",
            metadata={
                "BB1": "A",
                "BB2": "B",
                "BB3": "C",
                "assigned_rt": 12.0,
                "verify_status": "TRUE",
            },
        ),
        Compound(
            compound_id="ProdB",
            metadata={
                "BB1": "A",
                "BB2": "B",
                "BB3": "D",
                "assigned_rt": 15.0,
                "verify_status": "FALSE",
            },
        ),
    ]
    validated = validate_registered_metadata_columns(compounds, config)
    rt_info = next(info for info in validated if info.column_name == "assigned_rt")
    verify_info = next(info for info in validated if info.column_name == "verify_status")
    assert rt_info.n_numeric_values == 2
    assert verify_info.n_verified_values == 2
    assert verify_info.n_verified_with_bb_positions == 2


def test_metadata_tree_uses_user_verified_column_override() -> None:
    from src.core.del_cycle_tree.service import build_del_cycle_tree_from_metadata_column
    from src.models.compound import Compound
    from src.models.spreadsheet_config import SpreadsheetConfig

    config = SpreadsheetConfig(
        compound_id_column="Name",
        chromatographic_data_column="Chromatogram",
        delimiters=[","],
        time_column_index=0,
        count_column_indices=[1],
        count_names=["Count"],
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token="AgxNull",
        selected_metadata_columns=["assigned_rt", "custom_verify"],
    )
    compounds = [
        Compound(
            compound_id="ProdA",
            metadata={
                "BB1": "A",
                "BB2": "B",
                "BB3": "C",
                "assigned_rt": 12.0,
                "custom_verify": "FALSE",
            },
        ),
    ]
    data = build_del_cycle_tree_from_metadata_column(
        compounds,
        config,
        "assigned_rt",
        verified_column="custom_verify",
        rt_threshold=0.5,
    )
    assert data.verified_sequences[("A", "B", "C")].success is False


def test_build_del_cycle_tree_from_session_cache_all_returns_same_object() -> None:
    """Session split-tree reuse must not re-run peak picking for isoform All."""
    from src.core.del_cycle_tree.service import build_del_cycle_tree_from_session_cache
    from src.models.compound import Compound
    from src.models.spreadsheet_config import SpreadsheetConfig

    session = DelCycleTreeData(
        library_cycle_count=3,
        null_token="AgxNull",
        rt_threshold=0.5,
        tree={"A": {"B": {"C": 12.0}}},
        pruned_tree={},
        verified_sequences={},
        full_null_rt=None,
        rt_source="peak_pick",
        peak_picking_algorithm="old_school",
    )
    config = SpreadsheetConfig(
        compound_id_column="id",
        chromatographic_data_column="data",
        library_cycle_count=3,
        bb_position_columns=["BB1", "BB2", "BB3", ""],
        null_token="AgxNull",
    )
    compounds = [
        Compound(
            compound_id="p1",
            metadata={"BB1": "A", "BB2": "B", "BB3": "C"},
        )
    ]
    result = build_del_cycle_tree_from_session_cache(
        session,
        config,
        compounds,
        isoform_label="All",
    )
    assert result is session

