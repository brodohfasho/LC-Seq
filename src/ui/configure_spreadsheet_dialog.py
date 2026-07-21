# src/ui/configure_spreadsheet_dialog.py
"""
Dialog for configuring spreadsheet parsing settings.
"""

import customtkinter as ctk
import logging
import random
import threading
import pandas as pd
from typing import Callable, Dict, List, Optional, Tuple

from src.ui.base_window import BaseWindow
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.core.bb_index_csv import (
    detect_building_blocks_from_dataframe,
    format_validation_report,
    parse_bb_index_file,
    validate_bb_index_map,
)
from src.core.config_manager import ConfigManager
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.ui_messages import (
    show_bb_index_parse_errors,
    show_bb_index_validation_result,
    show_error,
    show_info,
)
from src.utils.data_parser import DataParser

logger = logging.getLogger(__name__)

_WIZARD_DIALOG_WIDTH = 1180
_WIZARD_DIALOG_HEIGHT = 820
_WIZARD_TEXT_WRAP = 1100


class ConfigureSpreadsheetDialog(BaseWindow):
    """
    Dialog window for configuring spreadsheet parsing (tabbed step workflow).
    
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
        on_success: Optional[Callable[[SpreadsheetConfig], None]] = None,
        on_default_preset_applied: Optional[Callable[[SpreadsheetConfig], None]] = None,
    ):
        """
        Initialize configure spreadsheet dialog.
        
        Args:
            parent: Parent window
            loader: SpreadsheetLoader instance with loaded data
            config_manager: ConfigManager instance
            on_success: Callback function called with SpreadsheetConfig on successful configuration
            on_default_preset_applied: Called when the user loads the Default preset successfully,
                before this dialog closes (used to sync main window application state).
        """
        super().__init__(parent, title="Configure Spreadsheet")
        
        self.loader = loader
        self.config_manager = config_manager
        self.on_success = on_success
        self.on_default_preset_applied = on_default_preset_applied
        
        self.geometry(f"{_WIZARD_DIALOG_WIDTH}x{_WIZARD_DIALOG_HEIGHT}")
        self.center_window(_WIZARD_DIALOG_WIDTH, _WIZARD_DIALOG_HEIGHT)
        self.resizable(True, True)
        self.minsize(860, 580)
        self._sample_loading = False
        self._sample_worker_thread: Optional[threading.Thread] = None
        
        # Column selections
        self.selected_compound_id_column: Optional[str] = None
        self.selected_chromatographic_data_column: Optional[str] = None
        self.selected_variant_column: Optional[str] = None
        self._columns_sample_confirmed: bool = False
        self._column_pair_sample_text: str = ""
        self._sample_chrom_strings: List[str] = []
        self._delimiter_parse_confirmed: bool = False
        self._data_assignments_confirmed: bool = False
        
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

        # DEL / pedigree (tab 5)
        self.library_cycle_count: int = 3
        self.null_token: str = "AgxNull"
        self.analysis_time_unit: str = "seconds"
        self.bb_position_columns: List[str] = ["", "", "", ""]
        self.bb_index_map: Dict[str, int] = {}
        self.bb_index_csv_path: Optional[str] = None
        self.bb_index_validated: bool = False
        self._bb_column_menus: List[ctk.CTkOptionMenu] = []
        self._bb_column_labels: List[ctk.CTkLabel] = []
        
        # Get available columns
        self.available_columns: List[str] = self.loader.get_column_names()
        
        if not self.available_columns:
            logger.error("No columns available in loaded spreadsheet")
            self._show_error("No columns found in loaded spreadsheet. Please load a valid spreadsheet first.")
            self.after(100, self.on_close)
            return
        
        # Load existing configuration if available
        self._load_existing_config()
        
        self._create_widgets()
        
        logger.info("Configure spreadsheet dialog initialized")

    @staticmethod
    def _wizard_section_font() -> ctk.CTkFont:
        return ctk.CTkFont(size=13, weight="bold")

    @staticmethod
    def _wizard_hint_font() -> ctk.CTkFont:
        return ctk.CTkFont(size=11)

    @staticmethod
    def _wizard_mono_font() -> ctk.CTkFont:
        return ctk.CTkFont(family="Consolas", size=11)
    
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
                    self.library_cycle_count = int(
                        getattr(existing_config, "library_cycle_count", 3) or 3
                    )
                    self.null_token = str(getattr(existing_config, "null_token", "AgxNull"))
                    self.analysis_time_unit = str(
                        getattr(existing_config, "analysis_time_unit", "seconds")
                    )
                    bb = getattr(existing_config, "bb_position_columns", None)
                    if bb and len(bb) >= 4:
                        self.bb_position_columns = [str(c or "") for c in bb[:4]]
                    elif bb:
                        self.bb_position_columns = [str(c or "") for c in bb] + [""] * (
                            4 - len(bb)
                        )
                    saved_index = getattr(existing_config, "bb_index_map", None) or {}
                    if saved_index:
                        self.bb_index_map = {str(k): int(v) for k, v in saved_index.items()}
                        raw_path = getattr(existing_config, "bb_index_csv_path", None)
                        self.bb_index_csv_path = str(raw_path).strip() if raw_path else None
                        self.bb_index_validated = True
                    vcol = getattr(existing_config, "compound_variant_column", None)
                    if vcol and str(vcol).strip() and str(vcol) in self.available_columns:
                        self.selected_variant_column = str(vcol).strip()
                    logger.debug("Loaded and validated existing configuration")
                else:
                    logger.warning(f"Existing configuration is not valid for current spreadsheet: {error_msg}")
        except Exception as e:
            logger.warning(f"Could not load existing configuration: {e}")
    
    def _create_widgets(self) -> None:
        """Build tabbed configuration UI (one step per tab)."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.wizard_hint = ctk.CTkLabel(
            self,
            text=(
                "Work through each step in order. Next / Back and the tab bar use the same rules: "
                "you cannot open a later tab until the current step passes validation (same as Next). "
                "Presets are under Load preset / Save preset."
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
        )
        self.wizard_hint.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")
        self.tabview = ctk.CTkTabview(
            self, height=560, command=self._on_wizard_tabview_changed
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        self._tab_labels = [
            "1 — Columns",
            "2 — Delimiters & parse",
            "3 — Time & counts",
            "4 — Metadata",
            "5 — DEL / Pedigree",
        ]
        tab__populate_tab_columns = self.tabview.add("1 — Columns")
        tab__populate_tab_columns.grid_columnconfigure(0, weight=1)
        self._populate_tab_columns(tab__populate_tab_columns)
        tab__populate_tab_delimiters = self.tabview.add("2 — Delimiters & parse")
        tab__populate_tab_delimiters.grid_columnconfigure(0, weight=1)
        self._populate_tab_delimiters_and_parse(tab__populate_tab_delimiters)
        tab__populate_tab_time_count = self.tabview.add("3 — Time & counts")
        tab__populate_tab_time_count.grid_columnconfigure(0, weight=1)
        self._populate_tab_time_count(tab__populate_tab_time_count)
        tab__populate_tab_metadata = self.tabview.add("4 — Metadata")
        tab__populate_tab_metadata.grid_columnconfigure(0, weight=1)
        self._populate_tab_metadata(tab__populate_tab_metadata)
        tab_pedigree = self.tabview.add("5 — DEL / Pedigree")
        tab_pedigree.grid_columnconfigure(0, weight=1)
        self._populate_tab_pedigree(tab_pedigree)
        self.validation_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
        )
        self.validation_label.grid(row=2, column=0, padx=16, pady=(6, 4), sticky="ew")
        self.nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.nav_frame.grid(row=3, column=0, padx=12, pady=(4, 12), sticky="ew")
        self.nav_frame.grid_columnconfigure(2, weight=1)
        self.back_tab_btn = ctk.CTkButton(
            self.nav_frame, text="Back", width=90, command=self._wizard_tab_back
        )
        self.back_tab_btn.grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.next_tab_btn = ctk.CTkButton(
            self.nav_frame, text="Next", width=90, command=self._wizard_tab_next
        )
        self.next_tab_btn.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.accept_button = ctk.CTkButton(
            self.nav_frame,
            text="Accept configuration",
            width=180,
            command=self._on_accept_configuration,
            state="disabled",
        )
        self.accept_button.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.accept_button.grid_remove()
        self.load_preset_button = ctk.CTkButton(
            self.nav_frame,
            text="Load preset",
            width=110,
            command=self._show_load_preset_dialog,
        )
        self.load_preset_button.grid(row=0, column=3, padx=(16, 4), pady=4, sticky="e")
        self.save_preset_button = ctk.CTkButton(
            self.nav_frame,
            text="Save preset",
            width=100,
            command=self._save_preset,
        )
        self.save_preset_button.grid(row=0, column=4, padx=4, pady=4, sticky="e")
        self.cancel_button = ctk.CTkButton(
            self.nav_frame,
            text="Cancel",
            command=self.on_close,
            fg_color="gray40",
            hover_color="gray25",
            width=100,
        )
        self.cancel_button.grid(row=0, column=5, padx=4, pady=4, sticky="e")
        self._tab_names = list(self._tab_labels)
        self._wizard_tab_last_committed = self.tabview.get()
        self._wizard_tab_revert_in_progress = False
        self._apply_delimiter_entries_from_list(self.delimiters)
        self._validate_selections()

    def _wizard_button_theme(self) -> Tuple[dict, dict]:
        theme = ctk.ThemeManager.theme["CTkButton"]
        normal = {
            "font": ctk.CTkFont(size=13),
            "fg_color": theme["fg_color"],
            "hover_color": theme["hover_color"],
        }
        emphasis = {
            "font": ctk.CTkFont(size=13, weight="bold"),
            "fg_color": "#B45309",
            "hover_color": "#92400E",
        }
        return normal, emphasis

    def _set_wizard_button_emphasis(self, button: Optional[ctk.CTkButton], emphasized: bool) -> None:
        if button is None or not button.winfo_exists():
            return
        normal, emphasis = self._wizard_button_theme()
        button.configure(**(emphasis if emphasized else normal))

    def _columns_selection_ready(self) -> bool:
        return bool(
            self.selected_compound_id_column
            and self.selected_chromatographic_data_column
            and self.selected_compound_id_column != self.selected_chromatographic_data_column
            and self.selected_compound_id_column in self.available_columns
            and self.selected_chromatographic_data_column in self.available_columns
        )

    def _update_wizard_action_highlights(self) -> None:
        """Draw attention to the validation action or Next/Accept for the active step."""
        if not hasattr(self, "next_tab_btn"):
            return

        for button in (
            getattr(self, "show_column_sample_button", None),
            getattr(self, "test_parse_button", None),
            getattr(self, "test_assignments_button", None),
            getattr(self, "validate_bb_index_button", None),
            self.next_tab_btn,
            getattr(self, "accept_button", None),
        ):
            self._set_wizard_button_emphasis(button, False)

        tab_i = self._wizard_tab_index()
        if tab_i == 0:
            if self._columns_selection_ready() and not self._columns_sample_confirmed:
                self._set_wizard_button_emphasis(self.show_column_sample_button, True)
            elif self._columns_sample_confirmed:
                self._set_wizard_button_emphasis(self.next_tab_btn, True)
        elif tab_i == 1:
            if not self._delimiter_parse_confirmed:
                self._set_wizard_button_emphasis(self.test_parse_button, True)
            else:
                self._set_wizard_button_emphasis(self.next_tab_btn, True)
        elif tab_i == 2:
            if not self._data_assignments_confirmed:
                self._set_wizard_button_emphasis(self.test_assignments_button, True)
            else:
                self._set_wizard_button_emphasis(self.next_tab_btn, True)
        elif tab_i == 3:
            self._set_wizard_button_emphasis(self.next_tab_btn, True)
        elif tab_i == 4:
            if self.bb_index_map and not self.bb_index_validated:
                self._set_wizard_button_emphasis(self.validate_bb_index_button, True)
            if str(self.accept_button.cget("state")) == "normal":
                self._set_wizard_button_emphasis(self.accept_button, True)

        self._update_wizard_nav_buttons()

    def _update_wizard_nav_buttons(self) -> None:
        """On the last tab, swap Next for Accept configuration in the nav bar."""
        if not hasattr(self, "next_tab_btn") or not hasattr(self, "accept_button"):
            return
        on_last_tab = self._wizard_tab_index() == len(self._tab_names) - 1
        if on_last_tab:
            self.next_tab_btn.grid_remove()
            self.accept_button.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        else:
            self.accept_button.grid_remove()
            self.next_tab_btn.grid(row=0, column=1, padx=4, pady=4, sticky="w")

    def _populate_tab_columns(self, parent: ctk.CTkFrame) -> None:
        """Step 1: column mapping panel + sample preview panel."""
        parent.grid_columnconfigure(0, weight=0, minsize=420)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        instructions = ctk.CTkLabel(
            parent,
            text="Step 1: Map spreadsheet columns to compound identity and chromatographic data.",
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
            anchor="w",
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 8), sticky="ew")

        mapping_col = ctk.CTkFrame(parent)
        mapping_col.grid(row=1, column=0, padx=(16, 6), pady=(0, 12), sticky="nsew")
        mapping_col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            mapping_col,
            text="1. Column mapping",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            mapping_col,
            text=(
                "Required columns must differ. Variant is optional for multi-version compounds "
                "(e.g. linear vs cyclized)."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=380,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        fields = ctk.CTkFrame(mapping_col, fg_color="transparent")
        fields.grid(row=2, column=0, padx=8, pady=(0, 12), sticky="ew")
        fields.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(fields, text="Compound ID:", font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, padx=8, pady=(8, 4), sticky="w"
        )
        self.compound_var = ctk.StringVar()
        if self.selected_compound_id_column:
            self.compound_var.set(self.selected_compound_id_column)
        self.compound_dropdown = ctk.CTkComboBox(
            fields,
            variable=self.compound_var,
            values=self.available_columns,
            command=self._on_compound_id_selected,
            state="readonly",
        )
        self.compound_dropdown.grid(row=0, column=1, padx=8, pady=(8, 2), sticky="ew")
        self.compound_selected_label = ctk.CTkLabel(
            fields, text="", font=self._wizard_hint_font(), text_color="gray"
        )
        self.compound_selected_label.grid(
            row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w"
        )
        self._update_compound_display()

        ctk.CTkLabel(fields, text="Chromatographic data:", font=ctk.CTkFont(size=12)).grid(
            row=2, column=0, padx=8, pady=(4, 4), sticky="w"
        )
        self.data_var = ctk.StringVar()
        if self.selected_chromatographic_data_column:
            self.data_var.set(self.selected_chromatographic_data_column)
        self.data_dropdown = ctk.CTkComboBox(
            fields,
            variable=self.data_var,
            values=self.available_columns,
            command=self._on_chromatographic_data_selected,
            state="readonly",
        )
        self.data_dropdown.grid(row=2, column=1, padx=8, pady=(4, 2), sticky="ew")
        self.data_selected_label = ctk.CTkLabel(
            fields, text="", font=self._wizard_hint_font(), text_color="gray"
        )
        self.data_selected_label.grid(
            row=3, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w"
        )
        self._update_data_display()

        ctk.CTkLabel(fields, text="Variant (optional):", font=ctk.CTkFont(size=12)).grid(
            row=4, column=0, padx=8, pady=(4, 4), sticky="w"
        )
        self.variant_var = ctk.StringVar(value="(none)")
        self.variant_dropdown = ctk.CTkComboBox(
            fields,
            variable=self.variant_var,
            values=["(none)"] + self.available_columns,
            command=self._on_variant_column_selected,
            state="readonly",
        )
        self.variant_dropdown.grid(row=4, column=1, padx=8, pady=(4, 2), sticky="ew")
        if self.selected_variant_column:
            self.variant_var.set(self.selected_variant_column)
        ctk.CTkLabel(
            fields,
            text=(
                "Labels compound versions (e.g. linear vs cyclized). Each row needs a value when set."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=380,
            justify="left",
            anchor="w",
        ).grid(row=5, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")

        preview_col = ctk.CTkFrame(parent)
        preview_col.grid(row=1, column=1, padx=(6, 16), pady=(0, 12), sticky="nsew")
        preview_col.grid_columnconfigure(0, weight=1)
        preview_col.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            preview_col,
            text="2. Sample preview",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            preview_col,
            text="Random rows showing paired compound ID and chromatographic text from the same row.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=520,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        action_row = ctk.CTkFrame(preview_col, fg_color="transparent")
        action_row.grid(row=2, column=0, padx=8, pady=(0, 6), sticky="ew")
        action_row.grid_columnconfigure(1, weight=1)

        self.show_column_sample_button = ctk.CTkButton(
            action_row,
            text="Show sample data",
            command=self._on_show_column_samples,
            width=160,
        )
        self.show_column_sample_button.grid(row=0, column=0, padx=(4, 8), pady=4, sticky="w")
        self.column_sample_status = ctk.CTkLabel(
            action_row,
            text="",
            font=self._wizard_hint_font(),
            text_color="gray",
            anchor="w",
            justify="left",
        )
        self.column_sample_status.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        self.column_sample_text = ctk.CTkTextbox(
            preview_col,
            wrap="word",
            activate_scrollbars=True,
            font=self._wizard_mono_font(),
        )
        self.column_sample_text.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.column_sample_text.configure(state="disabled")

    def _populate_tab_delimiters_and_parse(self, parent: ctk.CTkFrame) -> None:
        """Step 2: three-column layout — delimiters | raw sample | parsed preview."""
        parent.grid_columnconfigure(0, weight=0, minsize=272)
        parent.grid_columnconfigure(1, weight=1, uniform="delimiter_step")
        parent.grid_columnconfigure(2, weight=1, uniform="delimiter_step")
        parent.grid_rowconfigure(1, weight=1)

        instructions = ctk.CTkLabel(
            parent,
            text=(
                "Step 2: Enter delimiters that separate time and count values in your chromatographic "
                "data, then test parsing against the sample from step 1. Leave extra delimiter fields blank."
            ),
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
            anchor="w",
        )
        instructions.grid(row=0, column=0, columnspan=3, padx=16, pady=(12, 8), sticky="ew")

        delim_col = ctk.CTkFrame(parent)
        delim_col.grid(row=1, column=0, padx=(16, 6), pady=(0, 12), sticky="nsew")
        delim_col.grid_columnconfigure(0, weight=1)
        delim_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            delim_col,
            text="1. Delimiters",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            delim_col,
            text=(
                "Order matters — each delimiter adds one field per data point. "
                "Leave extra delimiter fields blank."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=240,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.delimiter_fields_frame = ctk.CTkFrame(delim_col, fg_color="transparent")
        self.delimiter_fields_frame.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="new")
        self.delimiter_fields_frame.grid_columnconfigure(1, weight=1)

        self.delimiter_entry_widgets: List[ctk.CTkEntry] = []
        for i in range(3):
            lbl = ctk.CTkLabel(self.delimiter_fields_frame, text=f"Delimiter {i + 1}:")
            lbl.grid(row=i, column=0, padx=4, pady=6, sticky="w")
            ent = ctk.CTkEntry(
                self.delimiter_fields_frame,
                placeholder_text="(blank to skip)",
            )
            ent.grid(row=i, column=1, padx=4, pady=6, sticky="ew")
            ent.bind("<KeyRelease>", lambda _e: self._on_delimiter_field_edited())
            self.delimiter_entry_widgets.append(ent)

        self.test_parse_button = ctk.CTkButton(
            delim_col,
            text="Test parse",
            command=self._on_test_parse_click,
            width=160,
        )
        self.test_parse_button.grid(row=3, column=0, padx=12, pady=(4, 12), sticky="w")

        sample_col = ctk.CTkFrame(parent)
        sample_col.grid(row=1, column=1, padx=6, pady=(0, 12), sticky="nsew")
        sample_col.grid_columnconfigure(0, weight=1)
        sample_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            sample_col,
            text="2. Sample data",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            sample_col,
            text="Raw chromatographic text from step 1 — parsing uses the first non-empty sample row.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=320,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.delimiter_step_reference_text = ctk.CTkTextbox(
            sample_col,
            wrap="word",
            activate_scrollbars=True,
            font=self._wizard_mono_font(),
        )
        self.delimiter_step_reference_text.grid(
            row=2, column=0, padx=12, pady=(0, 12), sticky="nsew"
        )
        self.delimiter_step_reference_text.insert(
            "1.0",
            "Complete step 1 and click Show sample data.",
        )
        self.delimiter_step_reference_text.configure(state="disabled")

        parse_col = ctk.CTkFrame(parent)
        parse_col.grid(row=1, column=2, padx=(6, 16), pady=(0, 12), sticky="nsew")
        parse_col.grid_columnconfigure(0, weight=1)
        parse_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            parse_col,
            text="3. Parsed preview",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            parse_col,
            text="Structured fields after test parse — verify columns align with time and counts.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=320,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.preview_text = ctk.CTkTextbox(
            parse_col,
            wrap="none",
            activate_scrollbars=True,
            font=self._wizard_mono_font(),
        )
        self.preview_text.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="nsew")
        self.preview_text.insert("1.0", "Enter delimiters and click Test parse.")

        self.parse_status_label = ctk.CTkLabel(
            parse_col,
            text="",
            font=ctk.CTkFont(size=11),
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.parse_status_label.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")

    def _populate_tab_time_count(self, parent: ctk.CTkFrame) -> None:
        """Step 3: structured preview panel + field assignment panel."""
        parent.grid_columnconfigure(0, weight=3, uniform="time_count_step")
        parent.grid_columnconfigure(1, weight=2, uniform="time_count_step")
        parent.grid_rowconfigure(1, weight=1)

        instructions = ctk.CTkLabel(
            parent,
            text=(
                "Step 3: Assign which parsed field is time and which are counts, name each count "
                "channel, then test assignments against the structured preview."
            ),
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
            anchor="w",
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 8), sticky="ew")

        preview_col = ctk.CTkFrame(parent)
        preview_col.grid(row=1, column=0, padx=(16, 6), pady=(0, 12), sticky="nsew")
        preview_col.grid_columnconfigure(0, weight=1)
        preview_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            preview_col,
            text="1. Structured preview",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            preview_col,
            text="Parsed data points from step 2 — confirm field indices before assigning time and counts.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=420,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.structured_text = ctk.CTkTextbox(
            preview_col,
            wrap="none",
            activate_scrollbars=True,
            font=self._wizard_mono_font(),
        )
        self.structured_text.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.structured_text.insert(
            "1.0",
            "Complete step 2 (Test parse) to populate structured points here.",
        )

        assign_col = ctk.CTkFrame(parent)
        assign_col.grid(row=1, column=1, padx=(6, 16), pady=(0, 12), sticky="nsew")
        assign_col.grid_columnconfigure(0, weight=1)
        assign_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            assign_col,
            text="2. Field assignments",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            assign_col,
            text="Time and counts must use different field indices. Count names appear in plots and exports.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=340,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        assign_body = ctk.CTkFrame(assign_col, fg_color="transparent")
        assign_body.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="new")
        assign_body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            assign_body,
            text="Time field",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=4, pady=(0, 4), sticky="w")
        self.time_index_var = ctk.StringVar()
        self.time_index_dropdown = ctk.CTkComboBox(
            assign_body,
            variable=self.time_index_var,
            values=[],
            command=self._on_time_index_selected,
            state="readonly",
        )
        self.time_index_dropdown.grid(row=1, column=0, padx=4, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(
            assign_body,
            text="Count fields",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=2, column=0, padx=4, pady=(0, 4), sticky="w")
        self.count_checkboxes_frame = ctk.CTkFrame(assign_body, fg_color="transparent")
        self.count_checkboxes_frame.grid(row=3, column=0, padx=4, pady=(0, 10), sticky="ew")
        self.count_checkboxes_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            assign_body,
            text="Count names",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=4, column=0, padx=4, pady=(0, 4), sticky="w")
        self.count_names_frame = ctk.CTkFrame(assign_body, fg_color="transparent")
        self.count_names_frame.grid(row=5, column=0, padx=4, pady=(0, 4), sticky="ew")
        self.count_names_frame.grid_columnconfigure(1, weight=1)

        self.test_assignments_button = ctk.CTkButton(
            assign_col,
            text="Test data assignments",
            width=200,
            command=self._on_test_data_assignments_click,
        )
        self.test_assignments_button.grid(row=3, column=0, padx=12, pady=(8, 12), sticky="w")

    def _populate_tab_metadata(self, parent: ctk.CTkFrame) -> None:
        """Step 4: guidance panel + scrollable metadata column picker."""
        parent.grid_columnconfigure(0, weight=0, minsize=320)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        instructions = ctk.CTkLabel(
            parent,
            text=(
                "Step 4: Choose metadata columns to store in the searchable database. "
                "Optional, but recommended for filtering in the visualizer."
            ),
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
            anchor="w",
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 8), sticky="ew")

        guide_col = ctk.CTkFrame(parent)
        guide_col.grid(row=1, column=0, padx=(16, 6), pady=(0, 12), sticky="nsew")
        guide_col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            guide_col,
            text="1. What to include",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            guide_col,
            text=(
                "Include columns you will search or filter on in the chromatogram visualizer. "
                "Fewer columns keeps the database smaller and searches faster."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=280,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(
            guide_col,
            text=(
                "Split-tree visualization can read retention-time and null-verification metadata "
                "from selected columns to build the tree — include those columns if you plan to "
                "use that feature."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=280,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        ctk.CTkLabel(
            guide_col,
            text=(
                "Compound ID, chromatographic data, and variant columns are excluded automatically. "
                "You can leave everything unchecked and continue — metadata can be added later "
                "by reconfiguring."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=280,
            justify="left",
            anchor="w",
        ).grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")

        self.metadata_selection_label = ctk.CTkLabel(
            guide_col,
            text="",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=280,
            justify="left",
            anchor="w",
        )
        self.metadata_selection_label.grid(row=4, column=0, padx=12, pady=(8, 8), sticky="w")

        picker_col = ctk.CTkFrame(parent)
        picker_col.grid(row=1, column=1, padx=(6, 16), pady=(0, 12), sticky="nsew")
        picker_col.grid_columnconfigure(0, weight=1)
        picker_col.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            picker_col,
            text="2. Available columns",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            picker_col,
            text="Check each metadata field to include in the processed database.",
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=520,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        self.metadata_columns = self._get_metadata_columns()

        if self.metadata_columns:
            metadata_buttons_frame = ctk.CTkFrame(picker_col, fg_color="transparent")
            metadata_buttons_frame.grid(row=2, column=0, padx=8, pady=(0, 6), sticky="ew")
            ctk.CTkButton(
                metadata_buttons_frame,
                text="Select all",
                command=self._select_all_metadata,
                width=110,
            ).pack(side="left", padx=(4, 6), pady=4)
            ctk.CTkButton(
                metadata_buttons_frame,
                text="Deselect all",
                command=self._deselect_all_metadata,
                width=110,
                fg_color="gray40",
            ).pack(side="left", padx=(0, 6), pady=4)

            self.metadata_scroll_frame = ctk.CTkScrollableFrame(picker_col)
            self.metadata_scroll_frame.grid(
                row=3, column=0, padx=12, pady=(0, 12), sticky="nsew"
            )
            self.metadata_scroll_frame.grid_columnconfigure(0, weight=1)
            picker_col.grid_rowconfigure(3, weight=1)

            self.metadata_checkboxes_frame = ctk.CTkFrame(
                self.metadata_scroll_frame, fg_color="transparent"
            )
            self.metadata_checkboxes_frame.grid(row=0, column=0, sticky="ew")
            self._create_metadata_checkboxes()
        else:
            self.metadata_checkboxes_frame = ctk.CTkFrame(picker_col, fg_color="transparent")
            ctk.CTkLabel(
                picker_col,
                text=(
                    "No additional metadata columns are available — every column is already "
                    "used for compound ID or chromatographic data."
                ),
                font=self._wizard_hint_font(),
                text_color="gray",
                wraplength=520,
                justify="left",
                anchor="w",
            ).grid(row=3, column=0, padx=12, pady=(0, 12), sticky="nw")

        self._update_metadata_selection_display()

    def _suggest_bb_columns(self) -> List[str]:
        """Prefer columns named like BB1 Name .. BB4 Name when present."""
        suggestions: List[str] = []
        for i in range(1, 5):
            for candidate in (f"BB{i} Name", f"BB{i}", f"BB{i}_Name"):
                if candidate in self.available_columns:
                    suggestions.append(candidate)
                    break
            else:
                suggestions.append("")
        return suggestions

    def _populate_tab_pedigree(self, parent: ctk.CTkFrame) -> None:
        """Step 5: library structure panel + optional index validation panel."""
        import tkinter as tk

        parent.grid_columnconfigure(0, weight=3, uniform="pedigree_step")
        parent.grid_columnconfigure(1, weight=2, uniform="pedigree_step")
        parent.grid_rowconfigure(1, weight=1)

        instructions = ctk.CTkLabel(
            parent,
            text=(
                "Step 5: Map DEL building-block columns for pedigree and split-tree analysis. "
                "Optionally upload a display-index CSV."
            ),
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=_WIZARD_TEXT_WRAP,
            justify="left",
            anchor="w",
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 8), sticky="ew")

        structure_col = ctk.CTkFrame(parent)
        structure_col.grid(row=1, column=0, padx=(16, 6), pady=(0, 12), sticky="nsew")
        structure_col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            structure_col,
            text="1. Library structure",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            structure_col,
            text=(
                "BB1 is the cycle 1 building block, BB2 is cycle 2, and so on. Map the spreadsheet "
                "column that holds each cycle's building-block name. Pedigree and split-tree "
                "analysis use these columns, not compound ID."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=420,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        cycle_fr = ctk.CTkFrame(structure_col, fg_color="transparent")
        cycle_fr.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(cycle_fr, text="Library cycles:", font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=(4, 8)
        )
        self._cycle_count_var = tk.IntVar(value=self.library_cycle_count)
        for n in (2, 3, 4):
            ctk.CTkRadioButton(
                cycle_fr,
                text=str(n),
                variable=self._cycle_count_var,
                value=n,
                command=self._on_library_cycle_changed,
            ).pack(side="left", padx=6)

        bb_fr = ctk.CTkFrame(structure_col, fg_color="transparent")
        bb_fr.grid(row=3, column=0, padx=8, pady=(0, 10), sticky="ew")
        bb_fr.grid_columnconfigure(1, weight=1)
        if not any(self.bb_position_columns):
            self.bb_position_columns = self._suggest_bb_columns()
        self._bb_column_menus.clear()
        self._bb_column_labels.clear()
        slot_labels = ("BB1", "BB2", "BB3", "BB4")
        col_opts = ["(none)"] + self.available_columns
        self._bb_column_vars: List[tk.StringVar] = []
        for i in range(4):
            lbl = ctk.CTkLabel(bb_fr, text=slot_labels[i])
            lbl.grid(row=i, column=0, padx=8, pady=6, sticky="w")
            self._bb_column_labels.append(lbl)
            initial = self.bb_position_columns[i] if self.bb_position_columns[i] else "(none)"
            if initial not in col_opts:
                initial = "(none)"
            var = tk.StringVar(value=initial)
            self._bb_column_vars.append(var)
            menu = ctk.CTkOptionMenu(bb_fr, variable=var, values=col_opts)
            menu.grid(row=i, column=1, padx=8, pady=6, sticky="ew")
            self._bb_column_menus.append(menu)

        options_fr = ctk.CTkFrame(structure_col, fg_color="transparent")
        options_fr.grid(row=4, column=0, padx=8, pady=(0, 12), sticky="ew")
        options_fr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(options_fr, text="Null token:").grid(
            row=0, column=0, padx=8, pady=6, sticky="w"
        )
        self._null_token_entry = ctk.CTkEntry(options_fr, width=140)
        self._null_token_entry.insert(0, self.null_token)
        self._null_token_entry.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(options_fr, text="Default time unit:").grid(
            row=1, column=0, padx=8, pady=6, sticky="w"
        )
        unit_fr = ctk.CTkFrame(options_fr, fg_color="transparent")
        unit_fr.grid(row=1, column=1, padx=8, pady=6, sticky="w")
        self._analysis_time_unit_var = tk.StringVar(value=self.analysis_time_unit)
        ctk.CTkRadioButton(
            unit_fr, text="Seconds", variable=self._analysis_time_unit_var, value="seconds"
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            unit_fr, text="Minutes", variable=self._analysis_time_unit_var, value="minutes"
        ).pack(side="left")

        index_col = ctk.CTkFrame(parent)
        index_col.grid(row=1, column=1, padx=(6, 16), pady=(0, 12), sticky="nsew")
        index_col.grid_columnconfigure(0, weight=1)
        index_col.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            index_col,
            text="2. Display index (optional)",
            font=self._wizard_section_font(),
        ).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            index_col,
            text=(
                "Upload a CSV with BB name (first column) and Index (second column) to map index "
                "numbers to building blocks for split-tree analysis. Leave empty for automatic "
                "A→Z indexing. Null token uses index 0 when omitted."
            ),
            font=self._wizard_hint_font(),
            text_color="gray",
            wraplength=340,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        index_btn_fr = ctk.CTkFrame(index_col, fg_color="transparent")
        index_btn_fr.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="ew")
        ctk.CTkButton(
            index_btn_fr,
            text="Choose index CSV…",
            width=150,
            command=self._on_browse_bb_index_csv,
        ).pack(side="left", padx=(4, 6), pady=4)
        ctk.CTkButton(
            index_btn_fr,
            text="Clear (auto index)",
            width=130,
            fg_color="gray40",
            command=self._on_clear_bb_index_csv,
        ).pack(side="left", padx=(0, 6), pady=4)
        self.validate_bb_index_button = ctk.CTkButton(
            index_btn_fr,
            text="Validate",
            width=100,
            command=self._on_validate_bb_index_csv,
        )
        self.validate_bb_index_button.pack(side="left", padx=(0, 4), pady=4)

        self._bb_index_path_label = ctk.CTkLabel(
            index_col,
            text="Index source: automatic (alphabetical)",
            font=self._wizard_hint_font(),
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self._bb_index_path_label.grid(row=3, column=0, padx=12, pady=(0, 6), sticky="ew")

        self._bb_index_validation_box = ctk.CTkTextbox(
            index_col,
            wrap="word",
            activate_scrollbars=True,
            font=self._wizard_mono_font(),
        )
        self._bb_index_validation_box.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._bb_index_validation_box.insert(
            "1.0",
            "Upload an index CSV and click Validate to compare against building blocks "
            "detected in the BB columns.",
        )
        self._bb_index_validation_box.configure(state="disabled")
        self._refresh_bb_index_path_label()
        self._on_library_cycle_changed()

    def _on_library_cycle_changed(self) -> None:
        if not hasattr(self, "_cycle_count_var"):
            return
        n = int(self._cycle_count_var.get())
        self.library_cycle_count = n
        for i, (menu, lbl) in enumerate(zip(self._bb_column_menus, self._bb_column_labels)):
            active = i < n
            menu.configure(state="normal" if active else "disabled")
            lbl.configure(text_color=("gray10", "gray90") if active else "gray")

    def _sync_pedigree_fields_to_ui(self) -> None:
        """Push loaded pedigree settings into step 5 controls."""
        if not hasattr(self, "_cycle_count_var"):
            return
        self._cycle_count_var.set(self.library_cycle_count)
        self._on_library_cycle_changed()
        if hasattr(self, "_null_token_entry"):
            self._null_token_entry.delete(0, "end")
            self._null_token_entry.insert(0, self.null_token)
        if hasattr(self, "_analysis_time_unit_var"):
            self._analysis_time_unit_var.set(self.analysis_time_unit)
        for i, var in enumerate(self._bb_column_vars):
            if i >= len(self.bb_position_columns):
                var.set("(none)")
                continue
            col = self.bb_position_columns[i]
            var.set(col if col else "(none)")

    def _read_pedigree_fields_from_ui(self) -> None:
        if not hasattr(self, "_cycle_count_var"):
            return
        prior_pedigree = (
            self.library_cycle_count,
            self.null_token,
            tuple(self.bb_position_columns),
        )
        self.library_cycle_count = int(self._cycle_count_var.get())
        self.null_token = self._null_token_entry.get().strip() or "AgxNull"
        self.analysis_time_unit = self._analysis_time_unit_var.get()
        cols: List[str] = []
        for i in range(4):
            if i >= self.library_cycle_count:
                cols.append("")
                continue
            v = self._bb_column_vars[i].get()
            cols.append("" if v == "(none)" else v)
        self.bb_position_columns = cols
        if prior_pedigree != (
            self.library_cycle_count,
            self.null_token,
            tuple(self.bb_position_columns),
        ):
            self.bb_index_validated = False

    def _refresh_bb_index_path_label(self) -> None:
        if not hasattr(self, "_bb_index_path_label"):
            return
        if self.bb_index_map:
            path_note = self.bb_index_csv_path or "(loaded index map)"
            self._bb_index_path_label.configure(
                text=f"Index source: CSV — {path_note} ({len(self.bb_index_map)} entries)"
            )
        else:
            self._bb_index_path_label.configure(
                text="Index source: automatic (alphabetical)"
            )

    def _set_bb_index_validation_text(self, text: str, *, ok: Optional[bool] = None) -> None:
        if not hasattr(self, "_bb_index_validation_box"):
            return
        self._bb_index_validation_box.configure(state="normal")
        self._bb_index_validation_box.delete("1.0", "end")
        self._bb_index_validation_box.insert("1.0", text)
        self._bb_index_validation_box.configure(state="disabled")
        if ok is True:
            color = ("#1a7f37", "#3fb950")
        elif ok is False:
            color = ("#cf222e", "#f85149")
        else:
            color = ("gray10", "gray90")
        self._bb_index_validation_box.configure(text_color=color)

    def _on_browse_bb_index_csv(self) -> None:
        from tkinter import filedialog

        self._read_pedigree_fields_from_ui()
        path = filedialog.askopenfilename(
            parent=self,
            title="Select building-block index file",
            filetypes=[
                ("Index files", "*.csv;*.xlsx"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        index_map, errors = parse_bb_index_file(path)
        if errors:
            self.bb_index_map = {}
            self.bb_index_csv_path = None
            self.bb_index_validated = False
            self._refresh_bb_index_path_label()
            self._set_bb_index_validation_text(
                "Could not read index file:\n" + "\n".join(errors),
                ok=False,
            )
            show_bb_index_parse_errors(self, errors)
            return
        self.bb_index_map = index_map
        self.bb_index_csv_path = path
        self.bb_index_validated = False
        self._refresh_bb_index_path_label()
        self._set_bb_index_validation_text(
            f"Loaded {len(index_map)} index entries.\n"
            "Click Validate to compare against this library.",
        )
        self._update_wizard_action_highlights()

    def _on_clear_bb_index_csv(self) -> None:
        self._read_pedigree_fields_from_ui()
        self.bb_index_map = {}
        self.bb_index_csv_path = None
        self.bb_index_validated = False
        self._refresh_bb_index_path_label()
        self._set_bb_index_validation_text(
            "Using automatic alphabetical indexing for split-tree labels.",
        )
        self._update_wizard_action_highlights()

    def _on_validate_bb_index_csv(self) -> None:
        self._read_pedigree_fields_from_ui()
        if not self.bb_index_map:
            show_info(
                self,
                "Building-block index",
                "Choose an index file first, or use Clear to rely on automatic indexing.",
            )
            return
        preview = SpreadsheetConfig(
            compound_id_column=self.selected_compound_id_column or "id",
            chromatographic_data_column=self.selected_chromatographic_data_column or "data",
            delimiters=self.delimiters or [","],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Count"],
            null_token=self.null_token,
            library_cycle_count=self.library_cycle_count,
            bb_position_columns=self.bb_position_columns.copy(),
        )
        if not preview.pedigree_configured():
            show_info(
                self,
                "Building-block index",
                "Map all BB1..BBn columns for the selected cycle count before validating.",
            )
            return
        df = self.loader.get_data()
        if df is None:
            self._show_error("Spreadsheet data is not available.")
            return
        detected = detect_building_blocks_from_dataframe(
            df,
            bb_columns=preview.active_bb_position_columns(),
            null_token=self.null_token,
        )
        result = validate_bb_index_map(
            self.bb_index_map,
            detected,
            null_token=self.null_token,
        )
        report = format_validation_report(result)
        self.bb_index_validated = result.ok
        self._set_bb_index_validation_text(report, ok=result.ok)
        show_bb_index_validation_result(self, result)
        self._update_wizard_action_highlights()

    def _wizard_tab_index(self) -> int:
        name = self.tabview.get()
        return self._tab_names.index(name)

    def _on_wizard_tabview_changed(self) -> None:
        """Enforce the same validation gates as Next when switching tabs from the tab bar."""
        if self._wizard_tab_revert_in_progress:
            return
        new_name = self.tabview.get()
        old_name = self._wizard_tab_last_committed
        new_idx = self._tab_names.index(new_name)
        old_idx = self._tab_names.index(old_name)
        if new_idx <= old_idx:
            self._wizard_tab_last_committed = new_name
            return
        for k in range(old_idx, new_idx):
            ok, msg = self._can_advance_from_tab(k)
            if not ok:
                self._wizard_tab_revert_in_progress = True
                try:
                    self.tabview.set(old_name)
                finally:
                    self._wizard_tab_revert_in_progress = False
                self._show_error(msg)
                return
        self._wizard_tab_last_committed = new_name
        self._update_wizard_action_highlights()

    def _wizard_tab_back(self) -> None:
        i = self._wizard_tab_index()
        if i > 0:
            self.tabview.set(self._tab_names[i - 1])
            self._wizard_tab_last_committed = self.tabview.get()
            self._update_wizard_action_highlights()

    def _wizard_tab_next(self) -> None:
        i = self._wizard_tab_index()
        ok, msg = self._can_advance_from_tab(i)
        if not ok:
            self._show_error(msg)
            return
        if i < len(self._tab_names) - 1:
            self.tabview.set(self._tab_names[i + 1])
            self._wizard_tab_last_committed = self.tabview.get()
            self._update_wizard_action_highlights()

    def _can_advance_from_tab(self, tab_index: int) -> tuple[bool, str]:
        if tab_index == 0:
            if not self.selected_compound_id_column or not self.selected_chromatographic_data_column:
                return False, "Select Compound ID and Chromatographic Data columns."
            if self.selected_compound_id_column == self.selected_chromatographic_data_column:
                return False, "Compound ID and Chromatographic Data must be different."
            if not self._columns_sample_confirmed:
                return (
                    False,
                    'Click "Show sample data" to verify paired values from the same rows before continuing.',
                )
        if tab_index == 1:
            if self._get_delimiters_from_ui() is None:
                return False, "Enter at least one delimiter on step 2 (leave extras blank)."
            if not self._delimiter_parse_confirmed or not self.parsed_data_points:
                return False, 'Run "Test parse" successfully on step 2 before continuing.'
        if tab_index == 2:
            if not self.parsed_data_points:
                return False, "Complete step 2 (Test parse) before selecting time and counts."
            if self.selected_time_index is None:
                return False, "Select the time field index."
            if not self.selected_count_indices:
                return False, "Select at least one count field."
            for count_idx in sorted(self.selected_count_indices):
                entry = self.count_name_entries.get(count_idx)
                if not entry or not entry.get().strip():
                    return False, f"Enter a name for count field {count_idx}."
            if not self._data_assignments_confirmed:
                return (
                    False,
                    'Click "Test data assignments" on step 3 before continuing to metadata.',
                )
        return True, ""

    def _on_compound_id_selected(self, choice: str) -> None:
        """Handle Compound ID column selection."""
        if choice and choice in self.available_columns:
            self.selected_compound_id_column = choice
            logger.debug(f"Selected Compound ID column: {choice}")
            self._update_compound_display()
            self._reset_columns_sample_confirmation()
            self._ensure_variant_column_valid()
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
            self._reset_columns_sample_confirmation()
            self._ensure_variant_column_valid()
            # Update metadata columns list (exclude newly selected chromatographic_data column)
            self._refresh_metadata_checkboxes()
            self._validate_selections()
        else:
            logger.warning(f"Invalid Chromatographic Data column selection: {choice}")

    def _on_variant_column_selected(self, choice: str) -> None:
        """Optional column that labels compound versions (e.g. linear / cyclized)."""
        if not choice or choice == "(none)":
            self.selected_variant_column = None
        elif choice in self.available_columns:
            self.selected_variant_column = choice
        else:
            self.selected_variant_column = None
        logger.debug("Variant column: %s", self.selected_variant_column)
        self._refresh_metadata_checkboxes()
        self._validate_selections()

    def _ensure_variant_column_valid(self) -> None:
        """Clear variant selection if it now matches compound ID or chromatographic column."""
        if not self.selected_variant_column:
            return
        if self.selected_variant_column == self.selected_compound_id_column:
            self.selected_variant_column = None
            self.variant_var.set("(none)")
        elif self.selected_variant_column == self.selected_chromatographic_data_column:
            self.selected_variant_column = None
            self.variant_var.set("(none)")

    def _reset_columns_sample_confirmation(self) -> None:
        """Clear sample preview; user must click Show sample data again after column changes."""
        self._columns_sample_confirmed = False
        self._column_pair_sample_text = ""
        self._sample_chrom_strings = []
        if hasattr(self, "column_sample_text"):
            self.column_sample_text.configure(state="normal")
            self.column_sample_text.delete("1.0", "end")
            self.column_sample_text.configure(state="disabled")
        self._refresh_delimiter_step_reference()
        self._invalidate_delimiter_parse()
        self._update_wizard_action_highlights()

    @staticmethod
    def _build_column_sample_preview(
        df: pd.DataFrame,
        cid_col: str,
        chrom_col: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[List[str]]]:
        """
        Pick random spreadsheet rows and format a paired column preview.

        Returns:
            (preview_text, error_message, chrom_values)
        """
        if cid_col not in df.columns or chrom_col not in df.columns:
            return None, "Selected columns are missing from the loaded data.", None

        valid_mask = ~(df[cid_col].isna() & df[chrom_col].isna())
        valid_positions = df.index[valid_mask].tolist()
        if not valid_positions:
            return None, "No rows found with data in at least one of the selected columns.", None

        k = min(3, len(valid_positions))
        picked = random.sample(valid_positions, k=k)

        def format_cell(value: object) -> str:
            try:
                if value is None or pd.isna(value):
                    return "(empty)"
            except (ValueError, TypeError):
                pass
            text = str(value).strip()
            if len(text) > 220:
                return f"{text[:217]}..."
            return text

        lines: List[str] = []
        chrom_values: List[str] = []
        for n, pos in enumerate(picked, start=1):
            row = df.loc[pos]
            row_number = int(pos) + 1 if isinstance(pos, int) else int(df.index.get_loc(pos)) + 1
            lines.append(f"--- Sample {n} · data row {row_number} of {len(df)} ---\n")
            lines.append(f"{cid_col}:\n  {format_cell(row[cid_col])}\n\n")
            lines.append(f"{chrom_col}:\n  {format_cell(row[chrom_col])}\n\n")
            if pd.notna(row[chrom_col]):
                chrom_values.append(str(row[chrom_col]).strip())
            else:
                chrom_values.append("")

        return "".join(lines), None, chrom_values

    def _schedule_on_main(self, callback: Callable, *args) -> None:
        if not self.winfo_exists():
            return
        self.after(0, lambda: self._run_on_main(callback, *args))

    def _run_on_main(self, callback: Callable, *args) -> None:
        if not self.winfo_exists():
            return
        callback(*args)

    def _set_column_sample_loading(self, active: bool, message: str = "") -> None:
        self._sample_loading = active
        if hasattr(self, "column_sample_status"):
            self.column_sample_status.configure(text=message)
        if hasattr(self, "show_column_sample_button"):
            self.show_column_sample_button.configure(state="disabled" if active else "normal")

    def _on_show_column_samples(self) -> None:
        """Display random rows: Compound ID and chromatographic text from the same row."""
        if self._sample_loading:
            return
        if not self.selected_compound_id_column or not self.selected_chromatographic_data_column:
            self._show_error("Select both columns before showing sample data.")
            return
        if self.selected_compound_id_column == self.selected_chromatographic_data_column:
            self._show_error("Compound ID and Chromatographic Data must be different columns.")
            return

        df = self.loader.get_data()
        if df is None or df.empty:
            self._show_error("No spreadsheet data is loaded.")
            return

        cid_col = self.selected_compound_id_column
        chrom_col = self.selected_chromatographic_data_column
        self._set_column_sample_loading(True, "Loading sample rows…")

        def worker() -> None:
            preview, error, chrom_values = self._build_column_sample_preview(
                df,
                cid_col,
                chrom_col,
            )
            self._schedule_on_main(
                self._on_column_samples_ready,
                preview,
                error,
                chrom_values,
            )

        self._sample_worker_thread = threading.Thread(target=worker, daemon=True)
        self._sample_worker_thread.start()

    def _on_column_samples_ready(
        self,
        preview: Optional[str],
        error: Optional[str],
        chrom_values: Optional[List[str]],
    ) -> None:
        self._set_column_sample_loading(False, "")

        if error or preview is None or chrom_values is None:
            self._show_error(error or "Could not build sample preview.")
            self._update_wizard_action_highlights()
            return

        self._column_pair_sample_text = preview
        self._sample_chrom_strings = chrom_values
        self._refresh_delimiter_step_reference()

        self.column_sample_text.configure(state="normal")
        self.column_sample_text.delete("1.0", "end")
        self.column_sample_text.insert("1.0", self._column_pair_sample_text)
        self.column_sample_text.configure(state="disabled")

        self._columns_sample_confirmed = True
        self._validate_selections()
        logger.info("User confirmed column selections via sample data preview")
    
    def _update_compound_display(self) -> None:
        """Update Compound ID selection display."""
        if not hasattr(self, "compound_selected_label"):
            return
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
        if not hasattr(self, "data_selected_label"):
            return
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
    
    def _refresh_delimiter_step_reference(self) -> None:
        """Mirror the step 1 sample text into the delimiters tab."""
        if not hasattr(self, "delimiter_step_reference_text"):
            return
        placeholder = (
            "Complete step 1 and click Show sample data — the same preview will appear here."
        )
        body = self._column_pair_sample_text.strip() or placeholder
        self.delimiter_step_reference_text.configure(state="normal")
        self.delimiter_step_reference_text.delete("1.0", "end")
        self.delimiter_step_reference_text.insert("1.0", body)
        self.delimiter_step_reference_text.configure(state="disabled")

    def _reset_data_assignments_confirmation(self) -> None:
        """Clear assignment preview confirmation; user must click Test data assignments again."""
        self._data_assignments_confirmed = False
        if (
            self.parsed_data_points
            and self.items_per_point is not None
            and hasattr(self, "structured_text")
        ):
            self._display_structured_data(use_assignment_headers=False)

    def _invalidate_delimiter_parse(self) -> None:
        """Clear parse results when delimiters or samples change."""
        self._delimiter_parse_confirmed = False
        self._data_assignments_confirmed = False
        self.parsed_flat_items = []
        self.parsed_data_points = []
        self.items_per_point = None
        if hasattr(self, "preview_text"):
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", "Enter delimiters and click Test parse.")
        if hasattr(self, "parse_status_label"):
            self.parse_status_label.configure(text="")
        if hasattr(self, "structured_text"):
            self.structured_text.delete("1.0", "end")
            self.structured_text.insert(
                "1.0",
                "Complete step 2 (Test parse) to populate structured points here.",
            )
        self._validate_selections()

    def _on_delimiter_field_edited(self) -> None:
        """Delimiter text changed — require a new test parse."""
        self._invalidate_delimiter_parse()

    def _get_delimiters_from_ui(self) -> Optional[List[str]]:
        """Return non-blank delimiters in order (up to three slots); None if none entered."""
        if not getattr(self, "delimiter_entry_widgets", None):
            return None
        out: List[str] = []
        for ent in self.delimiter_entry_widgets:
            raw = ent.get()
            if raw == "":
                continue
            out.append(raw)
        if not out:
            return None
        return out

    def _apply_delimiter_entries_from_list(self, delims: List[str]) -> None:
        """Populate the three delimiter fields from a saved list (extras omitted)."""
        if not hasattr(self, "delimiter_entry_widgets"):
            return
        self._invalidate_delimiter_parse()
        trimmed = list(delims[:3])
        for i in range(3):
            self.delimiter_entry_widgets[i].delete(0, "end")
            if i < len(trimmed):
                self.delimiter_entry_widgets[i].insert(0, trimmed[i])

    def _format_structured_preview_table(self) -> str:
        """Build a compact text table for the parse preview area."""
        if not self.parsed_data_points or self.items_per_point is None:
            return ""
        lines: List[str] = []
        header = "Idx | " + " | ".join(f"Fld {j}" for j in range(self.items_per_point))
        lines.append(header)
        lines.append("-" * min(96, max(40, len(header))))
        for i, pt in enumerate(self.parsed_data_points[:24]):
            row = " | ".join(str(x)[:22] for x in pt)
            lines.append(f"{i:3} | {row}")
        if len(self.parsed_data_points) > 24:
            lines.append(f"... ({len(self.parsed_data_points)} points total)")
        return "\n".join(lines)

    def _on_test_parse_click(self) -> None:
        """User clicked Test parse (shows errors in dialog)."""
        self._run_delimiter_test_parse(silent=False)

    def _ensure_chrom_sample_strings(self) -> None:
        """If step 1 did not fill chrom samples, take the first non-empty spreadsheet cell."""
        if self._sample_chrom_strings:
            return
        if not self.selected_chromatographic_data_column:
            return
        df = self.loader.get_data()
        if df is None or self.selected_chromatographic_data_column not in df.columns:
            return
        col = df[self.selected_chromatographic_data_column]
        for val in col:
            if pd.notna(val) and str(val).strip():
                self._sample_chrom_strings = [str(val).strip()]
                break

    def _run_delimiter_test_parse(self, silent: bool = False) -> bool:
        """
        Parse the first non-empty chrom sample using UI delimiters.
        Fields per point always equals len(delimiters).
        """
        def fail(msg: str) -> bool:
            self._delimiter_parse_confirmed = False
            if hasattr(self, "parse_status_label"):
                self.parse_status_label.configure(text=f"✗ {msg}", text_color="red")
            if hasattr(self, "preview_text"):
                self.preview_text.delete("1.0", "end")
                self.preview_text.insert("1.0", msg)
            if not silent:
                self._show_error(msg)
            self._validate_selections()
            return False

        test_data = ""
        for s in self._sample_chrom_strings:
            if s and str(s).strip():
                test_data = str(s).strip()
                break
        if not test_data:
            return fail("No chromatographic sample from step 1. Use Show sample data first.")

        dlist = self._get_delimiters_from_ui()
        if dlist is None:
            return fail("Enter at least one delimiter. Leave unused delimiter fields blank.")

        items_per = len(dlist)
        try:
            parser = DataParser(dlist.copy())
            flat = parser.parse(test_data)
        except Exception as e:
            logger.error("Delimiter test parse failed", exc_info=True)
            return fail(str(e))

        if not flat:
            return fail("Parsing produced no items.")

        if len(flat) % items_per != 0:
            return fail(
                f"Parsed {len(flat)} field(s), not evenly divisible by {items_per} "
                f"(your delimiter count). Adjust delimiters or pick a matching sample row."
            )

        self.delimiters = dlist.copy()
        self.parsed_flat_items = flat
        self.parsed_data_points = [
            flat[i : i + items_per] for i in range(0, len(flat), items_per)
        ]
        self.items_per_point = items_per
        self._delimiter_parse_confirmed = True

        if hasattr(self, "preview_text"):
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", self._format_structured_preview_table())
        if hasattr(self, "parse_status_label"):
            self.parse_status_label.configure(
                text=(
                    f"✓ {len(self.parsed_data_points)} data point(s), "
                    f"{items_per} field(s) per point (= {items_per} delimiter(s))."
                ),
                text_color="green",
            )
        self._data_assignments_confirmed = False
        self._display_structured_data(use_assignment_headers=False)
        self._update_field_selection_ui()
        self._validate_selections()
        logger.info(
            "Test parse OK: %s points, items_per_point=%s",
            len(self.parsed_data_points),
            items_per,
        )
        return True
    
    def _get_structured_column_headers(self, use_assignment_headers: bool) -> List[str]:
        """Build preview column titles: generic Field n, or Time / count names when testing assignments."""
        if self.items_per_point is None:
            return []
        headers: List[str] = []
        for i in range(self.items_per_point):
            if use_assignment_headers and self.selected_time_index == i:
                headers.append("Time")
            elif use_assignment_headers and i in self.selected_count_indices:
                ent = self.count_name_entries.get(i)
                name = ent.get().strip() if ent else ""
                if not name and self.count_names:
                    sorted_idx = sorted(self.selected_count_indices)
                    if i in sorted_idx:
                        pos = sorted_idx.index(i)
                        if pos < len(self.count_names):
                            name = str(self.count_names[pos]).strip()
                headers.append(name if name else f"Count (field {i})")
            else:
                headers.append(f"Field {i}")
        return headers

    def _display_structured_data(self, use_assignment_headers: bool = False) -> None:
        """Display structured data points; optional headers from time/count assignments."""
        if not hasattr(self, "structured_text"):
            return
        if not self.parsed_data_points or self.items_per_point is None:
            self.structured_text.delete("1.0", "end")
            self.structured_text.insert(
                "1.0",
                "No structured data yet. Complete step 2 with Test parse.",
            )
            return

        headers = self._get_structured_column_headers(use_assignment_headers)
        mode = "Assignment preview" if use_assignment_headers else "Field index preview"
        result_text = f"{mode} — {len(self.parsed_data_points)} data points (first 10 rows):\n\n"
        result_text += "Idx | " + " | ".join(headers) + "\n"
        sep_len = min(96, max(36, 6 + sum(max(8, len(h)) for h in headers)))
        result_text += "-" * sep_len + "\n"

        for i, point in enumerate(self.parsed_data_points[:10], 0):
            result_text += f"{i:3} | " + " | ".join(str(item)[:14] for item in point) + "\n"

        if len(self.parsed_data_points) > 10:
            result_text += f"\n... and {len(self.parsed_data_points) - 10} more data points\n"

        if use_assignment_headers:
            result_text += "\nHeaders reflect your time field and count names."
        else:
            result_text += (
                f"\nUse Test data assignments to replace headers with Time and your count names."
            )

        self.structured_text.delete("1.0", "end")
        self.structured_text.insert("1.0", result_text)

    def _on_test_data_assignments_click(self) -> None:
        """Refresh the structured preview using Time + count name column headers."""
        if not self.parsed_data_points:
            self._show_error("Complete step 2 with Test parse first.")
            return
        if self.selected_time_index is None:
            self._show_error("Select a time field first.")
            return
        if not self.selected_count_indices:
            self._show_error("Select at least one count field first.")
            return
        for idx in sorted(self.selected_count_indices):
            entry = self.count_name_entries.get(idx)
            if not entry or not entry.get().strip():
                self._show_error(
                    f"Enter a name for each selected count field (missing for field {idx})."
                )
                return
        self._display_structured_data(use_assignment_headers=True)
        self._data_assignments_confirmed = True
        self._validate_selections()

    def _update_field_selection_ui(self) -> None:
        """Update time and count selection UIs based on structured data."""
        if not self.parsed_data_points or self.items_per_point is None:
            return
        if not hasattr(self, "time_index_dropdown"):
            return
        
        # Update time index dropdown
        field_labels = [f"Field {i}" for i in range(self.items_per_point)]
        self.time_index_dropdown.configure(values=field_labels)
        if self.selected_time_index is not None and self.selected_time_index < self.items_per_point:
            self.time_index_var.set(f"Field {self.selected_time_index}")
        
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
        """Handle time index selection (combobox shows 'Field 0', 'Field 1', ...)."""
        try:
            raw = (choice or "").strip()
            prefix = "Field "
            if raw.startswith(prefix):
                self.selected_time_index = int(raw[len(prefix) :].strip())
            else:
                self.selected_time_index = int(raw)
            logger.debug(f"Selected time index: {self.selected_time_index}")
            self._reset_data_assignments_confirmation()
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
        self._reset_data_assignments_confirmation()
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
                text_color="gray",
            )
            label.grid(row=0, column=0, columnspan=2, padx=6, pady=8, sticky="w")
            return

        for row_idx, count_idx in enumerate(sorted(self.selected_count_indices)):
            field_label = ctk.CTkLabel(
                self.count_names_frame,
                text=f"Field {count_idx}:",
                font=ctk.CTkFont(size=11),
            )
            field_label.grid(row=row_idx, column=0, padx=(6, 8), pady=3, sticky="w")
            
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
                width=240,
            )
            if existing_name:
                entry.insert(0, existing_name)
            entry.grid(row=row_idx, column=1, padx=(0, 6), pady=3, sticky="ew")
            entry.bind("<KeyRelease>", lambda e, idx=count_idx: self._on_count_name_changed(idx))
            
            self.count_name_entries[count_idx] = entry
        
        self.count_names_frame.grid_columnconfigure(1, weight=1)
    
    def _on_count_name_changed(self, index: int) -> None:
        """Handle count name change."""
        entry = self.count_name_entries.get(index)
        if entry:
            self._reset_data_assignments_confirmation()
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
        if self.selected_variant_column:
            excluded.add(self.selected_variant_column)
        
        for col in self.available_columns:
            if col not in excluded:
                metadata_cols.append(col)
        
        return metadata_cols
    
    def _metadata_checkbox_caption(self, col_name: str) -> str:
        """Shorten very long header text so multi-column layout stays readable."""
        max_len = 48
        if len(col_name) <= max_len:
            return col_name
        return col_name[: max_len - 1] + "…"

    def _metadata_grid_column_count(self) -> int:
        """Pick 2–5 columns from how many metadata fields exist (reduces vertical stacking)."""
        n = len(self.metadata_columns)
        if n <= 1:
            return 1
        if n <= 8:
            return 2
        if n <= 18:
            return 3
        if n <= 36:
            return 4
        return 5

    def _create_metadata_checkboxes(self) -> None:
        """Lay out metadata checkboxes in a multi-column grid across the tab."""
        for widget in self.metadata_checkboxes_frame.winfo_children():
            widget.destroy()
        self.metadata_checkboxes.clear()

        cols = self._metadata_grid_column_count()
        for c in range(cols):
            self.metadata_checkboxes_frame.grid_columnconfigure(
                c, weight=1, uniform="metadata_checkbox_col"
            )

        sorted_names = sorted(self.metadata_columns)
        for i, col_name in enumerate(sorted_names):
            r, c = divmod(i, cols)
            checkbox = ctk.CTkCheckBox(
                self.metadata_checkboxes_frame,
                text=self._metadata_checkbox_caption(col_name),
                command=lambda col=col_name: self._on_metadata_column_toggled(col),
            )
            checkbox.grid(row=r, column=c, padx=8, pady=4, sticky="nw")
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
        if not hasattr(self, "metadata_selection_label"):
            return

        if not self.metadata_columns:
            self.metadata_selection_label.configure(
                text="No extra metadata columns are available for this spreadsheet.",
                text_color="gray",
            )
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
    
    def _validate_selections(self) -> bool:
        """
        Validate column selections and delimiter configuration.
        
        Returns:
            True if selections are valid, False otherwise
        """
        if not hasattr(self, "validation_label") or not hasattr(self, "accept_button"):
            return False

        result = False
        try:
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

            if self.selected_variant_column:
                if self.selected_variant_column not in self.available_columns:
                    errors.append(
                        f"Variant column '{self.selected_variant_column}' not found in spreadsheet"
                    )
                if self.selected_variant_column == self.selected_compound_id_column:
                    errors.append("Variant column must differ from Compound ID column")
                if self.selected_variant_column == self.selected_chromatographic_data_column:
                    errors.append("Variant column must differ from Chromatographic Data column")
        
            if (
                self.selected_compound_id_column
                and self.selected_chromatographic_data_column
                and self.selected_compound_id_column != self.selected_chromatographic_data_column
                and self.selected_compound_id_column in self.available_columns
                and self.selected_chromatographic_data_column in self.available_columns
                and not self._columns_sample_confirmed
            ):
                errors.append(
                    'Click "Show sample data" to verify paired values from the same rows before continuing.'
                )
        
            if errors:
                error_text = "Validation errors:\n" + "\n".join(f"• {error}" for error in errors)
                self.validation_label.configure(text=error_text, text_color="red")
                self.accept_button.configure(state="disabled")
                return False

            if not self._delimiter_parse_confirmed:
                self.validation_label.configure(
                    text=(
                        "✓ Column selections verified. On step 2, enter delimiters and click Test parse."
                    ),
                    text_color="green",
                )
                self.accept_button.configure(state="disabled")
                return False
        
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
        
            if errors:
                error_text = "Validation errors:\n" + "\n".join(f"• {error}" for error in errors)
                self.validation_label.configure(text=error_text, text_color="red")
                self.accept_button.configure(state="disabled")
                return False

            if self.parsed_data_points and self.selected_time_index is not None and self.selected_count_indices:
                if not self._data_assignments_confirmed:
                    self.validation_label.configure(
                        text=(
                            '✓ Time and count fields look valid. Click "Test data assignments" on step 3, '
                            "then use Accept configuration below on this tab."
                        ),
                        text_color="green",
                    )
                    self.accept_button.configure(state="disabled")
                    return False
                self.validation_label.configure(
                    text=(
                        "✓ Configuration is complete and valid. "
                        "Use Accept configuration below when you are done with metadata."
                    ),
                    text_color="green",
                )
            else:
                self.validation_label.configure(
                    text="✓ Basic configuration is valid. Complete time and count selection to finalize.",
                    text_color="green",
                )
            self.accept_button.configure(state="normal")
            return True
        finally:
            if hasattr(self, "next_tab_btn"):
                self._update_wizard_action_highlights()
    
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
            if not self._data_assignments_confirmed:
                self._show_error(
                    'Click "Test data assignments" on step 3 before accepting configuration.'
                )
                return
        
        self._read_pedigree_fields_from_ui()

        if self.bb_index_map and not self.bb_index_validated:
            show_error(
                self,
                "Building-block index",
                "The building-block index file has not been validated against this spreadsheet.",
                what_to_do=(
                    'Open step 5 — DEL / Pedigree, click Validate, fix any encoding or '
                    "name mismatches, then Accept again. "
                    "Or Clear the index to use automatic numbering."
                ),
            )
            return

        try:
            # Create complete configuration
            config = SpreadsheetConfig(
                compound_id_column=self.selected_compound_id_column,
                chromatographic_data_column=self.selected_chromatographic_data_column,
                compound_variant_column=self.selected_variant_column,
                delimiters=self.delimiters.copy(),
                time_column_index=self.selected_time_index,
                count_column_indices=self.selected_count_indices.copy(),
                count_names=self.count_names.copy(),
                selected_metadata_columns=self.selected_metadata_columns.copy(),
                null_token=self.null_token,
                library_cycle_count=self.library_cycle_count,
                bb_position_columns=self.bb_position_columns.copy(),
                bb_index_map=dict(self.bb_index_map),
                bb_index_csv_path=self.bb_index_csv_path,
                analysis_time_unit=self.analysis_time_unit,
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
        show_error(self, "Configuration", message)
    
    def _format_default_preset_summary(self) -> str:
        """Build a short summary of parameters from the default config file (for Load preset)."""
        config = self.config_manager.load_default_config()
        if not config:
            return (
                "Default preset (from default_config.json):\n\n"
                "No default configuration file was found, or it could not be read. "
                "Choosing Default still attempts to load it; complete the wizard manually if needed."
            )
        delim_line = (
            ", ".join(repr(d) for d in config.delimiters)
            if config.delimiters
            else "(none)"
        )
        count_pairs = []
        for idx, name in zip(config.count_column_indices, config.count_names):
            count_pairs.append(f"{idx} → {name}")
        counts_line = "; ".join(count_pairs) if count_pairs else "(not set in file)"
        meta_n = len(config.selected_metadata_columns)
        meta_line = (
            f"{meta_n} column(s): {', '.join(config.selected_metadata_columns)}"
            if meta_n
            else "None"
        )
        vline = (
            config.compound_variant_column
            if getattr(config, "compound_variant_column", None)
            else "(none)"
        )
        return (
            "Default preset (from default_config.json):\n\n"
            f"Compound ID column: {config.compound_id_column}\n"
            f"Chromatographic data column: {config.chromatographic_data_column}\n"
            f"Variant column: {vline}\n"
            f"Delimiters (order): {delim_line}\n"
            f"Time column index: {config.time_column_index}\n"
            f"Count fields: {counts_line}\n"
            f"Metadata: {meta_line}"
        )

    def _show_load_preset_dialog(self) -> None:
        """Open a small dialog showing default parameters and a preset picker."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Load preset")
        dlg.geometry("520x440")
        dlg.transient(self)
        dlg.grab_set()
        dlg.grid_columnconfigure(0, weight=1)
        dlg.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            dlg,
            text="Default file parameters (reference). Choose a preset to apply to this spreadsheet.",
            font=ctk.CTkFont(size=12),
            wraplength=480,
            justify="left",
            anchor="w",
        )
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")

        summary_box = ctk.CTkTextbox(dlg, height=200, wrap="word", activate_scrollbars=True)
        summary_box.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        summary_box.insert("1.0", self._format_default_preset_summary())
        summary_box.configure(state="disabled")

        picker_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        picker_frame.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        picker_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(picker_frame, text="Preset:").grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        saved_configs = self.config_manager.list_named_configs()
        config_names = [c["name"] for c in saved_configs]
        preset_var = ctk.StringVar(value="Default")
        combo = ctk.CTkComboBox(
            picker_frame,
            variable=preset_var,
            values=["Default"] + config_names if config_names else ["Default"],
            state="readonly",
            width=280,
        )
        combo.grid(row=0, column=1, padx=0, pady=4, sticky="ew")

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=3, column=0, padx=16, pady=(8, 16), sticky="e")

        def on_load() -> None:
            from tkinter import messagebox

            choice = preset_var.get() or "Default"
            loaded_config = self._load_preset(choice)
            if loaded_config is None:
                return
            dlg.destroy()
            if choice == "Default":
                messagebox.showinfo(
                    "Default configuration",
                    "Validation passed: the saved default configuration is compatible "
                    "with this spreadsheet.",
                    parent=self,
                )
                if self.on_default_preset_applied:
                    self.on_default_preset_applied(loaded_config)
                self.on_close()

        def on_cancel() -> None:
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        ctk.CTkButton(btn_row, text="Load preset", width=110, command=on_load).grid(
            row=0, column=0, padx=4, pady=4
        )
        ctk.CTkButton(
            btn_row,
            text="Close",
            width=90,
            fg_color="gray40",
            hover_color="gray25",
            command=on_cancel,
        ).grid(row=0, column=1, padx=4, pady=4)

        dlg.protocol("WM_DELETE_WINDOW", on_cancel)

    def _load_preset(self, preset_name: str) -> Optional[SpreadsheetConfig]:
        """
        Load the default or a named preset into the wizard.

        Returns:
            The applied SpreadsheetConfig if loading succeeded, or None on failure.
        """
        if not preset_name or preset_name == "Default":
            config = self.config_manager.load_default_config()
        else:
            config = self.config_manager.load_named_config(preset_name)

        if not config:
            self._show_error("No configuration found to load.")
            return None

        is_valid, error_msg = self.config_manager.validate_config_against_spreadsheet(
            config, self.available_columns
        )

        if not is_valid:
            self._show_error(
                "Cannot load configuration: "
                f"{error_msg or 'This preset does not match the current spreadsheet.'}"
            )
            return None

        self.selected_compound_id_column = config.compound_id_column
        self.selected_chromatographic_data_column = config.chromatographic_data_column
        self.delimiters = config.delimiters.copy() if config.delimiters else []
        if len(self.delimiters) > 3:
            logger.warning("Preset lists more than 3 delimiters; using the first 3 for this wizard.")
            self.delimiters = self.delimiters[:3]
        self.selected_time_index = config.time_column_index
        self.selected_count_indices = (
            config.count_column_indices.copy() if config.count_column_indices else []
        )
        self.count_names = config.count_names.copy() if config.count_names else []
        self.selected_metadata_columns = (
            config.selected_metadata_columns.copy() if config.selected_metadata_columns else []
        )
        self.library_cycle_count = int(getattr(config, "library_cycle_count", 3))
        self.null_token = str(getattr(config, "null_token", "AgxNull"))
        self.analysis_time_unit = str(getattr(config, "analysis_time_unit", "seconds"))
        bb = getattr(config, "bb_position_columns", None)
        if bb and len(bb) >= 4:
            self.bb_position_columns = [str(c or "") for c in bb[:4]]
        else:
            self.bb_position_columns = ["", "", "", ""]
        saved_index = getattr(config, "bb_index_map", None) or {}
        if saved_index:
            self.bb_index_map = {str(k): int(v) for k, v in saved_index.items()}
            raw_path = getattr(config, "bb_index_csv_path", None)
            self.bb_index_csv_path = str(raw_path).strip() if raw_path else None
            self.bb_index_validated = True
        else:
            self.bb_index_map = {}
            self.bb_index_csv_path = None
            self.bb_index_validated = False
        if hasattr(self, "_refresh_bb_index_path_label"):
            self._refresh_bb_index_path_label()
        vcol = getattr(config, "compound_variant_column", None)
        if vcol and str(vcol).strip() and str(vcol).strip() in self.available_columns:
            self.selected_variant_column = str(vcol).strip()
            self.variant_var.set(self.selected_variant_column)
        else:
            self.selected_variant_column = None
            self.variant_var.set("(none)")

        self._sync_pedigree_fields_to_ui()

        if self.selected_compound_id_column:
            self.compound_var.set(self.selected_compound_id_column)
        if self.selected_chromatographic_data_column:
            self.data_var.set(self.selected_chromatographic_data_column)

        self._update_compound_display()
        self._update_data_display()
        self._apply_delimiter_entries_from_list(self.delimiters)

        if hasattr(self, "metadata_checkboxes_frame"):
            self._refresh_metadata_checkboxes()

        preset_note = (
            "Preset applied: columns were validated for this spreadsheet. "
            "Change a column selection if you want a new preview via Show sample data.\n"
        )
        self._columns_sample_confirmed = True
        self._column_pair_sample_text = preset_note
        if hasattr(self, "column_sample_text"):
            self.column_sample_text.configure(state="normal")
            self.column_sample_text.delete("1.0", "end")
            self.column_sample_text.insert("1.0", preset_note)
            self.column_sample_text.configure(state="disabled")
        self._refresh_delimiter_step_reference()

        self._ensure_chrom_sample_strings()
        parse_ok = False
        if self.delimiters and self._sample_chrom_strings:
            parse_ok = self._run_delimiter_test_parse(silent=True)
        if not parse_ok:
            self.selected_time_index = None
            self.selected_count_indices = []
            self.count_names = []
        elif self.items_per_point is not None:
            if self.selected_time_index is not None and self.selected_time_index >= self.items_per_point:
                self.selected_time_index = None
            self.selected_count_indices = [
                i for i in self.selected_count_indices if i < self.items_per_point
            ]
            self.count_names = self.count_names[: len(self.selected_count_indices)]
            self._update_field_selection_ui()

        if (
            parse_ok
            and self.selected_time_index is not None
            and self.selected_count_indices
            and len(self.count_names) == len(self.selected_count_indices)
        ):
            self._display_structured_data(use_assignment_headers=True)
            self._data_assignments_confirmed = True
        else:
            self._data_assignments_confirmed = False
        self._validate_selections()

        try:
            applied = SpreadsheetConfig(
                compound_id_column=self.selected_compound_id_column,
                chromatographic_data_column=self.selected_chromatographic_data_column,
                compound_variant_column=self.selected_variant_column,
                delimiters=self.delimiters.copy(),
                time_column_index=self.selected_time_index,
                count_column_indices=self.selected_count_indices.copy(),
                count_names=self.count_names.copy(),
                selected_metadata_columns=self.selected_metadata_columns.copy(),
                null_token=self.null_token,
                library_cycle_count=self.library_cycle_count,
                bb_position_columns=self.bb_position_columns.copy(),
                bb_index_map=dict(self.bb_index_map),
                bb_index_csv_path=self.bb_index_csv_path,
                analysis_time_unit=self.analysis_time_unit,
            )
            applied.__post_init__()
        except ValueError as e:
            logger.error("Preset produced invalid configuration: %s", e, exc_info=True)
            self._show_error(f"Loaded preset has invalid field layout: {e}")
            return None

        logger.info("Loaded preset: %s", preset_name)
        return applied

    def _save_preset(self) -> None:
        """Save current configuration as a named preset (same as former Save As)."""
        from tkinter import messagebox
        from tkinter import simpledialog

        messagebox.showinfo(
            "Save preset",
            "This saves your current spreadsheet configuration settings only: "
            "column mappings, delimiter sequence, parsed field layout, time and count fields, "
            "and selected metadata. It does not export spreadsheet data. "
            "You can load this preset later with Load preset.",
        )

        name = simpledialog.askstring(
            "Save preset",
            "Enter a name for this configuration preset:",
            initialvalue="",
        )

        if not name or not name.strip():
            return

        if not self._validate_selections():
            self._show_error("Cannot save: Configuration is incomplete or invalid.")
            return

        self._read_pedigree_fields_from_ui()

        try:
            config = SpreadsheetConfig(
                compound_id_column=self.selected_compound_id_column,
                chromatographic_data_column=self.selected_chromatographic_data_column,
                compound_variant_column=self.selected_variant_column,
                delimiters=self.delimiters.copy(),
                time_column_index=self.selected_time_index,
                count_column_indices=self.selected_count_indices.copy(),
                count_names=self.count_names.copy(),
                selected_metadata_columns=self.selected_metadata_columns.copy(),
                null_token=self.null_token,
                library_cycle_count=self.library_cycle_count,
                bb_position_columns=self.bb_position_columns.copy(),
                analysis_time_unit=self.analysis_time_unit,
            )

            success = self.config_manager.save_named_config(config, name.strip())

            if success:
                messagebox.showinfo("Success", f"Configuration preset saved as '{name.strip()}'.")
                logger.info("Saved configuration preset as '%s'", name.strip())
            else:
                self._show_error("Failed to save configuration.")

        except Exception as e:
            error_msg = f"Error saving configuration: {str(e)}"
            self._show_error(error_msg)
            logger.error(error_msg, exc_info=True)