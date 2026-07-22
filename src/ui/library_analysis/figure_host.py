# src/ui/library_analysis/figure_host.py
"""Matplotlib figure embedding and cleanup for Library Analysis tabs."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Optional, Tuple

import customtkinter as ctk


def build_tree_figure_host(
    parent: ctk.CTkFrame,
    *,
    tk_bg: str,
    title: str,
    subtitle: str = "",
    placeholder: str,
    show_toolbar_hint: bool = True,
) -> Tuple[ctk.CTkFrame, ctk.CTkLabel, tk.Frame, Optional[ctk.CTkLabel]]:
    """Create a titled Matplotlib figure host and placeholder."""
    column = ctk.CTkFrame(parent, corner_radius=8)
    column.pack(fill="both", expand=True)
    column.grid_columnconfigure(0, weight=1)
    column.grid_rowconfigure(1, weight=1)

    header = ctk.CTkFrame(column, fg_color="transparent")
    header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
    header.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        header,
        text=title,
        font=ctk.CTkFont(size=14, weight="bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="w")
    subtitle_label: Optional[ctk.CTkLabel] = None
    next_row = 1
    if subtitle.strip():
        subtitle_label = ctk.CTkLabel(
            header,
            text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=520,
            justify="left",
        )
        subtitle_label.grid(row=next_row, column=0, sticky="ew", pady=(2, 0))
        next_row += 1
    if show_toolbar_hint:
        ctk.CTkLabel(
            header,
            text="Use the matplotlib toolbar below the figure to pan, zoom, and reset the view.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=520,
            justify="left",
        ).grid(row=next_row, column=0, sticky="ew", pady=(2, 0))
    host = ctk.CTkFrame(column, fg_color=("gray90", "gray17"))
    host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
    host.grid_columnconfigure(0, weight=1)
    host.grid_rowconfigure(0, weight=1)

    placeholder_label = ctk.CTkLabel(
        host,
        text=placeholder,
        font=ctk.CTkFont(size=12),
        text_color="gray",
        wraplength=520,
        justify="center",
    )
    placeholder_label.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    plot_host = tk.Frame(host, bg=tk_bg)
    plot_host.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
    plot_host.grid_remove()
    return host, placeholder_label, plot_host, subtitle_label


class FigureHost:
    """Own a Tk-hosted Matplotlib figure, canvas, toolbar, and placeholder."""

    def __init__(self, plot_host: tk.Misc, placeholder: tk.Misc) -> None:
        self._plot_host = plot_host
        self._placeholder = placeholder
        self._figure: Optional[Any] = None
        self._canvas: Optional[Any] = None
        self._toolbar: Optional[Any] = None

    @property
    def figure(self) -> Optional[Any]:
        """Return the currently mounted Matplotlib figure."""
        return self._figure

    def mount(self, figure: Any) -> None:
        """Replace the current figure and display its navigation toolbar."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

        self.clear()
        self._placeholder.grid_remove()
        self._plot_host.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._figure = figure
        self._canvas = FigureCanvasTkAgg(figure, master=self._plot_host)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._toolbar = NavigationToolbar2Tk(self._canvas, self._plot_host)
        self._toolbar.update()
        self._toolbar.pack(side=tk.BOTTOM, fill=tk.X)

    def show_placeholder(self, message: str) -> None:
        """Clear the current figure and display ``message`` in its place."""
        self.clear()
        self._plot_host.grid_remove()
        self._placeholder.configure(text=message)
        self._placeholder.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def clear(self) -> None:
        """Destroy Tk widgets and close the currently mounted figure."""
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
            import matplotlib.pyplot as plt

            plt.close(self._figure)
            self._figure = None
