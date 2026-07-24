# src/ui/help_window.py
"""
In-app scientist help viewer (plain-English analysis guides with markdown styling).
"""

from __future__ import annotations

import logging
from typing import Optional

import customtkinter as ctk

from src.core.help_content import (
    format_help_with_related,
    get_help_topic,
    list_help_topics,
)
from src.core.help_markdown import render_markdown_to_textbox
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)

_SINGLETON: Optional["HelpWindow"] = None

_SIDEBAR_WIDTH = 280
_SIDEBAR_LABEL_PAD_X = 10
_SIDEBAR_ROW_PAD_X = 8
# Inner scrollable width minus row/label pads and a little room for the scrollbar.
_SIDEBAR_WRAPLENGTH = _SIDEBAR_WIDTH - (2 * _SIDEBAR_ROW_PAD_X) - (2 * _SIDEBAR_LABEL_PAD_X) - 18

_TOPIC_FG_IDLE = "transparent"
_TOPIC_FG_HOVER = ("#d6e2f2", "#2a2f36")
_TOPIC_FG_ACTIVE = ("#cfe0f5", "#274563")
_TOPIC_TEXT = ("gray10", "gray90")


class HelpWindow(BaseWindow):
    """Scrollable help viewer with topic sidebar."""

    _WIDTH = 1080
    _HEIGHT = 760
    _CONTENT_MAX_WIDTH = 900

    def __init__(self, parent, *, initial_topic: str = "library_analysis") -> None:
        super().__init__(
            parent,
            title="LC-Seq Analysis Help",
            transient_parent=True,
            modal=False,
            width=self._WIDTH,
            height=self._HEIGHT,
        )
        self._topic_rows: dict[str, ctk.CTkFrame] = {}
        self._topic_labels: dict[str, ctk.CTkLabel] = {}
        self._active_topic = initial_topic
        self.minsize(820, 560)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

        if get_help_topic(initial_topic) is None:
            initial_topic = "library_analysis"
        self._show_topic(initial_topic)
        self.center_window(self._WIDTH, self._HEIGHT)
        self._raise_to_front()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkScrollableFrame(
            self,
            label_text="Help topics",
            width=_SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=("#eef2f8", "#1a1d21"),
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)

        for topic in list_help_topics():
            row = ctk.CTkFrame(
                sidebar,
                fg_color=_TOPIC_FG_IDLE,
                corner_radius=8,
                cursor="hand2",
            )
            row.pack(fill="x", padx=_SIDEBAR_ROW_PAD_X, pady=2)

            label = ctk.CTkLabel(
                row,
                text=topic.title,
                anchor="w",
                justify="left",
                wraplength=_SIDEBAR_WRAPLENGTH,
                font=ctk.CTkFont(size=13),
                text_color=_TOPIC_TEXT,
                cursor="hand2",
            )
            label.pack(fill="x", padx=_SIDEBAR_LABEL_PAD_X, pady=8)

            tid = topic.topic_id
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _e, t=tid: self._show_topic(t))
                widget.bind("<Enter>", lambda _e, t=tid: self._on_topic_hover(t, True))
                widget.bind("<Leave>", lambda _e, t=tid: self._on_topic_hover(t, False))

            self._topic_rows[tid] = row
            self._topic_labels[tid] = label

    def _on_topic_hover(self, topic_id: str, entering: bool) -> None:
        if topic_id == self._active_topic:
            return
        row = self._topic_rows.get(topic_id)
        if row is None:
            return
        row.configure(fg_color=_TOPIC_FG_HOVER if entering else _TOPIC_FG_IDLE)

    def _build_content(self) -> None:
        outer = ctk.CTkFrame(self, corner_radius=0, fg_color=("#ffffff", "#151719"))
        outer.grid(row=0, column=1, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        # Center a fixed-max-width reading column for comfortable line length.
        content = ctk.CTkFrame(outer, fg_color="transparent")
        content.grid(row=0, column=0, sticky="nsew", padx=28, pady=(22, 20))
        content.grid_rowconfigure(2, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)
        content.grid_columnconfigure(2, weight=1)

        header = ctk.CTkFrame(content, fg_color="transparent")
        header.grid(row=0, column=1, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=("#1f4e79", "#6cb6ff"),
            anchor="w",
            justify="left",
            wraplength=self._CONTENT_MAX_WIDTH,
        )
        self._title_label.grid(row=0, column=0, sticky="ew")

        self._accent_rule = ctk.CTkFrame(
            content,
            height=3,
            corner_radius=2,
            fg_color=("#1f4e79", "#6cb6ff"),
        )
        self._accent_rule.grid(row=1, column=1, sticky="ew", pady=(10, 14))

        self._text = ctk.CTkTextbox(
            content,
            wrap="word",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            activate_scrollbars=True,
            fg_color="transparent",
            border_width=0,
        )
        self._text.grid(row=2, column=1, sticky="nsew")

        content.bind("<Configure>", self._on_content_resize)

    def _on_content_resize(self, event) -> None:
        """Cap the reading column width so long lines stay legible."""
        available = max(event.width - 56, 320)
        col_width = min(available, self._CONTENT_MAX_WIDTH)
        self._text.configure(width=col_width)
        self._accent_rule.configure(width=col_width)
        self._title_label.configure(wraplength=col_width)

    def _show_topic(self, topic_id: str) -> None:
        topic = get_help_topic(topic_id)
        if topic is None:
            return
        self._active_topic = topic_id
        self._title_label.configure(text=topic.title)
        render_markdown_to_textbox(self._text, format_help_with_related(topic_id))
        self._text.see("1.0")

        for tid, row in self._topic_rows.items():
            if tid == topic_id:
                row.configure(fg_color=_TOPIC_FG_ACTIVE)
            else:
                row.configure(fg_color=_TOPIC_FG_IDLE)

    def _raise_to_front(self) -> None:
        """Keep the help viewer above its parent window (Windows z-order)."""
        if self.parent is not None:
            try:
                self.transient(self.parent)
            except Exception:
                pass
        self.lift()
        self.focus_force()

    def on_close(self) -> None:
        global _SINGLETON
        if _SINGLETON is self:
            _SINGLETON = None
        super().on_close()


def open_help_window(parent, topic_id: str = "library_analysis") -> HelpWindow:
    """Open or focus the singleton help viewer."""
    global _SINGLETON
    if _SINGLETON is not None:
        try:
            if _SINGLETON.winfo_exists():
                _SINGLETON.parent = parent
                _SINGLETON._raise_to_front()
                if get_help_topic(topic_id):
                    _SINGLETON._show_topic(topic_id)
                return _SINGLETON
        except Exception:
            _SINGLETON = None
    _SINGLETON = HelpWindow(parent, initial_topic=topic_id)
    return _SINGLETON
