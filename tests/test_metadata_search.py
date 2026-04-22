# tests/test_metadata_search.py
"""Unit tests for metadata search SQL construction (Phase 11)."""

import unittest

from src.core.metadata_search import (
    QueryCondition,
    append_results_text_filter,
    build_where_clause,
    escape_like_pattern,
    validate_conditions,
)


class TestMetadataSearch(unittest.TestCase):
    """Tests for ``metadata_search`` helpers."""

    def test_escape_like_pattern(self) -> None:
        self.assertEqual(escape_like_pattern("a%b_c\\"), "a\\%b\\_c\\\\")

    def test_validate_empty(self) -> None:
        errs = validate_conditions([], ["colA"])
        self.assertTrue(any("at least one" in e.lower() for e in errs))

    def test_validate_unknown_field(self) -> None:
        conds = [QueryCondition(field="nope", operator="=", value="x")]
        errs = validate_conditions(conds, ["colA"])
        self.assertTrue(any("unknown" in e.lower() for e in errs))

    def test_build_single_equals(self) -> None:
        conds = [QueryCondition(field="colA", operator="=", value="hello", field_type="text")]
        sql, params = build_where_clause(conds, [])
        self.assertIn("LOWER", sql)
        self.assertEqual(params, ["hello", "hello"])

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

    def test_append_results_filter(self) -> None:
        sql, params = append_results_text_filter("1=1", [], "ab", ["compound_id", "meta_x"])
        self.assertIn("LOWER", sql)
        self.assertTrue(len(params) >= 2)


if __name__ == "__main__":
    unittest.main()
