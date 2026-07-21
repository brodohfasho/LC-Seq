# src/core/lineage_batch_export.py
"""Batch export helpers for multi-compound lineage analysis."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Literal, Sequence

import matplotlib.pyplot as plt

from src.core.analysis_export import export_figure
from src.core.csv_io import CSV_EXPORT_ENCODING
from src.core.lineage_export import export_lineage_csv
from src.core.lineage_render import render_lineage_figure
from src.models.pedigree_result import LineageAnalysisResult
from src.models.spreadsheet_config import SpreadsheetConfig

ImageFormat = Literal["png", "svg", "pdf"]


def safe_export_stem(compound_id: str) -> str:
    """Filesystem-safe stem from a compound id."""
    stem = re.sub(r"[^\w.\-]+", "_", str(compound_id).strip())
    return stem[:120] if stem else "compound"


def export_lineage_csv_combined(
    results: Sequence[LineageAnalysisResult],
    path: str | Path,
) -> Path:
    """Write one CSV with all compounds (compound_id column distinguishes rows)."""
    out = Path(path)
    if not results:
        raise ValueError("No lineage results to export.")

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
        for result in results:
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
                        "effective_threshold": (
                            rec.effective_threshold if rec.effective_threshold is not None else ""
                        ),
                        "score_test_rt": rec.score_test_rt if rec.score_test_rt is not None else "",
                        "score_test_rt_se": (
                            rec.score_test_rt_se if rec.score_test_rt_se is not None else ""
                        ),
                        "score_test_p_value": (
                            rec.score_test_p_value if rec.score_test_p_value is not None else ""
                        ),
                        "bayesian_pick": rec.bayesian_pick if rec.bayesian_pick is not None else "",
                        "bayesian_pick_posterior": (
                            rec.bayesian_pick_posterior
                            if rec.bayesian_pick_posterior is not None
                            else ""
                        ),
                        "n_replicates_with_signal": rec.n_replicates_with_signal,
                        "alpha": result.settings.alpha,
                        "tolerance": result.settings.tolerance,
                        "time_unit": result.settings.time_unit,
                    }
                )
    return out


def export_lineage_csv_separate(
    results: Sequence[LineageAnalysisResult],
    directory: str | Path,
) -> list[Path]:
    """Write one CSV per compound into ``directory``."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for result in results:
        stem = safe_export_stem(result.compound_id)
        dest = out_dir / f"{stem}_lineage.csv"
        n = 2
        while dest.exists() and n < 1000:
            dest = out_dir / f"{stem}_lineage_{n}.csv"
            n += 1
        paths.append(export_lineage_csv(result, dest))
    return paths


def export_lineage_figures_folder(
    results: Sequence[LineageAnalysisResult],
    config: SpreadsheetConfig,
    directory: str | Path,
    *,
    fmt: ImageFormat = "svg",
    dpi: int = 200,
) -> list[Path]:
    """Render and save one lineage figure per compound into ``directory``."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_fmt = fmt.lower().lstrip(".")
    if image_fmt not in ("png", "svg", "pdf"):
        image_fmt = "svg"

    paths: list[Path] = []
    for result in results:
        stem = safe_export_stem(result.compound_id)
        dest = out_dir / f"{stem}_lineage.{image_fmt}"
        n = 2
        while dest.exists() and n < 1000:
            dest = out_dir / f"{stem}_lineage_{n}.{image_fmt}"
            n += 1
        fig = render_lineage_figure(
            result,
            result.chromatogram_map,
            null_token=config.null_token,
        )
        try:
            export_figure(fig, dest, dpi=dpi)
            paths.append(dest)
        finally:
            plt.close(fig)
    return paths


def export_lineage_batch(
    results: Sequence[LineageAnalysisResult],
    config: SpreadsheetConfig,
    directory: str | Path,
    *,
    image_fmt: ImageFormat = "svg",
    separate_csv: bool = True,
    combined_csv: bool = True,
    dpi: int = 200,
) -> dict[str, list[Path] | Path]:
    """
    Export all lineage figures and CSVs into one folder.

    Returns paths written keyed by ``figures``, ``combined_csv``, ``separate_csv``.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, list[Path] | Path] = {}

    written["figures"] = export_lineage_figures_folder(
        results,
        config,
        out_dir,
        fmt=image_fmt,
        dpi=dpi,
    )
    if combined_csv:
        written["combined_csv"] = export_lineage_csv_combined(results, out_dir / "lineage_combined.csv")
    if separate_csv:
        csv_dir = out_dir / "csv_per_compound"
        written["separate_csv"] = export_lineage_csv_separate(results, csv_dir)
    return written
