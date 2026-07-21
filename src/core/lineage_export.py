# src/core/lineage_export.py
"""Export lineage analysis tables."""

from __future__ import annotations

import csv
from pathlib import Path

from src.core.csv_io import CSV_EXPORT_ENCODING
from src.models.pedigree_result import LineageAnalysisResult


def export_lineage_csv(result: LineageAnalysisResult, path: str | Path) -> Path:
    """Write one row per lineage panel with evaluation summary fields."""
    out = Path(path)
    fieldnames = [
        "compound_id",
        "channel",
        "tier",
        "class_bbs",
        "node_id",
        "n_replicates",
        "evaluated",
        "passed",
        "insufficient_data",
        "effective_threshold",
        "score_test_rt",
        "score_test_rt_se",
        "score_test_p_value",
        "bayesian_pick",
        "bayesian_pick_posterior",
        "n_replicates_with_signal",
        "alpha",
        "tolerance",
        "time_unit",
    ]
    with out.open("w", encoding=CSV_EXPORT_ENCODING, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for panel in result.panels:
            rec = panel.record
            writer.writerow(
                {
                    "compound_id": result.compound_id,
                    "channel": result.channel,
                    "tier": panel.tier,
                    "class_bbs": "|".join(panel.class_bbs),
                    "node_id": rec.id,
                    "n_replicates": panel.n_replicates,
                    "evaluated": int(rec.evaluated),
                    "passed": int(rec.passed),
                    "insufficient_data": int(rec.insufficient_data),
                    "effective_threshold": rec.effective_threshold if rec.effective_threshold is not None else "",
                    "score_test_rt": rec.score_test_rt if rec.score_test_rt is not None else "",
                    "score_test_rt_se": rec.score_test_rt_se if rec.score_test_rt_se is not None else "",
                    "score_test_p_value": rec.score_test_p_value if rec.score_test_p_value is not None else "",
                    "bayesian_pick": rec.bayesian_pick if rec.bayesian_pick is not None else "",
                    "bayesian_pick_posterior": (
                        rec.bayesian_pick_posterior if rec.bayesian_pick_posterior is not None else ""
                    ),
                    "n_replicates_with_signal": rec.n_replicates_with_signal,
                    "alpha": result.settings.alpha,
                    "tolerance": result.settings.tolerance,
                    "time_unit": result.settings.time_unit,
                }
            )
    return out
