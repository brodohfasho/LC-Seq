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

    def __init__(self, parent, *, initial_topic: str = "peak_picking") -> None:
        super().__init__(
            parent,
            title="LC-Seq Analysis Help",
            transient_parent=True,
            modal=False,
            width=900,
            height=640,
        )
        self._topic_buttons: dict[str, ctk.CTkButton] = {}
        self._active_topic = initial_topic

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkScrollableFrame(self, label_text="Topics", width=200)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)

        for topic in list_help_topics():
            btn = ctk.CTkButton(
                sidebar,
                text=topic.title,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray85", "gray25"),
                command=lambda tid=topic.topic_id: self._show_topic(tid),
            )
            btn.pack(fill="x", pady=2)
            self._topic_buttons[topic.topic_id] = btn

        content = ctk.CTkFrame(self)
        content.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        content.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            content,
            text="",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self._title_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        self._text = ctk.CTkTextbox(
            content,
            wrap="word",
            font=ctk.CTkFont(size=13),
            activate_scrollbars=True,
        )
        self._text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        if get_help_topic(initial_topic) is None:
            initial_topic = "peak_picking"
        self._show_topic(initial_topic)
        self.center_window(900, 640)
        self._raise_to_front()

    def _show_topic(self, topic_id: str) -> None:
        topic = get_help_topic(topic_id)
        if topic is None:
            return
        self._active_topic = topic_id
        self._title_label.configure(text=topic.title)
        render_markdown_to_textbox(self._text, format_help_with_related(topic_id))

        for tid, btn in self._topic_buttons.items():
            if tid == topic_id:
                btn.configure(fg_color=("#dbeafe", "#1f3d5c"))
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


def open_help_window(parent, topic_id: str = "peak_picking") -> HelpWindow:
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
