# src/ui/library_analysis/state.py
"""Typed session state for the Library Analysis window."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from src.core.del_cycle_tree import DelCycleTreeData
from src.core.library_metrics import LibraryComputationSnapshot, LibraryScanData, PlotResult
from src.core.library_report_session import (
    LibraryQcMetricsArtifact,
    LibraryQcPlotsArtifact,
    PedigreeVizReportArtifact,
    RtAssignmentReportArtifact,
    SplittreeVizReportArtifact,
)
from src.models.pedigree_result import PedigreeAnalysisResult


@dataclass
class LibraryAnalysisState:
    """Own the mutable analysis results associated with one window session."""

    scan: Optional[LibraryScanData] = None
    snapshot: Optional[LibraryComputationSnapshot] = None
    snapshot_path: Optional[Path] = None
    plots: List[PlotResult] = field(default_factory=list)
    qc_metrics_artifact: Optional[LibraryQcMetricsArtifact] = None
    qc_plots_artifact: Optional[LibraryQcPlotsArtifact] = None
    rt_assignment_artifact: Optional[RtAssignmentReportArtifact] = None
    pedigree_viz_artifact: Optional[PedigreeVizReportArtifact] = None
    splittree_viz_artifact: Optional[SplittreeVizReportArtifact] = None
    pedigree_result: Optional[PedigreeAnalysisResult] = None
    pedigree_snapshot_path: Optional[Path] = None
    rt_assignment_result: Optional[DelCycleTreeData] = None
    splittree_result: Optional[DelCycleTreeData] = None

    def activate_scan(
        self,
        scan: LibraryScanData,
        snapshot: LibraryComputationSnapshot,
    ) -> None:
        """Replace the scan and invalidate every result derived from the old scan."""
        self.invalidate_scan()
        self.scan = scan
        self.snapshot = snapshot

    def invalidate_scan(self) -> None:
        """Clear the scan and all artifacts whose provenance depends on it."""
        self.scan = None
        self.snapshot = None
        self.snapshot_path = None
        self.plots.clear()
        self.qc_metrics_artifact = None
        self.qc_plots_artifact = None
        self.invalidate_rt_analysis()

    def invalidate_qc_results(self) -> None:
        """Clear computed QC results while retaining the parsed scan."""
        self.snapshot = None
        self.snapshot_path = None
        self.plots.clear()
        self.qc_metrics_artifact = None
        self.qc_plots_artifact = None

    def invalidate_rt_analysis(self) -> None:
        """Clear RT, pedigree, split-tree, and corresponding report artifacts."""
        self.rt_assignment_artifact = None
        self.pedigree_viz_artifact = None
        self.splittree_viz_artifact = None
        self.pedigree_result = None
        self.pedigree_snapshot_path = None
        self.rt_assignment_result = None
        self.splittree_result = None

    def invalidate_splittree(self) -> None:
        """Clear only the generated split-tree result and report artifact."""
        self.splittree_result = None
        self.splittree_viz_artifact = None
