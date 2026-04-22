# src/ui/main_screen.py
"""
Main screen UI for LC-Seq application.
"""

import logging
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import customtkinter as ctk
from typing import Optional

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.ui.load_spreadsheet_dialog import LoadSpreadsheetDialog
from src.ui.configure_spreadsheet_dialog import ConfigureSpreadsheetDialog
from src.ui.process_data_dialog import ProcessDataDialog
from src.ui.database_manage_dialog import DatabaseManageDialog
from src.ui.chromatogram_visualizer_window import ChromatogramVisualizerWindow
from src.core.data_processing_result import DataProcessingResult

logger = logging.getLogger(__name__)


class MainScreen(ctk.CTk):
    """
    Main application screen with primary navigation buttons.
    
    Provides:
    - Load Spreadsheet button
    - Configure Spreadsheet button
    - Enter Chromatogram Visualizer (after valid configuration)
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
        self.database_manage_dialog: Optional[DatabaseManageDialog] = None
        
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
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(4, weight=1)
        
        # Create UI components
        self._create_widgets()
        
        # Center window after widgets are created
        self.center_window()
        
        # Initial state update
        self._update_ui_state()
        
        # Reload last spreadsheet from settings (if path still valid)
        self.after(150, self._restore_last_spreadsheet_if_available)
        
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
        title_label.grid(row=0, column=0, pady=(40, 20), sticky="n")
        
        # Subtitle
        subtitle_label = ctk.CTkLabel(
            self,
            text="Chromatographic Data Analysis",
            font=ctk.CTkFont(size=18)
        )
        subtitle_label.grid(row=1, column=0, pady=(0, 30), sticky="n")
        
        # Primary button: Enter Visualizer
        self.visualizer_button = ctk.CTkButton(
            self,
            text="Enter Chromatogram Visualizer",
            font=ctk.CTkFont(size=16, weight="bold"),
            height=60,
            command=self._on_enter_visualizer,
            state="disabled"
        )
        self.visualizer_button.grid(row=2, column=0, padx=40, pady=20, sticky="ew")
        
        # Load Spreadsheet button
        self.load_button = ctk.CTkButton(
            self,
            text="Load Spreadsheet",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_load_spreadsheet
        )
        self.load_button.grid(row=3, column=0, padx=40, pady=10, sticky="ew")
        
        # Configure Spreadsheet button
        self.configure_button = ctk.CTkButton(
            self,
            text="Configure Spreadsheet",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_configure_spreadsheet,
            state="disabled"
        )
        self.configure_button.grid(row=4, column=0, padx=40, pady=10, sticky="ew")
        
        self.database_manage_button = ctk.CTkButton(
            self,
            text="Create / Load database",
            font=ctk.CTkFont(size=14),
            height=50,
            command=self._on_database_manage,
            state="disabled",
        )
        self.database_manage_button.grid(row=5, column=0, padx=40, pady=10, sticky="ew")
        
        # Status message label
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            wraplength=600,
            justify="center"
        )
        self.status_label.grid(row=6, column=0, padx=40, pady=(30, 20), sticky="n")
    
    def _on_state_change(self) -> None:
        """Handle application state change."""
        self._update_ui_state()
    
    def _update_ui_state(self) -> None:
        """Update UI elements based on current application state."""
        # Update visualizer button state
        can_enter = self.app_state.can_enter_visualizer()
        self.visualizer_button.configure(state="normal" if can_enter else "disabled")
        
        # Update configure button state
        self.configure_button.configure(
            state="normal" if self.app_state.spreadsheet_loaded else "disabled"
        )
        
        can_manage_db = (
            self.app_state.spreadsheet_loaded
            and self.app_state.spreadsheet_configured
            and self.app_state.config_valid
        )
        self.database_manage_button.configure(
            state="normal" if can_manage_db else "disabled"
        )
        
        # Update status message
        status_message = self.app_state.get_status_message()
        self.status_label.configure(text=status_message)
        
        logger.debug(
            "UI state updated. Can enter visualizer: %s, Can manage DB: %s",
            can_enter,
            can_manage_db,
        )
    
    def _apply_spreadsheet_loaded(
        self, file_path: str
    ) -> Optional[tuple[bool, str]]:
        """
        Update application state and settings after a successful spreadsheet load.

        Resets configuration and processing state for the new file, then applies the
        saved default configuration only if it validates against the spreadsheet.

        Args:
            file_path: Path to the loaded file (resolved)

        Returns:
            None if there is no default configuration file to check.
            (True, "") if a default exists and is valid for this spreadsheet.
            (False, message) if a default exists but is not valid for this spreadsheet.
        """
        self.app_state.set_spreadsheet_loaded(file_path)
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
    
    def _restore_last_spreadsheet_if_available(self) -> None:
        """If settings contain a last file path that still exists, load it silently."""
        if self.app_state.spreadsheet_loaded:
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
        success, err, df = self.spreadsheet_loader.load_file(str(p), sheet_name=sheet)
        if not success or df is None:
            logger.info("Could not restore last spreadsheet: %s", err)
            return
        self._apply_spreadsheet_loaded(str(p.resolve()))
        self._update_ui_state()
        logger.info("Restored last spreadsheet from settings: %s", path)
    
    def _on_enter_visualizer(self) -> None:
        """Handle Enter Visualizer button click."""
        if not self.app_state.can_enter_visualizer():
            logger.warning("Attempted to enter visualizer when not ready")
            return
        
        logger.info("Entering chromatogram visualizer")
        if self._chromatogram_window is not None:
            try:
                self._chromatogram_window.lift()
                self._chromatogram_window.focus()
                return
            except tk.TclError:
                self._chromatogram_window = None

        self._chromatogram_window = ChromatogramVisualizerWindow(
            self,
            self.app_state,
            self.config_manager,
            self.spreadsheet_loader,
        )
    
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

        def on_default_preset_applied(config) -> None:
            """Sync app state after Load preset → Default (file already on disk)."""
            self.app_state.set_spreadsheet_configured(True)
            self.app_state.set_config_valid(config.is_complete())
            logger.info(
                "Default preset applied from configure dialog. Complete: %s",
                config.is_complete(),
            )
        
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
        if not self.app_state.spreadsheet_loaded or not self.app_state.spreadsheet_path:
            logger.warning("Database manage requested without spreadsheet")
            return
        if not self.app_state.config_valid:
            messagebox.showwarning(
                "Configuration Required",
                "Please complete spreadsheet configuration first.",
                parent=self,
            )
            return

        def begin_bulk() -> None:
            self._run_bulk_create_database_flow()

        def on_database_loaded(path: str) -> None:
            self.app_state.set_data_processed(True, path)
            self._update_ui_state()

        def on_active_cleared() -> None:
            self.app_state.clear_active_database()
            self._update_ui_state()

        self.database_manage_dialog = DatabaseManageDialog(
            self,
            on_begin_bulk_create=begin_bulk,
            on_database_loaded=on_database_loaded,
            on_active_database_cleared=on_active_cleared,
        )
        self.wait_window(self.database_manage_dialog)
        self.database_manage_dialog = None

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
            self.app_state.set_data_processed(True, result.database_path)
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
