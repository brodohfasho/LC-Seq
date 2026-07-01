# src/core/pedigree_export.py
"""Export pedigree analysis tables."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

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


def export_pedigree_csv(result: PedigreeAnalysisResult, path: str | Path) -> Path:
    """Write one row per pedigree node."""
    out = Path(path)
    fieldnames = [
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
        "channel",
        "alpha",
        "tolerance",
        "time_unit",
        "isoform",
    ]
    settings = result.settings
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in result.records:
            chosen = chosen_rt_for_record(record)
            writer.writerow(
                {
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
            )
    return out


def export_product_prominence_csv(
    summary: ProductProminenceSummary,
    path: str | Path,
) -> Path:
    """Write one row per pedigree-validated product prominence entry."""
    out = Path(path)
    fieldnames = [
        "compound_id",
        "node_id",
        "chosen_rt",
        "prominence",
        "passed",
        "channel",
    ]
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for entry in summary.entries:
            writer.writerow(
                {
                    "compound_id": entry.compound_id,
                    "node_id": entry.node_id,
                    "chosen_rt": entry.chosen_rt,
                    "prominence": entry.prominence,
                    "passed": int(entry.passed),
                    "channel": summary.channel,
                }
            )
    return out
