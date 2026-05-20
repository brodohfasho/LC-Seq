# src/main.py
"""
Main entry point for LC-Seq application.

This is the primary entry point that launches the LC-Seq
chromatographic data analysis application.
"""

import sys
from pathlib import Path

# Repo root must be on sys.path before any ``src.*`` import when running from source.
# PyInstaller sets this up automatically when frozen.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.app_paths import resolve_user_path

import customtkinter as ctk

from src.core.logging_config import setup_logging, get_logger
from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.ui.main_screen import MainScreen

# Set up logging
setup_logging()
logger = get_logger(__name__)


def main():
    """
    Main application entry point.
    
    Initializes the application and starts the main UI.
    """
    logger.info("LC-Seq application starting...")
    
    try:
        # Set customtkinter appearance mode and color theme
        ctk.set_appearance_mode("system")  # Use system theme
        ctk.set_default_color_theme("blue")  # Use blue color theme
        
        # Initialize core components
        app_state = AppState()
        config_manager = ConfigManager()
        
        # Load saved settings
        settings = config_manager.load_settings()
        log_file = settings.log_file
        if log_file:
            log_file = str(resolve_user_path(log_file))
        if settings.log_level:
            setup_logging(log_level=settings.log_level, log_file=log_file)
        
        # Create and run main screen
        app = MainScreen(app_state, config_manager)
        app.run()
        
        logger.info("LC-Seq application exiting")
        return 0
    
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
