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
_TEXT_MATCH_OPS: frozenset[str] = frozenset(
    {"contains", "starts with", "ends with"}
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


def escape_glob_pattern(value: str) -> str:
    """Escape ``*``, ``?``, and ``[`` for SQLite GLOB (case-sensitive matching)."""
    return (
        value.replace("[", "[[]")
        .replace("*", "[*]")
        .replace("?", "[?]")
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

        value = "" if cond.value is None else str(cond.value)
        if not value.strip():
            errors.append(
                f"Condition {i}: enter a non-empty value "
                f"(empty text matches can return the entire library)."
            )

        eff_type = _effective_field_type(cond)
        if eff_type == "text" and op in _NUMERIC_OPS:
            errors.append(
                f"Condition {i}: operator {op!r} is not supported for text fields."
            )
        if eff_type == "numeric" and op in _TEXT_MATCH_OPS:
            errors.append(
                f"Condition {i}: operator {op!r} is not supported for numeric fields."
            )
        if eff_type == "date" and op in _TEXT_MATCH_OPS:
            errors.append(
                f"Condition {i}: text-style operator {op!r} is only for text fields."
            )
        if eff_type == "numeric":
            try:
                float(value.strip())
            except ValueError:
                errors.append(
                    f"Condition {i}: enter a numeric value for operator {op!r}."
                )

    return errors


def filter_value_suggestions(
    all_values: Sequence[str],
    needle: str,
    *,
    max_show: int = 400,
) -> List[str]:
    """
    Filter cached distinct values for the search value combobox.

    Empty needle returns the first ``max_show`` values (browse mode). Non-empty
    needle keeps case-insensitive substring matches so typing ``DV`` surfaces ``DVal``.
    """
    cap = max(0, int(max_show))
    values = [str(v) for v in all_values if str(v).strip()]
    n = (needle or "").strip().lower()
    if not n:
        return values[:cap]
    matched = [v for v in values if n in v.lower()]
    return matched[:cap]


def prioritize_search_fields(
    searchable_fields: Sequence[str],
    bb_position_columns: Sequence[str] | None = None,
) -> List[str]:
    """
    Put configured BB1..BB4 position columns first in the search field list.

    Search still filters by raw metadata column values; this only improves discoverability
    so “position 1” maps clearly to the BB1 name column.
    """
    present = [str(name) for name in searchable_fields if str(name).strip()]
    seen = set()
    ordered: List[str] = []
    for name in bb_position_columns or []:
        text = str(name or "").strip()
        if text and text in present and text not in seen:
            ordered.append(text)
            seen.add(text)
    for name in present:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


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
    """
    SQLite expression casting blank / non-numeric cells to NULL.

    SQLite ``CAST('abc' AS REAL)`` yields ``0.0``, so we reject cells that are not
    plausibly numeric before casting.
    """
    trimmed = f"TRIM({safe_col})"
    return (
        f"CASE WHEN {trimmed} IS NULL OR {trimmed} = '' THEN NULL "
        f"WHEN {trimmed} GLOB '*[^0-9eE.+-]*' THEN NULL "
        f"WHEN {trimmed} NOT GLOB '*[0-9]*' THEN NULL "
        f"ELSE CAST({trimmed} AS REAL) END"
    )


def _build_single_condition(cond: QueryCondition) -> Tuple[str, List[Any]]:
    """Return one parenthesized SQL fragment and bound parameters."""
    safe = sanitize_sql_column(cond.field)
    op = (cond.operator or "").strip()
    eff = _effective_field_type(cond)
    raw_val = cond.value if cond.value is not None else ""

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
        # Lexicographic compare on trimmed strings — reliable for ISO YYYY-MM-DD.
        lhs = f"TRIM({safe})"
        rhs = str(raw_val).strip()
        if op == "=":
            return f"({lhs} = ?)", [rhs]
        if op == "!=":
            return (
                f"({lhs} IS NOT NULL AND {lhs} != '' AND {lhs} != ?)",
                [rhs],
            )
        if op in (">", "<", ">=", "<="):
            return f"({lhs} {op} ?)", [rhs]
        raise ValueError(f"Unsupported date operator {op!r}")

    # Text branch — require a real needle so LIKE never becomes '%%' / '%'.
    text_value = str(raw_val).strip()
    if not text_value:
        raise ValueError(f"Empty value is not allowed for field {cond.field!r}.")

    if op in _TEXT_MATCH_OPS:
        return _build_text_match(safe, op, text_value, cond.case_sensitive)

    if op == "=":
        if cond.case_sensitive:
            return f"(TRIM({safe}) = ?)", [text_value]
        return f"(LOWER(TRIM({safe})) = ?)", [text_value.lower()]

    if op == "!=":
        if cond.case_sensitive:
            return (
                f"(TRIM({safe}) IS NOT NULL AND TRIM({safe}) != '' "
                f"AND TRIM({safe}) != ?)",
                [text_value],
            )
        return (
            f"(TRIM({safe}) IS NOT NULL AND TRIM({safe}) != '' "
            f"AND LOWER(TRIM({safe})) != ?)",
            [text_value.lower()],
        )

    raise ValueError(f"Unsupported text operator {op!r}")


def _build_text_match(
    safe: str,
    op: str,
    text_value: str,
    case_sensitive: bool,
) -> Tuple[str, List[Any]]:
    """
    Build contains / starts with / ends with SQL.

    Case-insensitive path uses LIKE + LOWER. Case-sensitive path uses GLOB because
    SQLite LIKE is ASCII case-insensitive by default unless a connection pragma is set.
    """
    if case_sensitive:
        esc = escape_glob_pattern(text_value)
        if op == "contains":
            pat = f"*{esc}*"
        elif op == "starts with":
            pat = f"{esc}*"
        elif op == "ends with":
            pat = f"*{esc}"
        else:
            raise ValueError(f"Unsupported text match operator {op!r}")
        return f"(TRIM({safe}) GLOB ?)", [pat]

    esc = escape_like_pattern(text_value)
    if op == "contains":
        pat = f"%{esc}%"
    elif op == "starts with":
        pat = f"{esc}%"
    elif op == "ends with":
        pat = f"%{esc}"
    else:
        raise ValueError(f"Unsupported text match operator {op!r}")
    return f"(LOWER(TRIM({safe})) LIKE ? ESCAPE '\\')", [pat.lower()]


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
