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
        self._topic_buttons: dict[str, ctk.CTkButton] = {}
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
            width=248,
            corner_radius=0,
            fg_color=("#eef2f8", "#1a1d21"),
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)

        for topic in list_help_topics():
            btn = ctk.CTkButton(
                sidebar,
                text=topic.title,
                anchor="w",
                height=34,
                corner_radius=8,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d6e2f2", "#2a2f36"),
                command=lambda tid=topic.topic_id: self._show_topic(tid),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._topic_buttons[topic.topic_id] = btn

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

    def _show_topic(self, topic_id: str) -> None:
        topic = get_help_topic(topic_id)
        if topic is None:
            return
        self._active_topic = topic_id
        self._title_label.configure(text=topic.title)
        render_markdown_to_textbox(self._text, format_help_with_related(topic_id))
        self._text.see("1.0")

        for tid, btn in self._topic_buttons.items():
            if tid == topic_id:
                btn.configure(fg_color=("#cfe0f5", "#274563"))
            else:
                btn.configure(fg_color="transparent")

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
