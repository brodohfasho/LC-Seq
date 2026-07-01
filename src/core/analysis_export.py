# src/core/analysis_export.py
"""Export peak analysis tables and figures."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from matplotlib.figure import Figure

from src.models.peak_result import PeakAnalysisBatchResult, PeakAnalysisResult


def peaks_to_dataframe(result: "PeakAnalysisResult") -> pd.DataFrame:
    """Build a table suitable for CSV export (single compound)."""
    return peaks_batch_to_dataframe(
        PeakAnalysisBatchResult(
            settings=result.settings,
            channel=result.channel,
            results=[result],
            backend_name=result.backend_name,
            computed_at=result.computed_at,
        ),
        include_variant=result.variant_label is not None,
        id_column_name="compound_id",
    )


def peaks_batch_to_dataframe(
    batch: "PeakAnalysisBatchResult",
    *,
    include_variant: bool,
    id_column_name: str = "compound_id",
) -> pd.DataFrame:
    """Build a combined peak table for one or more compounds."""
    rows = []
    for entry in batch.results:
        lib_id = entry.primary_compound_id or entry.compound_id
        for p in entry.peaks:
            row = {
                id_column_name: lib_id,
                "storage_id": entry.compound_id,
                "peak": p.peak_index,
                "retention_time": p.rt,
                "max_intensity": p.intensity,
                "area": p.area,
                "pct_area": round(p.pct_area, 4),
                "prominence": p.prominence,
                "p_value": p.p_value,
                "left_rt": p.left_rt,
                "right_rt": p.right_rt,
            }
            if p.suspected_peak_id is not None:
                row["suspected_peak_id"] = p.suspected_peak_id
            if include_variant:
                row["variant"] = entry.variant_label or ""
            rows.append(row)
    return pd.DataFrame(rows)


def export_peaks_csv(result: "PeakAnalysisResult", path: str | Path) -> Path:
    """Write peak table to CSV."""
    out = Path(path)
    include_variant = result.variant_label is not None
    df = peaks_batch_to_dataframe(
        PeakAnalysisBatchResult(
            settings=result.settings,
            channel=result.channel,
            results=[result],
            backend_name=result.backend_name,
            computed_at=result.computed_at,
        ),
        include_variant=include_variant,
        id_column_name="compound_id",
    )
    meta = {
        "compound_id": result.compound_id,
        "channel": result.channel,
        "alpha": result.settings.alpha,
        "time_unit": result.settings.time_unit,
        "backend": result.backend_name,
    }
    if result.baseline is not None:
        meta["baseline_mu"] = result.baseline.mu
        meta["baseline_sigma"] = result.baseline.sigma
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# " + ", ".join(f"{k}={v}" for k, v in meta.items()) + "\n")
    df.to_csv(out, mode="a", index=False)
    return out


def export_peaks_batch_csv(
    batch: "PeakAnalysisBatchResult",
    path: str | Path,
    *,
    id_column_name: str = "compound_id",
    include_variant: bool = False,
) -> Path:
    """Write a multi-compound peak table to CSV."""
    out = Path(path)
    df = peaks_batch_to_dataframe(
        batch,
        include_variant=include_variant,
        id_column_name=id_column_name,
    )
    meta = {
        "compounds": len(batch.results),
        "peaks": batch.total_peak_count,
        "channel": batch.channel,
        "alpha": batch.settings.alpha,
        "time_unit": batch.settings.time_unit,
        "backend": batch.backend_name,
    }
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# " + ", ".join(f"{k}={v}" for k, v in meta.items()) + "\n")
    df.to_csv(out, mode="a", index=False)
    return out


def export_figure(fig: "Figure", path: str | Path, dpi: int = 150) -> Path:
    """Save matplotlib figure."""
    from src.core.lineage_render import is_lineage_export_figure

    out = Path(path)
    if is_lineage_export_figure(fig):
        fig.savefig(
            out,
            dpi=dpi,
            facecolor=fig.get_facecolor(),
            bbox_inches=None,
            pad_inches=0.05,
        )
    else:
        fig.savefig(out, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    return out
