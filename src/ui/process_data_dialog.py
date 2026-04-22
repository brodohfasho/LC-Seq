# src/ui/process_data_dialog.py
"""
Dialog for optional bulk creation of a SQLite database (managed output folder).
"""

import customtkinter as ctk
import logging
import threading
from pathlib import Path
from typing import Optional, Callable, List

from src.ui.base_window import BaseWindow
from src.core.data_processor import DataProcessor
from src.core.data_processing_result import DataProcessingResult
from src.core import database_library
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)


def _format_processing_parameters_summary(
    config: SpreadsheetConfig,
    file_path: str,
    preset_display_name: Optional[str],
    database_name_prefix: str,
) -> str:
    """Build read-only summary of parsing/processing settings for the dialog."""
    safe_prefix = database_library.sanitize_database_stem(database_name_prefix)
    db_dir = database_library.get_databases_dir()
    delim_line = (
        ", ".join(repr(d) for d in config.delimiters) if config.delimiters else "(none)"
    )
    counts_line = (
        ", ".join(str(i) for i in config.count_column_indices)
        if config.count_column_indices
        else "(none)"
    )
    names_line = (
        ", ".join(config.count_names) if config.count_names else "(none)"
    )
    meta = config.selected_metadata_columns or []
    meta_line = ", ".join(meta) if meta else "(none selected)"

    lines: List[str] = []
    if preset_display_name:
        lines.append(f"Configuration preset: {preset_display_name}")
    else:
        lines.append("Configuration: saved spreadsheet settings (no named preset)")
    lines.append("")
    lines.append(f"Compound ID column: {config.compound_id_column}")
    lines.append(f"Chromatographic data column: {config.chromatographic_data_column}")
    lines.append(
        f"Compound variant column: {config.compound_variant_column}"
        if config.compound_variant_column
        else "Compound variant column: (none)"
    )
    lines.append(f"Delimiters (order): {delim_line}")
    lines.append(f"Time field index: {config.time_column_index}")
    lines.append(f"Count field indices: {counts_line}")
    lines.append(f"Count names: {names_line}")
    lines.append(f"Metadata columns: {meta_line}")
    lines.append("")
    lines.append(f"Output database folder: {db_dir}")
    lines.append(
        f"Database file prefix: {safe_prefix} "
        f"(final name is <prefix>_YYYYMMDD_HHMMSS.db when export starts)"
    )
    lines.append(
        f"Engine defaults: chunk size {DataProcessor.DEFAULT_CHUNK_SIZE:,}, "
        f"batch size {DataProcessor.DEFAULT_BATCH_SIZE:,}"
    )
    return "\n".join(lines)


