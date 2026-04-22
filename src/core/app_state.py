# src/core/app_state.py
"""
Application state management for LC-Seq.
"""

import logging
from typing import Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """
    Application state tracking for UI components.
    
    Attributes:
        spreadsheet_loaded: Whether a spreadsheet has been loaded
        spreadsheet_path: Path to the loaded spreadsheet file
        spreadsheet_configured: Whether the spreadsheet has been configured
        config_valid: Whether the current configuration is valid
        data_processed: Whether data has been processed into database
        database_path: Path to the processed database file
    """
    
    spreadsheet_loaded: bool = False
    spreadsheet_path: Optional[str] = None
    spreadsheet_configured: bool = False
    config_valid: bool = False
    data_processed: bool = False
    database_path: Optional[str] = None
    
    # List of callbacks to notify when state changes
    _state_change_callbacks: list[Callable] = field(default_factory=list, repr=False)
    
    def can_enter_visualizer(self) -> bool:
        """
        Check if user can enter the visualizer.

        Returns:
            True if spreadsheet is loaded, configuration is complete and valid.
            Bulk database processing is optional; on-demand parsing is used when
            no database path is active.
        """
        return (
            self.spreadsheet_loaded
            and self.spreadsheet_configured
            and self.config_valid
        )
    
    def register_state_change_callback(self, callback: Callable) -> None:
        """
        Register a callback to be called when state changes.
        
        Args:
            callback: Function to call when state changes (no arguments)
        """
        if callback not in self._state_change_callbacks:
            self._state_change_callbacks.append(callback)
            logger.debug(f"Registered state change callback: {callback.__name__}")
    
    def unregister_state_change_callback(self, callback: Callable) -> None:
        """
        Unregister a state change callback.
        
        Args:
            callback: Function to unregister
        """
        if callback in self._state_change_callbacks:
            self._state_change_callbacks.remove(callback)
            logger.debug(f"Unregistered state change callback: {callback.__name__}")
    
    def _notify_state_change(self) -> None:
        """Notify all registered callbacks of state change."""
        for callback in self._state_change_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in state change callback {callback.__name__}: {e}")
    
    def set_spreadsheet_loaded(self, path: Optional[str] = None) -> None:
        """
        Set spreadsheet loaded state.
        
        Args:
            path: Path to the loaded spreadsheet file
        """
        self.spreadsheet_loaded = path is not None
        self.spreadsheet_path = path
        logger.info(f"Spreadsheet loaded state: {self.spreadsheet_loaded}, path: {path}")
        self._notify_state_change()
    
    def set_spreadsheet_configured(self, configured: bool = True) -> None:
        """
        Set spreadsheet configured state.
        
        Args:
            configured: Whether spreadsheet is configured
        """
        self.spreadsheet_configured = configured
        logger.info(f"Spreadsheet configured state: {self.spreadsheet_configured}")
        self._notify_state_change()
    
    def set_config_valid(self, valid: bool = True) -> None:
        """
        Set configuration validity state.
        
        Args:
            valid: Whether configuration is valid
        """
        self.config_valid = valid
        logger.info(f"Config valid state: {self.config_valid}")
        self._notify_state_change()
    
    def set_data_processed(self, processed: bool = True, database_path: Optional[str] = None) -> None:
        """
        Set data processed state.
        
        Args:
            processed: Whether data has been processed
            database_path: Path to the database file
        """
        self.data_processed = processed
        self.database_path = database_path
        logger.info(f"Data processed state: {self.data_processed}, database: {database_path}")
        self._notify_state_change()

    def clear_active_database(self) -> None:
        """Unset bulk database path (does not delete the file on disk)."""
        self.set_data_processed(False, None)
    
    def reset(self) -> None:
        """Reset all state to initial values."""
        self.spreadsheet_loaded = False
        self.spreadsheet_path = None
        self.spreadsheet_configured = False
        self.config_valid = False
        self.data_processed = False
        self.database_path = None
        logger.info("Application state reset")
        self._notify_state_change()
    
    def get_status_message(self) -> str:
        """
        Get a human-readable status message based on current state.
        
        Returns:
            Status message string
        """
        if not self.spreadsheet_loaded:
            return "No spreadsheet loaded. Click 'Load Spreadsheet' to begin."
        
        if not self.spreadsheet_configured:
            return "Spreadsheet loaded. Click 'Configure Spreadsheet' to set up parsing."
        
        if not self.config_valid:
            return "Configuration incomplete. Please complete spreadsheet configuration."
        
        if self.data_processed and self.database_path:
            return (
                "Bulk database is active. Open the visualizer to explore data, or use "
                "'Create / Load database' to switch or build another file."
            )

        return (
            "Configuration complete. Open the Chromatogram Visualizer to parse and plot "
            "compounds on demand. Use 'Create / Load database' only if you want a full SQLite export."
        )
