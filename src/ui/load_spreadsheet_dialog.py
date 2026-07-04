# src/ui/load_spreadsheet_dialog.py
"""
Dialog for loading spreadsheet files.
"""

import customtkinter as ctk
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from src.ui.base_window import BaseWindow
from src.core.spreadsheet_loader import SpreadsheetLoader

logger = logging.getLogger(__name__)


class LoadSpreadsheetDialog(BaseWindow):
    """
    Dialog window for loading spreadsheet files.

    Provides:
    - File selection dialog
    - Excel sheet selection (if multiple sheets)
    - File validation and error display
    - Non-blocking load with progress feedback
    """

    def __init__(
        self,
        parent: ctk.CTk,
        loader: SpreadsheetLoader,
        on_success: Optional[Callable] = None,
        initial_file_path: Optional[str] = None,
        initial_sheet_name: Optional[str] = None,
    ):
        """
        Initialize load spreadsheet dialog.

        Args:
            parent: Parent window
            loader: SpreadsheetLoader instance
            on_success: Callback function called with (file_path, dataframe) on successful load
            initial_file_path: If set and the file exists, pre-select this path (from saved settings)
            initial_sheet_name: If set and valid for the file, pre-select this Excel sheet
        """
        super().__init__(parent, title="Load Spreadsheet")

        self.loader = loader
        self.on_success = on_success

        self.geometry("600x430")
        self.center_window(600, 430)

        self.selected_file_path: Optional[str] = None
        self.loaded_dataframe = None
        self._pending_initial_sheet = initial_sheet_name
        self._loading = False
        self._progress_animating = False
        self._progress_direction = 1
        self._progress_value = 0.0
        self._progress_after_id: Optional[str] = None
        self._worker_thread: Optional[threading.Thread] = None

        self._create_widgets()

        if initial_file_path and Path(initial_file_path).is_file():
            self.selected_file_path = str(Path(initial_file_path))
            self._update_file_display(enable_load=False)
            self.after(50, self._check_for_sheets_async)

        logger.info("Load spreadsheet dialog initialized")

    def _create_widgets(self) -> None:
        """Create and layout UI widgets."""
        instructions = ctk.CTkLabel(
            self,
            text="Select a spreadsheet file to load:",
            font=ctk.CTkFont(size=14),
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="w")

        self.file_path_label = ctk.CTkLabel(
            self,
            text="No file selected",
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=500,
        )
        self.file_path_label.grid(row=1, column=0, columnspan=2, padx=20, pady=10, sticky="ew")

        self.browse_button = ctk.CTkButton(
            self,
            text="Browse...",
            command=self._on_browse,
        )
        self.browse_button.grid(row=2, column=0, columnspan=2, padx=20, pady=10)

        self.sheet_frame = ctk.CTkFrame(self)
        self.sheet_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.sheet_frame.grid_remove()

        sheet_label = ctk.CTkLabel(
            self.sheet_frame,
            text="Select sheet:",
            font=ctk.CTkFont(size=12),
        )
        sheet_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.sheet_var = ctk.StringVar()
        self.sheet_dropdown = ctk.CTkComboBox(
            self.sheet_frame,
            variable=self.sheet_var,
            values=[],
            command=self._on_sheet_selected,
        )
        self.sheet_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.sheet_frame.grid_columnconfigure(1, weight=1)

        self.loading_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.loading_frame.grid(row=4, column=0, columnspan=2, padx=20, pady=(0, 6), sticky="ew")
        self.loading_frame.grid_columnconfigure(0, weight=1)
        self.loading_frame.grid_remove()

        self.loading_bar = ctk.CTkProgressBar(self.loading_frame, width=520)
        self.loading_bar.grid(row=0, column=0, sticky="ew")
        self.loading_bar.set(0.0)

        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            wraplength=550,
            justify="left",
        )
        self.status_label.grid(row=5, column=0, columnspan=2, padx=20, pady=10, sticky="w")

        button_frame = ctk.CTkFrame(self)
        button_frame.grid(row=6, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)

        self.load_button = ctk.CTkButton(
            button_frame,
            text="Load",
            command=self._on_load,
            state="disabled",
        )
        self.load_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self.on_close,
            fg_color="gray",
        )
        self.cancel_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

    def _on_browse(self) -> None:
        """Handle Browse button click."""
        from tkinter import filedialog

        fd_kwargs = {
            "title": "Select Spreadsheet File",
            "filetypes": [
                ("All Supported", "*.xlsx *.xls *.csv"),
                ("Excel Files", "*.xlsx *.xls"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*"),
            ],
        }
        if self.selected_file_path:
            fd_kwargs["initialdir"] = str(Path(self.selected_file_path).parent)

        file_path = filedialog.askopenfilename(**fd_kwargs)

        if file_path:
            self.selected_file_path = file_path
            self._pending_initial_sheet = None
            self._update_file_display(enable_load=False)
            self._check_for_sheets_async()

    def _update_file_display(self, *, enable_load: bool = True) -> None:
        """Update file path display."""
        if self.selected_file_path:
            self.file_path_label.configure(text=f"Selected: {self.selected_file_path}")
            self.load_button.configure(state="normal" if enable_load and not self._loading else "disabled")
            if not self._loading:
                self.status_label.configure(text="", text_color=("gray10", "gray90"))
        else:
            self.file_path_label.configure(text="No file selected")
            self.load_button.configure(state="disabled")

    def _set_loading(self, active: bool, message: str = "") -> None:
        """Show or hide the loading state and disable interactive controls."""
        self._loading = active
        if active:
            self.loading_frame.grid()
            self.status_label.configure(text=message, text_color=("gray10", "gray90"))
            self.load_button.configure(state="disabled")
            self.browse_button.configure(state="disabled")
            self.sheet_dropdown.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            self._start_progress_animation()
        else:
            self._stop_progress_animation()
            self.loading_frame.grid_remove()
            self.browse_button.configure(state="normal")
            self.sheet_dropdown.configure(state="normal")
            self.cancel_button.configure(state="normal")
            if self.selected_file_path:
                self.load_button.configure(state="normal")

    def _start_progress_animation(self) -> None:
        self._progress_animating = True
        self._progress_direction = 1
        self._progress_value = 0.05
        self.loading_bar.set(self._progress_value)
        self._tick_progress()

    def _tick_progress(self) -> None:
        if not self._progress_animating or not self.winfo_exists():
            return
        self._progress_value += 0.04 * self._progress_direction
        if self._progress_value >= 0.95:
            self._progress_direction = -1
        elif self._progress_value <= 0.05:
            self._progress_direction = 1
        self.loading_bar.set(self._progress_value)
        self._progress_after_id = self.after(60, self._tick_progress)

    def _stop_progress_animation(self) -> None:
        self._progress_animating = False
        if self._progress_after_id is not None:
            try:
                self.after_cancel(self._progress_after_id)
            except ValueError:
                pass
            self._progress_after_id = None
        if self.winfo_exists():
            self.loading_bar.set(1.0 if not self._loading else 0.0)

    def _schedule_on_main(self, callback: Callable, *args) -> None:
        """Run a callback on the Tk main thread if the dialog still exists."""
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._run_on_main(callback, *args))

    def _run_on_main(self, callback: Callable, *args) -> None:
        if not self.winfo_exists():
            return
        callback(*args)

    def _check_for_sheets_async(self) -> None:
        """Detect Excel sheets on a background thread."""
        if not self.selected_file_path or self._loading:
            return

        file_path = self.selected_file_path
        self._set_loading(True, "Reading workbook structure…")

        def worker() -> None:
            sheets = self.loader.get_available_sheets(file_path)
            self._schedule_on_main(self._on_sheets_ready, sheets)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_sheets_ready(self, sheets: Optional[list[str]]) -> None:
        """Apply sheet detection results on the main thread."""
        self._set_loading(False)

        if not self.selected_file_path:
            return

        if sheets and len(sheets) > 1:
            self.sheet_dropdown.configure(values=sheets)
            preferred = self._pending_initial_sheet
            if preferred and preferred in sheets:
                self.sheet_var.set(preferred)
            else:
                self.sheet_var.set(sheets[0])
            self.sheet_frame.grid()
        else:
            self.sheet_frame.grid_remove()
            self.sheet_var.set("")

        self._pending_initial_sheet = None
        self._update_file_display(enable_load=True)

    def _on_sheet_selected(self, choice: str) -> None:
        """Handle sheet selection change."""
        logger.debug("Sheet selected: %s", choice)

    def _on_load(self) -> None:
        """Handle Load button click."""
        if not self.selected_file_path or self._loading:
            return

        file_path = self.selected_file_path
        sheet_name = self.sheet_var.get().strip() or None
        self._set_loading(True, "Loading spreadsheet data…")

        def worker() -> None:
            success, error_message, dataframe = self.loader.load_file(
                file_path,
                sheet_name=sheet_name,
            )
            self._schedule_on_main(
                self._on_load_finished,
                success,
                error_message,
                dataframe,
            )

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _on_load_finished(
        self,
        success: bool,
        error_message: Optional[str],
        dataframe,
    ) -> None:
        """Apply spreadsheet load results on the main thread."""
        self._set_loading(False)

        if success and dataframe is not None:
            self.loaded_dataframe = dataframe
            self.status_label.configure(
                text=(
                    f"Successfully loaded {dataframe.shape[0]:,} rows, "
                    f"{dataframe.shape[1]:,} columns."
                ),
                text_color=("green", "#3fb950"),
            )

            if self.on_success:
                self.on_success(self.selected_file_path, dataframe)

            self.after(800, self.on_close)
            return

        error_text = error_message or "Unknown error occurred"
        self.status_label.configure(text=f"Error: {error_text}", text_color=("red", "#f85149"))
        self.load_button.configure(state="normal")
        logger.error("Failed to load spreadsheet: %s", error_text)

    def on_close(self) -> None:
        """Prevent closing while a background load is in progress."""
        if self._loading:
            return
        self._stop_progress_animation()
        super().on_close()
