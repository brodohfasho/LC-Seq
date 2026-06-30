# src/ui/library_data_window.py
"""
Library Data dashboard: scan parsed chromatograms, summary metrics, and plots.
"""

from __future__ import annotations

import logging
import shutil
import threading
import tkinter as tk
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.core.library_metrics import (
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    LibraryScanData,
    PlotResult,
    build_snapshot_from_scan,
    list_library_metric_definitions,
    scan_library_for_path,
)
from src.core.library_metrics_store import (
    database_paths_match,
    get_latest_snapshot_path,
    get_library_data_dir,
    load_snapshot,
    save_snapshot,
    session_plots_dir,
    snapshot_plots_dir,
)
from src.core.library_plots import generate_plots, list_library_plot_definitions
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_PLOT_DISPLAY_WIDTH = 700
_PLOT_DISPLAY_HEIGHT = 380


class LibraryDataWindow(BaseWindow):
    """
    Library-wide analysis: scan entries once (parse + sort by time), then derive
    summary metrics and optional visualizations.
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
        self._results_frame: Optional[ctk.CTkScrollableFrame] = None
        self._channel_vars: Dict[str, tk.BooleanVar] = {}
        self._plot_vars: Dict[str, tk.BooleanVar] = {}
        self._cached_scan: Optional[LibraryScanData] = None
        self._current_snapshot: Optional[LibraryComputationSnapshot] = None
        self._current_snapshot_path: Optional[Path] = None
        self._plot_results: List[PlotResult] = []
        self._plot_images: List[ctk.CTkImage] = []

        self.minsize(780, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

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

        self._build_header()
        self._build_context_bar(str(db_path))
        self._build_control_panel()
        self._build_results_shell()

        if n_compounds == 0:
            self._show_empty_library_message()
        else:
            self._show_idle_placeholder()

        self._update_action_states()
        self.after(150, self._apply_maximized_state)
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

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            header,
            text="Library Data",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")

    def _build_context_bar(self, db_path: str) -> None:
        bar = ctk.CTkFrame(self, fg_color=("gray92", "gray18"))
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)

        kind = "Index" if self._index_db_mode else "Full"
        fname = Path(db_path).name
        channels = ", ".join(self._config.count_names) if self._config else ""
        ctk.CTkLabel(
            bar,
            text=f"Database: {fname} ({kind})  ·  Count channels: {channels}",
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=820,
            justify="left",
        ).grid(row=0, column=0, padx=12, pady=10, sticky="w")

    def _build_control_panel(self) -> None:
        panel = ctk.CTkFrame(self, corner_radius=10)
        panel.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        panel.grid_columnconfigure(0, weight=1)

        channels_row = ctk.CTkFrame(panel, fg_color="transparent")
        channels_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(
            channels_row,
            text="Count channels",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 12))

        assert self._config is not None
        for channel_name in self._config.count_names:
            var = tk.BooleanVar(value=True)
            self._channel_vars[channel_name] = var
            ctk.CTkCheckBox(
                channels_row,
                text=channel_name,
                variable=var,
                command=self._update_action_states,
            ).pack(side="left", padx=(0, 10))

        plots_row = ctk.CTkFrame(panel, fg_color="transparent")
        plots_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        ctk.CTkLabel(
            plots_row,
            text="Plots",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 12))

        for definition in list_library_plot_definitions():
            var = tk.BooleanVar(value=True)
            self._plot_vars[definition.plot_id] = var
            cb = ctk.CTkCheckBox(
                plots_row,
                text=definition.title,
                variable=var,
                command=self._update_action_states,
            )
            cb.pack(side="left", padx=(0, 10))
            attach_tooltip(cb, definition.help_text)

        hint = ctk.CTkLabel(
            panel,
            text=(
                "Scan loads each entry, parses chromatogram data, and sorts by time (slow for "
                "large index databases). Summary metrics and plots are derived from that scan."
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=820,
            justify="left",
        )
        hint.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="w")

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))

        self._scan_btn = ctk.CTkButton(
            actions,
            text="Scan library",
            width=120,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_scan,
        )
        self._scan_btn.pack(side="left", padx=(0, 8))
        attach_tooltip(
            self._scan_btn,
            "Parse every library entry once and compute summary metrics.",
        )

        self._plots_btn = ctk.CTkButton(
            actions,
            text="Generate plots",
            width=130,
            command=self._on_generate_plots,
        )
        self._plots_btn.pack(side="left", padx=(0, 8))
        attach_tooltip(
            self._plots_btn,
            "Build selected plots from the current scan (requires Scan library first).",
        )

        self._save_btn = ctk.CTkButton(
            actions,
            text="Save results",
            width=110,
            command=self._on_save,
        )
        self._save_btn.pack(side="left", padx=(0, 8))

        self._load_last_btn = ctk.CTkButton(
            actions,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=self._on_load_last,
        )
        self._load_last_btn.pack(side="left", padx=(0, 8))

        self._browse_btn = ctk.CTkButton(
            actions,
            text="Browse saved…",
            width=120,
            fg_color="gray40",
            command=self._on_browse_saved,
        )
        self._browse_btn.pack(side="left")

        self._status_label = ctk.CTkLabel(
            panel,
            text="No scan loaded.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=820,
            justify="left",
        )
        self._status_label.grid(row=4, column=0, padx=12, pady=(0, 10), sticky="w")

    def _build_results_shell(self) -> None:
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 12))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(2, weight=1)

        self._progress_label = ctk.CTkLabel(
            shell,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._progress_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._progress_bar = ctk.CTkProgressBar(shell)
        self._progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._progress_bar.set(0)
        self._progress_bar.grid_remove()
        self._progress_label.grid_remove()

        self._results_frame = ctk.CTkScrollableFrame(shell, fg_color="transparent")
        self._results_frame.grid(row=2, column=0, sticky="nsew")
        self._results_frame.grid_columnconfigure(0, weight=1)

    def _get_selected_channels(self) -> List[str]:
        return [name for name, var in self._channel_vars.items() if var.get()]

    def _get_selected_plot_ids(self) -> List[str]:
        return [pid for pid, var in self._plot_vars.items() if var.get()]

    def _is_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _update_action_states(self) -> None:
        if not self._ui_is_active():
            return
        has_channels = bool(self._get_selected_channels())
        busy = self._is_busy()
        has_scan = self._cached_scan is not None
        has_plots = bool(self._get_selected_plot_ids()) and has_channels
        try:
            self._scan_btn.configure(state="normal" if has_channels and not busy else "disabled")
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
        except tk.TclError:
            pass

    def _clear_results(self) -> None:
        assert self._results_frame is not None
        self._plot_images.clear()
        for child in self._results_frame.winfo_children():
            child.destroy()

    def _show_empty_library_message(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._results_frame,
            "No data",
            "Build or load a database that contains at least one compound.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)
        self._scan_btn.configure(state="disabled")

    def _show_idle_placeholder(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._results_frame,
            "Ready",
            "Choose count channels and plots, then click Scan library. "
            "After the scan completes, generate plots or save the result set for later.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)

    def _on_scan(self) -> None:
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
        self._start_scan(channels)

    def _start_scan(self, channels: List[str]) -> None:
        assert self._db_path is not None and self._config is not None
        self._progress_bar.grid()
        self._progress_label.grid()
        self._progress_bar.set(0)
        self._progress_label.configure(text="Starting scan…", text_color="gray")
        self._clear_results()
        self._plot_results.clear()
        self._update_action_states()

        db_path = self._db_path
        config = self._config

        def worker() -> None:
            try:
                scan = scan_library_for_path(
                    db_path,
                    config,
                    channel_names=channels,
                    progress_callback=self._thread_progress,
                )
                self._schedule_on_main(self._on_scan_ready, scan, channels)
            except Exception as exc:
                logger.error("Library scan failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_scan_ready(self, scan: LibraryScanData, channels: List[str]) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._cached_scan = scan
        assert self._db_path is not None
        kind = "index" if self._index_db_mode else "full"
        metric_ids = [m.metric_id for m in list_library_metric_definitions()]
        snapshot = build_snapshot_from_scan(
            scan,
            database_path=self._db_path,
            database_kind=kind,
            channel_names=channels,
            metric_ids=metric_ids,
        )
        try:
            self._progress_bar.set(1.0)
            self._progress_label.configure(
                text=(
                    f"Scan complete: {scan.entries_used:,} of {scan.entries_attempted:,} "
                    f"entries parsed ({scan.entries_skipped:,} skipped)."
                ),
                text_color="gray",
            )
            self._apply_snapshot(snapshot, None, warn_database_mismatch=False)
        except tk.TclError:
            pass
        self._update_action_states()

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

        self._progress_bar.grid()
        self._progress_label.grid()
        self._progress_bar.set(0)
        self._progress_label.configure(text="Generating plots…", text_color="gray")
        self._update_action_states()

        scan = self._cached_scan
        plot_dir = session_plots_dir(self._db_path)
        for old in plot_dir.glob("*.png"):
            try:
                old.unlink()
            except OSError:
                pass

        def worker() -> None:
            try:
                plots = generate_plots(scan, plot_ids, channels, plot_dir)
                self._schedule_on_main(self._on_plots_ready, plots, plot_ids)
            except Exception as exc:
                logger.error("Plot generation failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_worker_error, str(exc))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_plots_ready(self, plots: List[PlotResult], plot_ids: List[str]) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        self._plot_results = plots
        if self._current_snapshot is not None:
            self._current_snapshot.selected_plots = list(plot_ids)
            self._current_snapshot.plot_results = plots
        try:
            self._progress_bar.set(1.0)
            self._progress_label.configure(
                text=f"Generated {len(plots)} plot(s).",
                text_color="gray",
            )
            self._render_results()
            self._update_status_label()
        except tk.TclError:
            pass
        self._update_action_states()

    def _thread_progress(self, processed: int, total: int, status: str) -> None:
        self._schedule_on_main(self._update_progress, processed, total, status)

    def _update_progress(self, processed: int, total: int, status: str) -> None:
        if not self._ui_is_active():
            return
        try:
            self._progress_bar.grid()
            self._progress_label.grid()
            if total > 0:
                self._progress_bar.set(min(1.0, processed / total))
            self._progress_label.configure(text=status)
        except tk.TclError:
            pass

    def _on_worker_error(self, message: str) -> None:
        if not self._ui_is_active():
            return
        self._worker_thread = None
        try:
            self._progress_bar.set(0)
            self._progress_label.configure(text=f"Error: {message}", text_color="red")
            messagebox.showerror("Library Data", message, parent=self)
        except tk.TclError:
            pass
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
        self._sync_plot_selection(snapshot)
        self._render_results()
        self._update_status_label()
        self._update_action_states()

    def _sync_channel_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        for channel_name, var in self._channel_vars.items():
            var.set(channel_name in snapshot.selected_channels)

    def _sync_plot_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        if not snapshot.selected_plots:
            return
        for plot_id, var in self._plot_vars.items():
            var.set(plot_id in snapshot.selected_plots)

    def _update_status_label(self) -> None:
        snapshot = self._current_snapshot
        if snapshot is None:
            self._status_label.configure(text="No scan loaded.")
            return

        processed = snapshot.processed_at
        if processed.tzinfo is not None:
            processed_local = processed.astimezone()
        else:
            processed_local = processed
        stamp = processed_local.strftime("%Y-%m-%d %H:%M:%S")
        channels = ", ".join(snapshot.selected_channels) or "—"
        plots = ", ".join(snapshot.selected_plots) or "—"
        source = (
            "current session (unsaved)"
            if self._current_snapshot_path is None
            else str(self._current_snapshot_path)
        )
        scan_note = "scan in memory" if self._cached_scan is not None else "metrics/plots only (rescan to refresh)"
        self._status_label.configure(
            text=(
                f"Processed: {stamp}  ·  Database: {snapshot.database_name} "
                f"({snapshot.database_kind})  ·  Entries: {snapshot.entries_used:,} / "
                f"{snapshot.entries_attempted:,}  ·  Channels: {channels}  ·  "
                f"Plots: {plots}  ·  {scan_note}  ·  Source: {source}"
            )
        )

    def _render_results(self) -> None:
        assert self._results_frame is not None
        self._clear_results()
        snapshot = self._current_snapshot
        if snapshot is None:
            return

        row = 0
        if snapshot.metric_results:
            ctk.CTkLabel(
                self._results_frame,
                text="Summary metrics",
                font=ctk.CTkFont(size=16, weight="bold"),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=(4, 8))
            row += 1
            for metric in snapshot.metric_results:
                self._render_stat_card(
                    row=row,
                    title=metric.title,
                    help_txt=metric.help_text,
                    channels=metric.channels,
                )
                row += 1

        plots = self._plot_results
        if not plots:
            plots = list(snapshot.plot_results)
            self._plot_results = plots

        if plots:
            ctk.CTkLabel(
                self._results_frame,
                text="Visualizations",
                font=ctk.CTkFont(size=16, weight="bold"),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=(12, 8))
            row += 1
            for plot in plots:
                self._render_plot_card(row=row, plot=plot)
                row += 1

        if row == 0:
            card = self._make_info_card(
                self._results_frame,
                "No results",
                "Scan the library to populate summary metrics, then generate plots.",
            )
            card.grid(row=0, column=0, sticky="ew", pady=8)

    def _render_stat_card(
        self,
        *,
        row: int,
        title: str,
        help_txt: str,
        channels: List[ChannelAggregateStats],
    ) -> None:
        assert self._results_frame is not None
        card = ctk.CTkFrame(self._results_frame, corner_radius=10)
        card.grid(row=row, column=0, sticky="ew", pady=(4, 10))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")

        ctk.CTkLabel(
            card,
            text=help_txt,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")

        if not channels or all(ch.n == 0 for ch in channels):
            ctk.CTkLabel(
                card,
                text="No values could be computed.",
                text_color="orange",
            ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
            return

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")
        body.grid_columnconfigure(1, weight=1)

        for row_i, ch in enumerate(channels):
            self._add_channel_row(body, row_i, ch)

    def _render_plot_card(self, *, row: int, plot: PlotResult) -> None:
        assert self._results_frame is not None
        card = ctk.CTkFrame(self._results_frame, corner_radius=10)
        card.grid(row=row, column=0, sticky="ew", pady=(4, 12))
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=plot.title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if plot.image_path is not None and plot.image_path.is_file():
            export_btn = ctk.CTkButton(
                header,
                text="Export image…",
                width=120,
                fg_color="gray40",
                command=lambda p=plot.image_path: self._export_plot_image(p),
            )
            export_btn.grid(row=0, column=1, sticky="e")

        if plot.help_text:
            ctk.CTkLabel(
                card,
                text=plot.help_text,
                font=ctk.CTkFont(size=11),
                text_color="gray",
                anchor="w",
                wraplength=760,
                justify="left",
            ).grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")

        if plot.image_path is None or not plot.image_path.is_file():
            ctk.CTkLabel(
                card,
                text="Plot image not available.",
                text_color="orange",
            ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
            return

        image = ctk.CTkImage(
            light_image=str(plot.image_path),
            dark_image=str(plot.image_path),
            size=(_PLOT_DISPLAY_WIDTH, _PLOT_DISPLAY_HEIGHT),
        )
        self._plot_images.append(image)
        img_label = ctk.CTkLabel(card, text="", image=image)
        img_label.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")

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
        ctk.CTkLabel(
            parent,
            text=ch.count_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=row_i, column=0, padx=(0, 16), pady=6, sticky="w")

        if ch.n == 0:
            value_text = "—"
        elif ch.n == 1:
            value_text = f"{ch.mean:,.4g}  (n = 1, SD undefined)"
        else:
            value_text = f"{ch.mean:,.4g} ± {ch.std_dev:,.4g}  (n = {ch.n:,})"

        ctk.CTkLabel(
            parent,
            text=value_text,
            font=ctk.CTkFont(size=13),
            anchor="w",
        ).grid(row=row_i, column=1, pady=6, sticky="w")

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
