# src/models/compound_identity.py
"""
Build and parse storage identifiers for compounds with optional variant labels (e.g. linear vs cyclized).
"""

from __future__ import annotations

from typing import Optional, Tuple

# ASCII Unit Separator — unlikely in peptide/library names; keeps primary IDs readable in logs.
_STORAGE_SEP = "\x1f"


def build_compound_storage_id(primary_id: str, variant_label: Optional[str]) -> str:
    """
    Build the unique database key for one spreadsheet row.

    Args:
        primary_id: Shared compound identity (e.g. library member name).
        variant_label: Distinguishes versions (e.g. linear / cyclized). Required when provided by config.

    Returns:
        ``primary_id`` only if variant is missing/blank; otherwise ``primary_id + sep + variant``.
    """
    p = str(primary_id).strip()
    if not p:
        raise ValueError("primary_id must be non-empty")
    if variant_label is None or not str(variant_label).strip():
        return p
    v = str(variant_label).strip()
    return f"{p}{_STORAGE_SEP}{v}"


def split_compound_storage_id(storage_id: str) -> Tuple[str, Optional[str]]:
    """
    Split a storage compound_id into primary and variant parts.

    Args:
        storage_id: Value stored in ``compounds.compound_id``.

    Returns:
        (primary, variant or None) if no separator is present, variant is None.
    """
    s = str(storage_id).strip()
    if _STORAGE_SEP in s:
        left, right = s.split(_STORAGE_SEP, 1)
        left, right = left.strip(), right.strip()
        return left, (right if right else None)
    return s, None
