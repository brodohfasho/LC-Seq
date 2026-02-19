# src/ui/configure_spreadsheet_dialog.py
"""
Dialog for configuring spreadsheet parsing settings.
"""

import customtkinter as ctk
import logging
import pandas as pd
from typing import Optional, Callable, List

from src.ui.base_window import BaseWindow
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.core.config_manager import ConfigManager
from src.models.spreadsheet_config import SpreadsheetConfig
from src.utils.data_parser import DataParser

logger = logging.getLogger(__name__)


class ConfigureSpreadsheetDialog(BaseWindow):
    """
    Dialog window for configuring spreadsheet parsing.
    
    Phase 5: Column Selection
    - Displays loaded spreadsheet column headers
    - Allows selection of Compound ID column
    - Allows selection of Chromatographic Data column
    - Validates column selections
    
    Phase 6: Delimiter Configuration
    - Configure delimiter sequence (order matters)
    - Support common delimiters and custom input
    - Parsing preview with test data
    - Display parsed results
    """
    
    def __init__(
        self,
        parent: ctk.CTk,
        loader: SpreadsheetLoader,
        config_manager: ConfigManager,
        on_success: Optional[Callable[[SpreadsheetConfig], None]] = None
    ):
        """
        Initialize configure spreadsheet dialog.
        
        Args:
            parent: Parent window
            loader: SpreadsheetLoader instance with loaded data
            config_manager: ConfigManager instance
            on_success: Callback function called with SpreadsheetConfig on successful configuration
        """
        super().__init__(parent, title="Configure Spreadsheet")
        
        self.loader = loader
        self.config_manager = config_manager
        self.on_success = on_success
        
        self.geometry("1000x900")
        self.center_window(1000, 900)
        
        # Column selections
        self.selected_compound_id_column: Optional[str] = None
        self.selected_chromatographic_data_column: Optional[str] = None
        
        # Delimiter configuration
        self.delimiters: List[str] = []
        
        # Phase 7: Time & Count selection
        self.parsed_data_points: List[List[str]] = []
        self.parsed_flat_items: List[str] = []
        self.items_per_point: Optional[int] = None
        self.selected_time_index: Optional[int] = None
        self.selected_count_indices: List[int] = []
        self.count_names: List[str] = []
        self.count_checkboxes: dict[int, ctk.CTkCheckBox] = {}
        self.count_name_entries: dict[int, ctk.CTkEntry] = {}
        
        # Phase 7.3: Metadata column selection
        self.selected_metadata_columns: List[str] = []
        self.metadata_checkboxes: dict[str, ctk.CTkCheckBox] = {}
        
        # Get available columns
        self.available_columns: List[str] = self.loader.get_column_names()
        
        # Common delimiters
        self.common_delimiters = {
            "Comma": ",",
            "Semicolon": ";",
            "Colon": ":",
            "Tab": "\t",
            "Pipe": "|",
            "Space": " "
        }
        
        if not self.available_columns:
            logger.error("No columns available in loaded spreadsheet")
            self._show_error("No columns found in loaded spreadsheet. Please load a valid spreadsheet first.")
            self.after(100, self.on_close)
            return
        
        # Load existing configuration if available
        self._load_existing_config()
        
        # Create scrollable frame for content
        self._create_scrollable_frame()
        
        # Create UI
        self._create_widgets()
        
        logger.info("Configure spreadsheet dialog initialized")
    
    def _create_scrollable_frame(self) -> None:
        """Create scrollable frame for dialog content."""
        # Main scrollable frame
        self.scrollable_frame = ctk.CTkScrollableFrame(self)
        self.scrollable_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.scrollable_frame.grid_columnconfigure(0, weight=1)
        
        # Configure main grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
    
    def _load_existing_config(self) -> None:
        """Load existing configuration if available and validate against spreadsheet."""
        try:
            existing_config = self.config_manager.load_default_config()
            if existing_config:
                # Validate config against current spreadsheet
                is_valid, error_msg = self.config_manager.validate_config_against_spreadsheet(
                    existing_config, self.available_columns
                )
                
                if is_valid:
                    # Config is valid - load it
                    if existing_config.compound_id_column in self.available_columns:
                        self.selected_compound_id_column = existing_config.compound_id_column
                    if existing_config.chromatographic_data_column in self.available_columns:
                        self.selected_chromatographic_data_column = existing_config.chromatographic_data_column
                    # Load delimiters if available
                    if existing_config.delimiters:
                        self.delimiters = existing_config.delimiters.copy()
                    # Load Phase 7 settings if available
                    if existing_config.time_column_index is not None:
                        self.selected_time_index = existing_config.time_column_index
                    if existing_config.count_column_indices:
                        self.selected_count_indices = existing_config.count_column_indices.copy()
                    if existing_config.count_names:
                        self.count_names = existing_config.count_names.copy()
                    # Load Phase 7.3 metadata columns if available
                    if existing_config.selected_metadata_columns:
                        self.selected_metadata_columns = existing_config.selected_metadata_columns.copy()
                    logger.debug("Loaded and validated existing configuration")
                else:
                    logger.warning(f"Existing configuration is not valid for current spreadsheet: {error_msg}")
        except Exception as e:
            logger.warning(f"Could not load existing configuration: {e}")
    
    def _create_widgets(self) -> None:
        """Create and layout UI widgets."""
        row = 0
        
        # Phase 8: Load/Save Configuration
        config_management_frame = ctk.CTkFrame(self.scrollable_frame)
        config_management_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="ew")
        config_management_frame.grid_columnconfigure(1, weight=1)
        row += 1
        
        load_config_label = ctk.CTkLabel(
            config_management_frame,
            text="Load Saved Configuration:",
            font=ctk.CTkFont(size=12)
        )
        load_config_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        # List of saved configs
        saved_configs = self.config_manager.list_named_configs()
        config_names = [config["name"] for config in saved_configs]
        
        self.config_dropdown_var = ctk.StringVar()
        self.config_dropdown = ctk.CTkComboBox(
            config_management_frame,
            variable=self.config_dropdown_var,
            values=["Default"] + config_names if config_names else ["Default"],
            command=self._on_load_saved_config,
            state="readonly",
            width=200
        )
        self.config_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        
        load_button = ctk.CTkButton(
            config_management_frame,
            text="Load",
            command=self._load_selected_config,
            width=80
        )
        load_button.grid(row=0, column=2, padx=10, pady=10)
        
        save_as_button = ctk.CTkButton(
            config_management_frame,
            text="Save As...",
            command=self._save_config_as,
            width=100
        )
        save_as_button.grid(row=0, column=3, padx=10, pady=10)
        
        # Instructions
        instructions = ctk.CTkLabel(
            self.scrollable_frame,
            text="Step 1: Select columns from your spreadsheet",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        instructions.grid(row=row, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="w")
        row += 1
        
        # Available columns display
        columns_frame = ctk.CTkFrame(self.scrollable_frame)
        columns_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        row += 1
        columns_frame.grid_columnconfigure(0, weight=1)
        
        columns_label = ctk.CTkLabel(
            columns_frame,
            text="Available Columns:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        columns_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        # Display column list
        columns_text = ", ".join(self.available_columns)
        columns_display = ctk.CTkLabel(
            columns_frame,
            text=columns_text,
            font=ctk.CTkFont(size=11),
            anchor="w",
            justify="left",
            wraplength=650
        )
        columns_display.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        
        # Compound ID column selection
        compound_frame = ctk.CTkFrame(self.scrollable_frame)
        compound_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        row += 1
        compound_frame.grid_columnconfigure(1, weight=1)
        
        compound_label = ctk.CTkLabel(
            compound_frame,
            text="Compound ID Column:",
            font=ctk.CTkFont(size=12)
        )
        compound_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.compound_var = ctk.StringVar()
        if self.selected_compound_id_column:
            self.compound_var.set(self.selected_compound_id_column)
        
        self.compound_dropdown = ctk.CTkComboBox(
            compound_frame,
            variable=self.compound_var,
            values=self.available_columns,
            command=self._on_compound_id_selected,
            state="readonly"
        )
        self.compound_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # Selected compound ID display
        self.compound_selected_label = ctk.CTkLabel(
            compound_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.compound_selected_label.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")
        self._update_compound_display()
        
        # Chromatographic Data column selection
        data_frame = ctk.CTkFrame(self.scrollable_frame)
        data_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        row += 1
        data_frame.grid_columnconfigure(1, weight=1)
        
        data_label = ctk.CTkLabel(
            data_frame,
            text="Chromatographic Data Column:",
            font=ctk.CTkFont(size=12)
        )
        data_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.data_var = ctk.StringVar()
        if self.selected_chromatographic_data_column:
            self.data_var.set(self.selected_chromatographic_data_column)
        
        self.data_dropdown = ctk.CTkComboBox(
            data_frame,
            variable=self.data_var,
            values=self.available_columns,
            command=self._on_chromatographic_data_selected,
            state="readonly"
        )
        self.data_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # Selected chromatographic data display
        self.data_selected_label = ctk.CTkLabel(
            data_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.data_selected_label.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")
        self._update_data_display()
        
        # Separator
        separator1 = ctk.CTkFrame(self.scrollable_frame, height=2, fg_color="gray")
        separator1.grid(row=row, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        row += 1
        
        # Phase 6: Delimiter Configuration
        delimiter_instructions = ctk.CTkLabel(
            self.scrollable_frame,
            text="Step 2: Configure delimiters for parsing chromatographic data",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        delimiter_instructions.grid(row=row, column=0, columnspan=2, padx=20, pady=(10, 10), sticky="w")
        row += 1
        
        # Delimiter configuration frame
        delimiter_config_frame = ctk.CTkFrame(self.scrollable_frame)
        delimiter_config_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        delimiter_config_frame.grid_columnconfigure(0, weight=1)
        row += 1
        
        # Delimiter sequence display
        delimiter_label = ctk.CTkLabel(
            delimiter_config_frame,
            text="Delimiter Sequence (order matters):",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        delimiter_label.grid(row=0, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w")
        
        # Delimiter list display
        self.delimiter_list_frame = ctk.CTkFrame(delimiter_config_frame)
        self.delimiter_list_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        self.delimiter_list_frame.grid_columnconfigure(0, weight=1)
        
        self.delimiter_display_label = ctk.CTkLabel(
            self.delimiter_list_frame,
            text="No delimiters added",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.delimiter_display_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        # Common delimiter buttons
        common_label = ctk.CTkLabel(
            delimiter_config_frame,
            text="Common Delimiters:",
            font=ctk.CTkFont(size=11)
        )
        common_label.grid(row=2, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="w")
        
        common_buttons_frame = ctk.CTkFrame(delimiter_config_frame)
        common_buttons_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        
        self.common_delimiter_buttons = {}
        col = 0
        for name, delimiter in self.common_delimiters.items():
            btn = ctk.CTkButton(
                common_buttons_frame,
                text=name,
                command=lambda d=delimiter: self._add_delimiter(d),
                width=100,
                height=30
            )
            btn.grid(row=0, column=col, padx=5, pady=5)
            self.common_delimiter_buttons[name] = btn
            col += 1
        
        # Custom delimiter input
        custom_frame = ctk.CTkFrame(delimiter_config_frame)
        custom_frame.grid(row=4, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        custom_frame.grid_columnconfigure(1, weight=1)
        
        custom_label = ctk.CTkLabel(
            custom_frame,
            text="Custom Delimiter:",
            font=ctk.CTkFont(size=11)
        )
        custom_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.custom_delimiter_entry = ctk.CTkEntry(
            custom_frame,
            placeholder_text="Enter custom delimiter",
            width=200
        )
        self.custom_delimiter_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        add_custom_button = ctk.CTkButton(
            custom_frame,
            text="Add",
            command=self._add_custom_delimiter,
            width=80
        )
        add_custom_button.grid(row=0, column=2, padx=10, pady=10)
        
        # Remove/Reorder buttons
        control_frame = ctk.CTkFrame(delimiter_config_frame)
        control_frame.grid(row=5, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        remove_button = ctk.CTkButton(
            control_frame,
            text="Remove Last",
            command=self._remove_last_delimiter,
            fg_color="red",
            width=120
        )
        remove_button.grid(row=0, column=0, padx=5, pady=5)
        
        clear_button = ctk.CTkButton(
            control_frame,
            text="Clear All",
            command=self._clear_delimiters,
            fg_color="orange",
            width=120
        )
        clear_button.grid(row=0, column=1, padx=5, pady=5)
        
        # Separator
        separator2 = ctk.CTkFrame(self.scrollable_frame, height=2, fg_color="gray")
        separator2.grid(row=row, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        row += 1
        
        # Phase 6: Parsing Preview
        preview_instructions = ctk.CTkLabel(
            self.scrollable_frame,
            text="Step 3: Test parsing with sample data",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        preview_instructions.grid(row=row, column=0, columnspan=2, padx=20, pady=(10, 10), sticky="w")
        row += 1
        
        # Test data input frame
        test_data_frame = ctk.CTkFrame(self.scrollable_frame)
        test_data_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        test_data_frame.grid_columnconfigure(1, weight=1)
        row += 1
        
        test_data_label = ctk.CTkLabel(
            test_data_frame,
            text="Test Data:",
            font=ctk.CTkFont(size=12)
        )
        test_data_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.test_data_entry = ctk.CTkEntry(
            test_data_frame,
            placeholder_text="Enter test data or click 'Load Sample'",
            width=400
        )
        self.test_data_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        load_sample_button = ctk.CTkButton(
            test_data_frame,
            text="Load Sample",
            command=self._load_sample_data,
            width=120
        )
        load_sample_button.grid(row=0, column=2, padx=10, pady=10)
        
        test_parse_button = ctk.CTkButton(
            test_data_frame,
            text="Test Parse",
            command=self._test_parse,
            width=120
        )
        test_parse_button.grid(row=0, column=3, padx=10, pady=10)
        
        # Parsing results frame
        results_frame = ctk.CTkFrame(self.scrollable_frame)
        results_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        results_frame.grid_columnconfigure(0, weight=1)
        row += 1
        
        results_label = ctk.CTkLabel(
            results_frame,
            text="Parsing Results:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        results_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        # Preview table (using text widget for simplicity)
        self.preview_text = ctk.CTkTextbox(
            results_frame,
            height=150,
            width=800
        )
        self.preview_text.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.preview_text.insert("1.0", "No parsing results yet. Enter test data and click 'Test Parse'.")
        
        # Parse status
        self.parse_status_label = ctk.CTkLabel(
            results_frame,
            text="",
            font=ctk.CTkFont(size=11)
        )
        self.parse_status_label.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        
        # Separator
        separator3 = ctk.CTkFrame(self.scrollable_frame, height=2, fg_color="gray")
        separator3.grid(row=row, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        row += 1
        
        # Phase 7: Time & Count Selection
        time_count_instructions = ctk.CTkLabel(
            self.scrollable_frame,
            text="Step 4: Select Time and Count fields",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        time_count_instructions.grid(row=row, column=0, columnspan=2, padx=20, pady=(10, 10), sticky="w")
        row += 1
        
        # Items per point configuration
        items_per_point_frame = ctk.CTkFrame(self.scrollable_frame)
        items_per_point_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        items_per_point_frame.grid_columnconfigure(1, weight=1)
        row += 1
        
        items_label = ctk.CTkLabel(
            items_per_point_frame,
            text="Items per Data Point:",
            font=ctk.CTkFont(size=12)
        )
        items_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.items_per_point_entry = ctk.CTkEntry(
            items_per_point_frame,
            placeholder_text="e.g., 2 for Time,Count or 3 for Time,Count1,Count2",
            width=300
        )
        self.items_per_point_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        structure_button = ctk.CTkButton(
            items_per_point_frame,
            text="Structure Data",
            command=self._structure_parsed_data,
            width=120
        )
        structure_button.grid(row=0, column=2, padx=10, pady=10)
        
        # Structured data display
        structured_frame = ctk.CTkFrame(self.scrollable_frame)
        structured_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        structured_frame.grid_columnconfigure(0, weight=1)
        row += 1
        
        structured_label = ctk.CTkLabel(
            structured_frame,
            text="Structured Data Points:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        structured_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        self.structured_text = ctk.CTkTextbox(
            structured_frame,
            height=120,
            width=800
        )
        self.structured_text.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        self.structured_text.insert("1.0", "Parse test data first, then specify items per point and click 'Structure Data'.")
        
        # Time selection
        time_selection_frame = ctk.CTkFrame(self.scrollable_frame)
        time_selection_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        time_selection_frame.grid_columnconfigure(1, weight=1)
        row += 1
        
        time_label = ctk.CTkLabel(
            time_selection_frame,
            text="Time Field Index:",
            font=ctk.CTkFont(size=12)
        )
        time_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.time_index_var = ctk.StringVar()
        self.time_index_dropdown = ctk.CTkComboBox(
            time_selection_frame,
            variable=self.time_index_var,
            values=[],
            command=self._on_time_index_selected,
            state="readonly",
            width=200
        )
        self.time_index_dropdown.grid(row=0, column=1, padx=10, pady=10, sticky="w")
        
        # Count selection frame
        count_selection_frame = ctk.CTkFrame(self.scrollable_frame)
        count_selection_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        count_selection_frame.grid_columnconfigure(0, weight=1)
        row += 1
        
        count_label = ctk.CTkLabel(
            count_selection_frame,
            text="Count Fields (select multiple):",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        count_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")
        
        # Scrollable frame for count checkboxes
        self.count_checkboxes_frame = ctk.CTkScrollableFrame(count_selection_frame, height=100)
        self.count_checkboxes_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.count_checkboxes_frame.grid_columnconfigure(0, weight=1)
        
        # Count names frame
        count_names_frame = ctk.CTkFrame(self.scrollable_frame)
        count_names_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        count_names_frame.grid_columnconfigure(1, weight=1)
        row += 1
        
        count_names_label = ctk.CTkLabel(
            count_names_frame,
            text="Count Names:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        count_names_label.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")
        
        self.count_names_frame = ctk.CTkFrame(count_names_frame)
        self.count_names_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.count_names_frame.grid_columnconfigure(1, weight=1)
        
        # Separator
        separator4 = ctk.CTkFrame(self.scrollable_frame, height=2, fg_color="gray")
        separator4.grid(row=row, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        row += 1
        
        # Phase 7.3: Metadata Column Selection
        metadata_instructions = ctk.CTkLabel(
            self.scrollable_frame,
            text="Step 5: Select metadata columns for database (optional but recommended)",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        metadata_instructions.grid(row=row, column=0, columnspan=2, padx=20, pady=(10, 5), sticky="w")
        row += 1
        
        # Explanation text
        explanation_text = (
            "Select which metadata columns to include in the searchable database. "
            "Including only necessary columns improves efficiency and speeds up searches. "
            "You can search and filter by these columns in the visualizer."
        )
        explanation_label = ctk.CTkLabel(
            self.scrollable_frame,
            text=explanation_text,
            font=ctk.CTkFont(size=11),
            wraplength=950,
            justify="left"
        )
        explanation_label.grid(row=row, column=0, columnspan=2, padx=20, pady=(0, 10), sticky="w")
        row += 1
        
        # Metadata column selection frame
        metadata_selection_frame = ctk.CTkFrame(self.scrollable_frame)
        metadata_selection_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="ew")
        metadata_selection_frame.grid_columnconfigure(0, weight=1)
        row += 1
        
        metadata_label = ctk.CTkLabel(
            metadata_selection_frame,
            text="Available Metadata Columns:",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        metadata_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        # Get metadata columns (exclude compound_id and chromatographic_data columns)
        self.metadata_columns = self._get_metadata_columns()
        
        if self.metadata_columns:
            # Scrollable frame for metadata checkboxes
            self.metadata_checkboxes_frame = ctk.CTkScrollableFrame(metadata_selection_frame, height=150)
            self.metadata_checkboxes_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
            self.metadata_checkboxes_frame.grid_columnconfigure(0, weight=1)
            
            # Create checkboxes for each metadata column
            self._create_metadata_checkboxes()
            
            # Select All / Deselect All buttons
            metadata_buttons_frame = ctk.CTkFrame(metadata_selection_frame)
            metadata_buttons_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
            
            select_all_button = ctk.CTkButton(
                metadata_buttons_frame,
                text="Select All",
                command=self._select_all_metadata,
                width=120
            )
            select_all_button.grid(row=0, column=0, padx=5, pady=5)
            
            deselect_all_button = ctk.CTkButton(
                metadata_buttons_frame,
                text="Deselect All",
                command=self._deselect_all_metadata,
                width=120
            )
            deselect_all_button.grid(row=0, column=1, padx=5, pady=5)
            
            # Selection count display
            self.metadata_selection_label = ctk.CTkLabel(
                metadata_selection_frame,
                text="",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            )
            self.metadata_selection_label.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="w")
            self._update_metadata_selection_display()
        else:
            # No metadata columns available
            no_metadata_label = ctk.CTkLabel(
                metadata_selection_frame,
                text="No additional metadata columns available. All columns are used for Compound ID or Chromatographic Data.",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            )
            no_metadata_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        
        # Validation message
        self.validation_label = ctk.CTkLabel(
            self.scrollable_frame,
            text="",
            font=ctk.CTkFont(size=11),
            wraplength=850,
            justify="left"
        )
        self.validation_label.grid(row=row, column=0, columnspan=2, padx=20, pady=10, sticky="w")
        row += 1
        
        # Buttons frame
        button_frame = ctk.CTkFrame(self.scrollable_frame)
        button_frame.grid(row=row, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        
        # Accept Configuration button (Phase 7 - replaces Continue)
        self.continue_button = ctk.CTkButton(
            button_frame,
            text="Accept Configuration",
            command=self._on_accept_configuration,
            state="disabled"
        )
        self.continue_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # Cancel button
        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            command=self.on_close,
            fg_color="gray"
        )
        cancel_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        
        # Update delimiter display
        self._update_delimiter_display()
        
        # Initial validation
        self._validate_selections()
    
    def _on_compound_id_selected(self, choice: str) -> None:
        """Handle Compound ID column selection."""
        if choice and choice in self.available_columns:
            self.selected_compound_id_column = choice
            logger.debug(f"Selected Compound ID column: {choice}")
            self._update_compound_display()
            # Update metadata columns list (exclude newly selected compound_id column)
            self._refresh_metadata_checkboxes()
            self._validate_selections()
        else:
            logger.warning(f"Invalid Compound ID column selection: {choice}")
    
    def _on_chromatographic_data_selected(self, choice: str) -> None:
        """Handle Chromatographic Data column selection."""
        if choice and choice in self.available_columns:
            self.selected_chromatographic_data_column = choice
            logger.debug(f"Selected Chromatographic Data column: {choice}")
            self._update_data_display()
            # Update metadata columns list (exclude newly selected chromatographic_data column)
            self._refresh_metadata_checkboxes()
            self._validate_selections()
        else:
            logger.warning(f"Invalid Chromatographic Data column selection: {choice}")
    
    def _update_compound_display(self) -> None:
        """Update Compound ID selection display."""
        if self.selected_compound_id_column:
            self.compound_selected_label.configure(
                text=f"Selected: {self.selected_compound_id_column}",
                text_color="green"
            )
        else:
            self.compound_selected_label.configure(
                text="No column selected",
                text_color="gray"
            )
    
    def _update_data_display(self) -> None:
        """Update Chromatographic Data selection display."""
        if self.selected_chromatographic_data_column:
            self.data_selected_label.configure(
                text=f"Selected: {self.selected_chromatographic_data_column}",
                text_color="green"
            )
        else:
            self.data_selected_label.configure(
                text="No column selected",
                text_color="gray"
            )
    
    def _add_delimiter(self, delimiter: str) -> None:
        """Add a delimiter to the sequence."""
        if delimiter:
            self.delimiters.append(delimiter)
            self._update_delimiter_display()
            self._validate_selections()
            logger.debug(f"Added delimiter: {repr(delimiter)}")
    
    def _add_custom_delimiter(self) -> None:
        """Add custom delimiter from input field."""
        custom_delimiter = self.custom_delimiter_entry.get().strip()
        if custom_delimiter:
            self._add_delimiter(custom_delimiter)
            self.custom_delimiter_entry.delete(0, "end")
        else:
            logger.warning("Attempted to add empty custom delimiter")
    
    def _remove_last_delimiter(self) -> None:
        """Remove the last delimiter from the sequence."""
        if self.delimiters:
            removed = self.delimiters.pop()
            self._update_delimiter_display()
            self._validate_selections()
            logger.debug(f"Removed delimiter: {repr(removed)}")
    
    def _clear_delimiters(self) -> None:
        """Clear all delimiters."""
        self.delimiters.clear()
        self._update_delimiter_display()
        self._validate_selections()
        logger.debug("Cleared all delimiters")
    
    def _update_delimiter_display(self) -> None:
        """Update the delimiter sequence display."""
        # Clear existing display
        for widget in self.delimiter_list_frame.winfo_children():
            widget.destroy()
        
        if not self.delimiters:
            self.delimiter_display_label = ctk.CTkLabel(
                self.delimiter_list_frame,
                text="No delimiters added",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            )
            self.delimiter_display_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        else:
            # Display delimiter sequence
            delimiter_text = " → ".join([repr(d) if d in ["\t", " "] else d for d in self.delimiters])
            self.delimiter_display_label = ctk.CTkLabel(
                self.delimiter_list_frame,
                text=f"Sequence: {delimiter_text}",
                font=ctk.CTkFont(size=11),
                text_color="green"
            )
            self.delimiter_display_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
    
    def _load_sample_data(self) -> None:
        """Load sample data from the chromatographic data column."""
        if not self.selected_chromatographic_data_column:
            self._show_error("Please select a Chromatographic Data column first.")
            return
        
        try:
            dataframe = self.loader.get_data()
            if dataframe is None or dataframe.empty:
                self._show_error("No data loaded in spreadsheet.")
                return
            
            # Get first non-null value from the selected column
            column_data = dataframe[self.selected_chromatographic_data_column]
            sample_value = None
            for value in column_data:
                if pd.notna(value) and str(value).strip():
                    sample_value = str(value).strip()
                    break
            
            if sample_value:
                self.test_data_entry.delete(0, "end")
                self.test_data_entry.insert(0, sample_value)
                logger.debug(f"Loaded sample data: {sample_value[:50]}...")
            else:
                self._show_error("No valid data found in the selected column.")
        except Exception as e:
            error_msg = f"Error loading sample data: {str(e)}"
            self._show_error(error_msg)
            logger.error(error_msg, exc_info=True)
    
    def _test_parse(self) -> None:
        """Test parsing with current delimiters and test data."""
        test_data = self.test_data_entry.get().strip()
        
        if not test_data:
            self.parse_status_label.configure(
                text="✗ Please enter test data",
                text_color="red"
            )
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", "No test data provided.")
            return
        
        if not self.delimiters:
            self.parse_status_label.configure(
                text="✗ Please add at least one delimiter",
                text_color="red"
            )
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", "No delimiters configured. Please add delimiters first.")
            return
        
        try:
            # Create parser with current delimiters
            parser = DataParser(self.delimiters.copy())
            
            # Parse the test data (returns flat list)
            parsed_items = parser.parse(test_data)
            
            # Store parsed items for Phase 7
            self.parsed_flat_items = parsed_items
            
            # Display results
            if parsed_items:
                # Format results for display
                result_text = f"Parsed {len(parsed_items)} items:\n\n"
                result_text += "Items:\n"
                
                # Show items in a readable format
                for i, item in enumerate(parsed_items[:50], 1):  # Limit to first 50
                    result_text += f"  {i}. {item}\n"
                
                if len(parsed_items) > 50:
                    result_text += f"\n... and {len(parsed_items) - 50} more items\n"
                
                result_text += "\n💡 Tip: Specify 'Items per Data Point' below to structure this data."
                
                self.preview_text.delete("1.0", "end")
                self.preview_text.insert("1.0", result_text)
                
                self.parse_status_label.configure(
                    text=f"✓ Successfully parsed {len(parsed_items)} items. Now specify items per point to structure.",
                    text_color="green"
                )
                
                logger.debug(f"Successfully parsed test data into {len(parsed_items)} items")
            else:
                self.preview_text.delete("1.0", "end")
                self.preview_text.insert("1.0", "Parsing returned no items.")
                self.parse_status_label.configure(
                    text="⚠ Parsing returned no items",
                    text_color="orange"
                )
                
        except Exception as e:
            error_msg = str(e)
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", f"Parsing Error:\n{error_msg}")
            self.parse_status_label.configure(
                text=f"✗ Parsing failed: {error_msg}",
                text_color="red"
            )
            logger.error(f"Parsing test failed: {error_msg}", exc_info=True)
    
    def _structure_parsed_data(self) -> None:
        """Structure parsed flat items into data points based on items_per_point."""
        if not hasattr(self, 'parsed_flat_items') or not self.parsed_flat_items:
            self._show_error("Please parse test data first.")
            return
        
        try:
            items_per_point_str = self.items_per_point_entry.get().strip()
            if not items_per_point_str:
                self._show_error("Please enter items per data point.")
                return
            
            items_per_point = int(items_per_point_str)
            if items_per_point < 1:
                self._show_error("Items per point must be at least 1.")
                return
            
            # Check if data divides evenly
            if len(self.parsed_flat_items) % items_per_point != 0:
                self._show_error(
                    f"Data has {len(self.parsed_flat_items)} items, which is not divisible by "
                    f"{items_per_point} items per point. Please check your delimiters or items per point."
                )
                return
            
            # Group into data points
            data_points = []
            for i in range(0, len(self.parsed_flat_items), items_per_point):
                data_point = self.parsed_flat_items[i:i + items_per_point]
                data_points.append(data_point)
            
            self.parsed_data_points = data_points
            self.items_per_point = items_per_point
            
            # Display structured data
            self._display_structured_data()
            
            # Update time and count selection UIs
            self._update_field_selection_ui()
            
            logger.debug(f"Structured data into {len(data_points)} data points with {items_per_point} items each")
            
        except ValueError:
            self._show_error("Items per point must be a valid integer.")
        except Exception as e:
            error_msg = f"Error structuring data: {str(e)}"
            self._show_error(error_msg)
            logger.error(error_msg, exc_info=True)
    
    def _display_structured_data(self) -> None:
        """Display structured data points."""
        if not self.parsed_data_points:
            self.structured_text.delete("1.0", "end")
            self.structured_text.insert("1.0", "No structured data. Parse test data and specify items per point.")
            return
        
        result_text = f"Structured into {len(self.parsed_data_points)} data points:\n\n"
        result_text += "Data Points (showing first 10):\n"
        result_text += "Index | " + " | ".join([f"Field {i}" for i in range(self.items_per_point)]) + "\n"
        result_text += "-" * (20 + self.items_per_point * 15) + "\n"
        
        for i, point in enumerate(self.parsed_data_points[:10], 0):
            result_text += f"  {i}   | " + " | ".join([str(item)[:10] for item in point]) + "\n"
        
        if len(self.parsed_data_points) > 10:
            result_text += f"\n... and {len(self.parsed_data_points) - 10} more data points\n"
        
        result_text += f"\nEach data point has {self.items_per_point} fields (indices 0-{self.items_per_point - 1})"
        
        self.structured_text.delete("1.0", "end")
        self.structured_text.insert("1.0", result_text)
    
    def _update_field_selection_ui(self) -> None:
        """Update time and count selection UIs based on structured data."""
        if not self.parsed_data_points or self.items_per_point is None:
            return
        
        # Update time index dropdown
        field_indices = [str(i) for i in range(self.items_per_point)]
        self.time_index_dropdown.configure(values=field_indices)
        if self.selected_time_index is not None and self.selected_time_index < self.items_per_point:
            self.time_index_var.set(str(self.selected_time_index))
        
        # Clear and recreate count checkboxes
        for widget in self.count_checkboxes_frame.winfo_children():
            widget.destroy()
        self.count_checkboxes.clear()
        
        # Create checkboxes for each field
        for i in range(self.items_per_point):
            checkbox = ctk.CTkCheckBox(
                self.count_checkboxes_frame,
                text=f"Field {i}",
                command=lambda idx=i: self._on_count_selection_changed(idx)
            )
            checkbox.grid(row=i, column=0, padx=10, pady=5, sticky="w")
            if i in self.selected_count_indices:
                checkbox.select()
            self.count_checkboxes[i] = checkbox
        
        # Update count names UI
        self._update_count_names_ui()
    
    def _on_time_index_selected(self, choice: str) -> None:
        """Handle time index selection."""
        try:
            self.selected_time_index = int(choice)
            logger.debug(f"Selected time index: {self.selected_time_index}")
            self._validate_selections()
        except (ValueError, TypeError):
            logger.warning(f"Invalid time index selection: {choice}")
    
    def _on_count_selection_changed(self, index: int) -> None:
        """Handle count checkbox selection change."""
        checkbox = self.count_checkboxes.get(index)
        if not checkbox:
            return
        
        if checkbox.get():
            if index not in self.selected_count_indices:
                self.selected_count_indices.append(index)
                # Ensure time and count are different
                if self.selected_time_index == index:
                    checkbox.deselect()
                    self._show_error("Time field and Count fields must be different.")
                    if index in self.selected_count_indices:
                        self.selected_count_indices.remove(index)
                    return
        else:
            if index in self.selected_count_indices:
                self.selected_count_indices.remove(index)
                # Remove associated count name
                if index in self.count_names:
                    idx = self.selected_count_indices.index(index) if index in self.selected_count_indices else None
                    # Actually, we need to track by index, not position
                    # Let's rebuild count_names based on selected_count_indices
                    self._update_count_names_ui()
        
        self._update_count_names_ui()
        self._validate_selections()
        logger.debug(f"Count selection changed. Selected indices: {self.selected_count_indices}")
    
    def _update_count_names_ui(self) -> None:
        """Update count names input fields based on selected count indices."""
        # Clear existing name entries
        for widget in self.count_names_frame.winfo_children():
            widget.destroy()
        self.count_name_entries.clear()
        
        if not self.selected_count_indices:
            label = ctk.CTkLabel(
                self.count_names_frame,
                text="No count fields selected",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            )
            label.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="w")
            return
        
        # Create label
        label = ctk.CTkLabel(
            self.count_names_frame,
            text="Enter names for each count field:",
            font=ctk.CTkFont(size=11)
        )
        label.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")
        
        # Create entry for each selected count
        for row_idx, count_idx in enumerate(sorted(self.selected_count_indices), 1):
            field_label = ctk.CTkLabel(
                self.count_names_frame,
                text=f"Field {count_idx}:",
                font=ctk.CTkFont(size=11)
            )
            field_label.grid(row=row_idx, column=0, padx=10, pady=5, sticky="w")
            
            # Get existing name if available
            existing_name = ""
            if self.count_names and len(self.count_names) == len(self.selected_count_indices):
                # Find name by matching the index position
                sorted_indices = sorted(self.selected_count_indices)
                if count_idx in sorted_indices:
                    pos = sorted_indices.index(count_idx)
                    if pos < len(self.count_names):
                        existing_name = self.count_names[pos]
            
            entry = ctk.CTkEntry(
                self.count_names_frame,
                placeholder_text=f"Name for field {count_idx}",
                width=200
            )
            if existing_name:
                entry.insert(0, existing_name)
            entry.grid(row=row_idx, column=1, padx=10, pady=5, sticky="ew")
            entry.bind("<KeyRelease>", lambda e, idx=count_idx: self._on_count_name_changed(idx))
            
            self.count_name_entries[count_idx] = entry
        
        self.count_names_frame.grid_columnconfigure(1, weight=1)
    
    def _on_count_name_changed(self, index: int) -> None:
        """Handle count name change."""
        entry = self.count_name_entries.get(index)
        if entry:
            # Will be collected in validation
            self._validate_selections()
    
    def _get_metadata_columns(self) -> List[str]:
        """
        Get list of metadata columns (all columns except compound_id and chromatographic_data).
        
        Returns:
            List of metadata column names
        """
        metadata_cols = []
        excluded = set()
        
        if self.selected_compound_id_column:
            excluded.add(self.selected_compound_id_column)
        if self.selected_chromatographic_data_column:
            excluded.add(self.selected_chromatographic_data_column)
        
        for col in self.available_columns:
            if col not in excluded:
                metadata_cols.append(col)
        
        return metadata_cols
    
    def _create_metadata_checkboxes(self) -> None:
        """Create checkboxes for metadata column selection."""
        # Clear existing checkboxes
        for widget in self.metadata_checkboxes_frame.winfo_children():
            widget.destroy()
        self.metadata_checkboxes.clear()
        
        # Create checkbox for each metadata column
        for i, col_name in enumerate(sorted(self.metadata_columns)):
            checkbox = ctk.CTkCheckBox(
                self.metadata_checkboxes_frame,
                text=col_name,
                command=lambda col=col_name: self._on_metadata_column_toggled(col)
            )
            checkbox.grid(row=i, column=0, padx=10, pady=5, sticky="w")
            
            # Check if this column was previously selected
            if col_name in self.selected_metadata_columns:
                checkbox.select()
            
            self.metadata_checkboxes[col_name] = checkbox
    
    def _on_metadata_column_toggled(self, column_name: str) -> None:
        """Handle metadata column checkbox toggle."""
        checkbox = self.metadata_checkboxes.get(column_name)
        if not checkbox:
            return
        
        if checkbox.get():
            if column_name not in self.selected_metadata_columns:
                self.selected_metadata_columns.append(column_name)
        else:
            if column_name in self.selected_metadata_columns:
                self.selected_metadata_columns.remove(column_name)
        
        self._update_metadata_selection_display()
        logger.debug(f"Metadata column selection changed. Selected: {self.selected_metadata_columns}")
    
    def _select_all_metadata(self) -> None:
        """Select all metadata columns."""
        for col_name, checkbox in self.metadata_checkboxes.items():
            if not checkbox.get():
                checkbox.select()
                if col_name not in self.selected_metadata_columns:
                    self.selected_metadata_columns.append(col_name)
        self._update_metadata_selection_display()
    
    def _deselect_all_metadata(self) -> None:
        """Deselect all metadata columns."""
        for col_name, checkbox in self.metadata_checkboxes.items():
            if checkbox.get():
                checkbox.deselect()
                if col_name in self.selected_metadata_columns:
                    self.selected_metadata_columns.remove(col_name)
        self._update_metadata_selection_display()
    
    def _update_metadata_selection_display(self) -> None:
        """Update metadata selection count display."""
        if not hasattr(self, 'metadata_selection_label') or not self.metadata_columns:
            return
        
        count = len(self.selected_metadata_columns)
        total = len(self.metadata_columns)
        
        if count == 0:
            self.metadata_selection_label.configure(
                text="No metadata columns selected (optional - you can still proceed)",
                text_color="orange"
            )
        else:
            self.metadata_selection_label.configure(
                text=f"Selected {count} of {total} metadata columns",
                text_color="green"
            )
    
    def _refresh_metadata_checkboxes(self) -> None:
        """Refresh metadata checkboxes when compound_id or chromatographic_data columns change."""
        if not hasattr(self, 'metadata_checkboxes_frame'):
            return
        
        # Store current selections
        current_selections = self.selected_metadata_columns.copy()
        
        # Update metadata columns list
        self.metadata_columns = self._get_metadata_columns()
        
        # Remove selections that are no longer valid
        self.selected_metadata_columns = [
            col for col in current_selections 
            if col in self.metadata_columns
        ]
        
        # Recreate checkboxes
        self._create_metadata_checkboxes()
        
        # Restore selections
        for col_name in self.selected_metadata_columns:
            checkbox = self.metadata_checkboxes.get(col_name)
            if checkbox:
                checkbox.select()
        
        self._update_metadata_selection_display()
    
    def _validate_selections(self) -> None:
        """
        Validate column selections and delimiter configuration.
        
        Returns:
            True if selections are valid, False otherwise
        """
        errors = []
        
        # Check Compound ID column
        if not self.selected_compound_id_column:
            errors.append("Please select a Compound ID column")
        elif self.selected_compound_id_column not in self.available_columns:
            errors.append(f"Selected Compound ID column '{self.selected_compound_id_column}' not found in spreadsheet")
        
        # Check Chromatographic Data column
        if not self.selected_chromatographic_data_column:
            errors.append("Please select a Chromatographic Data column")
        elif self.selected_chromatographic_data_column not in self.available_columns:
            errors.append(f"Selected Chromatographic Data column '{self.selected_chromatographic_data_column}' not found in spreadsheet")
        
        # Check that columns are different
        if (self.selected_compound_id_column and 
            self.selected_chromatographic_data_column and
            self.selected_compound_id_column == self.selected_chromatographic_data_column):
            errors.append("Compound ID and Chromatographic Data columns must be different")
        
        # Check delimiters (Phase 6)
        if not self.delimiters:
            errors.append("Please add at least one delimiter")
        
            # Phase 7: Time & Count validation
        if self.parsed_data_points:
            # Data is structured, so validate time and count selections
            if self.selected_time_index is None:
                errors.append("Please select a Time field index")
            elif self.items_per_point and self.selected_time_index >= self.items_per_point:
                errors.append(f"Time index {self.selected_time_index} is out of range (0-{self.items_per_point - 1})")
            else:
                # Validate Time field contains numeric values
                if self.selected_time_index is not None:
                    time_values = [point[self.selected_time_index] for point in self.parsed_data_points[:10]]
                    non_numeric = [v for v in time_values if DataParser.try_parse_numeric(v) is None]
                    if non_numeric:
                        errors.append(f"Time field contains non-numeric values: {non_numeric[0]}")
            
            if not self.selected_count_indices:
                errors.append("Please select at least one Count field")
            else:
                # Validate count indices are in range
                for count_idx in self.selected_count_indices:
                    if self.items_per_point and count_idx >= self.items_per_point:
                        errors.append(f"Count index {count_idx} is out of range (0-{self.items_per_point - 1})")
                
                # Validate time and count are different
                if self.selected_time_index is not None and self.selected_time_index in self.selected_count_indices:
                    errors.append("Time field and Count fields must be different")
                
                # Collect count names and validate (in sorted order of indices)
                count_names = []
                for count_idx in sorted(self.selected_count_indices):
                    entry = self.count_name_entries.get(count_idx)
                    if entry:
                        name = entry.get().strip()
                        if not name:
                            errors.append(f"Please enter a name for count field {count_idx}")
                        else:
                            count_names.append(name)
                    else:
                        errors.append(f"Missing name entry for count field {count_idx}")
                
                # Check for duplicate names
                if count_names and len(count_names) != len(set(count_names)):
                    errors.append("Count names must be unique")
                
                # Only update if no errors (to preserve partial input)
                if not errors:
                    self.count_names = count_names
        
        # Update validation message
        if errors:
            error_text = "Validation errors:\n" + "\n".join(f"• {error}" for error in errors)
            self.validation_label.configure(text=error_text, text_color="red")
            self.continue_button.configure(state="disabled")
            return False
        else:
            if self.parsed_data_points and self.selected_time_index is not None and self.selected_count_indices:
                self.validation_label.configure(
                    text="✓ Configuration is complete and valid. Click 'Accept Configuration' to save.",
                    text_color="green"
                )
            else:
                self.validation_label.configure(
                    text="✓ Basic configuration is valid. Complete time and count selection to finalize.",
                    text_color="green"
                )
            self.continue_button.configure(state="normal")
            return True
    
    def _on_accept_configuration(self) -> None:
        """Handle Accept Configuration button click (Phase 7 - final step)."""
        if not self._validate_selections():
            logger.warning("Attempted to accept configuration with invalid selections")
            return
        
        # Phase 7: Require time and count selections if data is structured
        if self.parsed_data_points:
            if self.selected_time_index is None:
                self._show_error("Please select a Time field index.")
                return
            if not self.selected_count_indices:
                self._show_error("Please select at least one Count field.")
                return
            if not self.count_names or len(self.count_names) != len(self.selected_count_indices):
                self._show_error("Please enter names for all selected count fields.")
                return
        
        try:
            # Create complete configuration
            config = SpreadsheetConfig(
                compound_id_column=self.selected_compound_id_column,
                chromatographic_data_column=self.selected_chromatographic_data_column,
                delimiters=self.delimiters.copy(),
                time_column_index=self.selected_time_index,
                count_column_indices=self.selected_count_indices.copy(),
                count_names=self.count_names.copy(),
                selected_metadata_columns=self.selected_metadata_columns.copy()
            )
            
            # Validate complete configuration
            try:
                config.__post_init__()
                is_valid, error_message = self.config_manager.validate_config(config)
                if not is_valid:
                    self.validation_label.configure(
                        text=f"✗ Configuration error: {error_message}",
                        text_color="red"
                    )
                    logger.error(f"Configuration validation failed: {error_message}")
                    return
            except ValueError as e:
                self.validation_label.configure(
                    text=f"✗ Configuration error: {str(e)}",
                    text_color="red"
                )
                logger.error(f"Configuration validation failed: {str(e)}")
                return
            
            logger.info(f"Complete configuration created: Compound ID={self.selected_compound_id_column}, "
                       f"Chromatographic Data={self.selected_chromatographic_data_column}, "
                       f"Delimiters={self.delimiters}, Time={self.selected_time_index}, "
                       f"Counts={self.selected_count_indices}, Names={self.count_names}")
            
            # Call success callback
            if self.on_success:
                self.on_success(config)
            
            # Close dialog
            self.on_close()
            
        except Exception as e:
            error_text = f"Error creating configuration: {str(e)}"
            self.validation_label.configure(text=f"✗ {error_text}", text_color="red")
            logger.error(error_text, exc_info=True)
    
    def _show_error(self, message: str) -> None:
        """Show error message in a messagebox."""
        from tkinter import messagebox
        messagebox.showerror("Error", message)
    
    def _on_load_saved_config(self, choice: str) -> None:
        """Handle saved config dropdown selection."""
        logger.debug(f"Selected config: {choice}")
    
    def _load_selected_config(self) -> None:
        """Load the selected saved configuration."""
        selected = self.config_dropdown_var.get()
        if not selected or selected == "Default":
            # Load default config
            config = self.config_manager.load_default_config()
        else:
            # Load named config
            config = self.config_manager.load_named_config(selected)
        
        if not config:
            self._show_error("No configuration found to load.")
            return
        
        # Validate config against current spreadsheet
        is_valid, error_msg = self.config_manager.validate_config_against_spreadsheet(
            config, self.available_columns
        )
        
        if not is_valid:
            self._show_error(f"Cannot load configuration: {error_msg}")
            return
        
        # Load configuration into UI
        self.selected_compound_id_column = config.compound_id_column
        self.selected_chromatographic_data_column = config.chromatographic_data_column
        self.delimiters = config.delimiters.copy() if config.delimiters else []
        self.selected_time_index = config.time_column_index
        self.selected_count_indices = config.count_column_indices.copy() if config.count_column_indices else []
        self.count_names = config.count_names.copy() if config.count_names else []
        self.selected_metadata_columns = config.selected_metadata_columns.copy() if config.selected_metadata_columns else []
        
        # Update UI
        if self.selected_compound_id_column:
            self.compound_var.set(self.selected_compound_id_column)
        if self.selected_chromatographic_data_column:
            self.data_var.set(self.selected_chromatographic_data_column)
        
        self._update_compound_display()
        self._update_data_display()
        self._update_delimiter_display()
        
        # Update metadata checkboxes
        if hasattr(self, 'metadata_checkboxes_frame'):
            self._refresh_metadata_checkboxes()
        
        # Update Phase 7 UI if we have structured data
        if self.items_per_point:
            self._update_field_selection_ui()
        
        self._validate_selections()
        
        logger.info(f"Loaded configuration: {selected}")
    
    def _save_config_as(self) -> None:
        """Save current configuration with a custom name."""
        from tkinter import simpledialog
        
        # Get name from user
        name = simpledialog.askstring(
            "Save Configuration",
            "Enter a name for this configuration:",
            initialvalue=""
        )
        
        if not name or not name.strip():
            return
        
        # Validate current configuration
        if not self._validate_selections():
            self._show_error("Cannot save: Configuration is incomplete or invalid.")
            return
        
        # Create config object
        try:
            config = SpreadsheetConfig(
                compound_id_column=self.selected_compound_id_column,
                chromatographic_data_column=self.selected_chromatographic_data_column,
                delimiters=self.delimiters.copy(),
                time_column_index=self.selected_time_index,
                count_column_indices=self.selected_count_indices.copy(),
                count_names=self.count_names.copy()
            )
            
            # Save named config
            success = self.config_manager.save_named_config(config, name.strip())
            
            if success:
                from tkinter import messagebox
                messagebox.showinfo("Success", f"Configuration saved as '{name}'")
                
                # Refresh dropdown
                saved_configs = self.config_manager.list_named_configs()
                config_names = [config["name"] for config in saved_configs]
                self.config_dropdown.configure(values=["Default"] + config_names)
                self.config_dropdown_var.set(name.strip())
                
                logger.info(f"Saved configuration as '{name}'")
            else:
                self._show_error("Failed to save configuration.")
                
        except Exception as e:
            error_msg = f"Error saving configuration: {str(e)}"
            self._show_error(error_msg)
            logger.error(error_msg, exc_info=True)