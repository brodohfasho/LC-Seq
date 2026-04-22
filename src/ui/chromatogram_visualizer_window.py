# src/ui/chromatogram_visualizer_window.py
"""
Chromatogram visualizer: basic Count vs Time plotting (Phase 10).
"""

import logging
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from typing import Any, List, Optional

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from tkinter import messagebox

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.spreadsheet_loader import SpreadsheetLoader
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)

_MAX_LIST_DISPLAY = 5000
_MAX_PARSE_CACHE = 32


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
        self._current_compound: Optional[Compound] = None
        self._count_check_vars: dict[str, tk.IntVar] = {}
        self._on_demand_mode = False
        self._compound_cache: "OrderedDict[str, Compound]" = OrderedDict()
        self._processor = DataProcessor()

        self.geometry("1200x820")
        self.center_window(1200, 820)
        self.minsize(900, 600)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

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
        """Unique compound IDs in sheet order."""
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
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
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
        """Left column: compound list + count series toggles."""
        left = ctk.CTkFrame(self, width=320)
        left.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(0, 12))
        left.grid_rowconfigure(2, weight=1)
        left.grid_propagate(False)

        ctk.CTkLabel(left, text="Compound ID", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=8, pady=(8, 4), sticky="w"
        )

        self._filter_var = tk.StringVar(value="")
        filter_entry = ctk.CTkEntry(
            left,
            placeholder_text="Filter list…",
            textvariable=self._filter_var,
        )
        filter_entry.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        filter_entry.bind("<KeyRelease>", lambda _e: self._apply_compound_filter())

        list_frame = ctk.CTkFrame(left)
        list_frame.grid(row=2, column=0, padx=8, pady=4, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._compound_listbox = tk.Listbox(
            list_frame,
            height=16,
            exportselection=False,
            activestyle="dotbox",
        )
        self._compound_listbox.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self._compound_listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._compound_listbox.configure(yscrollcommand=sb.set)
        self._compound_listbox.bind("<<ListboxSelect>>", self._on_compound_list_select)

        self._list_status = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._list_status.grid(row=3, column=0, padx=8, pady=(4, 4), sticky="w")

        r = 4
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

        ctk.CTkLabel(left, text="Count series", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=r, column=0, padx=8, pady=(12, 4), sticky="w"
        )
        r += 1

        series_frame = ctk.CTkScrollableFrame(left, height=180)
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

        left.grid_columnconfigure(0, weight=1)
        self._apply_compound_filter()

    def _on_process_data_clicked(self) -> None:
        """Parse selected spreadsheet row into a Compound (on-demand)."""
        if not self._on_demand_mode:
            return
        sel = self._compound_listbox.curselection()
        if not sel:
            messagebox.showinfo("Process data", "Select a compound first.", parent=self)
            return
        compound_id = self._compound_listbox.get(sel[0])
        df = self._loader.current_data
        assert self._config is not None and df is not None
        col = self._config.compound_id_column
        mask = df[col].astype(str).str.strip() == compound_id
        idx_positions = [i for i, v in enumerate(mask.tolist()) if v]
        if not idx_positions:
            messagebox.showerror("Process data", f"No row found for compound ID: {compound_id}", parent=self)
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
            self._current_compound = None
            self._redraw_plot()
            return

        self._cache_put(compound_id, compound)
        self._current_compound = compound
        self._redraw_plot()

    def _cache_put(self, compound_id: str, compound: Compound) -> None:
        """Insert into LRU-ordered cache with size cap."""
        if compound_id in self._compound_cache:
            self._compound_cache.move_to_end(compound_id)
        self._compound_cache[compound_id] = compound
        while len(self._compound_cache) > _MAX_PARSE_CACHE:
            self._compound_cache.popitem(last=False)

    def _on_clear_memory_cache(self) -> None:
        self._compound_cache.clear()
        self._current_compound = None
        self._redraw_plot()
        messagebox.showinfo("Memory cache", "Cleared parsed compounds from memory.", parent=self)

    def _build_plot_column(self) -> None:
        """Right column: matplotlib figure + navigation toolbar."""
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=(0, 12))
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

        hint_text = (
            "Select a compound, click Process data, then choose count series. "
            "Use the toolbar for pan and zoom."
            if self._on_demand_mode
            else "Use the toolbar for pan and zoom. Select a compound and count series to plot."
        )
        hint = ctk.CTkLabel(
            right,
            text=hint_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        hint.grid(row=1, column=0, padx=8, pady=(4, 8), sticky="w")

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
        """Load compound from DB or cache and refresh plot."""
        sel = self._compound_listbox.curselection()
        if not sel:
            return
        compound_id = self._compound_listbox.get(sel[0])

        if self._on_demand_mode:
            if compound_id in self._compound_cache:
                self._compound_cache.move_to_end(compound_id)
            self._current_compound = self._compound_cache.get(compound_id)
            self._redraw_plot()
            return

        if self._data_store is None:
            return
        compound = self._data_store.get_compound(compound_id)
        if compound is None:
            logger.warning("Compound not found: %s", compound_id)
            self._current_compound = None
            self._redraw_plot()
            return
        self._current_compound = compound
        self._redraw_plot()

    def _selected_count_names(self) -> List[str]:
        """Count names the user enabled."""
        names: List[str] = []
        for name, var in self._count_check_vars.items():
            if var.get():
                names.append(name)
        return names

    def _redraw_plot(self) -> None:
        """Redraw chromatogram for current compound and selected series."""
        ax = self._axes
        ax.clear()
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="lightgray")
        ax.xaxis.label.set_color("lightgray")
        ax.yaxis.label.set_color("lightgray")
        ax.title.set_color("white")
        for spine in ax.spines.values():
            spine.set_color("gray")

        compound = self._current_compound
        if compound is None or not compound.data_points:
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

        available = set(compound.get_count_names())
        colors = ("#58a6ff", "#3fb950", "#d2a8ff", "#ffa657", "#79c0ff", "#ff7b72")
        plotted = 0
        for idx, count_name in enumerate(names):
            if count_name not in available:
                continue
            try:
                times, counts = compound.get_time_series(count_name)
            except ValueError:
                continue
            if not times:
                continue
            color = colors[idx % len(colors)]
            ax.plot(times, counts, label=count_name, color=color, linewidth=1.2)
            plotted += 1

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
            ax.set_title(f"Chromatogram — {compound.compound_id}")
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
        logger.info("Chromatogram visualizer closed")
        super().on_close()
