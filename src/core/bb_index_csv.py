# src/core/bb_index_csv.py
"""Optional user-supplied building-block display index CSV for DEL / pedigree plots."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from src.core.del_cycle_tree.bb_index_scheme import normalize_bb_name

_NAME_HEADERS = frozenset({"name", "building block", "building_block", "bb", "bb name"})
_INDEX_HEADERS = frozenset({"index", "number", "num", "id", "bb index", "bb_index"})
_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_ENCODING_HINT = (
    "If names contain special characters (e.g. β), save the index file as "
    "UTF-8 (Excel: “CSV UTF-8 (Comma delimited)”) or upload an .xlsx index "
    "file so characters match the library spreadsheet."
)


@dataclass(frozen=True)
class BbIndexValidationResult:
    """Outcome of cross-referencing a BB index CSV against spreadsheet data."""

    ok: bool
    summary: str
    detected_names: Tuple[str, ...] = ()
    missing_in_csv: Tuple[str, ...] = ()
    extra_in_csv: Tuple[str, ...] = ()
    duplicate_csv_names: Tuple[str, ...] = ()
    duplicate_csv_indices: Tuple[int, ...] = ()
    parse_errors: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = field(default_factory=tuple)
    likely_encoding_mismatch: bool = False


def detect_building_blocks_from_dataframe(
    df: pd.DataFrame,
    *,
    bb_columns: Sequence[str],
    null_token: str,
) -> Set[str]:
    """
    Collect unique non-null building-block tokens from configured BB columns.

    Matches DEL-cycle discovery: any token seen at any coupling cycle counts once.
    """
    null_token = normalize_bb_name(null_token)
    names: Set[str] = set()
    for column in bb_columns:
        if column not in df.columns:
            continue
        for raw in df[column].dropna():
            if isinstance(raw, float) and pd.isna(raw):
                continue
            text = normalize_bb_name(raw)
            if text and text != null_token:
                names.add(text)
    return names


def _canonicalize_index_map(raw: Dict[str, int]) -> Dict[str, int]:
    """Merge case variants; last row wins for duplicate spellings."""
    merged: Dict[str, int] = {}
    lower_to_name: Dict[str, str] = {}
    for name, index in raw.items():
        text = normalize_bb_name(name)
        if not text:
            continue
        key = text.lower()
        if key not in lower_to_name or text < lower_to_name[key]:
            lower_to_name[key] = text
        merged[lower_to_name[key]] = int(index)
    return merged


def _decode_csv_bytes(data: bytes) -> Tuple[str, str]:
    """Decode CSV bytes, trying common encodings used by Excel on Windows."""
    for encoding in _CSV_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _parse_bb_index_rows(all_rows: Sequence[Sequence[object]]) -> Tuple[Dict[str, int], List[str]]:
    """Parse name/index pairs from row cells (CSV or Excel)."""
    errors: List[str] = []
    rows_out: Dict[str, int] = {}
    if not all_rows:
        return {}, ["Index file is empty."]

    start = 0
    first = all_rows[0]
    if len(first) >= 2:
        h0 = str(first[0]).strip().lower()
        h1 = str(first[1]).strip().lower()
        if h0 in _NAME_HEADERS or h1 in _INDEX_HEADERS:
            start = 1

    for line_no, row in enumerate(all_rows[start:], start=start + 1):
        if len(row) < 2:
            errors.append(f"Line {line_no}: expected two columns (name, index).")
            continue
        name = normalize_bb_name(row[0])
        index_text = str(row[1]).strip()
        if not name:
            errors.append(f"Line {line_no}: empty building-block name.")
            continue
        if not re.fullmatch(r"-?\d+", index_text):
            errors.append(f"Line {line_no}: index must be an integer (got {index_text!r}).")
            continue
        rows_out[name] = int(index_text)

    if errors:
        return {}, errors
    if not rows_out:
        return {}, ["No building-block rows found in index file."]
    return _canonicalize_index_map(rows_out), []


def parse_bb_index_csv(path: str | Path) -> Tuple[Dict[str, int], List[str]]:
    """
    Parse a two-column CSV: building-block name and display index.

    Header row is optional. Accepts common column titles (name/index, etc.).
    Tries UTF-8 first, then legacy Windows encodings when Excel saves ANSI CSV.
    """
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}, [f"File not found: {csv_path}"]

    try:
        text, _encoding = _decode_csv_bytes(csv_path.read_bytes())
        reader = csv.reader(text.splitlines())
        all_rows = [row for row in reader if row and any(str(cell).strip() for cell in row)]
    except OSError as exc:
        return {}, [f"Could not read CSV: {exc}"]

    return _parse_bb_index_rows(all_rows)


def parse_bb_index_excel(path: str | Path) -> Tuple[Dict[str, int], List[str]]:
    """Parse a two-column Excel workbook (first sheet) as a BB index table."""
    excel_path = Path(path)
    if not excel_path.is_file():
        return {}, [f"File not found: {excel_path}"]

    try:
        df = pd.read_excel(excel_path, header=None, engine="openpyxl")
    except OSError as exc:
        return {}, [f"Could not read Excel file: {exc}"]
    except ValueError as exc:
        return {}, [f"Could not read Excel file: {exc}"]

    all_rows = [
        [cell for cell in row]
        for row in df.itertuples(index=False, name=None)
        if any(pd.notna(cell) and str(cell).strip() for cell in row)
    ]
    return _parse_bb_index_rows(all_rows)


def parse_bb_index_file(path: str | Path) -> Tuple[Dict[str, int], List[str]]:
    """Parse a BB index CSV or Excel (.xlsx) file."""
    file_path = Path(path)
    if file_path.suffix.lower() in {".xlsx", ".xls"}:
        return parse_bb_index_excel(file_path)
    return parse_bb_index_csv(file_path)


def validate_bb_index_map(
    index_map: Dict[str, int],
    detected_names: Iterable[str],
    *,
    null_token: str,
) -> BbIndexValidationResult:
    """Cross-reference a parsed index CSV against BB names detected in the spreadsheet."""
    null_token = normalize_bb_name(null_token)
    detected = sorted({normalize_bb_name(n) for n in detected_names if normalize_bb_name(n)}, key=str.lower)
    detected_non_null = [name for name in detected if name != null_token]

    parse_errors: List[str] = []
    if not index_map:
        return BbIndexValidationResult(
            ok=False,
            summary="No index map loaded.",
            parse_errors=("Upload a CSV first.",),
        )

    duplicate_names: List[str] = []
    seen_lower: Dict[str, str] = {}
    for name in index_map:
        key = name.lower()
        if key in seen_lower and seen_lower[key] != name:
            duplicate_names.append(name)
        seen_lower[key] = name

    duplicate_indices: List[int] = []
    by_index: Dict[int, List[str]] = {}
    for name, index in index_map.items():
        by_index.setdefault(index, []).append(name)
    for index, names in by_index.items():
        if len(names) > 1:
            duplicate_indices.append(index)

    csv_names = set(index_map.keys())
    detected_set = set(detected_non_null)
    csv_lower = {name.lower(): name for name in csv_names}
    detected_lower = {name.lower(): name for name in detected_set}
    missing_in_csv = sorted(
        (detected_lower[key] for key in detected_lower if key not in csv_lower),
        key=str.lower,
    )
    extra_in_csv = sorted(
        (
            csv_lower[key]
            for key in csv_lower
            if key not in detected_lower and csv_lower[key] != null_token
        ),
        key=str.lower,
    )

    notes: List[str] = []
    if null_token not in csv_names:
        notes.append(f'Null token "{null_token}" not in CSV — will use index 0 on plots.')
    encoding_mismatch = bool(
        missing_in_csv
        and extra_in_csv
        and _looks_like_encoding_mismatch(missing_in_csv, extra_in_csv)
    )
    if encoding_mismatch:
        notes.append(_ENCODING_HINT)

    ok = not duplicate_names and not duplicate_indices and not missing_in_csv
    if ok:
        summary = (
            f"Index CSV matches spreadsheet: {len(detected_non_null)} building block(s) covered."
        )
    else:
        parts: List[str] = []
        if encoding_mismatch:
            parts.append("likely encoding mismatch (special characters)")
        if missing_in_csv:
            parts.append(f"{len(missing_in_csv)} in spreadsheet but missing from CSV")
        if duplicate_names:
            parts.append("duplicate names in CSV")
        if duplicate_indices:
            parts.append("duplicate indices in CSV")
        summary = "Validation failed: " + "; ".join(parts) + "."

    return BbIndexValidationResult(
        ok=ok,
        summary=summary,
        detected_names=tuple(detected_non_null),
        missing_in_csv=tuple(missing_in_csv),
        extra_in_csv=tuple(extra_in_csv),
        duplicate_csv_names=tuple(sorted(set(duplicate_names), key=str.lower)),
        duplicate_csv_indices=tuple(sorted(set(duplicate_indices))),
        parse_errors=tuple(parse_errors),
        notes=tuple(notes),
        likely_encoding_mismatch=encoding_mismatch,
    )


def _looks_like_encoding_mismatch(
    missing: Sequence[str],
    extra: Sequence[str],
) -> bool:
    """Heuristic: paired near-matches often mean a corrupted special character."""
    if not missing or not extra:
        return False
    if any("?" in name or "\ufffd" in name for name in extra):
        return True
    extra_lower = {name.lower() for name in extra}
    for name in missing:
        stripped = name.lstrip("\u03b2\u0392bB")
        if stripped and stripped.lower() in extra_lower:
            return True
    return False


def format_validation_report(result: BbIndexValidationResult, *, max_list: int = 12) -> str:
    """Human-readable multi-line report for the configure-spreadsheet UI."""
    lines = [result.summary]
    for note in result.notes:
        lines.append(f"Note: {note}")
    if result.missing_in_csv:
        shown = ", ".join(result.missing_in_csv[:max_list])
        extra = len(result.missing_in_csv) - max_list
        if extra > 0:
            shown += f", … (+{extra} more)"
        lines.append(f"In spreadsheet but not in CSV ({len(result.missing_in_csv)}): {shown}")
    if result.extra_in_csv:
        shown = ", ".join(result.extra_in_csv[:max_list])
        extra = len(result.extra_in_csv) - max_list
        if extra > 0:
            shown += f", … (+{extra} more)"
        lines.append(
            f"In CSV but not detected in spreadsheet ({len(result.extra_in_csv)}): {shown}"
        )
    if result.duplicate_csv_names:
        lines.append(f"Duplicate CSV names: {', '.join(result.duplicate_csv_names)}")
    if result.duplicate_csv_indices:
        lines.append(
            "Duplicate CSV indices: "
            + ", ".join(str(i) for i in result.duplicate_csv_indices)
        )
    for err in result.parse_errors:
        lines.append(f"Error: {err}")
    return "\n".join(lines)
