# src/ui/library_data_window.py
"""
Library Analysis dashboard: scan parsed chromatograms, RT assignment, and QC plots.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.core.library_report import generate_library_report_pdf
from src.core.library_report_session import (
    LibraryQcMetricsArtifact,
    LibraryQcPlotsArtifact,
    LibraryReportSession,
    PedigreeVizReportArtifact,
    RtAssignmentReportArtifact,
    SplittreeVizReportArtifact,
    build_report_snapshot,
    missing_report_sections,
)
from src.core.library_report_assets import (
    build_del_cycle_report_figures,
    build_pedigree_tier_report_figure,
    session_report_assets_dir,
)
from src.core.library_report_models import (
    LibraryReportAuditTrail,
    LibraryReportOptions,
    LibraryReportPrerequisites,
    LibraryReportSectionStatus,
)
from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    LibraryScanData,
    PlotResult,
    build_snapshot_from_scan,
    compute_metrics_from_scan,
    export_metrics_summary_csv,
    list_library_metric_definitions_by_category,
    scan_library_for_path,
)
from src.core.library_metrics import LIBRARY_METRIC_DEFINITIONS, SIGNAL_QUALITY_METRIC_IDS
from src.core.library_metrics_store import (
    database_paths_match,
    any_session_scan_exists,
    delete_all_saved_snapshots,
    delete_all_session_scans,
    export_scan_pickle,
    get_latest_snapshot_path,
    get_library_data_dir,
    list_session_scan_paths,
    list_snapshots,
    load_scan_pickle,
    load_session_scan,
    load_snapshot,
    save_session_scan,
    save_snapshot,
    session_plots_dir,
    snapshot_plots_dir,
    suggested_scan_export_filename,
    validate_scan_for_database,
)
from src.core.library_plots import (
    generate_plots,
    list_library_plot_definitions,
    list_library_plot_definitions_by_category,
)
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
    attach_signal_quality_to_entries,
    export_per_entry_signal_csv,
)
from src.core.pedigree_analysis_store import (
    get_latest_pedigree_snapshot_path,
    get_pedigree_analysis_dir,
    load_pedigree_result,
    save_pedigree_result,
    session_pedigree_dir,
)
from src.core.pedigree_backend import pedigree_backend_available
from src.core.pedigree_export import export_pedigree_csv
from src.core.pedigree_render import (
    PedigreeTreeRenderOptions,
    build_default_tree_render_options,
    build_pedigree_tree_preview_figure,
    count_visible_pedigree_nodes,
    graphviz_available,
    graphviz_install_hint,
    max_tier_in_records,
    render_pedigree_tree,
    suggest_include_failed,
)
from src.core.pedigree_service import run_pedigree_analysis_for_path
from src.core.rt_assignment_export import (
    build_spreadsheet_rows_from_compounds,
    export_rt_analysis_spreadsheet,
    load_compounds_for_export,
)
from src.core.del_cycle_tree import (
    DelCycleExportResult,
    DelCycleTreeData,
    DelCycleTreeView,
    build_assignments_from_del_cycle_tree,
    build_del_cycle_tree_for_path,
    build_del_cycle_tree_from_metadata_for_path,
    build_del_cycle_tree_from_session_cache_for_path,
    registered_metadata_column_names,
    validate_registered_metadata_columns,
    export_del_cycle_package,
    render_del_cycle_tree_figure,
    resolve_compound_rt_assignments_for_path,
)
from src.core.del_cycle_tree.models import MetadataRtColumnInfo
from src.core.del_cycle_tree.bb_index_scheme import (
    format_bb_branch_label,
    lookup_bb_display_index,
)
from src.core.del_cycle_tree.render import COLOR_MODE_NOTEBOOK, COLOR_MODE_PEDIGREE
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult, PedigreeTierSummary
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.library_report_dialog import LibraryReportDialogResult, show_library_report_dialog
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_TAB_METRICS = "Library QC metrics"
_TAB_PLOTS = "Library QC visualizations"
_TAB_RT_ASSIGNMENT = "RT assignment"
_TAB_PEDIGREE_VIZ = "Pedigree visualization"
_TAB_SPLITTREE_VIZ = "Split-tree visualization"

_SPLITTREE_VIEW_FULL = "Full tree"
_SPLITTREE_VIEW_BRANCH = "BB1 branch"
_SPLITTREE_VIEW_MODES = (_SPLITTREE_VIEW_FULL, _SPLITTREE_VIEW_BRANCH)

_RT_ANALYSIS_PEDIGREE = "pedigree"
_RT_ANALYSIS_DIRECT = "direct_pick"

_SPLITTREE_RT_SESSION = "Session RT assignment"
_SPLITTREE_RT_METADATA = "Spreadsheet metadata"

_SIDEBAR_WRAP = 280
_PLOT_PREVIEW_MAX_WIDTH = 820
_PLOT_LIST_BUTTON_HEIGHT = 52
_SECTION_HEADER_COLOR = ("#0969da", "#58a6ff")
_MAIN_SIDEBAR_MINSIZE = 240
_MAIN_CONTENT_MINSIZE = 520
_PEDIGREE_SUMMARY_MINSIZE = 200
_PEDIGREE_TREE_MINSIZE = 420
_PEDIGREE_CONTROLS_MINSIZE = 160
_PLOT_LIST_MINSIZE = 180
_PLOT_PREVIEW_MINSIZE = 360


def _paned_sash_bg() -> str:
    """Background color for tk.PanedWindow sash handles."""
    return "#3d3d3d" if ctk.get_appearance_mode() == "Dark" else "#c0c0c0"


def _create_horizontal_paned(
    parent: ctk.CTkFrame,
    *,
    left_minsize: int,
    right_minsize: int,
) -> Tuple[tk.PanedWindow, ctk.CTkFrame, ctk.CTkFrame]:
    """Return a horizontal paned window with CTk hosts for left and right panes."""
    paned = tk.PanedWindow(
        parent,
        orient=tk.HORIZONTAL,
        sashwidth=8,
        sashrelief=tk.RAISED,
        opaqueresize=True,
        bg=_paned_sash_bg(),
        bd=0,
        showhandle=False,
    )
    paned.pack(fill="both", expand=True)
    left = ctk.CTkFrame(paned, fg_color="transparent")
    right = ctk.CTkFrame(paned, fg_color="transparent")
    paned.add(left, minsize=left_minsize, stretch="always")
    paned.add(right, minsize=right_minsize, stretch="always")
    return paned, left, right


def _create_vertical_paned(
    parent: ctk.CTkFrame,
    *,
    top_minsize: int,
    bottom_minsize: int,
) -> Tuple[tk.PanedWindow, ctk.CTkFrame, ctk.CTkFrame]:
    """Return a vertical paned window with CTk hosts for top and bottom panes."""
    paned = tk.PanedWindow(
        parent,
        orient=tk.VERTICAL,
        sashwidth=8,
        sashrelief=tk.RAISED,
        opaqueresize=True,
        bg=_paned_sash_bg(),
        bd=0,
        showhandle=False,
    )
    paned.pack(fill="both", expand=True)
    top = ctk.CTkFrame(paned, fg_color="transparent")
    bottom = ctk.CTkFrame(paned, fg_color="transparent")
    paned.add(top, minsize=top_minsize, stretch="always")
    paned.add(bottom, minsize=bottom_minsize, stretch="always")
    return paned, top, bottom


class LibraryOperationCancelled(Exception):
    """Raised in a background worker when the user cancels a library operation."""


def _section_header_font() -> ctk.CTkFont:
    """Section header font (must be created after a Tk root exists)."""
    return ctk.CTkFont(size=14, weight="bold")


def _primary_action_font() -> ctk.CTkFont:
    """Primary action button font (must be created after a Tk root exists)."""
    return ctk.CTkFont(size=14, weight="bold")


class LibraryDataWindow(BaseWindow):
    """
    Library-wide analysis: scan entries once (parse + sort by time), then
    optionally compute summary metrics and/or visualizations from that scan.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
    ) -> None:
        super().__init__(
            parent,
            title="Library Analysis",
            transient_parent=False,
            modal=False,
        )
        self.bind("<Destroy>", self._clear_main_reference)

        self._closing = False
        self.app_state = app_state
        self.config_manager = config_manager
        self._data_store: Optional[DataStore] = None
        self._db_path: Optional[Path] = None
        self._config: Optional[SpreadsheetConfig] = None
        self._index_db_mode = False
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_busy = False
        self._metrics_frame: Optional[ctk.CTkScrollableFrame] = None
        self._plot_list_frame: Optional[ctk.CTkScrollableFrame] = None
        self._content_tabview: Optional[ctk.CTkTabview] = None
        self._plot_preview_tk: Optional[tk.Label] = None
        self._plot_preview_title: Optional[ctk.CTkLabel] = None
        self._plot_preview_help: Optional[ctk.CTkLabel] = None
        self._plot_list_buttons: List[ctk.CTkButton] = []
        self._plot_photo: Optional[object] = None
        self._selected_plot_index: Optional[int] = None
        self._channel_vars: Dict[str, tk.BooleanVar] = {}
        self._metric_vars: Dict[str, tk.BooleanVar] = {}
        self._plot_vars: Dict[str, tk.BooleanVar] = {}
        self._fraction_count_var = tk.StringVar(value=str(DEFAULT_FRACTION_COUNT))
        self._signal_alpha_var = tk.StringVar(value=str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._signal_min_prominence_var = tk.StringVar(value="5")
        self._signal_min_pct_area_var = tk.StringVar(value="3")
        self._pedigree_result: Optional[PedigreeAnalysisResult] = None
        self._pedigree_snapshot_path: Optional[Path] = None
        self._pedigree_frame: Optional[ctk.CTkScrollableFrame] = None
        self._pedigree_summary_label: Optional[ctk.CTkLabel] = None
        self._pedigree_status_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_host: Optional[ctk.CTkFrame] = None
        self._pedigree_tree_placeholder: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_plot_host: Optional[tk.Frame] = None
        self._pedigree_tree_figure: Optional[object] = None
        self._pedigree_tree_canvas: Optional[object] = None
        self._pedigree_tree_toolbar: Optional[object] = None
        self._pedigree_channel_var = tk.StringVar(value="")
        self._pedigree_time_unit_var = tk.StringVar(value="seconds")
        self._pedigree_tolerance_var = tk.StringVar(value="30")
        self._pedigree_del_pass_pct_var = tk.StringVar(value="30")
        self._pedigree_alpha_var = tk.StringVar(value=str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._pedigree_picker_algorithm_var = tk.StringVar(value="modern")
        self._pedigree_gaussian_height_var = tk.StringVar(value="0.35")
        self._pedigree_gaussian_fit_width_var = tk.StringVar(value="30")
        self._pedigree_gaussian_stddev_var = tk.StringVar(value="2")
        self._pedigree_gaussian_min_rt_var = tk.StringVar(value="600")
        self._pedigree_modern_widgets: List[ctk.CTkBaseClass] = []
        self._pedigree_old_school_widgets: List[ctk.CTkBaseClass] = []
        self._pedigree_modern_col: Optional[ctk.CTkFrame] = None
        self._pedigree_old_col: Optional[ctk.CTkFrame] = None
        self._splittree_isoform_var = tk.StringVar(value="All")
        self._pedigree_variant_choices: List[str] = ["All"]
        self._pedigree_include_failed_var = tk.BooleanVar(value=True)
        self._pedigree_show_rt_var = tk.BooleanVar(value=True)
        self._pedigree_tree_tier_slider: Optional[ctk.CTkSlider] = None
        self._pedigree_tree_tier_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_dense_note: Optional[ctk.CTkLabel] = None
        self._pedigree_graphviz_banner: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_node_count_label: Optional[ctk.CTkLabel] = None
        self._rt_analysis_mode_var = tk.StringVar(value=_RT_ANALYSIS_DIRECT)
        self._last_rt_analysis_mode: Optional[str] = None
        self._splittree_view_mode_var = tk.StringVar(value=_SPLITTREE_VIEW_FULL)
        self._splittree_rt_source_var = tk.StringVar(value=_SPLITTREE_RT_SESSION)
        self._splittree_metadata_rt_column_var = tk.StringVar(value="")
        self._splittree_metadata_verified_column_var = tk.StringVar(value="")
        self._splittree_rt_column_menu: Optional[ctk.CTkOptionMenu] = None
        self._splittree_verified_column_menu: Optional[ctk.CTkOptionMenu] = None
        self._splittree_rt_detect_btn: Optional[ctk.CTkButton] = None
        self._splittree_rt_column_status_label: Optional[ctk.CTkLabel] = None
        self._splittree_verified_column_status_label: Optional[ctk.CTkLabel] = None
        self._splittree_rt_scan_running = False
        self._splittree_rt_columns_detected: List[MetadataRtColumnInfo] = []
        self._splittree_viz_data: Optional[DelCycleTreeData] = None
        self._splittree_viz_isoform: Optional[str] = None
        self._del_cycle_tree_isoform: Optional[str] = None
        self._splittree_isoform_menu: Optional[ctk.CTkOptionMenu] = None
        self._splittree_tree_host: Optional[ctk.CTkFrame] = None
        self._splittree_tree_placeholder: Optional[ctk.CTkLabel] = None
        self._splittree_tree_plot_host: Optional[tk.Frame] = None
        self._splittree_tree_figure: Optional[object] = None
        self._splittree_tree_canvas: Optional[object] = None
        self._splittree_tree_toolbar: Optional[object] = None
        self._splittree_body_paned: Optional[tk.PanedWindow] = None
        self._pedigree_viz_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._splittree_viz_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._rt_assignment_results_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_viz_mode_var = tk.StringVar(value=_SPLITTREE_VIEW_FULL)
        self._pedigree_del_branch_var = tk.StringVar(value="")
        self._pedigree_del_color_rt_var = tk.BooleanVar(value=False)
        self._pedigree_del_color_pedigree_var = tk.BooleanVar(value=False)
        self._del_cycle_tree_data: Optional[DelCycleTreeData] = None
        self._del_build_show_loading: bool = True
        self._pedigree_tree_viz_mode_menu: Optional[ctk.CTkOptionMenu] = None
        self._pedigree_del_branch_menu: Optional[ctk.CTkOptionMenu] = None
        self._del_branch_label_to_name: Dict[str, str] = {}
        self._pedigree_tree_header_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tier_controls_frame: Optional[ctk.CTkFrame] = None
        self._pedigree_del_controls_frame: Optional[ctk.CTkFrame] = None
        self._body_paned: Optional[tk.PanedWindow] = None
        self._pedigree_body_paned: Optional[tk.PanedWindow] = None
        self._pedigree_left_paned: Optional[tk.PanedWindow] = None
        self._plots_body_paned: Optional[tk.PanedWindow] = None
        self._metrics_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._plots_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._rt_assignment_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._pedigree_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._cached_scan: Optional[LibraryScanData] = None
        self._qc_metrics_artifact: Optional[LibraryQcMetricsArtifact] = None
        self._qc_plots_artifact: Optional[LibraryQcPlotsArtifact] = None
        self._rt_assignment_artifact: Optional[RtAssignmentReportArtifact] = None
        self._pedigree_viz_artifact: Optional[PedigreeVizReportArtifact] = None
        self._splittree_artifact: Optional[SplittreeVizReportArtifact] = None
        self._current_snapshot: Optional[LibraryComputationSnapshot] = None
        self._current_snapshot_path: Optional[Path] = None
        self._plot_results: List[PlotResult] = []
        self._busy_sensitive_widgets: List[ctk.CTkBaseClass] = []
        self._busy_operation: Optional[str] = None
        self._loading_max_fraction: float = 0.0
        self._cancel_requested = threading.Event()
        self._loading_cancel_btn: Optional[ctk.CTkButton] = None
        self._active_operation_id = 0
        self._worker_op_id = 0

        self.minsize(1000, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        cfg = config_manager.load_default_config()
        if not cfg or not cfg.is_complete():
            messagebox.showerror(
                "Configuration missing",
                "Complete spreadsheet configuration and save it before opening Library Analysis.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        self._config = cfg
        db_path = app_state.database_path
        if not db_path or not Path(db_path).is_file():
            messagebox.showerror(
                "Database required",
                "Load or create a database before opening Library Analysis.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        self._db_path = Path(db_path)
        try:
            self._data_store = DataStore(db_path=self._db_path, use_memory=False)
        except OSError as exc:
            logger.error("Failed to open database: %s", exc, exc_info=True)
            messagebox.showerror("Database error", str(exc), parent=self)
            self.after(50, self.on_close)
            return

        self._index_db_mode = self._data_store.is_index_database()
        n_compounds = self._data_store.get_compound_count()

        self._init_pedigree_settings()

        self._build_top_bar(str(db_path))
        self._build_body_shell()

        if n_compounds == 0:
            self._show_empty_library_message()
        else:
            self._show_idle_placeholder()

        self._update_action_states()
        self.after(150, self._apply_maximized_state)
        self.after(300, self._sync_tabview_height)
        self.after(400, self._set_initial_paned_positions)
        self.after(400, self._try_restore_session_scan)
        logger.info(
            "Library Analysis opened (compounds=%s, index_db=%s)",
            n_compounds,
            self._index_db_mode,
        )

    def _apply_maximized_state(self) -> None:
        if not self._ui_is_active():
            return
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        self.after(100, self._set_initial_paned_positions)

    def _ui_is_active(self) -> bool:
        if self._closing:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _schedule_on_main(self, callback, *args) -> None:
        if not self._ui_is_active():
            return

        def invoke() -> None:
            if not self._ui_is_active():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass

        try:
            self.after(0, invoke)
        except tk.TclError:
            pass

    def _bind_worker_callback(self, callback, *args) -> None:
        """Schedule a worker result handler only if the operation was not superseded."""
        op_id = self._worker_op_id

        def invoke() -> None:
            try:
                if not self._ui_is_active():
                    return
                if op_id != self._active_operation_id:
                    return
                try:
                    callback(*args)
                except tk.TclError:
                    pass
            finally:
                if op_id == self._active_operation_id:
                    self._worker_busy = False
                    try:
                        self._update_action_states()
                    except tk.TclError:
                        pass

        try:
            self.after(0, invoke)
        except tk.TclError:
            if op_id == self._active_operation_id:
                self._worker_busy = False
                try:
                    self._update_action_states()
                except tk.TclError:
                    pass

    def _clear_main_reference(self, event: tk.Event) -> None:
        if event.widget != self:
            return
        main = self.parent
        if main is not None and getattr(main, "_library_data_window", None) is self:
            main._library_data_window = None

    def _build_top_bar(self, db_path: str) -> None:
        """Header row: title, global actions, and database context."""
        bar = ctk.CTkFrame(self, fg_color=("gray92", "gray18"))
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 8))
        bar.grid_columnconfigure(2, weight=1)

        title_row = ctk.CTkFrame(bar, fg_color="transparent")
        title_row.grid(row=0, column=0, padx=(12, 16), pady=8, sticky="w")

        ctk.CTkLabel(
            title_row,
            text="Library Analysis",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=(0, 16))

        self._scan_btn = ctk.CTkButton(
            title_row,
            text="Run library scan",
            width=150,
            height=32,
            font=_primary_action_font(),
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_run_library_scan,
        )
        self._scan_btn.pack(side="left", padx=(0, 8))
        self._busy_sensitive_widgets.append(self._scan_btn)

        self._clear_scan_btn = ctk.CTkButton(
            title_row,
            text="Clear scan",
            width=96,
            height=32,
            fg_color="gray40",
            command=self._on_clear_library_scan,
        )
        self._clear_scan_btn.pack(side="left", padx=(0, 4))
        self._busy_sensitive_widgets.append(self._clear_scan_btn)

        self._export_scan_btn = ctk.CTkButton(
            title_row,
            text="Export scan…",
            width=108,
            height=32,
            fg_color="gray40",
            command=self._on_export_library_scan,
        )
        self._export_scan_btn.pack(side="left", padx=(0, 4))
        self._busy_sensitive_widgets.append(self._export_scan_btn)

        self._import_scan_btn = ctk.CTkButton(
            title_row,
            text="Import scan…",
            width=108,
            height=32,
            fg_color="gray40",
            command=self._on_import_library_scan,
        )
        self._import_scan_btn.pack(side="left", padx=(0, 8))
        self._busy_sensitive_widgets.append(self._import_scan_btn)

        self._export_report_btn = ctk.CTkButton(
            title_row,
            text="Generate report…",
            width=150,
            height=32,
            fg_color="gray40",
            command=self._on_export_report,
        )
        self._export_report_btn.pack(side="left")
        self._busy_sensitive_widgets.append(self._export_report_btn)

        kind = "Index" if self._index_db_mode else "Full"
        fname = Path(db_path).name
        channels = ", ".join(self._config.count_names) if self._config else ""
        ctk.CTkLabel(
            bar,
            text=f"Database: {fname} ({kind})  ·  Channels: {channels}",
            font=ctk.CTkFont(size=12),
            anchor="e",
            justify="right",
        ).grid(row=0, column=2, padx=12, pady=8, sticky="e")

    def _build_body_shell(self) -> None:
        """Resizable split between the left option sidebar and tab content."""
        host = ctk.CTkFrame(self, fg_color="transparent")
        host.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)

        self._body_paned, sidebar_host, content_host = _create_horizontal_paned(
            host,
            left_minsize=_MAIN_SIDEBAR_MINSIZE,
            right_minsize=_MAIN_CONTENT_MINSIZE,
        )
        self._build_left_sidebar(sidebar_host)
        self._build_right_content(content_host)

    def _set_initial_paned_positions(self) -> None:
        """Place paned-window sashes after the first layout pass."""
        if not self._ui_is_active():
            return
        try:
            if self._body_paned is not None:
                total = self._body_paned.winfo_width()
                if total > _MAIN_SIDEBAR_MINSIZE + _MAIN_CONTENT_MINSIZE:
                    self._body_paned.sash_place(0, int(total * 0.28), 0)
            if self._pedigree_body_paned is not None:
                total = self._pedigree_body_paned.winfo_width()
                if total > _PEDIGREE_SUMMARY_MINSIZE + _PEDIGREE_TREE_MINSIZE:
                    self._pedigree_body_paned.sash_place(
                        0,
                        min(300, int(total * 0.30)),
                        0,
                    )
            if self._pedigree_left_paned is not None:
                total = self._pedigree_left_paned.winfo_height()
                if total > _PEDIGREE_SUMMARY_MINSIZE + _PEDIGREE_CONTROLS_MINSIZE:
                    self._pedigree_left_paned.sash_place(
                        0,
                        min(280, int(total * 0.55)),
                        0,
                    )
            if self._plots_body_paned is not None:
                total = self._plots_body_paned.winfo_width()
                if total > _PLOT_LIST_MINSIZE + _PLOT_PREVIEW_MINSIZE:
                    self._plots_body_paned.sash_place(
                        0,
                        min(220, int(total * 0.22)),
                        0,
                    )
        except tk.TclError:
            pass

    def _build_left_sidebar(self, parent: ctk.CTkFrame) -> None:
        """Left column: tab-specific analysis options."""
        shell = ctk.CTkFrame(parent, corner_radius=10)
        self._control_panel = shell
        shell.pack(fill="both", expand=True, padx=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        stack = ctk.CTkFrame(shell, fg_color="transparent")
        stack.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        stack.grid_rowconfigure(0, weight=1)
        stack.grid_columnconfigure(0, weight=1)
        self._sidebar_stack = stack

        self._metrics_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Library QC metrics",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._plots_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Library QC visualizations",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._rt_assignment_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="RT assignment",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._pedigree_viz_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Pedigree visualization",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._splittree_viz_sidebar = ctk.CTkScrollableFrame(
            stack,
            label_text="Split-tree visualization",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        for panel in (
            self._metrics_sidebar,
            self._plots_sidebar,
            self._rt_assignment_sidebar,
            self._pedigree_viz_sidebar,
            self._splittree_viz_sidebar,
        ):
            panel.grid_columnconfigure(0, weight=1)

        self._build_metrics_sidebar_content(self._metrics_sidebar)
        self._build_plots_sidebar_content(self._plots_sidebar)
        self._build_rt_assignment_sidebar_content(self._rt_assignment_sidebar)
        self._build_pedigree_viz_sidebar_content(self._pedigree_viz_sidebar)
        self._build_splittree_viz_sidebar_content(self._splittree_viz_sidebar)
        self._pedigree_sidebar = self._rt_assignment_sidebar
        self._show_sidebar_for_tab(_TAB_METRICS)

        self._status_label = ctk.CTkLabel(
            shell,
            text="No scan loaded.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._status_label.grid(row=1, column=0, padx=12, pady=(4, 10), sticky="w")

    def _show_sidebar_for_tab(self, tab_name: str) -> None:
        panels = {
            _TAB_METRICS: self._metrics_sidebar,
            _TAB_PLOTS: self._plots_sidebar,
            _TAB_RT_ASSIGNMENT: self._rt_assignment_sidebar,
            _TAB_PEDIGREE_VIZ: self._pedigree_viz_sidebar,
            _TAB_SPLITTREE_VIZ: self._splittree_viz_sidebar,
        }
        for name, panel in panels.items():
            if panel is None:
                continue
            if name == tab_name:
                panel.grid(row=0, column=0, sticky="nsew")
            else:
                panel.grid_remove()

    def _on_main_tab_changed(self) -> None:
        if self._content_tabview is None:
            return
        try:
            tab = self._content_tabview.get()
        except (ValueError, tk.TclError):
            return
        if tab == _TAB_PEDIGREE_VIZ and self._pedigree_result is None:
            messagebox.showinfo(
                "Pedigree visualization",
                "Run pedigree RT assignment first, then open this tab.",
                parent=self,
            )
            self._focus_tab(_TAB_RT_ASSIGNMENT)
            return
        self._show_sidebar_for_tab(tab)
        if tab == _TAB_PEDIGREE_VIZ and self._pedigree_result is not None:
            self._show_pedigree_tree_preview(self._pedigree_result)
        elif tab == _TAB_SPLITTREE_VIZ:
            self._show_splittree_placeholder(
                "Choose RT source and click Generate plot in the sidebar."
            )

    def _pack_save_load_row(
        self,
        parent: ctk.CTkFrame,
        *,
        save_command: Callable[[], None],
        load_command: Callable[[], None],
        browse_command: Callable[[], None],
    ) -> Tuple[ctk.CTkButton, ctk.CTkButton, ctk.CTkButton]:
        save_btn = ctk.CTkButton(parent, text="Save results", command=save_command)
        save_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(save_btn)

        row_btns = ctk.CTkFrame(parent, fg_color="transparent")
        row_btns.pack(fill="x", pady=(0, 4))
        load_btn = ctk.CTkButton(
            row_btns, text="Load last", width=90, fg_color="gray40", command=load_command
        )
        load_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        browse_btn = ctk.CTkButton(
            row_btns, text="Browse…", width=90, fg_color="gray40", command=browse_command
        )
        browse_btn.pack(side="left", expand=True, fill="x")
        self._busy_sensitive_widgets.extend([load_btn, browse_btn])
        return save_btn, load_btn, browse_btn

    def _build_metrics_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        self._metrics_btn = ctk.CTkButton(
            actions,
            text="Calculate metrics",
            font=_primary_action_font(),
            height=36,
            command=self._on_calculate_metrics,
        )
        self._metrics_btn.pack(fill="x", pady=(0, 8))
        self._busy_sensitive_widgets.append(self._metrics_btn)

        self._save_btn = ctk.CTkButton(
            actions,
            text="Save results",
            command=self._on_save,
        )
        self._save_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._save_btn)

        metrics_load_row = ctk.CTkFrame(actions, fg_color="transparent")
        metrics_load_row.pack(fill="x", pady=(0, 4))
        self._load_last_btn = ctk.CTkButton(
            metrics_load_row,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=self._on_load_last,
        )
        self._load_last_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._clear_metrics_results_btn = ctk.CTkButton(
            metrics_load_row,
            text="Clear all results",
            width=90,
            fg_color="gray40",
            command=self._on_clear_all_metrics_results,
        )
        self._clear_metrics_results_btn.pack(side="left", expand=True, fill="x")
        self._busy_sensitive_widgets.extend([self._load_last_btn, self._clear_metrics_results_btn])

        self._browse_btn = ctk.CTkButton(
            actions,
            text="Browse…",
            fg_color="gray40",
            command=self._on_browse_saved,
        )
        self._browse_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._browse_btn)

        ctk.CTkLabel(
            panel,
            text="Count channels",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 4))
        row += 1

        assert self._config is not None
        for channel_name in self._config.count_names:
            var = tk.BooleanVar(value=True)
            self._channel_vars[channel_name] = var
            cb = ctk.CTkCheckBox(
                panel,
                text=channel_name,
                variable=var,
                command=self._update_action_states,
            )
            cb.grid(row=row, column=0, sticky="w", padx=12, pady=1)
            self._busy_sensitive_widgets.append(cb)
            row += 1

        ctk.CTkLabel(
            panel,
            text="Metrics",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(10, 4))
        row += 1

        for category, label in (("coverage", "Coverage"), ("signal", "Signal quality")):
            ctk.CTkLabel(
                panel,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
            ).grid(row=row, column=0, sticky="w", padx=12, pady=(2, 0))
            row += 1
            for definition in list_library_metric_definitions_by_category(category):
                var = tk.BooleanVar(value=True)
                self._metric_vars[definition.metric_id] = var
                cb = ctk.CTkCheckBox(
                    panel,
                    text=definition.title.split(" — ")[0],
                    variable=var,
                    command=self._update_action_states,
                )
                cb.grid(row=row, column=0, sticky="w", padx=16, pady=1)
                attach_tooltip(cb, definition.help_text)
                self._busy_sensitive_widgets.append(cb)
                row += 1

        params = ctk.CTkFrame(panel, fg_color="transparent")
        params.grid(row=row, column=0, sticky="ew", padx=8, pady=(10, 4))
        row += 1
        ctk.CTkLabel(params, text="Fraction count", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w"
        )
        frac_entry = ctk.CTkEntry(params, textvariable=self._fraction_count_var)
        frac_entry.pack(fill="x", pady=(2, 6))
        attach_tooltip(frac_entry, "Used for library coverage index.")
        ctk.CTkLabel(params, text="Peak significance α", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w"
        )
        alpha_entry = ctk.CTkEntry(params, textvariable=self._signal_alpha_var)
        alpha_entry.pack(fill="x", pady=(2, 0))
        self._busy_sensitive_widgets.extend([frac_entry, alpha_entry])
        attach_tooltip(
            alpha_entry,
            "α for significant-peak metrics and signal plots. A local maximum counts as "
            "significant only when both height and area p-values are below α/2 "
            "(same engine as Chromatogram Visualizer). Lower α → fewer significant peaks.",
        )
        ctk.CTkLabel(params, text="Min prominence", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", pady=(6, 0)
        )
        prom_entry = ctk.CTkEntry(params, textvariable=self._signal_min_prominence_var)
        prom_entry.pack(fill="x", pady=(2, 0))
        attach_tooltip(
            prom_entry,
            "Drop detected peaks below this prominence (0 = off). Also used by pedigree analysis.",
        )
        ctk.CTkLabel(params, text="Min % area", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", pady=(6, 0)
        )
        pct_entry = ctk.CTkEntry(params, textvariable=self._signal_min_pct_area_var)
        pct_entry.pack(fill="x", pady=(2, 0))
        attach_tooltip(
            pct_entry,
            "Drop detected peaks below this share of total detected peak area (0 = off). "
            "Also used by pedigree analysis.",
        )
        self._busy_sensitive_widgets.extend([prom_entry, pct_entry])

        ctk.CTkLabel(
            panel,
            text=(
                "Run library scan first (top bar). Metrics are computed from that "
                "parsed scan without re-reading the database."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _build_plots_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        self._plots_btn = ctk.CTkButton(
            actions,
            text="Generate plots",
            font=_primary_action_font(),
            height=36,
            command=self._on_generate_plots,
        )
        self._plots_btn.pack(fill="x", pady=(0, 8))
        self._busy_sensitive_widgets.append(self._plots_btn)

        self._plots_save_btn, self._plots_load_btn, self._plots_browse_btn = (
            self._pack_save_load_row(
                actions,
                save_command=self._on_save,
                load_command=self._on_load_last,
                browse_command=self._on_browse_saved,
            )
        )

        self._export_plots_csv_btn = ctk.CTkButton(
            actions,
            text="Export plot data CSV…",
            fg_color="gray40",
            command=self._on_export_signal_csv,
        )
        self._export_plots_csv_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._export_plots_csv_btn)

        ctk.CTkLabel(
            panel,
            text="Plots",
            font=_section_header_font(),
            text_color=_SECTION_HEADER_COLOR,
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 4))
        row += 1

        for category, label in (("coverage", "Coverage"), ("signal", "Signal quality")):
            ctk.CTkLabel(
                panel,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
            ).grid(row=row, column=0, sticky="w", padx=12, pady=(2, 0))
            row += 1
            for definition in list_library_plot_definitions_by_category(category):
                var = tk.BooleanVar(value=True)
                self._plot_vars[definition.plot_id] = var
                cb = ctk.CTkCheckBox(
                    panel,
                    text=definition.title,
                    variable=var,
                    command=self._update_action_states,
                )
                cb.grid(row=row, column=0, sticky="w", padx=16, pady=1)
                attach_tooltip(cb, definition.help_text)
                self._busy_sensitive_widgets.append(cb)
                row += 1

        ctk.CTkLabel(
            panel,
            text=(
                "Plots reuse the library scan from the top bar. Signal-quality plots "
                "use peak parameters from the Summary metrics sidebar."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _build_rt_assignment_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """RT assignment settings and run controls."""
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        ctk.CTkLabel(
            actions,
            text="Analysis mode",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        mode_row = ctk.CTkFrame(actions, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 8))
        ctk.CTkRadioButton(
            mode_row,
            text="Pedigree",
            variable=self._rt_analysis_mode_var,
            value=_RT_ANALYSIS_PEDIGREE,
        ).pack(anchor="w")
        ctk.CTkRadioButton(
            mode_row,
            text="Direct pick",
            variable=self._rt_analysis_mode_var,
            value=_RT_ANALYSIS_DIRECT,
        ).pack(anchor="w")

        self._rt_assignment_run_btn = ctk.CTkButton(
            actions,
            text="Run RT assignment",
            font=_primary_action_font(),
            height=36,
            fg_color="#1F6FEB",
            state="disabled",
            command=self._on_run_rt_assignment,
        )
        self._rt_assignment_run_btn.pack(fill="x", pady=(0, 8))
        self._busy_sensitive_widgets.append(self._rt_assignment_run_btn)
        self._pedigree_run_btn = self._rt_assignment_run_btn  # legacy alias
        self._del_cycle_run_btn = self._rt_assignment_run_btn  # legacy alias

        self._pedigree_save_btn = ctk.CTkButton(
            actions,
            text="Save results",
            fg_color="gray40",
            state="disabled",
            command=self._on_save_pedigree,
        )
        self._pedigree_save_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._pedigree_save_btn)

        ped_row = ctk.CTkFrame(actions, fg_color="transparent")
        ped_row.pack(fill="x", pady=(0, 4))
        self._pedigree_load_btn = ctk.CTkButton(
            ped_row,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=self._on_load_last_pedigree,
        )
        self._pedigree_load_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._pedigree_browse_btn = ctk.CTkButton(
            ped_row,
            text="Browse…",
            width=90,
            fg_color="gray40",
            command=self._on_browse_pedigree,
        )
        self._pedigree_browse_btn.pack(side="left", expand=True, fill="x")
        self._busy_sensitive_widgets.extend([self._pedigree_load_btn, self._pedigree_browse_btn])

        self._pedigree_status_label = ctk.CTkLabel(
            actions,
            text="Direct pick reads chromatograms from the database.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._pedigree_status_label.pack(fill="x", pady=(4, 0))

        pedigree_box = ctk.CTkFrame(panel, fg_color="transparent")
        pedigree_box.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        row += 1

        assert self._config is not None
        pedigree_header = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        pedigree_header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            pedigree_header,
            text="Count channel",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", anchor="w")
        ctk.CTkButton(
            pedigree_header,
            text="? Help",
            width=64,
            height=22,
            fg_color="gray40",
            command=self._on_pedigree_help,
        ).pack(side="right")

        channel_menu = ctk.CTkOptionMenu(
            pedigree_box,
            variable=self._pedigree_channel_var,
            values=list(self._config.count_names) or [""],
        )
        channel_menu.pack(fill="x", pady=(2, 6))
        self._busy_sensitive_widgets.append(channel_menu)

        unit_row = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        unit_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(unit_row, text="Time unit", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w"
        )
        unit_btns = ctk.CTkFrame(unit_row, fg_color="transparent")
        unit_btns.pack(fill="x", pady=(2, 0))
        ctk.CTkRadioButton(
            unit_btns,
            text="Seconds",
            variable=self._pedigree_time_unit_var,
            value="seconds",
            command=self._on_pedigree_time_unit_changed,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            unit_btns,
            text="Minutes",
            variable=self._pedigree_time_unit_var,
            value="minutes",
            command=self._on_pedigree_time_unit_changed,
        ).pack(side="left")

        ctk.CTkLabel(
            pedigree_box, text="Peak picking", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(6, 0))
        picker_menu = ctk.CTkOptionMenu(
            pedigree_box,
            variable=self._pedigree_picker_algorithm_var,
            values=["modern", "old_school"],
            command=lambda _v: self._sync_pedigree_picker_widgets(),
        )
        picker_menu.pack(fill="x", pady=(2, 4))
        self._busy_sensitive_widgets.append(picker_menu)
        attach_tooltip(
            picker_menu,
            "Modern: NB/Poisson significance. Old-school: scipy height gate + Gaussian fits.",
        )

        picker_cols = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        picker_cols.pack(fill="x", pady=(2, 4))
        picker_cols.grid_columnconfigure(0, weight=1, uniform="pedpicker")
        picker_cols.grid_columnconfigure(1, weight=1, uniform="pedpicker")

        modern_col = ctk.CTkFrame(picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        modern_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        old_col = ctk.CTkFrame(picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        old_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._pedigree_modern_col = modern_col
        self._pedigree_old_col = old_col

        ped_modern_hdr = ctk.CTkLabel(
            modern_col, text="Modern", font=ctk.CTkFont(size=10, weight="bold")
        )
        ped_modern_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        ped_alpha_lbl = ctk.CTkLabel(modern_col, text="Peak significance α")
        ped_alpha_lbl.pack(anchor="w", padx=6)
        ped_alpha_entry = ctk.CTkEntry(modern_col, textvariable=self._pedigree_alpha_var)
        ped_alpha_entry.pack(fill="x", padx=6, pady=(2, 8))
        self._busy_sensitive_widgets.append(ped_alpha_entry)
        self._pedigree_modern_widgets.extend([ped_modern_hdr, ped_alpha_lbl, ped_alpha_entry])

        ped_old_hdr = ctk.CTkLabel(
            old_col, text="Old-school", font=ctk.CTkFont(size=10, weight="bold")
        )
        ped_old_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        self._pedigree_old_school_widgets.append(ped_old_hdr)

        def _ped_old_field(parent, label: str, var: tk.StringVar) -> None:
            lbl = ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=10))
            lbl.pack(anchor="w", padx=6)
            entry = ctk.CTkEntry(parent, textvariable=var)
            entry.pack(fill="x", padx=6, pady=(0, 4))
            self._busy_sensitive_widgets.append(entry)
            self._pedigree_old_school_widgets.extend([lbl, entry])

        _ped_old_field(old_col, "Min height factor", self._pedigree_gaussian_height_var)
        _ped_old_field(old_col, "Gaussian fit width", self._pedigree_gaussian_fit_width_var)
        _ped_old_field(old_col, "Max Gaussian σ", self._pedigree_gaussian_stddev_var)
        _ped_old_field(old_col, "Minimum RT", self._pedigree_gaussian_min_rt_var)

        ctk.CTkLabel(pedigree_box, text="Null RT Threshold", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", pady=(6, 0)
        )
        tol_entry = ctk.CTkEntry(pedigree_box, textvariable=self._pedigree_tolerance_var)
        tol_entry.pack(fill="x", pady=(2, 4))
        self._busy_sensitive_widgets.append(tol_entry)

        ctk.CTkButton(
            pedigree_box,
            text="Restore defaults",
            height=24,
            fg_color="gray40",
            command=self._restore_pedigree_picker_defaults,
        ).pack(fill="x", pady=(0, 4))

        self._sync_pedigree_picker_widgets()

        pedigree_ready = (
            self._config.pedigree_configured()
            and pedigree_backend_available()
            and bool(self._config.count_names)
        )
        if not pedigree_ready:
            tip = (
                "Map BB1..BBn columns in Configure Spreadsheet and build the Rust lcseq "
                "extension to enable pedigree analysis."
            )
            if not pedigree_backend_available():
                tip = (
                    "The Rust lcseq extension is required. See docs/DEVELOPER_SETUP.md."
                )
            attach_tooltip(self._rt_assignment_run_btn, tip)
        else:
            attach_tooltip(
                self._rt_assignment_run_btn,
                "Assign retention times using pedigree or direct chromatogram pick. "
                "Use visualization tabs after a successful run.",
            )

        ctk.CTkLabel(
            panel,
            text=(
                "Run library scan first (top bar). After RT assignment, open "
                "Pedigree visualization or Split-tree visualization to view figures."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _build_pedigree_viz_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """Hints for the pedigree visualization tab."""
        ctk.CTkLabel(
            panel,
            text=(
                "Requires a pedigree RT assignment run in this session (or Load last). "
                "Pedigree evaluation includes all isoforms; adjust tier display options "
                "in the tab panel. Use Split-tree visualization to filter by isoform."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=8)

    def _build_splittree_viz_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """Split-tree RT source and generate controls."""
        row = 0
        ctk.CTkLabel(
            panel,
            text="RT source for plot",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 4))
        row += 1
        src_menu = ctk.CTkOptionMenu(
            panel,
            variable=self._splittree_rt_source_var,
            values=[_SPLITTREE_RT_SESSION, _SPLITTREE_RT_METADATA],
            command=lambda _v: self._on_splittree_rt_source_changed(),
        )
        src_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._busy_sensitive_widgets.append(src_menu)
        row += 1

        ctk.CTkLabel(
            panel,
            text="Spreadsheet RT column",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(0, 4))
        row += 1
        self._splittree_rt_column_menu = ctk.CTkOptionMenu(
            panel,
            variable=self._splittree_metadata_rt_column_var,
            values=["(select column)"],
            state="disabled",
            command=lambda _v: self._on_splittree_rt_column_selected(),
        )
        self._splittree_rt_column_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._busy_sensitive_widgets.append(self._splittree_rt_column_menu)
        row += 1

        self._splittree_rt_detect_btn = ctk.CTkButton(
            panel,
            text="Validate column",
            fg_color="gray40",
            state="disabled",
            command=self._on_validate_splittree_rt_column,
        )
        self._splittree_rt_detect_btn.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._busy_sensitive_widgets.append(self._splittree_rt_detect_btn)
        row += 1

        self._splittree_rt_column_status_label = ctk.CTkLabel(
            panel,
            text="Select registered metadata columns, optionally Validate column, then Generate plot.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._splittree_rt_column_status_label.grid(
            row=row, column=0, sticky="w", padx=8, pady=(0, 8)
        )
        row += 1

        ctk.CTkLabel(
            panel,
            text="Null verification column",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(0, 4))
        row += 1
        self._splittree_verified_column_menu = ctk.CTkOptionMenu(
            panel,
            variable=self._splittree_metadata_verified_column_var,
            values=["(select column)"],
            state="disabled",
            command=lambda _v: self._on_splittree_verified_column_selected(),
        )
        self._splittree_verified_column_menu.grid(
            row=row, column=0, sticky="ew", padx=8, pady=(0, 4)
        )
        self._busy_sensitive_widgets.append(self._splittree_verified_column_menu)
        row += 1

        self._splittree_verified_column_status_label = ctk.CTkLabel(
            panel,
            text=(
                "Select the registered metadata column with null-analysis pass/fail "
                "(e.g. from RT export)."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._splittree_verified_column_status_label.grid(
            row=row, column=0, sticky="w", padx=8, pady=(0, 8)
        )
        row += 1

        if self._config is not None and self._config.compound_variant_column:
            ctk.CTkLabel(
                panel,
                text="Isoform",
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=row, column=0, sticky="w", padx=8, pady=(0, 4))
            row += 1
            self._splittree_isoform_menu = ctk.CTkOptionMenu(
                panel,
                variable=self._splittree_isoform_var,
                values=self._pedigree_variant_choices,
                command=lambda _v: self._on_splittree_isoform_changed(),
            )
            self._splittree_isoform_menu.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
            self._busy_sensitive_widgets.append(self._splittree_isoform_menu)
            row += 1

        self._splittree_generate_btn = ctk.CTkButton(
            panel,
            text="Generate plot",
            font=_primary_action_font(),
            height=36,
            fg_color="#1F6FEB",
            command=self._on_generate_splittree_plot,
        )
        self._splittree_generate_btn.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._busy_sensitive_widgets.append(self._splittree_generate_btn)
        row += 1
        ctk.CTkLabel(
            panel,
            text=(
                "Session RT assignment uses results from the RT assignment tab. "
                "Spreadsheet metadata reads precomputed RTs and null verification "
                "from registered metadata columns (skips peak picking only); null "
                "truncation verification still runs. Include RTs for truncation rows, "
                "not just full products. Empty cells are skipped."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(0, 8))

    def _splittree_isoform_label(self) -> str:
        return self._splittree_isoform_var.get().strip() or "All"

    def _session_del_cycle_isoform_matches(self) -> bool:
        """True when cached RT-assignment tree can be reused for the current viz filter."""
        return self._can_reuse_session_del_cycle_tree(self._splittree_isoform_label())

    def _cached_session_del_cycle_isoform(self) -> str:
        return (self._del_cycle_tree_isoform or "All").strip() or "All"

    def _can_reuse_session_del_cycle_tree(self, isoform: str = "All") -> bool:
        """True when session RT assignment data can be rendered without re-picking peaks."""
        _ = isoform
        return self._del_cycle_tree_data is not None

    def _resolve_splittree_figure(
        self,
        data: DelCycleTreeData,
        *,
        view_mode: str,
        branch_selection: str,
        color_by_rt: bool,
        color_mode: str,
        pass_pct_cutoff: float,
    ) -> Tuple[object, str]:
        view = (
            DelCycleTreeView.BRANCH
            if view_mode == _SPLITTREE_VIEW_BRANCH
            else DelCycleTreeView.FULL
        )
        selected_branch = branch_selection
        if view == DelCycleTreeView.BRANCH:
            branches = self._sorted_bb1_branch_names(data)
            resolved = self._resolve_del_branch_bb1(data, branch_selection)
            if resolved in branches:
                selected_branch = resolved
            elif branches:
                selected_branch = branches[0]
        figure = render_del_cycle_tree_figure(
            data,
            view=view,
            branch_bb1=selected_branch if view == DelCycleTreeView.BRANCH else None,
            color_by_rt=color_by_rt,
            color_mode=color_mode,
            pass_pct_cutoff=pass_pct_cutoff,
        )
        return figure, selected_branch

    def _render_splittree_from_cached_session(
        self,
        isoform: str,
        *,
        show_loading: bool,
    ) -> None:
        """Render split-tree from cached RT assignment data (no compound re-analysis)."""
        session_data = self._del_cycle_tree_data
        if session_data is None or self._config is None or self._db_path is None:
            return
        isoform = (isoform or "All").strip() or "All"
        isoform_filter = isoform.lower() != "all"
        if show_loading:
            detail = (
                f"Filtering session RT assignment for isoform “{isoform}”…"
                if isoform_filter
                else "Rendering split-tree from session RT assignment (no re-analysis)…"
            )
            self._show_loading_page("Generating split-tree", detail)
        view_mode = self._splittree_view_mode_var.get()
        branch_selection = self._pedigree_del_branch_var.get().strip()
        color_by_rt = bool(self._pedigree_del_color_rt_var.get())
        color_mode = self._del_tree_color_mode()
        pass_pct_cutoff = self._read_del_tree_pass_pct_cutoff()
        settings = self._parse_pedigree_settings()
        rt_threshold = float(settings.tolerance) if settings is not None else session_data.rt_threshold
        db_path = self._db_path
        config = self._config

        def worker() -> None:
            try:
                def progress(step: int, total: int, status: str) -> None:
                    if not show_loading:
                        return
                    if total == 1000:
                        fraction = step / 1000.0
                    else:
                        fraction = step / total if total > 0 else 0.0
                    self._thread_loading_progress(
                        min(0.95, fraction),
                        status or "Building split-tree from session RT assignment…",
                    )

                if isoform_filter:
                    data = build_del_cycle_tree_from_session_cache_for_path(
                        db_path,
                        config,
                        session_data,
                        isoform_label=isoform,
                        rt_threshold=rt_threshold,
                        progress_callback=progress if show_loading else None,
                    )
                else:
                    data = session_data
                if show_loading:
                    self._thread_loading_progress(0.96, "Rendering split-tree figure…")
                figure, selected_branch = self._resolve_splittree_figure(
                    data,
                    view_mode=view_mode,
                    branch_selection=branch_selection,
                    color_by_rt=color_by_rt,
                    color_mode=color_mode,
                    pass_pct_cutoff=pass_pct_cutoff,
                )
                self._bind_worker_callback(
                    self._on_splittree_session_ready,
                    data,
                    figure,
                    selected_branch,
                    isoform,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Cached session split-tree render failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_splittree_metadata_failed, str(exc))

        self._start_worker(worker)
        self._update_action_states()

    def _reuse_session_del_cycle_for_splittree(self) -> bool:
        """Render split-tree from cached session RT data without rebuilding."""
        isoform = self._splittree_isoform_label()
        if not self._can_reuse_session_del_cycle_tree(isoform):
            return False
        self._render_splittree_from_cached_session(isoform, show_loading=False)
        return True

    def _format_splittree_rt_column_status(
        self,
        discovered: List[MetadataRtColumnInfo],
        *,
        selected: str = "",
    ) -> str:
        if not discovered:
            return (
                "No metadata columns are registered. "
                "Select columns in Configure Spreadsheet and re-process the library."
            )
        selected = selected.strip()
        if selected and selected != "(select column)":
            match = next(
                (info for info in discovered if info.column_name == selected),
                None,
            )
            if match is not None:
                if match.n_compounds_scanned == 0:
                    return f"“{match.column_name}”: not validated yet."
                pct = (
                    100.0 * match.n_numeric_values / match.n_compounds_scanned
                    if match.n_compounds_scanned
                    else 0.0
                )
                return (
                    f"“{match.column_name}”: {match.n_numeric_values:,} numeric values "
                    f"({pct:.1f}% of library), "
                    f"{match.n_with_bb_positions:,} with BB positions."
                )
        with_values = [info for info in discovered if info.n_numeric_values > 0]
        if not with_values:
            return (
                f"{len(discovered)} registered column(s); none have numeric values yet. "
                "Click Validate column to scan the library."
            )
        return (
            f"{len(discovered)} registered metadata column(s). "
            f"{len(with_values)} contain numeric values after validation."
        )

    def _format_splittree_verified_column_status(
        self,
        discovered: List[MetadataRtColumnInfo],
        *,
        selected: str = "",
    ) -> str:
        if not discovered:
            return (
                "No metadata columns are registered. "
                "Select columns in Configure Spreadsheet and re-process the library."
            )
        selected = selected.strip()
        if selected and selected != "(select column)":
            match = next(
                (info for info in discovered if info.column_name == selected),
                None,
            )
            if match is not None:
                if match.n_compounds_scanned == 0:
                    return f"“{match.column_name}”: not validated yet."
                pct = (
                    100.0 * match.n_verified_values / match.n_compounds_scanned
                    if match.n_compounds_scanned
                    else 0.0
                )
                return (
                    f"“{match.column_name}”: {match.n_verified_values:,} pass/fail values "
                    f"({pct:.1f}% of library), "
                    f"{match.n_verified_with_bb_positions:,} with BB positions."
                )
        with_values = [info for info in discovered if info.n_verified_values > 0]
        if not with_values:
            return (
                f"{len(discovered)} registered column(s); none have pass/fail values yet. "
                "Click Validate column to scan the library."
            )
        return (
            f"{len(discovered)} registered metadata column(s). "
            f"{len(with_values)} contain pass/fail values after validation."
        )

    def _load_registered_metadata_columns(self) -> None:
        """Populate the RT column dropdown from Configure Spreadsheet metadata."""
        if self._config is None:
            return
        names = registered_metadata_column_names(self._config)
        placeholder = [
            MetadataRtColumnInfo(
                column_name=name,
                n_numeric_values=0,
                n_compounds_scanned=0,
            )
            for name in names
        ]
        self._splittree_rt_columns_detected = placeholder
        self._apply_splittree_rt_column_choices(placeholder)
        if self._splittree_rt_column_status_label is not None:
            if names:
                self._splittree_rt_column_status_label.configure(
                    text=(
                        f"{len(names)} registered metadata column(s). "
                        "Click Validate column to check numeric value counts."
                    ),
                    text_color="gray",
                )
            else:
                self._splittree_rt_column_status_label.configure(
                    text=(
                        "No metadata columns registered in Configure Spreadsheet."
                    ),
                    text_color="#D29922",
                )
        if self._splittree_verified_column_status_label is not None:
            self._splittree_verified_column_status_label.configure(
                text=self._format_splittree_verified_column_status(placeholder),
                text_color="#D29922" if not names else "gray",
            )

    def _build_pedigree_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """Legacy hook — use ``_build_rt_assignment_sidebar_content``."""
        self._build_rt_assignment_sidebar_content(panel)

    def _init_pedigree_settings(self) -> None:
        """Set pedigree control defaults from loaded spreadsheet config."""
        if self._config is None:
            return
        default_channel = self._config.count_names[0] if self._config.count_names else ""
        self._pedigree_channel_var.set(default_channel)
        self._pedigree_time_unit_var.set(self._config.analysis_time_unit)
        self._pedigree_tolerance_var.set(
            "30" if self._config.analysis_time_unit == "seconds" else "0.5"
        )
        self._pedigree_alpha_var.set(str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._pedigree_picker_algorithm_var.set("modern")
        self._apply_pedigree_gaussian_defaults(self._config.analysis_time_unit)
        self._splittree_isoform_var.set("All")
        self._pedigree_variant_choices = self._collect_variant_choices()
        self._sync_pedigree_picker_widgets()

    def _apply_pedigree_gaussian_defaults(self, time_unit: str) -> None:
        unit = "minutes" if time_unit == "minutes" else "seconds"
        g = AnalysisSettings.default_gaussian_params(unit)  # type: ignore[arg-type]
        self._pedigree_gaussian_height_var.set(str(g["gaussian_min_height_factor"]))
        self._pedigree_gaussian_fit_width_var.set(str(g["gaussian_fit_width"]))
        self._pedigree_gaussian_stddev_var.set(str(g["gaussian_stddev_threshold"]))
        self._pedigree_gaussian_min_rt_var.set(str(g["gaussian_minimum_rt"]))

    def _restore_pedigree_picker_defaults(self) -> None:
        self._pedigree_alpha_var.set(str(AnalysisSettings.default_modern_alpha()))
        self._apply_pedigree_gaussian_defaults(self._pedigree_time_unit_var.get())
        tol = "30" if self._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._pedigree_tolerance_var.set(tol)
        self._sync_pedigree_picker_widgets()

    def _on_pedigree_time_unit_changed(self) -> None:
        self._apply_pedigree_gaussian_defaults(self._pedigree_time_unit_var.get())
        tol = "30" if self._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._pedigree_tolerance_var.set(tol)

    def _sync_pedigree_picker_widgets(self) -> None:
        old_school = self._pedigree_picker_algorithm_var.get() == "old_school"
        modern_state = "disabled" if old_school else "normal"
        old_state = "normal" if old_school else "disabled"
        modern_fg = ("gray85", "gray25") if not old_school else ("gray78", "gray20")
        old_fg = ("gray85", "gray25") if old_school else ("gray78", "gray20")
        if self._pedigree_modern_col is not None:
            self._pedigree_modern_col.configure(fg_color=modern_fg)
        if self._pedigree_old_col is not None:
            self._pedigree_old_col.configure(fg_color=old_fg)
        for widget in self._pedigree_modern_widgets:
            try:
                widget.configure(state=modern_state)
            except Exception:
                pass
        for widget in self._pedigree_old_school_widgets:
            try:
                widget.configure(state=old_state)
            except Exception:
                pass

    def _collect_variant_choices(self) -> List[str]:
        """Distinct isoform labels from the active database."""
        choices = ["All"]
        if self._data_store is None or self._config is None:
            return choices
        if not self._config.compound_variant_column:
            return choices
        try:
            cursor = self._data_store.conn.execute(
                """
                SELECT DISTINCT compound_variant
                FROM compounds
                WHERE compound_variant IS NOT NULL AND TRIM(compound_variant) != ''
                ORDER BY compound_variant
                """
            )
            for row in cursor.fetchall():
                label = str(row[0]).strip()
                if label and label not in choices:
                    choices.append(label)
        except Exception as exc:
            logger.warning("Could not load variant choices: %s", exc)
        return choices

    def _build_tree_figure_host(
        self,
        parent: ctk.CTkFrame,
        *,
        tk_bg: str,
        title: str,
        subtitle: str,
        placeholder: str,
    ) -> Tuple[ctk.CTkFrame, ctk.CTkLabel, tk.Frame, ctk.CTkLabel]:
        """Create a matplotlib tree preview host with header labels."""
        col = ctk.CTkFrame(parent, corner_radius=8)
        col.pack(fill="both", expand=True)
        col.grid_columnconfigure(0, weight=1)
        col.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(col, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        subtitle_label = ctk.CTkLabel(
            header,
            text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=520,
            justify="left",
        )
        subtitle_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ctk.CTkLabel(
            header,
            text="Use the matplotlib toolbar below the figure to pan, zoom, and reset the view.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=520,
            justify="left",
        ).grid(row=2, column=0, sticky="ew", pady=(2, 0))

        host = ctk.CTkFrame(col, fg_color=("gray90", "gray17"))
        host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)

        placeholder_label = ctk.CTkLabel(
            host,
            text=placeholder,
            font=ctk.CTkFont(size=12),
            text_color="gray",
            wraplength=520,
            justify="center",
        )
        placeholder_label.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        plot_host = tk.Frame(host, bg=tk_bg)
        plot_host.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        plot_host.grid_remove()
        return host, placeholder_label, plot_host, subtitle_label

    def _build_rt_and_viz_tabs(self, tk_bg: str) -> None:
        """RT assignment, pedigree visualization, and split-tree visualization tabs."""
        assert self._content_tabview is not None and self._config is not None

        rt_tab = self._content_tabview.add(_TAB_RT_ASSIGNMENT)
        rt_tab.grid_columnconfigure(0, weight=1)
        rt_tab.grid_rowconfigure(1, weight=1)

        rt_toolbar = ctk.CTkFrame(rt_tab, fg_color="transparent")
        rt_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        rt_toolbar.grid_columnconfigure(0, weight=1)

        self._pedigree_summary_label = ctk.CTkLabel(
            rt_toolbar,
            text="Configure peak picking and analysis mode in the sidebar, then run RT assignment.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
            wraplength=760,
            justify="left",
        )
        self._pedigree_summary_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        rt_actions = ctk.CTkFrame(rt_toolbar, fg_color="transparent")
        rt_actions.grid(row=1, column=0, sticky="w")

        self._export_rts_btn = ctk.CTkButton(
            rt_actions,
            text="Export RTs…",
            width=130,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_assigned_rts,
        )
        self._export_rts_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._export_rts_btn)

        self._pedigree_export_del_csv_btn = ctk.CTkButton(
            rt_actions,
            text="Export analysis bundle…",
            width=170,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_del_cycle_csv,
        )
        self._pedigree_export_del_csv_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._pedigree_export_del_csv_btn)

        self._pedigree_help_btn = ctk.CTkButton(
            rt_actions,
            text="Help ▾",
            width=100,
            fg_color="gray40",
            command=self._show_pedigree_help_menu,
        )
        self._pedigree_help_btn.pack(side="left", padx=(0, 6))

        rt_body = ctk.CTkScrollableFrame(rt_tab, label_text="Assignment results")
        rt_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        rt_body.grid_columnconfigure(0, weight=1)
        self._rt_assignment_results_label = ctk.CTkLabel(
            rt_body,
            text="No RT assignment run yet.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="nw",
            wraplength=760,
            justify="left",
        )
        self._rt_assignment_results_label.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        # --- Pedigree visualization tab ---
        ped_viz_tab = self._content_tabview.add(_TAB_PEDIGREE_VIZ)
        ped_viz_tab.grid_columnconfigure(0, weight=1)
        ped_viz_tab.grid_rowconfigure(1, weight=1)

        ped_viz_toolbar = ctk.CTkFrame(ped_viz_tab, fg_color="transparent")
        ped_viz_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        ped_viz_actions = ctk.CTkFrame(ped_viz_toolbar, fg_color="transparent")
        ped_viz_actions.grid(row=0, column=0, sticky="w")
        self._pedigree_export_tree_btn = ctk.CTkButton(
            ped_viz_actions,
            text="Export tree PNG…",
            width=140,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_pedigree_tree,
        )
        self._pedigree_export_tree_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._pedigree_export_tree_btn)
        self._pedigree_export_csv_btn = ctk.CTkButton(
            ped_viz_actions,
            text="Export pedigree CSV…",
            width=150,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_pedigree_csv,
        )
        self._pedigree_export_csv_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._pedigree_export_csv_btn)

        ped_viz_body = ctk.CTkFrame(ped_viz_tab, fg_color="transparent")
        ped_viz_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        ped_viz_body.grid_columnconfigure(0, weight=1)
        ped_viz_body.grid_rowconfigure(0, weight=1)

        self._pedigree_body_paned, ped_left, ped_right = _create_horizontal_paned(
            ped_viz_body,
            left_minsize=_PEDIGREE_SUMMARY_MINSIZE,
            right_minsize=_PEDIGREE_TREE_MINSIZE,
        )
        self._pedigree_left_paned, ped_summary_host, ped_controls_host = _create_vertical_paned(
            ped_left,
            top_minsize=_PEDIGREE_SUMMARY_MINSIZE,
            bottom_minsize=_PEDIGREE_CONTROLS_MINSIZE,
        )
        self._pedigree_frame = ctk.CTkScrollableFrame(
            ped_summary_host,
            label_text="Tier summary",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._pedigree_frame.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))

        ped_controls = ctk.CTkFrame(ped_controls_host, fg_color="transparent")
        ped_controls.pack(fill="both", expand=True, padx=(0, 4), pady=(4, 0))
        ped_controls.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            ped_controls,
            text="Pedigree tree display",
            font=_section_header_font(),
            text_color=_SECTION_HEADER_COLOR,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ped_controls_inner = ctk.CTkFrame(ped_controls, corner_radius=8)
        ped_controls_inner.grid(row=1, column=0, sticky="ew")
        ped_controls_inner.grid_columnconfigure(0, weight=1)

        self._pedigree_graphviz_banner = ctk.CTkLabel(
            ped_controls_inner,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="#B8860B",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._pedigree_graphviz_banner.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._update_pedigree_graphviz_banner()

        self._pedigree_tier_controls_frame = ctk.CTkFrame(
            ped_controls_inner, fg_color="transparent"
        )
        self._pedigree_tier_controls_frame.grid(row=1, column=0, sticky="ew")
        self._pedigree_tier_controls_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(
            self._pedigree_tier_controls_frame,
            text="Show failed trim points",
            variable=self._pedigree_include_failed_var,
            command=self._on_pedigree_tree_option_changed,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=2)
        ctk.CTkCheckBox(
            self._pedigree_tier_controls_frame,
            text="Show chosen RT on passed nodes",
            variable=self._pedigree_show_rt_var,
            command=self._on_pedigree_tree_option_changed,
        ).grid(row=1, column=0, sticky="w", padx=8, pady=2)
        tier_row = ctk.CTkFrame(self._pedigree_tier_controls_frame, fg_color="transparent")
        tier_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 2))
        tier_row.grid_columnconfigure(0, weight=1)
        self._pedigree_tree_tier_label = ctk.CTkLabel(
            tier_row,
            text="Max tier shown: —",
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._pedigree_tree_tier_label.grid(row=0, column=0, sticky="w")
        max_tier_default = max(0, (self._config.library_cycle_count or 1) - 1)
        self._pedigree_tree_tier_slider = ctk.CTkSlider(
            tier_row,
            from_=0,
            to=max(max_tier_default, 1),
            number_of_steps=max(max_tier_default, 1),
            command=self._on_pedigree_tier_slider_changed,
        )
        self._pedigree_tree_tier_slider.set(float(max_tier_default))
        self._pedigree_tree_tier_slider.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._pedigree_tree_dense_note = ctk.CTkLabel(
            ped_controls_inner,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._pedigree_tree_dense_note.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 0))
        self._pedigree_tree_node_count_label = ctk.CTkLabel(
            ped_controls_inner,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        )
        self._pedigree_tree_node_count_label.grid(row=3, column=0, sticky="w", padx=8, pady=(0, 8))
        ctk.CTkButton(
            ped_controls_inner,
            text="Refresh pedigree tree",
            width=140,
            fg_color="gray40",
            command=self._on_refresh_pedigree_tree,
        ).grid(row=4, column=0, sticky="w", padx=8, pady=(0, 8))

        (
            self._pedigree_tree_host,
            self._pedigree_tree_placeholder,
            self._pedigree_tree_plot_host,
            self._pedigree_tree_header_label,
        ) = self._build_tree_figure_host(
            ped_right,
            tk_bg=tk_bg,
            title="Pedigree tier-ring",
            subtitle="Requires a pedigree RT assignment run in this session.",
            placeholder="Run pedigree RT assignment, then open this tab.",
        )

        # --- Split-tree visualization tab ---
        st_tab = self._content_tabview.add(_TAB_SPLITTREE_VIZ)
        st_tab.grid_columnconfigure(0, weight=1)
        st_tab.grid_rowconfigure(1, weight=1)

        st_body = ctk.CTkFrame(st_tab, fg_color="transparent")
        st_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        st_body.grid_columnconfigure(0, weight=1)
        st_body.grid_rowconfigure(0, weight=1)

        self._splittree_body_paned, st_left, st_right = _create_horizontal_paned(
            st_body,
            left_minsize=_PEDIGREE_CONTROLS_MINSIZE,
            right_minsize=_PEDIGREE_TREE_MINSIZE,
        )
        st_controls = ctk.CTkFrame(st_left, fg_color="transparent")
        st_controls.pack(fill="both", expand=True, padx=(0, 4), pady=(4, 0))
        st_controls.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            st_controls,
            text="Split-tree display",
            font=_section_header_font(),
            text_color=_SECTION_HEADER_COLOR,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        st_inner = ctk.CTkFrame(st_controls, corner_radius=8)
        st_inner.grid(row=1, column=0, sticky="ew")
        st_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            st_inner,
            text="View",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        self._splittree_view_mode_menu = ctk.CTkOptionMenu(
            st_inner,
            variable=self._splittree_view_mode_var,
            values=list(_SPLITTREE_VIEW_MODES),
            command=lambda _v: self._on_splittree_view_changed(),
        )
        self._splittree_view_mode_menu.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))

        self._pedigree_del_controls_frame = ctk.CTkFrame(st_inner, fg_color="transparent")
        self._pedigree_del_controls_frame.grid(row=2, column=0, sticky="ew")
        self._pedigree_del_controls_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._pedigree_del_controls_frame,
            text="BB1 branch",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(4, 2))
        self._pedigree_del_branch_menu = ctk.CTkOptionMenu(
            self._pedigree_del_controls_frame,
            variable=self._pedigree_del_branch_var,
            values=["—"],
            command=lambda _v: self._on_del_branch_changed(),
        )
        self._pedigree_del_branch_menu.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        ctk.CTkCheckBox(
            self._pedigree_del_controls_frame,
            text="Color product leaves by RT",
            variable=self._pedigree_del_color_rt_var,
            command=self._on_del_tree_option_changed,
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 4))
        ctk.CTkCheckBox(
            self._pedigree_del_controls_frame,
            text="Color by pedigree pass/fail",
            variable=self._pedigree_del_color_pedigree_var,
            command=self._on_del_tree_option_changed,
        ).grid(row=3, column=0, sticky="w", padx=8, pady=(0, 4))
        ctk.CTkLabel(
            self._pedigree_del_controls_frame,
            text="Pass % cutoff (hub coloring)",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=4, column=0, sticky="w", padx=8, pady=(4, 2))
        pass_pct_entry = ctk.CTkEntry(
            self._pedigree_del_controls_frame,
            textvariable=self._pedigree_del_pass_pct_var,
        )
        pass_pct_entry.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 2))
        pass_pct_entry.bind("<FocusOut>", lambda _e: self._on_del_pass_pct_changed())
        pass_pct_entry.bind("<Return>", lambda _e: self._on_del_pass_pct_changed())
        self._busy_sensitive_widgets.append(pass_pct_entry)
        ctk.CTkLabel(
            self._pedigree_del_controls_frame,
            text=(
                "Hub turns blue when ≥ this % of descendant full products pass "
                "(RT verify or pedigree mode). Use 0 for “any pass” (legacy)."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=6, column=0, sticky="w", padx=8, pady=(0, 4))

        self._splittree_status_label = ctk.CTkLabel(
            st_inner,
            text="",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._splittree_status_label.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 8))

        (
            self._splittree_tree_host,
            self._splittree_tree_placeholder,
            self._splittree_tree_plot_host,
            self._splittree_header_label,
        ) = self._build_tree_figure_host(
            st_right,
            tk_bg=tk_bg,
            title="DEL split-tree",
            subtitle="Build from session RT assignment or spreadsheet metadata (sidebar).",
            placeholder="Run RT assignment or choose metadata source, then refresh.",
        )

        self._on_splittree_view_changed()

    def _build_right_content(self, parent: ctk.CTkFrame) -> None:
        """Right column: metrics and visualization tabs."""
        shell = ctk.CTkFrame(parent, fg_color="transparent")
        self._results_shell = shell
        shell.pack(fill="both", expand=True, padx=(8, 0))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._content_tabview = ctk.CTkTabview(
            shell, corner_radius=10, command=self._on_main_tab_changed
        )
        self._content_tabview.grid(row=0, column=0, sticky="nsew")
        shell.bind("<Configure>", self._on_results_shell_resize)

        metrics_tab = self._content_tabview.add(_TAB_METRICS)
        metrics_tab.grid_columnconfigure(0, weight=1)
        metrics_tab.grid_rowconfigure(1, weight=1)
        metrics_tab.grid_rowconfigure(0, weight=0)

        metrics_toolbar = ctk.CTkFrame(metrics_tab, fg_color="transparent")
        metrics_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        metrics_toolbar.grid_columnconfigure(0, weight=1)

        self._metrics_summary_label = ctk.CTkLabel(
            metrics_toolbar,
            text="Summary metrics appear after Calculate metrics.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self._metrics_summary_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        metrics_actions = ctk.CTkFrame(metrics_toolbar, fg_color="transparent")
        metrics_actions.grid(row=1, column=0, sticky="w")

        self._export_metrics_csv_btn = ctk.CTkButton(
            metrics_actions,
            text="Export metrics CSV…",
            width=150,
            fg_color="#0969da",
            hover_color="#1f6feb",
            state="disabled",
            command=self._on_export_metrics_csv,
        )
        self._export_metrics_csv_btn.pack(side="left")
        self._busy_sensitive_widgets.append(self._export_metrics_csv_btn)

        self._metrics_frame = ctk.CTkScrollableFrame(metrics_tab, fg_color="transparent")
        self._metrics_frame.grid(row=1, column=0, sticky="nsew")
        self._metrics_frame.grid_columnconfigure(0, weight=1)

        plots_tab = self._content_tabview.add(_TAB_PLOTS)
        plots_tab.grid_columnconfigure(0, weight=1)
        plots_tab.grid_rowconfigure(1, weight=1)
        plots_tab.grid_rowconfigure(0, weight=0)

        plots_toolbar = ctk.CTkFrame(plots_tab, fg_color="transparent")
        plots_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        plots_toolbar.grid_columnconfigure(0, weight=1)

        self._plots_summary_label = ctk.CTkLabel(
            plots_toolbar,
            text="No plots generated yet.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self._plots_summary_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        plots_actions = ctk.CTkFrame(plots_toolbar, fg_color="transparent")
        plots_actions.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._plot_export_btn = ctk.CTkButton(
            plots_actions,
            text="Export PNG…",
            width=110,
            fg_color="gray40",
            state="disabled",
            command=self._on_export_current_plot,
        )
        self._plot_export_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._plot_export_btn)

        self._export_all_plots_btn = ctk.CTkButton(
            plots_actions,
            text="Export all plots…",
            width=130,
            fg_color="gray40",
            command=self._on_export_all_plots,
        )
        self._export_all_plots_btn.pack(side="left", padx=(0, 6))
        self._busy_sensitive_widgets.append(self._export_all_plots_btn)

        self._open_plots_folder_btn = ctk.CTkButton(
            plots_actions,
            text="Open plots folder",
            width=120,
            fg_color="gray40",
            command=self._on_open_plots_folder,
        )
        self._open_plots_folder_btn.pack(side="left")
        self._busy_sensitive_widgets.append(self._open_plots_folder_btn)

        plot_body = ctk.CTkFrame(plots_tab, fg_color="transparent")
        plot_body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        plot_body.grid_columnconfigure(0, weight=1)
        plot_body.grid_rowconfigure(0, weight=1)

        self._plots_body_paned, plot_list_host, plot_preview_host = _create_horizontal_paned(
            plot_body,
            left_minsize=_PLOT_LIST_MINSIZE,
            right_minsize=_PLOT_PREVIEW_MINSIZE,
        )

        self._plot_list_frame = ctk.CTkScrollableFrame(
            plot_list_host,
            label_text="Plots",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        self._plot_list_frame.pack(fill="both", expand=True, padx=(0, 4))

        preview_col = ctk.CTkFrame(plot_preview_host, corner_radius=8)
        preview_col.pack(fill="both", expand=True)
        preview_col.grid_columnconfigure(0, weight=1)
        preview_col.grid_rowconfigure(2, weight=1)

        self._plot_preview_title = ctk.CTkLabel(
            preview_col,
            text="Select a plot from the list",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
            wraplength=560,
            justify="left",
        )
        self._plot_preview_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        self._plot_preview_help = ctk.CTkLabel(
            preview_col,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=620,
            justify="left",
        )
        self._plot_preview_help.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        preview_host = ctk.CTkFrame(preview_col, fg_color=("gray90", "gray17"))
        preview_host.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        preview_host.grid_columnconfigure(0, weight=1)
        preview_host.grid_rowconfigure(0, weight=1)

        tk_bg = ctk.ThemeManager.theme["CTkFrame"]["fg_color"][
            1 if ctk.get_appearance_mode() == "Dark" else 0
        ]
        self._plot_preview_tk = tk.Label(preview_host, text="", bg=tk_bg, borderwidth=0)
        self._plot_preview_tk.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._build_rt_and_viz_tabs(tk_bg)

        self._loading_frame = ctk.CTkFrame(shell, corner_radius=12)
        self._loading_frame.grid(row=0, column=0, sticky="nsew")
        self._loading_frame.grid_columnconfigure(0, weight=1)
        self._loading_frame.grid_rowconfigure(0, weight=1)

        loading_center = ctk.CTkFrame(self._loading_frame, fg_color="transparent")
        loading_center.grid(row=0, column=0)
        loading_center.grid_columnconfigure(0, weight=1)

        self._loading_title = ctk.CTkLabel(
            loading_center,
            text="Working…",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self._loading_title.grid(row=0, column=0, pady=(0, 8))

        self._loading_detail = ctk.CTkLabel(
            loading_center,
            text="Please wait while processing continues.",
            font=ctk.CTkFont(size=13),
            text_color="gray",
            wraplength=520,
            justify="center",
        )
        self._loading_detail.grid(row=1, column=0, pady=(0, 16))

        self._loading_bar = ctk.CTkProgressBar(loading_center, width=420)
        self._loading_bar.grid(row=2, column=0, pady=(0, 8))
        self._loading_bar.set(0)

        self._loading_percent = ctk.CTkLabel(
            loading_center,
            text="0%",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._loading_percent.grid(row=3, column=0)

        self._loading_cancel_btn = ctk.CTkButton(
            loading_center,
            text="Cancel",
            width=120,
            fg_color="#8B2E2E",
            hover_color="#A33",
            command=self._on_cancel_operation,
        )
        self._loading_cancel_btn.grid(row=4, column=0, pady=(16, 0))

        self._loading_frame.grid_remove()

        self._progress_label = self._loading_detail
        self._progress_bar = self._loading_bar
        self._last_tabview_height = 0
        self.after(200, self._sync_tabview_height)

    def _on_results_shell_resize(self, event: tk.Event) -> None:
        if getattr(event, "widget", None) is not self._results_shell:
            return
        self._sync_tabview_height(event.height)

    def _sync_tabview_height(self, shell_height: Optional[int] = None) -> None:
        """CTkTabview does not always expand vertically with grid; size it to the shell."""
        if not self._ui_is_active() or self._content_tabview is None or self._results_shell is None:
            return
        try:
            height = shell_height if shell_height is not None else self._results_shell.winfo_height()
            target = max(320, int(height) - 4)
            if target == self._last_tabview_height:
                return
            self._last_tabview_height = target
            self._content_tabview.configure(height=target)
        except tk.TclError:
            pass

    def _tk_preview_bg(self) -> str:
        return ctk.ThemeManager.theme["CTkFrame"]["fg_color"][
            1 if ctk.get_appearance_mode() == "Dark" else 0
        ]

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._busy_sensitive_widgets:
            try:
                widget.configure(state=state)
            except (tk.TclError, AttributeError):
                pass

    def _show_loading_page(self, title: str, detail: str = "") -> None:
        self._busy_operation = title
        self._loading_max_fraction = 0.0
        self._cancel_requested.clear()
        if self._content_tabview is not None:
            self._content_tabview.grid_remove()
        self._loading_frame.grid()
        self._loading_title.configure(text=title)
        self._loading_detail.configure(text=detail or "Starting…", text_color="gray")
        self._loading_bar.set(0)
        self._loading_percent.configure(text="0%")
        if self._loading_cancel_btn is not None:
            self._loading_cancel_btn.configure(state="normal")
        self._set_controls_enabled(False)
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _update_loading_progress(self, fraction: float, detail: str) -> None:
        if not self._ui_is_active():
            return
        try:
            self._loading_max_fraction = max(self._loading_max_fraction, fraction)
            clamped = min(1.0, max(0.0, self._loading_max_fraction))
            self._loading_bar.set(clamped)
            self._loading_percent.configure(text=f"{int(clamped * 100)}%")
            if detail:
                self._loading_detail.configure(text=detail)
        except tk.TclError:
            pass

    def _hide_loading_page(self) -> None:
        self._busy_operation = None
        self._cancel_requested.clear()
        try:
            self._loading_frame.grid_remove()
            if self._content_tabview is not None:
                self._content_tabview.grid()
            self._loading_detail.configure(text_color="gray")
            if self._loading_cancel_btn is not None:
                self._loading_cancel_btn.configure(state="normal")
        except tk.TclError:
            pass
        self._set_controls_enabled(True)

    def _on_cancel_operation(self) -> None:
        if not self._is_busy():
            return
        self._cancel_requested.set()
        self._active_operation_id += 1
        self._worker_thread = None
        self._del_build_show_loading = False
        try:
            if self._loading_cancel_btn is not None:
                self._loading_cancel_btn.configure(state="disabled")
        except tk.TclError:
            pass
        self._hide_loading_page()
        self._update_action_states()
        if self._pedigree_status_label is not None:
            try:
                self._pedigree_status_label.configure(
                    text="Operation cancelled.",
                    text_color="#D29922",
                )
            except tk.TclError:
                pass
        logger.info("Library Analysis operation cancelled by user")

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise LibraryOperationCancelled()

    def _thread_loading_progress(self, fraction: float, status: str) -> None:
        self._raise_if_cancelled()
        self._schedule_on_main(self._update_loading_progress, fraction, status)

    def _library_entry_count(self) -> int:
        if self._cached_scan is not None:
            return self._cached_scan.entries_attempted
        if self._data_store is not None:
            return self._data_store.get_compound_count()
        return 0

    def _selected_signal_metric_ids(self) -> List[str]:
        return [mid for mid in self._get_selected_metric_ids() if mid in SIGNAL_QUALITY_METRIC_IDS]

    def _selected_signal_plot_ids(self) -> List[str]:
        signal_ids = {
            p.plot_id
            for p in list_library_plot_definitions_by_category("signal")
        }
        return [pid for pid in self._get_selected_plot_ids() if pid in signal_ids]

    def _signal_quality_is_cached(
        self,
        channels: List[str],
        alpha: float,
        *,
        min_prominence: float = 0.0,
        min_pct_area: float = 0.0,
    ) -> bool:
        scan = self._cached_scan
        if scan is None or scan.signal_quality_alpha is None:
            return False
        if abs(scan.signal_quality_alpha - alpha) >= 1e-12:
            return False
        if (scan.signal_quality_min_prominence or 0.0) != min_prominence:
            return False
        if (scan.signal_quality_min_pct_area or 0.0) != min_pct_area:
            return False
        return all(ch in scan.signal_quality_by_channel for ch in channels)

    def _confirm_long_operation(self, message: str) -> bool:
        return bool(
            messagebox.askyesno(
                "Library Analysis — long operation",
                message,
                icon="warning",
                parent=self,
            )
        )

    def _confirm_library_scan(self, entry_count: int) -> bool:
        overwrite_note = ""
        if self._cached_scan is not None:
            loaded = self._scan_entry_count(self._cached_scan)
            overwrite_note = (
                f"A library scan is already loaded ({loaded:,} entries parsed). "
                "Running a new scan will replace it and discard metrics, plots, and "
                "other results that depend on the current scan.\n\n"
            )
        index_note = (
            "Index databases parse raw chromatogram text for each entry, so this step "
            "is often the slowest part of a session.\n\n"
            if self._index_db_mode
            else ""
        )
        return self._confirm_long_operation(
            f"This will scan {entry_count:,} library entries across the selected "
            f"count channel(s).\n\n"
            f"{overwrite_note}"
            f"{index_note}"
            "Large libraries can take several minutes. You can cancel while the scan "
            "runs, but partial results will be discarded.\n\n"
            "Continue?"
        )

    def _confirm_metrics_computation(self, entry_count: int, metric_ids: List[str]) -> bool:
        signal_metrics = [mid for mid in metric_ids if mid in SIGNAL_QUALITY_METRIC_IDS]
        channels = self._get_selected_channels()
        alpha = self._parse_signal_alpha()
        min_prominence, min_pct_area = self._peek_peak_quality_params()
        if signal_metrics and alpha is not None and self._signal_quality_is_cached(
            channels,
            alpha,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
        ):
            signal_note = (
                "Signal metrics are selected, but per-entry peak analysis was already "
                "computed for the current scan and α — aggregation should be relatively quick.\n\n"
            )
        elif signal_metrics:
            signal_note = (
                "Signal metrics are selected. This includes per-entry peak analysis across "
                f"{entry_count:,} entries and may take a long time.\n\n"
            )
        else:
            signal_note = (
                "Coverage-only metrics aggregate the existing scan and are usually faster "
                "than signal metrics.\n\n"
            )
        return self._confirm_long_operation(
            f"Calculate {len(metric_ids)} metric(s) for {entry_count:,} scanned entries?\n\n"
            f"{signal_note}"
            "You can cancel while this runs; previously calculated metrics in this "
            "session will be kept.\n\n"
            "Continue?"
        )

    def _confirm_plot_generation(self, entry_count: int, plot_ids: List[str]) -> bool:
        signal_plots = self._selected_signal_plot_ids()
        channels = self._get_selected_channels()
        alpha = self._parse_signal_alpha()
        min_prominence, min_pct_area = self._peek_peak_quality_params()
        if signal_plots and alpha is not None and self._signal_quality_is_cached(
            channels,
            alpha,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
        ):
            signal_note = (
                "Signal plots are selected, but per-entry peak analysis is already cached "
                "from metrics or a prior plot run — rendering should be faster.\n\n"
            )
        elif signal_plots:
            signal_note = (
                "Signal plots are selected. Peak analysis runs across "
                f"{entry_count:,} entries before rendering and may take a long time.\n\n"
            )
        else:
            signal_note = (
                "Coverage plots use the existing scan only and are usually the quickest "
                "plots to generate.\n\n"
            )
        return self._confirm_long_operation(
            f"Generate {len(plot_ids)} plot type(s) for {len(channels)} channel(s)?\n\n"
            f"{signal_note}"
            "You can cancel while this runs; plots already on screen will be kept.\n\n"
            "Continue?"
        )

    def _expected_report_plot_keys(self) -> Set[Tuple[str, str]]:
        return {
            (plot_id, channel)
            for plot_id in self._get_selected_plot_ids()
            for channel in self._get_selected_channels()
        }

    def _peek_pedigree_settings(self) -> Optional[AnalysisSettings]:
        """Read pedigree fields without validation dialogs (for cache checks)."""
        if self._config is None:
            return None
        channel = self._pedigree_channel_var.get().strip()
        if not channel:
            return None
        try:
            tolerance = float(self._pedigree_tolerance_var.get().strip())
            alpha = float(self._pedigree_alpha_var.get().strip())
            gaussian_min_height_factor = float(self._pedigree_gaussian_height_var.get().strip())
            gaussian_fit_width = float(self._pedigree_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(self._pedigree_gaussian_stddev_var.get().strip())
            gaussian_minimum_rt = float(self._pedigree_gaussian_min_rt_var.get().strip())
        except ValueError:
            return None
        if tolerance <= 0 or alpha <= 0 or alpha >= 1:
            return None
        time_unit = self._pedigree_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            return None
        min_prominence, min_pct_area = self._peek_peak_quality_params()
        algorithm = self._pedigree_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            return None
        stored_unit = (
            "minutes" if self._config.analysis_time_unit == "minutes" else "seconds"
        )
        return AnalysisSettings(
            count_channel=channel,
            time_unit=time_unit,  # type: ignore[arg-type]
            chromatogram_time_unit=stored_unit,  # type: ignore[arg-type]
            peak_picking_algorithm=algorithm,  # type: ignore[arg-type]
            alpha=alpha,
            tolerance=tolerance,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            selected_variants=None,
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _report_session(self) -> LibraryReportSession:
        """Collect optional session artifacts available for PDF assembly."""
        assert self._db_path is not None
        scan = self._cached_scan
        return LibraryReportSession(
            database_path=str(self._db_path.resolve()),
            database_name=self._db_path.name,
            database_kind="index" if self._index_db_mode else "full",
            scan_entries_used=scan.entries_used if scan is not None else 0,
            scan_entries_attempted=scan.entries_attempted if scan is not None else 0,
            scan_entries_skipped=scan.entries_skipped if scan is not None else 0,
            qc_metrics=self._qc_metrics_artifact,
            qc_plots=self._qc_plots_artifact,
            rt_assignment=self._rt_assignment_artifact,
            pedigree_viz=self._pedigree_viz_artifact,
            splittree_viz=self._splittree_artifact,
        )

    def _session_has_report_artifacts(self) -> bool:
        return bool(self._report_session().available_section_keys())

    def _capture_qc_metrics_artifact(self, snapshot: LibraryComputationSnapshot) -> None:
        metric_ids = self._get_selected_metric_ids()
        channels = self._get_selected_channels()
        self._qc_metrics_artifact = LibraryQcMetricsArtifact(
            generated_at=snapshot.processed_at,
            snapshot=snapshot,
            metric_ids=list(metric_ids),
            channels=list(channels),
        )

    def _capture_qc_plots_artifact(
        self,
        plots: List[PlotResult],
        plot_ids: List[str],
    ) -> None:
        from datetime import timezone

        channels = self._get_selected_channels()
        self._qc_plots_artifact = LibraryQcPlotsArtifact(
            generated_at=datetime.now(timezone.utc),
            plot_results=list(plots),
            plot_ids=list(plot_ids),
            channels=list(channels),
        )

    def _picker_label(self) -> str:
        picker = self._pedigree_picker_algorithm_var.get()
        return "old-school Gaussian" if picker == "old_school" else "modern NB"

    def _capture_rt_assignment_artifact(
        self,
        data: DelCycleTreeData,
        *,
        analysis_mode: str,
        settings: AnalysisSettings,
        isoform: str,
    ) -> None:
        from datetime import timezone

        self._rt_assignment_artifact = RtAssignmentReportArtifact(
            generated_at=datetime.now(timezone.utc),
            analysis_mode=analysis_mode,
            settings=settings,
            channel=settings.count_channel,
            time_unit=str(settings.time_unit),
            isoform=isoform,
            rt_source=data.rt_source,
            rt_threshold=float(data.rt_threshold),
            n_products=len(data.verified_sequences),
            n_verified=data.n_verified,
            n_rt_from_pedigree=data.n_rt_from_pedigree,
            n_rt_from_peak_pick=data.n_rt_from_peak_pick,
            n_rt_from_metadata=data.n_rt_from_metadata,
            peak_picking_algorithm=data.peak_picking_algorithm or self._picker_label(),
        )

    def _capture_pedigree_viz_artifact(self, result: PedigreeAnalysisResult) -> None:
        if self._db_path is None:
            return
        from datetime import timezone

        from src.core.library_report_assets import (
            build_pedigree_tier_report_figure,
            session_report_assets_dir,
        )

        tree_opts = self._pedigree_tree_render_options()
        tier_path, tier_caption = build_pedigree_tier_report_figure(
            result,
            tree_opts=tree_opts,
            output_dir=session_report_assets_dir(self._db_path),
        )
        self._pedigree_viz_artifact = PedigreeVizReportArtifact(
            generated_at=datetime.now(timezone.utc),
            image_path=tier_path,
            caption=tier_caption,
            tree_opts=tree_opts,
            n_nodes=len(result.records),
            n_chromatograms=result.n_chromatograms,
            backend_name=result.backend_name,
            tree_render_engine=result.tree_render_engine or "",
        )

    def _capture_splittree_artifact(
        self,
        data: DelCycleTreeData,
        figure: object,
        *,
        isoform: str,
        selected_branch: str,
    ) -> None:
        if self._db_path is None:
            return
        from datetime import timezone

        from src.core.library_report_assets import save_report_figure, session_report_assets_dir

        view_mode = self._splittree_view_mode_var.get()
        branch_mode = view_mode == _SPLITTREE_VIEW_BRANCH
        assets = session_report_assets_dir(self._db_path)
        image_path = assets / (
            f"splittree_branch_{selected_branch or 'unknown'}.png"
            if branch_mode
            else "splittree_full.png"
        )
        save_report_figure(figure, image_path)
        metadata_mode = self._splittree_rt_source_var.get() == _SPLITTREE_RT_METADATA
        rt_source = "metadata" if metadata_mode else "session"
        rt_column = (
            self._splittree_metadata_rt_column_var.get().strip()
            if metadata_mode
            else ""
        )
        verified_column = (
            self._splittree_metadata_verified_column_var.get().strip()
            if metadata_mode
            else ""
        )
        caption = (
            f"Split-tree — {data.n_verified:,} verified of "
            f"{len(data.verified_sequences):,} products "
            f"(RT source: {data.rt_source}, null RT threshold {data.rt_threshold:g})."
        )
        self._splittree_artifact = SplittreeVizReportArtifact(
            generated_at=datetime.now(timezone.utc),
            image_path=image_path,
            caption=caption,
            rt_source=rt_source,
            rt_column=rt_column,
            verified_column=verified_column,
            isoform=isoform,
            view_mode=view_mode,
            branch_bb1=selected_branch if branch_mode else "",
            color_mode=self._del_tree_color_mode(),
            color_by_rt=bool(self._pedigree_del_color_rt_var.get()),
            pass_pct_cutoff=self._read_del_tree_pass_pct_cutoff(),
            rt_threshold=float(data.rt_threshold),
            del_rt_source=data.rt_source,
            n_verified=data.n_verified,
            n_products=len(data.verified_sequences),
        )

    def _assess_report_prerequisites(
        self,
        report_options: LibraryReportOptions,
    ) -> LibraryReportPrerequisites:
        missing = missing_report_sections(report_options, self._report_session())
        return LibraryReportPrerequisites(missing_sections=missing)

    def _build_report_section_statuses(self) -> List[LibraryReportSectionStatus]:
        session = self._report_session()
        metrics = session.qc_metrics
        plots = session.qc_plots
        rt_assignment = session.rt_assignment
        pedigree_viz = session.pedigree_viz
        splittree = session.splittree_viz
        metric_ids = metrics.metric_ids if metrics is not None else []
        plot_ids = plots.plot_ids if plots is not None else []
        channels = metrics.channels if metrics is not None else (
            plots.channels if plots is not None else []
        )
        return [
            LibraryReportSectionStatus(
                key="metrics",
                label="Summary metrics",
                selected=metrics is not None,
                ready=metrics is not None,
                detail=(
                    f"{len(metric_ids)} metric(s) across {len(channels)} channel(s) — "
                    f"captured {self._format_report_time(metrics.generated_at)}."
                    if metrics is not None
                    else "Run Calculate metrics on the Metrics tab first."
                ),
                item_ids=list(metric_ids),
                channels=list(channels),
            ),
            LibraryReportSectionStatus(
                key="plots",
                label="Visualizations",
                selected=plots is not None,
                ready=plots is not None,
                detail=(
                    f"{len(plot_ids)} plot type(s) across {len(plots.channels)} channel(s) — "
                    f"captured {self._format_report_time(plots.generated_at)}."
                    if plots is not None
                    else "Run Generate plots on the Plots tab first."
                ),
                item_ids=list(plot_ids),
                channels=list(plots.channels) if plots is not None else [],
            ),
            LibraryReportSectionStatus(
                key="rt_assignment",
                label="RT assignment",
                selected=rt_assignment is not None,
                ready=rt_assignment is not None,
                detail=(
                    f"{rt_assignment.analysis_mode.replace('_', ' ')} mode — "
                    f"{rt_assignment.n_verified:,} verified products, "
                    f"captured {self._format_report_time(rt_assignment.generated_at)}."
                    if rt_assignment is not None
                    else "Run RT assignment on the RT assignment tab first."
                ),
            ),
            LibraryReportSectionStatus(
                key="pedigree_viz",
                label="Pedigree visualization",
                selected=pedigree_viz is not None,
                ready=pedigree_viz is not None,
                detail=(
                    f"Tier-ring — {pedigree_viz.n_nodes:,} nodes, "
                    f"captured {self._format_report_time(pedigree_viz.generated_at)}."
                    if pedigree_viz is not None
                    else "Run pedigree RT assignment to capture the tier-ring figure."
                ),
            ),
            LibraryReportSectionStatus(
                key="splittree",
                label="Split-tree visualization",
                selected=splittree is not None,
                ready=splittree is not None,
                detail=(
                    f"{splittree.view_mode} view ({splittree.rt_source} RT source) — "
                    f"captured {self._format_report_time(splittree.generated_at)}."
                    if splittree is not None
                    else "Click Generate plot on the Split-tree visualization tab first."
                ),
            ),
        ]

    def _build_report_audit_trail(
        self,
        report_options: LibraryReportOptions,
        session: LibraryReportSession,
    ) -> LibraryReportAuditTrail:
        assert self._db_path is not None
        min_prominence, min_pct_area = self._peek_peak_quality_params()
        metrics = session.qc_metrics
        rt_assignment = session.rt_assignment
        pedigree_viz = session.pedigree_viz
        splittree = session.splittree_viz
        tree_opts = pedigree_viz.tree_opts if pedigree_viz is not None else self._pedigree_tree_render_options()
        return LibraryReportAuditTrail(
            generated_at=datetime.now(timezone.utc),
            database_path=str(self._db_path.resolve()),
            database_name=self._db_path.name,
            database_kind="index" if self._index_db_mode else "full",
            report_options=report_options,
            fraction_count=(
                metrics.snapshot.fraction_count
                if metrics is not None
                else self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
            ),
            signal_quality_alpha=(
                metrics.snapshot.signal_quality_alpha
                if metrics is not None
                else self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA
            ),
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            pedigree_channel=(
                rt_assignment.channel if rt_assignment is not None
                else self._pedigree_channel_var.get().strip()
            ),
            pedigree_time_unit=(
                rt_assignment.time_unit if rt_assignment is not None
                else self._pedigree_time_unit_var.get()
            ),
            pedigree_tolerance=(
                rt_assignment.rt_threshold if rt_assignment is not None
                else float(self._pedigree_tolerance_var.get().strip() or "0")
            ),
            pedigree_alpha=float(self._pedigree_alpha_var.get().strip() or "0"),
            pedigree_peak_picker=self._picker_label(),
            pedigree_isoform=rt_assignment.isoform if rt_assignment is not None else "All",
            pedigree_max_display_tier=tree_opts.max_display_tier,
            pedigree_include_failed=tree_opts.include_failed,
            pedigree_show_rt=tree_opts.show_rt,
            rt_analysis_mode=rt_assignment.analysis_mode if rt_assignment is not None else "",
            splittree_rt_source=splittree.rt_source if splittree is not None else "",
            splittree_rt_column=splittree.rt_column if splittree is not None else "",
            splittree_verified_column=splittree.verified_column if splittree is not None else "",
            splittree_isoform=splittree.isoform if splittree is not None else "All",
            splittree_view_mode=splittree.view_mode if splittree is not None else "",
            del_color_mode=splittree.color_mode if splittree is not None else self._del_tree_color_mode(),
            del_color_by_rt=splittree.color_by_rt if splittree is not None else bool(
                self._pedigree_del_color_rt_var.get()
            ),
            del_rt_threshold=splittree.rt_threshold if splittree is not None else 0.0,
            del_rt_source=splittree.del_rt_source if splittree is not None else "",
        )

    def _confirm_report_export(
        self,
        pdf_path: Path,
        report_options: LibraryReportOptions,
    ) -> bool:
        sections = []
        if report_options.include_metrics:
            sections.append(f"Summary metrics ({len(report_options.metric_ids)})")
        if report_options.include_plots:
            sections.append(f"Visualizations ({len(report_options.plot_ids)})")
        if report_options.include_rt_assignment:
            sections.append("RT assignment")
        if report_options.include_pedigree_viz:
            sections.append("Pedigree visualization")
        if report_options.include_splittree:
            sections.append("Split-tree visualization")
        return self._confirm_long_operation(
            "\n".join(
                [
                    f"Save library report to:\n{pdf_path}\n",
                    "Sections: " + ", ".join(sections),
                    "\nThe PDF will embed session artifacts you already generated. Continue?",
                ]
            )
        )

    def _on_export_report(self) -> None:
        if self._is_busy():
            return
        if self._data_store is not None and self._data_store.get_compound_count() == 0:
            messagebox.showinfo(
                "Library Analysis",
                "The database has no compounds to report on.",
                parent=self,
            )
            return
        if not self._session_has_report_artifacts():
            messagebox.showinfo(
                "Generate report",
                "No report sections are ready yet.\n\n"
                "Run library scan, metrics, plots, RT assignment, or split-tree steps "
                "in this session, then return here to assemble a PDF.",
                parent=self,
            )
            return

        session = self._report_session()
        default_options = LibraryReportOptions(
            include_metrics=session.qc_metrics is not None,
            include_plots=session.qc_plots is not None,
            include_rt_assignment=session.rt_assignment is not None,
            include_pedigree_viz=session.pedigree_viz is not None,
            include_splittree=session.splittree_viz is not None,
            metric_ids=list(session.qc_metrics.metric_ids) if session.qc_metrics else [],
            plot_ids=list(session.qc_plots.plot_ids) if session.qc_plots else [],
            channels=list(
                dict.fromkeys(
                    [
                        *(session.qc_metrics.channels if session.qc_metrics else []),
                        *(session.qc_plots.channels if session.qc_plots else []),
                    ]
                )
            ),
        )
        prerequisites = self._assess_report_prerequisites(default_options)
        section_statuses = self._build_report_section_statuses()

        def on_dialog_confirm(result: LibraryReportDialogResult) -> None:
            self._continue_report_export(result)

        show_library_report_dialog(
            self,
            section_statuses=section_statuses,
            prerequisites=prerequisites,
            on_confirm=on_dialog_confirm,
            reassess=self._assess_report_prerequisites,
        )

    def _continue_report_export(self, dialog_result: LibraryReportDialogResult) -> None:
        report_options = dialog_result.options
        prerequisites = self._assess_report_prerequisites(report_options)
        if prerequisites.missing_sections:
            messagebox.showinfo(
                "Generate report",
                "Some selected sections are not available yet:\n\n"
                + "\n".join(f"• {note}" for note in prerequisites.missing_sections),
                parent=self,
            )
            return

        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export library report",
            defaultextension=".pdf",
            filetypes=[("PDF document", "*.pdf")],
        )
        if not dest:
            return
        pdf_path = Path(dest)
        if not self._confirm_report_export(pdf_path, report_options):
            return
        self._start_report_export(pdf_path, report_options)

    def _start_report_export(
        self,
        pdf_path: Path,
        report_options: LibraryReportOptions,
    ) -> None:
        assert self._db_path is not None
        session = self._report_session()
        audit = self._build_report_audit_trail(report_options, session)
        snapshot = build_report_snapshot(session)
        plot_results = (
            list(session.qc_plots.plot_results)
            if report_options.include_plots and session.qc_plots is not None
            else []
        )
        rt_assignment = session.rt_assignment if report_options.include_rt_assignment else None
        pedigree_viz = session.pedigree_viz if report_options.include_pedigree_viz else None
        splittree_viz = session.splittree_viz if report_options.include_splittree else None
        del_data = (
            self._splittree_viz_data or self._del_cycle_tree_data
            if report_options.include_splittree
            else None
        )
        db_path = self._db_path
        splittree_color_mode = (
            splittree_viz.color_mode if splittree_viz is not None else self._del_tree_color_mode()
        )
        splittree_color_by_rt = (
            splittree_viz.color_by_rt
            if splittree_viz is not None
            else bool(self._pedigree_del_color_rt_var.get())
        )
        splittree_pass_pct = (
            splittree_viz.pass_pct_cutoff
            if splittree_viz is not None
            else self._read_del_tree_pass_pct_cutoff()
        )
        splittree_shows_full = (
            splittree_viz.view_mode.strip().lower() in ("full tree", "full")
            if splittree_viz is not None
            else True
        )

        self._show_loading_page("Exporting library report", "Writing PDF…")
        self._update_action_states()

        def worker() -> None:
            try:
                self._thread_loading_progress(0.35, "Rendering split-tree figures for report…")
                pedigree_figures = None
                if del_data is not None and report_options.include_splittree:
                    assets_dir = session_report_assets_dir(db_path) / "del_cycle_report"
                    pedigree_figures = build_del_cycle_report_figures(
                        del_data,
                        del_color_mode=splittree_color_mode,
                        del_color_by_rt=splittree_color_by_rt,
                        del_pass_pct_cutoff=splittree_pass_pct,
                        output_dir=assets_dir,
                        include_full_tree=not splittree_shows_full,
                    )
                self._thread_loading_progress(0.65, "Writing PDF report…")
                generate_library_report_pdf(
                    snapshot,
                    pdf_path,
                    plot_results=plot_results,
                    report_options=report_options,
                    audit=audit,
                    rt_assignment=rt_assignment,
                    pedigree_viz=pedigree_viz,
                    splittree_viz=splittree_viz,
                    pedigree_figures=pedigree_figures,
                )
                self._bind_worker_callback(
                    self._on_report_export_ready,
                    str(pdf_path.resolve()),
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library report export failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _on_report_export_ready(self, pdf_path: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._update_loading_progress(1.0, f"Report saved: {pdf_path}")

        def finish() -> None:
            if not self._ui_is_active():
                return
            self._hide_loading_page()
            self._update_action_states()
            messagebox.showinfo(
                "Library Analysis",
                f"Library report saved to:\n{pdf_path}",
                parent=self,
            )

        self.after(30, finish)

    @staticmethod
    def _format_report_time(when: datetime) -> str:
        if when.tzinfo is None:
            return when.strftime("%Y-%m-%d %H:%M")
        return when.astimezone().strftime("%Y-%m-%d %H:%M")


    def _on_worker_cancelled(self) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._worker_busy = False
        self._del_build_show_loading = False
        self._hide_loading_page()
        self._update_action_states()
        if self._pedigree_status_label is not None:
            try:
                self._pedigree_status_label.configure(
                    text="Operation cancelled.",
                    text_color="#D29922",
                )
            except tk.TclError:
                pass
        logger.info("Library Analysis background worker acknowledged cancel")

    def _start_worker(self, worker: Callable[[], None]) -> None:
        self._cancel_requested.clear()
        self._active_operation_id += 1
        self._worker_op_id = self._active_operation_id
        self._worker_busy = True

        def wrapped() -> None:
            try:
                worker()
            except LibraryOperationCancelled:
                self._schedule_on_main(self._on_worker_cancelled)

        self._worker_thread = threading.Thread(target=wrapped, daemon=True)
        self._worker_thread.start()

    def _focus_tab(self, tab_name: str) -> None:
        if self._content_tabview is None:
            return
        try:
            self._content_tabview.set(tab_name)
            self._show_sidebar_for_tab(tab_name)
        except (tk.TclError, ValueError):
            pass

    def _get_selected_channels(self) -> List[str]:
        return [name for name, var in self._channel_vars.items() if var.get()]

    def _get_selected_plot_ids(self) -> List[str]:
        return [pid for pid, var in self._plot_vars.items() if var.get()]

    def _get_selected_metric_ids(self) -> List[str]:
        return [mid for mid, var in self._metric_vars.items() if var.get()]

    def _parse_fraction_count(self) -> Optional[int]:
        raw = self._fraction_count_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Fraction count must be a positive integer.",
                parent=self,
            )
            return None
        if value <= 0:
            messagebox.showerror(
                "Library Analysis",
                "Fraction count must be greater than zero.",
                parent=self,
            )
            return None
        return value

    def _parse_signal_alpha(self) -> Optional[float]:
        raw = self._signal_alpha_var.get().strip()
        try:
            value = float(raw)
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Peak significance α must be a number (e.g. 0.001).",
                parent=self,
            )
            return None
        if value <= 0.0 or value >= 1.0:
            messagebox.showerror(
                "Library Analysis",
                "Peak significance α must be between 0 and 1 (exclusive).",
                parent=self,
            )
            return None
        return value

    def _parse_peak_quality_params(self) -> Optional[tuple[float, float]]:
        try:
            min_prominence = float(self._signal_min_prominence_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Min prominence must be a number (0 = off).",
                parent=self,
            )
            return None
        try:
            min_pct_area = float(self._signal_min_pct_area_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Min % area must be a number (0 = off).",
                parent=self,
            )
            return None
        if min_prominence < 0:
            messagebox.showerror(
                "Library Analysis",
                "Min prominence must be >= 0.",
                parent=self,
            )
            return None
        if min_pct_area < 0 or min_pct_area > 100:
            messagebox.showerror(
                "Library Analysis",
                "Min % area must be between 0 and 100.",
                parent=self,
            )
            return None
        return min_prominence, min_pct_area

    def _peek_peak_quality_params(self) -> tuple[float, float]:
        """Read peak quality fields without validation dialogs (for cache checks)."""
        try:
            min_prominence = float(self._signal_min_prominence_var.get().strip())
            min_pct_area = float(self._signal_min_pct_area_var.get().strip())
        except ValueError:
            return 0.0, 0.0
        if min_prominence < 0 or min_pct_area < 0 or min_pct_area > 100:
            return 0.0, 0.0
        return min_prominence, min_pct_area

    def _is_busy(self) -> bool:
        if self._worker_busy:
            return True
        if self._worker_thread is None:
            return False
        return self._worker_thread.is_alive()

    def _update_action_states(self) -> None:
        if not self._ui_is_active():
            return
        has_channels = bool(self._get_selected_channels())
        has_metrics = bool(self._get_selected_metric_ids())
        busy = self._is_busy()
        has_scan = self._cached_scan is not None
        has_scan_cache = has_scan or any_session_scan_exists()
        has_plots = bool(self._get_selected_plot_ids()) and has_channels
        try:
            scan_enabled = has_channels and not busy
            self._scan_btn.configure(
                state="normal" if scan_enabled else "disabled",
                fg_color="gray40" if has_scan else "#238636",
                hover_color="gray50" if has_scan else "#2ea043",
                font=ctk.CTkFont(size=14) if has_scan else _primary_action_font(),
            )
            self._clear_scan_btn.configure(
                state="normal" if has_scan_cache and not busy else "disabled"
            )
            self._export_scan_btn.configure(
                state="normal" if has_scan and not busy else "disabled"
            )
            self._import_scan_btn.configure(
                state="normal" if not busy else "disabled"
            )
            self._metrics_btn.configure(
                state="normal" if has_scan and has_metrics and not busy else "disabled"
            )
            self._plots_btn.configure(
                state="normal" if has_scan and has_plots and not busy else "disabled"
            )
            self._save_btn.configure(
                state="normal" if self._current_snapshot is not None and not busy else "disabled"
            )
            self._plots_save_btn.configure(
                state="normal" if self._current_snapshot is not None and not busy else "disabled"
            )
            latest = get_latest_snapshot_path(self._db_path) if self._db_path else None
            load_state = "normal" if latest is not None and not busy else "disabled"
            self._load_last_btn.configure(state=load_state)
            self._plots_load_btn.configure(state=load_state)
            self._browse_btn.configure(state="normal" if not busy else "disabled")
            self._plots_browse_btn.configure(state="normal" if not busy else "disabled")
            export_plot_csv_state = (
                "normal" if has_scan and has_channels and not busy else "disabled"
            )
            self._export_plots_csv_btn.configure(state=export_plot_csv_state)
            has_plot_files = any(
                p.image_path is not None and p.image_path.is_file() for p in self._plot_results
            )
            self._open_plots_folder_btn.configure(
                state="normal" if has_plot_files and not busy else "disabled"
            )
            self._export_all_plots_btn.configure(
                state="normal" if has_plot_files and not busy else "disabled"
            )
            has_metrics = bool(
                self._current_snapshot is not None
                and self._current_snapshot.metric_results
            )
            self._export_metrics_csv_btn.configure(
                state="normal" if has_metrics and not busy else "disabled"
            )
            saved_snapshot_count = len(list_snapshots())
            self._clear_metrics_results_btn.configure(
                state="normal" if saved_snapshot_count > 0 and not busy else "disabled"
            )
            has_report_content = self._session_has_report_artifacts()
            self._export_report_btn.configure(
                state="normal" if has_report_content and not busy else "disabled"
            )
            pedigree_ready = (
                self._config is not None
                and self._config.pedigree_configured()
                and pedigree_backend_available()
            )
            n_compounds = (
                self._data_store.get_compound_count() if self._data_store is not None else 0
            )
            rt_ready = (
                self._pedigree_result is not None or self._del_cycle_tree_data is not None
            )
            rt_can_run = (
                n_compounds > 0
                and self._config is not None
                and self._config.pedigree_configured()
                and not busy
            )
            pedigree_mode = self._rt_analysis_mode_var.get() == _RT_ANALYSIS_PEDIGREE
            if pedigree_mode:
                rt_can_run = rt_can_run and has_scan and pedigree_ready
            self._rt_assignment_run_btn.configure(
                state="normal" if rt_can_run else "disabled"
            )
            has_pedigree = self._pedigree_result is not None
            latest_ped = (
                get_latest_pedigree_snapshot_path(self._db_path) if self._db_path else None
            )
            self._pedigree_load_btn.configure(
                state="normal" if latest_ped is not None and not busy else "disabled"
            )
            self._pedigree_browse_btn.configure(
                state="normal" if not busy else "disabled"
            )
            tree_path = (
                self._pedigree_result.tree_image_path
                if self._pedigree_result is not None
                else None
            )
            has_tree = tree_path is not None and Path(tree_path).is_file()
            ped_export_state = "normal" if has_pedigree and not busy else "disabled"
            self._pedigree_export_csv_btn.configure(state=ped_export_state)
            has_del_tree = self._del_cycle_tree_data is not None
            self._pedigree_export_del_csv_btn.configure(
                state="normal" if has_del_tree and not busy else "disabled"
            )
            self._export_rts_btn.configure(
                state="normal" if rt_ready and not busy else "disabled"
            )
            self._pedigree_save_btn.configure(state=ped_export_state)
            self._pedigree_export_tree_btn.configure(
                state="normal" if has_tree and not busy else "disabled"
            )
            if self._pedigree_status_label is not None and self._pedigree_result is None and not busy:
                pedigree_mode = self._rt_analysis_mode_var.get() == _RT_ANALYSIS_PEDIGREE
                if pedigree_mode and not has_scan:
                    self._pedigree_status_label.configure(
                        text="Run library scan first (top bar). Pedigree requires a scan.",
                        text_color="gray",
                    )
                elif not has_scan and not pedigree_mode:
                    hint = self._pedigree_status_label.cget("text")
                    if hint.startswith("Run library scan") or hint == "No pedigree run yet.":
                        self._pedigree_status_label.configure(
                            text=(
                                "Direct pick reads chromatograms from the database. "
                                "Run library scan first to reuse parsed traces (faster)."
                            ),
                            text_color="gray",
                        )
                elif has_scan:
                    hint = self._pedigree_status_label.cget("text")
                    if hint.startswith("Run library scan") or hint.startswith("Direct pick reads"):
                        self._pedigree_status_label.configure(
                            text=(
                                "Scan ready. Configure options, then run RT assignment."
                            ),
                            text_color="gray",
                        )
        except tk.TclError:
            pass

    def _clear_frame_children(self, frame: Optional[ctk.CTkScrollableFrame]) -> None:
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()

    def _clear_metrics_view(self) -> None:
        self._clear_frame_children(self._metrics_frame)

    def _clear_plots_view(self) -> None:
        self._plot_photo = None
        self._selected_plot_index = None
        self._plot_list_buttons.clear()
        self._clear_frame_children(self._plot_list_frame)
        if self._plot_preview_tk is not None:
            self._plot_preview_tk.configure(image="", text="No plot selected")
        if self._plot_preview_title is not None:
            self._plot_preview_title.configure(text="Select a plot from the list")
        if self._plot_preview_help is not None:
            self._plot_preview_help.configure(text="")
        try:
            self._plot_export_btn.configure(state="disabled")
        except (tk.TclError, AttributeError):
            pass

    def _clear_results(self) -> None:
        self._clear_metrics_view()
        self._clear_plots_view()

    def _show_empty_library_message(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._metrics_frame,
            "No data",
            "Build or load a database that contains at least one compound.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)
        self._scan_btn.configure(state="disabled")
        self._metrics_btn.configure(state="disabled")
        self._plots_btn.configure(state="disabled")

    def _show_idle_placeholder(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._metrics_frame,
            "Ready",
            "Select count channels in the sidebar, then click Run library scan "
            "in the top bar. After the scan completes, use Calculate metrics and/or "
            "Generate plots from the same parsed scan.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)
        self._update_plots_summary([])

    def _show_scan_ready_placeholder(self, scan: LibraryScanData) -> None:
        self._clear_metrics_view()
        card = self._make_info_card(
            self._metrics_frame,
            "Scan complete",
            (
                f"Parsed {scan.entries_used:,} of {scan.entries_attempted:,} entries "
                f"({scan.entries_skipped:,} skipped). "
                "Select metrics and click Calculate metrics, or select plots and "
                "open the Visualizations tab."
            ),
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)

    def _on_run_library_scan(self) -> None:
        if self._is_busy():
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        if self._data_store is None or self._data_store.get_compound_count() == 0:
            self._show_empty_library_message()
            return
        entry_count = self._data_store.get_compound_count()
        if not self._confirm_library_scan(entry_count):
            return
        self._start_library_scan(channels)

    def _scan_entry_count(self, scan: LibraryScanData) -> int:
        return scan.entries_used or len(scan.entries)

    def _apply_loaded_scan(self, scan: LibraryScanData) -> None:
        """Activate a scan in memory and persist it for the current database."""
        assert self._db_path is not None and self._config is not None
        kind = "index" if self._index_db_mode else "full"
        channels = list(scan.channel_names) or self._get_selected_channels()
        for name, var in self._channel_vars.items():
            var.set(name in channels)
        fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
        signal_alpha = self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA
        snapshot = build_snapshot_from_scan(
            scan,
            database_path=self._db_path,
            database_kind=kind,
            channel_names=channels,
            metric_ids=[],
            plot_ids=[],
            plot_results=[],
            fraction_count=fraction_count,
            signal_quality_alpha=signal_alpha,
        )
        self._cached_scan = scan
        self._current_snapshot = snapshot
        self._current_snapshot_path = None
        self._plot_results.clear()
        save_session_scan(scan, self._db_path)
        self._show_scan_ready_placeholder(scan)
        self._clear_plots_view()
        self._update_plots_summary([])
        self._update_status_label()
        self._update_action_states()

    def _on_clear_library_scan(self) -> None:
        if self._is_busy():
            return
        has_memory = self._cached_scan is not None
        saved_count = len(list_session_scan_paths())
        if not has_memory and saved_count == 0:
            messagebox.showinfo(
                "Library Analysis",
                "No library scan is loaded or saved.",
                parent=self,
            )
            return
        saved_note = (
            f"This deletes {saved_count:,} saved scan file(s) for all databases.\n\n"
            if saved_count
            else ""
        )
        if not messagebox.askyesno(
            "Clear library scan",
            "Remove all cached library scans?\n\n"
            f"{saved_note}"
            "Use Export scan… first if you need to keep a scan between sessions.\n\n"
            "Metrics, plots, and RT assignment results that depend on the scan "
            "will no longer be available until you run or import a scan again.",
            parent=self,
            icon="warning",
        ):
            return
        deleted = delete_all_session_scans()
        self._cached_scan = None
        self._qc_metrics_artifact = None
        self._qc_plots_artifact = None
        self._rt_assignment_artifact = None
        self._pedigree_viz_artifact = None
        self._splittree_artifact = None
        self._current_snapshot = None
        self._current_snapshot_path = None
        self._plot_results.clear()
        self._clear_metrics_view()
        self._clear_plots_view()
        self._show_idle_placeholder()
        self._update_status_label()
        self._update_action_states()
        if deleted:
            detail = f"Removed {deleted:,} saved scan file(s)."
        elif has_memory:
            detail = "Cleared the in-memory scan."
        else:
            detail = "No saved scan files were found."
        messagebox.showinfo(
            "Library Analysis",
            f"Library scans cleared.\n\n{detail}",
            parent=self,
        )

    def _on_export_library_scan(self) -> None:
        if self._is_busy() or self._cached_scan is None or self._db_path is None:
            return
        scan = self._cached_scan
        default_name = suggested_scan_export_filename(self._db_path, scan)
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export library scan",
            initialfile=default_name,
            defaultextension=".pkl",
            filetypes=[
                ("LC-Seq library scan", "*.pkl"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return
        try:
            export_scan_pickle(scan, Path(dest))
        except OSError as exc:
            messagebox.showerror(
                "Export library scan",
                f"Could not save scan:\n{exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Export library scan",
            f"Scan exported to:\n{dest}",
            parent=self,
        )

    def _on_import_library_scan(self) -> None:
        if self._is_busy() or self._db_path is None or self._config is None:
            return
        source = filedialog.askopenfilename(
            parent=self,
            title="Import library scan",
            filetypes=[
                ("LC-Seq library scan", "*.pkl"),
                ("All files", "*.*"),
            ],
        )
        if not source:
            return
        try:
            scan = load_scan_pickle(Path(source))
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Import library scan",
                f"Could not read scan file:\n{exc}",
                parent=self,
            )
            return
        compound_count = (
            self._data_store.get_compound_count() if self._data_store is not None else 0
        )
        report = validate_scan_for_database(
            scan,
            database_path=self._db_path,
            config=self._config,
            compound_count=compound_count,
        )
        if not report.ok:
            messagebox.showerror(
                "Import library scan",
                "This scan cannot be used with the active library:\n\n"
                + "\n".join(f"• {line}" for line in report.errors),
                parent=self,
            )
            return
        if report.warnings:
            warning_text = "\n".join(f"• {line}" for line in report.warnings)
            if not messagebox.askyesno(
                "Import library scan",
                "The scan loaded, but please review these warnings:\n\n"
                f"{warning_text}\n\n"
                "Import this scan anyway?",
                parent=self,
                icon="warning",
            ):
                return
        self._apply_loaded_scan(scan)
        messagebox.showinfo(
            "Import library scan",
            f"Imported scan with {self._scan_entry_count(scan):,} entries "
            f"({', '.join(scan.channel_names) or 'no channels'}).",
            parent=self,
        )

    def _on_calculate_metrics(self) -> None:
        if self._is_busy() or self._cached_scan is None:
            return
        metric_ids = self._get_selected_metric_ids()
        if not metric_ids:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one metric.",
                parent=self,
            )
            return
        if self._parse_fraction_count() is None or self._parse_signal_alpha() is None:
            return
        entry_count = self._cached_scan.entries_used or self._cached_scan.entries_attempted
        if not self._confirm_metrics_computation(entry_count, metric_ids):
            return
        self._start_metrics_computation(metric_ids)

    def _start_library_scan(self, channels: List[str]) -> None:
        assert self._db_path is not None and self._config is not None

        self._show_loading_page(
            "Running library scan",
            "Parsing chromatograms from database entries…",
        )
        self._update_action_states()

        db_path = self._db_path
        config = self._config
        kind = "index" if self._index_db_mode else "full"
        fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
        signal_alpha = self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA

        def worker() -> None:
            try:
                def scan_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._thread_loading_progress(
                        fraction,
                        status or "Parsing library entries…",
                    )

                scan = scan_library_for_path(
                    db_path,
                    config,
                    channel_names=channels,
                    progress_callback=scan_progress,
                )
                self._raise_if_cancelled()
                snapshot = build_snapshot_from_scan(
                    scan,
                    database_path=db_path,
                    database_kind=kind,
                    channel_names=channels,
                    metric_ids=[],
                    plot_ids=[],
                    plot_results=[],
                    fraction_count=fraction_count,
                    signal_quality_alpha=signal_alpha,
                )
                self._bind_worker_callback(self._on_scan_ready, scan, snapshot)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library scan failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _start_metrics_computation(self, metric_ids: List[str]) -> None:
        assert self._db_path is not None and self._cached_scan is not None
        scan = self._cached_scan
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        fraction_count = self._parse_fraction_count()
        signal_alpha = self._parse_signal_alpha()
        quality = self._parse_peak_quality_params()
        if fraction_count is None or signal_alpha is None or quality is None:
            return
        min_prominence, min_pct_area = quality

        self._show_loading_page(
            "Calculating metrics",
            "Aggregating library summary metrics…",
        )
        self._update_action_states()

        db_path = self._db_path
        kind = "index" if self._index_db_mode else "full"
        plot_ids = self._get_selected_plot_ids()
        plot_results = list(self._plot_results)

        def worker() -> None:
            try:
                def metrics_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._thread_loading_progress(
                        fraction,
                        status or "Computing library metrics…",
                    )

                metric_results = compute_metrics_from_scan(
                    scan,
                    metric_ids,
                    channels=channels,
                    fraction_count=fraction_count,
                    signal_quality_alpha=signal_alpha,
                    min_prominence=min_prominence,
                    min_pct_area=min_pct_area,
                    progress_callback=metrics_progress,
                )
                snapshot = LibraryComputationSnapshot(
                    processed_at=datetime.now(timezone.utc),
                    database_path=str(db_path.resolve()),
                    database_kind=kind,
                    fraction_count=fraction_count,
                    selected_channels=list(channels),
                    selected_metrics=list(metric_ids),
                    selected_plots=list(plot_ids),
                    entries_attempted=scan.entries_attempted,
                    entries_used=scan.entries_used,
                    entries_skipped=scan.entries_skipped,
                    metric_results=metric_results,
                    plot_results=plot_results,
                    signal_quality_alpha=signal_alpha,
                )
                self._raise_if_cancelled()
                self._bind_worker_callback(self._on_metrics_ready, snapshot)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library metrics failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _on_scan_ready(
        self,
        scan: LibraryScanData,
        snapshot: LibraryComputationSnapshot,
    ) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._cached_scan = scan
        self._current_snapshot = snapshot
        self._current_snapshot_path = None
        self._plot_results.clear()
        if self._db_path is not None:
            save_session_scan(scan, self._db_path)
        self._update_loading_progress(
            0.98,
            (
                f"Scan complete: {scan.entries_used:,} of {scan.entries_attempted:,} "
                f"entries parsed ({scan.entries_skipped:,} skipped)."
            ),
        )

        def finish() -> None:
            if not self._ui_is_active():
                return
            try:
                self._show_scan_ready_placeholder(scan)
                self._clear_plots_view()
                self._update_plots_summary([])
                self._update_status_label()
            except tk.TclError:
                pass
            finally:
                self._hide_loading_page()
                self._update_action_states()

        self.after(30, finish)

    def _on_metrics_ready(self, snapshot: LibraryComputationSnapshot) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._update_loading_progress(0.98, "Preparing metric display…")

        def finish() -> None:
            if not self._ui_is_active():
                return
            try:
                self._current_snapshot = snapshot
                self._current_snapshot_path = None
                self._capture_qc_metrics_artifact(snapshot)
                self._render_metrics()
                self._update_status_label()
                self._focus_tab(_TAB_METRICS)
            except tk.TclError:
                pass
            finally:
                self._hide_loading_page()
                self._update_action_states()

        self.after(30, finish)

    def _on_generate_plots(self) -> None:
        if self._is_busy() or self._cached_scan is None or self._db_path is None:
            return
        plot_ids = self._get_selected_plot_ids()
        channels = self._get_selected_channels()
        if not plot_ids or not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one plot and one count channel.",
                parent=self,
            )
            return
        signal_alpha = self._parse_signal_alpha()
        quality = self._parse_peak_quality_params()
        if signal_alpha is None or quality is None:
            return
        min_prominence, min_pct_area = quality
        entry_count = self._cached_scan.entries_used or self._cached_scan.entries_attempted
        if not self._confirm_plot_generation(entry_count, plot_ids):
            return

        self._show_loading_page(
            "Generating plots",
            "Rendering library visualizations…",
        )
        self._update_action_states()

        scan = self._cached_scan
        plot_dir = session_plots_dir(self._db_path)

        def worker() -> None:
            try:
                def plot_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._thread_loading_progress(
                        fraction,
                        status or "Generating plots…",
                    )

                plots = generate_plots(
                    scan,
                    plot_ids,
                    channels,
                    plot_dir,
                    signal_quality_alpha=signal_alpha,
                    min_prominence=min_prominence,
                    min_pct_area=min_pct_area,
                    progress_callback=plot_progress,
                )
                self._raise_if_cancelled()
                kept = {
                    p.image_path.resolve()
                    for p in plots
                    if p.image_path is not None and p.image_path.is_file()
                }
                for old in plot_dir.glob("*.png"):
                    try:
                        if old.resolve() not in kept:
                            old.unlink()
                    except OSError:
                        pass
                self._bind_worker_callback(self._on_plots_ready, plots, plot_ids)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Plot generation failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _on_plots_ready(self, plots: List[PlotResult], plot_ids: List[str]) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._plot_results = plots
        if self._current_snapshot is not None:
            self._current_snapshot.selected_plots = list(plot_ids)
            self._current_snapshot.plot_results = plots
        elif self._cached_scan is not None and self._db_path is not None:
            channels = self._get_selected_channels()
            fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
            signal_alpha = self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA
            scan = self._cached_scan
            kind = "index" if self._index_db_mode else "full"
            self._current_snapshot = LibraryComputationSnapshot(
                processed_at=datetime.now(timezone.utc),
                database_path=str(self._db_path.resolve()),
                database_kind=kind,
                fraction_count=fraction_count,
                selected_channels=list(channels),
                selected_metrics=[],
                selected_plots=list(plot_ids),
                entries_attempted=scan.entries_attempted,
                entries_used=scan.entries_used,
                entries_skipped=scan.entries_skipped,
                metric_results=[],
                plot_results=plots,
                signal_quality_alpha=signal_alpha,
            )

        self._update_loading_progress(
            0.98,
            f"Generated {len(plots)} plot(s). Loading images…",
        )

        def finish() -> None:
            if not self._ui_is_active():
                return
            try:
                self._capture_qc_plots_artifact(plots, plot_ids)
                self._update_plots_summary(plots)
                self._focus_tab(_TAB_PLOTS)
                self._refresh_plot_gallery(plots)
                self._update_status_label()
            except tk.TclError:
                pass
            finally:
                self._hide_loading_page()
                self._update_action_states()

        self.after(30, finish)

    def _thread_progress(self, processed: int, total: int, status: str) -> None:
        fraction = (processed / total) if total > 0 else 0.0
        self._thread_loading_progress(fraction, status)

    def _update_progress(self, processed: int, total: int, status: str) -> None:
        fraction = (processed / total) if total > 0 else 0.0
        self._update_loading_progress(fraction, status)

    def _on_worker_error(self, message: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        try:
            self._loading_detail.configure(text=f"Error: {message}", text_color="red")
            self._loading_percent.configure(text="")
            messagebox.showerror("Library Analysis", message, parent=self)
        except tk.TclError:
            pass
        self._hide_loading_page()
        self._update_action_states()

    def _on_save(self) -> None:
        if self._current_snapshot is None or self._db_path is None:
            return
        plot_dir = session_plots_dir(self._db_path)
        try:
            saved = save_snapshot(
                self._current_snapshot,
                plot_source_dir=plot_dir if plot_dir.is_dir() else None,
            )
            self._current_snapshot_path = saved
            self._update_status_label()
            messagebox.showinfo(
                "Library Analysis",
                f"Saved results to:\n{saved}\n\nPlots: {snapshot_plots_dir(saved)}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror("Library Analysis", f"Could not save results:\n{exc}", parent=self)

    def _on_load_last(self) -> None:
        if self._db_path is None:
            return
        path = get_latest_snapshot_path(self._db_path)
        if path is None:
            messagebox.showinfo(
                "Library Analysis",
                "No saved results were found for this database.",
                parent=self,
            )
            return
        self._load_snapshot_from_path(path)

    def _on_clear_all_metrics_results(self) -> None:
        if self._is_busy():
            return
        saved_paths = list_snapshots()
        if not saved_paths:
            messagebox.showinfo(
                "Library Analysis",
                "No saved Library QC metrics results were found.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Clear all results",
            f"Delete all {len(saved_paths):,} saved Library QC metrics result file(s)?\n\n"
            "This removes snapshot JSON files and their plot folders under "
            f"{get_library_data_dir()}.\n\n"
            "This does not clear the in-memory library scan or unsaved metrics on screen.\n\n"
            "Continue?",
            parent=self,
            icon="warning",
        ):
            return
        deleted = delete_all_saved_snapshots()
        if (
            self._current_snapshot_path is not None
            and not self._current_snapshot_path.is_file()
        ):
            self._current_snapshot_path = None
        self._update_status_label()
        self._update_action_states()
        messagebox.showinfo(
            "Library Analysis",
            f"Removed {deleted:,} saved result file(s).",
            parent=self,
        )

    def _on_browse_saved(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open saved library data",
            initialdir=str(get_library_data_dir()),
            filetypes=[("Library data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self._load_snapshot_from_path(Path(path))

    def _load_snapshot_from_path(self, path: Path) -> None:
        try:
            snapshot = load_snapshot(path)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not load saved results:\n{exc}",
                parent=self,
            )
            return
        self._cached_scan = None
        self._plot_results = []
        self._apply_snapshot(snapshot, path, warn_database_mismatch=True)

    def _apply_snapshot(
        self,
        snapshot: LibraryComputationSnapshot,
        path: Optional[Path],
        *,
        warn_database_mismatch: bool,
    ) -> None:
        if warn_database_mismatch and self._db_path is not None:
            if not database_paths_match(snapshot.database_path, self._db_path):
                messagebox.showwarning(
                    "Database mismatch",
                    "The saved results were computed from a different database:\n\n"
                    f"Saved: {snapshot.database_name}\n"
                    f"Active: {self._db_path.name}\n\n"
                    "Results will still be shown, but they may not match the current library.",
                    parent=self,
                )

        self._current_snapshot = snapshot
        self._current_snapshot_path = path
        self._plot_results = list(snapshot.plot_results)
        self._sync_channel_selection(snapshot)
        self._sync_metric_selection(snapshot)
        self._sync_plot_selection(snapshot)
        self._fraction_count_var.set(str(snapshot.fraction_count))
        self._signal_alpha_var.set(str(snapshot.signal_quality_alpha))
        self._render_results()
        self._update_status_label()
        self._update_action_states()

    def _sync_channel_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        for channel_name, var in self._channel_vars.items():
            var.set(channel_name in snapshot.selected_channels)

    def _sync_metric_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        if not snapshot.selected_metrics:
            return
        for metric_id, var in self._metric_vars.items():
            var.set(metric_id in snapshot.selected_metrics)

    def _sync_plot_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        if not snapshot.selected_plots:
            return
        for plot_id, var in self._plot_vars.items():
            var.set(plot_id in snapshot.selected_plots)

    def _update_status_label(self) -> None:
        scan = self._cached_scan
        snapshot = self._current_snapshot
        if snapshot is None and scan is None:
            self._status_label.configure(text="No scan loaded.")
            return

        if snapshot is not None:
            processed = snapshot.processed_at
            if processed.tzinfo is not None:
                processed_local = processed.astimezone()
            else:
                processed_local = processed
            stamp = processed_local.strftime("%Y-%m-%d %H:%M:%S")
            channels = ", ".join(snapshot.selected_channels) or "—"
            metrics_count = len(snapshot.metric_results)
            plots = ", ".join(snapshot.selected_plots) or "—"
            source = (
                "current session (unsaved)"
                if self._current_snapshot_path is None
                else str(self._current_snapshot_path)
            )
            scan_note = (
                "scan in memory"
                if scan is not None
                else "metrics/plots only (rescan to refresh)"
            )
            self._status_label.configure(
                text=(
                    f"Processed: {stamp}  ·  Database: {snapshot.database_name} "
                    f"({snapshot.database_kind})  ·  Entries: {snapshot.entries_used:,} / "
                    f"{snapshot.entries_attempted:,}  ·  Fractions: {snapshot.fraction_count}  ·  "
                    f"α: {snapshot.signal_quality_alpha:g}  ·  Channels: {channels}  ·  "
                    f"Metrics: {metrics_count}  ·  Plots: {plots}  ·  "
                    f"{scan_note}  ·  Source: {source}"
                )
            )
            return

        assert scan is not None
        channels = ", ".join(scan.channel_names) or "—"
        self._status_label.configure(
            text=(
                f"Scan in memory  ·  Entries: {scan.entries_used:,} / "
                f"{scan.entries_attempted:,} ({scan.entries_skipped:,} skipped)  ·  "
                f"Channels: {channels}  ·  Metrics: not calculated  ·  Plots: not generated"
            )
        )

    def _on_export_signal_csv(self) -> None:
        if self._cached_scan is None:
            messagebox.showinfo(
                "Library Analysis",
                "Run library scan first.",
                parent=self,
            )
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        alpha = self._parse_signal_alpha()
        quality = self._parse_peak_quality_params()
        if alpha is None or quality is None:
            return
        min_prominence, min_pct_area = quality
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export per-entry signal CSV",
            initialfile="library_signal_per_entry.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not dest:
            return

        self._show_loading_page(
            "Exporting signal CSV",
            "Computing per-entry signal metrics…",
        )
        scan = self._cached_scan
        assert scan is not None

        def worker() -> None:
            try:
                def export_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._thread_loading_progress(fraction, status)

                stats = attach_signal_quality_to_entries(
                    scan.entries,
                    channels,
                    alpha=alpha,
                    min_prominence=min_prominence,
                    min_pct_area=min_pct_area,
                    progress_callback=export_progress,
                )
                export_per_entry_signal_csv(stats, dest, alpha=alpha)
                self._bind_worker_callback(self._on_export_csv_ready, str(dest))
            except LibraryOperationCancelled:
                raise
            except OSError as exc:
                self._bind_worker_callback(self._on_worker_error, str(exc))
            except Exception as exc:
                logger.error("CSV export failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_worker_error, str(exc))

        self._start_worker(worker)
        self._update_action_states()

    def _on_export_csv_ready(self, dest: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._hide_loading_page()
        self._update_action_states()
        messagebox.showinfo(
            "Library Analysis",
            f"Exported per-entry signal metrics to:\n{dest}",
            parent=self,
        )

    def _render_results(self) -> None:
        self._render_metrics()
        plots = self._plot_results
        if self._current_snapshot is not None and not plots:
            plots = list(self._current_snapshot.plot_results)
            self._plot_results = plots
        self._update_plots_summary(plots)
        self._refresh_plot_gallery(plots)

    def _render_metrics(self) -> None:
        assert self._metrics_frame is not None
        self._clear_metrics_view()
        snapshot = self._current_snapshot
        if snapshot is None:
            self._update_metrics_summary_label(0)
            return

        row = 0
        if snapshot.signal_quality_alpha and any(
            m.metric_id in SIGNAL_QUALITY_METRIC_IDS for m in snapshot.metric_results
        ):
            banner = ctk.CTkFrame(
                self._metrics_frame,
                corner_radius=10,
                fg_color=("gray90", "gray22"),
                border_width=1,
                border_color=("gray78", "gray28"),
            )
            banner.grid(row=row, column=0, sticky="ew", pady=(4, 14), padx=2)
            ctk.CTkLabel(
                banner,
                text=(
                    "Signal-quality metrics (significant peaks): peak height, SNR, and dynamic "
                    "range use the tallest peak with p-value < α from the same peak picker "
                    "as Chromatogram Visualizer. Baseline μ and σ come from a σ-clipped median "
                    f"(iteratively drop points above mean+2σ). α = {snapshot.signal_quality_alpha:g}."
                ),
                font=ctk.CTkFont(size=11),
                anchor="w",
                wraplength=760,
                justify="left",
            ).pack(padx=14, pady=12, anchor="w")
            row += 1

        if snapshot.metric_results:
            self._update_metrics_summary_label(len(snapshot.metric_results))
            last_category: Optional[str] = None
            for metric in snapshot.metric_results:
                definition = LIBRARY_METRIC_DEFINITIONS.get(metric.metric_id)
                category = definition.category if definition else "other"
                if category != last_category:
                    category_label = (
                        "Coverage metrics"
                        if category == "coverage"
                        else "Signal-quality metrics"
                        if category == "signal"
                        else "Metrics"
                    )
                    ctk.CTkLabel(
                        self._metrics_frame,
                        text=category_label,
                        font=_section_header_font(),
                        text_color=_SECTION_HEADER_COLOR,
                        anchor="w",
                    ).grid(row=row, column=0, sticky="w", padx=6, pady=(12, 6))
                    row += 1
                    last_category = category
                self._render_stat_card(
                    parent=self._metrics_frame,
                    row=row,
                    title=metric.title,
                    help_txt=metric.help_text,
                    channels=metric.channels,
                )
                row += 1
        else:
            self._update_metrics_summary_label(0)

        if row == 0:
            card = self._make_info_card(
                self._metrics_frame,
                "No metrics",
                "Run library scan, then click Calculate metrics.",
            )
            card.grid(row=0, column=0, sticky="ew", pady=8)

    def _update_metrics_summary_label(self, metric_count: int) -> None:
        if not hasattr(self, "_metrics_summary_label"):
            return
        if metric_count == 0:
            text = "Summary metrics appear after Calculate metrics."
        else:
            text = f"{metric_count} metric(s) calculated — values by channel below."
        try:
            self._metrics_summary_label.configure(text=text)
        except tk.TclError:
            pass

    def _on_export_metrics_csv(self) -> None:
        snapshot = self._current_snapshot
        if snapshot is None or not snapshot.metric_results:
            messagebox.showinfo(
                "Library Analysis",
                "Calculate metrics first.",
                parent=self,
            )
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export summary metrics CSV",
            initialfile="library_summary_metrics.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not dest:
            return
        try:
            saved = export_metrics_summary_csv(snapshot, dest)
            messagebox.showinfo(
                "Library Analysis",
                f"Exported summary metrics to:\n{saved}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not export metrics:\n{exc}",
                parent=self,
            )

    def _update_plots_summary(self, plots: List[PlotResult]) -> None:
        if not hasattr(self, "_plots_summary_label"):
            return
        available = sum(
            1 for p in plots if p.image_path is not None and p.image_path.is_file()
        )
        total = len(plots)
        if total == 0:
            text = "No plots generated yet. Run library scan, then Generate plots."
        elif available == total:
            text = f"{available} plot(s) ready — select one from the list to preview."
        else:
            text = (
                f"{available} of {total} plot(s) available "
                f"({total - available} missing or failed to render)."
            )
        try:
            self._plots_summary_label.configure(text=text)
        except tk.TclError:
            pass

    @staticmethod
    def _format_plot_list_label(title: str) -> str:
        """Wrap long plot titles onto two lines for the selection list."""
        if " — " in title:
            plot_name, channel = title.split(" — ", 1)
            return f"{plot_name}\n— {channel}"
        if len(title) > 28:
            split_at = title.rfind(" ", 0, 28)
            if split_at > 10:
                return f"{title[:split_at]}\n{title[split_at + 1:]}"
        return title

    def _refresh_plot_gallery(self, plots: List[PlotResult]) -> None:
        """Rebuild plot list and show the first available plot."""
        self._clear_plots_view()
        if not plots:
            if self._plot_preview_tk is not None:
                self._plot_preview_tk.configure(
                    image="",
                    text="Generate plots to preview visualizations here.",
                )
            return

        assert self._plot_list_frame is not None
        for index, plot in enumerate(plots):
            available = plot.image_path is not None and plot.image_path.is_file()
            label = self._format_plot_list_label(
                plot.title if available else f"{plot.title} (missing)"
            )
            btn = ctk.CTkButton(
                self._plot_list_frame,
                text=label,
                anchor="w",
                height=_PLOT_LIST_BUTTON_HEIGHT,
                fg_color="gray40" if not available else ("gray75", "gray30"),
                hover_color=("gray70", "gray35"),
                command=lambda i=index: self._select_plot(i),
            )
            btn.pack(fill="x", pady=2, padx=2)
            self._plot_list_buttons.append(btn)

        first_ok = next(
            (i for i, p in enumerate(plots) if p.image_path and p.image_path.is_file()),
            None,
        )
        if first_ok is not None:
            self._select_plot(first_ok)
        elif plots:
            self._select_plot(0)

    def _select_plot(self, index: int) -> None:
        if index < 0 or index >= len(self._plot_results):
            return
        self._selected_plot_index = index
        plot = self._plot_results[index]

        for i, btn in enumerate(self._plot_list_buttons):
            try:
                if i == index:
                    btn.configure(fg_color=("#238636", "#2ea043"))
                else:
                    available = (
                        self._plot_results[i].image_path is not None
                        and self._plot_results[i].image_path.is_file()
                    )
                    btn.configure(
                        fg_color="gray40" if not available else ("gray75", "gray30")
                    )
            except tk.TclError:
                pass

        if self._plot_preview_title is not None:
            self._plot_preview_title.configure(text=plot.title)
        if self._plot_preview_help is not None:
            self._plot_preview_help.configure(text=plot.help_text or "")

        image_path: Optional[Path] = None
        if plot.image_path is not None:
            try:
                image_path = plot.image_path.resolve()
            except OSError:
                image_path = plot.image_path

        has_file = image_path is not None and image_path.is_file()
        try:
            self._plot_export_btn.configure(state="normal" if has_file else "disabled")
        except (tk.TclError, AttributeError):
            pass

        if not has_file or self._plot_preview_tk is None or image_path is None:
            if self._plot_preview_tk is not None:
                self._plot_preview_tk.configure(
                    image="",
                    text="Plot image not available. Try Generate plots.",
                    bg=self._tk_preview_bg(),
                )
            self._plot_photo = None
            return

        try:
            from PIL import Image, ImageTk

            with Image.open(image_path) as pil_image:
                width, height = pil_image.size
                scale = min(1.0, _PLOT_PREVIEW_MAX_WIDTH / float(width))
                display_w = max(1, int(width * scale))
                display_h = max(1, int(height * scale))
                resized = pil_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
                self._plot_photo = ImageTk.PhotoImage(resized)
            self._plot_preview_tk.configure(
                image=self._plot_photo,
                text="",
                bg=self._tk_preview_bg(),
            )
        except Exception as exc:
            logger.warning("Failed to display plot preview %s: %s", image_path, exc)
            self._plot_photo = None
            self._plot_preview_tk.configure(
                image="",
                text=f"Could not load preview.\nUse Open to view:\n{image_path}",
                bg=self._tk_preview_bg(),
            )

    def _current_plot_path(self) -> Optional[Path]:
        if self._selected_plot_index is None:
            return None
        plot = self._plot_results[self._selected_plot_index]
        if plot.image_path is None:
            return None
        try:
            path = plot.image_path.resolve()
        except OSError:
            path = plot.image_path
        return path if path.is_file() else None

    def _on_export_current_plot(self) -> None:
        path = self._current_plot_path()
        if path is None:
            return
        self._export_plot_image(path)

    def _on_export_all_plots(self) -> None:
        plots = [
            p
            for p in self._plot_results
            if p.image_path is not None and p.image_path.is_file()
        ]
        if not plots:
            messagebox.showinfo(
                "Library Analysis",
                "No plot files are available to export. Generate plots first.",
                parent=self,
            )
            return
        dest = filedialog.askdirectory(
            parent=self,
            title="Choose folder for exported plots",
        )
        if not dest:
            return
        out_dir = Path(dest)
        exported = 0
        errors: List[str] = []
        for plot in plots:
            assert plot.image_path is not None
            target = out_dir / plot.image_path.name
            try:
                shutil.copy2(plot.image_path, target)
                exported += 1
            except OSError as exc:
                errors.append(f"{plot.image_path.name}: {exc}")
        if errors:
            messagebox.showwarning(
                "Library Analysis",
                f"Exported {exported} plot(s) to:\n{out_dir}\n\n"
                f"Some files failed:\n" + "\n".join(errors[:5]),
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Library Analysis",
                f"Exported {exported} plot(s) to:\n{out_dir}",
                parent=self,
            )

    def _on_open_plots_folder(self) -> None:
        if self._db_path is None:
            return
        folder = session_plots_dir(self._db_path)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder.resolve()))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not open plots folder:\n{folder}\n\n{exc}",
                parent=self,
            )

    def _render_stat_card(
        self,
        *,
        parent: ctk.CTkScrollableFrame,
        row: int,
        title: str,
        help_txt: str,
        channels: List[ChannelAggregateStats],
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color=("gray95", "gray18"),
            border_width=1,
            border_color=("gray82", "gray30"),
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16), padx=2)
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color=("gray88", "gray22"), corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            header,
            text=help_txt,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        if not channels or all(ch.n == 0 for ch in channels):
            ctk.CTkLabel(
                card,
                text="No values could be computed.",
                text_color="orange",
            ).grid(row=1, column=0, padx=14, pady=(0, 14), sticky="w")
            return

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, padx=12, pady=(0, 14), sticky="ew")
        body.grid_columnconfigure(0, weight=1)

        for row_i, ch in enumerate(channels):
            self._add_channel_row(body, row_i, ch)

    def _open_plot_file(self, path: Path) -> None:
        if not path.is_file():
            messagebox.showwarning("Open plot", "Plot file was not found.", parent=self)
            return
        try:
            os.startfile(str(path.resolve()))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open plot", f"Could not open plot:\n{exc}", parent=self)

    def _export_plot_image(self, source: Path) -> None:
        if not source.is_file():
            messagebox.showwarning("Export", "Plot file was not found.", parent=self)
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export plot image",
            initialfile=source.name,
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return
        try:
            shutil.copy2(source, dest)
            messagebox.showinfo("Export", f"Saved plot to:\n{dest}", parent=self)
        except OSError as exc:
            messagebox.showerror("Export", f"Could not export plot:\n{exc}", parent=self)

    def _add_channel_row(
        self,
        parent: ctk.CTkFrame,
        row_i: int,
        ch: ChannelAggregateStats,
    ) -> None:
        row_frame = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("gray90", "gray24"),
            border_width=1,
            border_color=("gray80", "gray32"),
        )
        row_frame.grid(row=row_i, column=0, sticky="ew", pady=4)
        row_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_frame,
            text=ch.count_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=(12, 16), pady=10, sticky="w")

        if ch.n == 0:
            value_text = "—"
        elif ch.n == 1:
            value_text = f"{ch.mean:,.4g}  (n = 1, SD undefined)"
        else:
            value_text = f"{ch.mean:,.4g} ± {ch.std_dev:,.4g}  (n = {ch.n:,})"

        ctk.CTkLabel(
            row_frame,
            text=value_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0969da", "#58a6ff"),
            anchor="e",
        ).grid(row=0, column=1, padx=12, pady=10, sticky="e")

    @staticmethod
    def _make_info_card(
        parent: ctk.CTkFrame,
        title: str,
        body: str,
        *,
        wraplength: int = 760,
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text=body,
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=wraplength,
            justify="left",
        ).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")
        return card

    def _parse_pedigree_settings(self) -> Optional[AnalysisSettings]:
        channel = self._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showerror("Pedigree", "Select a count channel.", parent=self)
            return None
        try:
            tolerance = float(self._pedigree_tolerance_var.get().strip())
        except ValueError:
            messagebox.showerror("Pedigree", "Null RT threshold must be a number.", parent=self)
            return None
        if tolerance <= 0:
            messagebox.showerror("Pedigree", "Null RT threshold must be positive.", parent=self)
            return None
        try:
            alpha = float(self._pedigree_alpha_var.get().strip())
        except ValueError:
            messagebox.showerror("Pedigree", "α must be a number.", parent=self)
            return None
        if alpha <= 0 or alpha >= 1:
            messagebox.showerror("Pedigree", "α must be between 0 and 1 (exclusive).", parent=self)
            return None
        time_unit = self._pedigree_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            messagebox.showerror("Pedigree", "Invalid time unit.", parent=self)
            return None
        quality = self._parse_peak_quality_params()
        if quality is None:
            return None
        min_prominence, min_pct_area = quality
        algorithm = self._pedigree_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            messagebox.showerror("Pedigree", "Invalid peak picking algorithm.", parent=self)
            return None
        try:
            gaussian_min_height_factor = float(self._pedigree_gaussian_height_var.get().strip())
            gaussian_fit_width = float(self._pedigree_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(self._pedigree_gaussian_stddev_var.get().strip())
            gaussian_minimum_rt = float(self._pedigree_gaussian_min_rt_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Pedigree", "Old-school peak picker parameters must be numbers.", parent=self
            )
            return None
        stored_unit = (
            "minutes" if self._config and self._config.analysis_time_unit == "minutes" else "seconds"
        )
        return AnalysisSettings(
            count_channel=channel,
            time_unit=time_unit,  # type: ignore[arg-type]
            chromatogram_time_unit=stored_unit,  # type: ignore[arg-type]
            peak_picking_algorithm=algorithm,  # type: ignore[arg-type]
            alpha=alpha,
            tolerance=tolerance,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            selected_variants=None,
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _format_pedigree_summary(self, result: PedigreeAnalysisResult) -> str:
        picker_label = (
            "old-school Gaussian"
            if result.settings.uses_old_school_peak_picker
            else "modern NB"
        )
        parts = [
            f"{result.n_chromatograms:,} chromatograms · channel {result.channel} · "
            f"picker={picker_label} · null RT threshold={result.settings.tolerance:g} "
            f"{result.settings.time_unit}"
        ]
        if result.settings.uses_modern_peak_picker:
            parts[0] += f" · α={result.settings.alpha:g}"
        if result.settings.min_prominence > 0 or result.settings.min_pct_area > 0:
            parts.append(
                f"quality: prom≥{result.settings.min_prominence:g}, "
                f"%area≥{result.settings.min_pct_area:g}"
            )
        if result.isoform_label != "All":
            parts.append(f"isoform={result.isoform_label}")
        tier_bits = []
        for summary in result.tier_summaries:
            tier_bits.append(
                f"tier {summary.tier}: pass={summary.pass_count} "
                f"fail={summary.fail_count} pruned={summary.pruned_count}"
            )
        if tier_bits:
            parts.append(" · ".join(tier_bits))
        return "\n".join(parts)

    def _update_pedigree_graphviz_banner(self) -> None:
        if self._pedigree_graphviz_banner is None:
            return
        if graphviz_available():
            self._pedigree_graphviz_banner.configure(text="")
            self._pedigree_graphviz_banner.grid_remove()
        else:
            hint = graphviz_install_hint()
            self._pedigree_graphviz_banner.configure(
                text=f"⚠ {hint}",
                text_color="#B8860B",
            )
            self._pedigree_graphviz_banner.grid()

    def _pedigree_tree_render_options(self) -> PedigreeTreeRenderOptions:
        max_tier = int(round(self._pedigree_tree_tier_slider.get())) if self._pedigree_tree_tier_slider else 0
        return PedigreeTreeRenderOptions(
            max_display_tier=max_tier,
            include_failed=bool(self._pedigree_include_failed_var.get()),
            show_rt=bool(self._pedigree_show_rt_var.get()),
        )

    def _configure_pedigree_tier_slider(self, result: PedigreeAnalysisResult) -> None:
        if self._pedigree_tree_tier_slider is None:
            return
        max_tier = max_tier_in_records(result.records)
        steps = max(max_tier, 1)
        self._pedigree_tree_tier_slider.configure(from_=0, to=max_tier, number_of_steps=steps)
        default_tier = result.max_display_tier
        if default_tier is None:
            default_tier = build_default_tree_render_options(
                result.records,
                library_cycle_count=result.library_cycle_count,
            ).max_display_tier
        tier_val = min(max(int(default_tier or 0), 0), max_tier)
        self._pedigree_tree_tier_slider.set(float(tier_val))
        self._on_pedigree_tier_slider_changed(float(tier_val))

    def _update_pedigree_tree_density_note(self, result: PedigreeAnalysisResult) -> None:
        if self._pedigree_tree_dense_note is None or self._pedigree_tree_node_count_label is None:
            return
        opts = self._pedigree_tree_render_options()
        visible = count_visible_pedigree_nodes(
            result.records,
            include_failed=opts.include_failed,
            max_display_tier=opts.max_display_tier,
        )
        self._pedigree_tree_node_count_label.configure(
            text=f"Visible nodes in figure: {visible:,}"
        )
        if not opts.include_failed:
            with_failed = count_visible_pedigree_nodes(
                result.records,
                include_failed=True,
                max_display_tier=opts.max_display_tier,
            )
            if with_failed > visible:
                self._pedigree_tree_dense_note.configure(
                    text=(
                        f"Showing passed nodes only ({visible:,} of {with_failed:,} visible with "
                        "failed trim points). Enable failed trim points to see red/yellow boundaries."
                    )
                )
                return
        self._pedigree_tree_dense_note.configure(text="")

    def _on_pedigree_tier_slider_changed(self, value: float) -> None:
        tier = int(round(float(value)))
        if self._pedigree_tree_tier_label is not None:
            self._pedigree_tree_tier_label.configure(text=f"Max tier shown: {tier}")
        if self._pedigree_result is not None:
            self._update_pedigree_tree_density_note(self._pedigree_result)
            self._show_pedigree_tree_preview(self._pedigree_result)

    def _on_pedigree_tree_option_changed(self) -> None:
        if self._pedigree_result is not None:
            self._update_pedigree_tree_density_note(self._pedigree_result)
            self._show_pedigree_tree_preview(self._pedigree_result)

    def _is_del_branch_viz_mode(self) -> bool:
        return self._splittree_view_mode_var.get() == _SPLITTREE_VIEW_BRANCH

    def _on_splittree_view_changed(self) -> None:
        branch_mode = self._is_del_branch_viz_mode()
        if self._pedigree_del_branch_menu is not None:
            self._pedigree_del_branch_menu.configure(
                state="normal" if branch_mode else "disabled"
            )
        if self._splittree_viz_data is not None:
            self._show_del_cycle_tree_preview(self._splittree_viz_data)

    def _apply_splittree_rt_column_choices(
        self,
        discovered: List[MetadataRtColumnInfo],
    ) -> None:
        """Update the metadata RT and verification column dropdowns."""
        if self._splittree_rt_column_menu is None:
            return
        columns = [info.column_name for info in discovered]
        choices = ["(select column)", *columns]
        self._splittree_rt_column_menu.configure(values=choices)
        current = self._splittree_metadata_rt_column_var.get().strip()
        if current not in choices:
            self._splittree_metadata_rt_column_var.set(
                choices[1] if len(choices) > 1 else choices[0]
            )
        if self._splittree_verified_column_menu is not None:
            self._splittree_verified_column_menu.configure(values=choices)
            verified_current = self._splittree_metadata_verified_column_var.get().strip()
            if verified_current not in choices:
                self._splittree_metadata_verified_column_var.set(
                    choices[1] if len(choices) > 1 else choices[0]
                )
        if self._splittree_rt_column_status_label is not None:
            self._splittree_rt_column_status_label.configure(
                text=self._format_splittree_rt_column_status(
                    discovered,
                    selected=self._splittree_metadata_rt_column_var.get(),
                ),
                text_color=("gray10", "gray90") if discovered else "#D29922",
            )
        if self._splittree_verified_column_status_label is not None:
            self._splittree_verified_column_status_label.configure(
                text=self._format_splittree_verified_column_status(
                    discovered,
                    selected=self._splittree_metadata_verified_column_var.get(),
                ),
                text_color=("gray10", "gray90") if discovered else "#D29922",
            )

    def _on_splittree_isoform_changed(self) -> None:
        self._splittree_viz_data = None
        self._splittree_viz_isoform = None
        if self._splittree_rt_source_var.get() == _SPLITTREE_RT_METADATA:
            if self._splittree_rt_column_status_label is not None:
                iso = self._splittree_isoform_label()
                extra = f" Isoform: {iso}." if iso != "All" else ""
                self._splittree_rt_column_status_label.configure(
                    text=(
                        "Isoform filter changed — click Validate column to refresh counts"
                        f"{extra}"
                    ),
                    text_color="gray",
                )
            if self._splittree_verified_column_status_label is not None:
                self._splittree_verified_column_status_label.configure(
                    text="Isoform filter changed — click Validate column to refresh counts.",
                    text_color="gray",
                )
        self._show_splittree_placeholder(
            "Isoform filter changed. Click Generate plot to rebuild."
        )

    def _on_splittree_rt_column_selected(self) -> None:
        if not self._splittree_rt_columns_detected:
            return
        if self._splittree_rt_column_status_label is None:
            return
        self._splittree_rt_column_status_label.configure(
            text=self._format_splittree_rt_column_status(
                self._splittree_rt_columns_detected,
                selected=self._splittree_metadata_rt_column_var.get(),
            ),
            text_color=("gray10", "gray90"),
        )

    def _on_splittree_verified_column_selected(self) -> None:
        if not self._splittree_rt_columns_detected:
            return
        if self._splittree_verified_column_status_label is None:
            return
        self._splittree_verified_column_status_label.configure(
            text=self._format_splittree_verified_column_status(
                self._splittree_rt_columns_detected,
                selected=self._splittree_metadata_verified_column_var.get(),
            ),
            text_color=("gray10", "gray90"),
        )

    def _on_validate_splittree_rt_column(self) -> None:
        if (
            self._splittree_rt_scan_running
            or self._data_store is None
            or self._config is None
            or self._db_path is None
        ):
            return
        if self._splittree_rt_source_var.get() != _SPLITTREE_RT_METADATA:
            messagebox.showinfo(
                "Split-tree visualization",
                "Set RT source to Spreadsheet metadata before validating.",
                parent=self,
            )
            return
        if not registered_metadata_column_names(self._config):
            messagebox.showinfo(
                "Validate column",
                "No metadata columns are registered in Configure Spreadsheet.",
                parent=self,
            )
            return

        self._splittree_rt_scan_running = True
        if self._splittree_rt_detect_btn is not None:
            self._splittree_rt_detect_btn.configure(state="disabled")
        if self._splittree_rt_column_status_label is not None:
            self._splittree_rt_column_status_label.configure(
                text="Scanning library metadata…",
                text_color="gray",
            )

        config = self._config
        db_path = self._db_path

        def worker() -> None:
            store: Optional[DataStore] = None
            try:
                from src.core.lineage_service import load_all_compound_metadata

                store = DataStore(db_path=db_path, use_memory=False)

                def progress(processed: int, total: int, status: str) -> None:
                    self._schedule_on_main(
                        self._update_splittree_rt_detect_progress,
                        processed,
                        total,
                        status,
                    )

                compounds = load_all_compound_metadata(
                    store,
                    metadata_columns=config.selected_metadata_columns,
                    progress_callback=progress,
                )
                isoform = self._splittree_isoform_label()
                if isoform.lower() != "all":
                    from src.core.pedigree_adapter import filter_compounds_by_variant

                    compounds = filter_compounds_by_variant(compounds, [isoform])
                validated = validate_registered_metadata_columns(compounds, config)
                self._schedule_on_main(self._on_splittree_rt_columns_validated, validated)
            except Exception as exc:
                logger.error("Metadata column validation failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_splittree_rt_columns_detect_failed, str(exc))
            finally:
                if store is not None:
                    store.close()

        threading.Thread(target=worker, daemon=True).start()

    def _on_detect_splittree_rt_columns(self) -> None:
        """Legacy alias."""
        self._on_validate_splittree_rt_column()

    def _update_splittree_rt_detect_progress(
        self,
        processed: int,
        total: int,
        status: str,
    ) -> None:
        if self._splittree_rt_column_status_label is None:
            return
        if total > 0:
            pct = 100.0 * processed / total
            text = f"{status} ({pct:.0f}%)"
        else:
            text = status
        self._splittree_rt_column_status_label.configure(text=text, text_color="gray")
        if self._splittree_verified_column_status_label is not None:
            self._splittree_verified_column_status_label.configure(
                text=text,
                text_color="gray",
            )

    def _on_splittree_rt_columns_validated(
        self,
        validated: List[MetadataRtColumnInfo],
    ) -> None:
        self._splittree_rt_scan_running = False
        self._splittree_rt_columns_detected = list(validated)
        self._apply_splittree_rt_column_choices(validated)
        if self._splittree_rt_detect_btn is not None:
            self._splittree_rt_detect_btn.configure(state="normal")
        if not any(info.n_numeric_values > 0 for info in validated):
            scanned = max((info.n_compounds_scanned for info in validated), default=0)
            if scanned == 0:
                detail = (
                    "The library scan returned no compounds. "
                    "Try closing and reopening Library Analysis."
                )
            else:
                detail = (
                    f"Scanned {scanned:,} compound(s) but found no numeric RT values "
                    "in registered metadata columns."
                )
            messagebox.showinfo(
                "Validate column",
                f"None of the registered metadata columns contain numeric values.\n\n"
                f"{detail}\n\n"
                "Check the column in your spreadsheet and re-process the library if needed.",
                parent=self,
            )

    def _on_splittree_rt_columns_detected(
        self,
        discovered: List[MetadataRtColumnInfo],
    ) -> None:
        self._on_splittree_rt_columns_validated(discovered)

    def _on_splittree_rt_columns_detect_failed(self, message: str) -> None:
        self._splittree_rt_scan_running = False
        if self._splittree_rt_detect_btn is not None:
            self._splittree_rt_detect_btn.configure(state="normal")
        if self._splittree_rt_column_status_label is not None:
            self._splittree_rt_column_status_label.configure(
                text=f"Detection failed: {message}",
                text_color="#D29922",
            )
        messagebox.showerror("Validate column", message, parent=self)

    def _on_splittree_rt_source_changed(self) -> None:
        metadata_mode = self._splittree_rt_source_var.get() == _SPLITTREE_RT_METADATA
        if self._splittree_rt_column_menu is not None:
            self._splittree_rt_column_menu.configure(
                state="normal" if metadata_mode else "disabled"
            )
        if self._splittree_verified_column_menu is not None:
            self._splittree_verified_column_menu.configure(
                state="normal" if metadata_mode else "disabled"
            )
        if self._splittree_rt_detect_btn is not None:
            self._splittree_rt_detect_btn.configure(
                state="normal" if metadata_mode and not self._splittree_rt_scan_running else "disabled"
            )
        if metadata_mode:
            self._load_registered_metadata_columns()
        self._splittree_viz_data = None
        self._show_splittree_placeholder(
            "Select metadata columns, then click Generate plot."
        )

    def _on_generate_splittree_plot(self) -> None:
        if self._is_busy():
            return
        if self._splittree_rt_source_var.get() == _SPLITTREE_RT_METADATA:
            self._generate_splittree_from_metadata()
            return
        if self._reuse_session_del_cycle_for_splittree():
            return
        self._generate_splittree_from_session()

    def _generate_splittree_from_session(self) -> None:
        if self._data_store is None or self._config is None or self._db_path is None:
            return
        if self._del_cycle_tree_data is None:
            messagebox.showinfo(
                "Split-tree visualization",
                "Run RT assignment on the RT assignment tab first, then generate the plot.",
                parent=self,
            )
            return
        isoform = self._splittree_isoform_label()
        self._render_splittree_from_cached_session(isoform, show_loading=True)

    def _on_splittree_session_ready(
        self,
        data: DelCycleTreeData,
        figure: object,
        selected_branch: str,
        isoform: str,
    ) -> None:
        self._worker_thread = None
        self._splittree_viz_data = data
        self._splittree_viz_isoform = isoform
        self._update_del_branch_choices(data)
        if selected_branch:
            self._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected_branch,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
            )
        self._update_del_tree_status_note(data)
        self._mount_splittree_figure(figure)
        self._capture_splittree_artifact(
            data,
            figure,
            isoform=isoform,
            selected_branch=selected_branch,
        )
        self._hide_loading_page()
        self._update_action_states()

    def _generate_splittree_from_metadata(self) -> None:
        column = self._splittree_metadata_rt_column_var.get().strip()
        if not column or column == "(select column)":
            messagebox.showinfo(
                "Split-tree visualization",
                "Select a registered metadata RT column before generating the plot.",
                parent=self,
            )
            return
        verified_column = self._splittree_metadata_verified_column_var.get().strip()
        if not verified_column or verified_column == "(select column)":
            messagebox.showinfo(
                "Split-tree visualization",
                "Select a registered null verification column before generating the plot.",
                parent=self,
            )
            return
        if self._config is None or not registered_metadata_column_names(self._config):
            messagebox.showinfo(
                "Split-tree visualization",
                "No metadata columns are registered in Configure Spreadsheet.",
                parent=self,
            )
            return
        if self._data_store is None or self._config is None or self._db_path is None:
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return

        config = self._config
        isoform = self._splittree_isoform_label()
        rt_threshold = float(settings.tolerance)
        color_by_rt = bool(self._pedigree_del_color_rt_var.get())
        color_mode = self._del_tree_color_mode()
        pass_pct_cutoff = self._read_del_tree_pass_pct_cutoff()
        view_mode = self._splittree_view_mode_var.get()
        branch_selection = self._pedigree_del_branch_var.get().strip()
        iso_note = f" · isoform: {isoform}" if isoform != "All" else ""

        self._show_loading_page(
            "Generating split-tree",
            f"Reading RT values from “{column}” and verification from “{verified_column}”{iso_note}…",
        )
        db_path = self._db_path

        def worker() -> None:
            try:
                def progress(step: int, total: int, status: str) -> None:
                    if total == 1000:
                        fraction = step / 1000.0
                    else:
                        fraction = step / total if total > 0 else 0.0
                    self._thread_loading_progress(
                        min(0.95, fraction),
                        status or "Building split-tree…",
                    )

                data = build_del_cycle_tree_from_metadata_for_path(
                    db_path,
                    config,
                    column,
                    verified_column=verified_column,
                    rt_threshold=rt_threshold,
                    isoform_label=isoform,
                    progress_callback=progress,
                )
                view = (
                    DelCycleTreeView.BRANCH
                    if view_mode == _SPLITTREE_VIEW_BRANCH
                    else DelCycleTreeView.FULL
                )
                selected_branch = branch_selection
                if view == DelCycleTreeView.BRANCH:
                    branches = self._sorted_bb1_branch_names(data)
                    resolved = self._resolve_del_branch_bb1(data, branch_selection)
                    if resolved in branches:
                        selected_branch = resolved
                    elif branches:
                        selected_branch = branches[0]
                self._thread_loading_progress(0.96, "Rendering split-tree figure…")
                figure = render_del_cycle_tree_figure(
                    data,
                    view=view,
                    branch_bb1=selected_branch if view == DelCycleTreeView.BRANCH else None,
                    color_by_rt=color_by_rt,
                    color_mode=color_mode,
                    pass_pct_cutoff=pass_pct_cutoff,
                )
                self._bind_worker_callback(
                    self._on_splittree_metadata_ready,
                    data,
                    figure,
                    selected_branch,
                    isoform,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Metadata split-tree build failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_splittree_metadata_failed, str(exc))

        self._start_worker(worker)
        self._update_action_states()

    def _on_splittree_metadata_ready(
        self,
        data: DelCycleTreeData,
        figure: object,
        selected_branch: str,
        isoform: str = "All",
    ) -> None:
        self._worker_thread = None
        self._splittree_viz_data = data
        self._splittree_viz_isoform = isoform
        self._update_del_branch_choices(data)
        if selected_branch:
            self._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected_branch,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
            )
        self._update_del_tree_status_note(data)
        self._mount_splittree_figure(figure)
        self._capture_splittree_artifact(
            data,
            figure,
            isoform=isoform,
            selected_branch=selected_branch,
        )
        self._hide_loading_page()
        self._update_action_states()

    def _on_splittree_metadata_failed(self, message: str) -> None:
        self._worker_thread = None
        self._hide_loading_page()
        self._show_splittree_placeholder(message)
        messagebox.showerror("Split-tree visualization", message, parent=self)
        self._update_action_states()

    def _read_del_tree_pass_pct_cutoff(self) -> float:
        """Parse split-tree pass-rate cutoff (0–100). Invalid values fall back to 0."""
        try:
            value = float(self._pedigree_del_pass_pct_var.get().strip())
        except ValueError:
            return 0.0
        return min(100.0, max(0.0, value))

    def _on_del_pass_pct_changed(self) -> None:
        if self._splittree_viz_data is not None:
            self._show_del_cycle_tree_preview(self._splittree_viz_data)

    def _del_tree_color_mode(self) -> str:
        if bool(self._pedigree_del_color_pedigree_var.get()):
            return COLOR_MODE_PEDIGREE
        return COLOR_MODE_NOTEBOOK

    def _on_del_branch_changed(self) -> None:
        if self._splittree_viz_data is not None and self._is_del_branch_viz_mode():
            self._show_del_cycle_tree_preview(self._splittree_viz_data)

    def _on_del_tree_option_changed(self) -> None:
        if self._splittree_viz_data is not None:
            self._show_del_cycle_tree_preview(self._splittree_viz_data)

    def _on_refresh_pedigree_tree(self) -> None:
        if self._pedigree_result is None or self._db_path is None:
            return
        self._update_pedigree_graphviz_banner()
        session_dir = session_pedigree_dir(self._db_path)
        tree_path = session_dir / "pedigree_tree.png"
        try:
            self._render_pedigree_tree_image(self._pedigree_result, tree_path)
            self._show_pedigree_tree_preview(self._pedigree_result)
            if self._pedigree_status_label is not None:
                engine = self._pedigree_result.tree_render_engine or "unknown"
                self._pedigree_status_label.configure(
                    text=f"Tree refreshed ({engine}).",
                    text_color=("gray10", "gray90"),
                )
        except Exception as exc:
            messagebox.showerror("Pedigree tree", str(exc), parent=self)

    def _sorted_bb1_branch_names(self, data: DelCycleTreeData) -> List[str]:
        """BB1 branch names sorted by display index (#N), then alphabetically."""
        null = data.null_token
        names = [name for name in data.bb1_names if name != null]
        return sorted(
            names,
            key=lambda name: (
                lookup_bb_display_index(name, data.bb_index_global, null_token=null)
                or 10**9,
                name.lower(),
            ),
        )

    def _resolve_del_branch_bb1(
        self,
        data: DelCycleTreeData,
        selection: str = "",
    ) -> str:
        """Map branch dropdown text (``#N name`` or raw name) to a BB1 tree key."""
        selection = (selection or self._pedigree_del_branch_var.get()).strip()
        null = data.null_token
        branches = self._sorted_bb1_branch_names(data)
        if not branches:
            return ""
        if selection in self._del_branch_label_to_name:
            return self._del_branch_label_to_name[selection]
        if selection in branches:
            return selection
        if selection.startswith("#"):
            _, _, name = selection.partition(" ")
            if name in branches:
                return name
        for name in branches:
            label = format_bb_branch_label(
                name,
                data.bb_index_global,
                null_token=null,
            )
            if selection == label:
                return name
        return branches[0]

    def _update_del_branch_choices(self, data: DelCycleTreeData) -> None:
        null = data.null_token
        bb1_names = self._sorted_bb1_branch_names(data)
        self._del_branch_label_to_name = {
            format_bb_branch_label(name, data.bb_index_global, null_token=null): name
            for name in bb1_names
        }
        choices = list(self._del_branch_label_to_name.keys()) or ["—"]
        if self._pedigree_del_branch_menu is not None:
            self._pedigree_del_branch_menu.configure(values=choices)
        current_bb1 = self._resolve_del_branch_bb1(data)
        if current_bb1:
            self._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    current_bb1,
                    data.bb_index_global,
                    null_token=null,
                )
            )
        elif choices:
            self._pedigree_del_branch_var.set(choices[0])

    def _update_del_tree_status_note(self, data: DelCycleTreeData) -> None:
        if self._pedigree_tree_node_count_label is None:
            return
        picker = data.peak_picking_algorithm or "—"
        picker_label = "old-school Gaussian" if picker == "old_school" else (
            "modern NB" if picker == "modern" else picker
        )
        agree_note = ""
        if data.pedigree_passed_by_product and data.n_rt_verified_pedigree_agree is not None:
            compared = sum(
                1
                for positions in data.verified_sequences
                if len(positions) == data.library_cycle_count
                and positions in data.pedigree_passed_by_product
            )
            if compared:
                agree_note = (
                    f" · RT verify vs pedigree agree: "
                    f"{data.n_rt_verified_pedigree_agree:,}/{compared:,}"
                )
        iso = self._splittree_viz_isoform or self._splittree_isoform_label()
        iso_note = f" · isoform: {iso}" if iso and iso != "All" else ""
        if self._splittree_status_label is not None:
            self._splittree_status_label.configure(
                text=(
                    f"DEL rows: {data.n_rows:,} · RT verified: {data.n_verified:,} · "
                    f"pedigree passed: {data.n_pedigree_passed:,} · "
                    f"RT: {data.rt_source} (pedigree={data.n_rt_from_pedigree:,}, "
                    f"direct-pick={data.n_rt_from_peak_pick:,}, "
                    f"metadata={data.n_rt_from_metadata:,}) · "
                    f"picker: {picker_label} · null RT threshold: {data.rt_threshold:g}"
                    f"{agree_note}{iso_note}"
                ),
                wraplength=_SIDEBAR_WRAP,
                justify="left",
            )

    def _refresh_tree_display(self, *, force_rebuild_del: bool = False) -> None:
        if force_rebuild_del or self._del_cycle_tree_data is None:
            self._refresh_del_cycle_tree()
        elif self._del_cycle_tree_data is not None:
            self._show_del_cycle_tree_preview(self._del_cycle_tree_data)
        if self._pedigree_result is not None:
            self._show_pedigree_tree_preview(self._pedigree_result)

    def _active_main_tab(self) -> str:
        if self._content_tabview is None:
            return ""
        try:
            return self._content_tabview.get()
        except (ValueError, tk.TclError):
            return ""

    def _update_rt_assignment_results(
        self,
        data: Optional[DelCycleTreeData] = None,
        *,
        pedigree_result: Optional[PedigreeAnalysisResult] = None,
    ) -> None:
        if self._rt_assignment_results_label is None:
            return
        if pedigree_result is not None:
            picker = pedigree_result.settings.peak_picking_algorithm
            lines = [
                f"Mode: pedigree ({picker} peak picking)",
                f"Nodes evaluated: {len(pedigree_result.records):,}",
                f"Chromatograms: {pedigree_result.n_chromatograms:,}",
                "Open Pedigree visualization to view the tier-ring figure.",
            ]
            if data is not None:
                lines.append(
                    f"DEL verification (optional): {data.n_verified:,} RT-verified products."
                )
            self._rt_assignment_results_label.configure(text="\n".join(lines))
            return
        if data is None:
            self._rt_assignment_results_label.configure(text="No RT assignment run yet.")
            return
        picker = data.peak_picking_algorithm or "—"
        self._rt_assignment_results_label.configure(
            text=(
                f"Mode: direct pick ({picker} peak picking)\n"
                f"RT source: {data.rt_source}\n"
                f"Products with RT: {data.n_rows:,}\n"
                f"RT verified: {data.n_verified:,}\n"
                f"From pedigree lookup: {data.n_rt_from_pedigree:,} · "
                f"direct pick: {data.n_rt_from_peak_pick:,} · "
                f"metadata: {data.n_rt_from_metadata:,}\n"
                "Open Split-tree visualization to view the DEL split-tree."
            )
        )

    def _on_run_rt_assignment(self) -> None:
        self._splittree_viz_data = None
        self._splittree_artifact = None
        self._rt_assignment_artifact = None
        self._pedigree_viz_artifact = None
        # Keep _del_cycle_tree_data until a new RT assignment completes successfully.
        if self._rt_analysis_mode_var.get() == _RT_ANALYSIS_PEDIGREE:
            self._last_rt_analysis_mode = _RT_ANALYSIS_PEDIGREE
            self._on_run_pedigree()
        else:
            self._last_rt_analysis_mode = _RT_ANALYSIS_DIRECT
            self._on_run_direct_pick_assignment()

    def _on_run_direct_pick_assignment(self) -> None:
        if self._is_busy():
            return
        if self._data_store is None or self._db_path is None or self._config is None:
            return
        if not self._config.pedigree_configured():
            messagebox.showinfo(
                "RT assignment",
                "Map BB1..BBn columns in Configure Spreadsheet before assigning RTs.",
                parent=self,
            )
            return
        if self._parse_pedigree_settings() is None:
            return
        channel = self._pedigree_channel_var.get().strip()
        if self._cached_scan is not None and channel:
            if channel not in self._cached_scan.channel_names:
                messagebox.showinfo(
                    "RT assignment",
                    f"Channel “{channel}” is not in the cached library scan.\n\n"
                    f"Available: {', '.join(self._cached_scan.channel_names) or 'none'}.\n\n"
                    "Re-run library scan with this channel selected, or clear the scan "
                    "to read chromatograms from the database.",
                    parent=self,
                )
                return
        if self._data_store.get_compound_count() == 0:
            messagebox.showinfo("RT assignment", "The database has no compounds.", parent=self)
            return
        self._focus_tab(_TAB_RT_ASSIGNMENT)
        self._refresh_del_cycle_tree(render_figure=False)

    def _refresh_del_cycle_tree(
        self,
        *,
        render_figure: bool = True,
        show_loading: bool = True,
    ) -> None:
        if self._is_busy():
            return
        if self._data_store is None or self._config is None:
            return
        if not self._config.pedigree_configured():
            messagebox.showinfo(
                "DEL-cycle tree",
                "Map BB1..BBn columns in Configure Spreadsheet before building the tree.",
                parent=self,
            )
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return
        channel = self._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showinfo("DEL-cycle tree", "Select a channel first.", parent=self)
            return

        scan = self._cached_scan
        self._del_build_show_loading = show_loading
        if show_loading:
            scan_note = (
                "Using cached library scan chromatograms…"
                if scan is not None
                else "Loading chromatograms from database…"
            )
            self._show_loading_page(
                "Assigning retention times",
                scan_note,
            )
        assert self._db_path is not None
        db_path = self._db_path
        config = self._config
        use_pedigree = (
            self._pedigree_result is not None
            and self._last_rt_analysis_mode == _RT_ANALYSIS_PEDIGREE
        )
        pedigree_result = self._pedigree_result if use_pedigree else None
        rt_threshold = float(settings.tolerance)
        time_unit = settings.time_unit
        color_by_rt = bool(self._pedigree_del_color_rt_var.get())
        color_mode = self._del_tree_color_mode()
        pass_pct_cutoff = self._read_del_tree_pass_pct_cutoff()
        view_mode = self._splittree_view_mode_var.get()
        branch_selection = self._pedigree_del_branch_var.get().strip()
        render_figure = False

        def worker() -> None:
            try:
                def progress(step: int, total: int, status: str) -> None:
                    if not self._del_build_show_loading:
                        return
                    if total == 1000:
                        fraction = step / 1000.0
                    else:
                        fraction = step / total if total > 0 else 0.0
                    self._thread_loading_progress(
                        min(0.95, fraction),
                        status or "Resolving retention times…",
                    )

                data = build_del_cycle_tree_for_path(
                    db_path,
                    config,
                    settings,
                    channel,
                    time_unit,  # type: ignore[arg-type]
                    rt_threshold=rt_threshold,
                    pedigree_result=pedigree_result,
                    isoform_label="All",
                    scan=scan,
                    use_metadata_rt=False,
                    progress_callback=progress,
                )
                figure = None
                selected_branch = branch_selection
                if render_figure:
                    view = (
                        DelCycleTreeView.BRANCH
                        if view_mode == _SPLITTREE_VIEW_BRANCH
                        else DelCycleTreeView.FULL
                    )
                    if view == DelCycleTreeView.BRANCH:
                        branches = self._sorted_bb1_branch_names(data)
                        resolved = self._resolve_del_branch_bb1(data, branch_selection)
                        if resolved in branches:
                            selected_branch = resolved
                        elif branches:
                            selected_branch = branches[0]
                    self._thread_loading_progress(0.96, "Rendering split-tree figure…")
                    figure = render_del_cycle_tree_figure(
                        data,
                        view=view,
                        branch_bb1=selected_branch if view == DelCycleTreeView.BRANCH else None,
                        color_by_rt=color_by_rt,
                        color_mode=color_mode,
                        pass_pct_cutoff=pass_pct_cutoff,
                    )
                self._bind_worker_callback(
                    self._on_del_cycle_tree_ready,
                    data,
                    figure,
                    selected_branch,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("DEL-cycle tree build failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_del_cycle_tree_failed, str(exc))

        self._start_worker(worker)

    def _on_del_cycle_tree_ready(
        self,
        data: DelCycleTreeData,
        figure: Optional[object],
        selected_branch: str,
    ) -> None:
        self._worker_thread = None
        self._del_cycle_tree_data = data
        self._del_cycle_tree_isoform = "All"
        if self._splittree_rt_source_var.get() == _SPLITTREE_RT_SESSION:
            self._splittree_viz_data = data
            self._splittree_viz_isoform = "All"
        self._update_del_branch_choices(data)
        if selected_branch:
            self._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected_branch,
                    data.bb_index_global,
                    null_token=data.null_token,
                )
            )
        self._update_del_tree_status_note(data)
        self._update_rt_assignment_results(data)
        settings = self._peek_pedigree_settings()
        if settings is not None:
            mode = self._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
            self._capture_rt_assignment_artifact(
                data,
                analysis_mode=mode,
                settings=settings,
                isoform=self._del_cycle_tree_isoform or "All",
            )
        if figure is not None and self._splittree_viz_data is data:
            self._mount_splittree_figure(figure)
        if self._pedigree_status_label is not None:
            self._pedigree_status_label.configure(
                text=(
                    f"RT assignment ready — {data.n_verified:,} RT-verified of "
                    f"{len(data.verified_sequences):,} products (source: {data.rt_source})."
                ),
                text_color=("gray10", "gray90"),
            )
        if self._del_build_show_loading:
            self._hide_loading_page()
        self._update_action_states()

    def _on_del_cycle_tree_failed(self, message: str) -> None:
        self._worker_thread = None
        if self._del_build_show_loading:
            self._hide_loading_page()
        if not message.strip():
            self._update_action_states()
            return
        self._show_splittree_placeholder(message)
        if self._pedigree_status_label is not None:
            self._pedigree_status_label.configure(text=message, text_color="#D29922")
        messagebox.showerror("RT assignment", message, parent=self)
        self._update_action_states()

    def _show_del_cycle_tree_preview(self, data: DelCycleTreeData) -> None:
        try:
            view = (
                DelCycleTreeView.BRANCH
                if self._is_del_branch_viz_mode()
                else DelCycleTreeView.FULL
            )
            branch = self._resolve_del_branch_bb1(data)
            figure = render_del_cycle_tree_figure(
                data,
                view=view,
                branch_bb1=branch if view == DelCycleTreeView.BRANCH else None,
                color_by_rt=bool(self._pedigree_del_color_rt_var.get()),
                color_mode=self._del_tree_color_mode(),
                pass_pct_cutoff=self._read_del_tree_pass_pct_cutoff(),
            )
            self._update_del_tree_status_note(data)
            self._mount_splittree_figure(figure)
        except Exception as exc:
            self._show_splittree_placeholder(str(exc))

    def _render_pedigree_tree_image(
        self,
        result: PedigreeAnalysisResult,
        tree_path: Path,
        *,
        fmt: str = "png",
    ):
        """Render split-tree using current display controls."""
        opts = self._pedigree_tree_render_options()
        result.max_display_tier = opts.max_display_tier
        render_out = render_pedigree_tree(
            result.records,
            tree_path,
            fmt=fmt,
            max_display_tier=opts.max_display_tier,
            include_failed=opts.include_failed,
            show_rt=opts.show_rt,
        )
        result.tree_image_path = render_out.path
        result.tree_render_engine = render_out.engine
        result.tree_render_note = render_out.detail
        self._update_pedigree_tree_density_note(result)
        return render_out

    def _on_run_pedigree(self) -> None:
        if self._is_busy():
            return
        if self._cached_scan is None:
            messagebox.showinfo(
                "Pedigree",
                "Run library scan first (top bar). Pedigree analysis reuses the cached scan.",
                parent=self,
            )
            return
        if self._data_store is None or self._db_path is None or self._config is None:
            return
        if not self._config.pedigree_configured():
            messagebox.showinfo(
                "Pedigree",
                "Map BB1..BBn columns in Configure Spreadsheet before running pedigree.",
                parent=self,
            )
            return
        if not pedigree_backend_available():
            messagebox.showerror(
                "Pedigree",
                "The Rust lcseq extension is required.\n\nSee docs/DEVELOPER_SETUP.md.",
                parent=self,
            )
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return
        if self._data_store.get_compound_count() == 0:
            messagebox.showinfo("Pedigree", "The database has no compounds.", parent=self)
            return
        n = self._data_store.get_compound_count()
        if not messagebox.askyesno(
            "Pedigree analysis",
            f"Run full-library pedigree evaluation on {n:,} compound(s)?\n\n"
            "Chromatograms are taken from the cached library scan; only metadata "
            "is read from the database.",
            parent=self,
        ):
            return
        self._start_pedigree_analysis(settings)

    def _on_run_del_cycle_analysis(self) -> None:
        """Legacy alias — direct-pick RT assignment."""
        self._rt_analysis_mode_var.set(_RT_ANALYSIS_DIRECT)
        self._on_run_rt_assignment()

    def _start_pedigree_analysis(
        self,
        settings: AnalysisSettings,
    ) -> None:
        assert self._db_path is not None and self._config is not None
        self._show_loading_page(
            "Running pedigree RT assignment",
            "Building chromatogram map from scan and evaluating pedigree…",
        )
        if self._pedigree_status_label is not None:
            self._pedigree_status_label.configure(text="Pedigree analysis running…")
        self._update_action_states()

        db_path = self._db_path
        config = self._config
        scan = self._cached_scan
        assert scan is not None

        def worker() -> None:
            try:
                def progress(step: int, total: int, status: str) -> None:
                    fraction = (step + 1) / total if total > 0 else 0.0
                    self._thread_loading_progress(
                        min(0.95, fraction),
                        status or "Evaluating pedigree…",
                    )

                result = run_pedigree_analysis_for_path(
                    db_path,
                    config,
                    settings,
                    scan=scan,
                    progress_callback=progress,
                    isoform_label="All",
                )
                tree_opts = build_default_tree_render_options(
                    result.records,
                    library_cycle_count=result.library_cycle_count,
                )
                result.max_display_tier = tree_opts.max_display_tier
                session_dir = session_pedigree_dir(db_path)
                tree_path = session_dir / "pedigree_tree.png"
                try:
                    render_out = render_pedigree_tree(
                        result.records,
                        tree_path,
                        max_display_tier=tree_opts.max_display_tier,
                        include_failed=tree_opts.include_failed,
                        show_rt=tree_opts.show_rt,
                    )
                    result.tree_image_path = render_out.path
                    result.tree_render_engine = render_out.engine
                    result.tree_render_note = render_out.detail
                except Exception as exc:
                    logger.error("Pedigree tree render failed: %s", exc, exc_info=True)
                    result.tree_render_note = f"Tree image could not be generated: {exc}"
                    tree_opts = None
                self._bind_worker_callback(self._on_pedigree_ready, result, tree_opts)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Pedigree analysis failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_pedigree_failed, str(exc))

        self._start_worker(worker)

    def _on_pedigree_ready(
        self,
        result: PedigreeAnalysisResult,
        tree_opts: Optional[PedigreeTreeRenderOptions] = None,
    ) -> None:
        self._worker_thread = None
        self._pedigree_result = result
        self._pedigree_snapshot_path = None
        self._update_pedigree_graphviz_banner()
        self._update_rt_assignment_results(pedigree_result=result)
        if tree_opts is not None:
            self._pedigree_show_rt_var.set(tree_opts.show_rt)
            self._configure_pedigree_tier_slider(result)
            self._update_pedigree_tree_density_note(result)
            # In-app preview defaults to showing failed trim points for coloring.
            self._pedigree_include_failed_var.set(True)
        self._display_pedigree_result(result)
        try:
            self._capture_pedigree_viz_artifact(result)
        except Exception as exc:
            logger.warning("Could not capture pedigree report artifact: %s", exc)
        if self._pedigree_status_label is not None:
            status = (
                f"Pedigree RT assignment ready — {len(result.records):,} nodes, "
                f"{result.n_chromatograms:,} chromatograms."
            )
            if result.tree_render_engine:
                status += f" Tree: {result.tree_render_engine}."
            if result.tree_render_note and result.tree_image_path is None:
                status += f" {result.tree_render_note}"
            self._pedigree_status_label.configure(
                text=status,
                text_color=("gray10", "gray90"),
            )
        if self._content_tabview is not None:
            try:
                self._content_tabview.set(_TAB_RT_ASSIGNMENT)
            except ValueError:
                pass
        self._hide_loading_page()
        self._update_action_states()
        self._focus_tab(_TAB_PEDIGREE_VIZ)
        self._build_del_cycle_artifacts_after_pedigree()

    def _build_del_cycle_artifacts_after_pedigree(self) -> None:
        """Build DEL-cycle data for exports without blocking the UI."""
        if self._pedigree_result is None or self._is_busy():
            return
        self._last_rt_analysis_mode = _RT_ANALYSIS_PEDIGREE
        self._refresh_del_cycle_tree(render_figure=False, show_loading=False)

    def _on_pedigree_failed(self, message: str) -> None:
        self._worker_thread = None
        if self._pedigree_status_label is not None:
            self._pedigree_status_label.configure(text=message, text_color="#D29922")
        self._hide_loading_page()
        messagebox.showerror("Pedigree analysis", message, parent=self)
        self._update_action_states()

    def _display_pedigree_result(self, result: PedigreeAnalysisResult) -> None:
        if self._pedigree_summary_label is not None:
            self._pedigree_summary_label.configure(
                text=self._format_pedigree_summary(result),
                text_color=("gray10", "gray90"),
            )
        self._clear_frame_children(self._pedigree_frame)
        if self._pedigree_frame is not None:
            total_pass = sum(s.pass_count for s in result.tier_summaries)
            total_fail = sum(s.fail_count for s in result.tier_summaries)
            total_pruned = sum(s.pruned_count for s in result.tier_summaries)
            header = self._make_info_card(
                self._pedigree_frame,
                "Library totals",
                (
                    f"{len(result.records):,} nodes — passed={total_pass:,}, "
                    f"failed={total_fail:,}, pruned={total_pruned:,} · "
                    f"engine {result.backend_name}"
                ),
                wraplength=_SIDEBAR_WRAP,
            )
            header.pack(fill="x", pady=(0, 8))
            if result.tier_summaries:
                self._make_tier_summary_panel(self._pedigree_frame, result.tier_summaries)
            else:
                ctk.CTkLabel(
                    self._pedigree_frame,
                    text="No per-tier counts were returned for this run.",
                    font=ctk.CTkFont(size=11),
                    text_color="gray",
                    anchor="w",
                    wraplength=_SIDEBAR_WRAP,
                    justify="left",
                ).pack(fill="x", pady=4)
        if self._pedigree_result is not None:
            self._show_pedigree_tree_preview(self._pedigree_result)

    def _make_tier_summary_panel(
        self,
        parent: ctk.CTkScrollableFrame,
        summaries: List[PedigreeTierSummary],
    ) -> ctk.CTkFrame:
        """Per-tier pass / fail / pruned counts (one row per coupling cycle)."""
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", pady=4)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text="By coupling tier",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            card,
            text=(
                "Each tier is one coupling cycle in the pedigree tree. "
                "Passed = RT-consistent nodes; failed = synthesis dropped; "
                "pruned = unevaluated because a parent failed."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        table = ctk.CTkFrame(card, fg_color="transparent")
        table.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="ew")
        for col, weight in enumerate((0, 1, 1, 1)):
            table.grid_columnconfigure(col, weight=weight)

        for col, title in enumerate(("Tier", "Pass", "Fail", "Prune")):
            ctk.CTkLabel(
                table,
                text=title,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="e" if col else "w",
            ).grid(row=0, column=col, padx=(0 if col == 0 else 4, 0), pady=(0, 4), sticky="ew")

        for row_idx, summary in enumerate(summaries, start=1):
            values = (
                str(summary.tier),
                f"{summary.pass_count:,}",
                f"{summary.fail_count:,}",
                f"{summary.pruned_count:,}",
            )
            for col, value in enumerate(values):
                ctk.CTkLabel(
                    table,
                    text=value,
                    font=ctk.CTkFont(size=12, weight="bold" if col else "normal"),
                    anchor="e" if col else "w",
                ).grid(
                    row=row_idx,
                    column=col,
                    padx=(0 if col == 0 else 4, 0),
                    pady=2,
                    sticky="ew",
                )
        return card

    _PEDIGREE_HELP_MENU: Tuple[Tuple[str, str], ...] = (
        ("pedigree_analysis", "Pedigree analysis"),
        ("pedigree_split_tree", "Split-tree figure"),
        ("del_cycle_bundle_glossary", "Export analysis bundle glossary"),
    )

    def _show_pedigree_help_menu(self) -> None:
        """Show pedigree-tab help topics in a dropdown menu."""
        menu = tk.Menu(self, tearoff=0)
        for topic_id, label in self._PEDIGREE_HELP_MENU:
            menu.add_command(
                label=label,
                command=lambda tid=topic_id: self._open_pedigree_help_topic(tid),
            )
        btn = self._pedigree_help_btn
        if btn is None:
            return
        try:
            menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
        finally:
            menu.grab_release()

    def _open_pedigree_help_topic(self, topic_id: str) -> None:
        from src.ui.help_window import open_help_window

        open_help_window(self, topic_id)

    def _on_pedigree_help(self) -> None:
        self._open_pedigree_help_topic("pedigree_analysis")

    def _clear_pedigree_tree_plot(self) -> None:
        """Release matplotlib canvas/toolbar used for the interactive tree preview."""
        if self._pedigree_tree_toolbar is not None:
            try:
                self._pedigree_tree_toolbar.destroy()
            except tk.TclError:
                pass
            self._pedigree_tree_toolbar = None
        if self._pedigree_tree_canvas is not None:
            try:
                self._pedigree_tree_canvas.get_tk_widget().destroy()
            except tk.TclError:
                pass
            self._pedigree_tree_canvas = None
        if self._pedigree_tree_figure is not None:
            try:
                import matplotlib.pyplot as plt

                plt.close(self._pedigree_tree_figure)
            except Exception:
                pass
            self._pedigree_tree_figure = None

    def _show_pedigree_tree_placeholder(self, message: str) -> None:
        self._clear_pedigree_tree_plot()
        if self._pedigree_tree_plot_host is not None:
            self._pedigree_tree_plot_host.grid_remove()
        if self._pedigree_tree_placeholder is not None:
            self._pedigree_tree_placeholder.configure(text=message)
            self._pedigree_tree_placeholder.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _mount_pedigree_tree_figure(self, figure) -> None:
        """Embed a matplotlib figure with pan/zoom toolbar in the pedigree tab."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

        self._clear_pedigree_tree_plot()
        if self._pedigree_tree_placeholder is not None:
            self._pedigree_tree_placeholder.grid_remove()
        if self._pedigree_tree_plot_host is None:
            return
        self._pedigree_tree_plot_host.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._pedigree_tree_figure = figure
        self._pedigree_tree_canvas = FigureCanvasTkAgg(figure, master=self._pedigree_tree_plot_host)
        self._pedigree_tree_canvas.draw()
        self._pedigree_tree_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._pedigree_tree_toolbar = NavigationToolbar2Tk(
            self._pedigree_tree_canvas,
            self._pedigree_tree_plot_host,
        )
        self._pedigree_tree_toolbar.update()
        self._pedigree_tree_toolbar.pack(side=tk.BOTTOM, fill=tk.X)

    def _clear_splittree_tree_plot(self) -> None:
        if self._splittree_tree_toolbar is not None:
            try:
                self._splittree_tree_toolbar.destroy()
            except tk.TclError:
                pass
            self._splittree_tree_toolbar = None
        if self._splittree_tree_canvas is not None:
            try:
                self._splittree_tree_canvas.get_tk_widget().destroy()
            except tk.TclError:
                pass
            self._splittree_tree_canvas = None
        if self._splittree_tree_figure is not None:
            try:
                import matplotlib.pyplot as plt

                plt.close(self._splittree_tree_figure)
            except Exception:
                pass
            self._splittree_tree_figure = None

    def _show_splittree_placeholder(self, message: str) -> None:
        self._clear_splittree_tree_plot()
        if self._splittree_tree_plot_host is not None:
            self._splittree_tree_plot_host.grid_remove()
        if self._splittree_tree_placeholder is not None:
            self._splittree_tree_placeholder.configure(text=message)
            self._splittree_tree_placeholder.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _mount_splittree_figure(self, figure) -> None:
        """Embed a matplotlib figure with pan/zoom toolbar in the split-tree tab."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

        self._clear_splittree_tree_plot()
        if self._splittree_tree_placeholder is not None:
            self._splittree_tree_placeholder.grid_remove()
        if self._splittree_tree_plot_host is None:
            return
        self._splittree_tree_plot_host.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._splittree_tree_figure = figure
        self._splittree_tree_canvas = FigureCanvasTkAgg(
            figure,
            master=self._splittree_tree_plot_host,
        )
        self._splittree_tree_canvas.draw()
        self._splittree_tree_canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._splittree_tree_toolbar = NavigationToolbar2Tk(
            self._splittree_tree_canvas,
            self._splittree_tree_plot_host,
        )
        self._splittree_tree_toolbar.update()
        self._splittree_tree_toolbar.pack(side=tk.BOTTOM, fill=tk.X)

    def _show_pedigree_tree_preview(self, result: PedigreeAnalysisResult) -> None:
        if self._pedigree_tree_host is None:
            return
        if not result.records:
            self._show_pedigree_tree_placeholder("No pedigree nodes to display.")
            return
        image_path = result.tree_image_path
        if image_path is None or not Path(image_path).is_file():
            if result.tree_render_engine != "matplotlib":
                message = result.tree_render_note or (
                    "Tree image could not be generated. Check logs for details."
                )
                self._show_pedigree_tree_placeholder(message)
                return
        try:
            opts = self._pedigree_tree_render_options()
            figure = build_pedigree_tree_preview_figure(
                result.records,
                image_path,
                render_engine=result.tree_render_engine,
                max_display_tier=opts.max_display_tier,
                include_failed=opts.include_failed,
                show_rt=opts.show_rt,
            )
            self._mount_pedigree_tree_figure(figure)
        except Exception as exc:
            logger.warning("Could not build interactive pedigree tree preview: %s", exc)
            fallback = (
                f"Tree saved at:\n{image_path}"
                if image_path
                else "Tree preview could not be built."
            )
            self._show_pedigree_tree_placeholder(fallback)

    def _on_export_pedigree_csv(self) -> None:
        if self._pedigree_result is None:
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export pedigree CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not dest:
            return
        try:
            export_pedigree_csv(self._pedigree_result, dest)
            messagebox.showinfo("Pedigree", f"Saved to:\n{dest}", parent=self)
        except Exception as exc:
            messagebox.showerror("Pedigree", str(exc), parent=self)

    def _on_export_assigned_rts(self) -> None:
        if self._is_busy():
            return
        if self._pedigree_result is None and self._del_cycle_tree_data is None:
            messagebox.showinfo(
                "Export RTs",
                "Run RT assignment first.",
                parent=self,
            )
            return
        if self._config is None or self._db_path is None:
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return
        channel = self._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showinfo("Export RTs", "Select a channel first.", parent=self)
            return

        source_path: Optional[Path] = None
        if self.app_state.spreadsheet_path:
            candidate = Path(self.app_state.spreadsheet_path)
            if candidate.is_file():
                source_path = candidate

        if source_path is not None:
            default_name = f"{source_path.stem}_rt_analysis{source_path.suffix or '.xlsx'}"
            default_ext = source_path.suffix or ".xlsx"
        else:
            default_name = f"{self._db_path.stem}_rt_analysis.xlsx"
            default_ext = ".xlsx"

        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export RT analysis to spreadsheet",
            initialfile=default_name,
            defaultextension=default_ext,
            filetypes=[
                ("Excel", "*.xlsx"),
                ("CSV", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return

        db_path = self._db_path
        config = self._config
        scan = self._cached_scan
        del_data = self._del_cycle_tree_data
        use_pedigree = (
            self._pedigree_result is not None
            and self._last_rt_analysis_mode == _RT_ANALYSIS_PEDIGREE
        )
        pedigree_result = self._pedigree_result if use_pedigree else None
        time_unit = settings.time_unit
        rt_threshold = float(settings.tolerance)
        sheet_name = self.config_manager.load_settings().last_loaded_sheet

        self._show_loading_page(
            "Exporting RT analysis",
            "Resolving assigned retention times and null verification…",
        )

        def worker() -> None:
            try:
                store = DataStore(db_path=db_path, use_memory=False)
                try:
                    def load_progress(processed: int, total: int, status: str) -> None:
                        fraction = processed / total if total else 0.0
                        self._thread_loading_progress(
                            min(0.45, 0.05 + 0.4 * fraction),
                            status or "Loading library metadata…",
                        )

                    compounds = load_compounds_for_export(
                        store,
                        config,
                        progress_callback=load_progress,
                    )

                    self._thread_loading_progress(
                        0.55,
                        "Building RT assignments from session results…",
                    )
                    if del_data is not None:
                        assignments = build_assignments_from_del_cycle_tree(
                            compounds,
                            config,
                            del_data,
                            pedigree_result=pedigree_result,
                        )
                    else:
                        assignments = resolve_compound_rt_assignments_for_path(
                            db_path,
                            config,
                            settings,
                            channel,
                            time_unit,  # type: ignore[arg-type]
                            pedigree_result=pedigree_result,
                            isoform_label="All",
                            scan=scan,
                            use_metadata_rt=False,
                        )

                    spreadsheet_rows = None
                    if source_path is None:
                        def row_progress(processed: int, total: int, status: str) -> None:
                            fraction = processed / total if total else 0.0
                            self._thread_loading_progress(
                                min(0.72, 0.58 + 0.14 * fraction),
                                status or "Preparing export rows…",
                            )

                        spreadsheet_rows = build_spreadsheet_rows_from_compounds(
                            compounds,
                            config,
                            store,
                            progress_callback=row_progress,
                        )

                    self._thread_loading_progress(0.78, "Writing spreadsheet…")
                    result = export_rt_analysis_spreadsheet(
                        dest,
                        config,
                        assignments,
                        source_path=source_path,
                        sheet_name=sheet_name,
                        time_unit=time_unit,
                        rt_threshold=rt_threshold,
                        spreadsheet_rows=spreadsheet_rows,
                    )
                    self._bind_worker_callback(self._on_export_rts_ready, result)
                finally:
                    store.close()
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("RT spreadsheet export failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_export_rts_failed, str(exc))

        self._start_worker(worker)
        self._update_action_states()

    def _on_export_rts_ready(self, result) -> None:
        self._worker_thread = None
        self._hide_loading_page()
        self._update_action_states()
        if self._pedigree_status_label is not None:
            self._pedigree_status_label.configure(
                text=(
                    f"Exported RTs — {result.rows_assigned:,} of "
                    f"{result.rows_written:,} row(s) assigned."
                ),
                text_color="green",
            )
        messagebox.showinfo(
            "Export RTs",
            f"Saved to:\n{result.output_path}\n\n"
            f"Assigned RTs for {result.rows_assigned:,} of {result.rows_written:,} row(s).\n"
            f"Null pass/fail recorded for {result.rows_with_verification:,} full product(s).",
            parent=self,
        )

    def _on_export_rts_failed(self, message: str) -> None:
        self._worker_thread = None
        self._hide_loading_page()
        self._update_action_states()
        messagebox.showerror("Export RTs", message, parent=self)

    def _on_export_del_cycle_csv(self) -> None:
        if self._is_busy():
            return
        if self._del_cycle_tree_data is None:
            messagebox.showinfo(
                "Analysis bundle",
                "Run RT assignment first to build analysis data.",
                parent=self,
            )
            return
        dest = filedialog.askdirectory(
            parent=self,
            title="Select folder for DEL-cycle export",
        )
        if not dest:
            return

        del_data = self._del_cycle_tree_data
        pedigree_result = self._pedigree_result
        analysis_settings = self._peek_pedigree_settings()
        rt_analysis_mode = self._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
        self._show_loading_page(
            "Exporting analysis bundle",
            "Starting export…",
        )

        def worker() -> None:
            try:
                def export_progress(fraction: float, status: str) -> None:
                    self._thread_loading_progress(fraction, status)

                result = export_del_cycle_package(
                    del_data,
                    dest,
                    analysis_settings=analysis_settings,
                    rt_analysis_mode=rt_analysis_mode,
                    pedigree_result=pedigree_result,
                    progress_callback=export_progress,
                )
                self._bind_worker_callback(
                    self._on_del_cycle_export_ready,
                    result,
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("DEL-cycle export failed: %s", exc, exc_info=True)
                self._bind_worker_callback(self._on_del_cycle_export_failed, str(exc))

        self._start_worker(worker)
        self._update_action_states()

    def _on_del_cycle_export_ready(
        self,
        result: DelCycleExportResult,
    ) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._update_loading_progress(
            1.0,
            f"Exported {result.file_count} file(s) to {result.output_dir.name}",
        )

        def finish() -> None:
            if not self._ui_is_active():
                return
            self._hide_loading_page()
            self._update_action_states()
            if self._pedigree_status_label is not None:
                self._pedigree_status_label.configure(
                    text=f"Analysis bundle saved — {result.file_count} file(s) in {result.output_dir}",
                    text_color="green",
                )
            extra = ""
            if result.prominence_csv is not None:
                extra = f"\n- {result.prominence_csv.name}"
            messagebox.showinfo(
                "Analysis bundle",
                f"Exported {result.file_count} file(s) to:\n{result.output_dir}\n\n"
                f"- {result.products_csv.name}\n"
                f"- {result.audit_csv.name}\n"
                f"- {result.summary_csv.name}\n"
                f"- {result.flagged_csv.name}"
                + extra
                + (
                    f"\n- {len(result.grid_files)} grid workbook(s) in grids/"
                    if result.grid_files
                    else "\n- (no BB1 grids — requires a 3-cycle library)"
                ),
                parent=self,
            )

        self.after(30, finish)

    def _on_del_cycle_export_failed(self, message: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        try:
            self._loading_detail.configure(text=f"Export failed: {message}", text_color="red")
            self._loading_percent.configure(text="")
        except tk.TclError:
            pass
        self._hide_loading_page()
        self._update_action_states()
        messagebox.showerror("DEL-cycle tree", message, parent=self)

    def _on_export_pedigree_tree(self) -> None:
        if self._pedigree_result is None:
            return
        if not graphviz_available():
            if not messagebox.askyesno(
                "Pedigree export",
                "Graphviz is not installed; export will use the matplotlib tier-ring "
                "layout instead of the native split-tree engine.\n\nContinue?",
                parent=self,
            ):
                return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export pedigree tree",
            defaultextension=".png",
            filetypes=[
                ("PNG", "*.png"),
                ("SVG vector", "*.svg"),
                ("PDF", "*.pdf"),
            ],
        )
        if not dest:
            return
        try:
            fmt = Path(dest).suffix.lstrip(".") or "png"
            opts = self._pedigree_tree_render_options()
            render_out = render_pedigree_tree(
                self._pedigree_result.records,
                Path(dest),
                fmt=fmt,
                max_display_tier=opts.max_display_tier,
                include_failed=opts.include_failed,
                show_rt=opts.show_rt,
            )
            messagebox.showinfo(
                "Pedigree",
                f"Saved to:\n{render_out.path}\n\n({render_out.engine})",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Pedigree", str(exc), parent=self)

    def _on_save_pedigree(self) -> None:
        if self._pedigree_result is None:
            return
        try:
            saved = save_pedigree_result(self._pedigree_result)
            self._pedigree_snapshot_path = saved
            messagebox.showinfo(
                "Pedigree",
                f"Saved pedigree snapshot to:\n{saved}",
                parent=self,
            )
            self._update_action_states()
        except Exception as exc:
            messagebox.showerror("Pedigree", str(exc), parent=self)

    def _on_load_last_pedigree(self) -> None:
        if self._db_path is None:
            return
        path = get_latest_pedigree_snapshot_path(self._db_path)
        if path is None:
            messagebox.showinfo("Pedigree", "No saved pedigree run for this database.", parent=self)
            return
        self._load_pedigree_from_path(path)

    def _on_browse_pedigree(self) -> None:
        initial = str(get_pedigree_analysis_dir()) if self._db_path else ""
        path = filedialog.askopenfilename(
            parent=self,
            title="Open pedigree snapshot",
            initialdir=initial,
            filetypes=[("Pedigree JSON", "*.json")],
        )
        if not path:
            return
        self._load_pedigree_from_path(Path(path))

    def _try_restore_session_scan(self) -> None:
        """Restore a persisted library scan from the current session folder."""
        if not self._ui_is_active() or self._cached_scan is not None or self._db_path is None:
            return
        scan = load_session_scan(self._db_path)
        if scan is None:
            return
        self._apply_loaded_scan(scan)
        logger.info(
            "Restored session library scan (%s entries)",
            self._scan_entry_count(scan),
        )

    def _load_pedigree_from_path(self, path: Path) -> None:
        try:
            result = load_pedigree_result(path)
        except Exception as exc:
            messagebox.showerror("Pedigree", f"Could not load snapshot:\n{exc}", parent=self)
            return
        if self._db_path is not None and not database_paths_match(
            result.database_path, self._db_path
        ):
            if not messagebox.askyesno(
                "Pedigree",
                "This snapshot was saved from a different database. Load anyway?",
                parent=self,
            ):
                return
        self._show_loading_page(
            "Loading pedigree",
            "Restoring pedigree snapshot and rebuilding DEL-cycle tree…",
        )
        config = self._config

        def worker() -> None:
            del_data = None
            try:
                if (
                    config is not None
                    and config.pedigree_configured()
                    and self._db_path is not None
                ):
                    del_data = build_del_cycle_tree_for_path(
                        self._db_path,
                        config,
                        result.settings,
                        result.settings.count_channel,
                        result.settings.time_unit,  # type: ignore[arg-type]
                        rt_threshold=float(result.settings.tolerance),
                        pedigree_result=result,
                        use_metadata_rt=False,
                        progress_callback=None,
                    )
            except Exception as exc:
                logger.warning(
                    "DEL-cycle tree rebuild on pedigree load failed: %s", exc, exc_info=True
                )
            self._bind_worker_callback(self._on_pedigree_loaded, result, path, del_data)

        self._start_worker(worker)

    def _on_pedigree_loaded(
        self,
        result: PedigreeAnalysisResult,
        path: Path,
        del_data: Optional[DelCycleTreeData],
    ) -> None:
        self._worker_thread = None
        self._pedigree_result = result
        self._pedigree_snapshot_path = path
        if del_data is not None:
            self._del_cycle_tree_data = del_data
            self._del_cycle_tree_isoform = "All"
            self._update_del_branch_choices(del_data)
        else:
            self._del_cycle_tree_data = None
            self._del_cycle_tree_isoform = None
        self._sync_pedigree_controls(result)
        self._update_pedigree_graphviz_banner()
        self._configure_pedigree_tier_slider(result)
        if result.max_display_tier is not None:
            self._pedigree_include_failed_var.set(
                suggest_include_failed(
                    result.records,
                    max_display_tier=result.max_display_tier,
                )
            )
        self._update_pedigree_tree_density_note(result)
        self._display_pedigree_result(result)
        if self._pedigree_status_label is not None:
            note = f"Loaded pedigree snapshot from {path.name}"
            if del_data is not None:
                note += f" — DEL tree ready ({del_data.n_verified:,} verified)."
            self._pedigree_status_label.configure(
                text=note,
                text_color=("gray10", "gray90"),
            )
        if self._content_tabview is not None:
            try:
                self._content_tabview.set(_TAB_RT_ASSIGNMENT)
            except ValueError:
                pass
        self._hide_loading_page()
        self._update_action_states()

    def _sync_pedigree_controls(self, result: PedigreeAnalysisResult) -> None:
        settings = result.settings
        self._pedigree_channel_var.set(settings.count_channel)
        self._pedigree_time_unit_var.set(settings.time_unit)
        self._pedigree_tolerance_var.set(str(settings.tolerance))
        self._pedigree_alpha_var.set(str(settings.alpha))

    def on_close(self) -> None:
        self._closing = True
        self._clear_pedigree_tree_plot()
        if self._data_store is not None:
            self._data_store.close()
            self._data_store = None
        super().on_close()
