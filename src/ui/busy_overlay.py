# src/ui/busy_overlay.py
"""
Reusable full-area busy overlay (title, detail, progress bar, optional Cancel).

Library Analysis and other long-running windows should use this widget so busy
state looks and behaves the same everywhere.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
import tkinter as tk


class BusyOverlay:
    """Grid-managed overlay that covers a parent shell while work runs."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_cancel: Optional[Callable[[], None]] = None,
        wraplength: int = 520,
        bar_width: int = 420,
    ) -> None:
        self._on_cancel = on_cancel
        self._max_fraction = 0.0

        self.frame = ctk.CTkFrame(parent, corner_radius=12)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        center = ctk.CTkFrame(self.frame, fg_color="transparent")
        center.grid(row=0, column=0)
        center.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            center,
            text="Working…",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, pady=(0, 8))

        self.detail_label = ctk.CTkLabel(
            center,
            text="Please wait while processing continues.",
            font=ctk.CTkFont(size=13),
            text_color="gray",
            wraplength=wraplength,
            justify="center",
        )
        self.detail_label.grid(row=1, column=0, pady=(0, 16))

        self.progress_bar = ctk.CTkProgressBar(center, width=bar_width)
        self.progress_bar.grid(row=2, column=0, pady=(0, 8))
        self.progress_bar.set(0)

        self.percent_label = ctk.CTkLabel(
            center,
            text="0%",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self.percent_label.grid(row=3, column=0)

        self.cancel_button = ctk.CTkButton(
            center,
            text="Cancel",
            width=120,
            fg_color="#8B2E2E",
            hover_color="#A33",
            command=self._handle_cancel,
        )
        self.cancel_button.grid(row=4, column=0, pady=(16, 0))
        if on_cancel is None:
            self.cancel_button.grid_remove()

        self.frame.grid_remove()

    def _handle_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()

    def show(
        self,
        title: str,
        detail: str = "",
        *,
        grid_kwargs: Optional[dict] = None,
    ) -> None:
        """Show the overlay. ``grid_kwargs`` defaults to full sticky fill."""
        self._max_fraction = 0.0
        kwargs = {"row": 0, "column": 0, "sticky": "nsew"}
        if grid_kwargs:
            kwargs.update(grid_kwargs)
        self.frame.grid(**kwargs)
        try:
            self.frame.lift()
        except tk.TclError:
            pass
        self.title_label.configure(text=title or "Working…")
        self.detail_label.configure(
            text=detail or "Starting…",
            text_color="gray",
        )
        self.progress_bar.set(0)
        self.percent_label.configure(text="0%")
        self.set_cancel_enabled(True)

    def hide(self) -> None:
        """Hide the overlay and reset cancel affordance."""
        try:
            self.frame.grid_remove()
            self.detail_label.configure(text_color="gray")
            self.set_cancel_enabled(True)
        except tk.TclError:
            pass

    def set_progress(self, fraction: float, detail: str = "") -> None:
        """Update determinate progress (monotonic; never moves backward)."""
        try:
            self._max_fraction = max(self._max_fraction, fraction)
            clamped = min(1.0, max(0.0, self._max_fraction))
            self.progress_bar.set(clamped)
            self.percent_label.configure(text=f"{int(clamped * 100)}%")
            if detail:
                self.detail_label.configure(text=detail)
        except tk.TclError:
            pass

    def set_cancel_enabled(self, enabled: bool) -> None:
        if self._on_cancel is None:
            return
        try:
            self.cancel_button.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def set_indeterminate_detail(self, detail: str) -> None:
        """Status-only update when no reliable fraction is available."""
        try:
            if detail:
                self.detail_label.configure(text=detail)
            self.percent_label.configure(text="")
        except tk.TclError:
            pass
