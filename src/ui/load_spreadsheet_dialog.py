# src/ui/load_spreadsheet_dialog.py
"""
Dialog for loading spreadsheet files.
"""

import customtkinter as ctk
import logging
from pathlib import Path
from typing import Optional, Callable

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
    - Loading status feedback
    """
    
    def __init__(self, parent: ctk.CTk, loader: SpreadsheetLoader, on_success: Optional[Callable] = None):
        """
        Initialize load spreadsheet dialog.
        
        Args:
            parent: Parent window
            loader: SpreadsheetLoader instance
            on_success: Callback function called with (file_path, dataframe) on successful load
        """
        super().__init__(parent, title="Load Spreadsheet")
        
        self.loader = loader
        self.on_success = on_success
        
        self.geometry("600x400")
        self.center_window(600, 400)
        
        # Selected file path
        self.selected_file_path: Optional[str] = None
        self.loaded_dataframe = None
        
        # Create UI
        self._create_widgets()
        
        logger.info("Load spreadsheet dialog initialized")
    
    def _create_widgets(self) -> None:
        """Create and layout UI widgets."""
        # Instructions
        instructions = ctk.CTkLabel(
            self,
            text="Select a spreadsheet file to load:",
            font=ctk.CTkFont(size=14)
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="w")
        
        # File path display
        self.file_path_label = ctk.CTkLabel(
            self,
            text="No file selected",
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=500
        )
        self.file_path_label.grid(row=1, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        
        # Browse button
        self.browse_button = ctk.CTkButton(
            self,
            text="Browse...",
            command=self._on_browse
        )
        self.browse_button.grid(row=2, column=0, columnspan=2, padx=20, pady=10)
        
        # Sheet selection (for Excel files)
        self.sheet_frame = ctk.CTkFrame(self)
        self.sheet_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        self.sheet_frame.grid_remove()  # Hidden by default
        
        sheet_label = ctk.CTkLabel(
            self.sheet_frame,
            text="Select sheet:",
            font=ctk.CTkFont(size=12)
        )
        sheet_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.sheet_var = ctk.StringVar()
        self.sheet_dropdown = ctk.CTkComboBox(
            self.sheet_frame,
            variable=self.sheet_var,
            values=[],
            command=self._on_sheet_selected
        )
        self.sheet_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.sheet_frame.grid_columnconfigure(1, weight=1)
        
        # Status message
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            wraplength=550,
            justify="left"
        )
        self.status_label.grid(row=4, column=0, columnspan=2, padx=20, pady=10, sticky="w")
        
        # Buttons frame
        button_frame = ctk.CTkFrame(self)
        button_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        
        # Load button
        self.load_button = ctk.CTkButton(
            button_frame,
            text="Load",
            command=self._on_load,
            state="disabled"
        )
        self.load_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Cancel button
        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self.on_close,
            fg_color="gray"
        )
        cancel_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
    
    def _on_browse(self) -> None:
        """Handle Browse button click."""
        from tkinter import filedialog
        
        # Open file dialog
        file_path = filedialog.askopenfilename(
            title="Select Spreadsheet File",
            filetypes=[
                ("All Supported", "*.xlsx *.xls *.csv"),
                ("Excel Files", "*.xlsx *.xls"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*")
            ]
        )
        
        if file_path:
            self.selected_file_path = file_path
            self._update_file_display()
            self._check_for_sheets()
    
    def _update_file_display(self) -> None:
        """Update file path display."""
        if self.selected_file_path:
            self.file_path_label.configure(text=f"Selected: {self.selected_file_path}")
            self.load_button.configure(state="normal")
            self.status_label.configure(text="")
        else:
            self.file_path_label.configure(text="No file selected")
            self.load_button.configure(state="disabled")
    
    def _check_for_sheets(self) -> None:
        """Check if file has multiple sheets and show sheet selector."""
        if not self.selected_file_path:
            return
        
        sheets = self.loader.get_available_sheets(self.selected_file_path)
        
        if sheets and len(sheets) > 1:
            # Multiple sheets - show selector
            self.sheet_dropdown.configure(values=sheets)
            self.sheet_var.set(sheets[0])  # Default to first sheet
            self.sheet_frame.grid()
        else:
            # Single sheet or CSV - hide selector
            self.sheet_frame.grid_remove()
            self.sheet_var.set("")
    
    def _on_sheet_selected(self, choice: str) -> None:
        """Handle sheet selection change."""
        logger.debug(f"Sheet selected: {choice}")
    
    def _on_load(self) -> None:
        """Handle Load button click."""
        if not self.selected_file_path:
            return
        
        # Disable buttons during loading
        self.load_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.status_label.configure(text="Loading spreadsheet...")
        self.update()
        
        # Get selected sheet (if Excel)
        sheet_name = None
        if self.sheet_var.get():
            sheet_name = self.sheet_var.get()
        
        # Load file
        success, error_message, dataframe = self.loader.load_file(
            self.selected_file_path,
            sheet_name=sheet_name
        )
        
        if success and dataframe is not None:
            self.loaded_dataframe = dataframe
            self.status_label.configure(
                text=f"✓ Successfully loaded {dataframe.shape[0]} rows, {dataframe.shape[1]} columns",
                text_color="green"
            )
            
            # Call success callback
            if self.on_success:
                self.on_success(self.selected_file_path, dataframe)
            
            # Close dialog after short delay
            self.after(1000, self.on_close)
        else:
            # Show error
            error_text = error_message or "Unknown error occurred"
            self.status_label.configure(text=f"✗ Error: {error_text}", text_color="red")
            self.load_button.configure(state="normal")
            self.browse_button.configure(state="normal")
            logger.error(f"Failed to load spreadsheet: {error_text}")
