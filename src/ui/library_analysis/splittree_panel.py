# src/ui/library_analysis/splittree_panel.py
"""Composed split-tree visualization responsibilities for Library Analysis."""

from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Tuple

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.data_store import DataStore
from src.core.del_cycle_tree import (
    DelCycleExportResult,
    DelCycleTreeData,
    DelCycleTreeView,
    build_del_cycle_tree_from_metadata_for_path,
    build_del_cycle_tree_from_session_cache_for_path,
    export_del_cycle_package,
    registered_metadata_column_names,
    render_del_cycle_tree_figure,
    validate_registered_metadata_columns,
)
from src.core.del_cycle_tree.bb_index_scheme import (
    format_bb_branch_label,
    lookup_bb_display_index,
)
from src.core.del_cycle_tree.models import MetadataRtColumnInfo
from src.core.del_cycle_tree.service import metadata_columns_for_split_tree
from src.core.del_cycle_tree.render import COLOR_MODE_NOTEBOOK, COLOR_MODE_PEDIGREE
from src.ui.library_analysis.contexts import (
    LibraryPanelContext,
    SplitTreePanelCallbacks,
)
from src.ui.library_analysis.figure_host import FigureHost, build_tree_figure_host
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.task_coordinator import TaskCoordinator

logger = logging.getLogger(__name__)

SPLITTREE_RT_SESSION = "Session RT assignment"
SPLITTREE_RT_METADATA = "Spreadsheet metadata"
SPLITTREE_VIEW_FULL = "Full tree"
SPLITTREE_VIEW_BRANCH = "BB1 branch"
SPLITTREE_VIEW_MODES = (SPLITTREE_VIEW_FULL, SPLITTREE_VIEW_BRANCH)
_SIDEBAR_WRAP = 280
_SECTION_HEADER_COLOR = ("#0969da", "#58a6ff")
_SELECT_COLUMN = "(select column)"


@dataclass(frozen=True)
class _MetadataValidationSelection:
    """Metadata RT column and isoform covered by one successful validation."""

    rt_column: str
    isoform: str

class SplitTreePanelContext(LibraryPanelContext, Protocol):
    """Typed host capability surface supplied through composition."""


