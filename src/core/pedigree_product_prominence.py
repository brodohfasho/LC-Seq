# src/core/pedigree_product_prominence.py
"""
Pedigree-validated product-peak prominence (Phase 5.7).

For each full-compound pedigree node that passed, measure prominence at the
algorithm-chosen retention time on that compound's chromatogram.
"""

from __future__ import annotations

import logging
import statistics
from typing import Dict, List, Optional, Sequence

from src.core.pedigree_adapter import truncate_positions_from_metadata
from src.core.pedigree_export import chosen_rt_for_record
from src.core.peak_picker_python import prominence_at_rt
from src.models.compound import Compound
from src.models.pedigree_result import (
    EntryProductProminence,
    PedigreeNodeRecord,
    ProductProminenceSummary,
)
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)


def truncate_display_label(compound: Compound, config: SpreadsheetConfig) -> Optional[str]:
    """Rust ``Truncate::display`` — N→C positions joined by ``-``."""
    positions = truncate_positions_from_metadata(compound, config)
    if positions is None:
        return None
    return "-".join(positions)


def _build_display_to_compound_id(
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for compound in compounds:
        label = truncate_display_label(compound, config)
        cid = str(compound.compound_id).strip()
        if label:
            mapping[label] = cid
        mapping[cid] = cid
        if compound.primary_compound_id:
            mapping[str(compound.primary_compound_id).strip()] = cid
    return mapping


def _chromatogram_for_compound(
    compound: Compound,
    channel: str,
) -> Optional[tuple[List[float], List[float]]]:
    try:
        times, counts = compound.get_time_series(channel)
    except ValueError:
        return None
    if len(times) < 3:
        return None
    return [float(t) for t in times], [float(c) for c in counts]


def compute_product_prominence_summary(
    records: Sequence[PedigreeNodeRecord],
    compounds: Sequence[Compound],
    config: SpreadsheetConfig,
    channel: str,
) -> ProductProminenceSummary:
    """
    Compute per-compound and library-mean product prominence from pedigree results.

    Only ``kind == "compound"`` nodes are considered. Prominence is measured at
    ``chosen_rt`` for nodes that passed pedigree evaluation.
    """
    display_to_id = _build_display_to_compound_id(compounds, config)
    compound_by_id = {str(c.compound_id).strip(): c for c in compounds}

    entries: List[EntryProductProminence] = []
    prominences: List[float] = []
    n_compound = 0
    n_skipped = 0

    for record in records:
        if record.kind != "compound":
            continue
        n_compound += 1
        chosen = chosen_rt_for_record(record)
        if not record.passed or chosen is None:
            n_skipped += 1
            continue

        lookup_keys = list(record.members) if record.members else [record.label]
        compound_id: Optional[str] = None
        for key in lookup_keys:
            compound_id = display_to_id.get(str(key).strip())
            if compound_id:
                break
        if compound_id is None:
            compound_id = display_to_id.get(str(record.label).strip())

        compound = compound_by_id.get(compound_id or "")
        if compound is None:
            logger.debug("No compound match for pedigree node %s", record.id)
            n_skipped += 1
            continue

        chrom = _chromatogram_for_compound(compound, channel)
        if chrom is None:
            n_skipped += 1
            continue

        rt, intensity = chrom
        prom = prominence_at_rt(rt, intensity, float(chosen))
        if prom is None:
            n_skipped += 1
            continue

        entries.append(
            EntryProductProminence(
                compound_id=compound_id or str(compound.compound_id),
                node_id=record.id,
                chosen_rt=float(chosen),
                prominence=float(prom),
                passed=True,
            )
        )
        prominences.append(float(prom))

    if prominences:
        mean_val = float(statistics.mean(prominences))
        std_val = float(statistics.stdev(prominences)) if len(prominences) > 1 else 0.0
    else:
        mean_val = 0.0
        std_val = 0.0

    return ProductProminenceSummary(
        channel=channel,
        mean=mean_val,
        std_dev=std_val,
        n_pass_with_prominence=len(prominences),
        n_compound_nodes=n_compound,
        n_skipped=n_skipped,
        entries=entries,
    )
