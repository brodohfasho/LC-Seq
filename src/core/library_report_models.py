# src/core/library_report_models.py
"""Data models for Library Data PDF report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class LibraryReportOptions:
    """User-selected sections to include in a library report."""

    include_metrics: bool
    include_plots: bool
    include_rt_assignment: bool
    include_pedigree_viz: bool
    include_splittree: bool
    metric_ids: List[str] = field(default_factory=list)
    plot_ids: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)

    @property
    def include_pedigree(self) -> bool:
        """Legacy alias for pedigree tier-ring section."""
        return self.include_pedigree_viz

    @property
    def include_del_cycle(self) -> bool:
        """Legacy alias for split-tree section."""
        return self.include_splittree


@dataclass(frozen=True)
class LibraryReportPrerequisites:
    """Session artifacts still required before the PDF can be written."""

    missing_sections: List[str] = field(default_factory=list)

    @property
    def needs_work(self) -> bool:
        return bool(self.missing_sections)

    @property
    def ready(self) -> bool:
        return not self.missing_sections

    @property
    def notes(self) -> List[str]:
        return list(self.missing_sections)


@dataclass(frozen=True)
class LibraryReportSectionStatus:
    """Readiness summary for one report section shown in the dialog."""

    key: str
    label: str
    selected: bool
    ready: bool
    detail: str
    item_ids: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LibraryReportPedigreeBranchFigure:
    """One DEL-cycle BB1 branch figure for the report."""

    bb1_name: str
    image_path: Path
    bb1_index: Optional[int] = None
    caption: str = ""


@dataclass
class LibraryReportPedigreeFigures:
    """Pedigree and DEL-cycle figure paths embedded in the report."""

    tier_ring_path: Optional[Path] = None
    tier_ring_caption: str = ""
    del_full_tree_path: Optional[Path] = None
    del_full_tree_caption: str = ""
    del_branch_figures: List[LibraryReportPedigreeBranchFigure] = field(default_factory=list)
    bb_index_reference: List[Tuple[int, str]] = field(default_factory=list)
    null_token: str = ""


@dataclass
class LibraryReportAuditTrail:
    """Provenance and settings snapshot for the report audit section."""

    generated_at: datetime
    database_path: str
    database_name: str
    database_kind: str
    report_options: LibraryReportOptions
    # Run metadata
    computed_scan: bool = False
    computed_metrics: bool = False
    computed_plots: bool = False
    computed_pedigree: bool = False
    computed_del_tree: bool = False
    # Metrics module
    fraction_count: int = 96
    signal_quality_alpha: float = 0.001
    min_prominence: float = 0.0
    min_pct_area: float = 0.0
    # Pedigree module (when included)
    pedigree_channel: str = ""
    pedigree_time_unit: str = ""
    pedigree_tolerance: float = 0.0
    pedigree_alpha: float = 0.001
    pedigree_peak_picker: str = ""
    pedigree_isoform: str = "All"
    pedigree_max_display_tier: Optional[int] = None
    pedigree_include_failed: bool = True
    pedigree_show_rt: bool = True
    rt_analysis_mode: str = ""
    splittree_rt_source: str = ""
    splittree_rt_column: str = ""
    splittree_verified_column: str = ""
    splittree_isoform: str = "All"
    splittree_view_mode: str = ""
    del_color_mode: str = "notebook"
    del_color_by_rt: bool = False
    del_rt_threshold: float = 0.0
    del_rt_source: str = ""
    del_n_bb1_branches: int = 0
    # Extra lines (free-form notes)
    notes: List[str] = field(default_factory=list)

    def audit_rows(self) -> List[List[str]]:
        """Key-value rows for the PDF audit table."""
        opts = self.report_options
        rows: List[List[str]] = [
            ["Generated", self._fmt_time(self.generated_at)],
            ["Database file", self.database_name],
            ["Database path", self.database_path],
            ["Database kind", self.database_kind],
            ["Include summary metrics", "Yes" if opts.include_metrics else "No"],
            ["Include visualizations", "Yes" if opts.include_plots else "No"],
            ["Include RT assignment", "Yes" if opts.include_rt_assignment else "No"],
            ["Include pedigree visualization", "Yes" if opts.include_pedigree_viz else "No"],
            ["Include split-tree", "Yes" if opts.include_splittree else "No"],
        ]
        if opts.include_metrics:
            rows.extend(
                [
                    ["Metrics selected", ", ".join(opts.metric_ids) or "—"],
                    ["Report channels", ", ".join(opts.channels) or "—"],
                    ["Fraction count", str(self.fraction_count)],
                    ["Peak significance α", f"{self.signal_quality_alpha:g}"],
                    ["Min prominence", f"{self.min_prominence:g}"],
                    ["Min % area", f"{self.min_pct_area:g}"],
                ]
            )
        if opts.include_plots:
            rows.extend(
                [
                    ["Plots selected", ", ".join(opts.plot_ids) or "—"],
                ]
            )
        if opts.include_rt_assignment:
            rows.extend(
                [
                    ["RT analysis mode", self.rt_analysis_mode or "—"],
                    ["RT assignment channel", self.pedigree_channel or "—"],
                    ["RT assignment time unit", self.pedigree_time_unit or "—"],
                    ["RT assignment tolerance", f"{self.pedigree_tolerance:g}"],
                    ["RT assignment isoform", self.pedigree_isoform],
                    ["Peak picker", self.pedigree_peak_picker or "—"],
                ]
            )
        if opts.include_pedigree_viz:
            rows.extend(
                [
                    ["Pedigree max tier displayed", str(self.pedigree_max_display_tier)],
                    ["Show failed trim points", "Yes" if self.pedigree_include_failed else "No"],
                    ["Show RT on passed nodes", "Yes" if self.pedigree_show_rt else "No"],
                ]
            )
        if opts.include_splittree:
            rows.extend(
                [
                    ["Split-tree RT source", self.splittree_rt_source or "—"],
                    ["Split-tree RT column", self.splittree_rt_column or "—"],
                    ["Split-tree verification column", self.splittree_verified_column or "—"],
                    ["Split-tree isoform", self.splittree_isoform or "—"],
                    ["Split-tree view", self.splittree_view_mode or "—"],
                    ["DEL color mode", self.del_color_mode],
                    ["DEL color leaves by RT", "Yes" if self.del_color_by_rt else "No"],
                    ["DEL RT threshold", f"{self.del_rt_threshold:g}"],
                    ["DEL RT resolution source", self.del_rt_source or "—"],
                ]
            )
        for note in self.notes:
            rows.append(["Note", note])
        return rows

    @staticmethod
    def _fmt_time(when: datetime) -> str:
        if when.tzinfo is None:
            return when.strftime("%Y-%m-%d %H:%M:%S")
        return when.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
