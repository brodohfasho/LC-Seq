# src/ui/library_data_window.py
"""
Library Data dashboard: library-wide calculations over the active database.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from pathlib import Path
from typing import List, Optional

import customtkinter as ctk
from tkinter import messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.core.library_metrics import (
    ChannelAggregateStats,
    LibraryMetricsResult,
    compute_library_metrics_for_path,
)
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)


class LibraryDataWindow(BaseWindow):
    """
    Dashboard of library-wide metrics (extensible card layout).
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
        self._compute_thread: Optional[threading.Thread] = None
        self._metrics_frame: Optional[ctk.CTkScrollableFrame] = None

        self.minsize(640, 480)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

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
        self._build_context_bar(db_path)
        self._build_dashboard_shell()

        if n_compounds == 0:
            self._show_empty_library_message()
        else:
            self._start_metrics_compute()

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
        refresh_btn = ctk.CTkButton(
            header,
            text="Refresh",
            width=90,
            command=self._on_refresh,
        )
        refresh_btn.pack(side="right", padx=(8, 0))
        attach_tooltip(refresh_btn, "Recompute all metrics from the active database.")

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
            wraplength=720,
            justify="left",
        ).grid(row=0, column=0, padx=12, pady=10, sticky="w")

    def _build_dashboard_shell(self) -> None:
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(2, weight=1)

        self._progress_label = ctk.CTkLabel(
            shell,
            text="Preparing…",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._progress_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._progress_bar = ctk.CTkProgressBar(shell)
        self._progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._progress_bar.set(0)

        self._metrics_frame = ctk.CTkScrollableFrame(shell, fg_color="transparent")
        self._metrics_frame.grid(row=2, column=0, sticky="nsew")
        self._metrics_frame.grid_columnconfigure(0, weight=1)

    def _show_empty_library_message(self) -> None:
        assert self._metrics_frame is not None
        self._progress_bar.grid_remove()
        self._progress_label.configure(text="No compounds in the active database.")
        card = self._make_info_card(
            self._metrics_frame,
            "No data",
            "Build or load a database that contains at least one compound.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)

    def _start_metrics_compute(self) -> None:
        assert self._db_path is not None and self._config is not None
        self._progress_bar.grid()
        self._progress_bar.set(0)
        self._progress_label.configure(text="Computing metrics…", text_color="gray")
        self._clear_metric_cards()

        db_path = self._db_path
        config = self._config

        def worker() -> None:
            try:
                result = compute_library_metrics_for_path(
                    db_path,
                    config,
                    progress_callback=self._thread_progress,
                )
                self._schedule_on_main(self._on_metrics_ready, result)
            except Exception as exc:
                logger.error("Library metrics failed: %s", exc, exc_info=True)
                self._schedule_on_main(self._on_metrics_error, str(exc))

        self._compute_thread = threading.Thread(target=worker, daemon=True)
        self._compute_thread.start()

    def _thread_progress(self, processed: int, total: int, status: str) -> None:
        self._schedule_on_main(self._update_progress, processed, total, status)

    def _update_progress(self, processed: int, total: int, status: str) -> None:
        if not self._ui_is_active():
            return
        try:
            if total > 0:
                self._progress_bar.set(min(1.0, processed / total))
            self._progress_label.configure(text=status)
        except tk.TclError:
            pass

    def _on_metrics_ready(self, result: LibraryMetricsResult) -> None:
        if not self._ui_is_active():
            return
        try:
            self._progress_bar.set(1.0)
            self._progress_label.configure(
                text=(
                    f"Based on {result.entries_used:,} of {result.entries_attempted:,} entries "
                    f"({result.entries_skipped:,} skipped)."
                ),
                text_color="gray",
            )
            self._render_metrics_cards(result)
        except tk.TclError:
            pass

    def _on_metrics_error(self, message: str) -> None:
        if not self._ui_is_active():
            return
        try:
            self._progress_bar.set(0)
            self._progress_label.configure(text=f"Error: {message}", text_color="red")
            messagebox.showerror("Library Data", message, parent=self)
        except tk.TclError:
            pass

    def _clear_metric_cards(self) -> None:
        assert self._metrics_frame is not None
        for child in self._metrics_frame.winfo_children():
            child.destroy()

    def _render_metrics_cards(self, result: LibraryMetricsResult) -> None:
        assert self._metrics_frame is not None
        self._render_stat_card(
            row=0,
            title="Total count per entry — library mean ± SD",
            help_txt=(
                "For each compound, all count values are summed across time points. "
                "Mean and sample standard deviation are taken across the library."
            ),
            channels=result.total_count_per_entry,
        )
        n_frac = result.fraction_count
        self._render_stat_card(
            row=1,
            title=f"Average sequencing count per fraction ({n_frac}) — library mean ± SD",
            help_txt=(
                f"For each compound, total count ÷ {n_frac} fractions gives the average count "
                "per fraction. Mean and sample SD of those per-compound averages are shown here."
            ),
            channels=result.avg_count_per_fraction,
        )

    def _render_stat_card(
        self,
        *,
        row: int,
        title: str,
        help_txt: str,
        channels: List[ChannelAggregateStats],
    ) -> None:
        assert self._metrics_frame is not None
        card = ctk.CTkFrame(self._metrics_frame, corner_radius=10)
        card.grid(row=row, column=0, sticky="ew", pady=(4, 12))
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
            wraplength=680,
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
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")
        return card

    def _on_refresh(self) -> None:
        if self._compute_thread is not None and self._compute_thread.is_alive():
            return
        if self._data_store is None or self._data_store.get_compound_count() == 0:
            self._show_empty_library_message()
            return
        self._start_metrics_compute()

    def on_close(self) -> None:
        self._closing = True
        if self._data_store is not None:
            self._data_store.close()
            self._data_store = None
        super().on_close()
