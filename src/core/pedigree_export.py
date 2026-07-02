# src/core/pedigree_export.py
"""Export pedigree analysis tables."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.models.pedigree_result import (
    PedigreeAnalysisResult,
    PedigreeNodeRecord,
    ProductProminenceSummary,
)


def chosen_rt_for_record(record: PedigreeNodeRecord) -> Optional[float]:
    """Algorithm-chosen RT: bayesian pick, score test, or single-rep pick."""
    if record.bayesian_pick is not None:
        return record.bayesian_pick
    if record.score_test_rt is not None:
        return record.score_test_rt
    picks = record.initial_most_significant_picks
    return float(picks[0]) if picks else None


def bb_cycle_field_names(library_cycle_count: int) -> List[str]:
    """CSV column names for per-cycle building blocks (BB1 = cycle 1, C-terminus first)."""
    n = max(int(library_cycle_count), 0)
    return [f"bb_cycle_{k}" for k in range(1, n + 1)]


def _segments_after_id_prefix(node_id: str) -> List[str]:
    """Return underscore-separated payload after ``C{tier}_`` or ``F{n}_``."""
    if "_" not in node_id:
        return []
    return node_id.split("_", 1)[1].split("_")


def positions_n_to_c_from_record(
    record: PedigreeNodeRecord,
    *,
    library_cycle_count: int,
    null_token: str,
) -> List[str]:
    """
    Reconstruct the N→C positional BB tuple for a pedigree node.

    Uses Rust node ``id`` encoding (underscore-separated) so cassette BB names
    may contain dashes. Cycle 1 = C-terminus = BB1 in spreadsheet column order.
    """
    n_cycles = max(int(library_cycle_count), 0)
    if n_cycles == 0:
        return []

    node_id = str(record.id).strip()
    if record.tier == 0 or node_id in ("C0", "ROOT"):
        return [null_token] * n_cycles

    if record.kind == "compound" or node_id.startswith("F"):
        segments = _segments_after_id_prefix(node_id)
        if len(segments) >= n_cycles:
            return list(segments[:n_cycles])
        if segments:
            padded = [null_token] * (n_cycles - len(segments)) + segments
            return padded[-n_cycles:]
        return [null_token] * n_cycles

    # Class node: non-null BBs in N→C order, coupled at the C-terminal ``tier`` slots.
    if node_id.startswith("C"):
        bbs = _segments_after_id_prefix(node_id)
        tier = len(bbs) if bbs else int(record.tier)
        tier = min(max(tier, 0), n_cycles)
        pad = [null_token] * (n_cycles - tier)
        return pad + bbs[:tier]

    return [null_token] * n_cycles


def bb_cycle_columns_for_record(
    record: PedigreeNodeRecord,
    *,
    library_cycle_count: int,
    null_token: str,
) -> Dict[str, str]:
    """
    Map ``bb_cycle_1`` … ``bb_cycle_N`` to building blocks (spreadsheet BB1..BBn).

    ``bb_cycle_1`` is the first coupled position (C-terminus / BB1 column).
  """
    positions = positions_n_to_c_from_record(
        record,
        library_cycle_count=library_cycle_count,
        null_token=null_token,
    )
    n_cycles = max(int(library_cycle_count), 0)
    columns: Dict[str, str] = {}
    for cycle in range(1, n_cycles + 1):
        idx = n_cycles - cycle
        columns[f"bb_cycle_{cycle}"] = positions[idx] if 0 <= idx < len(positions) else null_token
    return columns


def _pedigree_csv_fieldnames(library_cycle_count: int) -> List[str]:
    base = [
        "id",
        "label",
        "tier",
        "kind",
        "evaluated",
        "passed",
        "insufficient_data",
        "chosen_rt",
        "effective_threshold",
        "score_test_rt",
        "score_test_p",
        "bayesian_pick",
        "bayesian_posterior",
        "n_replicates",
        "n_replicates_with_signal",
        "members",
    ]
    return base + bb_cycle_field_names(library_cycle_count) + [
        "channel",
        "alpha",
        "tolerance",
        "time_unit",
        "isoform",
    ]


def export_pedigree_csv(result: PedigreeAnalysisResult, path: str | Path) -> Path:
    """Write one row per pedigree node."""
    out = Path(path)
    n_cycles = result.library_cycle_count
    null_token = result.null_token
    fieldnames = _pedigree_csv_fieldnames(n_cycles)
    settings = result.settings
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in result.records:
            chosen = chosen_rt_for_record(record)
            row = {
                "id": record.id,
                "label": record.label,
                "tier": record.tier,
                "kind": record.kind,
                "evaluated": int(record.evaluated),
                "passed": int(record.passed),
                "insufficient_data": int(record.insufficient_data),
                "chosen_rt": chosen if chosen is not None else "",
                "effective_threshold": (
                    record.effective_threshold
                    if record.effective_threshold is not None
                    else ""
                ),
                "score_test_rt": (
                    record.score_test_rt if record.score_test_rt is not None else ""
                ),
                "score_test_p": (
                    record.score_test_p_value
                    if record.score_test_p_value is not None
                    else ""
                ),
                "bayesian_pick": (
                    record.bayesian_pick if record.bayesian_pick is not None else ""
                ),
                "bayesian_posterior": (
                    record.bayesian_pick_posterior
                    if record.bayesian_pick_posterior is not None
                    else ""
                ),
                "n_replicates": record.n_replicates,
                "n_replicates_with_signal": record.n_replicates_with_signal,
                "members": "|".join(record.members),
                "channel": result.channel,
                "alpha": settings.alpha,
                "tolerance": settings.tolerance,
                "time_unit": settings.time_unit,
                "isoform": result.isoform_label,
            }
            row.update(
                bb_cycle_columns_for_record(
                    record,
                    library_cycle_count=n_cycles,
                    null_token=null_token,
                )
            )
            writer.writerow(row)
    return out


def export_product_prominence_csv(
    summary: ProductProminenceSummary,
    path: str | Path,
    *,
    result: Optional[PedigreeAnalysisResult] = None,
) -> Path:
    """Write one row per pedigree-validated product prominence entry."""
    out = Path(path)
    n_cycles = result.library_cycle_count if result is not None else 0
    null_token = result.null_token if result is not None else ""
    records_by_id: Dict[str, PedigreeNodeRecord] = {}
    if result is not None:
        records_by_id = {r.id: r for r in result.records}

    fieldnames = [
        "compound_id",
        "node_id",
        "chosen_rt",
        "prominence",
        "passed",
    ] + bb_cycle_field_names(n_cycles) + ["channel"]

    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for entry in summary.entries:
            row = {
                "compound_id": entry.compound_id,
                "node_id": entry.node_id,
                "chosen_rt": entry.chosen_rt,
                "prominence": entry.prominence,
                "passed": int(entry.passed),
                "channel": summary.channel,
            }
            record = records_by_id.get(entry.node_id)
            if record is not None and n_cycles > 0:
                row.update(
                    bb_cycle_columns_for_record(
                        record,
                        library_cycle_count=n_cycles,
                        null_token=null_token,
                    )
                )
            else:
                for name in bb_cycle_field_names(n_cycles):
                    row[name] = ""
            writer.writerow(row)
    return out


def bb_cycle_columns_for_compound_id(
    compound_id: str,
    records: Sequence[PedigreeNodeRecord],
    *,
    library_cycle_count: int,
    null_token: str,
) -> Dict[str, str]:
    """Look up a compound node's BB cycle columns by compound id or node label."""
    key = str(compound_id).strip()
    for record in records:
        if record.kind != "compound":
            continue
        if key in (str(record.id), str(record.label)) or key in record.members:
            return bb_cycle_columns_for_record(
                record,
                library_cycle_count=library_cycle_count,
                null_token=null_token,
            )
        if any(key == m.strip() for m in record.members):
            return bb_cycle_columns_for_record(
                record,
                library_cycle_count=library_cycle_count,
                null_token=null_token,
            )
    return {name: "" for name in bb_cycle_field_names(library_cycle_count)}
