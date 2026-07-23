# src/ui/library_data_window.py
"""
Library Analysis dashboard: QC metrics/plots, RT assignment, and pedigree/split-tree.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
from tkinter import messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.core.library_report_session import (
    LibraryQcMetricsArtifact,
    LibraryQcPlotsArtifact,
    PedigreeVizReportArtifact,
    RtAssignmentReportArtifact,
    SplittreeVizReportArtifact,
)
from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    LibraryComputationSnapshot,
    LibraryScanData,
    PlotResult,
)
from src.core.library_metrics_store import (
    any_session_scan_exists,
    get_latest_snapshot_path,
    list_snapshots,
)
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
)
from src.core.pedigree_backend import pedigree_backend_available
from src.ui.library_analysis import FigureHost, LibraryAnalysisState, TaskCoordinator
from src.ui.library_analysis.action_state import LibraryActionInputs, LibraryActionState
from src.ui.library_analysis.contexts import (
    PedigreePanelCallbacks,
    QcPanelCallbacks,
    ReportControllerCallbacks,
    RtAssignmentCallbacks,
    SplitTreePanelCallbacks,
)
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.library_analysis.report_controller import ReportController
from src.ui.library_analysis.rt_assignment_panel import RtAssignmentPanel
from src.ui.library_analysis.pedigree_panel import PedigreePanel
from src.ui.library_analysis.splittree_panel import SplitTreePanel
from src.ui.library_analysis.window_shell import WindowShell
from src.core.del_cycle_tree import DelCycleTreeData
from src.models.pedigree_result import PedigreeAnalysisResult
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)

_RT_ANALYSIS_PEDIGREE = "pedigree"
_RT_ANALYSIS_DIRECT = "direct_pick"


class LibraryDataWindow(BaseWindow):
    """
    Library-wide analysis: load chromatograms as needed for QC, then RT assignment
    and pedigree / split-tree visualization.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
        *,
        on_closed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title="Library Analysis",
            transient_parent=False,
            modal=False,
        )
        self.withdraw()
        self._closing = False
        self._on_closed = on_closed
        self._closed_callback_sent = False
        self._session_state = LibraryAnalysisState()
        self._task_coordinator = TaskCoordinator(
            self._dispatch_to_tk,
            self._ui_is_active,
        )
        self.app_state = app_state
        self.config_manager = config_manager
        self._data_store: Optional[DataStore] = None
        self._db_path: Optional[Path] = None
        self._config: Optional[SpreadsheetConfig] = None
        self._index_db_mode = False
        self._compound_count = 0
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
        self._qc_picker_algorithm_var = tk.StringVar(value="modern")
        self._qc_alpha_var = tk.StringVar(value=str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._qc_min_prominence_var = tk.StringVar(value="5")
        self._qc_min_pct_area_var = tk.StringVar(value="3")
        self._qc_time_unit_var = tk.StringVar(value="seconds")
        self._qc_gaussian_height_var = tk.StringVar(value="0.35")
        self._qc_gaussian_fit_width_var = tk.StringVar(value="30")
        self._qc_gaussian_stddev_var = tk.StringVar(value="2")
        self._qc_gaussian_min_rt_var = tk.StringVar(value="600")
        self._qc_modern_widgets: List[ctk.CTkBaseClass] = []
        self._qc_old_school_widgets: List[ctk.CTkBaseClass] = []
        self._qc_modern_col: Optional[ctk.CTkFrame] = None
        self._qc_old_col: Optional[ctk.CTkFrame] = None
        self._pedigree_frame: Optional[ctk.CTkFrame] = None
        self._pedigree_summary_label: Optional[ctk.CTkLabel] = None
        self._pedigree_status_label: Optional[ctk.CTkLabel] = None
        self._rt_assignment_results_frame: Optional[ctk.CTkFrame] = None
        self._rt_assignment_results_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_host: Optional[ctk.CTkFrame] = None
        self._pedigree_tree_placeholder: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_plot_host: Optional[tk.Frame] = None
        self._pedigree_figure_host: Optional[FigureHost] = None
        self._pedigree_channel_var = tk.StringVar(value="")
        self._pedigree_time_unit_var = tk.StringVar(value="seconds")
        self._pedigree_tolerance_var = tk.StringVar(value="30")
        self._pedigree_del_pass_pct_var = tk.StringVar(value="30")
        self._pedigree_alpha_var = tk.StringVar(value=str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._pedigree_min_prominence_var = tk.StringVar(value="5")
        self._pedigree_min_pct_area_var = tk.StringVar(value="3")
        self._pedigree_picker_algorithm_var = tk.StringVar(value="modern")
        self._pedigree_gaussian_height_var = tk.StringVar(value="0.35")
        self._pedigree_gaussian_fit_width_var = tk.StringVar(value="30")
        self._pedigree_gaussian_stddev_var = tk.StringVar(value="2")
        self._pedigree_gaussian_min_rt_var = tk.StringVar(value="600")
        self._pedigree_modern_widgets: List[ctk.CTkBaseClass] = []
        self._pedigree_old_school_widgets: List[ctk.CTkBaseClass] = []
        self._pedigree_modern_col: Optional[ctk.CTkFrame] = None
        self._pedigree_old_col: Optional[ctk.CTkFrame] = None
        self._pedigree_variant_choices: List[str] = ["All"]
        self._pedigree_include_failed_var = tk.BooleanVar(value=True)
        self._pedigree_show_rt_var = tk.BooleanVar(value=True)
        self._pedigree_tree_tier_slider: Optional[ctk.CTkSlider] = None
        self._pedigree_tree_tier_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_dense_note: Optional[ctk.CTkLabel] = None
        self._pedigree_graphviz_banner: Optional[ctk.CTkLabel] = None
        self._pedigree_tree_node_count_label: Optional[ctk.CTkLabel] = None
        self._pedigree_generate_btn: Optional[ctk.CTkButton] = None
        self._pedigree_export_tree_btn: Optional[ctk.CTkButton] = None
        self._pedigree_export_csv_btn: Optional[ctk.CTkButton] = None
        self._pedigree_export_del_csv_btn: Optional[ctk.CTkButton] = None
        self._export_rts_btn: Optional[ctk.CTkButton] = None
        self._splittree_export_png_btn: Optional[ctk.CTkButton] = None
        self._splittree_export_branches_btn: Optional[ctk.CTkButton] = None
        self._splittree_export_bundle_btn: Optional[ctk.CTkButton] = None
        self._rt_analysis_mode_var = tk.StringVar(value=_RT_ANALYSIS_DIRECT)
        self._last_rt_analysis_mode: Optional[str] = None
        self._del_cycle_tree_isoform: Optional[str] = None
        self._pedigree_viz_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._splittree_viz_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._del_build_show_loading: bool = True
        self._pedigree_tree_viz_mode_menu: Optional[ctk.CTkOptionMenu] = None
        self._pedigree_tree_header_label: Optional[ctk.CTkLabel] = None
        self._pedigree_tier_controls_frame: Optional[ctk.CTkFrame] = None
        self._pedigree_del_controls_frame: Optional[ctk.CTkFrame] = None
        self._body_paned: Optional[tk.PanedWindow] = None
        self._plots_body_paned: Optional[tk.PanedWindow] = None
        self._metrics_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._plots_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._rt_assignment_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._pedigree_sidebar: Optional[ctk.CTkScrollableFrame] = None
        self._busy_sensitive_widgets: List[ctk.CTkBaseClass] = []
        self._busy_operation: Optional[str] = None
        self._loading_max_fraction: float = 0.0
        self._loading_cancel_btn: Optional[ctk.CTkButton] = None
        self._qc_panel = QcPanel(
            self,
            QcPanelCallbacks(
                capture_metrics=lambda snapshot: (
                    self._report_controller._capture_qc_metrics_artifact(snapshot)
                ),
                capture_plots=lambda plots, plot_ids: (
                    self._report_controller._capture_qc_plots_artifact(
                        plots,
                        plot_ids,
                    )
                ),
            ),
        )
        self._report_controller = ReportController(
            self,
            self._qc_panel,
            ReportControllerCallbacks(
                picker_label=lambda: self._rt_assignment_panel._picker_label(),
                pedigree_render_options=lambda: (
                    self._pedigree_panel._pedigree_tree_render_options()
                ),
                split_tree_color_mode=lambda: (self._splittree_panel._del_tree_color_mode()),
                split_tree_pass_cutoff=lambda: (
                    self._splittree_panel._read_del_tree_pass_pct_cutoff()
                ),
                peek_pedigree_settings=lambda: (
                    self._rt_assignment_panel._peek_pedigree_settings()
                ),
            ),
        )
        self._rt_assignment_panel = RtAssignmentPanel(
            self,
            self._qc_panel,
            RtAssignmentCallbacks(
                run_pedigree=lambda: self._pedigree_panel._on_run_pedigree(),
                split_tree_color_mode=lambda: (self._splittree_panel._del_tree_color_mode()),
                split_tree_pass_cutoff=lambda: (
                    self._splittree_panel._read_del_tree_pass_pct_cutoff()
                ),
                sorted_branch_names=lambda data: (
                    self._splittree_panel._sorted_bb1_branch_names(data)
                ),
                resolve_branch=lambda data, selection: (
                    self._splittree_panel._resolve_del_branch_bb1(data, selection)
                ),
                update_branch_choices=lambda data: (
                    self._splittree_panel._update_del_branch_choices(data)
                ),
                update_tree_status=lambda data: (
                    self._splittree_panel._update_del_tree_status_note(data)
                ),
                capture_rt_artifact=lambda *args, **kwargs: (
                    self._report_controller._capture_rt_assignment_artifact(
                        *args,
                        **kwargs,
                    )
                ),
                mount_split_tree=lambda figure: (
                    self._splittree_panel._mount_splittree_figure(figure)
                ),
                show_split_tree_placeholder=lambda message: (
                    self._splittree_panel._show_splittree_placeholder(message)
                ),
                render_cached_split_tree=lambda isoform, show_loading: (
                    self._splittree_panel._render_splittree_from_cached_session(
                        isoform,
                        show_loading=show_loading,
                    )
                ),
            ),
        )
        self._pedigree_panel = PedigreePanel(
            self,
            self._qc_panel,
            PedigreePanelCallbacks(
                parse_settings=lambda: (self._rt_assignment_panel._parse_pedigree_settings()),
                update_rt_results=lambda *args, **kwargs: (
                    self._rt_assignment_panel._update_rt_assignment_results(
                        *args,
                        **kwargs,
                    )
                ),
                capture_visualization=lambda result: (
                    self._report_controller._capture_pedigree_viz_artifact(result)
                ),
                update_split_tree_status=lambda: (
                    self._rt_assignment_panel._update_splittree_rt_assignment_status()
                ),
                ensure_del_cycle_tree=lambda: (
                    self._rt_assignment_panel._ensure_session_del_cycle_after_pedigree()
                ),
            ),
        )
        self._splittree_panel = SplitTreePanel(
            self,
            SplitTreePanelCallbacks(
                session_rt_ready=lambda: (
                    self._rt_assignment_panel._session_rt_ready_for_splittree()
                ),
                update_rt_status=lambda: (
                    self._rt_assignment_panel._update_splittree_rt_assignment_status()
                ),
                ensure_session_tree=lambda: (
                    self._rt_assignment_panel._ensure_session_del_cycle_after_pedigree()
                ),
                parse_settings=lambda: self._rt_assignment_panel._parse_pedigree_settings(),
                peek_settings=lambda: self._rt_assignment_panel._peek_pedigree_settings(),
                capture_visualization=lambda data, figure, isoform, selected_branch: (
                    self._report_controller._capture_splittree_artifact(
                        data,
                        figure,
                        isoform=isoform,
                        selected_branch=selected_branch,
                    )
                ),
            ),
        )
        self._window_shell = WindowShell(self)
        self._splittree_panel.initialize()

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
        self._compound_count = n_compounds

        self._rt_assignment_panel._init_pedigree_settings()

        self._window_shell._build_top_bar(str(db_path))
        self._window_shell._build_body_shell()

        if n_compounds == 0:
            self._qc_panel._show_empty_library_message()
        else:
            self._qc_panel._show_idle_placeholder()

        self._update_action_states()
        self.after_idle(self._finish_initial_display)
        self.after(250, self._qc_panel._try_restore_session_scan)
        logger.info(
            "Library Analysis opened (compounds=%s, index_db=%s)",
            n_compounds,
            self._index_db_mode,
        )

    @property
    def _cached_scan(self) -> Optional[LibraryScanData]:
        return self._session_state.scan

    @_cached_scan.setter
    def _cached_scan(self, value: Optional[LibraryScanData]) -> None:
        self._session_state.scan = value

    @property
    def _current_snapshot(self) -> Optional[LibraryComputationSnapshot]:
        return self._session_state.snapshot

    @_current_snapshot.setter
    def _current_snapshot(self, value: Optional[LibraryComputationSnapshot]) -> None:
        self._session_state.snapshot = value

    @property
    def _current_snapshot_path(self) -> Optional[Path]:
        return self._session_state.snapshot_path

    @_current_snapshot_path.setter
    def _current_snapshot_path(self, value: Optional[Path]) -> None:
        self._session_state.snapshot_path = value

    @property
    def _plot_results(self) -> List[PlotResult]:
        return self._session_state.plots

    @_plot_results.setter
    def _plot_results(self, value: List[PlotResult]) -> None:
        self._session_state.plots = value

    @property
    def _qc_metrics_artifact(self) -> Optional[LibraryQcMetricsArtifact]:
        return self._session_state.qc_metrics_artifact

    @_qc_metrics_artifact.setter
    def _qc_metrics_artifact(self, value: Optional[LibraryQcMetricsArtifact]) -> None:
        self._session_state.qc_metrics_artifact = value

    @property
    def _qc_plots_artifact(self) -> Optional[LibraryQcPlotsArtifact]:
        return self._session_state.qc_plots_artifact

    @_qc_plots_artifact.setter
    def _qc_plots_artifact(self, value: Optional[LibraryQcPlotsArtifact]) -> None:
        self._session_state.qc_plots_artifact = value

    @property
    def _rt_assignment_artifact(self) -> Optional[RtAssignmentReportArtifact]:
        return self._session_state.rt_assignment_artifact

    @_rt_assignment_artifact.setter
    def _rt_assignment_artifact(self, value: Optional[RtAssignmentReportArtifact]) -> None:
        self._session_state.rt_assignment_artifact = value

    @property
    def _pedigree_viz_artifact(self) -> Optional[PedigreeVizReportArtifact]:
        return self._session_state.pedigree_viz_artifact

    @_pedigree_viz_artifact.setter
    def _pedigree_viz_artifact(self, value: Optional[PedigreeVizReportArtifact]) -> None:
        self._session_state.pedigree_viz_artifact = value

    @property
    def _splittree_artifact(self) -> Optional[SplittreeVizReportArtifact]:
        return self._session_state.splittree_viz_artifact

    @_splittree_artifact.setter
    def _splittree_artifact(self, value: Optional[SplittreeVizReportArtifact]) -> None:
        self._session_state.splittree_viz_artifact = value

    @property
    def _pedigree_result(self) -> Optional[PedigreeAnalysisResult]:
        return self._session_state.pedigree_result

    @_pedigree_result.setter
    def _pedigree_result(self, value: Optional[PedigreeAnalysisResult]) -> None:
        self._session_state.pedigree_result = value

    @property
    def _pedigree_snapshot_path(self) -> Optional[Path]:
        return self._session_state.pedigree_snapshot_path

    @_pedigree_snapshot_path.setter
    def _pedigree_snapshot_path(self, value: Optional[Path]) -> None:
        self._session_state.pedigree_snapshot_path = value

    @property
    def _del_cycle_tree_data(self) -> Optional[DelCycleTreeData]:
        return self._session_state.rt_assignment_result

    @_del_cycle_tree_data.setter
    def _del_cycle_tree_data(self, value: Optional[DelCycleTreeData]) -> None:
        self._session_state.rt_assignment_result = value

    @property
    def _splittree_viz_data(self) -> Optional[DelCycleTreeData]:
        return self._session_state.splittree_result

    @_splittree_viz_data.setter
    def _splittree_viz_data(self, value: Optional[DelCycleTreeData]) -> None:
        self._session_state.splittree_result = value

    @property
    def _worker_thread(self):
        return self._task_coordinator.thread

    @_worker_thread.setter
    def _worker_thread(self, value) -> None:
        if value is not None:
            raise ValueError("Worker threads are owned by TaskCoordinator.")
        self._task_coordinator.clear_finished_thread()

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
        self.after(100, self._window_shell._set_initial_paned_positions)

    def _finish_initial_display(self) -> None:
        """Reveal the fully constructed window instead of partial widget frames."""
        if not self._ui_is_active():
            return
        try:
            self.update_idletasks()
            self._apply_maximized_state()
            self.deiconify()
            self.lift()
        except tk.TclError:
            pass

    def _ui_is_active(self) -> bool:
        if self._closing:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _dispatch_to_tk(self, callback: Callable[[], None]) -> None:
        """Queue a callback on Tk's event loop when the window still exists."""
        if not self._ui_is_active():
            return
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _schedule_on_main(self, callback, *args) -> None:
        def invoke() -> None:
            if not self._ui_is_active():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass

        if self._task_coordinator.current_operation is not None:
            self._task_coordinator.dispatch_current(invoke)
        else:
            self._task_coordinator.dispatch_unbound(invoke)

    def _bind_worker_callback(self, callback, *args) -> None:
        """Schedule a worker result handler only if the operation was not superseded."""

        def invoke() -> None:
            if not self._ui_is_active():
                return
            try:
                callback(*args)
            except tk.TclError:
                pass

        self._task_coordinator.dispatch_current(invoke, complete=True)

    def _cached_session_del_cycle_isoform(self) -> str:
        return (self._del_cycle_tree_isoform or "All").strip() or "All"

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._busy_sensitive_widgets:
            try:
                widget.configure(state=state)
            except (tk.TclError, AttributeError):
                pass
        self._splittree_panel._sync_metadata_control_states()

    def _show_loading_page(self, title: str, detail: str = "") -> None:
        self._busy_operation = title
        if self._content_tabview is not None:
            self._content_tabview.grid_remove()
        self._busy_overlay.show(title, detail)
        self._set_controls_enabled(False)
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _update_loading_progress(self, fraction: float, detail: str) -> None:
        if not self._ui_is_active():
            return
        self._busy_overlay.set_progress(fraction, detail)

    def _hide_loading_page(self, *, clear_cancel: bool = True) -> None:
        self._busy_operation = None
        self._busy_overlay.hide()
        try:
            if self._content_tabview is not None:
                self._content_tabview.grid()
        except tk.TclError:
            pass
        self._set_controls_enabled(True)

    def _on_cancel_operation(self) -> None:
        if not self._is_busy():
            return
        self._task_coordinator.cancel_active()
        self._del_build_show_loading = False
        self._busy_overlay.set_cancel_enabled(False)
        self._hide_loading_page(clear_cancel=False)
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
        self._task_coordinator.raise_if_cancelled(LibraryOperationCancelled)

    def _thread_loading_progress(self, fraction: float, status: str) -> None:
        self._raise_if_cancelled()
        self._schedule_on_main(self._update_loading_progress, fraction, status)

    def _library_entry_count(self) -> int:
        if self._cached_scan is not None:
            return self._cached_scan.entries_attempted
        return self._compound_count

    def _confirm_long_operation(self, message: str) -> bool:
        return bool(
            messagebox.askyesno(
                "Library Analysis — long operation",
                message,
                icon="warning",
                parent=self,
            )
        )

    @staticmethod
    def _format_peak_picking_mode_label(algorithm: str) -> str:
        if algorithm == "old_school":
            return "Old-school"
        if algorithm == "modern":
            return "Modern"
        return algorithm or "—"

    def _start_worker(self, worker: Callable[[], None]) -> None:
        def wrapped() -> None:
            try:
                worker()
            except LibraryOperationCancelled:
                return

        self._task_coordinator.start(wrapped)

    def _focus_tab(self, tab_name: str) -> None:
        if self._content_tabview is None:
            return
        try:
            self._content_tabview.set(tab_name)
            self._window_shell._show_sidebar_for_tab(tab_name)
        except (tk.TclError, ValueError):
            pass

    def _parse_peak_quality_params(self) -> Optional[tuple[float, float]]:
        return self._rt_assignment_panel._parse_pedigree_quality_params()

    def _peek_peak_quality_params(self) -> tuple[float, float]:
        return self._rt_assignment_panel._peek_pedigree_quality_params()

    def _is_busy(self) -> bool:
        return self._task_coordinator.is_busy

    def _update_action_states(self) -> None:
        if not self._ui_is_active():
            return
        has_channels = bool(self._qc_panel._get_selected_channels())
        busy = self._is_busy()
        has_scan = self._cached_scan is not None
        has_scan_cache = has_scan or any_session_scan_exists()
        latest = get_latest_snapshot_path(self._db_path) if self._db_path else None
        has_plot_files = any(
            plot.image_path is not None and plot.image_path.is_file() for plot in self._plot_results
        )
        has_computed_metrics = bool(
            self._current_snapshot is not None and self._current_snapshot.metric_results
        )
        pedigree_ready = (
            self._config is not None
            and self._config.pedigree_configured()
            and pedigree_backend_available()
        )
        n_compounds = self._compound_count
        rt_can_run = (
            n_compounds > 0 and self._config is not None and self._config.pedigree_configured()
        )
        if self._rt_analysis_mode_var.get() == _RT_ANALYSIS_PEDIGREE:
            rt_can_run = rt_can_run and pedigree_ready
        tree_path = (
            self._pedigree_result.tree_image_path if self._pedigree_result is not None else None
        )
        actions = LibraryActionState.decide(
            LibraryActionInputs(
                busy=busy,
                has_channels=has_channels,
                has_selected_metrics=bool(self._qc_panel._get_selected_metric_ids()),
                has_selected_plots=bool(self._qc_panel._get_selected_plot_ids()),
                has_scan=has_scan,
                has_scan_cache=has_scan_cache,
                has_snapshot=self._current_snapshot is not None,
                has_latest_snapshot=latest is not None,
                has_plot_files=has_plot_files,
                has_computed_metrics=has_computed_metrics,
                has_saved_snapshots=bool(list_snapshots()),
                has_report_content=self._report_controller._session_has_report_artifacts(),
                rt_can_run=rt_can_run,
                has_rt_result=(
                    self._pedigree_result is not None or self._del_cycle_tree_data is not None
                ),
                has_pedigree=self._pedigree_result is not None,
                has_pedigree_tree=tree_path is not None and Path(tree_path).is_file(),
                has_del_tree=self._del_cycle_tree_data is not None,
                has_splittree_plot=(
                    self._splittree_viz_data is not None or self._del_cycle_tree_data is not None
                ),
            )
        )

        def state(enabled: bool) -> str:
            return "normal" if enabled else "disabled"

        try:
            self._clear_scan_btn.configure(state=state(actions.clear_scan))
            self._plots_clear_scan_btn.configure(state=state(actions.clear_scan))
            self._metrics_btn.configure(state=state(actions.calculate_metrics))
            self._plots_btn.configure(state=state(actions.generate_plots))
            self._save_btn.configure(state=state(actions.save_snapshot))
            self._plots_save_btn.configure(state=state(actions.save_snapshot))
            self._load_last_btn.configure(state=state(actions.load_snapshot))
            self._plots_load_btn.configure(state=state(actions.load_snapshot))
            self._browse_btn.configure(state=state(actions.browse_snapshot))
            self._plots_browse_btn.configure(state=state(actions.browse_snapshot))
            self._export_plots_csv_btn.configure(state=state(actions.export_signal_csv))
            self._export_all_plots_btn.configure(state=state(actions.export_all_plots))
            self._export_metrics_csv_btn.configure(state=state(actions.export_metrics_csv))
            self._clear_metrics_results_btn.configure(state=state(actions.clear_metrics_results))
            self._plots_clear_metrics_results_btn.configure(
                state=state(actions.clear_metrics_results)
            )
            self._export_report_btn.configure(state=state(actions.export_report))
            self._rt_assignment_run_btn.configure(state=state(actions.run_rt_assignment))
            self._pedigree_export_csv_btn.configure(state=state(actions.export_pedigree))
            self._pedigree_generate_btn.configure(state=state(actions.generate_pedigree_plot))
            self._pedigree_export_del_csv_btn.configure(state=state(actions.export_del_tree))
            self._export_rts_btn.configure(state=state(actions.export_assigned_rts))
            self._pedigree_export_tree_btn.configure(state=state(actions.export_pedigree_tree))
            if self._splittree_export_png_btn is not None:
                self._splittree_export_png_btn.configure(
                    state=state(actions.export_splittree_png)
                )
            if self._splittree_export_branches_btn is not None:
                self._splittree_export_branches_btn.configure(
                    state=state(actions.export_splittree_branches)
                )
            if self._splittree_export_bundle_btn is not None:
                self._splittree_export_bundle_btn.configure(
                    state=state(actions.export_del_tree)
                )
            if (
                self._pedigree_status_label is not None
                and self._pedigree_result is None
                and not busy
            ):
                hint = self._pedigree_status_label.cget("text")
                stale_hint = (
                    hint.startswith("Run library scan")
                    or hint.startswith("Direct pick reads")
                    or hint.startswith("Chromatograms are read")
                    or hint == "No pedigree run yet."
                )
                if stale_hint:
                    self._pedigree_status_label.configure(
                        text=(
                            "Chromatograms are read from the database "
                            "(or the QC cache when available)."
                        ),
                        text_color="gray",
                    )
        except tk.TclError:
            pass

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

    def _active_main_tab(self) -> str:
        if self._content_tabview is None:
            return ""
        try:
            return self._content_tabview.get()
        except (ValueError, tk.TclError):
            return ""

    def on_close(self) -> None:
        self._closing = True
        self._task_coordinator.cancel_active()
        self._qc_panel.close()
        self._pedigree_panel._clear_pedigree_tree_plot()
        self._splittree_panel.close()
        if self._data_store is not None:
            self._data_store.close()
            self._data_store = None
        try:
            super().on_close()
        finally:
            if not self._closed_callback_sent and self._on_closed is not None:
                self._closed_callback_sent = True
                self._on_closed()
