# src/core/del_cycle_tree/export.py
"""CSV export for DEL-cycle split-tree analysis."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Tuple

from src.core.del_cycle_tree.bb_index_scheme import lookup_bb_display_index
from src.core.del_cycle_tree.models import DelCycleTreeData
from src.core.pedigree_export import bb_cycle_field_names


def _del_cycle_csv_fieldnames(library_cycle_count: int) -> List[str]:
    cycles = bb_cycle_field_names(library_cycle_count)
    return [
        "row_kind",
        *cycles,
        "rt",
        "rt_verified",
        "pedigree_passed",
        "bb1_index",
        "bb2_index",
        "bb3_index",
        "bb4_index",
        "rt_threshold",
        "rt_source",
        "peak_picking_algorithm",
        "n_rt_from_pedigree",
        "n_rt_from_peak_pick",
        "n_rt_from_metadata",
        "n_rt_verified_pedigree_agree",
        "full_null_rt",
    ]


def _cycle_indices(
    positions: Tuple[str, ...],
    index_map: Dict[str, int],
    *,
    null_token: str,
) -> Dict[str, int | None]:
    out: Dict[str, int | None] = {}
    for cycle in range(1, 5):
        key = f"bb{cycle}_index"
        if cycle - 1 < len(positions):
            out[key] = lookup_bb_display_index(
                positions[cycle - 1],
                index_map,
                null_token=null_token,
            )
        else:
            out[key] = None
    return out


def _cycle_columns(positions: Tuple[str, ...], n_cycles: int) -> Dict[str, str]:
    cols = bb_cycle_field_names(n_cycles)
    out = {name: "" for name in cols}
    for index, name in enumerate(cols):
        if index < len(positions):
            out[name] = positions[index]
    return out


def _summary_metadata(data: DelCycleTreeData) -> Dict[str, object]:
    return {
        "rt_threshold": data.rt_threshold,
        "rt_source": data.rt_source,
        "peak_picking_algorithm": data.peak_picking_algorithm,
        "n_rt_from_pedigree": data.n_rt_from_pedigree,
        "n_rt_from_peak_pick": data.n_rt_from_peak_pick,
        "n_rt_from_metadata": data.n_rt_from_metadata,
        "n_rt_verified_pedigree_agree": data.n_rt_verified_pedigree_agree,
        "full_null_rt": data.full_null_rt if data.full_null_rt is not None else "",
    }


def export_del_cycle_csv(data: DelCycleTreeData, path: str | Path) -> Path:
    """
    Write DEL-cycle verification results to CSV.

    Includes one summary row plus one row per full product.
    """
    out = Path(path)
    n_cycles = data.library_cycle_count
    null_token = data.null_token
    fieldnames = _del_cycle_csv_fieldnames(n_cycles)
    meta = _summary_metadata(data)

    product_rows: List[Dict[str, object]] = []
    for positions, info in sorted(
        data.verified_sequences.items(),
        key=lambda item: item[0],
    ):
        if len(positions) != n_cycles:
            continue
        indices = _cycle_indices(
            positions,
            data.bb_index_global,
            null_token=null_token,
        )
        row: Dict[str, object] = {
            "row_kind": "product",
            "rt": info.rt,
            "rt_verified": int(info.success),
            "pedigree_passed": (
                int(data.pedigree_passed_by_product[positions])
                if positions in data.pedigree_passed_by_product
                else ""
            ),
            "bb1_index": indices["bb1_index"] if indices["bb1_index"] is not None else "",
            "bb2_index": indices["bb2_index"] if indices["bb2_index"] is not None else "",
            "bb3_index": indices["bb3_index"] if indices["bb3_index"] is not None else "",
            "bb4_index": indices["bb4_index"] if indices["bb4_index"] is not None else "",
            **meta,
        }
        row.update(_cycle_columns(positions, n_cycles))
        product_rows.append(row)

    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        summary: Dict[str, object] = {
            "row_kind": "summary",
            "rt": "",
            "rt_verified": data.n_verified,
            "pedigree_passed": data.n_pedigree_passed,
            "bb1_index": "",
            "bb2_index": "",
            "bb3_index": "",
            "bb4_index": "",
            **meta,
        }
        summary.update({name: "" for name in bb_cycle_field_names(n_cycles)})
        writer.writerow(summary)
        for row in product_rows:
            writer.writerow(row)
    return out
