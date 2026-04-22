# src/ui/chromatogram_visualizer_window.py
"""
Chromatogram visualizer: basic Count vs Time plotting (Phase 10).
"""

import logging
import tkinter as tk
from pathlib import Path
from typing import Any, List, Optional

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from src.core.app_state import AppState
from src.core.config_manager import ConfigManager
from src.core.data_store import DataStore
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)

_MAX_LIST_DISPLAY = 5000


class ChromatogramVisualizerWindow(BaseWindow):
    """
    Window for viewing chromatograms: Count vs Time with zoom/pan and series toggles.

    Loads compounds from the processed SQLite database and plots using matplotlib.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        app_state: AppState,
        config_manager: ConfigManager,
    ) -> None:
        """
        Args:
            parent: Main application window
            app_state: Current application state (must include database_path or spreadsheet)
            config_manager: Used to load SpreadsheetConfig (count names)
        """
        super().__init__(parent, title="Chromatogram Visualizer")
        self.bind("<Destroy>", self._clear_main_reference)

        self.app_state = app_state
        self.config_manager = config_manager
        self._data_store: Optional[DataStore] = None
        self._config: Optional[SpreadsheetConfig] = None
        self._all_ids: List[str] = []
        self._current_compound: Optional[Compound] = None
        self._count_check_vars: dict[str, tk.IntVar] = {}

        self.geometry("1200x820")
        self.center_window(1200, 820)
        self.minsize(900, 600)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        db_path = self._resolve_database_path()
        cfg = config_manager.load_default_config()
        if not db_path or not Path(db_path).is_file():
            from tkinter import messagebox

            messagebox.showerror(
                "Database not found",
                "Could not open the processed database file. "
                "Run Process Data again, or ensure the database exists next to your spreadsheet.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        if not cfg or not cfg.count_names:
            from tkinter import messagebox

            messagebox.showerror(
                "Configuration missing",
                "Count channel names are not available. "
                "Re-open Configure Spreadsheet and save your configuration.",
                parent=self,
            )
            self.after(50, self.on_close)
            return

        self._config = cfg

        try:
            self._data_store = DataStore(db_path=Path(db_path), use_memory=False)
        except Exception as exc:
            logger.error("Failed to open database: %s", exc, exc_info=True)
            from tkinter import messagebox

            messagebox.showerror("Database error", str(exc), parent=self)
            self.after(50, self.on_close)
            return

        self._all_ids = sorted(self._data_store.get_all_compound_ids())
        if not self._all_ids:
            from tkinter import messagebox

            messagebox.showwarning(
                "No compounds",
                "The database contains no compounds to plot.",
                parent=self,
            )

        self._build_header()
        self._build_controls_column()
        self._build_plot_column()

        logger.info("Chromatogram visualizer opened (%s compounds)", len(self._all_ids))

    def _clear_main_reference(self, event: tk.Event) -> None:
        """Drop reference on main screen when this window is destroyed."""
        if event.widget != self:
            return
        main = self.parent
        if main is not None and getattr(main, "_chromatogram_window", None) is self:
            main._chromatogram_window = None

    def _resolve_database_path(self) -> Optional[str]:
        """Resolve SQLite path from app state or default next to spreadsheet."""
        if self.app_state.database_path and Path(self.app_state.database_path).is_file():
            return self.app_state.database_path
        if self.app_state.spreadsheet_path:
            p = Path(self.app_state.spreadsheet_path)
            candidate = p.parent / f"{p.stem}_database.db"
            if candidate.is_file():
                return str(candidate)
        return self.app_state.database_path

    def _build_header(self) -> None:
        """Top bar with title and Back."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Chromatogram Visualizer",
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
        left = ctk.CTkFrame(self, width=300)
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
            height=18,
            exportselection=False,
            activestyle="dotbox",
        )
        self._compound_listbox.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self._compound_listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._compound_listbox.configure(yscrollcommand=sb.set)
        self._compound_listbox.bind("<<ListboxSelect>>", self._on_compound_list_select)

        self._list_status = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._list_status.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="w")

        ctk.CTkLabel(left, text="Count series", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=4, column=0, padx=8, pady=(12, 4), sticky="w"
        )

        series_frame = ctk.CTkScrollableFrame(left, height=200)
        series_frame.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="ew")

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

        hint = ctk.CTkLabel(
            right,
            text="Use the toolbar for pan and zoom. Select a compound and count series to plot.",
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
        ax.text(
            0.5,
            0.5,
            "Select a compound",
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
        """Load compound from DB and refresh plot."""
        sel = self._compound_listbox.curselection()
        if not sel or self._data_store is None:
            return
        compound_id = self._compound_listbox.get(sel[0])
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
        logger.info("Chromatogram visualizer closed")
        super().on_close()
