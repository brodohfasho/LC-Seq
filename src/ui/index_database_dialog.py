# src/ui/index_database_dialog.py
"""
Dialog to build a compact index SQLite file (metadata + raw chromatogram strings).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
import pandas as pd
from tkinter import messagebox

from src.core.data_processing_result import DataProcessingResult
from src.core.index_database_builder import build_index_database_from_dataframe
from src.core import database_library
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)


class IndexDatabaseDialog(BaseWindow):
    """Background build of an index database from the loaded dataframe."""

    def __init__(
        self,
        parent: ctk.CTk,
        dataframe: pd.DataFrame,
        config: SpreadsheetConfig,
        on_success: Optional[Callable[[DataProcessingResult], None]] = None,
    ) -> None:
        super().__init__(parent, title="Build index database")
        self._df = dataframe
        self.config = config
        self.on_success = on_success
        self._planned_db_path: Optional[Path] = None
        self._cancel_event = threading.Event()
        self.processing_thread: Optional[threading.Thread] = None
        self.is_processing = False
        self.result: Optional[DataProcessingResult] = None

        self.geometry("620x420")
        self.center_window(620, 420)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        intro = (
            "Creates a searchable SQLite file under output/databases. It stores metadata "
            "columns and the raw chromatogram cell text (no expanded time series). "
            "Chromatograms are parsed when you plot in the visualizer.\n\n"
            f"Rows to index: {len(dataframe):,}"
        )
        ctk.CTkLabel(
            self,
            text=intro,
            font=ctk.CTkFont(size=12),
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")

        self._name_row = ctk.CTkFrame(self, fg_color="transparent")
        self._name_row.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        ctk.CTkLabel(self._name_row, text="File name prefix:").pack(side="left", padx=(0, 8))
        self._db_name_entry = ctk.CTkEntry(self._name_row, width=280)
        self._db_name_entry.pack(side="left", fill="x", expand=True)
        if parent and getattr(parent, "app_state", None) and parent.app_state.spreadsheet_path:
            self._db_name_entry.insert(0, Path(parent.app_state.spreadsheet_path).stem)
        else:
            self._db_name_entry.insert(0, "library")

        self._progress_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self._progress_label.grid(row=2, column=0, padx=16, pady=4, sticky="w")

        self._progress_bar = ctk.CTkProgressBar(self)
        self._progress_bar.grid(row=3, column=0, padx=16, pady=8, sticky="ew")
        self._progress_bar.set(0)

        self._details = ctk.CTkTextbox(self, height=120)
        self._details.grid(row=4, column=0, padx=16, pady=8, sticky="nsew")
        self.grid_rowconfigure(4, weight=1)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=16, pady=(8, 16), sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1)

        self._start_btn = ctk.CTkButton(
            btn_row, text="Start build", command=self._on_start, font=ctk.CTkFont(size=14, weight="bold")
        )
        self._start_btn.grid(row=0, column=0, padx=4, sticky="ew")
        self._cancel_btn = ctk.CTkButton(
            btn_row,
            text="Cancel build",
            fg_color="gray40",
            command=self._on_cancel,
            state="disabled",
        )
        self._cancel_btn.grid(row=0, column=1, padx=4, sticky="ew")

        self._close_btn = ctk.CTkButton(self, text="Close", width=100, command=self.on_close)
        self._close_btn.grid(row=6, column=0, padx=16, pady=(0, 12), sticky="e")

    def _name_prefix(self) -> str:
        raw = self._db_name_entry.get().strip()
        return raw if raw else "index"

    def _on_start(self) -> None:
        if self.is_processing:
            return
        stem = database_library.sanitize_database_stem(self._name_prefix())
        self._planned_db_path = database_library.allocate_new_index_database_path(stem)
        self._details.delete("1.0", "end")
        self._details.insert("1.0", f"Output: {self._planned_db_path}\n")
        self._start_btn.configure(state="disabled")
        self._db_name_entry.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._cancel_event.clear()
        self.is_processing = True
        self.processing_thread = threading.Thread(
            target=self._run_build, args=(self._planned_db_path,), daemon=True
        )
        self.processing_thread.start()

    def _run_build(self, db_path: Path) -> None:
        try:

            def progress(processed: int, total: int, status: str) -> None:
                if self._cancel_event.is_set():
                    return
                self.after(0, self._update_ui, processed, total, status)

            self.result = build_index_database_from_dataframe(
                self._df,
                self.config,
                db_path,
                progress_callback=progress,
                cancel_event=self._cancel_event,
            )
            self.after(0, self._on_finished)
        except Exception as exc:
            logger.exception("Index build failed")
            self.after(0, self._on_error, str(exc))

    def _update_ui(self, processed: int, total: int, status: str) -> None:
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if total > 0:
            self._progress_bar.set(min(1.0, processed / total))
        self._progress_label.configure(text=status)
        self._details.insert("end", f"{status}\n")
        self._details.see("end")

    def _on_finished(self) -> None:
        self.is_processing = False
        self._cancel_btn.configure(state="disabled")
        self._start_btn.configure(state="normal")
        try:
            if self.result and self.result.cancelled:
                self._progress_label.configure(text="Cancelled", text_color="orange")
            elif self.result:
                self._progress_bar.set(1.0)
                self._progress_label.configure(
                    text=f"Done: {self.result.successful_compounds:,} compounds indexed",
                    text_color="green",
                )
                self._details.insert("end", self.result.get_summary() + "\n")
                if self.on_success:
                    self.on_success(self.result)
        except Exception:
            pass

    def _on_error(self, msg: str) -> None:
        self.is_processing = False
        self._cancel_btn.configure(state="disabled")
        self._start_btn.configure(state="normal")
        self._progress_label.configure(text=f"Error: {msg}", text_color="red")
        messagebox.showerror("Index build", msg, parent=self)

    def _on_cancel(self) -> None:
        if not self.is_processing:
            return
        if messagebox.askyesno(
            "Cancel",
            "Stop the index build? The database may be incomplete.",
            parent=self,
        ):
            self._cancel_event.set()

    def on_close(self) -> None:
        if self.is_processing:
            if not messagebox.askyesno(
                "Close",
                "Build is running. Cancel and close?",
                parent=self,
            ):
                return
            self._cancel_event.set()
        super().on_close()
