# src/ui/base_window.py
"""
Base window class for consistent UI components.
"""

import customtkinter as ctk
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BaseWindow(ctk.CTkToplevel):
    """
    Base window class providing common functionality for all windows.
    
    All application windows should inherit from this class for consistency.
    """
    
    def __init__(self, parent: Optional[ctk.CTk] = None, title: str = "LC-Seq", **kwargs):
        """
        Initialize base window.
        
        Args:
            parent: Parent window (main application window)
            title: Window title
            **kwargs: Additional arguments passed to CTkToplevel
        """
        super().__init__(parent, **kwargs)
        
        self.title(title)
        self.parent = parent
        
        # Set window properties
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        logger.debug(f"Created base window: {title}")
    
    def on_close(self) -> None:
        """
        Handle window close event.
        
        Override this method in subclasses to add custom cleanup.
        """
        logger.debug(f"Closing window: {self.title()}")
        self.destroy()
    
    def center_window(self, width: Optional[int] = None, height: Optional[int] = None) -> None:
        """
        Center the window on the screen.
        
        Args:
            width: Window width (uses current if None)
            height: Window height (uses current if None)
        """
        self.update_idletasks()
        
        if width is None:
            width = self.winfo_width()
        if height is None:
            height = self.winfo_height()
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        self.geometry(f"{width}x{height}+{x}+{y}")
        logger.debug(f"Centered window at {x}, {y}")
