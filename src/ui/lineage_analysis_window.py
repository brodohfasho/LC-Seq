# src/ui/lineage_analysis_window.py
"""
Scrollable viewer for lineage analysis figures (vector-friendly vertical layout).

Supports one or many compounds: select from a sidebar list (like Library Data plots).
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence, Union

import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from src.core.analysis_export import export_figure
from src.core.lineage_batch_export import (
    export_lineage_batch,
    export_lineage_csv_combined,
    export_lineage_csv_separate,
    export_lineage_figures_folder,
)
from src.core.lineage_export import export_lineage_csv
from src.core.lineage_render import render_lineage_figure
from src.models.pedigree_result import LineageAnalysisResult
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.base_window import BaseWindow
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_LIST_BUTTON_HEIGHT = 36
_MAX_COMPOUND_LABEL_LEN = 42


def _normalize_results(
    results: Union[LineageAnalysisResult, Sequence[LineageAnalysisResult]],
) -> List[LineageAnalysisResult]:
    if isinstance(results, LineageAnalysisResult):
        return [results]
    return list(results)


def _compound_list_label(compound_id: str) -> str:
    text = str(compound_id).strip()
    if len(text) <= _MAX_COMPOUND_LABEL_LEN:
        return text
    return text[: _MAX_COMPOUND_LABEL_LEN - 1] + "…"


class LineageViewerWindow(BaseWindow):
    """Scrollable popup for lineage chromatogram stack(s); sidebar when multiple compounds."""

    def __init__(
        self,
        parent,
        results: Union[LineageAnalysisResult, Sequence[LineageAnalysisResult]],
        config: SpreadsheetConfig,
    ) -> None:
        self._results = _normalize_results(results)
        if not self._results:
            raise ValueError("No lineage results to display.")

        n_compounds = len(self._results)
        title = (
            f"Lineage — {self._results[0].compound_id}"
            if n_compounds == 1
            else f"Lineage — {n_compounds} compounds"
        )
        width = 1040 if n_compounds > 1 else 920
        super().__init__(
            parent,
            title=title,
            transient_parent=False,
            modal=False,
            width=width,
            height=780,
        )
        self._config = config
        self._selected_index = 0
        self._figure_cache: Dict[int, Figure] = {}
        self._figure: Figure | None = None
        self._canvas: FigureCanvasTkAgg | None = None
        self._toolbar: NavigationToolbar2Tk | None = None
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_inner: tk.Frame | None = None
        self._wheel_bound = False
        self._list_buttons: List[ctk.CTkButton] = []
        self._summary_label: Optional[ctk.CTkLabel] = None

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        if n_compounds > 1:
            self._build_compound_sidebar()

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self._build_toolbar(content)
        self._build_scroll_area(content)

        try:
            self._select_compound(0)
        except Exception as exc:
            logger.error("Lineage render failed: %s", exc, exc_info=True)
            messagebox.showerror("Lineage viewer", str(exc), parent=self)
            self.after(50, self.on_close)
            return

        self._bind_mousewheel()
        self.center_window(width, 780)

    def _build_compound_sidebar(self) -> None:
        sidebar = ctk.CTkScrollableFrame(self, label_text="Compounds", width=220)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        for index, result in enumerate(self._results):
            label = _compound_list_label(result.compound_id)
            n_panels = len(result.panels)
            btn = ctk.CTkButton(
                sidebar,
                text=f"{label}\n({n_panels} tier(s))",
                anchor="w",
                height=_LIST_BUTTON_HEIGHT,
                fg_color=("gray75", "gray30"),
                hover_color=("gray70", "gray35"),
                command=lambda i=index: self._select_compound(i),
            )
            btn.pack(fill="x", pady=2, padx=2)
            self._list_buttons.append(btn)

    def _build_toolbar(self, parent: ctk.CTkFrame) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        toolbar.grid_columnconfigure(0, weight=1)

        self._summary_label = ctk.CTkLabel(
            toolbar,
            text="",
            anchor="w",
            wraplength=760 if len(self._results) > 1 else 860,
            justify="left",
        )
        self._summary_label.grid(row=0, column=0, sticky="ew")

        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=(8, 0))

        export_btn = ctk.CTkButton(actions, text="Export figure…", command=self._on_export_image)
        export_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(export_btn, "Save the current compound as PNG, PDF, or SVG.")

        csv_btn = ctk.CTkButton(actions, text="Export CSV…", command=self._on_export_csv)
        csv_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(csv_btn, "Per-tier summary CSV for the current compound.")

        if len(self._results) > 1:
            batch_frame = ctk.CTkFrame(actions, fg_color="transparent")
            batch_frame.pack(side="left", padx=(12, 0))

            all_img_btn = ctk.CTkButton(
                batch_frame,
                text="Export all figures…",
                fg_color="gray40",
                command=self._on_export_all_figures,
            )
            all_img_btn.pack(side="left", padx=(0, 6))
            attach_tooltip(all_img_btn, "Save one image per compound into a folder.")

            combined_btn = ctk.CTkButton(
                batch_frame,
                text="Export combined CSV…",
                fg_color="gray40",
                command=self._on_export_combined_csv,
            )
            combined_btn.pack(side="left", padx=(0, 6))

            separate_btn = ctk.CTkButton(
                batch_frame,
                text="Export CSVs per compound…",
                fg_color="gray40",
                command=self._on_export_separate_csvs,
            )
            separate_btn.pack(side="left", padx=(0, 6))

            all_btn = ctk.CTkButton(
                batch_frame,
                text="Export all to folder…",
                fg_color="#1F6FEB",
                command=self._on_export_all_to_folder,
            )
            all_btn.pack(side="left")
            attach_tooltip(
                all_btn,
                "Figures plus combined and per-compound CSV files in one folder.",
            )

    def _build_scroll_area(self, parent: ctk.CTkFrame) -> None:
        scroll_host = ctk.CTkFrame(parent)
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

        self._scroll_inner = tk.Frame(self._scroll_canvas, bg=tk_bg)
        self._scroll_window_id = self._scroll_canvas.create_window(
            (0, 0), window=self._scroll_inner, anchor="nw"
        )

        def _on_inner_configure(_event: tk.Event) -> None:
            if self._scroll_canvas is not None:
                self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

        def _on_canvas_configure(event: tk.Event) -> None:
            if self._scroll_canvas is not None:
                self._scroll_canvas.itemconfigure(self._scroll_window_id, width=event.width)

        self._scroll_inner.bind("<Configure>", _on_inner_configure)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

    def _current_result(self) -> LineageAnalysisResult:
        return self._results[self._selected_index]

    def _update_summary_label(self) -> None:
        if self._summary_label is None:
            return
        result = self._current_result()
        n = len(result.panels)
        prefix = ""
        if len(self._results) > 1:
            prefix = f"({self._selected_index + 1}/{len(self._results)}) "
        self._summary_label.configure(
            text=(
                f"{prefix}{result.compound_id} — {n} tier panel(s), channel {result.channel}, "
                f"α={result.settings.alpha:g}, tolerance={result.settings.tolerance:g} "
                f"{result.settings.time_unit}. Scroll to scan root → leaf."
            )
        )

    def _highlight_list_selection(self) -> None:
        for i, btn in enumerate(self._list_buttons):
            try:
                if i == self._selected_index:
                    btn.configure(fg_color=("#238636", "#2ea043"))
                else:
                    btn.configure(fg_color=("gray75", "gray30"))
            except tk.TclError:
                pass

    def _get_or_render_figure(self, index: int) -> Figure:
        if index in self._figure_cache:
            return self._figure_cache[index]
        result = self._results[index]
        fig = render_lineage_figure(
            result,
            result.chromatogram_map,
            null_token=self._config.null_token,
        )
        self._figure_cache[index] = fig
        return fig

    def _select_compound(self, index: int) -> None:
        if index < 0 or index >= len(self._results):
            return
        self._selected_index = index
        self._highlight_list_selection()
        self._update_summary_label()
        if self._scroll_canvas is not None:
            self._scroll_canvas.yview_moveto(0)
        assert self._scroll_inner is not None
        fig = self._get_or_render_figure(index)
        self._show_figure(fig, self._scroll_inner)

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
        if self._figure is not figure:
            self._clear_plot_widgets()
        self._figure = figure
        if self._canvas is None:
            self._canvas = FigureCanvasTkAgg(figure, master=parent)
            widget = self._canvas.get_tk_widget()
            widget.pack(side=tk.TOP, fill=tk.X, expand=False)
            self._toolbar = NavigationToolbar2Tk(self._canvas, parent)
            self._toolbar.update()
        self._canvas.draw()

    def _clear_plot_widgets(self) -> None:
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
            path = export_lineage_csv(self._current_result(), dest)
            messagebox.showinfo("Lineage viewer", f"Saved to:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _on_export_all_figures(self) -> None:
        dest = filedialog.askdirectory(parent=self, title="Export all lineage figures to folder")
        if not dest:
            return
        fmt = self._ask_image_format()
        if fmt is None:
            return
        try:
            paths = export_lineage_figures_folder(
                self._results,
                self._config,
                dest,
                fmt=fmt,
            )
            messagebox.showinfo(
                "Lineage viewer",
                f"Saved {len(paths)} figure(s) to:\n{dest}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _on_export_combined_csv(self) -> None:
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export combined lineage CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not dest:
            return
        try:
            path = export_lineage_csv_combined(self._results, dest)
            messagebox.showinfo("Lineage viewer", f"Saved to:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _on_export_separate_csvs(self) -> None:
        dest = filedialog.askdirectory(parent=self, title="Export per-compound lineage CSVs")
        if not dest:
            return
        try:
            paths = export_lineage_csv_separate(self._results, dest)
            messagebox.showinfo(
                "Lineage viewer",
                f"Saved {len(paths)} CSV file(s) to:\n{dest}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _on_export_all_to_folder(self) -> None:
        dest = filedialog.askdirectory(
            parent=self,
            title="Export all lineage figures and CSVs to folder",
        )
        if not dest:
            return
        fmt = self._ask_image_format()
        if fmt is None:
            return
        try:
            written = export_lineage_batch(
                self._results,
                self._config,
                dest,
                image_fmt=fmt,
            )
            n_fig = len(written.get("figures", []))
            messagebox.showinfo(
                "Lineage viewer",
                f"Exported {n_fig} figure(s), combined CSV, and per-compound CSVs to:\n{dest}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Lineage viewer", str(exc), parent=self)

    def _ask_image_format(self) -> Optional[str]:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Image format")
        dialog.transient(self)
        dialog.grab_set()
        choice: dict[str, Optional[str]] = {"fmt": None}

        ctk.CTkLabel(dialog, text="Choose format for exported figures:").pack(
            padx=20, pady=(16, 8)
        )
        var = tk.StringVar(value="svg")

        for label, value in (("SVG (vector)", "svg"), ("PDF (vector)", "pdf"), ("PNG", "png")):
            ctk.CTkRadioButton(dialog, text=label, variable=var, value=value).pack(
                anchor="w", padx=24, pady=2
            )

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(pady=16)

        def _ok() -> None:
            choice["fmt"] = var.get()
            dialog.destroy()

        def _cancel() -> None:
            dialog.destroy()

        ctk.CTkButton(btn_row, text="OK", width=80, command=_ok).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="gray40", command=_cancel).pack(
            side="left", padx=6
        )
        dialog.wait_window()
        return choice["fmt"]

    def on_close(self) -> None:
        self._unbind_mousewheel()
        self._clear_plot_widgets()
        for fig in self._figure_cache.values():
            plt.close(fig)
        self._figure_cache.clear()
        super().on_close()


def open_lineage_viewer_window(
    parent,
    results: Union[LineageAnalysisResult, Sequence[LineageAnalysisResult]],
    config: SpreadsheetConfig,
) -> LineageViewerWindow:
    """Open a scrollable lineage figure viewer for one or more completed analyses."""
    return LineageViewerWindow(parent, results, config)
