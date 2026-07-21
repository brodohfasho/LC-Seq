# src/core/help_markdown.py
"""
Render markdown help topics into a CustomTkinter textbox with styled tags.

Supports the subset used in ``src/help/*.md``: headings, bold, inline code,
bullet lists, block quotes, horizontal rules, and pipe tables.
"""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from typing import Dict, Iterable, Sequence, Tuple

import customtkinter as ctk

BlockTag = Tuple[str, ...]
InlinePattern = Tuple[re.Pattern[str], str]

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(\s*)([-*•]|\d+\.)\s+(.*)$")
_BLOCKQUOTE = re.compile(r"^>\s?(.*)$")
_TABLE_ROW = re.compile(r"^\|.+\|$")
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")
_HRULE = re.compile(r"^-{3,}\s*$")

_INLINE_PATTERNS: Tuple[InlinePattern, ...] = (
    (re.compile(r"\*\*(.+?)\*\*"), "bold"),
    (re.compile(r"`([^`]+)`"), "code"),
)

_BODY_FONT = "Segoe UI"
_MONO_FONT = "Consolas"

_TAG_OPTIONS: dict[str, dict] = {
    "h1": {"font": (_BODY_FONT, 21, "bold"), "spacing1": 14, "spacing3": 8},
    "h2": {"font": (_BODY_FONT, 16, "bold"), "spacing1": 14, "spacing3": 5},
    "h3": {"font": (_BODY_FONT, 13, "bold"), "spacing1": 10, "spacing3": 3},
    "h4": {"font": (_BODY_FONT, 12, "bold"), "spacing1": 8, "spacing3": 2},
    "body": {"font": (_BODY_FONT, 13), "spacing1": 3, "spacing3": 3, "spacing2": 3},
    "bold": {"font": (_BODY_FONT, 13, "bold")},
    "quote": {
        "font": (_BODY_FONT, 12, "italic"),
        "lmargin1": 22,
        "lmargin2": 22,
        "spacing1": 3,
        "spacing3": 3,
    },
    "bullet": {
        "font": (_BODY_FONT, 13),
        "lmargin1": 22,
        "lmargin2": 40,
        "spacing1": 3,
        "spacing3": 3,
        "spacing2": 3,
    },
    "hr": {"font": (_BODY_FONT, 4)},
    "related": {"font": (_BODY_FONT, 13, "bold"), "spacing1": 16, "spacing3": 6},
}

# Accent + surface colors resolved per appearance mode (light, dark).
_THEME = {
    "accent": ("#1f4e79", "#6cb6ff"),
    "code_fg": ("#0b5cad", "#7ee3c6"),
    "hr": ("#d0d7de", "#3a3f47"),
    "table_border": ("#c9ced6", "#3a3f47"),
    "table_header_bg": ("#e8edf5", "#243447"),
    "table_header_fg": ("#152430", "#e6edf3"),
    "table_row_even": ("#ffffff", "#1f1f1f"),
    "table_row_odd": ("#f3f6fa", "#262a30"),
    "table_cell_fg": ("#152430", "#d7dde3"),
}


def _mode_index() -> int:
    return 1 if ctk.get_appearance_mode() == "Dark" else 0


def _color(name: str) -> str:
    return _THEME[name][_mode_index()]


def configure_help_text_tags(textbox: ctk.CTkTextbox) -> None:
    """Register styled tags on a help textbox (idempotent)."""
    tk_text = textbox._textbox
    for name, options in _TAG_OPTIONS.items():
        tk_text.tag_configure(name, **options)
    accent = _color("accent")
    tk_text.tag_configure("h1", foreground=accent)
    tk_text.tag_configure("h2", foreground=accent)
    tk_text.tag_configure("related", foreground=accent)
    tk_text.tag_configure("code", font=(_MONO_FONT, 12), foreground=_color("code_fg"))


def render_markdown_to_textbox(textbox: ctk.CTkTextbox, markdown: str) -> None:
    """Replace textbox contents with rendered markdown."""
    configure_help_text_tags(textbox)
    _reset_embedded_tables(textbox)
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            textbox.insert("end", "\n")
            index += 1
            continue

        if _HRULE.match(stripped):
            _insert_rule(textbox)
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading.group(1))
            tag = f"h{min(level, 4)}"
            _insert_inline(textbox, heading.group(2), (tag,))
            textbox.insert("end", "\n")
            index += 1
            continue

        if _TABLE_ROW.match(stripped):
            table_lines: list[str] = []
            while index < len(lines) and _TABLE_ROW.match(lines[index].strip()):
                row = lines[index].strip()
                if not _TABLE_SEP.match(row):
                    table_lines.append(row)
                index += 1
            _insert_table(textbox, table_lines)
            textbox.insert("end", "\n")
            continue

        quote = _BLOCKQUOTE.match(stripped)
        if quote:
            _insert_inline(textbox, quote.group(1), ("quote",))
            textbox.insert("end", "\n")
            index += 1
            continue

        bullet = _LIST_ITEM.match(line)
        if bullet:
            textbox.insert("end", "• ", ("bullet",))
            _insert_inline(textbox, bullet.group(3), ("bullet",))
            textbox.insert("end", "\n")
            index += 1
            continue

        if stripped.startswith("— ") and "Related topics" in stripped:
            textbox.insert("end", stripped + "\n", ("related",))
            index += 1
            continue

        _insert_inline(textbox, stripped, ("body",))
        textbox.insert("end", "\n")
        index += 1

    textbox.configure(state="disabled")
    textbox.see("1.0")


_EMBED_REGISTRY: "Dict[int, list]" = {}
_RESIZE_BOUND: "Dict[int, bool]" = {}


