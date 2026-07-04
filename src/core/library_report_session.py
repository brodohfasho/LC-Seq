# src/core/library_report_session.py
"""Session artifacts for Option-A library PDF reports (embed what the user already ran)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.core.library_metrics import LibraryComputationSnapshot, MetricResult, PlotResult
from src.core.library_report_models import LibraryReportOptions
from src.core.pedigree_render import PedigreeTreeRenderOptions
from src.models.analysis_settings import AnalysisSettings


@dataclass
class LibraryQcMetricsArtifact:
    """Metrics computed during the active Library Analysis session."""

    generated_at: datetime
    snapshot: LibraryComputationSnapshot
    metric_ids: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)


@dataclass
class LibraryQcPlotsArtifact:
    """Plot PNGs generated during the active session."""

    generated_at: datetime
    plot_results: List[PlotResult] = field(default_factory=list)
    plot_ids: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)


@dataclass
class RtAssignmentReportArtifact:
    """RT assignment run captured from the RT assignment tab."""

    generated_at: datetime
    analysis_mode: str
    settings: AnalysisSettings
    channel: str
    time_unit: str
    isoform: str
    rt_source: str
    rt_threshold: float
    n_products: int
    n_verified: int
    n_rt_from_pedigree: int
    n_rt_from_peak_pick: int
    n_rt_from_metadata: int
    peak_picking_algorithm: str = ""


@dataclass
class PedigreeVizReportArtifact:
    """Pedigree tier-ring figure from pedigree RT assignment."""

    generated_at: datetime
    image_path: Path
    caption: str
    tree_opts: PedigreeTreeRenderOptions
    n_nodes: int
    n_chromatograms: int
    backend_name: str = ""
    tree_render_engine: str = ""


@dataclass
class SplittreeVizReportArtifact:
    """Split-tree figure generated on the Split-tree visualization tab."""

    generated_at: datetime
    image_path: Path
    caption: str
    rt_source: str
    rt_column: str
    verified_column: str
    isoform: str
    view_mode: str
    branch_bb1: str
    color_mode: str
    color_by_rt: bool
    pass_pct_cutoff: float
    rt_threshold: float
    del_rt_source: str
    n_verified: int
    n_products: int
    branch_figures: List[Path] = field(default_factory=list)


@dataclass
class LibraryReportSession:
    """Optional session artifacts available for PDF assembly."""

    database_path: str
    database_name: str
    database_kind: str
    scan_entries_used: int = 0
    scan_entries_attempted: int = 0
    scan_entries_skipped: int = 0
    qc_metrics: Optional[LibraryQcMetricsArtifact] = None
    qc_plots: Optional[LibraryQcPlotsArtifact] = None
    rt_assignment: Optional[RtAssignmentReportArtifact] = None
    pedigree_viz: Optional[PedigreeVizReportArtifact] = None
    splittree_viz: Optional[SplittreeVizReportArtifact] = None

    def available_section_keys(self) -> List[str]:
        keys: List[str] = []
        if self.qc_metrics is not None and self.qc_metrics.metric_ids:
            keys.append("metrics")
        if self.qc_plots is not None and self.qc_plots.plot_ids:
            keys.append("plots")
        if self.rt_assignment is not None:
            keys.append("rt_assignment")
        if self.pedigree_viz is not None:
            keys.append("pedigree_viz")
        if self.splittree_viz is not None:
            keys.append("splittree")
        return keys


def missing_report_sections(
    options: LibraryReportOptions,
    session: LibraryReportSession,
) -> List[str]:
    """Return human-readable labels for selected sections that have no session artifact."""
    missing: List[str] = []
    if options.include_metrics and session.qc_metrics is None:
        missing.append("Summary metrics (run Calculate metrics on the Metrics tab)")
    if options.include_plots and session.qc_plots is None:
        missing.append("Visualizations (run Generate plots on the Plots tab)")
    if options.include_rt_assignment and session.rt_assignment is None:
        missing.append("RT assignment (run RT assignment on the RT assignment tab)")
    if options.include_pedigree_viz and session.pedigree_viz is None:
        missing.append(
            "Pedigree visualization (run pedigree RT assignment, then open Pedigree visualization)"
        )
    if options.include_splittree and session.splittree_viz is None:
        missing.append("Split-tree (click Generate plot on the Split-tree visualization tab)")
    return missing


def build_report_snapshot(session: LibraryReportSession) -> LibraryComputationSnapshot:
    """Minimal computation snapshot for PDF title/summary rows."""
    from datetime import timezone

    from src.core.library_metrics import LibraryComputationSnapshot

    metrics = session.qc_metrics
    plots = session.qc_plots
    generated_at = (
        metrics.generated_at
        if metrics is not None
        else plots.generated_at
        if plots is not None
        else datetime.now(timezone.utc)
    )
    if metrics is not None:
        snap = metrics.snapshot
        return LibraryComputationSnapshot(
            processed_at=generated_at,
            database_path=snap.database_path or session.database_path,
            database_kind=snap.database_kind or session.database_kind,
            fraction_count=snap.fraction_count,
            selected_channels=list(metrics.channels),
            selected_metrics=list(metrics.metric_ids),
            selected_plots=list(plots.plot_ids) if plots else [],
            entries_attempted=snap.entries_attempted or session.scan_entries_attempted,
            entries_used=snap.entries_used or session.scan_entries_used,
            entries_skipped=snap.entries_skipped or session.scan_entries_skipped,
            metric_results=list(snap.metric_results),
            plot_results=list(plots.plot_results) if plots else [],
            signal_quality_alpha=snap.signal_quality_alpha,
        )
    return LibraryComputationSnapshot(
        processed_at=generated_at,
        database_path=session.database_path,
        database_kind=session.database_kind,
        fraction_count=96,
        selected_channels=list(plots.channels) if plots else [],
        selected_metrics=[],
        selected_plots=list(plots.plot_ids) if plots else [],
        entries_attempted=session.scan_entries_attempted,
        entries_used=session.scan_entries_used,
        entries_skipped=session.scan_entries_skipped,
        metric_results=[],
        plot_results=list(plots.plot_results) if plots else [],
        signal_quality_alpha=0.001,
    )
