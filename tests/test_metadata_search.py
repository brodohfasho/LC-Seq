# tests/test_metadata_search.py
"""Unit tests for metadata search SQL construction (Phase 11)."""

import tempfile
import unittest
from pathlib import Path

from src.core.data_store import DataStore
from src.core.metadata_search import (
    QueryCondition,
    append_results_text_filter,
    build_where_clause,
    escape_glob_pattern,
    escape_like_pattern,
    filter_value_suggestions,
    prioritize_search_fields,
    validate_conditions,
)
from src.models.compound import Compound


class TestMetadataSearch(unittest.TestCase):
    """Tests for ``metadata_search`` helpers."""

    def test_escape_like_pattern(self) -> None:
        self.assertEqual(escape_like_pattern("a%b_c\\"), "a\\%b\\_c\\\\")

    def test_escape_glob_pattern(self) -> None:
        self.assertEqual(escape_glob_pattern("a*b?c[d"), "a[*]b[?]c[[]d")

    def test_validate_empty(self) -> None:
        errs = validate_conditions([], ["colA"])
        self.assertTrue(any("at least one" in e.lower() for e in errs))

    def test_validate_unknown_field(self) -> None:
        conds = [QueryCondition(field="nope", operator="=", value="x")]
        errs = validate_conditions(conds, ["colA"])
        self.assertTrue(any("unknown" in e.lower() for e in errs))

    def test_validate_rejects_empty_value(self) -> None:
        conds = [QueryCondition(field="colA", operator="contains", value="  ")]
        errs = validate_conditions(conds, ["colA"])
        self.assertTrue(any("non-empty" in e.lower() for e in errs))

    def test_validate_rejects_text_numeric_ops(self) -> None:
        conds = [
            QueryCondition(
                field="colA",
                operator=">",
                value="1",
                field_type="text",
            )
        ]
        errs = validate_conditions(conds, ["colA"])
        self.assertTrue(any("not supported for text" in e.lower() for e in errs))

    def test_build_single_equals(self) -> None:
        conds = [QueryCondition(field="colA", operator="=", value="hello", field_type="text")]
        sql, params = build_where_clause(conds, [])
        self.assertIn("LOWER", sql)
        self.assertIn("TRIM", sql)
        self.assertEqual(params, ["hello"])

    def test_build_and_chain(self) -> None:
        conds = [
            QueryCondition(field="a", operator="=", value="1", field_type="numeric"),
            QueryCondition(field="b", operator=">", value="2", field_type="numeric"),
        ]
        sql, params = build_where_clause(conds, ["AND"])
        self.assertIn("AND", sql)
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0], 1.0)
        self.assertEqual(params[1], 2.0)

    def test_build_or_chain(self) -> None:
        conds = [
            QueryCondition(field="a", operator="=", value="1", field_type="numeric"),
            QueryCondition(field="b", operator="=", value="2", field_type="numeric"),
        ]
        sql, params = build_where_clause(conds, ["OR"])
        self.assertIn(" OR ", sql.upper())
        self.assertEqual(len(params), 2)

    def test_left_associative_combiners(self) -> None:
        conds = [
            QueryCondition(field="a", operator="=", value="1", field_type="numeric"),
            QueryCondition(field="b", operator="=", value="2", field_type="numeric"),
            QueryCondition(field="c", operator="=", value="3", field_type="numeric"),
        ]
        sql, _params = build_where_clause(conds, ["OR", "AND"])
        self.assertTrue(sql.startswith("(("))
        self.assertIn(" OR ", sql)
        self.assertIn(" AND ", sql)

    def test_append_results_filter(self) -> None:
        sql, params = append_results_text_filter("1=1", [], "ab", ["compound_id", "meta_x"])
        self.assertIn("LOWER", sql)
        self.assertTrue(len(params) >= 2)

    def test_empty_contains_raises(self) -> None:
        conds = [QueryCondition(field="colA", operator="contains", value="", field_type="text")]
        with self.assertRaises(ValueError):
            build_where_clause(conds, [])

    def test_filter_value_suggestions(self) -> None:
        values = ["DVal", "DPhe", "Leu", "PreDValX"]
        self.assertEqual(filter_value_suggestions(values, ""), values)
        self.assertEqual(filter_value_suggestions(values, "dv"), ["DVal", "PreDValX"])
        self.assertEqual(filter_value_suggestions(values, "zzz"), [])
        self.assertEqual(
            filter_value_suggestions(values, "", max_show=2),
            ["DVal", "DPhe"],
        )

    def test_prioritize_search_fields_puts_bb_first(self) -> None:
        ordered = prioritize_search_fields(
            ["Exact Mass", "BB2 Name", "BB1 Name", "AlogP"],
            ["BB1 Name", "BB2 Name", "BB3 Name", ""],
        )
        self.assertEqual(ordered[:2], ["BB1 Name", "BB2 Name"])
        self.assertIn("Exact Mass", ordered)

    def test_list_distinct_metadata_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "distinct.db", use_memory=False)
            self._seed_store(store)
            values, truncated = store.list_distinct_metadata_values("BB1 Name", limit=10)
            store.close()
            self.assertFalse(truncated)
            self.assertEqual(set(values), {"DVal", "Leu", "PreDValX", "dval"})
            # Case-insensitive sort keeps letter groups together.
            self.assertEqual([v.lower() for v in values], sorted(v.lower() for v in values))

    def test_list_distinct_respects_limit_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "trunc.db", use_memory=False)
            meta_cols = ["Tag"]
            store.create_metadata_columns(meta_cols)
            for i in range(5):
                self.assertTrue(
                    store.add_compound(
                        Compound(
                            compound_id=f"c{i}",
                            metadata={"Tag": f"V{i}"},
                        ),
                        meta_cols,
                    )
                )
            store.conn.commit()
            values, truncated = store.list_distinct_metadata_values("Tag", limit=3)
            store.close()
            self.assertTrue(truncated)
            self.assertEqual(len(values), 3)
        ordered = prioritize_search_fields(
            ["Exact Mass", "BB2 Name", "BB1 Name", "AlogP"],
            ["BB1 Name", "BB2 Name", "BB3 Name", ""],
        )
        self.assertEqual(ordered[:2], ["BB1 Name", "BB2 Name"])
        self.assertIn("Exact Mass", ordered)

    def test_case_sensitive_contains_uses_glob(self) -> None:
        conds = [
            QueryCondition(
                field="BB1 Name",
                operator="contains",
                value="DVal",
                field_type="text",
                case_sensitive=True,
            )
        ]
        sql, params = build_where_clause(conds, [])
        self.assertIn("GLOB", sql)
        self.assertNotIn("LIKE", sql)
        self.assertEqual(params, ["*DVal*"])

    def test_case_insensitive_contains_uses_like(self) -> None:
        conds = [
            QueryCondition(
                field="BB1 Name",
                operator="contains",
                value="DVal",
                field_type="text",
                case_sensitive=False,
            )
        ]
        sql, params = build_where_clause(conds, [])
        self.assertIn("LIKE", sql)
        self.assertEqual(params, ["%dval%"])

    def _seed_store(self, store: DataStore) -> list[tuple[str, dict]]:
        meta_cols = ["BB1 Name", "BB2 Name", "Exact Mass", "Run Date"]
        store.create_metadata_columns(meta_cols)
        rows = [
            ("c1", {
                "BB1 Name": "DVal",
                "BB2 Name": "DPhe",
                "Exact Mass": "100.5",
                "Run Date": "2020-01-01",
            }),
            ("c2", {
                "BB1 Name": "dval",
                "BB2 Name": "DVal",
                "Exact Mass": "abc",
                "Run Date": "2020-02-01",
            }),
            ("c3", {
                "BB1 Name": "DVal",
                "BB2 Name": "Leu",
                "Exact Mass": "0",
                "Run Date": "2020-01-15",
            }),
            ("c4", {
                "BB1 Name": "Leu",
                "BB2 Name": "DPhe",
                "Exact Mass": "",
                "Run Date": "2019-12-31",
            }),
            ("c5", {
                "BB1 Name": "PreDValX",
                "BB2 Name": "DPhe",
                "Exact Mass": "50",
                "Run Date": "2021-01-01",
            }),
        ]
        for cid, meta in rows:
            compound = Compound(compound_id=cid, metadata=meta)
            self.assertTrue(store.add_compound(compound, meta_cols))
        store.conn.commit()
        return rows

    def test_bb1_equals_returns_subset_not_full_library(self) -> None:
        """Regression: BB1 = DVal must not match every compound."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "search.db"
            store = DataStore(db_path=db_path, use_memory=False)
            rows = self._seed_store(store)

            conds = [
                QueryCondition(
                    field="BB1 Name",
                    operator="=",
                    value="DVal",
                    field_type="text",
                )
            ]
            sql, params = build_where_clause(conds, [])
            count = store.count_compounds_where(sql, params)
            ids = store.list_compound_ids_where(sql, params)
            store.close()

            # Case-insensitive: DVal and dval
            self.assertEqual(count, 3)
            self.assertEqual(sorted(ids), ["c1", "c2", "c3"])
            self.assertLess(count, len(rows))

    def test_case_sensitive_equals_and_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "cs.db", use_memory=False)
            self._seed_store(store)

            eq_sql, eq_params = build_where_clause(
                [
                    QueryCondition(
                        field="BB1 Name",
                        operator="=",
                        value="DVal",
                        field_type="text",
                        case_sensitive=True,
                    )
                ],
                [],
            )
            self.assertEqual(
                sorted(store.list_compound_ids_where(eq_sql, eq_params)),
                ["c1", "c3"],
            )

            contains_sql, contains_params = build_where_clause(
                [
                    QueryCondition(
                        field="BB1 Name",
                        operator="contains",
                        value="DVal",
                        field_type="text",
                        case_sensitive=True,
                    )
                ],
                [],
            )
            self.assertEqual(
                sorted(store.list_compound_ids_where(contains_sql, contains_params)),
                ["c1", "c3", "c5"],
            )
            store.close()

    def test_starts_with_and_ends_with(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "affix.db", use_memory=False)
            self._seed_store(store)

            start_sql, start_params = build_where_clause(
                [
                    QueryCondition(
                        field="BB1 Name",
                        operator="starts with",
                        value="Pre",
                        field_type="text",
                    )
                ],
                [],
            )
            self.assertEqual(
                store.list_compound_ids_where(start_sql, start_params),
                ["c5"],
            )

            end_sql, end_params = build_where_clause(
                [
                    QueryCondition(
                        field="BB2 Name",
                        operator="ends with",
                        value="he",
                        field_type="text",
                    )
                ],
                [],
            )
            self.assertEqual(
                sorted(store.list_compound_ids_where(end_sql, end_params)),
                ["c1", "c4", "c5"],
            )
            store.close()

    def test_numeric_non_numeric_cells_are_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "num.db", use_memory=False)
            self._seed_store(store)

            eq0_sql, eq0_params = build_where_clause(
                [
                    QueryCondition(
                        field="Exact Mass",
                        operator="=",
                        value="0",
                        field_type="numeric",
                    )
                ],
                [],
            )
            self.assertEqual(
                store.list_compound_ids_where(eq0_sql, eq0_params),
                ["c3"],
            )

            gt_sql, gt_params = build_where_clause(
                [
                    QueryCondition(
                        field="Exact Mass",
                        operator=">",
                        value="-1",
                        field_type="numeric",
                    )
                ],
                [],
            )
            # c2 ("abc") and c4 ("") must not match as 0
            self.assertEqual(
                sorted(store.list_compound_ids_where(gt_sql, gt_params)),
                ["c1", "c3", "c5"],
            )
            store.close()

    def test_date_iso_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "date.db", use_memory=False)
            self._seed_store(store)

            sql, params = build_where_clause(
                [
                    QueryCondition(
                        field="Run Date",
                        operator="<",
                        value="2020-02-01",
                        field_type="date",
                    )
                ],
                [],
            )
            self.assertEqual(
                sorted(store.list_compound_ids_where(sql, params)),
                ["c1", "c3", "c4"],
            )
            store.close()

    def test_list_ids_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "limit.db", use_memory=False)
            self._seed_store(store)
            ids = store.list_compound_ids_where("1 = 1", [], limit=2)
            store.close()
            self.assertEqual(len(ids), 2)

    def test_text_not_equals_excludes_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "neq.db", use_memory=False)
            meta_cols = ["Tag"]
            store.create_metadata_columns(meta_cols)
            for cid, tag in [("a", "X"), ("b", ""), ("c", "Y")]:
                self.assertTrue(
                    store.add_compound(
                        Compound(compound_id=cid, metadata={"Tag": tag}),
                        meta_cols,
                    )
                )
            store.conn.commit()
            sql, params = build_where_clause(
                [QueryCondition(field="Tag", operator="!=", value="X", field_type="text")],
                [],
            )
            self.assertEqual(store.list_compound_ids_where(sql, params), ["c"])
            store.close()

    def test_append_filter_narrows_primary_where(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(db_path=Path(tmp) / "filt.db", use_memory=False)
            self._seed_store(store)
            where, params = build_where_clause(
                [
                    QueryCondition(
                        field="BB1 Name",
                        operator="=",
                        value="DVal",
                        field_type="text",
                    )
                ],
                [],
            )
            where2, params2 = append_results_text_filter(
                where,
                list(params),
                "c1",
                ["compound_id", "BB1_Name"],
            )
            self.assertEqual(store.list_compound_ids_where(where2, params2), ["c1"])
            store.close()


if __name__ == "__main__":
    unittest.main()
