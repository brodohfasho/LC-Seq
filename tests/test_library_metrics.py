# tests/test_library_metrics.py
"""
Tests for library-wide metrics.
"""

from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    compound_total_counts,
    compute_library_metrics,
)
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig


def _compound(cid: str, totals_by_time: list) -> Compound:
    """Build compound from list of (time, {count: value})."""
    points = [
        ChromatographicDataPoint(time=t, counts=counts) for t, counts in totals_by_time
    ]
    return Compound(compound_id=cid, data_points=points)


class TestCompoundTotalCounts:
    def test_sums_across_time_points(self) -> None:
        c = _compound(
            "A",
            [
                (0.0, {"Count": 10.0, "Alt": 1.0}),
                (1.0, {"Count": 20.0, "Alt": 2.0}),
            ],
        )
        totals = compound_total_counts(c, ["Count", "Alt"])
        assert totals["Count"] == 30.0
        assert totals["Alt"] == 3.0


class TestTotalCountLibraryStats:
    def test_mean_and_sample_stdev(self, tmp_path) -> None:
        from src.core.data_store import DataStore

        config = SpreadsheetConfig(
            compound_id_column="id",
            chromatographic_data_column="data",
            delimiters=[","],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Count"],
        )
        db_path = tmp_path / "lib.db"
        store = DataStore(db_path=db_path, use_memory=False)
        c1 = _compound("c1", [(0.0, {"Count": 10.0}), (1.0, {"Count": 20.0})])
        c2 = _compound("c2", [(0.0, {"Count": 40.0})])
        assert store.add_compound(c1, [])
        assert store.add_compound(c2, [])
        store.conn.commit()
        store.close()

        store2 = DataStore(db_path=db_path, use_memory=False)
        result = compute_library_metrics(store2, config, index_database=False)
        store2.close()

        assert result.entries_used == 2
        assert result.entries_skipped == 0

        ch_total = result.total_count_per_entry[0]
        assert ch_total.count_name == "Count"
        assert ch_total.n == 2
        assert ch_total.mean == 35.0

        ch_frac = result.avg_count_per_fraction[0]
        assert ch_frac.n == 2
        assert ch_frac.mean == 35.0 / DEFAULT_FRACTION_COUNT
        assert ch_frac.mean == ch_total.mean / DEFAULT_FRACTION_COUNT