class ProcessDataDialog(BaseWindow):
    """
    Dialog window for processing spreadsheet data into database.

    User reviews parameters, then starts processing explicitly.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        file_path: str,
        config: SpreadsheetConfig,
        on_success: Optional[Callable[[DataProcessingResult], None]] = None,
        preset_display_name: Optional[str] = None,
    ):
        """
        Initialize process data dialog.

        Args:
            parent: Parent window
            file_path: Path to spreadsheet file to process
            config: SpreadsheetConfig with parsing settings
            on_success: Callback function called with DataProcessingResult on successful processing
            preset_display_name: Human-readable preset label (e.g. "Default") when applicable
        """
        super().__init__(parent, title="Create database")

        self.file_path = file_path
        self.config = config
        self.on_success = on_success
        self.preset_display_name = preset_display_name
        self._planned_db_path: Optional[Path] = None

        self.geometry("640x580")
        self.center_window(640, 580)

        self.processor = DataProcessor()
        self.processing_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._quit_app_after_cancel = False
        self._close_dialog_after_cancel = False
        self.is_processing = False
        self._processing_started = False
        self.result: Optional[DataProcessingResult] = None

        self._create_widgets()

        logger.info("Process data dialog initialized")

    def _create_widgets(self) -> None:
        """Create and layout UI widgets."""
        title_label = ctk.CTkLabel(
            self,
            text="Create SQLite database (bulk export)",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        title_label.grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")

        file_label = ctk.CTkLabel(
            self,
            text=f"File: {Path(self.file_path).name}",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        file_label.grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")

        name_row = ctk.CTkFrame(self, fg_color="transparent")
        name_row.grid(row=2, column=0, padx=20, pady=(4, 4), sticky="ew")
        name_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            name_row,
            text="Database name (prefix):",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self._db_name_entry = ctk.CTkEntry(
            name_row,
            placeholder_text="Uses spreadsheet file name if empty",
        )
        self._db_name_entry.grid(row=0, column=1, padx=0, pady=4, sticky="ew")
        self._db_name_entry.insert(0, Path(self.file_path).stem)
        self._db_name_entry.bind("<KeyRelease>", self._on_db_name_changed)

        self.params_text = ctk.CTkTextbox(
            self,
            height=180,
            wrap="word",
            activate_scrollbars=True,
            font=ctk.CTkFont(size=12),
        )
        self.params_text.grid(row=3, column=0, padx=20, pady=(4, 10), sticky="nsew")
        self._refresh_params_summary()

        self.idle_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.idle_frame.grid(row=4, column=0, padx=20, pady=(8, 12), sticky="ew")
        self.idle_frame.grid_columnconfigure(0, weight=1)
        self.idle_frame.grid_columnconfigure(1, weight=1)

        self.start_process_button = ctk.CTkButton(
            self.idle_frame,
            text="Create database",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._on_start_process_clicked,
        )
        self.start_process_button.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="ew")

        self.close_idle_button = ctk.CTkButton(
            self.idle_frame,
            text="Close",
            command=self._on_close_without_processing,
            fg_color="gray40",
            hover_color="gray25",
            height=40,
        )
        self.close_idle_button.grid(row=0, column=1, padx=(8, 0), pady=4, sticky="ew")

        self.run_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.run_frame.grid_columnconfigure(0, weight=1)
        self.run_frame.grid_rowconfigure(2, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.run_frame)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=0, padx=0, pady=(0, 8), sticky="ew")

        self.status_label = ctk.CTkLabel(
            self.run_frame,
            text="",
            font=ctk.CTkFont(size=12),
        )
        self.status_label.grid(row=1, column=0, padx=0, pady=6, sticky="w")

        self.progress_details = ctk.CTkTextbox(self.run_frame, height=150)
        self.progress_details.grid(row=2, column=0, padx=0, pady=8, sticky="nsew")

        self.button_frame = ctk.CTkFrame(self.run_frame, fg_color="transparent")
        self.button_frame.grid(row=3, column=0, padx=0, pady=(8, 0), sticky="ew")
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)

        self.close_button = ctk.CTkButton(
            self.button_frame,
            text="Close",
            command=self.on_close,
            state="disabled",
        )
        self.close_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.cancel_button = ctk.CTkButton(
            self.button_frame,
            text="Cancel processing",
            command=self._on_cancel_processing_clicked,
        )
        self.cancel_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(4, weight=0)

    def _database_name_prefix(self) -> str:
        """Return prefix for the managed database file (spreadsheet stem if blank)."""
        raw = self._db_name_entry.get().strip()
        return raw if raw else Path(self.file_path).stem

    def _on_db_name_changed(self, _event: object = None) -> None:
        """Refresh the read-only summary when the user edits the database name."""
        self._refresh_params_summary()

    def _refresh_params_summary(self) -> None:
        """Update the parameters textbox from current config and name prefix."""
        summary = _format_processing_parameters_summary(
            self.config,
            self.file_path,
            self.preset_display_name,
            self._database_name_prefix(),
        )
        self.params_text.configure(state="normal")
        self.params_text.delete("1.0", "end")
        self.params_text.insert("1.0", summary)
        self.params_text.configure(state="disabled")

    def _on_close_without_processing(self) -> None:
        """Dismiss dialog without starting processing."""
        if self.is_processing:
            return
        super().on_close()

    def _on_start_process_clicked(self) -> None:
        """Reveal progress UI and begin background processing."""
        if self._processing_started or self.is_processing:
            return
        self._processing_started = True
        stem = self._database_name_prefix()
        self._planned_db_path = database_library.allocate_new_database_path(stem)
        self._refresh_params_summary()
        self._db_name_entry.configure(state="disabled")

        self.idle_frame.grid_forget()
        self.run_frame.grid(row=4, column=0, padx=20, pady=(0, 16), sticky="nsew")
        self.grid_rowconfigure(4, weight=1)
        self.grid_rowconfigure(3, weight=0)

        self.progress_details.delete("1.0", "end")
        self.progress_details.insert(
            "1.0",
            f"Output file: {self._planned_db_path}\nStarting data processing...\n",
        )
        self.status_label.configure(text="Initializing...", text_color=("gray10", "gray90"))
        self.progress_bar.set(0)

        self.after(50, self._start_processing)

    def _start_processing(self) -> None:
        """Start data processing in background thread."""
        if self.is_processing:
            return

        self.is_processing = True

        db_path = self._planned_db_path
        if db_path is None:
            logger.error("Planned database path was not set before processing")
            return

        self.processing_thread = threading.Thread(
            target=self._process_in_thread,
            args=(str(db_path),),
            daemon=True,
        )
        self.processing_thread.start()

    def _process_in_thread(self, db_path: str) -> None:
        """Process data in background thread."""
        try:
            def progress_callback(processed: int, total: int, status: str) -> None:
                """Update progress from processing thread."""
                if self._cancel_event.is_set() and status != "Processing cancelled.":
                    return
                self.after(0, self._update_progress, processed, total, status)

            self.result = self.processor.process_spreadsheet(
                file_path=self.file_path,
                config=self.config,
                db_path=Path(db_path),
                progress_callback=progress_callback,
                cancel_event=self._cancel_event,
            )

            self.after(0, self._dispatch_processing_finished)

        except Exception as e:
            error_msg = f"Error during processing: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.after(0, self._on_processing_error, error_msg)

    def _update_progress(self, processed: int, total: int, status: str) -> None:
        """Update progress bar and status (called from main thread)."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if total > 0:
            progress = processed / total
            self.progress_bar.set(progress)

        self.status_label.configure(text=status)

        details_text = f"Processed: {processed:,} / {total:,} rows\n{status}\n"
        self.progress_details.insert("end", details_text)
        self.progress_details.see("end")

    def _dispatch_processing_finished(self) -> None:
        """Route to completion, cancellation, or error UI after worker returns."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self.result and getattr(self.result, "cancelled", False):
            self._on_processing_cancelled()
        else:
            self._on_processing_complete()

    def user_requested_exit(self, quit_app: bool = False) -> None:
        """
        Request cooperative cancellation of processing.

        Args:
            quit_app: If True, the main window will close after cancellation finishes.
        """
        self._quit_app_after_cancel = quit_app
        self._cancel_event.set()
        try:
            self.status_label.configure(text="Cancelling…", text_color="orange")
            self.cancel_button.configure(state="disabled")
        except Exception:
            pass

    def _on_cancel_processing_clicked(self) -> None:
        """Confirm and request cancellation from the dialog."""
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Cancel processing",
            "Stop processing? Partial data will be discarded and no database will be saved.",
            parent=self,
        ):
            return
        self.user_requested_exit(quit_app=False)

    def _on_processing_cancelled(self) -> None:
        """Handle user-cancelled processing."""
        self.is_processing = False
        try:
            if self.winfo_exists():
                self.progress_details.insert("end", "\nProcessing was cancelled.\n")
                self.progress_details.see("end")
                self.status_label.configure(
                    text="Processing cancelled",
                    text_color="orange",
                )
                self.close_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
        except Exception:
            pass
        if self._quit_app_after_cancel and self.parent is not None:
            setattr(self.parent, "_quit_after_process_dialog", True)
            super().on_close()
            return
        if self._close_dialog_after_cancel:
            super().on_close()
            return
        logger.info("Data processing cancelled by user")

    def _on_processing_complete(self) -> None:
        """Handle processing completion."""
        self.is_processing = False

        if self.result:
            self.progress_bar.set(1.0)

            summary = self.result.get_summary()
            self.progress_details.insert("end", f"\n{summary}\n")
            self.progress_details.see("end")

            self.status_label.configure(
                text=f"✓ Complete! {self.result.successful_compounds:,} compounds processed",
                text_color="green",
            )

            self.close_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")

            if self.on_success:
                self.on_success(self.result)

            logger.info("Data processing completed successfully")
        else:
            self.status_label.configure(
                text="✗ Processing failed",
                text_color="red",
            )
            self.close_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")

    def _on_processing_error(self, error_msg: str) -> None:
        """Handle processing error."""
        self.is_processing = False
        self.status_label.configure(
            text=f"✗ Error: {error_msg}",
            text_color="red",
        )
        self.progress_details.insert("end", f"\nError: {error_msg}\n")
        self.close_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def on_close(self) -> None:
        """Handle window close event."""
        if self.is_processing:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Cancel processing",
                "Processing is still running. Cancel and close this window?",
                parent=self,
            ):
                return
            self._close_dialog_after_cancel = True
            self.user_requested_exit(quit_app=False)
            return

        super().on_close()
