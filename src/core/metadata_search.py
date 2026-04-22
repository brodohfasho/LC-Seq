# src/core/metadata_search.py
"""
Build validated SQLite WHERE clauses from visual query-builder conditions.

Used by Chromatogram Visualizer search (Phase 11) against indexed metadata columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Sequence, Tuple

from src.core.data_store import DataStore

FieldType = Literal["auto", "text", "numeric", "date"]
QueryOperator = Literal[
    "=",
    "!=",
    ">",
    "<",
    ">=",
    "<=",
    "contains",
    "starts with",
    "ends with",
]
Combiner = Literal["AND", "OR"]

_NUMERIC_OPS: frozenset[str] = frozenset({">", "<", ">=", "<="})
_TEXT_OPS: frozenset[str] = frozenset(
    {"contains", "starts with", "ends with", "=", "!="}
)


@dataclass(frozen=True)
class QueryCondition:
    """
    One row in the visual query builder.

    Attributes:
        field: Spreadsheet metadata column name (must match whitelist).
        operator: Comparison or text match operator.
        value: User-entered literal (interpreted per field_type).
        field_type: How value and column are coerced for SQL.
        case_sensitive: For text operators, compare with exact case when True.
    """

    field: str
    operator: str
    value: str
    field_type: FieldType = "auto"
    case_sensitive: bool = False


def sanitize_sql_column(name: str) -> str:
    """Delegate to DataStore column sanitization (must match DB DDL)."""
    return DataStore._sanitize_column_name(name)


def escape_like_pattern(value: str) -> str:
    """Escape ``%``, ``_``, and ``\\`` for SQLite LIKE … ESCAPE '\\'."""
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def validate_conditions(
    conditions: Sequence[QueryCondition],
    allowed_fields: Sequence[str],
) -> List[str]:
    """
    Validate builder state before running a search.

    Returns:
        Empty list if valid; otherwise human-readable error strings.
    """
    errors: List[str] = []
    allowed = {str(f).strip() for f in allowed_fields if str(f).strip()}
    if not conditions:
        errors.append("Add at least one search condition.")
        return errors

    for i, cond in enumerate(conditions, start=1):
        field = (cond.field or "").strip()
        if not field:
            errors.append(f"Condition {i}: select a metadata column.")
            continue
        if field not in allowed:
            errors.append(f"Condition {i}: unknown field {field!r}.")
        op = (cond.operator or "").strip()
        if op not in _NUMERIC_OPS and op not in _TEXT_OPS:
            errors.append(f"Condition {i}: unsupported operator {op!r}.")
        if cond.field_type not in ("auto", "text", "numeric", "date"):
            errors.append(f"Condition {i}: invalid field type {cond.field_type!r}.")

        eff_type = _effective_field_type(cond)
        if eff_type == "numeric" and op in _TEXT_OPS and op not in ("=", "!="):
            errors.append(
                f"Condition {i}: operator {op!r} is not supported for numeric fields."
            )
        if eff_type in ("numeric", "date") and op in ("contains", "starts with", "ends with"):
            errors.append(
                f"Condition {i}: text-style operator {op!r} is only for text fields."
            )

    return errors


def default_combiners(n_conditions: int) -> List[Combiner]:
    """Return default combiners of length ``n_conditions - 1`` (all AND)."""
    return ["AND"] * max(0, n_conditions - 1)


def _effective_field_type(cond: QueryCondition) -> Literal["text", "numeric", "date"]:
    if cond.field_type == "auto":
        if cond.operator in _NUMERIC_OPS:
            return "numeric"
        return "text"
    if cond.field_type == "numeric":
        return "numeric"
    if cond.field_type == "date":
        return "date"
    return "text"


def _numeric_expr(safe_col: str) -> str:
    """SQLite expression treating blank / non-numeric as NULL."""
    return (
        f"CASE WHEN TRIM({safe_col}) IS NULL OR TRIM({safe_col}) = '' "
        f"THEN NULL ELSE CAST(TRIM({safe_col}) AS REAL) END"
    )


def _build_single_condition(cond: QueryCondition) -> Tuple[str, List[Any]]:
    """Return one parenthesized SQL fragment and bound parameters."""
    safe = sanitize_sql_column(cond.field)
    op = (cond.operator or "").strip()
    eff = _effective_field_type(cond)
    raw_val = cond.value if cond.value is not None else ""
    params: List[Any] = []

    if eff == "numeric":
        expr = _numeric_expr(safe)
        try:
            num = float(str(raw_val).strip())
        except ValueError as exc:
            raise ValueError(f"Invalid numeric value for field {cond.field!r}.") from exc
        if op == "=":
            return f"({expr} = ?)", [num]
        if op == "!=":
            return f"({expr} IS NOT NULL AND {expr} != ?)", [num]
        if op in _NUMERIC_OPS:
            return f"({expr} {op} ?)", [num]
        raise ValueError(f"Unsupported numeric operator {op!r}")

    if eff == "date":
        lhs = f"TRIM({safe})"
        rhs = str(raw_val).strip()
        if op == "=":
            return f"({lhs} = ?)", [rhs]
        if op == "!=":
            return f"({lhs} IS NOT NULL AND TRIM({lhs}) != '' AND {lhs} != ?)", [rhs]
        if op in (">", "<", ">=", "<="):
            return f"({lhs} {op} ?)", [rhs]
        raise ValueError(f"Unsupported date operator {op!r}")

    # Text branch
    esc = escape_like_pattern(str(raw_val))

    if op == "contains":
        pat = f"%{esc}%"
        if cond.case_sensitive:
            return f"({safe} LIKE ? ESCAPE '\\')", [pat]
        return f"(LOWER({safe}) LIKE ? ESCAPE '\\')", [pat.lower()]

    if op == "starts with":
        pat = f"{esc}%"
        if cond.case_sensitive:
            return f"({safe} LIKE ? ESCAPE '\\')", [pat]
        return f"(LOWER({safe}) LIKE ? ESCAPE '\\')", [pat.lower()]

    if op == "ends with":
        pat = f"%{esc}"
        if cond.case_sensitive:
            return f"({safe} LIKE ? ESCAPE '\\')", [pat]
        return f"(LOWER({safe}) LIKE ? ESCAPE '\\')", [pat.lower()]

    if op == "=":
        p = str(raw_val)
        if cond.case_sensitive:
            return f"((? IS NULL AND {safe} IS NULL) OR ({safe} = ?))", [p, p]
        return f"((? IS NULL AND {safe} IS NULL) OR (LOWER({safe}) = ?))", [p, p.lower()]

    if op == "!=":
        p = str(raw_val)
        if cond.case_sensitive:
            inner = f"((? IS NULL AND {safe} IS NULL) OR ({safe} = ?))"
            return f"(NOT ({inner}))", [p, p]
        inner = f"((? IS NULL AND {safe} IS NULL) OR (LOWER({safe}) = ?))"
        return f"(NOT ({inner}))", [p, p.lower()]

    raise ValueError(f"Unsupported text operator {op!r}")


def build_where_clause(
    conditions: Sequence[QueryCondition],
    combiners: Sequence[str],
) -> Tuple[str, List[Any]]:
    """
    Combine condition SQL fragments with AND/OR (left-associative, explicit parens).

    Args:
        conditions: Non-empty validated conditions.
        combiners: Length ``len(conditions) - 1``, each ``AND`` or ``OR``.

    Returns:
        Tuple of (where_sql_without_where_keyword, bound_parameters).
    """
    if not conditions:
        return "1 = 0", []
    frags: List[str] = []
    all_params: List[Any] = []
    for cond in conditions:
        sql_part, params = _build_single_condition(cond)
        frags.append(sql_part)
        all_params.extend(params)

    if len(frags) == 1:
        return frags[0], all_params

    if len(combiners) != len(frags) - 1:
        raise ValueError("combiners must have length len(conditions) - 1")

    combined = frags[0]
    for i, comb in enumerate(combiners):
        if comb not in ("AND", "OR"):
            raise ValueError(f"Invalid combiner {comb!r}")
        combined = f"({combined} {comb} {frags[i + 1]})"
    return combined, all_params


def append_results_text_filter(
    where_sql: str,
    params: List[Any],
    needle: str,
    display_sql_columns: Sequence[str],
) -> Tuple[str, List[Any]]:
    """
    AND a loose OR-match across compound_id and visible metadata columns (secondary filter).
    """
    n = (needle or "").strip()
    if not n:
        return where_sql, params
    esc = escape_like_pattern(n)
    pat = f"%{esc.lower()}%"
    parts: List[str] = []
    new_params: List[Any] = list(params)
    for col in display_sql_columns:
        parts.append(f"LOWER(COALESCE({col}, '')) LIKE ? ESCAPE '\\'")
        new_params.append(pat)
    if not parts:
        return where_sql, params
    or_block = "(" + " OR ".join(parts) + ")"
    return f"({where_sql}) AND {or_block}", new_params
