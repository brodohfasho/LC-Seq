# src/ui/main_screen.py
"""
Main screen UI for LC-Seq application.
"""

import customtkinter as ctk
import logging
from typing import Optional

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.ui.load_spreadsheet_dialog import LoadSpreadsheetDialog
from src.ui.configure_spreadsheet_dialog import ConfigureSpreadsheetDialog

logger = logging.getLogger(__name__)


class MainScreen(ctk.CTk):
    """
    Main application screen with primary navigation buttons.
    
    Provides:
    - Load Spreadsheet button
    - Configure Spreadsheet button
    - Enter Chromatogram Visualizer button (disabled until ready)
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
        
        # Status message label
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            wraplength=600,
            justify="center"
        )
        self.status_label.grid(row=5, column=0, padx=40, pady=(30, 20), sticky="n")
    
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
        
        # Update status message
        status_message = self.app_state.get_status_message()
        self.status_label.configure(text=status_message)
        
        logger.debug(f"UI state updated. Can enter visualizer: {can_enter}")
    
    def _on_enter_visualizer(self) -> None:
        """Handle Enter Visualizer button click."""
        if not self.app_state.can_enter_visualizer():
            logger.warning("Attempted to enter visualizer when not ready")
            return
        
        logger.info("Entering chromatogram visualizer")
        # TODO: Implement visualizer window (Phase 10-12)
        # For now, show a placeholder message
        from tkinter import messagebox
        messagebox.showinfo(
            "Visualizer",
            "Chromatogram Visualizer will be implemented in Phase 10-12.\n\n"
            "This will allow you to plot and search your chromatographic data."
        )
    
    def _on_load_spreadsheet(self) -> None:
        """Handle Load Spreadsheet button click."""
        logger.info("Load spreadsheet button clicked")
        
        def on_load_success(file_path: str, dataframe) -> None:
            """Handle successful spreadsheet load."""
            # Update application state
            self.app_state.set_spreadsheet_loaded(file_path)
            
            # Save file path to settings
            settings = self.config_manager.load_settings()
            settings.set_last_loaded_file(file_path)
            self.config_manager.save_settings(settings)
            
            # Phase 8: Try to load default configuration if available
            default_config = self.config_manager.load_default_config()
            if default_config:
                # Validate config against loaded spreadsheet
                available_columns = self.spreadsheet_loader.get_column_names()
                is_valid, error_msg = self.config_manager.validate_config_against_spreadsheet(
                    default_config, available_columns
                )
                if is_valid:
                    # Config is valid - mark as configured
                    self.app_state.set_spreadsheet_configured(True)
                    self.app_state.set_config_valid(default_config.is_complete())
                    logger.info("Loaded and validated default configuration for spreadsheet")
                else:
                    logger.info(f"Default configuration not valid for this spreadsheet: {error_msg}")
            
            logger.info(f"Spreadsheet loaded successfully: {file_path}")
        
        # Open load dialog - store reference to prevent garbage collection
        self.load_dialog = LoadSpreadsheetDialog(
            parent=self,
            loader=self.spreadsheet_loader,
            on_success=on_load_success
        )
        
        # Wait for dialog to close (modal behavior)
        self.wait_window(self.load_dialog)
    
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
        
        # Open configuration dialog - store reference to prevent garbage collection
        self.config_dialog = ConfigureSpreadsheetDialog(
            parent=self,
            loader=self.spreadsheet_loader,
            config_manager=self.config_manager,
            on_success=on_config_success
        )
        
        # Wait for dialog to close (modal behavior)
        self.wait_window(self.config_dialog)
    
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
