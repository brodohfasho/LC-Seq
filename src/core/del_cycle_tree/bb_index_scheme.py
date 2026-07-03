# src/core/del_cycle_tree/bb_index_scheme.py
"""
Dynamic building-block display indices for DEL-cycle trees.

Assigns each unique BB name a stable 1-based index (sorted alphabetically,
case-insensitive). The same name keeps the same index at every coupling level.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, Sequence, Tuple, Optional


def normalize_bb_name(bb: object) -> str:
    """Strip whitespace and apply Unicode NFC normalization."""
    text = str(bb).strip()
    if not text:
        return ""
    return unicodedata.normalize("NFC", text)


def merge_bb_name_canonical_maps(*maps: Dict[str, str]) -> Dict[str, str]:
    """Merge lowercase→canonical maps; lexicographically smallest spelling wins."""
    merged: Dict[str, str] = {}
    for canonical_map in maps:
        for key, name in canonical_map.items():
            existing = merged.get(key)
            if existing is None or name < existing:
                merged[key] = name
    return merged


def build_bb_name_canonical_map(
    rows: Sequence[object],
    null_token: str,
) -> Dict[str, str]:
    """
    Map lowercase BB spellings to one canonical token per name.

    When the library contains case variants (e.g. ``LA03`` and ``la03``), the
    lexicographically smallest spelling wins so tree keys and indices stay aligned.
    """
    null_token = normalize_bb_name(null_token)
    canonical: Dict[str, str] = {}
    for row in rows:
        positions = getattr(row, "positions", None)
        if positions is None:
            continue
        for bb in positions:
            text = normalize_bb_name(bb)
            if not text or text == null_token:
                continue
            key = text.lower()
            existing = canonical.get(key)
            if existing is None or text < existing:
                canonical[key] = text
    return canonical


def canonicalize_bb_token(
    bb: object,
    *,
    null_token: str,
    canonical_by_lower: Dict[str, str],
) -> str:
    """Normalize one BB token to the canonical spelling used in tree keys."""
    null_token = normalize_bb_name(null_token)
    text = normalize_bb_name(bb)
    if not text or text == null_token:
        return null_token
    return canonical_by_lower.get(text.lower(), text)


def canonicalize_positions(
    positions: Tuple[str, ...],
    *,
    null_token: str,
    canonical_by_lower: Dict[str, str],
) -> Tuple[str, ...]:
    """Rewrite a coupling-order tuple using canonical BB spellings."""
    return tuple(
        canonicalize_bb_token(
            bb,
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
        for bb in positions
    )


def build_global_bb_index_map(
    rows: Sequence[object],
    null_token: str,
    *,
    override_map: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """
    Map each non-null BB name to a display index.

    When ``override_map`` is non-empty, uses user-supplied indices (from index CSV).
    Otherwise assigns 1-based indices sorted alphabetically (case-insensitive).
    """
    if override_map:
        return _apply_override_index_map(rows, null_token, override_map)
    canonical_by_lower = build_bb_name_canonical_map(rows, null_token)
    names = sorted(canonical_by_lower.values(), key=str.lower)
    return {name: index + 1 for index, name in enumerate(names)}


def _apply_override_index_map(
    rows: Sequence[object],
    null_token: str,
    override_map: Dict[str, int],
) -> Dict[str, int]:
    """Build display map from user CSV, canonicalizing against library BB spellings."""
    null_token = normalize_bb_name(null_token)
    canonical_by_lower = build_bb_name_canonical_map(rows, null_token)
    merged: Dict[str, int] = {}
    lower_to_override: Dict[str, Tuple[str, int]] = {}
    for raw_name, index in override_map.items():
        text = normalize_bb_name(raw_name)
        if not text or text == null_token:
            continue
        key = text.lower()
        if key not in lower_to_override or text < lower_to_override[key][0]:
            lower_to_override[key] = (text, int(index))
    for key, (name, index) in lower_to_override.items():
        canonical = canonical_by_lower.get(key, name)
        merged[canonical] = index
    return merged


def canonicalize_lookup_keys(
    lookup: Dict[Tuple[str, ...], object],
    *,
    null_token: str,
    canonical_by_lower: Dict[str, str],
) -> Dict[Tuple[str, ...], object]:
    """Rewrite lookup tuple keys to canonical BB spellings."""
    null_token = normalize_bb_name(null_token)
    out: Dict[Tuple[str, ...], object] = {}
    for positions, value in lookup.items():
        key = canonicalize_positions(
            tuple(normalize_bb_name(part) for part in positions),
            null_token=null_token,
            canonical_by_lower=canonical_by_lower,
        )
        out[key] = value
    return out


def lookup_bb_display_index(
    bb_name: str,
    index_map: Dict[str, int],
    *,
    null_token: str = "AgxNull",
) -> int | None:
    """Return the display index for ``bb_name`` from ``index_map``."""
    text = normalize_bb_name(bb_name)
    if not text or text == normalize_bb_name(null_token):
        return 0
    if text in index_map:
        return index_map[text]
    lowered = text.lower()
    for name, index in index_map.items():
        if name.lower() == lowered:
            return index
    return None


def format_bb_branch_label(
    bb1_name: str,
    index_map: Dict[str, int],
    *,
    null_token: str,
) -> str:
    """Human-readable branch selector label: ``#N BBname`` when indexed."""
    index = lookup_bb_display_index(bb1_name, index_map, null_token=null_token)
    if index is not None and index > 0:
        return f"#{index} {bb1_name}"
    return bb1_name
