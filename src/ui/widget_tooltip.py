# src/ui/widget_tooltip.py
"""
Hover tooltips for Tk and CustomTkinter widgets.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class HoverToolTip:
    """
    Show a small borderless popup with ``text`` while the pointer is over ``widget``.
    """

    def __init__(
        self,
        widget: tk.Misc,
        text: str,
        *,
        wraplength: int = 300,
    ) -> None:
        self._widget = widget
        self._text = text
        self._wraplength = wraplength
        self._tip_window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")
        widget._lcseq_tooltip = self  # type: ignore[attr-defined]

    def _on_enter(self, _event: tk.Event) -> None:
        if self._tip_window is not None:
            return
        try:
            x = self._widget.winfo_rootx() + 12
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        except tk.TclError:
            return

        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(
            tw,
            text=self._text,
            justify=tk.LEFT,
            wraplength=self._wraplength,
            background="#3d3d3d",
            foreground="#e6e6e6",
            relief=tk.SOLID,
            borderwidth=1,
            highlightthickness=0,
            padx=8,
            pady=6,
            font=("Segoe UI", 9),
        )
        label.pack()
        self._tip_window = tw

    def _on_leave(self, _event: Optional[tk.Event] = None) -> None:
        if self._tip_window is not None:
            self._tip_window.destroy()
            self._tip_window = None


def attach_tooltip(widget: tk.Misc, text: str, *, wraplength: int = 300) -> HoverToolTip:
    """Attach a hover tooltip to ``widget`` and return the helper instance."""
    return HoverToolTip(widget, text, wraplength=wraplength)
