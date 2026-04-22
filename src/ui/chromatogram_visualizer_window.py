# src/ui/chromatogram_visualizer_window.py
"""
Chromatogram visualizer: Count vs Time plotting (Phase 10) and metadata search (Phase 11).
"""

import logging
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from typing import Any, List, Optional, Tuple

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from tkinter import messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.metadata_search import (
    append_results_text_filter,
    build_where_clause,
    sanitize_sql_column,
    validate_conditions,
)
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.query_builder_panel import QueryBuilderPanel
from src.ui.virtual_metadata_results import VirtualMetadataResultList

logger = logging.getLogger(__name__)

_MAX_LIST_DISPLAY = 5000
_MAX_PARSE_CACHE = 32
_COMPACT_TOGGLE_HEIGHT = 54


class ChromatogramVisualizerWindow(BaseWindow):
    """
    Window for viewing chromatograms: Count vs Time with zoom/pan and series toggles.

    Uses a bulk SQLite database when one is active; otherwise parses spreadsheet rows
    on demand for the selected compound.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
        loader: SpreadsheetLoader,
    ) -> None:
        """
        Args:
            parent: Main application window
            app_state: Current application state
            config_manager: Used to load SpreadsheetConfig (count names)
            loader: Loaded spreadsheet data (required for on-demand parsing)
        """
        super().__init__(parent, title="Chromatogram Visualizer")
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
        self._variant_check_vars: dict[str, tk.IntVar] = {}
        self._on_demand_mode = False
        self._compound_cache: "OrderedDict[str, Compound]" = OrderedDict()
        self._primary_variant_cache: "OrderedDict[str, List[Compound]]" = OrderedDict()
        self._processor = DataProcessor()
        self._active_search_where: Optional[str] = None
        self._active_search_params: List[Any] = []
        self._result_filter_debounce: Optional[str] = None
        self._query_panel: Optional[QueryBuilderPanel] = None
        self._virtual_results: Optional[VirtualMetadataResultList] = None
        self._search_status: Optional[ctk.CTkLabel] = None
        self._result_filter_var: Optional[tk.StringVar] = None
        self._browse_column_frame: Optional[ctk.CTkFrame] = None
        self._search_column_frame: Optional[ctk.CTkFrame] = None
        self._nav_list_btn: Optional[ctk.CTkButton] = None
        self._nav_search_btn: Optional[ctk.CTkButton] = None

        self.geometry("1600x980")
        self.center_window(1600, 980)
        self.minsize(1200, 700)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._content_panes = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            showhandle=False,
            bd=0,
            bg="#4a4a4a",
        )
        self._content_panes.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self._left_panel = ctk.CTkFrame(self._content_panes)
        self._middle_panel = ctk.CTkFrame(self._content_panes)
        self._right_panel = ctk.CTkFrame(self._content_panes)
        self._content_panes.add(self._left_panel, minsize=220, stretch="always")
        self._content_panes.add(self._middle_panel, minsize=240, stretch="always")
        self._content_panes.add(self._right_panel, minsize=420, stretch="always")
        self.after(120, self._set_initial_pane_sizes)

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
        if db_path and Path(db_path).is_file():
            self._on_demand_mode = False
            try:
                self._data_store = DataStore(db_path=Path(db_path), use_memory=False)
            except Exception as exc:
                logger.error("Failed to open database: %s", exc, exc_info=True)
                messagebox.showerror("Database error", str(exc), parent=self)
                self.after(50, self.on_close)
                return
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
        else:
            self._on_demand_mode = True
            self._data_store = None
            df = self._loader.current_data
            if df is None or self._config.compound_id_column not in df.columns:
                messagebox.showerror(
                    "Spreadsheet data",
                    "No in-memory spreadsheet data or compound ID column is missing.",
                    parent=self,
                )
                self.after(50, self.on_close)
                return
            self._all_ids = self._compound_ids_from_dataframe(df)
            if not self._all_ids:
                messagebox.showwarning(
                    "No compounds",
                    "No compound IDs found in the configured column.",
                    parent=self,
                )

        self._build_header()
        self._build_controls_column()
        self._build_compound_list_column()
        self._build_plot_column()

        logger.info(
            "Chromatogram visualizer opened (%s compounds, on_demand=%s)",
            len(self._all_ids),
            self._on_demand_mode,
        )

    def _clear_main_reference(self, event: tk.Event) -> None:
        """Drop reference on main screen when this window is destroyed."""
        if event.widget != self:
            return
        main = self.parent
        if main is not None and getattr(main, "_chromatogram_window", None) is self:
            main._chromatogram_window = None

    def _resolve_database_path(self) -> Optional[str]:
        """Return active bulk database path only if the file exists."""
        if self.app_state.database_path and Path(self.app_state.database_path).is_file():
            return self.app_state.database_path
        return None

    def _compound_ids_from_dataframe(self, df: pd.DataFrame) -> List[str]:
        """Unique primary compound IDs in first-seen spreadsheet order."""
        col = self._config.compound_id_column
        out: List[str] = []
        seen: set[str] = set()
        for val in df[col]:
            if pd.isna(val):
                continue
            s = str(val).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    def _build_header(self) -> None:
        """Top bar with title and Back."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        header.grid_columnconfigure(0, weight=1)

        mode = (
            "On-demand parsing (no bulk database)"
            if self._on_demand_mode
            else "Bulk SQLite database"
        )
        title = ctk.CTkLabel(
            header,
            text=f"Chromatogram Visualizer — {mode}",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        back_btn = ctk.CTkButton(
            header,
            text="Back to main",
            width=120,
            command=self.on_close,
        )
        back_btn.grid(row=0, column=1, sticky="e")

    def _build_controls_column(self) -> None:
        """Left column: actions + count/isoform toggles."""
        left = self._left_panel
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Controls", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=8, pady=(8, 6), sticky="w"
        )

        r = 1
        if self._on_demand_mode:
            self._process_row_btn = ctk.CTkButton(
                left,
                text="Process data",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=self._on_process_data_clicked,
            )
            self._process_row_btn.grid(row=r, column=0, padx=8, pady=(4, 4), sticky="ew")
            r += 1
            self._clear_cache_btn = ctk.CTkButton(
                left,
                text="Clear memory cache",
                fg_color="gray40",
                hover_color="gray25",
                command=self._on_clear_memory_cache,
            )
            self._clear_cache_btn.grid(row=r, column=0, padx=8, pady=(0, 8), sticky="ew")
            r += 1

        count_heading = "Count series"
        if self._uses_variants and len(self._config.count_names) > 1:
            count_heading = "Count series (each × variant when plotted)"
        ctk.CTkLabel(left, text=count_heading, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=r, column=0, padx=8, pady=(12, 4), sticky="w"
        )
        r += 1

        # Keep count toggles compact so compound search/list remains visible.
        series_frame = ctk.CTkScrollableFrame(left, height=_COMPACT_TOGGLE_HEIGHT)
        series_frame.grid(row=r, column=0, padx=8, pady=(0, 8), sticky="ew")

        assert self._config is not None
        for name in self._config.count_names:
            var = tk.IntVar(value=1)
            self._count_check_vars[name] = var
            cb = ctk.CTkCheckBox(
                series_frame,
                text=name,
                variable=var,
                command=self._redraw_plot,
            )
            cb.pack(anchor="w", padx=4, pady=2)
        r += 1

        if self._uses_variants:
            ctk.CTkLabel(
                left,
                text="Isoforms / variants",
                font=ctk.CTkFont(size=13, weight="bold"),
            ).grid(row=r, column=0, padx=8, pady=(8, 4), sticky="w")
            r += 1
            # Keep isoform toggles compact; users can scroll for additional variants.
            self._variant_series_frame = ctk.CTkScrollableFrame(
                left, height=_COMPACT_TOGGLE_HEIGHT
            )
            self._variant_series_frame.grid(row=r, column=0, padx=8, pady=(0, 8), sticky="ew")

    def _build_compound_list_column(self) -> None:
        """Middle column: compound list; optional Search tab only when a bulk DB is active."""
        middle = self._middle_panel
        middle.grid_columnconfigure(0, weight=1)

        # On-demand mode has no SQL search — a single tab labeled "Browse" looked like a broken
        # button (re-selecting the current tab does nothing). Embed the list directly.
        if self._on_demand_mode:
            middle.grid_rowconfigure(0, weight=1)
            self._browse_column_frame = None
            self._search_column_frame = None
            self._nav_list_btn = None
            self._nav_search_btn = None
            self._build_browse_compound_ui(middle)
            return

        # CTkTabview inside a PanedWindow often gets zero-height content on Windows;
        # use explicit nav buttons + two frames instead.
        middle.grid_rowconfigure(0, weight=0)
        middle.grid_rowconfigure(1, weight=1)

        nav = ctk.CTkFrame(middle, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))

        self._browse_column_frame = ctk.CTkFrame(middle, fg_color="transparent")
        self._search_column_frame = ctk.CTkFrame(middle, fg_color="transparent")
        self._browse_column_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._search_column_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._search_column_frame.grid_remove()

        self._nav_list_btn = ctk.CTkButton(
            nav,
            text="Compound list",
            width=130,
            command=lambda: self._set_middle_compound_view("list"),
        )
        self._nav_search_btn = ctk.CTkButton(
            nav,
            text="Search",
            width=100,
            command=lambda: self._set_middle_compound_view("search"),
        )
        self._nav_list_btn.pack(side="left", padx=(0, 6))
        self._nav_search_btn.pack(side="left")

        self._build_browse_compound_ui(self._browse_column_frame)
        self._build_search_tab(self._search_column_frame)
        self._set_middle_compound_view("list")

    def _set_middle_compound_view(self, mode: str) -> None:
        """Toggle compound list vs SQL search (database mode only)."""
        if self._browse_column_frame is None or self._search_column_frame is None:
            return
        if self._nav_list_btn is None or self._nav_search_btn is None:
            return
        selected = ("#1f538d", "#14375e")
        idle = ("gray70", "gray35")
        if mode == "search":
            self._browse_column_frame.grid_remove()
            self._search_column_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
            self._nav_list_btn.configure(fg_color=idle)
            self._nav_search_btn.configure(fg_color=selected)
        else:
            self._search_column_frame.grid_remove()
            self._browse_column_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
            self._nav_list_btn.configure(fg_color=selected)
            self._nav_search_btn.configure(fg_color=idle)

    def _build_browse_compound_ui(self, parent: ctk.CTkFrame) -> None:
        """Compound list + text filter (spreadsheet or full DB browse)."""
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        list_title = "Compound (primary ID)" if self._uses_variants else "Compound ID"
        ctk.CTkLabel(
            parent,
            text=list_title,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=8, pady=(8, 4), sticky="w")

        self._filter_var = tk.StringVar(value="")
        filter_entry = ctk.CTkEntry(
            parent,
            placeholder_text="Filter compounds…",
            textvariable=self._filter_var,
        )
        filter_entry.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        filter_entry.bind("<KeyRelease>", lambda _e: self._apply_compound_filter())

        list_frame = ctk.CTkFrame(parent)
        list_frame.grid(row=2, column=0, padx=8, pady=4, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._compound_listbox = tk.Listbox(
            list_frame,
            height=30,
            exportselection=False,
            activestyle="dotbox",
        )
        self._compound_listbox.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self._compound_listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._compound_listbox.configure(yscrollcommand=sb.set)
        self._compound_listbox.bind("<<ListboxSelect>>", self._on_compound_list_select)

        self._list_status = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=11), text_color="gray"
        )
        self._list_status.grid(row=3, column=0, padx=8, pady=(4, 6), sticky="w")

        self._apply_compound_filter()

    def _build_search_tab(self, parent: ctk.CTkFrame) -> None:
        """Metadata query builder and virtual results (bulk database mode only)."""
        assert self._config is not None
        parent.grid_rowconfigure(4, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            parent,
            text="Search compounds (SQLite)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=8, pady=(8, 4), sticky="w")

        meta = list(self._config.selected_metadata_columns or [])
        self._query_panel = QueryBuilderPanel(
            parent,
            metadata_fields=meta,
            on_search=self._on_query_search_clicked,
            on_clear=self._on_query_clear_clicked,
        )
        self._query_panel.grid(row=1, column=0, sticky="ew", padx=4, pady=4)

        self._result_filter_var = tk.StringVar(value="")
        rf = ctk.CTkEntry(
            parent,
            placeholder_text="Filter results (matches ID or any metadata text)…",
            textvariable=self._result_filter_var,
        )
        rf.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
        rf.bind("<KeyRelease>", lambda _e: self._schedule_result_filter_refresh())

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        ctk.CTkButton(actions, text="Select all results", width=130, command=self._on_search_select_all).pack(
            side="left", padx=4
        )
        ctk.CTkButton(
            actions, text="Select none", width=90, fg_color="gray40", command=self._on_search_select_none
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            actions,
            text="Load selected into plot",
            width=160,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_load_search_selection_into_plot,
        ).pack(side="left", padx=4)

        cols = self._search_result_column_headers()
        self._virtual_results = VirtualMetadataResultList(parent, columns=cols, height=220)
        self._virtual_results.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)

        self._search_status = ctk.CTkLabel(
            parent, text="Run a search to see matches.", font=ctk.CTkFont(size=11), text_color="gray"
        )
        self._search_status.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="w")

    def _search_result_column_headers(self) -> List[str]:
        """Column headers for the virtual results table."""
        assert self._config is not None
        meta = list(self._config.selected_metadata_columns or [])
        if self._uses_variants:
            return ["primary_compound_id", "compound_variant", *meta]
        return ["compound_id", *meta]

    def _compute_search_where(self) -> Tuple[str, List[Any]]:
        """Build WHERE clause from the query panel plus optional results text filter."""
        assert self._config is not None
        assert self._query_panel is not None
        conditions = self._query_panel.get_conditions()
        combiners = self._query_panel.get_combiners()
        while len(combiners) < max(0, len(conditions) - 1):
            combiners.append("AND")
        where_sql, params = build_where_clause(conditions, combiners)
        needle = (self._result_filter_var.get() if self._result_filter_var else "").strip()
        meta_safe = [sanitize_sql_column(c) for c in self._config.selected_metadata_columns]
        or_cols = ["compound_id", *meta_safe]
        where_sql, params = append_results_text_filter(where_sql, list(params), needle, or_cols)
        return where_sql, params

    def _on_query_search_clicked(self) -> None:
        """Validate, execute search, populate virtual list."""
        assert self._config is not None
        assert self._data_store is not None
        assert self._query_panel is not None
        assert self._virtual_results is not None
        assert self._search_status is not None

        conditions = self._query_panel.get_conditions()
        allowed = self._config.selected_metadata_columns or []
        errs = validate_conditions(conditions, allowed)
        if errs:
            messagebox.showerror("Search", "\n".join(errs), parent=self)
            return
        try:
            where_sql, params = self._compute_search_where()
        except ValueError as exc:
            messagebox.showerror("Search", str(exc), parent=self)
            return

        self._active_search_where = where_sql
        self._active_search_params = list(params)
        total = self._data_store.count_compounds_where(where_sql, params)
        if total == 0:
            self._search_status.configure(text="No matches for this query.")
            self._virtual_results.clear_results()
            return

        display_cols = list(self._config.selected_metadata_columns or [])

        def fetch_page(offset: int, limit: int) -> List[dict]:
            rows, _t = self._data_store.search_compounds_page(
                display_cols,
                where_sql,
                tuple(params),
                limit,
                offset,
            )
            return rows

        self._virtual_results.set_columns(self._search_result_column_headers())
        self._virtual_results.set_query(total, fetch_page)
        self._search_status.configure(text=f"{total} match(es). Scroll to load more rows.")

    def _on_query_clear_clicked(self) -> None:
        """Reset search results pane (query panel clears itself)."""
        self._active_search_where = None
        self._active_search_params = []
        if self._virtual_results is not None:
            self._virtual_results.clear_results()
        if self._search_status is not None:
            self._search_status.configure(text="Run a search to see matches.")

    def _schedule_result_filter_refresh(self) -> None:
        """Debounce secondary filter while typing."""
        if self._active_search_where is None:
            return
        if self._result_filter_debounce is not None:
            try:
                self.after_cancel(self._result_filter_debounce)
            except Exception:
                pass
        self._result_filter_debounce = self.after(400, self._apply_result_filter_refresh)

    def _apply_result_filter_refresh(self) -> None:
        self._result_filter_debounce = None
        if self._active_search_where is None or self._data_store is None:
            return
        if self._query_panel is None or self._virtual_results is None or self._search_status is None:
            return
        conditions = self._query_panel.get_conditions()
        allowed = self._config.selected_metadata_columns or []  # type: ignore[union-attr]
        errs_rf = validate_conditions(conditions, allowed)
        if errs_rf:
            return
        try:
            where_sql, params = self._compute_search_where()
        except ValueError:
            return
        self._active_search_where = where_sql
        self._active_search_params = list(params)
        total = self._data_store.count_compounds_where(where_sql, params)
        display_cols = list(self._config.selected_metadata_columns or [])

        def fetch_page(offset: int, limit: int) -> List[dict]:
            rows, _t = self._data_store.search_compounds_page(
                display_cols,
                where_sql,
                tuple(params),
                limit,
                offset,
            )
            return rows

        self._virtual_results.set_query(total, fetch_page)
        self._search_status.configure(text=f"{total} match(es) after result filter.")

    def _on_search_select_all(self) -> None:
        """Select every compound_id returned by the active query (capped)."""
        if self._data_store is None or self._active_search_where is None:
            messagebox.showinfo("Search", "Run a search first.", parent=self)
            return
        assert self._virtual_results is not None
        total = self._data_store.count_compounds_where(
            self._active_search_where, self._active_search_params
        )
        cap = VirtualMetadataResultList.max_select_all()
        if total > cap:
            messagebox.showwarning(
                "Search",
                f"Your query matches {total} rows, which exceeds the select-all limit "
                f"of {cap}. Narrow the query before using Select all results.",
                parent=self,
            )
            return
        ids = self._data_store.list_compound_ids_where(
            self._active_search_where, self._active_search_params
        )
        self._virtual_results.select_all_ids(ids)
        if self._search_status is not None:
            self._search_status.configure(text=f"Selected all {len(ids)} result(s).")

    def _on_search_select_none(self) -> None:
        if self._virtual_results is not None:
            self._virtual_results.select_none()
        if self._search_status is not None:
            self._search_status.configure(text="Selection cleared.")

    def _on_load_search_selection_into_plot(self) -> None:
        """Load checked search hits into the chromatogram plot."""
        if self._data_store is None:
            return
        assert self._virtual_results is not None
        ids = self._virtual_results.get_selected_compound_ids()
        if not ids:
            messagebox.showinfo("Plot", "Select one or more results (checkboxes) first.", parent=self)
            return
        if len(ids) > 200:
            ids = ids[:200]
            messagebox.showwarning(
                "Plot",
                "Too many compounds selected; only the first 200 will be loaded.",
                parent=self,
            )

        loaded: List[Compound] = []
        for cid in ids:
            c = self._data_store.get_compound(cid)
            if c is not None:
                loaded.append(c)
        if not loaded:
            messagebox.showerror("Plot", "Could not load selected compound(s).", parent=self)
            return
        self._current_compounds = loaded
        self._refresh_variant_toggles()
        self._redraw_plot()

    def _on_process_data_clicked(self) -> None:
        """Parse selected spreadsheet row(s) into Compound(s) (on-demand)."""
        if not self._on_demand_mode:
            return
        sel = self._compound_listbox.curselection()
        if not sel:
            messagebox.showinfo("Process data", "Select a compound first.", parent=self)
            return
        primary_id = self._compound_listbox.get(sel[0])
        df = self._loader.current_data
        assert self._config is not None and df is not None

        if self._uses_variants:
            compounds = self._parse_all_rows_for_primary(primary_id)
            if not compounds:
                messagebox.showerror(
                    "Process data",
                    f"No rows parsed for primary: {primary_id}",
                    parent=self,
                )
                self._current_compounds = []
                self._redraw_plot()
                return
            self._cache_put_primary(primary_id, compounds)
            self._current_compounds = compounds
            self._refresh_variant_toggles()
            self._redraw_plot()
            return

        col = self._config.compound_id_column
        mask = df[col].astype(str).str.strip() == primary_id
        idx_positions = [i for i, v in enumerate(mask.tolist()) if v]
        if not idx_positions:
            messagebox.showerror(
                "Process data",
                f"No row found for compound ID: {primary_id}",
                parent=self,
            )
            return
        iloc_pos = int(idx_positions[0])
        row = df.iloc[iloc_pos]
        row_number = iloc_pos + 2

        compound, result = self._processor.parse_dataframe_row_to_compound(
            row, self._config, row_number
        )
        if compound is None:
            errs = result.errors[:5]
            detail = "\n".join(f"Row {e.row_number}: {e.error_message}" for e in errs) if errs else "Unknown error"
            messagebox.showerror("Process data", f"Could not parse compound.\n\n{detail}", parent=self)
            self._current_compounds = []
            self._redraw_plot()
            return

        self._cache_put(primary_id, compound)
        self._current_compounds = [compound]
        self._refresh_variant_toggles()
        self._redraw_plot()

    def _cache_put(self, compound_id: str, compound: Compound) -> None:
        """Insert into LRU-ordered cache with size cap."""
        if compound_id in self._compound_cache:
            self._compound_cache.move_to_end(compound_id)
        self._compound_cache[compound_id] = compound
        while len(self._compound_cache) > _MAX_PARSE_CACHE:
            self._compound_cache.popitem(last=False)

    def _cache_put_primary(self, primary_id: str, compounds: List[Compound]) -> None:
        """LRU cache for all variants of one primary (on-demand mode)."""
        if primary_id in self._primary_variant_cache:
            self._primary_variant_cache.move_to_end(primary_id)
        self._primary_variant_cache[primary_id] = compounds
        while len(self._primary_variant_cache) > _MAX_PARSE_CACHE:
            self._primary_variant_cache.popitem(last=False)

    def _parse_all_rows_for_primary(self, primary_id: str) -> List[Compound]:
        """Parse every spreadsheet row whose primary compound ID matches."""
        df = self._loader.current_data
        assert self._config is not None and df is not None
        col = self._config.compound_id_column
        found: List[Compound] = []
        for iloc_pos in range(len(df)):
            row = df.iloc[iloc_pos]
            if str(row[col]).strip() != primary_id:
                continue
            compound, _result = self._processor.parse_dataframe_row_to_compound(
                row, self._config, iloc_pos + 2
            )
            if compound is not None:
                found.append(compound)
        found.sort(key=lambda c: (c.variant_label or "", c.compound_id))
        return found

    def _on_clear_memory_cache(self) -> None:
        self._compound_cache.clear()
        self._primary_variant_cache.clear()
        self._current_compounds = []
        self._redraw_plot()
        messagebox.showinfo("Memory cache", "Cleared parsed compounds from memory.", parent=self)

    def _build_plot_column(self) -> None:
        """Right column: matplotlib figure + navigation toolbar."""
        right = self._right_panel
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._plot_host = tk.Frame(right, bg="#2b2b2b")
        self._plot_host.grid(row=0, column=0, sticky="nsew")

        self._figure = Figure(figsize=(7, 5), dpi=100)
        self._figure.patch.set_facecolor("#2b2b2b")
        self._axes = self._figure.add_subplot(111)
        self._style_axes_empty()

        self._canvas = FigureCanvasTkAgg(self._figure, master=self._plot_host)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._toolbar = NavigationToolbar2Tk(self._canvas, self._plot_host)
        self._toolbar.update()

        if self._on_demand_mode:
            if self._uses_variants:
                hint_text = (
                    "Select a primary compound, click Process data to load all variants, "
                    "then toggle count series (each combines with every variant). "
                    "Use the toolbar for pan and zoom."
                )
            else:
                hint_text = (
                    "Select a compound, click Process data, then choose count series. "
                    "Use the toolbar for pan and zoom."
                )
        else:
            if self._uses_variants:
                hint_text = (
                    "Select a primary compound to coplot all variants. "
                    "Toggle count series — legend shows variant × count. Use the toolbar for pan and zoom."
                )
            else:
                hint_text = (
                    "Use the toolbar for pan and zoom. "
                    "Select a compound and count series to plot."
                )
        hint = ctk.CTkLabel(
            right,
            text=hint_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        hint.grid(row=1, column=0, padx=8, pady=(4, 8), sticky="w")

    def _set_initial_pane_sizes(self) -> None:
        """Initialize pane widths to ~17.5% / 17.5% / 65%."""
        try:
            total = max(self._content_panes.winfo_width(), self.winfo_width() - 24)
            if total <= 0:
                return
            left_w = max(220, int(total * 0.175))
            middle_w = max(240, int(total * 0.175))
            self._content_panes.sash_place(0, left_w, 0)
            self._content_panes.sash_place(1, left_w + middle_w, 0)
        except Exception as exc:
            logger.debug("Could not set initial pane sizes: %s", exc)

    def _style_axes_empty(self) -> None:
        """Draw placeholder axes styling (dark background)."""
        ax = self._axes
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="lightgray")
        ax.xaxis.label.set_color("lightgray")
        ax.yaxis.label.set_color("lightgray")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_color("gray")
        msg = (
            "Select a compound,\nthen click Process data"
            if self._on_demand_mode
            else "Select a compound"
        )
        ax.text(
            0.5,
            0.5,
            msg,
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="gray",
            fontsize=12,
        )
        ax.set_xticks([])
        ax.set_yticks([])

    def _apply_compound_filter(self) -> None:
        """Populate listbox with filtered compound IDs (capped)."""
        q = self._filter_var.get().strip().lower()
        if q:
            filtered = [i for i in self._all_ids if q in i.lower()]
        else:
            filtered = list(self._all_ids)

        truncated = False
        if len(filtered) > _MAX_LIST_DISPLAY:
            filtered = filtered[:_MAX_LIST_DISPLAY]
            truncated = True

        self._compound_listbox.delete(0, tk.END)
        for cid in filtered:
            self._compound_listbox.insert(tk.END, cid)

        msg = f"{len(filtered)} shown"
        if truncated:
            msg += f" (first {_MAX_LIST_DISPLAY} matches; refine filter)"
        elif q and not filtered:
            msg = "No matches"
        self._list_status.configure(text=msg)

    def _on_compound_list_select(self, _event: Any = None) -> None:
        """Load compound(s) from DB or cache and refresh plot."""
        sel = self._compound_listbox.curselection()
        if not sel:
            return
        list_key = self._compound_listbox.get(sel[0])

        if self._on_demand_mode:
            if self._uses_variants:
                if list_key in self._primary_variant_cache:
                    self._primary_variant_cache.move_to_end(list_key)
                    self._current_compounds = list(self._primary_variant_cache[list_key])
                else:
                    self._current_compounds = []
            else:
                if list_key in self._compound_cache:
                    self._compound_cache.move_to_end(list_key)
                    c = self._compound_cache.get(list_key)
                    self._current_compounds = [c] if c is not None else []
                else:
                    self._current_compounds = []
            self._refresh_variant_toggles()
            self._redraw_plot()
            return

        if self._data_store is None:
            return
        if self._uses_variants:
            self._current_compounds = self._data_store.get_compounds_for_primary(list_key)
            if not self._current_compounds:
                logger.warning("No compounds for primary: %s", list_key)
            self._refresh_variant_toggles()
            self._redraw_plot()
            return

        compound = self._data_store.get_compound(list_key)
        if compound is None:
            logger.warning("Compound not found: %s", list_key)
            self._current_compounds = []
            self._redraw_plot()
            return
        self._current_compounds = [compound]
        self._refresh_variant_toggles()
        self._redraw_plot()

    def _selected_count_names(self) -> List[str]:
        """Count names the user enabled."""
        names: List[str] = []
        for name, var in self._count_check_vars.items():
            if var.get():
                names.append(name)
        return names

    def _selected_variant_labels(self) -> List[str]:
        """Variant labels the user enabled (normalized with '(none)' placeholder)."""
        labels: List[str] = []
        for label, var in self._variant_check_vars.items():
            if var.get():
                labels.append(label)
        return labels

    def _refresh_variant_toggles(self) -> None:
        """Populate variant checkboxes from currently loaded compounds; preserve prior toggles."""
        if not self._uses_variants or not hasattr(self, "_variant_series_frame"):
            return

        labels = sorted({(c.variant_label or "(none)") for c in self._current_compounds})
        prev = {k for k, v in self._variant_check_vars.items() if v.get()}
        for widget in self._variant_series_frame.winfo_children():
            widget.destroy()

        self._variant_check_vars = {}
        for label in labels:
            enabled = 1 if (not prev or label in prev) else 0
            var = tk.IntVar(value=enabled)
            self._variant_check_vars[label] = var
            ctk.CTkCheckBox(
                self._variant_series_frame,
                text=label,
                variable=var,
                command=self._redraw_plot,
            ).pack(anchor="w", padx=4, pady=2)

    def _redraw_plot(self) -> None:
        """Redraw chromatogram for current compound(s) and selected series."""
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
            self._canvas.draw()
            return

        selected_variants = set(self._selected_variant_labels())
        if self._uses_variants and not selected_variants:
            ax.text(
                0.5,
                0.5,
                "Enable at least one isoform/variant",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color="orange",
                fontsize=12,
            )
            self._canvas.draw()
            return

        colors = ("#58a6ff", "#3fb950", "#d2a8ff", "#ffa657", "#79c0ff", "#ff7b72")
        plotted = 0
        idx = 0
        for compound in compounds:
            if not compound.data_points:
                continue
            available = set(compound.get_count_names())
            vlabel = compound.variant_label or "(none)"
            if self._uses_variants and vlabel not in selected_variants:
                continue
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
                if self._uses_variants:
                    legend_label = f"{vlabel} — {count_name}"
                else:
                    legend_label = count_name
                ax.plot(times, counts, label=legend_label, color=color, linewidth=1.2)
                plotted += 1
                idx += 1

        if plotted == 0:
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
            ax.legend(facecolor="#2b2b2b", edgecolor="gray", labelcolor="lightgray")
            ax.grid(True, alpha=0.25, color="gray")

        self._figure.tight_layout()
        self._canvas.draw()

    def on_close(self) -> None:
        """Close database and window."""
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
