# src/ui/lineage_analysis_window.py
"""
Scrollable viewer for lineage analysis figures (vector-friendly vertical layout).
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from src.core.analysis_export import export_figure
from src.core.lineage_export import export_lineage_csv
from src.core.lineage_render import render_lineage_figure
from src.models.pedigree_result import LineageAnalysisResult
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)


class LineageViewerWindow(BaseWindow):
    """Scrollable popup for a tall lineage chromatogram stack."""

    def __init__(
        self,
        parent,
        result: LineageAnalysisResult,
        config: SpreadsheetConfig,
    ) -> None:
        compound_id = result.compound_id
        super().__init__(
            parent,
            title=f"Lineage — {compound_id}",
            transient_parent=False,
            modal=False,
            width=920,
            height=780,
        )
        self._result = result
        self._config = config
        self._figure: Figure | None = None
        self._canvas: FigureCanvasTkAgg | None = None
        self._toolbar: NavigationToolbar2Tk | None = None
        self._scroll_canvas: tk.Canvas | None = None
        self._wheel_bound = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        toolbar.grid_columnconfigure(0, weight=1)

        n = len(result.panels)
        ctk.CTkLabel(
            toolbar,
            text=(
                f"{compound_id} — {n} tier panel(s), channel {result.channel}, "
                f"α={result.settings.alpha:g}, tolerance={result.settings.tolerance:g} "
                f"{result.settings.time_unit}. Scroll to scan root → leaf."
            ),
            anchor="w",
            wraplength=860,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=(8, 0))

        export_btn = ctk.CTkButton(actions, text="Export PNG…", command=self._on_export_image)
        export_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(export_btn, "Save as PNG, PDF, or SVG (vector formats recommended).")

        csv_btn = ctk.CTkButton(actions, text="Export CSV…", command=self._on_export_csv)
        csv_btn.pack(side="left")
        attach_tooltip(csv_btn, "Per-tier summary: pass/fail, thresholds, and chosen RT fields.")

        scroll_host = ctk.CTkFrame(self)
        scroll_host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        scroll_host.grid_columnconfigure(0, weight=1)
        scroll_host.grid_rowconfigure(0, weight=1)

        tk_bg = ctk.ThemeManager.theme["CTkFrame"]["fg_color"][
            1 if ctk.get_appearance_mode() == "Dark" else 0
        ]
        self._scroll_canvas = tk.Canvas(scroll_host, bg=tk_bg, highlightthickness=0)
        vsb = ttk.Scrollbar(scroll_host, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=vsb.set)
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(self._scroll_canvas, bg=tk_bg)
        self._scroll_window_id = self._scroll_canvas.create_window(
            (0, 0), window=inner, anchor="nw"
        )

        def _on_inner_configure(_event: tk.Event) -> None:
            if self._scroll_canvas is not None:
                self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

        def _on_canvas_configure(event: tk.Event) -> None:
            if self._scroll_canvas is not None:
                self._scroll_canvas.itemconfigure(self._scroll_window_id, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

        try:
            fig = render_lineage_figure(
                result,
                result.chromatogram_map,
                null_token=config.null_token,
            )
            self._show_figure(fig, inner)
        except Exception as exc:
            logger.error("Lineage render failed: %s", exc, exc_info=True)
            messagebox.showerror("Lineage viewer", str(exc), parent=self)
            self.after(50, self.on_close)
            return

        self._bind_mousewheel()
        self.center_window(920, 780)

    def _bind_mousewheel(self) -> None:
        if self._scroll_canvas is None or self._wheel_bound:
            return

        def _on_mousewheel(event: tk.Event) -> None:
            if self._scroll_canvas is None:
                return
            delta = int(-1 * (event.delta / 120))
            self._scroll_canvas.yview_scroll(delta, "units")

        self.bind_all("<MouseWheel>", _on_mousewheel)
        self._wheel_bound = True
        self._mousewheel_handler = _on_mousewheel

    def _unbind_mousewheel(self) -> None:
        if self._wheel_bound:
            try:
                self.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            self._wheel_bound = False

    def _show_figure(self, figure: Figure, parent: tk.Frame) -> None:
        self._clear_plot()
        self._figure = figure
        self._canvas = FigureCanvasTkAgg(figure, master=parent)
        widget = self._canvas.get_tk_widget()
        widget.pack(side=tk.TOP, fill=tk.X, expand=False)
        self._toolbar = NavigationToolbar2Tk(self._canvas, parent)
        self._toolbar.update()
        self._canvas.draw()

    def _clear_plot(self) -> None:
        if self._toolbar is not None:
            try:
                self._toolbar.destroy()
            except tk.TclError:
                pass
            self._toolbar = None
        if self._canvas is not None:
            try:
                self._canvas.get_tk_widget().destroy()
            except tk.TclError:
                pass
            self._canvas = None
        if self._figure is not None:
            plt.close(self._figure)
            self._figure = None

    def _on_export_image(self) -> None:
        if self._figure is None:
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export lineage figure",
            defaultextension=".svg",
            filetypes=[
                ("SVG vector", "*.svg"),
                ("PDF vector", "*.pdf"),
                ("PNG", "*.png"),
            ],
        )
        if not dest:
            return
        try:
            export_figure(self._figure, dest, dpi=200)
            messagebox.showinfo("Lineage viewer", f"Saved to:\n{dest}", parent=self)
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _on_export_csv(self) -> None:
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export lineage summary CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not dest:
            return
        try:
            path = export_lineage_csv(self._result, dest)
            messagebox.showinfo("Lineage viewer", f"Saved to:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def on_close(self) -> None:
        self._unbind_mousewheel()
        self._clear_plot()
        super().on_close()


def open_lineage_viewer_window(
    parent,
    result: LineageAnalysisResult,
    config: SpreadsheetConfig,
) -> LineageViewerWindow:
    """Open a scrollable lineage figure viewer for a completed analysis."""
    return LineageViewerWindow(parent, result, config)
