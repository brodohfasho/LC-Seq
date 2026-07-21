# src/ui/main_screen.py
"""
Main screen UI for LC-Seq application.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import customtkinter as ctk
from typing import TYPE_CHECKING, Any, Optional

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core import database_library
from src.core.data_store import DB_KIND_FULL, DB_KIND_INDEX, DataStore
from src.core.spreadsheet_loader import SpreadsheetLoader

if TYPE_CHECKING:
    from src.core.data_processing_result import DataProcessingResult
    from src.ui.chromatogram_visualizer_window import ChromatogramVisualizerWindow
    from src.ui.library_data_window import LibraryDataWindow

logger = logging.getLogger(__name__)


class MainScreen(ctk.CTk):
    """
    Main application screen with primary navigation buttons.
    
    Provides:
    - Load Spreadsheet button
    - Configure Spreadsheet button
    - Enter Chromatogram Visualizer / Library Data (after valid configuration + database)
    - Create / Load database (optional bulk SQLite)
    - Status message display
    """
    
    def __init__(self, app_state: AppState, config_manager: ConfigManager):
        """
        Initialize main screen.
        
        Args:
            app_state: Application state manager
            config_manager: Configuration manager
        """
        super().__init__()
        
        self.app_state = app_state
        self.config_manager = config_manager
        self.spreadsheet_loader = SpreadsheetLoader()
        self._chromatogram_window: Optional[ChromatogramVisualizerWindow] = None
        self._library_data_window: Optional[LibraryDataWindow] = None
        self.database_manage_dialog: Optional[Any] = None
        self._restore_spreadsheet_thread: Optional[threading.Thread] = None
        self._closing = False
        
        # Register for state changes
        self.app_state.register_state_change_callback(self._on_state_change)
        
        # Set window properties
        self.title("LC-Seq: Chromatographic Data Analysis")
        
        # Set minimum window size
        self.minsize(600, 500)
        
        # Load saved window size from settings, or use defaults
        settings = self.config_manager.load_settings()
        if settings.window_width and settings.window_height and settings.window_width >= 600 and settings.window_height >= 500:
            width = settings.window_width
            height = settings.window_height
        else:
            # Default size
            width = 800
            height = 600
        
        # Set initial geometry
        self.geometry(f"{width}x{height}")
        # Native title-bar maximize (square) requires user resizing to be allowed
        self.resizable(True, True)
        
        # Configure grid weights for responsive layout
        self.grid_columnconfigure(0, weight=1)
        for r in (3, 4, 5, 6, 7, 8):
            self.grid_rowconfigure(r, weight=1)
        
        # Create UI components
        self._create_widgets()
        
        # Center window after widgets are created
        self.center_window()
        
        # Initial state update
        self._update_ui_state()
        
        # Restore saved configuration and active database only (no automatic spreadsheet load).
        self.after(150, self._restore_session_on_startup)
        
        logger.info("Main screen initialized")
    
    def center_window(self) -> None:
        """Center the window on the screen."""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        
        # Ensure minimum size
        if width < 600:
            width = 600
        if height < 500:
            height = 500
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
    
    def _create_widgets(self) -> None:
        """Create and layout all UI widgets."""
        # Title label
        title_label = ctk.CTkLabel(
            self,
            text="LC-Seq",
            font=ctk.CTkFont(size=36, weight="bold")
        )
        title_label.grid(row=0, column=0, pady=(36, 8), sticky="n")

        self._database_status_button = ctk.CTkButton(
            self,
            text="Database: none loaded",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34,
            corner_radius=8,
            fg_color=("gray90", "gray22"),
            hover_color=("gray82", "gray30"),
            border_width=1,
            border_color=("gray75", "gray40"),
            text_color="gray",
            anchor="center",
            command=self._on_database_status_clicked,
        )
        self._database_status_button.grid(row=1, column=0, padx=40, pady=(0, 12), sticky="ew")
        
        # Subtitle
        subtitle_label = ctk.CTkLabel(
            self,
            text="Chromatographic Data Analysis",
            font=ctk.CTkFont(size=18)
        )
        subtitle_label.grid(row=2, column=0, pady=(0, 24), sticky="n")
        
        primary_row = ctk.CTkFrame(self, fg_color="transparent")
        primary_row.grid(row=3, column=0, padx=40, pady=20, sticky="ew")
        primary_row.grid_columnconfigure((0, 1), weight=1)

        self.visualizer_button = ctk.CTkButton(
            primary_row,
            text="Chromatogram Visualizer",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=60,
            command=self._on_enter_visualizer,
            state="disabled",
        )
        self.visualizer_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.library_data_button = ctk.CTkButton(
            primary_row,
            text="Library Analysis",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=60,
            command=self._on_enter_library_data,
            state="disabled",
        )
        self.library_data_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")
        
        # Load Spreadsheet button
        self.load_button = ctk.CTkButton(
            self,
            text="Load Spreadsheet",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_load_spreadsheet
        )
        self.load_button.grid(row=4, column=0, padx=40, pady=10, sticky="ew")
        
        # Configure Spreadsheet button
        self.configure_button = ctk.CTkButton(
            self,
            text="Configure Spreadsheet",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_configure_spreadsheet,
            state="disabled"
        )
        self.configure_button.grid(row=5, column=0, padx=40, pady=10, sticky="ew")
        
        self.database_manage_button = ctk.CTkButton(
            self,
            text="Create / Load database",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_database_manage,
            state="disabled",
        )
        self.database_manage_button.grid(row=6, column=0, padx=40, pady=10, sticky="ew")

        self.help_button = ctk.CTkButton(
            self,
            text="Analysis help",
            font=ctk.CTkFont(size=13),
            height=40,
            fg_color="gray40",
            command=self._on_analysis_help,
        )
        self.help_button.grid(row=7, column=0, padx=40, pady=(10, 0), sticky="ew")
        
        # Status message label
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            wraplength=600,
            justify="center"
        )
        self.status_label.grid(row=8, column=0, padx=40, pady=(30, 20), sticky="n")
    
    def _on_state_change(self) -> None:
        """Handle application state change."""
        self._update_ui_state()
    
    def _update_ui_state(self) -> None:
        """Update UI elements based on current application state."""
        # Update visualizer button state
        can_enter = self.app_state.can_access_library_data()
        state = "normal" if can_enter else "disabled"
        self.visualizer_button.configure(state=state)
        self.library_data_button.configure(state=state)
        
        # Update configure button state
        self.configure_button.configure(
            state="normal" if self.app_state.spreadsheet_loaded else "disabled"
        )
        
        can_manage_db = (
            self.app_state.spreadsheet_configured
            and self.app_state.config_valid
        )
        self.database_manage_button.configure(
            state="normal" if can_manage_db else "disabled"
        )
        
        # Update status message
        status_message = self.app_state.get_status_message()
        self.status_label.configure(text=status_message)

        if (
            self.app_state.data_processed
            and self.app_state.database_path
            and Path(self.app_state.database_path).is_file()
        ):
            kt = self.app_state.database_kind or "full"
            display = "Index" if kt == "index" else "Full"
            fname = Path(self.app_state.database_path).name
            self._database_status_button.configure(
                text=f"Database: {display} — {fname}",
                text_color=("#1a7f37", "#3fb950"),
                border_color=("#b7dfc4", "#238636"),
            )
        else:
            self._database_status_button.configure(
                text="Database: none loaded",
                text_color="gray",
                border_color=("gray75", "gray40"),
            )
        
        logger.debug(
            "UI state updated. Can enter visualizer: %s, Can manage DB: %s",
            can_enter,
            can_manage_db,
        )

    def _active_database_resolved(self) -> bool:
        """True when an active database path is set and the file exists."""
        return (
            bool(self.app_state.data_processed)
            and bool(self.app_state.database_path)
            and Path(self.app_state.database_path).is_file()
        )

    def _resolve_quick_database_path(self) -> Optional[str]:
        """
        Prefer the last active database from settings if the file still exists;
        otherwise the first ``.db`` in the managed folder (same ordering as Load Database).
        """
        settings = self.config_manager.load_settings()
        last = settings.last_active_database_path
        if last and Path(last).is_file():
            return str(Path(last).resolve())
        paths = database_library.list_managed_databases()
        if paths:
            return str(Path(paths[0]).resolve())
        return None

    def _remember_database_path(self, path: str) -> None:
        """Persist the database path for quick reload on the main screen."""
        settings = self.config_manager.load_settings()
        settings.set_last_active_database_path(path)
        self.config_manager.save_settings(settings)

    def _on_database_status_clicked(self) -> None:
        """Open database management when one is active, or load last/default DB when none."""
        if self._active_database_resolved():
            self._on_database_manage()
            return

        path = self._resolve_quick_database_path()
        if path:
            self._restore_default_config_if_available()
            self._on_quick_load_database()
            return

        can_manage_db = (
            self.app_state.spreadsheet_configured
            and self.app_state.config_valid
        )
        if not can_manage_db:
            messagebox.showinfo(
                "Database",
                "No saved database was found. Load and configure a spreadsheet, then use "
                "'Create / Load database' to build one.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Database",
            "No saved or managed database file was found. Use 'Create / Load database' to "
            "build or register one.",
            parent=self,
        )

    def _on_quick_load_database(self) -> None:
        """Attach the saved or default managed database without opening the manage dialog."""
        path = self._resolve_quick_database_path()
        if not path or not Path(path).is_file():
            messagebox.showwarning(
                "Load database",
                "No saved or managed database file was found. Use 'Create / Load database'.",
                parent=self,
            )
            return
        try:
            kind = DataStore.peek_database_kind(Path(path))
        except OSError as exc:
            logger.warning("Could not read database kind: %s", exc)
            kind = DB_KIND_FULL
        type_word = "index" if kind == DB_KIND_INDEX else "full"
        self._remember_database_path(path)
        self.app_state.set_data_processed(True, path, type_word)
        self._update_ui_state()
        self._notify_chromatogram_visualizer_database_changed()
        messagebox.showinfo(
            "Database loaded",
            f"Loaded {type_word} database.\n\n{path}",
            parent=self,
        )
    
    def _apply_spreadsheet_loaded(
        self, file_path: str, *, preserve_database: bool = False
    ) -> Optional[tuple[bool, str]]:
        """
        Update application state and settings after a successful spreadsheet load.

        Resets configuration and processing state for the new file, then applies the
        saved default configuration only if it validates against the spreadsheet.

        Args:
            file_path: Path to the loaded file (resolved)
            preserve_database: When True, keep the active database pointer (session restore).

        Returns:
            None if there is no default configuration file to check.
            (True, "") if a default exists and is valid for this spreadsheet.
            (False, message) if a default exists but is not valid for this spreadsheet.
        """
        self.app_state.set_spreadsheet_loaded(file_path)
        if not preserve_database:
            self.app_state.set_data_processed(False, None)
        self.app_state.set_spreadsheet_configured(False)
        self.app_state.set_config_valid(False)

        settings = self.config_manager.load_settings()
        settings.set_last_loaded_file(file_path)
        settings.last_loaded_sheet = self.spreadsheet_loader.current_sheet_name
        self.config_manager.save_settings(settings)

        default_config = self.config_manager.load_default_config()
        if not default_config:
            return None

        available_columns = self.spreadsheet_loader.get_column_names()
        is_valid, error_msg = self.config_manager.validate_config_against_spreadsheet(
            default_config, available_columns
        )
        if is_valid:
            self.app_state.set_spreadsheet_configured(True)
            self.app_state.set_config_valid(default_config.is_complete())
            logger.info("Loaded and validated default configuration for spreadsheet")
            return True, ""

        detail = (error_msg or "Unknown validation error").strip()
        logger.info("Default configuration not valid for this spreadsheet: %s", detail)
        return False, detail
    
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

    def _restore_session_on_startup(self) -> None:
        """Restore saved spreadsheet configuration and last active database path."""
        self._restore_default_config_if_available()
        self._restore_last_database_if_available()
        self._update_ui_state()

    def _restore_default_config_if_available(self) -> bool:
        """Apply saved default configuration from disk when structurally valid."""
        default_config = self.config_manager.load_default_config()
        if not default_config:
            return False
        is_valid, error_msg = self.config_manager.validate_config(default_config)
        if not is_valid:
            logger.info("Saved default configuration is not valid: %s", error_msg)
            return False
        self.app_state.set_spreadsheet_configured(True)
        self.app_state.set_config_valid(default_config.is_complete())
        logger.info("Restored saved default configuration from disk")
        return True

    def _restore_last_spreadsheet_if_available(self) -> None:
        """If settings contain a last file path that still exists, load it in the background."""
        if not self._ui_is_active() or self.app_state.spreadsheet_loaded:
            return
        if self._restore_spreadsheet_thread is not None and self._restore_spreadsheet_thread.is_alive():
            return

        settings = self.config_manager.load_settings()
        path = settings.last_loaded_file
        if not path:
            return
        p = Path(path)
        if not p.is_file():
            logger.info("Last spreadsheet path is not available: %s", path)
            return

        sheet = settings.last_loaded_sheet
        path_resolved = str(p.resolve())
        self.status_label.configure(text=f"Restoring last spreadsheet… ({p.name})")

        def worker() -> None:
            loader = SpreadsheetLoader()
            success, err, _df = loader.load_file(path_resolved, sheet_name=sheet)
            self._schedule_on_main(
                self._finish_spreadsheet_restore,
                path_resolved,
                success,
                err,
                loader,
            )

        self._restore_spreadsheet_thread = threading.Thread(target=worker, daemon=True)
        self._restore_spreadsheet_thread.start()

    def _finish_spreadsheet_restore(
        self,
        path_resolved: str,
        success: bool,
        err: Optional[str],
        loader: SpreadsheetLoader,
    ) -> None:
        if not self._ui_is_active():
            return
        self._restore_spreadsheet_thread = None
        if not success or loader.current_data is None:
            logger.info("Could not restore last spreadsheet: %s", err)
            self._update_ui_state()
            return

        self.spreadsheet_loader.current_data = loader.current_data
        self.spreadsheet_loader.current_file_path = loader.current_file_path
        self.spreadsheet_loader.current_sheet_name = loader.current_sheet_name
        self._apply_spreadsheet_loaded(path_resolved, preserve_database=True)
        self._restore_last_database_if_available()
        self._update_ui_state()
        logger.info("Restored last spreadsheet from settings: %s", path_resolved)

    def _restore_last_database_if_available(self) -> None:
        """Reattach the last active database path from settings when the file still exists."""
        if self.app_state.data_processed:
            return
        if not (self.app_state.spreadsheet_configured and self.app_state.config_valid):
            return

        settings = self.config_manager.load_settings()
        path = settings.last_active_database_path
        if not path or not Path(path).is_file():
            return

        try:
            kind = DataStore.peek_database_kind(Path(path))
        except OSError as exc:
            logger.warning("Could not read database kind during restore: %s", exc)
            kind = DB_KIND_FULL
        type_word = "index" if kind == DB_KIND_INDEX else "full"
        self.app_state.set_data_processed(True, path, type_word)
        logger.info("Restored last active database from settings: %s", path)
    
    def _on_enter_visualizer(self) -> None:
        """Handle Enter Visualizer button click."""
        if not self.app_state.can_enter_visualizer():
            logger.warning("Attempted to enter visualizer when not ready")
            return
        
        logger.info("Entering chromatogram visualizer")
        if self._chromatogram_window is not None:
            try:
                self._chromatogram_window.ensure_database_current()
                self._chromatogram_window.lift()
                self._chromatogram_window.focus()
                return
            except tk.TclError:
                self._chromatogram_window = None

        from src.ui.chromatogram_visualizer_window import ChromatogramVisualizerWindow

        self._chromatogram_window = ChromatogramVisualizerWindow(
            self,
            self.app_state,
            self.config_manager,
            self.spreadsheet_loader,
        )

    def _on_enter_library_data(self) -> None:
        """Open Library Analysis dashboard."""
        if not self.app_state.can_access_library_data():
            logger.warning("Attempted to open Library Analysis when not ready")
            return
        logger.info("Opening Library Analysis")
        if self._library_data_window is not None:
            try:
                self._library_data_window.lift()
                self._library_data_window.focus()
                return
            except tk.TclError:
                self._library_data_window = None

        from src.ui.library_data_window import LibraryDataWindow

        self._library_data_window = LibraryDataWindow(
            self,
            self.app_state,
            self.config_manager,
        )

    def _on_analysis_help(self) -> None:
        """Open the in-app analysis help viewer."""
        from src.ui.help_window import open_help_window

        open_help_window(self, "library_analysis")

    def _notify_chromatogram_visualizer_config_changed(self) -> None:
        """Keep an open visualizer in sync with a newly saved spreadsheet configuration."""
        win = self._chromatogram_window
        if win is None:
            return
        try:
            win.refresh_after_configuration_changed()
        except tk.TclError:
            self._chromatogram_window = None

    def _notify_chromatogram_visualizer_database_changed(self) -> None:
        """Keep an open visualizer in sync when the active SQLite database changes."""
        win = self._chromatogram_window
        if win is None:
            return
        try:
            win.refresh_after_database_changed()
        except tk.TclError:
            self._chromatogram_window = None
    
    def _on_load_spreadsheet(self) -> None:
        """Handle Load Spreadsheet button click."""
        logger.info("Load spreadsheet button clicked")
        self._default_validation_after_load = None

        def on_load_success(file_path: str, dataframe) -> None:
            """Handle successful spreadsheet load."""
            self._default_validation_after_load = self._apply_spreadsheet_loaded(
                file_path
            )
            logger.info("Spreadsheet loaded successfully: %s", file_path)
        
        dlg_settings = self.config_manager.load_settings()
        initial_path: Optional[str] = None
        initial_sheet: Optional[str] = None
        if dlg_settings.last_loaded_file:
            lp = Path(dlg_settings.last_loaded_file)
            if lp.is_file():
                initial_path = str(lp)
                initial_sheet = dlg_settings.last_loaded_sheet
        
        from src.ui.load_spreadsheet_dialog import LoadSpreadsheetDialog

        # Open load dialog - store reference to prevent garbage collection
        self.load_dialog = LoadSpreadsheetDialog(
            parent=self,
            loader=self.spreadsheet_loader,
            on_success=on_load_success,
            initial_file_path=initial_path,
            initial_sheet_name=initial_sheet,
        )
        
        # Wait for dialog to close (modal behavior)
        self.wait_window(self.load_dialog)

        pending = getattr(self, "_default_validation_after_load", None)
        self._default_validation_after_load = None
        if pending is not None:
            ok, detail = pending
            if ok:
                messagebox.showinfo(
                    "Default configuration",
                    "Validation passed: the saved default configuration is compatible "
                    "with this spreadsheet.",
                    parent=self,
                )
            else:
                messagebox.showerror(
                    "Default configuration",
                    "Validation failed: the saved default configuration is not valid "
                    f"for this spreadsheet.\n\n{detail}\n\n"
                    "Use Configure Spreadsheet to set up parsing for this file.",
                    parent=self,
                )
    
    def _on_configure_spreadsheet(self) -> None:
        """Handle Configure Spreadsheet button click."""
        if not self.app_state.spreadsheet_loaded:
            logger.warning("Attempted to configure spreadsheet when none loaded")
            return
        
        logger.info("Configure spreadsheet button clicked")
        
        def on_config_success(config) -> None:
            """Handle successful configuration."""
            # Save configuration as default
            self.config_manager.save_default_config(config)
            
            # Update application state - configuration is now complete
            self.app_state.set_spreadsheet_configured(True)
            self.app_state.set_config_valid(config.is_complete())
            
            logger.info(f"Configuration saved and validated. Complete: {config.is_complete()}")
            self._notify_chromatogram_visualizer_config_changed()

        def on_default_preset_applied(config) -> None:
            """Sync app state after Load preset → Default (file already on disk)."""
            self.app_state.set_spreadsheet_configured(True)
            self.app_state.set_config_valid(config.is_complete())
            logger.info(
                "Default preset applied from configure dialog. Complete: %s",
                config.is_complete(),
            )
            self._notify_chromatogram_visualizer_config_changed()
        
        from src.ui.configure_spreadsheet_dialog import ConfigureSpreadsheetDialog

        # Open configuration dialog - store reference to prevent garbage collection
        self.config_dialog = ConfigureSpreadsheetDialog(
            parent=self,
            loader=self.spreadsheet_loader,
            config_manager=self.config_manager,
            on_success=on_config_success,
            on_default_preset_applied=on_default_preset_applied,
        )
        
        # Wait for dialog to close (modal behavior)
        self.wait_window(self.config_dialog)
    
    def _on_database_manage(self) -> None:
        """Open create / load / delete managed bulk database dialog."""
        if not self.app_state.spreadsheet_configured or not self.app_state.config_valid:
            messagebox.showwarning(
                "Configuration Required",
                "A saved spreadsheet configuration is required. Load a spreadsheet and "
                "complete Configure Spreadsheet, or restore your default configuration.",
                parent=self,
            )
            return

        def begin_bulk() -> None:
            if not self.app_state.spreadsheet_loaded or not self.app_state.spreadsheet_path:
                messagebox.showwarning(
                    "Spreadsheet Required",
                    "Load a spreadsheet before creating a full database.",
                    parent=self,
                )
                return
            self._run_bulk_create_database_flow()

        def begin_index() -> None:
            if not self.app_state.spreadsheet_loaded or not self.app_state.spreadsheet_path:
                messagebox.showwarning(
                    "Spreadsheet Required",
                    "Load a spreadsheet before creating an index database.",
                    parent=self,
                )
                return
            self._run_index_database_build_flow()

        def on_database_loaded(path: str, db_kind: str) -> None:
            self._remember_database_path(path)
            self.app_state.set_data_processed(True, path, db_kind)
            self._update_ui_state()
            self._notify_chromatogram_visualizer_database_changed()

        def on_active_cleared() -> None:
            self.app_state.clear_active_database()
            self._update_ui_state()

        from src.ui.database_manage_dialog import DatabaseManageDialog

        self.database_manage_dialog = DatabaseManageDialog(
            self,
            on_begin_bulk_create=begin_bulk,
            on_begin_index_create=begin_index,
            on_database_loaded=on_database_loaded,
            on_active_database_cleared=on_active_cleared,
        )
        self.wait_window(self.database_manage_dialog)
        self.database_manage_dialog = None

    def _run_index_database_build_flow(self) -> None:
        """Build metadata + raw-chromatogram SQLite for search and on-demand plotting."""
        if not self.app_state.spreadsheet_loaded or not self.app_state.spreadsheet_path:
            return
        df = self.spreadsheet_loader.current_data
        if df is None:
            messagebox.showerror(
                "Spreadsheet",
                "No spreadsheet data in memory. Load the spreadsheet again, then retry.",
                parent=self,
            )
            return
        config = self.config_manager.load_default_config()
        if not config or not config.is_complete():
            messagebox.showerror(
                "Configuration Error",
                "No valid configuration found. Please configure the spreadsheet first.",
                parent=self,
            )
            return

        from src.ui.index_database_dialog import IndexDatabaseDialog

        def on_index_success(result: DataProcessingResult) -> None:
            if result.cancelled or not result.database_path:
                return
            self._remember_database_path(result.database_path)
            self.app_state.set_data_processed(True, result.database_path, "index")
            self._update_ui_state()
            self._notify_chromatogram_visualizer_database_changed()
            messagebox.showinfo(
                "Index database",
                f"Index database created.\n{result.database_path}\n\n"
                "Open the Chromatogram Visualizer to search and plot.",
                parent=self,
            )

        index_dialog = IndexDatabaseDialog(
            self,
            dataframe=df,
            config=config,
            on_success=on_index_success,
        )
        self.wait_window(index_dialog)

    def _run_bulk_create_database_flow(self) -> None:
        """Run full SQLite build (ProcessDataDialog) after user confirms in manage dialog."""
        if not self.app_state.spreadsheet_loaded or not self.app_state.spreadsheet_path:
            return
        config = self.config_manager.load_default_config()
        if not config or not config.is_complete():
            messagebox.showerror(
                "Configuration Error",
                "No valid configuration found. Please configure the spreadsheet first.",
                parent=self,
            )
            return

        def on_processing_success(result: DataProcessingResult) -> None:
            if result.database_path:
                self._remember_database_path(result.database_path)
            self.app_state.set_data_processed(True, result.database_path, "full")
            self._update_ui_state()
            self._notify_chromatogram_visualizer_database_changed()
            logger.info(
                "Bulk database created: %s compounds -> %s",
                result.successful_compounds,
                result.database_path,
            )

        previous_close = self.protocol("WM_DELETE_WINDOW")

        def main_close_during_process() -> None:
            dlg = getattr(self, "process_dialog", None)
            if dlg is not None:
                try:
                    if dlg.winfo_exists() and getattr(dlg, "is_processing", False):
                        if not messagebox.askyesno(
                            "Quit",
                            "Database creation is running. Cancel and exit LC-Seq?",
                            parent=self,
                        ):
                            return
                        dlg.user_requested_exit(quit_app=True)
                        return
                except Exception:
                    pass
            previous_close()

        from src.ui.process_data_dialog import ProcessDataDialog

        self.protocol("WM_DELETE_WINDOW", main_close_during_process)
        try:
            self.process_dialog = ProcessDataDialog(
                parent=self,
                file_path=self.app_state.spreadsheet_path,
                config=config,
                on_success=on_processing_success,
                preset_display_name="Default",
            )
            self.wait_window(self.process_dialog)
        finally:
            self.protocol("WM_DELETE_WINDOW", previous_close)
            self.process_dialog = None

        if getattr(self, "_quit_after_process_dialog", False):
            self._quit_after_process_dialog = False
            self.on_close()
    
    def on_close(self) -> None:
        """Handle window close event."""
        self._closing = True
        # Save window size to settings
        width = self.winfo_width()
        height = self.winfo_height()
        settings = self.config_manager.load_settings()
        settings.window_width = width
        settings.window_height = height
        self.config_manager.save_settings(settings)
        
        # Unregister state change callback
        self.app_state.unregister_state_change_callback(self._on_state_change)
        
        logger.info("Main screen closing")
        self.destroy()
    
    def run(self) -> None:
        """Start the main event loop."""
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        logger.info("Starting main event loop")
        self.mainloop()
