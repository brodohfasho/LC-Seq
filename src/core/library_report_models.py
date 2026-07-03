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
    include_pedigree: bool
    include_del_cycle: bool
    metric_ids: List[str] = field(default_factory=list)
    plot_ids: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LibraryReportPrerequisites:
    """Which computations must run before the PDF can be written."""

    needs_scan: bool = False
    needs_metrics: bool = False
    needs_plots: bool = False
    needs_pedigree: bool = False
    needs_del_cycle: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def needs_work(self) -> bool:
        return (
            self.needs_scan
            or self.needs_metrics
            or self.needs_plots
            or self.needs_pedigree
            or self.needs_del_cycle
        )


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
            ["Include pedigree analysis", "Yes" if opts.include_pedigree else "No"],
            ["Include DEL-cycle analysis", "Yes" if opts.include_del_cycle else "No"],
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
                    ["Metrics computed for report", "Yes" if self.computed_metrics else "No (cached)"],
                ]
            )
        if opts.include_plots:
            rows.extend(
                [
                    ["Plots selected", ", ".join(opts.plot_ids) or "—"],
                    ["Plots computed for report", "Yes" if self.computed_plots else "No (cached)"],
                ]
            )
        if opts.include_pedigree:
            rows.extend(
                [
                    ["Pedigree channel", self.pedigree_channel or "—"],
                    ["Pedigree time unit", self.pedigree_time_unit or "—"],
                    ["Pedigree tolerance", f"{self.pedigree_tolerance:g}"],
                    ["Pedigree α", f"{self.pedigree_alpha:g}"],
                    ["Peak picker", self.pedigree_peak_picker or "—"],
                    ["Isoform filter", self.pedigree_isoform],
                    ["Max tier displayed", str(self.pedigree_max_display_tier)],
                    ["Show failed trim points", "Yes" if self.pedigree_include_failed else "No"],
                    ["Show RT on passed nodes", "Yes" if self.pedigree_show_rt else "No"],
                    ["Pedigree computed for report", "Yes" if self.computed_pedigree else "No (cached)"],
                ]
            )
        if opts.include_del_cycle:
            rows.extend(
                [
                    ["DEL color mode", self.del_color_mode],
                    ["DEL color leaves by RT", "Yes" if self.del_color_by_rt else "No"],
                    ["DEL RT threshold", f"{self.del_rt_threshold:g}"],
                    ["DEL RT source", self.del_rt_source or "—"],
                    ["DEL BB1 branches in report", str(self.del_n_bb1_branches)],
                    ["DEL tree computed for report", "Yes" if self.computed_del_tree else "No (cached)"],
                ]
            )
        if self.computed_scan:
            rows.append(["Library scan", "Computed fresh for this report"])
        for note in self.notes:
            rows.append(["Note", note])
        return rows

    @staticmethod
    def _fmt_time(when: datetime) -> str:
        if when.tzinfo is None:
            return when.strftime("%Y-%m-%d %H:%M:%S")
        return when.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
