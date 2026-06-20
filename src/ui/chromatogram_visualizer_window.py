# src/ui/chromatogram_visualizer_window.py
"""
Chromatogram visualizer: plot on top, compound table and controls below (Phase 10–11).
"""

import logging
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
import pandas as pd
from matplotlib.backend_bases import MouseEvent, PickEvent
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.text import Text
from tkinter import filedialog, messagebox, ttk

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.models.compound import Compound
from src.models.compound_identity import split_compound_storage_id
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.chromatogram_dialogs import CompoundPickerDialog, MetadataSearchDialog
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_MAX_PARSE_CACHE = 32
_MAX_PROCEED_KEYS = 200
_MAX_METADATA_COLUMNS_DISPLAY = 128
_TABLE_ROW_INDEX_COL = "row_idx"
_TABLE_COL_PAD_PX = 28
_TABLE_COL_WIDTH_MIN = 72
_TABLE_COL_WIDTH_MAX = 420
_TABLE_IDX_COL_WIDTH_MIN = 44
_TABLE_IDX_COL_WIDTH_MAX = 72
_PLOT_LINE_PICK_RADIUS_PT = 12
_PLOT_FOCUS_LINE_COLOR = "#ffd666"


class ChromatogramVisualizerWindow(BaseWindow):
    """
    Chromatogram on top (full width); compound table, picker/search dialogs, and series toggles below.

    Requires an active SQLite database (full export or index). Index databases store raw
    chromatogram text and parse on demand; full databases use precomputed data_points.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
        loader: SpreadsheetLoader,
    ) -> None:
        super().__init__(
            parent,
            title="Chromatogram Visualizer",
            transient_parent=False,
            modal=False,
        )
        self.bind("<Destroy>", self._clear_main_reference)

        self.app_state = app_state
        self.config_manager = config_manager
        self._loader = loader
        self._data_store: Optional[DataStore] = None
        self._config: Optional[SpreadsheetConfig] = None
        self._all_ids: List[str] = []
        self._uses_variants: bool = False
        self._current_compounds: List[Compound] = []
        self._count_check_vars: dict[str, tk.IntVar] = {}
        self._on_demand_mode = False
        self._index_db_mode = False
        self._compound_cache: "OrderedDict[str, Compound]" = OrderedDict()
        self._primary_variant_cache: "OrderedDict[str, List[Compound]]" = OrderedDict()
        self._processor = DataProcessor()
        self._searchable_metadata_columns: List[str] = []
        self._table_compounds_by_iid: Dict[str, Compound] = {}
        self._count_series_frame: Optional[ctk.CTkFrame] = None
        self._pick_meta: Dict[int, Tuple[str, str]] = {}
        self._legend_text_meta: Dict[int, Tuple[str, str]] = {}
        self._plot_pick_table_iid: Optional[str] = None
        self._plot_pick_count_name: Optional[str] = None
        self._suppress_table_selection_plot = False
        self._selection_plot_after_id: Optional[str] = None

        self.minsize(900, 600)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=3)
        self.grid_rowconfigure(3, weight=2)

        cfg = config_manager.load_default_config()
        if not cfg or not cfg.count_names:
            messagebox.showerror(
                "Configuration missing",
                "Count channel names are not available. "
                "Re-open Configure Spreadsheet and save your configuration.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        self._config = cfg
        self._uses_variants = bool(cfg.compound_variant_column)

        db_path = self._resolve_database_path()
        if not db_path or not Path(db_path).is_file():
            messagebox.showerror(
                "Database required",
                "Use 'Create / Load database' to build or load a full or index SQLite file "
                "before opening the visualizer.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        try:
            self._data_store = DataStore(db_path=Path(db_path), use_memory=False)
        except Exception as exc:
            logger.error("Failed to open database: %s", exc, exc_info=True)
            messagebox.showerror("Database error", str(exc), parent=self)
            self.after(50, self.on_close)
            return

        self._index_db_mode = self._data_store.is_index_database()
        self._on_demand_mode = self._index_db_mode
        all_meta = list(self._config.selected_metadata_columns or [])
        self._searchable_metadata_columns, _miss = self._data_store.filter_metadata_columns_for_search(
            all_meta
        )
        if self._uses_variants:
            self._all_ids = self._data_store.get_distinct_primary_compound_ids()
        else:
            self._all_ids = sorted(self._data_store.get_all_compound_ids())
        if not self._all_ids:
            messagebox.showwarning(
                "No compounds",
                "The database contains no compounds to plot.",
                parent=self,
            )

        self._build_header()
        self._build_plot_area()
        self._build_bottom_controls()
        self._build_compound_table()

        self.after(200, self._apply_maximized_state)

        logger.info(
            "Chromatogram visualizer opened (%s compounds, index_db=%s)",
            len(self._all_ids),
            self._index_db_mode,
        )

    def _apply_maximized_state(self) -> None:
        """Fill the screen (Windows ``zoomed`` / Linux zoomed attribute)."""
        if not self.winfo_exists():
            return
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                self.geometry(f"{self.winfo_screenwidth() - 80}x{self.winfo_screenheight() - 120}+40+40")

    def _clear_main_reference(self, event: tk.Event) -> None:
        if event.widget != self:
            return
        main = self.parent
        if main is not None and getattr(main, "_chromatogram_window", None) is self:
            main._chromatogram_window = None

    def _resolve_database_path(self) -> Optional[str]:
        if self.app_state.database_path and Path(self.app_state.database_path).is_file():
            return self.app_state.database_path
        return None

    @staticmethod
    def _column_heading_display(col: str) -> str:
        """Heading label for a logical column id (matches Treeview heading text)."""
        if col == _TABLE_ROW_INDEX_COL:
            return "#"
        if col == "library_id":
            return "Compound ID"
        return col.replace("_", " ").title()

    def _treeview_font(self) -> tkfont.Font:
        """Font used for Treeview cell measurements (horizontal scroll / column widths)."""
        try:
            return tkfont.nametofont("TkTreeviewFont")
        except tk.TclError:
            return tkfont.nametofont("TkDefaultFont")

    def _cell_text_for_tree_column(self, c: Compound, col: str, row_index: int) -> str:
        """Plain text for one table cell (must match ``_row_values`` truncation rules)."""
        if col == _TABLE_ROW_INDEX_COL:
            return str(row_index)
        if col == "library_id":
            return str(c.primary_compound_id or "").strip()
        if col == "variant":
            return str(c.variant_label or "").strip()
        if col == "compound_id":
            return str(c.compound_id).strip()
        v = c.metadata.get(col, "")
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v)[:80]

    def _autosize_tree_columns(self) -> None:
        """
        Set column widths from header and cell text, capped so the total can exceed the
        widget width and enable horizontal scrolling (all columns use stretch=False).
        """
        cols = self._table_column_names()
        font = self._treeview_font()
        for col in cols:
            label = self._column_heading_display(col)
            measured = font.measure(label)
            for idx, iid in enumerate(self._tree.get_children(), start=1):
                compound = self._table_compounds_by_iid.get(str(iid))
                if compound is None:
                    continue
                cell = self._cell_text_for_tree_column(compound, col, idx)
                measured = max(measured, font.measure(cell))
            width = int(measured + _TABLE_COL_PAD_PX)
            if col == _TABLE_ROW_INDEX_COL:
                width = max(_TABLE_IDX_COL_WIDTH_MIN, min(_TABLE_IDX_COL_WIDTH_MAX, width))
                self._tree.column(col, width=width, stretch=False, anchor="e")
            else:
                width = max(_TABLE_COL_WIDTH_MIN, min(_TABLE_COL_WIDTH_MAX, width))
                self._tree.column(col, width=width, stretch=False, anchor="w")
        self._tree.update_idletasks()

    def _apply_tree_column_definitions(self, cols: List[str]) -> None:
        """Set Treeview column ids and headings; widths come from ``_autosize_tree_columns``."""
        self._tree.configure(columns=cols)
        for c in cols:
            self._tree.heading(c, text=self._column_heading_display(c))
            if c == _TABLE_ROW_INDEX_COL:
                self._tree.column(c, width=_TABLE_IDX_COL_WIDTH_MIN, stretch=False, anchor="e")
            else:
                self._tree.column(c, width=_TABLE_COL_WIDTH_MIN, stretch=False, anchor="w")

    def _populate_count_series_widgets(self) -> None:
        """Rebuild count-channel checkboxes from ``self._config``."""
        assert self._config is not None and self._count_series_frame is not None
        for w in self._count_series_frame.winfo_children():
            w.destroy()
        self._count_check_vars.clear()
        lbl_counts = ctk.CTkLabel(
            self._count_series_frame,
            text="Count series:",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        lbl_counts.pack(side="left", padx=(12, 4))
        attach_tooltip(lbl_counts, "Toggle which count channels are drawn for the current plot.")
        for name in self._config.count_names:
            var = tk.IntVar(value=1)
            self._count_check_vars[name] = var
            cb = ctk.CTkCheckBox(
                self._count_series_frame,
                text=name,
                variable=var,
                command=self._redraw_plot,
            )
            cb.pack(side="left", padx=4)
            attach_tooltip(cb, f"Show or hide the “{name}” trace on the plot.")

    def _clear_parse_caches_silently(self) -> None:
        self._compound_cache.clear()
        self._primary_variant_cache.clear()

    def _hydrate_index_compound(self, c: Optional[Compound]) -> Optional[Compound]:
        """For index DB rows, parse raw chromatogram text into data points; pass through full DB."""
        if c is None:
            return None
        if not self._index_db_mode:
            return c
        if c.data_points:
            return c
        assert self._data_store is not None and self._config is not None
        raw = self._data_store.get_raw_chromatogram(str(c.compound_id))
        if not raw:
            return None
        primary = str(c.primary_compound_id or "").strip()
        if not primary:
            primary, _ = split_compound_storage_id(str(c.compound_id))
        row_data: Dict[str, Any] = {
            self._config.compound_id_column: primary,
            self._config.chromatographic_data_column: raw,
        }
        if self._config.compound_variant_column:
            row_data[self._config.compound_variant_column] = (
                str(c.variant_label) if c.variant_label is not None else ""
            )
        for k, val in c.metadata.items():
            row_data[k] = val
        series = pd.Series(row_data)
        compound, _res = self._processor.parse_dataframe_row_to_compound(
            series, self._config, 0
        )
        return compound

    def _reload_compound_after_config_change(self, c: Compound) -> Optional[Compound]:
        """
        Re-load one compound using the current ``_config`` (index: re-parse from raw;
        full DB: re-fetch by id).
        """
        if self._index_db_mode:
            assert self._data_store is not None
            base = self._data_store.get_compound(str(c.compound_id).strip())
            if base is None:
                return None
            return self._hydrate_index_compound(base)

        assert self._data_store is not None
        if self._uses_variants:
            primary = str(c.primary_compound_id or "").strip() or split_compound_storage_id(
                str(c.compound_id)
            )[0]
            want_v = str(c.variant_label or "").strip()
            variants = self._data_store.get_compounds_for_primary(primary)
            if not variants:
                return None
            for comp in variants:
                if str(comp.variant_label or "").strip() == want_v:
                    return comp
            return variants[0] if len(variants) == 1 else None
        return self._data_store.get_compound(str(c.compound_id).strip())

    def refresh_after_configuration_changed(self) -> None:
        """
        Reload saved spreadsheet configuration and refresh compound IDs, table layout,
        count-series toggles, and loaded rows (re-parse on-demand or re-fetch from DB).
        """
        cfg = self.config_manager.load_default_config()
        if not cfg or not cfg.count_names:
            logger.warning("Configuration refresh skipped: no saved config or count names")
            return
        if not cfg.is_complete():
            logger.warning("Configuration refresh: saved config incomplete")

        self._config = cfg
        self._uses_variants = bool(cfg.compound_variant_column)
        self._pick_meta.clear()
        self._clear_plot_pick_focus_state()

        assert self._data_store is not None
        if self._index_db_mode:
            self._clear_parse_caches_silently()
        all_meta = list(cfg.selected_metadata_columns or [])
        self._searchable_metadata_columns, _miss = self._data_store.filter_metadata_columns_for_search(
            all_meta
        )
        if self._uses_variants:
            self._all_ids = self._data_store.get_distinct_primary_compound_ids()
        else:
            self._all_ids = sorted(self._data_store.get_all_compound_ids())

        self._populate_count_series_widgets()
        cols = self._table_column_names()
        self._apply_tree_column_definitions(cols)

        snapshot: List[Tuple[str, Compound]] = []
        for iid in self._tree.get_children():
            sid = str(iid)
            old = self._table_compounds_by_iid.get(sid)
            if old is not None:
                snapshot.append((sid, old))

        for iid in list(self._tree.get_children()):
            self._tree.delete(iid)
        self._table_compounds_by_iid.clear()

        lost = 0
        for _old_iid, old_c in snapshot:
            refreshed = self._reload_compound_after_config_change(old_c)
            if refreshed is None:
                lost += 1
                continue
            new_iid = str(refreshed.compound_id)
            if new_iid in self._table_compounds_by_iid:
                lost += 1
                continue
            row_index = len(self._table_compounds_by_iid) + 1
            self._table_compounds_by_iid[new_iid] = refreshed
            self._tree.insert("", "end", iid=new_iid, values=self._row_values(refreshed, row_index))

        self._autosize_tree_columns()
        self._current_compounds = []
        self._style_axes_empty()
        self._canvas.draw()

        n = len(self._table_compounds_by_iid)
        if lost:
            self._table_status.configure(
                text=(
                    f"Configuration updated: {n} compound(s) in table "
                    f"({lost} row(s) could not be remapped; reload from Compound list if needed)."
                )
            )
            logger.info("Configuration refresh: remapped %s row(s), dropped %s", n, lost)
        else:
            self._table_status.configure(
                text=f"Configuration updated: {n} compound(s) in table. Select rows to plot again.",
            )
            logger.info("Configuration refresh: %s compound(s) in table", n)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        header.grid_columnconfigure(0, weight=1)

        if self._index_db_mode:
            mode = "On-demand (index database)"
        else:
            mode = "Full SQLite database (pre-parsed)"
        ctk.CTkLabel(
            header,
            text=f"Chromatogram Visualizer — {mode}",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

    def _build_plot_area(self) -> None:
        plot_fr = ctk.CTkFrame(self, fg_color="transparent")
        plot_fr.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        plot_fr.grid_rowconfigure(0, weight=1)
        plot_fr.grid_columnconfigure(0, weight=1)

        self._plot_host = tk.Frame(plot_fr, bg="#2b2b2b")
        self._plot_host.grid(row=0, column=0, sticky="nsew")

        self._figure = Figure(figsize=(10, 4.5), dpi=100)
        self._figure.patch.set_facecolor("#2b2b2b")
        self._axes = self._figure.add_subplot(111)
        self._style_axes_empty()

        self._canvas = FigureCanvasTkAgg(self._figure, master=self._plot_host)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._toolbar = NavigationToolbar2Tk(self._canvas, self._plot_host)
        self._toolbar.update()

        self._canvas.mpl_connect("pick_event", self._on_plot_line_pick)
        self._canvas.mpl_connect("button_press_event", self._on_plot_background_click)

        hint = (
            "Open Compound list or Search, load the table, then select rows to plot. "
            "Click a trace to focus its table row (click again to clear selection and plot). "
            "Use the toolbar for pan and zoom."
        )
        ctk.CTkLabel(
            plot_fr,
            text=hint,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).grid(row=1, column=0, padx=4, pady=(4, 0), sticky="w")

    def _build_bottom_controls(self) -> None:
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
        bottom.grid_columnconfigure(1, weight=1)

        row0 = ctk.CTkFrame(bottom, fg_color="transparent")
        row0.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        btn_list = ctk.CTkButton(
            row0,
            text="Compound list…",
            width=130,
            command=self._open_compound_picker,
        )
        btn_list.pack(side="left", padx=(0, 6))
        attach_tooltip(
            btn_list,
            "Open a searchable list of compound IDs and add chosen rows to the table.",
        )

        btn_search = ctk.CTkButton(
            row0,
            text="Search…",
            width=100,
            command=self._open_metadata_search,
        )
        btn_search.pack(side="left", padx=(0, 6))
        attach_tooltip(
            btn_search,
            "Build a metadata query, run it against the database, and load matches into the table.",
        )

        btn_clear_table = ctk.CTkButton(
            row0,
            text="Clear table",
            width=100,
            fg_color="gray40",
            command=self._on_clear_table,
        )
        btn_clear_table.pack(side="left", padx=(0, 6))
        attach_tooltip(btn_clear_table, "Remove every row from the table and clear the plot.")

        btn_clear_plot = ctk.CTkButton(
            row0,
            text="Clear plot",
            width=100,
            fg_color="gray40",
            command=self._on_clear_plot_only,
        )
        btn_clear_plot.pack(side="left", padx=(0, 6))
        attach_tooltip(
            btn_clear_plot,
            "Clear plotted traces only. Table rows stay loaded; select rows again to replot.",
        )

        btn_export = ctk.CTkButton(
            row0,
            text="Export plot…",
            width=110,
            command=self._on_export_plot,
        )
        btn_export.pack(side="left", padx=(0, 12))
        attach_tooltip(
            btn_export,
            "Save the current plot to PNG, PDF, or SVG. At least one trace must be visible.",
        )

        self._count_series_frame = ctk.CTkFrame(row0, fg_color="transparent")
        self._count_series_frame.pack(side="left", fill="x", expand=True)
        self._populate_count_series_widgets()

    def _build_compound_table(self) -> None:
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 10))
        wrap.grid_rowconfigure(0, weight=0)
        wrap.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrap,
            text="Loaded compounds (select rows to plot)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        tbl_fr = tk.Frame(wrap, bg="#1e1e1e")
        tbl_fr.grid(row=1, column=0, sticky="nsew")
        tbl_fr.grid_rowconfigure(0, weight=1)
        tbl_fr.grid_columnconfigure(0, weight=1)

        cols = self._table_column_names()
        self._tree = ttk.Treeview(
            tbl_fr,
            columns=cols,
            show="headings",
            selectmode=tk.EXTENDED,
            height=10,
        )
        self._apply_tree_column_definitions(cols)
        self._tree.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(tbl_fr, orient="vertical", command=self._tree.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb = ttk.Scrollbar(tbl_fr, orient="horizontal", command=self._tree.xview)
        xsb.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self._apply_treeview_dark_style()
        self._autosize_tree_columns()
        self._tree.bind("<<TreeviewSelect>>", self._on_table_selection_changed)
        attach_tooltip(
            self._tree,
            "Select one or more rows to plot overlays. "
            "Ctrl+click toggles a row; Shift+click selects a range. "
            "Click a plot trace to focus its row.",
        )

        self._table_status = ctk.CTkLabel(wrap, text="No compounds in the table.", text_color="gray")
        self._table_status.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _apply_treeview_dark_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview",
            background="#2b2b2b",
            foreground="#e6e6e6",
            fieldbackground="#2b2b2b",
            rowheight=24,
        )
        style.configure("Treeview.Heading", background="#3d3d3d", foreground="#ffffff")
        style.map("Treeview", background=[("selected", "#1f538d")])

    def _table_column_names(self) -> List[str]:
        assert self._config is not None
        meta = list(self._searchable_metadata_columns[:_MAX_METADATA_COLUMNS_DISPLAY])
        if self._uses_variants:
            return [_TABLE_ROW_INDEX_COL, "library_id", "variant", *meta]
        return [_TABLE_ROW_INDEX_COL, "compound_id", *meta]

    def _row_values(self, c: Compound, row_index: int) -> tuple:
        cols = self._table_column_names()
        skip = {"compound_id", "library_id", "variant", _TABLE_ROW_INDEX_COL}
        meta_keys = [x for x in cols if x not in skip]
        if self._uses_variants:
            parts: List[str] = [
                str(row_index),
                str(c.primary_compound_id or "").strip(),
                str(c.variant_label or "").strip(),
            ]
        else:
            parts = [str(row_index), str(c.compound_id).strip()]
        for mk in meta_keys:
            v = c.metadata.get(mk, "")
            if v is None or (isinstance(v, float) and pd.isna(v)):
                parts.append("")
            else:
                parts.append(str(v)[:80])
        return tuple(parts)

    def _open_compound_picker(self) -> None:
        heading = "Primary compound IDs" if self._uses_variants else "Compound IDs"
        CompoundPickerDialog(
            self,
            title="Compound list",
            list_heading=heading,
            all_ids=self._all_ids,
            on_done=self._on_compound_picker_done,
        )

    def _on_compound_picker_done(self, keys: Optional[List[str]]) -> None:
        if not keys:
            return
        if len(keys) > _MAX_PROCEED_KEYS:
            keys = keys[:_MAX_PROCEED_KEYS]
            messagebox.showwarning(
                "Compound list",
                f"Only the first {_MAX_PROCEED_KEYS} selected IDs were loaded.",
                parent=self,
            )
        compounds = self._load_compounds_for_keys(keys)
        if not compounds:
            messagebox.showerror("Compound list", "Could not load selected compound(s).", parent=self)
            return
        self._append_compounds_to_table(compounds, replace=False)

    def _open_metadata_search(self) -> None:
        if self._data_store is None or self._config is None:
            return
        MetadataSearchDialog(
            self,
            config=self._config,
            data_store=self._data_store,
            searchable_metadata_columns=self._searchable_metadata_columns,
            on_done=self._on_metadata_search_done,
        )

    def _on_metadata_search_done(self, ids: Optional[List[str]]) -> None:
        if not ids or self._data_store is None:
            return
        loaded: List[Compound] = []
        for cid in ids:
            c = self._data_store.get_compound(cid)
            if c is None:
                continue
            h = self._hydrate_index_compound(c)
            if h is not None:
                loaded.append(h)
        if not loaded:
            messagebox.showerror("Search", "No compounds could be loaded for this query.", parent=self)
            return
        self._append_compounds_to_table(loaded, replace=True)

    def _load_compounds_for_keys(self, keys: List[str]) -> List[Compound]:
        out: List[Compound] = []
        assert self._data_store is not None
        for key in keys:
            if self._uses_variants:
                for c in self._data_store.get_compounds_for_primary(key):
                    h = self._hydrate_index_compound(c)
                    if h is not None:
                        out.append(h)
            else:
                c = self._data_store.get_compound(key)
                h = self._hydrate_index_compound(c)
                if h is not None:
                    out.append(h)
        return out

    def _append_compounds_to_table(self, compounds: List[Compound], *, replace: bool) -> None:
        if replace:
            for iid in list(self._tree.get_children()):
                self._tree.delete(iid)
            self._table_compounds_by_iid.clear()

        added = 0
        for c in compounds:
            iid = str(c.compound_id)
            if iid in self._table_compounds_by_iid:
                continue
            row_index = len(self._table_compounds_by_iid) + 1
            self._table_compounds_by_iid[iid] = c
            self._tree.insert("", "end", iid=iid, values=self._row_values(c, row_index))
            added += 1

        n = len(self._table_compounds_by_iid)
        action = "Replaced table with" if replace else "Added"
        self._table_status.configure(text=f"{action} {added} row(s); {n} compound(s) in table.")
        self._autosize_tree_columns()

    def _on_clear_table(self) -> None:
        self._cancel_deferred_selection_plot()
        self._clear_tree_selection_without_plot()
        self._clear_plot_pick_focus_state()
        for iid in list(self._tree.get_children()):
            self._tree.delete(iid)
        self._table_compounds_by_iid.clear()
        self._clear_plot_display()
        self._autosize_tree_columns()
        self._table_status.configure(text="Table cleared.")

    def _on_clear_plot_only(self) -> None:
        """Clear only the plotted traces; keep loaded table rows untouched."""
        self._clear_plot_display()

    def _cancel_deferred_selection_plot(self) -> None:
        if self._selection_plot_after_id is not None:
            try:
                self.after_cancel(self._selection_plot_after_id)
            except ValueError:
                pass
            self._selection_plot_after_id = None

    def _with_suppressed_table_selection_plot(self, callback: Any, *args: Any) -> Any:
        """Run a tree selection mutation without triggering auto-plot."""
        self._suppress_table_selection_plot = True
        try:
            return callback(*args)
        finally:
            self._suppress_table_selection_plot = False

    def _clear_tree_selection_without_plot(self) -> None:
        """Deselect all table rows without scheduling a selection-driven redraw."""
        selected = self._tree.selection()
        if not selected:
            return

        def _remove_all() -> None:
            for iid in selected:
                self._tree.selection_remove(iid)

        self._with_suppressed_table_selection_plot(_remove_all)

    def _on_table_selection_changed(self, _event: Optional[tk.Event] = None) -> None:
        """Redraw or clear the plot when the user changes table row selection."""
        if self._suppress_table_selection_plot:
            return
        self._cancel_deferred_selection_plot()
        self._selection_plot_after_id = self.after_idle(self._deferred_apply_plot_from_table_selection)

    def _deferred_apply_plot_from_table_selection(self) -> None:
        self._selection_plot_after_id = None
        self._apply_plot_from_table_selection()

    def _clear_plot_display(self) -> None:
        """Remove all traces from the axes and reset plotted compound state."""
        self._pick_meta.clear()
        self._legend_text_meta.clear()
        self._clear_plot_pick_focus_state()
        self._current_compounds = []
        self._style_axes_empty()
        self._canvas.draw()

    def _compounds_for_tree_selection(self) -> List[Compound]:
        compounds: List[Compound] = []
        for iid in self._tree.selection():
            c = self._table_compounds_by_iid.get(str(iid))
            if c is None:
                continue
            if self._index_db_mode and not c.data_points:
                c = self._hydrate_index_compound(c)
            if c is not None:
                compounds.append(c)
        return compounds

    def _apply_plot_from_table_selection(self) -> None:
        sel = self._tree.selection()
        if not sel:
            self._clear_plot_display()
            return
        compounds = self._compounds_for_tree_selection()
        if not compounds:
            self._clear_plot_display()
            return
        self._current_compounds = compounds
        self._redraw_plot()

    def _plot_has_exportable_content(self) -> bool:
        """True when the axes show at least one data trace (not the empty-state hint)."""
        return bool(self._axes.get_lines())

    def _on_export_plot(self) -> None:
        """Save the current matplotlib figure to PNG, PDF, or SVG."""
        if not self._plot_has_exportable_content():
            messagebox.showinfo(
                "Export plot",
                "There is nothing to export. Select table rows to plot traces first.",
                parent=self,
            )
            return

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export plot",
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("PDF document", "*.pdf"),
                ("SVG vector image", "*.svg"),
            ],
        )
        if not path:
            return

        out = Path(path)
        try:
            self._figure.savefig(
                out,
                dpi=150,
                bbox_inches="tight",
                facecolor=self._figure.get_facecolor(),
                edgecolor="none",
            )
        except OSError as exc:
            logger.exception("Plot export failed: %s", out)
            messagebox.showerror(
                "Export plot",
                f"Could not save the plot:\n{exc}",
                parent=self,
            )
            return

        messagebox.showinfo("Export plot", f"Plot saved to:\n{out}", parent=self)
        logger.info("Exported chromatogram plot to %s", out)

    def _selected_count_names(self) -> List[str]:
        names: List[str] = []
        for name, var in self._count_check_vars.items():
            if var.get():
                names.append(name)
        return names

    def _style_axes_empty(self) -> None:
        ax = self._axes
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="lightgray")
        ax.xaxis.label.set_color("lightgray")
        ax.yaxis.label.set_color("lightgray")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_color("gray")
        ax.text(
            0.5,
            0.5,
            "Add compounds via Compound list or Search,\nthen select table rows to plot.",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="gray",
            fontsize=12,
        )
        ax.set_xticks([])
        ax.set_yticks([])

    def _on_plot_line_pick(self, event: PickEvent) -> None:
        """Highlight the picked series on the axes and select the matching table row."""
        me = event.mouseevent
        if me is None or me.button != 1 or me.inaxes != self._axes:
            return
        artist = event.artist
        if not isinstance(artist, Line2D):
            return
        meta = self._pick_meta.get(id(artist))
        if not meta:
            return
        iid, count_name = meta
        if self._plot_pick_table_iid == iid and self._plot_pick_count_name == count_name:
            self._plot_pick_table_iid = None
            self._plot_pick_count_name = None
            self._clear_tree_selection_without_plot()
            self._clear_plot_display()
        else:
            self._plot_pick_table_iid = iid
            self._plot_pick_count_name = count_name
            self._focus_table_row_for_plot_pick(iid)
        self._apply_plot_line_focus_styling()
        self._canvas.draw_idle()

    def _on_plot_background_click(self, event: MouseEvent) -> None:
        """
        Clear highlight when user clicks inside plot area but not on a trace.
        """
        if event.button != 1 or event.inaxes != self._axes:
            return
        for line in self._axes.get_lines():
            hit, _details = line.contains(event)
            if hit:
                return
        if not self._plot_pick_table_iid and not self._plot_pick_count_name:
            return
        self._clear_plot_pick_focus_state()
        self._clear_tree_selection_without_plot()
        self._clear_plot_display()

    def _focus_table_row_for_plot_pick(self, iid: str) -> None:
        if iid not in self._table_compounds_by_iid:
            return
        self._tree.selection_set(iid)
        self._tree.see(iid)
        self._tree.focus(iid)

    def _apply_plot_line_focus_styling(self) -> None:
        """Emphasize focused line and legend text; restore defaults when nothing focused."""
        ax = self._axes
        focus_iid = self._plot_pick_table_iid
        focus_count = self._plot_pick_count_name
        for line in ax.get_lines():
            base = getattr(line, "_lcseq_base", None)
            if not base:
                continue
            meta = self._pick_meta.get(id(line))
            if not focus_iid or not focus_count:
                line.set_color(base["color"])
                line.set_linewidth(base["lw"])
                line.set_alpha(1.0)
                continue
            if meta and meta[0] == focus_iid and meta[1] == focus_count:
                line.set_color(_PLOT_FOCUS_LINE_COLOR)
                line.set_linewidth(max(base["lw"] * 1.55, 1.9))
                line.set_alpha(1.0)
            else:
                line.set_color(base["color"])
                line.set_linewidth(base["lw"])
                line.set_alpha(1.0)

        legend = self._axes.get_legend()
        for text_obj in legend.get_texts() if legend else []:
            meta = self._legend_text_meta.get(id(text_obj))
            text_obj.set_fontweight("normal")
            text_obj.set_color("lightgray")
            if focus_iid and focus_count and meta and meta[0] == focus_iid and meta[1] == focus_count:
                text_obj.set_color(_PLOT_FOCUS_LINE_COLOR)
                text_obj.set_fontweight("bold")

    def _sync_plot_pick_after_redraw(self) -> None:
        """Drop pick focus if that series is no longer plotted (e.g. count toggles changed)."""
        if not self._plot_pick_table_iid or not self._plot_pick_count_name:
            return
        target = (self._plot_pick_table_iid, self._plot_pick_count_name)
        if any(m == target for m in self._pick_meta.values()):
            return
        self._plot_pick_table_iid = None
        self._plot_pick_count_name = None

    def _clear_plot_pick_focus_state(self) -> None:
        """Forget plot click-highlight (no table selection change)."""
        self._plot_pick_table_iid = None
        self._plot_pick_count_name = None

    def _redraw_plot(self) -> None:
        ax = self._axes
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="lightgray")
        ax.xaxis.label.set_color("lightgray")
        ax.yaxis.label.set_color("lightgray")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_color("gray")

        compounds = [c for c in self._current_compounds if c is not None]
        if not compounds or not any(c.data_points for c in compounds):
            self._pick_meta.clear()
            self._legend_text_meta.clear()
            self._clear_plot_pick_focus_state()
            self._style_axes_empty()
            self._canvas.draw()
            return

        names = self._selected_count_names()
        if not names:
            ax.text(
                0.5,
                0.5,
                "Enable at least one count series",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color="orange",
                fontsize=12,
            )
            self._pick_meta.clear()
            self._legend_text_meta.clear()
            self._clear_plot_pick_focus_state()
            self._canvas.draw()
            return

        self._pick_meta.clear()
        self._legend_text_meta.clear()
        legend_meta_in_order: List[Tuple[str, str]] = []
        colors = ("#58a6ff", "#3fb950", "#d2a8ff", "#ffa657", "#79c0ff", "#ff7b72")
        plotted = 0
        idx = 0
        default_lw = 1.2
        for compound in compounds:
            if not compound.data_points:
                continue
            available = set(compound.get_count_names())
            vlabel = compound.variant_label or "(none)"
            for count_name in names:
                if count_name not in available:
                    continue
                try:
                    times, counts = compound.get_time_series(count_name)
                except ValueError:
                    continue
                if not times:
                    continue
                color = colors[idx % len(colors)]
                lib_id = str(compound.primary_compound_id or compound.compound_id or "").strip()
                if not lib_id:
                    lib_id = "(unknown)"
                if self._uses_variants:
                    legend_label = f"{lib_id} — {vlabel} — {count_name}"
                else:
                    legend_label = f"{lib_id} — {count_name}"
                (line,) = ax.plot(
                    times,
                    counts,
                    label=legend_label,
                    color=color,
                    linewidth=default_lw,
                )
                line.set_picker(_PLOT_LINE_PICK_RADIUS_PT)
                line._lcseq_base = {"color": color, "lw": default_lw}
                table_iid = str(compound.compound_id).strip()
                self._pick_meta[id(line)] = (table_iid, count_name)
                legend_meta_in_order.append((table_iid, count_name))
                plotted += 1
                idx += 1

        if plotted == 0:
            self._clear_plot_pick_focus_state()
            self._legend_text_meta.clear()
            ax.text(
                0.5,
                0.5,
                "No data for selected series",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color="orange",
                fontsize=12,
            )
        else:
            ax.set_xlabel("Time")
            ax.set_ylabel("Count")
            title_primary = compounds[0].primary_compound_id or compounds[0].compound_id
            ax.set_title(f"Chromatogram — {title_primary}")
            legend = ax.legend(facecolor="#2b2b2b", edgecolor="gray", labelcolor="lightgray")
            if legend is not None:
                texts: List[Text] = legend.get_texts()
                for text_obj, meta in zip(texts, legend_meta_in_order):
                    self._legend_text_meta[id(text_obj)] = meta
            ax.grid(True, alpha=0.25, color="gray")
            self._sync_plot_pick_after_redraw()
            self._apply_plot_line_focus_styling()

        self._figure.tight_layout()
        self._canvas.draw()

    def on_close(self) -> None:
        if self._data_store is not None:
            try:
                self._data_store.close()
            except Exception as exc:
                logger.warning("Error closing data store: %s", exc)
            self._data_store = None
        self._compound_cache.clear()
        self._primary_variant_cache.clear()
        logger.info("Chromatogram visualizer closed")
        super().on_close()
