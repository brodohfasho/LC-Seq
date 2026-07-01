# src/ui/library_data_window.py
"""
Library Data dashboard: scan parsed chromatograms, summary metrics, and plots.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.core.library_report import generate_library_report_pdf
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
    get_latest_snapshot_path,
    get_library_data_dir,
    load_snapshot,
    save_snapshot,
    session_plots_dir,
    snapshot_plots_dir,
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
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_TAB_METRICS = "Summary metrics"
_TAB_PLOTS = "Visualizations"

_SIDEBAR_WRAP = 280
_PLOT_PREVIEW_MAX_WIDTH = 820
_PLOT_LIST_BUTTON_HEIGHT = 52
_SECTION_HEADER_COLOR = ("#0969da", "#58a6ff")


class LibraryOperationCancelled(Exception):
    """Raised in a background worker when the user cancels a library operation."""


def _section_header_font() -> ctk.CTkFont:
    """Section header font (must be created after a Tk root exists)."""
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
            title="Library Data",
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
        self._cached_scan: Optional[LibraryScanData] = None
        self._current_snapshot: Optional[LibraryComputationSnapshot] = None
        self._current_snapshot_path: Optional[Path] = None
        self._plot_results: List[PlotResult] = []
        self._busy_sensitive_widgets: List[ctk.CTkBaseClass] = []
        self._busy_operation: Optional[str] = None
        self._loading_max_fraction: float = 0.0
        self._cancel_requested = threading.Event()
        self._loading_cancel_btn: Optional[ctk.CTkButton] = None

        self.minsize(1000, 620)
        self.grid_columnconfigure(0, weight=3, uniform="library_body")
        self.grid_columnconfigure(1, weight=7, uniform="library_body")
        self.grid_rowconfigure(1, weight=1)

        cfg = config_manager.load_default_config()
        if not cfg or not cfg.is_complete():
            messagebox.showerror(
                "Configuration missing",
                "Complete spreadsheet configuration and save it before opening Library Data.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        self._config = cfg
        db_path = app_state.database_path
        if not db_path or not Path(db_path).is_file():
            messagebox.showerror(
                "Database required",
                "Load or create a database before opening Library Data.",
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

        self._build_top_bar(str(db_path))
        self._build_left_sidebar()
        self._build_right_content()

        if n_compounds == 0:
            self._show_empty_library_message()
        else:
            self._show_idle_placeholder()

        self._update_action_states()
        self.after(150, self._apply_maximized_state)
        self.after(300, self._sync_tabview_height)
        logger.info(
            "Library Data opened (compounds=%s, index_db=%s)",
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

    def _clear_main_reference(self, event: tk.Event) -> None:
        if event.widget != self:
            return
        main = self.parent
        if main is not None and getattr(main, "_library_data_window", None) is self:
            main._library_data_window = None

    def _build_top_bar(self, db_path: str) -> None:
        """Single compact header row: title + database context."""
        bar = ctk.CTkFrame(self, fg_color=("gray92", "gray18"))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 8))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            bar,
            text="Library Data",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=(12, 16), pady=8, sticky="w")

        kind = "Index" if self._index_db_mode else "Full"
        fname = Path(db_path).name
        channels = ", ".join(self._config.count_names) if self._config else ""
        ctk.CTkLabel(
            bar,
            text=f"Database: {fname} ({kind})  ·  Channels: {channels}",
            font=ctk.CTkFont(size=12),
            anchor="e",
            justify="right",
        ).grid(row=0, column=1, padx=12, pady=8, sticky="e")

    def _build_left_sidebar(self) -> None:
        """Left column (~30%): parameters, metrics/plot selection, and actions."""
        shell = ctk.CTkFrame(self, corner_radius=10)
        self._control_panel = shell
        shell.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 12))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        panel = ctk.CTkScrollableFrame(
            shell,
            label_text="Analysis options",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
        )
        panel.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        panel.grid_columnconfigure(0, weight=1)

        row = 0

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        self._scan_btn = ctk.CTkButton(
            actions,
            text="Run library scan",
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_run_library_scan,
        )
        self._scan_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._scan_btn)

        self._metrics_btn = ctk.CTkButton(
            actions,
            text="Calculate metrics",
            command=self._on_calculate_metrics,
        )
        self._metrics_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._metrics_btn)

        self._plots_btn = ctk.CTkButton(
            actions,
            text="Generate plots",
            command=self._on_generate_plots,
        )
        self._plots_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._plots_btn)

        self._save_btn = ctk.CTkButton(actions, text="Save results", command=self._on_save)
        self._save_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._save_btn)

        row_btns = ctk.CTkFrame(actions, fg_color="transparent")
        row_btns.pack(fill="x", pady=(0, 4))
        self._load_last_btn = ctk.CTkButton(
            row_btns, text="Load last", width=90, fg_color="gray40", command=self._on_load_last
        )
        self._load_last_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._browse_btn = ctk.CTkButton(
            row_btns, text="Browse…", width=90, fg_color="gray40", command=self._on_browse_saved
        )
        self._browse_btn.pack(side="left", expand=True, fill="x")
        self._busy_sensitive_widgets.extend([self._load_last_btn, self._browse_btn])

        self._export_csv_btn = ctk.CTkButton(
            actions,
            text="Export signal CSV…",
            fg_color="gray40",
            command=self._on_export_signal_csv,
        )
        self._export_csv_btn.pack(fill="x", pady=(0, 4))
        self._busy_sensitive_widgets.append(self._export_csv_btn)

        self._export_report_btn = ctk.CTkButton(
            actions,
            text="Export report…",
            fg_color="gray40",
            command=self._on_export_report,
        )
        self._export_report_btn.pack(fill="x", pady=(0, 0))
        self._busy_sensitive_widgets.append(self._export_report_btn)

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
            "significant only when the peak picker's height or area p-value is below α "
            "(same engine as Chromatogram Visualizer). Lower α → fewer significant peaks.",
        )

        ctk.CTkLabel(
            panel,
            text="Plots",
            font=_section_header_font(),
            text_color=_SECTION_HEADER_COLOR,
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
                "Run library scan parses each entry once. Metrics and plots are computed "
                "separately from that scan. Signal metrics use the same peak engine as "
                "Chromatogram Visualizer."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))
        row += 1

        self._status_label = ctk.CTkLabel(
            panel,
            text="No scan loaded.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._status_label.grid(row=row, column=0, padx=8, pady=(4, 10), sticky="w")

    def _build_right_content(self) -> None:
        """Right column (~70%): metrics and visualization tabs."""
        shell = ctk.CTkFrame(self, fg_color="transparent")
        self._results_shell = shell
        shell.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 12))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._content_tabview = ctk.CTkTabview(shell, corner_radius=10)
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
            fg_color="gray40",
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
        plot_body.grid_columnconfigure(0, weight=1, minsize=200)
        plot_body.grid_columnconfigure(1, weight=4)
        plot_body.grid_rowconfigure(0, weight=1)

        self._plot_list_frame = ctk.CTkScrollableFrame(
            plot_body,
            label_text="Plots",
            label_font=_section_header_font(),
            label_text_color=_SECTION_HEADER_COLOR,
            width=210,
        )
        self._plot_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        preview_col = ctk.CTkFrame(plot_body, corner_radius=8)
        preview_col.grid(row=0, column=1, sticky="nsew")
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
        try:
            if self._loading_cancel_btn is not None:
                self._loading_cancel_btn.configure(state="disabled")
            self._loading_detail.configure(
                text="Cancelling… finishing the current step.",
                text_color="#D29922",
            )
        except tk.TclError:
            pass

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

    def _signal_quality_is_cached(self, channels: List[str], alpha: float) -> bool:
        scan = self._cached_scan
        if scan is None or scan.signal_quality_alpha is None:
            return False
        if abs(scan.signal_quality_alpha - alpha) >= 1e-12:
            return False
        return all(ch in scan.signal_quality_by_channel for ch in channels)

    def _confirm_long_operation(self, message: str) -> bool:
        return bool(
            messagebox.askyesno(
                "Library Data — long operation",
                message,
                icon="warning",
                parent=self,
            )
        )

    def _confirm_library_scan(self, entry_count: int) -> bool:
        index_note = (
            "Index databases parse raw chromatogram text for each entry, so this step "
            "is often the slowest part of a session.\n\n"
            if self._index_db_mode
            else ""
        )
        return self._confirm_long_operation(
            f"This will scan {entry_count:,} library entries across the selected "
            f"count channel(s).\n\n"
            f"{index_note}"
            "Large libraries can take several minutes. You can cancel while the scan "
            "runs, but partial results will be discarded.\n\n"
            "Continue?"
        )

    def _confirm_metrics_computation(self, entry_count: int, metric_ids: List[str]) -> bool:
        signal_metrics = [mid for mid in metric_ids if mid in SIGNAL_QUALITY_METRIC_IDS]
        channels = self._get_selected_channels()
        alpha = self._parse_signal_alpha()
        if signal_metrics and alpha is not None and self._signal_quality_is_cached(
            channels, alpha
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
        if signal_plots and alpha is not None and self._signal_quality_is_cached(
            channels, alpha
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

    def _report_plots_are_ready(self) -> bool:
        expected = self._expected_report_plot_keys()
        if not expected:
            return True
        available = {
            (p.plot_id, p.channel)
            for p in self._plot_results
            if p.image_path is not None and p.image_path.is_file()
        }
        return expected.issubset(available)

    def _report_metrics_are_ready(self, metric_ids: List[str], channels: List[str]) -> bool:
        if not metric_ids:
            return True
        snapshot = self._current_snapshot
        if snapshot is None:
            return False
        alpha = self._parse_signal_alpha()
        fraction_count = self._parse_fraction_count()
        if alpha is None or fraction_count is None:
            return False
        if snapshot.fraction_count != fraction_count:
            return False
        if abs(snapshot.signal_quality_alpha - alpha) >= 1e-12:
            return False
        if set(snapshot.selected_channels) != set(channels):
            return False
        computed = {m.metric_id for m in snapshot.metric_results}
        return set(metric_ids).issubset(computed)

    def _assess_report_prerequisites(
        self,
        metric_ids: List[str],
        channels: List[str],
    ) -> tuple[bool, bool, bool, str]:
        needs_scan = self._cached_scan is None
        needs_metrics = not self._report_metrics_are_ready(metric_ids, channels)
        needs_plots = not self._report_plots_are_ready()
        notes: List[str] = []
        if needs_scan:
            notes.append(
                "• Run a full library scan (parses every entry; often the slowest step)."
            )
        if needs_metrics:
            signal_metrics = [mid for mid in metric_ids if mid in SIGNAL_QUALITY_METRIC_IDS]
            if signal_metrics and not self._signal_quality_is_cached(
                channels, self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA
            ):
                notes.append(
                    "• Calculate selected metrics, including per-entry peak analysis for "
                    "signal metrics (may take a long time)."
                )
            else:
                notes.append("• Calculate selected metrics.")
        if needs_plots:
            signal_plots = self._selected_signal_plot_ids()
            alpha = self._parse_signal_alpha() or DEFAULT_SIGNAL_QUALITY_ALPHA
            if signal_plots and not self._signal_quality_is_cached(channels, alpha):
                notes.append(
                    "• Generate selected plots, including peak analysis for signal plots "
                    "(may take a long time)."
                )
            else:
                notes.append("• Generate selected plots.")
        slow_note = "\n".join(notes) if notes else ""
        return needs_scan, needs_metrics, needs_plots, slow_note

    def _confirm_report_export(
        self,
        pdf_path: Path,
        metric_ids: List[str],
        plot_ids: List[str],
        needs_scan: bool,
        needs_metrics: bool,
        needs_plots: bool,
        slow_note: str,
    ) -> bool:
        parts = [
            f"Save library report to:\n{pdf_path}\n",
            f"Metrics selected: {len(metric_ids)}",
            f"Plots selected: {len(plot_ids)}",
        ]
        if needs_scan or needs_metrics or needs_plots:
            parts.append(
                "\nThe following calculations will run before the PDF is written "
                "(this may take several minutes for large libraries):"
            )
            if slow_note:
                parts.append(f"\n{slow_note}")
            parts.append("\nContinue?")
        else:
            parts.append(
                "\nAll selected metrics and plots are already computed. "
                "The PDF will be generated from the current session.\n\nContinue?"
            )
        return self._confirm_long_operation("\n".join(parts))

    def _on_export_report(self) -> None:
        if self._is_busy():
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Data",
                "Select at least one count channel.",
                parent=self,
            )
            return
        metric_ids = self._get_selected_metric_ids()
        plot_ids = self._get_selected_plot_ids()
        if not metric_ids and not plot_ids:
            messagebox.showinfo(
                "Library Data",
                "Select at least one metric and/or plot to include in the report.",
                parent=self,
            )
            return
        if self._parse_fraction_count() is None or self._parse_signal_alpha() is None:
            return
        if self._data_store is not None and self._data_store.get_compound_count() == 0:
            messagebox.showinfo(
                "Library Data",
                "The database has no compounds to report on.",
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

        needs_scan, needs_metrics, needs_plots, slow_note = self._assess_report_prerequisites(
            metric_ids, channels
        )
        if not self._confirm_report_export(
            pdf_path,
            metric_ids,
            plot_ids,
            needs_scan,
            needs_metrics,
            needs_plots,
            slow_note,
        ):
            return
        self._start_report_export(pdf_path, metric_ids, plot_ids, channels)

    def _start_report_export(
        self,
        pdf_path: Path,
        metric_ids: List[str],
        plot_ids: List[str],
        channels: List[str],
    ) -> None:
        assert self._db_path is not None and self._config is not None
        db_path = self._db_path
        config = self._config
        kind = "index" if self._index_db_mode else "full"
        fraction_count = self._parse_fraction_count()
        signal_alpha = self._parse_signal_alpha()
        assert fraction_count is not None and signal_alpha is not None

        needs_scan, needs_metrics, needs_plots, _ = self._assess_report_prerequisites(
            metric_ids, channels
        )

        self._show_loading_page(
            "Exporting library report",
            "Preparing calculations and PDF…",
        )
        self._update_action_states()

        def worker() -> None:
            try:
                scan = self._cached_scan
                plot_results = list(self._plot_results)
                metric_results: List = []

                if needs_scan:
                    def scan_progress(processed: int, total: int, status: str) -> None:
                        fraction = 0.35 * ((processed / total) if total > 0 else 0.0)
                        self._thread_loading_progress(
                            fraction,
                            status or "Running library scan…",
                        )

                    scan = scan_library_for_path(
                        db_path,
                        config,
                        channel_names=channels,
                        progress_callback=scan_progress,
                    )
                    self._raise_if_cancelled()
                    plot_results = []
                    metric_results = []

                assert scan is not None

                if needs_metrics:
                    def metrics_progress(processed: int, total: int, status: str) -> None:
                        base = 0.35 if needs_scan else 0.0
                        span = 0.35
                        fraction = base + span * ((processed / total) if total > 0 else 0.0)
                        self._thread_loading_progress(
                            fraction,
                            status or "Calculating metrics…",
                        )

                    metric_results = compute_metrics_from_scan(
                        scan,
                        metric_ids,
                        channels=channels,
                        fraction_count=fraction_count,
                        signal_quality_alpha=signal_alpha,
                        progress_callback=metrics_progress,
                    )
                    self._raise_if_cancelled()
                elif self._current_snapshot is not None:
                    metric_results = [
                        m
                        for m in self._current_snapshot.metric_results
                        if m.metric_id in metric_ids
                    ]

                if needs_plots:
                    plot_dir = session_plots_dir(db_path)

                    def plot_progress(processed: int, total: int, status: str) -> None:
                        base = 0.7 if (needs_scan or needs_metrics) else 0.35
                        span = 0.25
                        fraction = base + span * ((processed / total) if total > 0 else 0.0)
                        self._thread_loading_progress(
                            fraction,
                            status or "Generating plots…",
                        )

                    plot_results = generate_plots(
                        scan,
                        plot_ids,
                        channels,
                        plot_dir,
                        signal_quality_alpha=signal_alpha,
                        progress_callback=plot_progress,
                    )
                    self._raise_if_cancelled()
                    kept = {
                        p.image_path.resolve()
                        for p in plot_results
                        if p.image_path is not None and p.image_path.is_file()
                    }
                    for old in plot_dir.glob("*.png"):
                        try:
                            if old.resolve() not in kept:
                                old.unlink()
                        except OSError:
                            pass
                elif plot_ids:
                    plot_results = [
                        p
                        for p in plot_results
                        if p.plot_id in plot_ids and p.channel in channels
                    ]

                self._thread_loading_progress(0.92, "Writing PDF report…")
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
                generate_library_report_pdf(
                    snapshot,
                    pdf_path,
                    plot_results=plot_results,
                )
                self._raise_if_cancelled()
                self._schedule_on_main(
                    self._on_report_export_ready,
                    scan,
                    snapshot,
                    plot_results,
                    str(pdf_path.resolve()),
                )
            except LibraryOperationCancelled:
                self._schedule_on_main(self._on_worker_cancelled)
            except Exception as exc:
                logger.error("Library report export failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _on_report_export_ready(
        self,
        scan: LibraryScanData,
        snapshot: LibraryComputationSnapshot,
        plot_results: List[PlotResult],
        pdf_path: str,
    ) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._cached_scan = scan
        self._current_snapshot = snapshot
        self._current_snapshot_path = None
        self._plot_results = plot_results
        self._update_loading_progress(1.0, f"Report saved: {pdf_path}")
        try:
            if snapshot.metric_results:
                self._render_metrics()
            if plot_results:
                self._refresh_plot_gallery(plot_results)
            self._update_status_label()
        except tk.TclError:
            pass

        def finish() -> None:
            if not self._ui_is_active():
                return
            self._hide_loading_page()
            self._update_action_states()
            messagebox.showinfo(
                "Library Data",
                f"Library report saved to:\n{pdf_path}",
                parent=self,
            )

        self.after(30, finish)

    def _on_worker_cancelled(self) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        try:
            self._loading_detail.configure(
                text="Operation cancelled.",
                text_color="#D29922",
            )
        except tk.TclError:
            pass
        self._hide_loading_page()
        self._update_action_states()
        logger.info("Library Data operation cancelled by user")

    def _start_worker(self, worker: Callable[[], None]) -> None:
        self._cancel_requested.clear()
        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _focus_tab(self, tab_name: str) -> None:
        if self._content_tabview is None:
            return
        try:
            self._content_tabview.set(tab_name)
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
                "Library Data",
                "Fraction count must be a positive integer.",
                parent=self,
            )
            return None
        if value <= 0:
            messagebox.showerror(
                "Library Data",
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
                "Library Data",
                "Peak significance α must be a number (e.g. 0.001).",
                parent=self,
            )
            return None
        if value <= 0.0 or value >= 1.0:
            messagebox.showerror(
                "Library Data",
                "Peak significance α must be between 0 and 1 (exclusive).",
                parent=self,
            )
            return None
        return value

    def _is_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _update_action_states(self) -> None:
        if not self._ui_is_active():
            return
        has_channels = bool(self._get_selected_channels())
        has_metrics = bool(self._get_selected_metric_ids())
        busy = self._is_busy()
        has_scan = self._cached_scan is not None
        has_plots = bool(self._get_selected_plot_ids()) and has_channels
        try:
            self._scan_btn.configure(
                state="normal" if has_channels and not busy else "disabled"
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
            latest = get_latest_snapshot_path(self._db_path) if self._db_path else None
            self._load_last_btn.configure(
                state="normal" if latest is not None and not busy else "disabled"
            )
            self._browse_btn.configure(state="normal" if not busy else "disabled")
            self._export_csv_btn.configure(
                state="normal" if has_scan and has_channels and not busy else "disabled"
            )
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
            has_report_content = bool(
                self._get_selected_metric_ids() or self._get_selected_plot_ids()
            )
            self._export_report_btn.configure(
                state="normal"
                if has_channels and has_report_content and not busy
                else "disabled"
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
            "Select count channels, then click Run library scan. "
            "After the scan completes, use Calculate metrics and/or Generate plots "
            "independently from the same scan.",
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
                "Library Data",
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

    def _on_calculate_metrics(self) -> None:
        if self._is_busy() or self._cached_scan is None:
            return
        metric_ids = self._get_selected_metric_ids()
        if not metric_ids:
            messagebox.showinfo(
                "Library Data",
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
                self._schedule_on_main(self._on_scan_ready, scan, snapshot)
            except LibraryOperationCancelled:
                self._schedule_on_main(self._on_worker_cancelled)
            except Exception as exc:
                logger.error("Library scan failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

        self._start_worker(worker)

    def _start_metrics_computation(self, metric_ids: List[str]) -> None:
        assert self._db_path is not None and self._cached_scan is not None
        scan = self._cached_scan
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Data",
                "Select at least one count channel.",
                parent=self,
            )
            return
        fraction_count = self._parse_fraction_count()
        signal_alpha = self._parse_signal_alpha()
        if fraction_count is None or signal_alpha is None:
            return

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
                self._schedule_on_main(self._on_metrics_ready, snapshot)
            except LibraryOperationCancelled:
                self._schedule_on_main(self._on_worker_cancelled)
            except Exception as exc:
                logger.error("Library metrics failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

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
                self._focus_tab(_TAB_METRICS)
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
                "Library Data",
                "Select at least one plot and one count channel.",
                parent=self,
            )
            return
        signal_alpha = self._parse_signal_alpha()
        if signal_alpha is None:
            return
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
                self._schedule_on_main(self._on_plots_ready, plots, plot_ids)
            except LibraryOperationCancelled:
                self._schedule_on_main(self._on_worker_cancelled)
            except Exception as exc:
                logger.error("Plot generation failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

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
            messagebox.showerror("Library Data", message, parent=self)
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
                "Library Data",
                f"Saved results to:\n{saved}\n\nPlots: {snapshot_plots_dir(saved)}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror("Library Data", f"Could not save results:\n{exc}", parent=self)

    def _on_load_last(self) -> None:
        if self._db_path is None:
            return
        path = get_latest_snapshot_path(self._db_path)
        if path is None:
            messagebox.showinfo(
                "Library Data",
                "No saved results were found for this database.",
                parent=self,
            )
            return
        self._load_snapshot_from_path(path)

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
                "Library Data",
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
                "Library Data",
                "Run library scan first.",
                parent=self,
            )
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Data",
                "Select at least one count channel.",
                parent=self,
            )
            return
        alpha = self._parse_signal_alpha()
        if alpha is None:
            return
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
                    progress_callback=export_progress,
                )
                export_per_entry_signal_csv(stats, dest, alpha=alpha)
                self._schedule_on_main(self._on_export_csv_ready, str(dest))
            except OSError as exc:
                self._schedule_on_main(self._on_worker_error, str(exc))
            except Exception as exc:
                logger.error("CSV export failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()
        self._update_action_states()

    def _on_export_csv_ready(self, dest: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._hide_loading_page()
        self._update_action_states()
        messagebox.showinfo(
            "Library Data",
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
                    f"(iteratively drop points above mean+2σ). α = {snapshot.signal_quality_alpha:g}. "
                    "These are library-wide screening values—not pedigree-validated product "
                    "prominence."
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
                "Library Data",
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
                "Library Data",
                f"Exported summary metrics to:\n{saved}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror(
                "Library Data",
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
                "Library Data",
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
                "Library Data",
                f"Exported {exported} plot(s) to:\n{out_dir}\n\n"
                f"Some files failed:\n" + "\n".join(errors[:5]),
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Library Data",
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
                "Library Data",
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
    def _make_info_card(parent: ctk.CTkFrame, title: str, body: str) -> ctk.CTkFrame:
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
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")
        return card

    def on_close(self) -> None:
        self._closing = True
        if self._data_store is not None:
            self._data_store.close()
            self._data_store = None
        super().on_close()