def _reset_embedded_tables(textbox: ctk.CTkTextbox) -> None:
    """Destroy embedded widgets (tables, rules) left over from a prior render."""
    key = id(textbox)
    for widget in _EMBED_REGISTRY.get(key, []):
        try:
            widget.destroy()
        except tk.TclError:
            pass
    _EMBED_REGISTRY[key] = []
    _ensure_resize_handler(textbox)


def _register_embed(textbox: ctk.CTkTextbox, widget) -> None:
    _EMBED_REGISTRY.setdefault(id(textbox), []).append(widget)


def _ensure_resize_handler(textbox: ctk.CTkTextbox) -> None:
    """Bind a single width handler per textbox that resizes all live tables."""
    key = id(textbox)
    if _RESIZE_BOUND.get(key):
        return
    tk_text = textbox._textbox

    def _on_configure(_event=None) -> None:
        for widget in _EMBED_REGISTRY.get(key, []):
            apply_fn = getattr(widget, "_help_resize", None)
            if apply_fn is not None:
                apply_fn()

    tk_text.bind("<Configure>", _on_configure, add="+")
    _RESIZE_BOUND[key] = True


def _insert_rule(textbox: ctk.CTkTextbox) -> None:
    """Insert a thin full-width separator line."""
    tk_text = textbox._textbox
    textbox.insert("end", "\n")
    line = tk.Frame(tk_text, height=2, bg=_color("hr"))
    line.pack_propagate(False)

    def _apply() -> None:
        try:
            width = max(tk_text.winfo_width() - 34, 40)
            line.configure(width=width)
        except tk.TclError:
            pass

    line._help_resize = _apply  # type: ignore[attr-defined]
    tk_text.window_create("end", window=line, padx=2, pady=8)
    _register_embed(textbox, line)
    textbox.insert("end", "\n")
    line.after(60, _apply)


def _insert_table(textbox: ctk.CTkTextbox, rows: Sequence[str]) -> None:
    """Render a pipe table as an embedded, aligned grid widget."""
    if not rows:
        return
    parsed = [_split_table_row(row) for row in rows]
    parsed = [row for row in parsed if any(cell for cell in row)]
    if not parsed:
        return
    n_cols = max(len(row) for row in parsed)

    tk_text = textbox._textbox
    border = _color("table_border")
    table = tk.Frame(tk_text, bg=border, highlightthickness=0, bd=0)
    for col in range(n_cols):
        table.grid_columnconfigure(col, weight=1, uniform="helpcol")

    header_font = tkfont.Font(family=_BODY_FONT, size=12, weight="bold")
    cell_font = tkfont.Font(family=_BODY_FONT, size=12)

    for r_idx, cells in enumerate(parsed):
        is_header = r_idx == 0
        if is_header:
            bg = _color("table_header_bg")
            fg = _color("table_header_fg")
            font = header_font
        else:
            bg = _color("table_row_even") if (r_idx % 2 == 1) else _color("table_row_odd")
            fg = _color("table_cell_fg")
            font = cell_font
        for c_idx in range(n_cols):
            raw = cells[c_idx] if c_idx < len(cells) else ""
            cell = tk.Label(
                table,
                text=raw,
                bg=bg,
                fg=fg,
                font=font,
                justify="left",
                anchor="w",
                wraplength=1,
                padx=10,
                pady=6,
            )
            # 1px border via the frame background showing through grid gaps.
            cell.grid(
                row=r_idx,
                column=c_idx,
                sticky="nsew",
                padx=(0, 1) if c_idx < n_cols - 1 else 0,
                pady=(0, 1) if r_idx < len(parsed) - 1 else 0,
            )
            cell._help_is_header = is_header  # type: ignore[attr-defined]

    table.grid_propagate(False)

    def _apply() -> None:
        try:
            avail = tk_text.winfo_width()
        except tk.TclError:
            return
        if avail <= 1:
            return
        # Leave room for the text widget's internal padding + scrollbar.
        target = max(avail - 34, n_cols * 90)
        usable = max(target - (n_cols - 1) - n_cols * 22, n_cols * 60)
        per_col = max(int(usable / n_cols), 60)
        for child in table.winfo_children():
            try:
                child.configure(wraplength=per_col)
            except tk.TclError:
                pass
        try:
            table.update_idletasks()
            table.configure(width=target, height=max(table.winfo_reqheight(), 1))
        except tk.TclError:
            pass

    table._help_resize = _apply  # type: ignore[attr-defined]
    textbox.insert("end", "\n")
    tk_text.window_create("end", window=table, padx=2, pady=6)
    _register_embed(textbox, table)
    textbox.insert("end", "\n")
    table.after(60, _apply)


def _split_table_row(row: str) -> list[str]:
    inner = row.strip().strip("|")
    return [re.sub(r"\*\*(.+?)\*\*", r"\1", cell.strip()) for cell in inner.split("|")]


def _column_widths(rows: Iterable[Sequence[str]]) -> list[int]:
    widths: list[int] = []
    for row in rows:
        for idx, cell in enumerate(row):
            while len(widths) <= idx:
                widths.append(0)
            widths[idx] = max(widths[idx], len(cell))
    return widths


def _insert_inline(textbox: ctk.CTkTextbox, text: str, base_tags: BlockTag) -> None:
    """Insert a line with inline ``**bold**`` and ``code`` spans."""
    if not text:
        return
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            textbox.insert("end", text[pos : match.start()], base_tags)
        token = match.group(0)
        if token.startswith("**"):
            textbox.insert("end", token[2:-2], base_tags + ("bold",))
        else:
            textbox.insert("end", token[1:-1], base_tags + ("code",))
        pos = match.end()
    if pos < len(text):
        textbox.insert("end", text[pos:], base_tags)