class SplitTreePanel:
    """Own split-tree controls, source decisions, tasks, rendering, and results."""

    def __init__(
        self,
        context: SplitTreePanelContext,
        callbacks: SplitTreePanelCallbacks,
    ) -> None:
        self._context = context
        self._callbacks = callbacks
        self._metadata_tasks = TaskCoordinator(
            context._dispatch_to_tk,
            context._ui_is_active,
        )
        self._validated_metadata_selection: Optional[_MetadataValidationSelection] = None

    def initialize(self) -> None:
        """Initialize host-visible state retained for public API compatibility."""
        host = self._context
        host._splittree_isoform_var = tk.StringVar(value="All")
        host._splittree_view_mode_var = tk.StringVar(value=SPLITTREE_VIEW_FULL)
        host._splittree_rt_source_var = tk.StringVar(value=SPLITTREE_RT_SESSION)
        host._splittree_metadata_rt_column_var = tk.StringVar(value="")
        host._splittree_generate_btn = None
        host._splittree_rt_column_menu = None
        host._splittree_rt_detect_btn = None
        host._splittree_rt_column_status_label = None
        host._splittree_metadata_validation_status_label = None
        host._splittree_metadata_controls_frame = None
        host._splittree_metadata_control_labels = []
        host._splittree_rt_columns_detected = []
        host._splittree_viz_isoform = None
        host._pending_splittree_isoform = None
        host._splittree_rt_assignment_status_label = None
        host._splittree_isoform_menu = None
        host._splittree_tree_host = None
        host._splittree_tree_placeholder = None
        host._splittree_tree_plot_host = None
        host._splittree_figure_host = None
        host._splittree_export_png_btn = None
        host._splittree_export_branches_btn = None
        host._pedigree_tree_viz_mode_var = tk.StringVar(value=SPLITTREE_VIEW_FULL)
        host._pedigree_del_branch_var = tk.StringVar(value="")
        host._pedigree_del_color_rt_var = tk.BooleanVar(value=False)
        host._pedigree_del_color_pedigree_var = tk.BooleanVar(value=False)
        host._pedigree_del_branch_menu = None
        host._del_branch_label_to_name = {}

    def close(self) -> None:
        """Cancel metadata validation and release the hosted figure."""
        self._metadata_tasks.cancel_active()
        self._clear_splittree_tree_plot()

    def _build_splittree_viz_sidebar_content(
        self,
        panel: ctk.CTkScrollableFrame,
    ) -> None:
        """Build clearly separated plot-data and active-display controls."""
        host = self._context
        ctk.CTkLabel(
            panel,
            text="Plot data",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=_SECTION_HEADER_COLOR,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        host._splittree_generate_btn = ctk.CTkButton(
            panel,
            text="Generate plot",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36,
            fg_color="#1F6FEB",
            command=self._on_generate_splittree_plot,
        )
        host._splittree_generate_btn.grid(
            row=1, column=0, sticky="ew", padx=8, pady=(0, 12)
        )
        host._busy_sensitive_widgets.append(host._splittree_generate_btn)

        row = 2
        row = self._add_sidebar_label(panel, row, "RT source for plot", top=True)
        source_menu = ctk.CTkOptionMenu(
            panel,
            variable=host._splittree_rt_source_var,
            values=[SPLITTREE_RT_SESSION, SPLITTREE_RT_METADATA],
            command=lambda _value: self._on_splittree_rt_source_changed(),
        )
        source_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        host._busy_sensitive_widgets.append(source_menu)
        metadata_group = ctk.CTkFrame(panel, corner_radius=8)
        metadata_group.grid(
            row=row + 1,
            column=0,
            sticky="ew",
            padx=8,
            pady=(4, 10),
        )
        metadata_group.grid_columnconfigure(0, weight=1)
        host._splittree_metadata_controls_frame = metadata_group

        group_header = ctk.CTkLabel(
            metadata_group,
            text="Spreadsheet metadata",
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        group_header.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 6))
        rt_label = ctk.CTkLabel(metadata_group, text="Spreadsheet RT column")
        rt_label.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 4))
        host._splittree_rt_column_menu = ctk.CTkOptionMenu(
            metadata_group,
            variable=host._splittree_metadata_rt_column_var,
            values=[_SELECT_COLUMN],
            state="disabled",
            command=lambda _value: self._on_splittree_rt_column_selected(),
        )
        host._splittree_rt_column_menu.grid(
            row=2, column=0, sticky="ew", padx=8, pady=(0, 4)
        )
        host._busy_sensitive_widgets.append(host._splittree_rt_column_menu)
        host._splittree_rt_column_status_label = self._add_status_label(
            metadata_group,
            3,
            "Select the registered column containing numeric retention times.",
        )
        host._splittree_rt_detect_btn = ctk.CTkButton(
            metadata_group,
            text="Validate RT column",
            fg_color="gray40",
            state="disabled",
            command=self._on_validate_splittree_rt_column,
        )
        host._splittree_rt_detect_btn.grid(
            row=4, column=0, sticky="ew", padx=8, pady=(6, 4)
        )
        host._busy_sensitive_widgets.append(host._splittree_rt_detect_btn)
        host._splittree_metadata_validation_status_label = self._add_status_label(
            metadata_group,
            5,
            "",
        )
        host._splittree_metadata_control_labels = [
            group_header,
            rt_label,
            host._splittree_rt_column_status_label,
            host._splittree_metadata_validation_status_label,
        ]
        row += 2
        if host._config is not None and host._config.compound_variant_column:
            row = self._add_sidebar_label(panel, row, "Isoform")
            host._splittree_isoform_menu = ctk.CTkOptionMenu(
                panel,
                variable=host._splittree_isoform_var,
                values=host._pedigree_variant_choices,
                command=lambda _value: self._on_splittree_isoform_changed(),
            )
            host._splittree_isoform_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
            host._busy_sensitive_widgets.append(host._splittree_isoform_menu)
            row += 1
        ctk.CTkFrame(
            panel,
            height=1,
            fg_color=("gray75", "gray35"),
        ).grid(row=row, column=0, sticky="ew", padx=8, pady=(8, 12))
        row += 1
        ctk.CTkLabel(
            panel,
            text="Active plot parameters",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=_SECTION_HEADER_COLOR,
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 2))
        display_controls = ctk.CTkFrame(panel, corner_radius=8)
        display_controls.grid(
            row=row + 1,
            column=0,
            sticky="ew",
            padx=8,
            pady=(0, 12),
        )
        display_controls.grid_columnconfigure(0, weight=1)
        self._build_display_controls(display_controls)
        self._sync_metadata_control_states()

    @staticmethod
    def _add_sidebar_label(
        panel: ctk.CTkScrollableFrame,
        row: int,
        text: str,
        *,
        top: bool = False,
    ) -> int:
        """Add one sidebar section label and return the following row."""
        ctk.CTkLabel(
            panel,
            text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=((8 if top else 0), 4))
        return row + 1

    @staticmethod
    def _add_status_label(
        panel: ctk.CTkScrollableFrame,
        row: int,
        text: str,
    ) -> ctk.CTkLabel:
        """Add a wrapped sidebar status label."""
        label = ctk.CTkLabel(
            panel,
            text=text,
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        label.grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8))
        return label

    def _build_splittree_tab(self, tabview: ctk.CTkTabview, tk_bg: str) -> None:
        """Build the split-tree tab with an RT-style export toolbar and figure host."""
        host = self._context
        tab = tabview.add("Split-tree visualization")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.pack(anchor="w")

        host._splittree_export_png_btn = ctk.CTkButton(
            actions,
            text="Export tree PNG…",
            width=150,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_splittree_png,
        )
        host._splittree_export_png_btn.pack(side="left", padx=(0, 6))
        host._busy_sensitive_widgets.append(host._splittree_export_png_btn)

        host._splittree_export_branches_btn = ctk.CTkButton(
            actions,
            text="Export BB1 branches PNGs…",
            width=200,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_splittree_branches,
        )
        host._splittree_export_branches_btn.pack(side="left", padx=(0, 6))
        host._busy_sensitive_widgets.append(host._splittree_export_branches_btn)

        host._splittree_export_bundle_btn = ctk.CTkButton(
            actions,
            text="Export analysis bundle…",
            width=170,
            fg_color="#0969da",
            hover_color="#1f6feb",
            state="disabled",
            command=self._on_export_del_cycle_csv,
        )
        host._splittree_export_bundle_btn.pack(side="left", padx=(0, 6))
        host._busy_sensitive_widgets.append(host._splittree_export_bundle_btn)

        body = ctk.CTkFrame(tab, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        (
            host._splittree_tree_host,
            host._splittree_tree_placeholder,
            host._splittree_tree_plot_host,
            host._splittree_header_label,
        ) = build_tree_figure_host(
            body,
            tk_bg=tk_bg,
            title="Split-tree",
            placeholder="Run RT assignment or choose metadata source, then refresh.",
            show_toolbar_hint=False,
        )
        host._splittree_figure_host = FigureHost(
            host._splittree_tree_plot_host,
            host._splittree_tree_placeholder,
        )
        self._on_splittree_view_changed()

    def _build_display_controls(self, inner: ctk.CTkFrame) -> None:
        """Build active view, branch, coloring, cutoff, and status controls."""
        host = self._context
        ctk.CTkLabel(
            inner,
            text="RT assignment session",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        host._splittree_rt_assignment_status_label = ctk.CTkLabel(
            inner,
            text="No RT assignment run in this session.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="nw",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        host._splittree_rt_assignment_status_label.grid(
            row=1, column=0, sticky="ew", padx=8, pady=(0, 8)
        )
        ctk.CTkLabel(
            inner,
            text="View",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))
        host._splittree_view_mode_menu = ctk.CTkOptionMenu(
            inner,
            variable=host._splittree_view_mode_var,
            values=list(SPLITTREE_VIEW_MODES),
            command=lambda _value: self._on_splittree_view_changed(),
        )
        host._splittree_view_mode_menu.grid(
            row=3, column=0, sticky="ew", padx=8, pady=(0, 4)
        )
        host._pedigree_del_controls_frame = ctk.CTkFrame(inner, fg_color="transparent")
        host._pedigree_del_controls_frame.grid(row=4, column=0, sticky="ew")
        host._pedigree_del_controls_frame.grid_columnconfigure(0, weight=1)
        branch = host._pedigree_del_controls_frame
        ctk.CTkLabel(
            branch,
            text="BB1 branch",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(4, 2))
        host._pedigree_del_branch_menu = ctk.CTkOptionMenu(
            branch,
            variable=host._pedigree_del_branch_var,
            values=["—"],
            command=lambda _value: self._on_del_branch_changed(),
        )
        host._pedigree_del_branch_menu.grid(
            row=1, column=0, sticky="ew", padx=8, pady=(0, 4)
        )
        ctk.CTkCheckBox(
            branch,
            text="Color product leaves by RT",
            variable=host._pedigree_del_color_rt_var,
            command=self._on_del_tree_option_changed,
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 4))
        ctk.CTkCheckBox(
            branch,
            text="Color by pedigree pass/fail",
            variable=host._pedigree_del_color_pedigree_var,
            command=self._on_del_tree_option_changed,
        ).grid(row=3, column=0, sticky="w", padx=8, pady=(0, 4))
        ctk.CTkLabel(
            branch,
            text="Pass % cutoff (hub coloring)",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=4, column=0, sticky="w", padx=8, pady=(4, 2))
        cutoff = ctk.CTkEntry(branch, textvariable=host._pedigree_del_pass_pct_var)
        cutoff.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 2))
        cutoff.bind("<FocusOut>", lambda _event: self._on_del_pass_pct_changed())
        cutoff.bind("<Return>", lambda _event: self._on_del_pass_pct_changed())
        host._busy_sensitive_widgets.append(cutoff)
        ctk.CTkLabel(
            branch,
            text="Hub turns blue when ≥ this % of descendant full products pass "
            "(RT verify or pedigree mode). Use 0 for “any pass” (legacy).",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=6, column=0, sticky="w", padx=8, pady=(0, 4))
        host._splittree_status_label = ctk.CTkLabel(
            inner,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        host._splittree_status_label.grid(
            row=5, column=0, sticky="ew", padx=8, pady=(2, 8)
        )

    def _splittree_isoform_label(self) -> str:
        return self._context._splittree_isoform_var.get().strip() or "All"

    def _session_del_cycle_isoform_matches(self) -> bool:
        """Return whether cached RT assignment can serve the current filter."""
        return self._can_reuse_session_del_cycle_tree(self._splittree_isoform_label())

    def _can_reuse_session_del_cycle_tree(self, isoform: str = "All") -> bool:
        """Return whether session RT data can render without peak re-analysis."""
        del isoform
        return self._callbacks.session_rt_ready()

    def _resolve_splittree_figure(
        self,
        data: DelCycleTreeData,
        *,
        view_mode: str,
        branch_selection: str,
        color_by_rt: bool,
        color_mode: str,
        pass_pct_cutoff: float,
        progress_callback=None,
    ) -> Tuple[object, str]:
        """Render the selected view and return its resolved branch."""
        view = (
            DelCycleTreeView.BRANCH if view_mode == SPLITTREE_VIEW_BRANCH else DelCycleTreeView.FULL
        )
        selected = branch_selection
        if view == DelCycleTreeView.BRANCH:
            branches = self._sorted_bb1_branch_names(data)
            resolved = self._resolve_del_branch_bb1(data, branch_selection)
            selected = resolved if resolved in branches else (branches[0] if branches else "")
        figure = render_del_cycle_tree_figure(
            data,
            view=view,
            branch_bb1=selected if view == DelCycleTreeView.BRANCH else None,
            color_by_rt=color_by_rt,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
            progress_callback=progress_callback,
        )
        return figure, selected

    def _render_splittree_from_cached_session(
        self,
        isoform: str,
        *,
        show_loading: bool = True,
    ) -> None:
        """Render from cached session RT data without repeating peak analysis."""
        host = self._context
        session_data = host._del_cycle_tree_data
        if session_data is None or host._config is None or host._db_path is None:
            return
        isoform = (isoform or "All").strip() or "All"
        filtered = isoform.lower() != "all"
        if show_loading:
            detail = (
                f"Filtering session RT assignment for isoform “{isoform}”…"
                if filtered
                else "Rendering split-tree from session RT assignment…"
            )
            host._show_loading_page("Generating split-tree", detail)
            self._show_splittree_placeholder("Generating split-tree plot…")
        view_mode = host._splittree_view_mode_var.get()
        branch = host._pedigree_del_branch_var.get().strip()
        color_by_rt = bool(host._pedigree_del_color_rt_var.get())
        color_mode = self._del_tree_color_mode()
        cutoff = self._read_del_tree_pass_pct_cutoff()
        settings = self._callbacks.parse_settings()
        threshold = float(settings.tolerance) if settings is not None else session_data.rt_threshold
        db_path, config = host._db_path, host._config

        def worker() -> None:
            try:

                def build_progress(step: int, total: int, status: str) -> None:
                    if not show_loading:
                        return
                    fraction = step / total if total > 0 else 0.0
                    host._thread_loading_progress(
                        min(0.45, 0.02 + 0.43 * fraction),
                        status or "Preparing split-tree data…",
                    )

                def render_progress(fraction: float, status: str) -> None:
                    if not show_loading:
                        return
                    host._thread_loading_progress(
                        min(0.98, 0.50 + 0.48 * fraction),
                        status or "Rendering split-tree figure…",
                    )

                if show_loading:
                    host._thread_loading_progress(
                        0.02,
                        (
                            f"Filtering session RT assignment for isoform “{isoform}”…"
                            if filtered
                            else "Using session RT assignment…"
                        ),
                    )
                data = (
                    build_del_cycle_tree_from_session_cache_for_path(
                        db_path,
                        config,
                        session_data,
                        isoform_label=isoform,
                        rt_threshold=threshold,
                        progress_callback=build_progress if show_loading else None,
                    )
                    if filtered
                    else session_data
                )
                if show_loading:
                    host._thread_loading_progress(0.48, "Rendering split-tree figure…")
                figure, selected = self._resolve_splittree_figure(
                    data,
                    view_mode=view_mode,
                    branch_selection=branch,
                    color_by_rt=color_by_rt,
                    color_mode=color_mode,
                    pass_pct_cutoff=cutoff,
                    progress_callback=render_progress if show_loading else None,
                )
                if show_loading:
                    host._thread_loading_progress(0.99, "Mounting split-tree plot…")
                host._bind_worker_callback(
                    self._on_splittree_session_ready,
                    data,
                    figure,
                    selected,
                    isoform,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Cached split-tree render failed: %s", exc, exc_info=True)
                host._bind_worker_callback(self._on_splittree_metadata_failed, str(exc))

        host._start_worker(worker)
        host._update_action_states()

    def _reuse_session_del_cycle_for_splittree(self) -> bool:
        isoform = self._splittree_isoform_label()
        if not self._can_reuse_session_del_cycle_tree(isoform):
            return False
        self._render_splittree_from_cached_session(isoform, show_loading=True)
        return True

    @staticmethod
    def _format_splittree_rt_column_status(
        discovered: List[MetadataRtColumnInfo],
        *,
        selected: str = "",
    ) -> str:
        """Format numeric RT metadata validation status."""
        if not discovered:
            return (
                "No metadata columns are registered. "
                "Select columns in Configure Spreadsheet and re-process the library."
            )
        match = next(
            (info for info in discovered if info.column_name == selected.strip()),
            None,
        )
        if match is not None:
            if match.n_compounds_scanned == 0:
                return f"“{match.column_name}”: not validated yet."
            pct = 100.0 * match.n_numeric_values / match.n_compounds_scanned
            return (
                f"“{match.column_name}”: {match.n_numeric_values:,} numeric values "
                f"({pct:.1f}% of library), "
                f"{match.n_with_bb_positions:,} with BB positions."
            )
        count = sum(info.n_numeric_values > 0 for info in discovered)
        if count == 0:
            return (
                f"{len(discovered)} registered column(s); none have numeric values yet. "
                "Click Validate column to scan the library."
            )
        return (
            f"{len(discovered)} registered metadata column(s). "
            f"{count} contain numeric values after validation."
        )

    def _load_registered_metadata_columns(self) -> None:
        """Populate the metadata RT dropdown from spreadsheet configuration."""
        host = self._context
        if host._config is None:
            return
        names = registered_metadata_column_names(host._config)
        columns = [
            MetadataRtColumnInfo(
                column_name=name,
                n_numeric_values=0,
                n_compounds_scanned=0,
            )
            for name in names
        ]
        host._splittree_rt_columns_detected = columns
        self._apply_splittree_rt_column_choices(columns)
        if host._splittree_rt_column_status_label is not None:
            host._splittree_rt_column_status_label.configure(
                text=(
                    f"{len(names)} registered metadata column(s). "
                    "Select an RT column, then click Validate RT column."
                    if names
                    else "No metadata columns registered in Configure Spreadsheet."
                ),
                text_color="gray" if names else "#D29922",
            )

    def _apply_splittree_rt_column_choices(
        self,
        discovered: List[MetadataRtColumnInfo],
    ) -> None:
        """Update the metadata RT dropdown."""
        host = self._context
        if host._splittree_rt_column_menu is None:
            return
        choices = [_SELECT_COLUMN, *(info.column_name for info in discovered)]
        host._splittree_rt_column_menu.configure(values=choices)
        variable = host._splittree_metadata_rt_column_var
        if variable.get().strip() not in choices:
            variable.set(choices[1] if len(choices) > 1 else choices[0])
        self._on_splittree_rt_column_selected()

    def _current_metadata_selection(self) -> _MetadataValidationSelection:
        """Return the metadata inputs whose validation gates plot generation."""
        host = self._context
        return _MetadataValidationSelection(
            rt_column=host._splittree_metadata_rt_column_var.get().strip(),
            isoform=self._splittree_isoform_label(),
        )

    @staticmethod
    def _metadata_validation_error(
        selection: _MetadataValidationSelection,
        validated: List[MetadataRtColumnInfo],
    ) -> Optional[str]:
        """Return why selected metadata inputs are unusable, or ``None``."""
        if not selection.rt_column or selection.rt_column == _SELECT_COLUMN:
            return "Select a spreadsheet RT column."

        by_name = {info.column_name: info for info in validated}
        rt_info = by_name.get(selection.rt_column)
        if rt_info is None:
            return f"RT column “{selection.rt_column}” is not registered."
        if rt_info.n_compounds_scanned == 0:
            return "No compounds were available for the selected isoform."
        if rt_info.n_with_bb_positions == 0:
            return (
                f"RT column “{selection.rt_column}” has no numeric RT values on rows "
                "with configured BB positions."
            )
        return None

    def _metadata_selection_is_validated(self) -> bool:
        """Return whether current metadata inputs match a successful scan."""
        selection = self._current_metadata_selection()
        return (
            self._validated_metadata_selection == selection
            and self._metadata_validation_error(
                selection,
                self._context._splittree_rt_columns_detected,
            )
            is None
        )

    def _can_generate_splittree(self) -> bool:
        """Return whether the selected RT source is ready to generate a plot."""
        if self._context._splittree_rt_source_var.get() == SPLITTREE_RT_METADATA:
            return self._metadata_selection_is_validated()
        return self._callbacks.session_rt_ready()

    def _invalidate_metadata_validation(self, reason: str) -> None:
        """Invalidate the validation gate after a metadata input changes."""
        self._validated_metadata_selection = None
        label = self._context._splittree_metadata_validation_status_label
        if label is not None:
            label.configure(text=reason, text_color="#D29922")
        self._sync_metadata_control_states()

    def _sync_metadata_control_states(self) -> None:
        """Apply source, busy, selection, and validation state to metadata widgets."""
        host = self._context
        metadata = host._splittree_rt_source_var.get() == SPLITTREE_RT_METADATA
        busy = (
            host._busy_operation is not None
            or host._is_busy()
            or self._metadata_tasks.is_busy
        )
        metadata_enabled = metadata and not busy
        if host._splittree_rt_column_menu is not None:
            host._splittree_rt_column_menu.configure(
                state="normal" if metadata_enabled else "disabled"
            )

        selection = self._current_metadata_selection()
        selections_ready = (
            bool(selection.rt_column)
            and selection.rt_column != _SELECT_COLUMN
        )
        if host._splittree_rt_detect_btn is not None:
            host._splittree_rt_detect_btn.configure(
                state="normal" if metadata_enabled and selections_ready else "disabled"
            )
        if host._splittree_generate_btn is not None:
            can_generate = not busy and self._can_generate_splittree()
            host._splittree_generate_btn.configure(
                state="normal" if can_generate else "disabled"
            )

        frame = host._splittree_metadata_controls_frame
        if frame is not None:
            frame.configure(
                fg_color=("gray94", "gray14") if metadata else ("gray86", "gray22")
            )
        label_color = ("gray10", "gray90") if metadata else ("gray55", "gray50")
        for label in host._splittree_metadata_control_labels:
            if label is not None:
                label.configure(text_color=label_color)

    def _on_validate_splittree_rt_column(self) -> None:
        """Validate the selected metadata RT column under an immutable task token."""
        host = self._context
        if self._metadata_tasks.is_busy or host._is_busy():
            return
        if host._config is None or host._db_path is None:
            return
        if host._splittree_rt_source_var.get() != SPLITTREE_RT_METADATA:
            messagebox.showinfo(
                "Split-tree visualization",
                "Set RT source to Spreadsheet metadata before validating.",
                parent=host,
            )
            return
        selection = self._current_metadata_selection()
        selection_error = self._metadata_validation_error(
            selection,
            host._splittree_rt_columns_detected,
        )
        if selection_error is not None and (
            not selection.rt_column
            or selection.rt_column == _SELECT_COLUMN
        ):
            messagebox.showinfo(
                "Validate RT column",
                selection_error,
                parent=host,
            )
            return
        if not registered_metadata_column_names(host._config):
            messagebox.showinfo(
                "Validate RT column",
                "No metadata columns are registered in Configure Spreadsheet.",
                parent=host,
            )
            return
        self._validated_metadata_selection = None
        self._set_validation_status("Scanning library metadata…")
        if host._splittree_metadata_validation_status_label is not None:
            host._splittree_metadata_validation_status_label.configure(
                text="Validating the selected RT column…",
                text_color="gray",
            )
        config, db_path = host._config, host._db_path
        isoform = self._splittree_isoform_label()

        def worker() -> None:
            store = DataStore(db_path=db_path, use_memory=False)
            try:
                from src.core.lineage_service import load_all_compound_metadata

                def progress(processed: int, total: int, status: str) -> None:
                    self._metadata_tasks.dispatch_current(
                        self._update_splittree_rt_detect_progress,
                        processed,
                        total,
                        status,
                    )

                compounds = load_all_compound_metadata(
                    store,
                    metadata_columns=metadata_columns_for_split_tree(config),
                    progress_callback=progress,
                )
                if isoform.lower() != "all":
                    from src.core.pedigree_adapter import filter_compounds_by_variant

                    compounds = filter_compounds_by_variant(compounds, [isoform])
                validated = validate_registered_metadata_columns(compounds, config)
                self._metadata_tasks.dispatch_current(
                    self._on_splittree_rt_columns_validated,
                    validated,
                    selection,
                    complete=True,
                )
            except Exception as exc:
                logger.error("Metadata column validation failed: %s", exc, exc_info=True)
                self._metadata_tasks.dispatch_current(
                    self._on_splittree_rt_columns_detect_failed,
                    str(exc),
                    complete=True,
                )
            finally:
                store.close()

        self._metadata_tasks.start(worker)
        self._sync_metadata_control_states()

    def _set_validation_status(self, text: str) -> None:
        host = self._context
        if host._splittree_rt_column_status_label is not None:
            host._splittree_rt_column_status_label.configure(
                text=text,
                text_color="gray",
            )

    def _update_splittree_rt_detect_progress(
        self,
        processed: int,
        total: int,
        status: str,
    ) -> None:
        text = f"{status} ({100.0 * processed / total:.0f}%)" if total > 0 else status
        self._set_validation_status(text)

    def _on_splittree_rt_columns_validated(
        self,
        validated: List[MetadataRtColumnInfo],
        selection: _MetadataValidationSelection,
    ) -> None:
        host = self._context
        host._splittree_rt_columns_detected = list(validated)
        self._apply_splittree_rt_column_choices(validated)
        error = self._metadata_validation_error(selection, validated)
        status_label = host._splittree_metadata_validation_status_label
        if error is None and selection == self._current_metadata_selection():
            self._validated_metadata_selection = selection
            if status_label is not None:
                status_label.configure(
                    text=(
                        "RT column validated for "
                        f"{selection.isoform} data. Plot generation is enabled."
                    ),
                    text_color="#238636",
                )
        else:
            self._validated_metadata_selection = None
            message = error or "The metadata selection changed during validation."
            if status_label is not None:
                status_label.configure(text=message, text_color="#D29922")
            messagebox.showinfo(
                "Validate RT column",
                f"{message}\n\nPlot generation remains disabled.",
                parent=host,
            )
        self._sync_metadata_control_states()

    def _on_splittree_rt_columns_detect_failed(self, message: str) -> None:
        host = self._context
        self._validated_metadata_selection = None
        if host._splittree_metadata_validation_status_label is not None:
            host._splittree_metadata_validation_status_label.configure(
                text=f"Detection failed: {message}",
                text_color="#D29922",
            )
        self._sync_metadata_control_states()
        messagebox.showerror("Validate RT column", message, parent=host)

    def _on_splittree_rt_column_selected(self) -> None:
        host = self._context
        if host._splittree_rt_column_status_label is not None:
            host._splittree_rt_column_status_label.configure(
                text=self._format_splittree_rt_column_status(
                    host._splittree_rt_columns_detected,
                    selected=host._splittree_metadata_rt_column_var.get(),
                ),
                text_color=("gray10", "gray90"),
            )
        self._invalidate_metadata_validation(
            "RT column selection changed. Validate the RT column again."
        )

    def _on_splittree_rt_source_changed(self) -> None:
        host = self._context
        metadata = host._splittree_rt_source_var.get() == SPLITTREE_RT_METADATA
        self._validated_metadata_selection = None
        if metadata:
            self._load_registered_metadata_columns()
            if host._splittree_metadata_validation_status_label is not None:
                host._splittree_metadata_validation_status_label.configure(
                    text="",
                    text_color="gray",
                )
        host._session_state.invalidate_splittree()
        self._show_splittree_placeholder(
            "Select and validate an RT column, then click Generate plot."
            if metadata
            else "Choose RT source and click Generate plot in the sidebar."
        )
        self._sync_metadata_control_states()

    def _on_splittree_isoform_changed(self) -> None:
        host = self._context
        host._session_state.invalidate_splittree()
        host._splittree_viz_isoform = None
        if host._splittree_rt_source_var.get() == SPLITTREE_RT_METADATA:
            self._set_validation_status(
                "Isoform filter changed — click Validate RT column to refresh counts."
            )
            self._invalidate_metadata_validation(
                "Isoform filter changed. Validate the RT column again."
            )
        self._show_splittree_placeholder("Isoform filter changed. Click Generate plot to rebuild.")

    def _on_generate_splittree_plot(self) -> None:
        host = self._context
        if host._is_busy() or self._metadata_tasks.is_busy:
            return
        if host._splittree_rt_source_var.get() == SPLITTREE_RT_METADATA:
            if not self._metadata_selection_is_validated():
                messagebox.showinfo(
                    "Split-tree visualization",
                    "Validate the selected spreadsheet RT column before generating "
                    "the plot.",
                    parent=host,
                )
                return
            self._generate_splittree_from_metadata()
        elif not self._reuse_session_del_cycle_for_splittree():
            self._generate_splittree_from_session()

    def _generate_splittree_from_session(self) -> None:
        host = self._context
        isoform = self._splittree_isoform_label()
        if not self._callbacks.session_rt_ready():
            if host._pedigree_result is not None:
                host._pending_splittree_isoform = isoform
                self._callbacks.ensure_session_tree()
                self._callbacks.update_rt_status()
                return
            messagebox.showinfo(
                "Split-tree visualization",
                "Run RT assignment on the RT assignment tab first, then generate the plot.",
                parent=host,
            )
            return
        self._render_splittree_from_cached_session(isoform, show_loading=True)

    def _generate_splittree_from_metadata(self) -> None:
        host = self._context
        if not self._metadata_selection_is_validated():
            messagebox.showinfo(
                "Split-tree visualization",
                "The selected RT column has not been successfully validated for "
                "the current isoform.",
                parent=host,
            )
            self._sync_metadata_control_states()
            return
        column = host._splittree_metadata_rt_column_var.get().strip()
        if not column or column == _SELECT_COLUMN:
            messagebox.showinfo(
                "Split-tree visualization",
                "Select a registered metadata RT column before generating the plot.",
                parent=host,
            )
            return
        if host._config is None or host._db_path is None:
            return
        settings = self._callbacks.parse_settings()
        if settings is None:
            return
        isoform = self._splittree_isoform_label()
        options = (
            host._splittree_view_mode_var.get(),
            host._pedigree_del_branch_var.get().strip(),
            bool(host._pedigree_del_color_rt_var.get()),
            self._del_tree_color_mode(),
            self._read_del_tree_pass_pct_cutoff(),
        )
        host._show_loading_page(
            "Generating split-tree",
            (
                f"Reading RT values from “{column}” and calculating null verification "
                f"(threshold {settings.tolerance:g} {settings.time_unit})"
                f"{f' · isoform: {isoform}' if isoform != 'All' else ''}…"
            ),
        )
        db_path, config = host._db_path, host._config

        def worker() -> None:
            try:

                def build_progress(step: int, total: int, status: str) -> None:
                    fraction = step / total if total > 0 else 0.0
                    host._thread_loading_progress(
                        min(0.55, 0.02 + 0.53 * fraction),
                        status or "Building split-tree…",
                    )

                def render_progress(fraction: float, status: str) -> None:
                    host._thread_loading_progress(
                        min(0.98, 0.58 + 0.40 * fraction),
                        status or "Rendering split-tree figure…",
                    )

                data = build_del_cycle_tree_from_metadata_for_path(
                    db_path,
                    config,
                    column,
                    rt_threshold=float(settings.tolerance),
                    time_unit=settings.time_unit,
                    isoform_label=isoform,
                    progress_callback=build_progress,
                )
                host._thread_loading_progress(0.58, "Rendering split-tree figure…")
                figure, selected = self._resolve_splittree_figure(
                    data,
                    view_mode=options[0],
                    branch_selection=options[1],
                    color_by_rt=options[2],
                    color_mode=options[3],
                    pass_pct_cutoff=options[4],
                    progress_callback=render_progress,
                )
                host._thread_loading_progress(0.99, "Mounting split-tree plot…")
                host._bind_worker_callback(
                    self._on_splittree_metadata_ready,
                    data,
                    figure,
                    selected,
                    isoform,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Metadata split-tree build failed: %s", exc, exc_info=True)
                host._bind_worker_callback(self._on_splittree_metadata_failed, str(exc))

        host._start_worker(worker)
        host._update_action_states()

    def _on_splittree_session_ready(
        self,
        data: DelCycleTreeData,
        figure: object,
        selected_branch: str,
        isoform: str,
    ) -> None:
        self._accept_splittree_result(data, figure, selected_branch, isoform)
        self._callbacks.update_rt_status()

    def _on_splittree_metadata_ready(
        self,
        data: DelCycleTreeData,
        figure: object,
        selected_branch: str,
        isoform: str = "All",
    ) -> None:
        self._accept_splittree_result(data, figure, selected_branch, isoform)

    def _accept_splittree_result(
        self,
        data: DelCycleTreeData,
        figure: object,
        selected_branch: str,
        isoform: str,
    ) -> None:
        host = self._context
        host._worker_thread = None
        host._splittree_viz_data = data
        host._splittree_viz_isoform = isoform
        self._update_del_branch_choices(data)
        if selected_branch:
            host._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected_branch,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
            )
        self._update_del_tree_status_note(data)
        self._mount_splittree_figure(figure)
        self._callbacks.capture_visualization(
            data,
            figure,
            isoform,
            selected_branch,
        )
        host._hide_loading_page()
        host._update_action_states()

    def _on_splittree_metadata_failed(self, message: str) -> None:
        host = self._context
        host._worker_thread = None
        host._hide_loading_page()
        self._show_splittree_placeholder(message)
        messagebox.showerror("Split-tree visualization", message, parent=host)
        host._update_action_states()

    def _is_del_branch_viz_mode(self) -> bool:
        return self._context._splittree_view_mode_var.get() == SPLITTREE_VIEW_BRANCH

    def _on_splittree_view_changed(self) -> None:
        host = self._context
        if host._pedigree_del_branch_menu is not None:
            host._pedigree_del_branch_menu.configure(
                state="normal" if self._is_del_branch_viz_mode() else "disabled"
            )
        if host._splittree_viz_data is not None:
            self._show_del_cycle_tree_preview(host._splittree_viz_data)

    def _read_del_tree_pass_pct_cutoff(self) -> float:
        """Parse and clamp split-tree pass-rate cutoff."""
        try:
            value = float(self._context._pedigree_del_pass_pct_var.get().strip())
        except ValueError:
            return 0.0
        return min(100.0, max(0.0, value))

    def _del_tree_color_mode(self) -> str:
        return (
            COLOR_MODE_PEDIGREE
            if bool(self._context._pedigree_del_color_pedigree_var.get())
            else COLOR_MODE_NOTEBOOK
        )

    def _on_del_pass_pct_changed(self) -> None:
        self._refresh_current_tree()

    def _on_del_branch_changed(self) -> None:
        if self._is_del_branch_viz_mode():
            self._refresh_current_tree()

    def _on_del_tree_option_changed(self) -> None:
        self._refresh_current_tree()

    def _refresh_current_tree(self) -> None:
        data = self._context._splittree_viz_data
        if data is not None:
            self._show_del_cycle_tree_preview(data)

    def _sorted_bb1_branch_names(self, data: DelCycleTreeData) -> List[str]:
        """Return BB1 names sorted by display index then name."""
        names = [name for name in data.bb1_names if name != data.null_token]
        return sorted(
            names,
            key=lambda name: (
                lookup_bb_display_index(
                    name,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
                or 10**9,
                name.lower(),
            ),
        )

    def _resolve_del_branch_bb1(
        self,
        data: DelCycleTreeData,
        selection: str = "",
    ) -> str:
        """Map branch display text to a BB1 tree key."""
        host = self._context
        selection = (selection or host._pedigree_del_branch_var.get()).strip()
        branches = self._sorted_bb1_branch_names(data)
        if not branches:
            return ""
        if selection in host._del_branch_label_to_name:
            return host._del_branch_label_to_name[selection]
        if selection in branches:
            return selection
        for name in branches:
            if selection == format_bb_branch_label(
                name,
                data.bb_index_global,
                null_token=data.null_token,
            ):
                return name
        return branches[0]

    def _update_del_branch_choices(self, data: DelCycleTreeData) -> None:
        host = self._context
        host._del_branch_label_to_name = {
            format_bb_branch_label(
                name,
                data.bb_index_global,
                null_token=data.null_token,
            ): name
            for name in self._sorted_bb1_branch_names(data)
        }
        choices = list(host._del_branch_label_to_name) or ["—"]
        if host._pedigree_del_branch_menu is not None:
            host._pedigree_del_branch_menu.configure(values=choices)
        branch = self._resolve_del_branch_bb1(data)
        host._pedigree_del_branch_var.set(
            format_bb_branch_label(
                branch,
                data.bb_index_global,
                null_token=data.null_token,
            )
            if branch
            else choices[0]
        )

    def _update_del_tree_status_note(self, data: DelCycleTreeData) -> None:
        host = self._context
        if host._splittree_status_label is None:
            return
        picker = {
            "old_school": "old-school Gaussian",
            "modern": "modern NB",
        }.get(data.peak_picking_algorithm, data.peak_picking_algorithm or "—")
        isoform = host._splittree_viz_isoform or self._splittree_isoform_label()
        host._splittree_status_label.configure(
            text=(
                f"DEL rows: {data.n_rows:,} · RT verified: {data.n_verified:,} · "
                f"pedigree passed: {data.n_pedigree_passed:,} · "
                f"RT: {data.rt_source} (pedigree={data.n_rt_from_pedigree:,}, "
                f"direct-pick={data.n_rt_from_peak_pick:,}, "
                f"metadata={data.n_rt_from_metadata:,}) · picker: {picker} · "
                f"null RT threshold: {data.rt_threshold:g}"
                f"{f' · isoform: {isoform}' if isoform != 'All' else ''}"
            ),
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )

    def _show_del_cycle_tree_preview(self, data: DelCycleTreeData) -> None:
        """Render current controls into the composed FigureHost."""
        figure, selected = self._resolve_splittree_figure(
            data,
            view_mode=self._context._splittree_view_mode_var.get(),
            branch_selection=self._context._pedigree_del_branch_var.get().strip(),
            color_by_rt=bool(self._context._pedigree_del_color_rt_var.get()),
            color_mode=self._del_tree_color_mode(),
            pass_pct_cutoff=self._read_del_tree_pass_pct_cutoff(),
        )
        if selected:
            self._context._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
            )
        self._update_del_tree_status_note(data)
        self._mount_splittree_figure(figure)

    def _clear_splittree_tree_plot(self) -> None:
        host = self._context._splittree_figure_host
        if host is not None:
            host.clear()

    def _show_splittree_placeholder(self, message: str) -> None:
        host = self._context._splittree_figure_host
        if host is not None:
            host.show_placeholder(message)

    def _mount_splittree_figure(self, figure: object) -> None:
        host = self._context._splittree_figure_host
        if host is not None:
            host.mount(figure)

    def _on_detect_splittree_rt_columns(self) -> None:
        """Retain the legacy metadata-detection API alias."""
        self._on_validate_splittree_rt_column()

    def _on_splittree_rt_columns_detected(
        self,
        discovered: List[MetadataRtColumnInfo],
    ) -> None:
        """Retain the legacy metadata-detection callback alias."""
        self._on_splittree_rt_columns_validated(discovered)

    def _active_splittree_data(self) -> Optional[DelCycleTreeData]:
        """Return the split-tree data currently available for export or display."""
        host = self._context
        return host._splittree_viz_data or host._del_cycle_tree_data

    @staticmethod
    def _safe_export_token(value: str) -> str:
        """Sanitize a BB name for use in exported PNG filenames."""
        import re

        token = re.sub(r"[^\w\-]+", "_", str(value).strip())
        token = token.strip("_")
        return token[:48] if token else "branch"

    def _on_export_splittree_png(self) -> None:
        """Export the currently selected split-tree view as a PNG."""
        host = self._context
        if host._is_busy():
            return
        data = self._active_splittree_data()
        if data is None:
            messagebox.showinfo(
                "Export tree PNG",
                "Generate a split-tree plot first.",
                parent=host,
            )
            return
        dest = filedialog.asksaveasfilename(
            parent=host,
            title="Export split-tree PNG",
            initialfile="split_tree.png",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not dest:
            return
        try:
            figure, _selected = self._resolve_splittree_figure(
                data,
                view_mode=host._splittree_view_mode_var.get(),
                branch_selection=host._pedigree_del_branch_var.get().strip(),
                color_by_rt=bool(host._pedigree_del_color_rt_var.get()),
                color_mode=self._del_tree_color_mode(),
                pass_pct_cutoff=self._read_del_tree_pass_pct_cutoff(),
            )
            figure.savefig(dest, dpi=150, bbox_inches="tight", facecolor="white")
            import matplotlib.pyplot as plt

            plt.close(figure)
            messagebox.showinfo("Export tree PNG", f"Saved to:\n{dest}", parent=host)
        except Exception as exc:
            logger.error("Split-tree PNG export failed: %s", exc, exc_info=True)
            messagebox.showerror("Export tree PNG", str(exc), parent=host)

    def _on_export_splittree_branches(self) -> None:
        """Export one PNG per BB1 branch (and the full tree) into a folder."""
        host = self._context
        if host._is_busy():
            return
        data = self._active_splittree_data()
        if data is None:
            messagebox.showinfo(
                "Export BB1 branches PNGs",
                "Generate a split-tree plot first.",
                parent=host,
            )
            return
        branches = self._sorted_bb1_branch_names(data)
        if not branches:
            messagebox.showinfo(
                "Export BB1 branches PNGs",
                "No BB1 branches are available to export.",
                parent=host,
            )
            return
        destination = filedialog.askdirectory(
            parent=host,
            title="Select folder for split-tree branch PNGs",
        )
        if not destination:
            return
        out_dir = Path(destination)
        color_by_rt = bool(host._pedigree_del_color_rt_var.get())
        color_mode = self._del_tree_color_mode()
        pass_pct_cutoff = self._read_del_tree_pass_pct_cutoff()
        host._show_loading_page(
            "Exporting branch PNGs",
            f"Preparing {len(branches):,} BB1 branch figure(s)…",
        )

        def worker() -> None:
            try:
                import matplotlib.pyplot as plt

                written = 0
                total = len(branches) + 1

                def progress(done: int, status: str) -> None:
                    host._raise_if_cancelled()
                    host._thread_loading_progress(
                        min(0.95, done / total if total else 1.0),
                        status,
                    )

                progress(0, "Rendering full split-tree…")
                full_fig = render_del_cycle_tree_figure(
                    data,
                    view=DelCycleTreeView.FULL,
                    color_by_rt=color_by_rt,
                    color_mode=color_mode,
                    pass_pct_cutoff=pass_pct_cutoff,
                )
                full_path = out_dir / "split_tree_full.png"
                full_fig.savefig(full_path, dpi=150, bbox_inches="tight", facecolor="white")
                plt.close(full_fig)
                written += 1

                for index, bb1 in enumerate(branches, start=1):
                    progress(
                        index,
                        f"Rendering branch {index:,} / {len(branches):,}: {bb1}…",
                    )
                    figure = render_del_cycle_tree_figure(
                        data,
                        view=DelCycleTreeView.BRANCH,
                        branch_bb1=bb1,
                        color_by_rt=color_by_rt,
                        color_mode=color_mode,
                        pass_pct_cutoff=pass_pct_cutoff,
                    )
                    bb_index = lookup_bb_display_index(
                        bb1,
                        data.bb_index_global,
                        null_token=data.null_token,
                    )
                    safe = self._safe_export_token(bb1)
                    prefix = (
                        f"split_tree_bb1_{bb_index}_{safe}"
                        if bb_index
                        else f"split_tree_bb1_{safe}"
                    )
                    path = out_dir / f"{prefix}.png"
                    figure.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
                    plt.close(figure)
                    written += 1

                host._bind_worker_callback(
                    self._on_splittree_branch_export_ready,
                    written,
                    str(out_dir),
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Split-tree branch PNG export failed: %s", exc, exc_info=True)
                host._bind_worker_callback(self._on_splittree_branch_export_failed, str(exc))

        host._start_worker(worker)
        host._update_action_states()

    def _on_splittree_branch_export_ready(self, written: int, out_dir: str) -> None:
        """Finish a successful multi-branch PNG export on Tk's thread."""
        host = self._context
        if not host._ui_is_active():
            return
        host._worker_thread = None

        def finish() -> None:
            if not host._ui_is_active():
                return
            host._hide_loading_page()
            host._update_action_states()
            messagebox.showinfo(
                "Export BB1 branches PNGs",
                f"Saved {written:,} PNG file(s) to:\n{out_dir}",
                parent=host,
            )

        host._schedule_on_main(finish)

    def _on_splittree_branch_export_failed(self, message: str) -> None:
        """Finish a failed multi-branch PNG export on Tk's thread."""
        host = self._context
        if not host._ui_is_active():
            return
        host._worker_thread = None
        host._hide_loading_page()
        host._update_action_states()
        messagebox.showerror("Export BB1 branches PNGs", message, parent=host)

    def _on_export_del_cycle_csv(self) -> None:
        """Export the current DEL analysis bundle in a background operation."""
        host = self._context
        if host._is_busy():
            return
        if host._del_cycle_tree_data is None:
            messagebox.showinfo(
                "Analysis bundle",
                "Run RT assignment first to build analysis data.",
                parent=host,
            )
            return
        destination = filedialog.askdirectory(
            parent=host,
            title="Select folder for analysis bundle export",
        )
        if not destination:
            return
        data = host._del_cycle_tree_data
        pedigree = host._pedigree_result
        settings = self._callbacks.peek_settings()
        analysis_mode = host._last_rt_analysis_mode or "direct_pick"
        host._show_loading_page("Exporting analysis bundle", "Starting export…")

        def worker() -> None:
            try:
                result = export_del_cycle_package(
                    data,
                    destination,
                    analysis_settings=settings,
                    rt_analysis_mode=analysis_mode,
                    pedigree_result=pedigree,
                    progress_callback=host._thread_loading_progress,
                )
                host._bind_worker_callback(self._on_del_cycle_export_ready, result)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Analysis bundle export failed: %s", exc, exc_info=True)
                host._bind_worker_callback(self._on_del_cycle_export_failed, str(exc))

        host._start_worker(worker)
        host._update_action_states()

    def _on_del_cycle_export_ready(self, result: DelCycleExportResult) -> None:
        """Finish a successful analysis bundle export on Tk's thread."""
        host = self._context
        if not host._ui_is_active():
            return
        host._worker_thread = None
        host._update_loading_progress(
            1.0,
            f"Exported {result.file_count} file(s) to {result.output_dir.name}",
        )

        def finish() -> None:
            if not host._ui_is_active():
                return
            host._hide_loading_page()
            host._update_action_states()
            if host._pedigree_status_label is not None:
                host._pedigree_status_label.configure(
                    text=(
                        f"Analysis bundle saved — {result.file_count} file(s) "
                        f"in {result.output_dir}"
                    ),
                    text_color="green",
                )
            prominence = (
                f"\n- {result.prominence_csv.name}" if result.prominence_csv is not None else ""
            )
            grids = (
                f"\n- {len(result.grid_files)} grid workbook(s) in grids/"
                if result.grid_files
                else "\n- (no BB1 grids — requires a 3-cycle library)"
            )
            messagebox.showinfo(
                "Analysis bundle",
                f"Exported {result.file_count} file(s) to:\n{result.output_dir}\n\n"
                f"- {result.products_csv.name}\n"
                f"- {result.audit_csv.name}\n"
                f"- {result.summary_csv.name}\n"
                f"- {result.flagged_csv.name}{prominence}{grids}",
                parent=host,
            )

        host.after(30, finish)

    def _on_del_cycle_export_failed(self, message: str) -> None:
        """Restore the UI after a failed analysis bundle export."""
        host = self._context
        if not host._ui_is_active():
            return
        host._worker_thread = None
        try:
            host._loading_detail.configure(
                text=f"Export failed: {message}",
                text_color="red",
            )
            host._loading_percent.configure(text="")
        except tk.TclError:
            pass
        host._hide_loading_page()
        host._update_action_states()
        messagebox.showerror("Split-tree", message, parent=host)
