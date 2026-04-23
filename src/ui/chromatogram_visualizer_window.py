# src/ui/chromatogram_visualizer_window.py
"""
Chromatogram visualizer: plot on top, compound table and controls below (Phase 10–11).
"""

import logging
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from tkinter import messagebox, ttk

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.chromatogram_dialogs import CompoundPickerDialog, MetadataSearchDialog

logger = logging.getLogger(__name__)

_MAX_PARSE_CACHE = 32
_MAX_PROCEED_KEYS = 200
_MAX_META_TABLE_COLS = 4


class ChromatogramVisualizerWindow(BaseWindow):
    """
    Chromatogram on top (full width); compound table, picker/search dialogs, and series toggles below.

    Uses a bulk SQLite database when one is active; otherwise parses spreadsheet rows on demand.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
        loader: SpreadsheetLoader,
    ) -> None:
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
        self._searchable_metadata_columns: List[str] = []
        self._table_compounds_by_iid: Dict[str, Compound] = {}

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
        if db_path and Path(db_path).is_file():
            self._on_demand_mode = False
            try:
                self._data_store = DataStore(db_path=Path(db_path), use_memory=False)
            except Exception as exc:
                logger.error("Failed to open database: %s", exc, exc_info=True)
                messagebox.showerror("Database error", str(exc), parent=self)
                self.after(50, self.on_close)
                return
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
        self._build_plot_area()
        self._build_bottom_controls()
        self._build_compound_table()

        self.after(200, self._apply_maximized_state)

        logger.info(
            "Chromatogram visualizer opened (%s compounds, on_demand=%s)",
            len(self._all_ids),
            self._on_demand_mode,
        )

    def _apply_maximized_state(self) -> None:
        """Fill the screen (Windows ``zoomed`` / Linux zoomed attribute)."""
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

    def _compound_ids_from_dataframe(self, df: pd.DataFrame) -> List[str]:
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
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        header.grid_columnconfigure(0, weight=1)

        mode = "On-demand (spreadsheet)" if self._on_demand_mode else "Bulk SQLite database"
        ctk.CTkLabel(
            header,
            text=f"Chromatogram Visualizer — {mode}",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        btn_fr = ctk.CTkFrame(header, fg_color="transparent")
        btn_fr.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            btn_fr,
            text="Minimize",
            width=88,
            fg_color=("gray75", "gray35"),
            command=self.iconify,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_fr, text="Back to main", width=110, command=self.on_close).pack(side="left")

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

        hint = (
            "Open Compound list, add rows to the table, then Plot selected. "
            "Use the toolbar for pan and zoom."
            if self._on_demand_mode
            else "Open Compound list or Search, load the table, then Plot selected. Toolbar: pan / zoom."
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
        ctk.CTkButton(
            row0,
            text="Compound list…",
            width=130,
            command=self._open_compound_picker,
        ).pack(side="left", padx=(0, 6))
        if not self._on_demand_mode:
            ctk.CTkButton(
                row0,
                text="Search…",
                width=100,
                command=self._open_metadata_search,
            ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            row0,
            text="Clear table",
            width=100,
            fg_color="gray40",
            command=self._on_clear_table,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            row0,
            text="Plot selected",
            width=120,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_plot_selected_from_table,
        ).pack(side="left", padx=(0, 12))

        if self._on_demand_mode:
            ctk.CTkButton(
                row0,
                text="Clear parse cache",
                width=120,
                fg_color="gray35",
                command=self._on_clear_memory_cache,
            ).pack(side="left", padx=(0, 6))

        assert self._config is not None
        ctk.CTkLabel(row0, text="Count series:", font=ctk.CTkFont(size=12, weight="bold")).pack(
            side="left", padx=(12, 4)
        )
        for name in self._config.count_names:
            var = tk.IntVar(value=1)
            self._count_check_vars[name] = var
            ctk.CTkCheckBox(
                row0,
                text=name,
                variable=var,
                command=self._redraw_plot,
            ).pack(side="left", padx=4)

        if self._uses_variants:
            vf = ctk.CTkFrame(bottom, fg_color="transparent")
            vf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
            ctk.CTkLabel(vf, text="Isoforms / variants:", font=ctk.CTkFont(size=12, weight="bold")).pack(
                side="left", padx=(0, 6)
            )
            self._variant_series_frame = vf

    def _build_compound_table(self) -> None:
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 10))
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrap,
            text="Loaded compounds (select rows, then Plot selected)",
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
        for c in cols:
            self._tree.heading(c, text=c.replace("_", " ").title())
            self._tree.column(c, width=120, stretch=True)
        self._tree.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(tbl_fr, orient="vertical", command=self._tree.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb = ttk.Scrollbar(tbl_fr, orient="horizontal", command=self._tree.xview)
        xsb.grid(row=1, column=0, sticky="ew")
        self._tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self._apply_treeview_dark_style()

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
        if self._on_demand_mode:
            meta = list(self._config.selected_metadata_columns or [])[:_MAX_META_TABLE_COLS]
        else:
            meta = list(self._searchable_metadata_columns[:_MAX_META_TABLE_COLS])
        if self._uses_variants:
            return ["compound_id", "primary_id", "variant", *meta]
        return ["compound_id", *meta]

    def _row_values(self, c: Compound) -> tuple:
        cols = self._table_column_names()
        meta_keys = [x for x in cols if x not in ("compound_id", "primary_id", "variant")]
        parts: List[str] = [c.compound_id]
        if self._uses_variants:
            parts.append(c.primary_compound_id or "")
            parts.append(c.variant_label or "")
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
            if c is not None:
                loaded.append(c)
        if not loaded:
            messagebox.showerror("Search", "No compounds could be loaded for this query.", parent=self)
            return
        self._append_compounds_to_table(loaded, replace=True)

    def _load_compounds_for_keys(self, keys: List[str]) -> List[Compound]:
        out: List[Compound] = []
        if self._on_demand_mode:
            df = self._loader.current_data
            assert self._config is not None and df is not None
            col = self._config.compound_id_column
            for key in keys:
                if self._uses_variants:
                    found = self._parse_all_rows_for_primary(key)
                    out.extend(found)
                else:
                    mask = df[col].astype(str).str.strip() == key
                    idx_positions = [i for i, v in enumerate(mask.tolist()) if v]
                    if not idx_positions:
                        continue
                    row = df.iloc[int(idx_positions[0])]
                    compound, res = self._processor.parse_dataframe_row_to_compound(
                        row, self._config, int(idx_positions[0]) + 2
                    )
                    if compound is not None:
                        self._cache_put(key, compound)
                        out.append(compound)
            return out

        assert self._data_store is not None
        for key in keys:
            if self._uses_variants:
                out.extend(self._data_store.get_compounds_for_primary(key))
            else:
                c = self._data_store.get_compound(key)
                if c is not None:
                    out.append(c)
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
            self._table_compounds_by_iid[iid] = c
            self._tree.insert("", "end", iid=iid, values=self._row_values(c))
            added += 1

        n = len(self._table_compounds_by_iid)
        action = "Replaced table with" if replace else "Added"
        self._table_status.configure(text=f"{action} {added} row(s); {n} compound(s) in table.")

    def _on_clear_table(self) -> None:
        for iid in list(self._tree.get_children()):
            self._tree.delete(iid)
        self._table_compounds_by_iid.clear()
        self._current_compounds = []
        self._refresh_variant_toggles()
        self._style_axes_empty()
        self._canvas.draw()
        self._table_status.configure(text="Table cleared.")

    def _on_plot_selected_from_table(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Plot", "Select one or more rows in the table first.", parent=self)
            return
        compounds: List[Compound] = []
        for iid in sel:
            c = self._table_compounds_by_iid.get(str(iid))
            if c is not None:
                compounds.append(c)
        if not compounds:
            messagebox.showerror("Plot", "Could not resolve selected rows.", parent=self)
            return
        self._current_compounds = compounds
        self._refresh_variant_toggles()
        self._redraw_plot()

    def _cache_put(self, compound_id: str, compound: Compound) -> None:
        if compound_id in self._compound_cache:
            self._compound_cache.move_to_end(compound_id)
        self._compound_cache[compound_id] = compound
        while len(self._compound_cache) > _MAX_PARSE_CACHE:
            self._compound_cache.popitem(last=False)

    def _parse_all_rows_for_primary(self, primary_id: str) -> List[Compound]:
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
        if found:
            self._cache_put_primary(primary_id, found)
        return found

    def _cache_put_primary(self, primary_id: str, compounds: List[Compound]) -> None:
        if primary_id in self._primary_variant_cache:
            self._primary_variant_cache.move_to_end(primary_id)
        self._primary_variant_cache[primary_id] = compounds
        while len(self._primary_variant_cache) > _MAX_PARSE_CACHE:
            self._primary_variant_cache.popitem(last=False)

    def _on_clear_memory_cache(self) -> None:
        self._compound_cache.clear()
        self._primary_variant_cache.clear()
        messagebox.showinfo("Cache", "Cleared on-demand parse cache.", parent=self)

    def _selected_count_names(self) -> List[str]:
        names: List[str] = []
        for name, var in self._count_check_vars.items():
            if var.get():
                names.append(name)
        return names

    def _selected_variant_labels(self) -> List[str]:
        labels: List[str] = []
        for label, var in self._variant_check_vars.items():
            if var.get():
                labels.append(label)
        return labels

    def _refresh_variant_toggles(self) -> None:
        if not self._uses_variants or not hasattr(self, "_variant_series_frame"):
            return
        vf = self._variant_series_frame
        for w in list(vf.winfo_children())[1:]:
            w.destroy()

        labels = sorted({(c.variant_label or "(none)") for c in self._current_compounds})
        prev = {k for k, v in self._variant_check_vars.items() if v.get()}
        self._variant_check_vars = {}
        for label in labels:
            enabled = 1 if (not prev or label in prev) else 0
            var = tk.IntVar(value=enabled)
            self._variant_check_vars[label] = var
            ctk.CTkCheckBox(
                vf,
                text=label,
                variable=var,
                command=self._redraw_plot,
            ).pack(side="left", padx=4)

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
            "Add compounds via Compound list or Search,\nselect table rows, then Plot selected.",
            transform=ax.transAxes,
            ha="center",
            va="center",
            color="gray",
            fontsize=12,
        )
        ax.set_xticks([])
        ax.set_yticks([])

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
        if self._uses_variants and self._variant_check_vars and not selected_variants:
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
