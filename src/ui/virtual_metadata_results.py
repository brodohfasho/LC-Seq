# src/ui/virtual_metadata_results.py
"""
Virtual scrolling checklist for metadata search results (Phase 11).

Uses a tall inner ``tk.Frame`` inside a ``tk.Canvas``; only visible row widgets
are created and placed at absolute ``y`` positions so scrolling aligns with results.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Set

import customtkinter as ctk

_ROW_HEIGHT = 26
_OVERSCAN = 3
_PAGE_SIZE = 40
_MAX_SELECT_ALL = 100_000


class VirtualMetadataResultList(ctk.CTkFrame):
    """
    Canvas-based virtual list: checkboxes + tabular text, windowed data loading.

    Selection is tracked by ``compound_id`` (and optionally "select all" semantics).
    """

    def __init__(
        self,
        master: Any,
        *,
        columns: List[str],
        row_height: int = _ROW_HEIGHT,
        page_size: int = _PAGE_SIZE,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._columns = list(columns)
        self._row_height = row_height
        self._page_size = max(20, min(200, page_size))
        self._total = 0
        self._fetch_page: Optional[Callable[[int, int], List[Dict[str, Any]]]] = None
        self._rows_cache: Dict[int, Dict[str, Any]] = {}
        self._cache_lo = -1
        self._cache_hi = -1

        self._selected_ids: Set[str] = set()
        self._select_all_results = False

        self._header = tk.Frame(self, bg="#3d3d3d", height=self._row_height)
        self._header.grid(row=0, column=0, columnspan=2, sticky="ew")

        self._canvas = tk.Canvas(self, highlightthickness=0, bg="#2b2b2b", bd=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._scroll_cmd)
        self._canvas.configure(yscrollcommand=self._yscroll_cmd)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._scrollbar.grid(row=1, column=1, sticky="ns")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._inner = tk.Frame(self._canvas, bg="#2b2b2b")
        self._inner_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # Local scroll only — bind_all(MouseWheel) caused crashes when the window closed
        # or when events fired after destroy.
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)

        self._build_header()
        self._row_widgets: List[tk.Frame] = []
        self._repaint_scheduled = False
        self._last_canvas_width = 0

    def _scroll_cmd(self, *args: str) -> None:
        self._canvas.yview(*args)
        self._schedule_repaint()

    def _yscroll_cmd(self, lo: str, hi: str) -> None:
        # Do not schedule repaint here: updating scrollregion / inner height invokes
        # yscrollcommand again and can recurse until stack overflow / hard crash.
        self._scrollbar.set(lo, hi)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if event.delta:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._schedule_repaint()

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        w = int(event.width)
        if w <= 1:
            return
        if w != self._last_canvas_width:
            self._last_canvas_width = w
            self._canvas.itemconfig(self._inner_id, width=w)
            self._schedule_repaint()

    def _build_header(self) -> None:
        for w in self._header.winfo_children():
            w.destroy()
        labels = ["", *self._columns]
        for col, text in enumerate(labels):
            tk.Label(
                self._header,
                text=text or "Sel",
                width=16 if col == 0 else 22,
                anchor="w",
                bg="#3d3d3d",
                fg="#cccccc",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=0, column=col, padx=4, pady=2, sticky="w")

    def set_columns(self, columns: List[str]) -> None:
        """Update header labels (clears results)."""
        self._columns = list(columns)
        self._build_header()
        self.clear_results()

    def clear_results(self) -> None:
        """Reset data, selection, and scroll."""
        self._total = 0
        self._fetch_page = None
        self._rows_cache.clear()
        self._cache_lo = -1
        self._cache_hi = -1
        self._selected_ids.clear()
        self._select_all_results = False
        self._destroy_row_widgets()
        self._canvas.yview_moveto(0)
        self._inner.configure(height=1)

    def set_query(
        self,
        total: int,
        fetch_page: Callable[[int, int], List[Dict[str, Any]]],
    ) -> None:
        """Attach a new result set and reset scroll to top."""
        self._selected_ids.clear()
        self._select_all_results = False
        self._destroy_row_widgets()
        self._total = max(0, int(total))
        self._fetch_page = fetch_page
        self._rows_cache.clear()
        self._cache_lo = -1
        self._cache_hi = -1
        self._canvas.yview_moveto(0)
        self._inner.configure(height=max(1, self._total) * self._row_height)
        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=(0, 0, 1, self._inner.winfo_reqheight()))
        self._repaint()

    def get_selected_compound_ids(self) -> List[str]:
        """Return explicitly checked compound IDs (sorted)."""
        return sorted(self._selected_ids)

    def is_select_all_results(self) -> bool:
        return self._select_all_results

    def set_select_all_results(self, value: bool) -> None:
        self._select_all_results = value
        if value:
            self._selected_ids.clear()
        self._repaint()

    def select_none(self) -> None:
        self._select_all_results = False
        self._selected_ids.clear()
        self._repaint()

    def select_all_ids(self, ids: List[str]) -> None:
        """Select exactly the given compound IDs."""
        self._select_all_results = False
        self._selected_ids = set(ids)
        self._repaint()

    @staticmethod
    def max_select_all() -> int:
        return _MAX_SELECT_ALL

    def _destroy_row_widgets(self) -> None:
        for r in self._row_widgets:
            r.destroy()
        self._row_widgets.clear()

    def _ensure_cache(self, start: int, end: int) -> None:
        if self._fetch_page is None or self._total <= 0:
            return
        need_lo = max(0, start)
        need_hi = min(self._total, end)
        if need_lo >= need_hi:
            return
        if self._cache_lo <= need_lo and need_hi <= self._cache_hi and self._rows_cache:
            return
        margin = self._page_size
        block_start = max(0, need_lo - margin)
        block_end = min(self._total, need_hi + margin)
        block_len = block_end - block_start
        rows = self._fetch_page(block_start, block_len)
        self._rows_cache = {block_start + i: rows[i] for i in range(len(rows))}
        self._cache_lo = block_start
        self._cache_hi = block_end

    def _first_visible_index(self) -> int:
        if self._total <= 0:
            return 0
        try:
            top_frac = float(self._canvas.yview()[0])
        except tk.TclError:
            return 0
        inner_h = max(1, self._total * self._row_height)
        y_off = top_frac * inner_h
        return max(0, min(self._total - 1, int(y_off // self._row_height)))

    def _repaint(self) -> None:
        self._destroy_row_widgets()
        if self._total <= 0 or self._fetch_page is None:
            self._canvas.configure(scrollregion=(0, 0, 1, 1))
            return

        view_h = max(1, self._canvas.winfo_height())
        first = self._first_visible_index()
        visible_count = max(1, view_h // self._row_height + _OVERSCAN * 2)
        last = min(self._total, first + visible_count)
        self._ensure_cache(first, last)

        for i in range(first, last):
            row = self._rows_cache.get(i)
            if row is None:
                continue
            cid = str(row.get("compound_id", "") or "")
            fr = tk.Frame(self._inner, bg="#2b2b2b" if i % 2 == 0 else "#323232")
            fr.place(x=0, y=i * self._row_height, relwidth=1, height=self._row_height)

            checked = self._select_all_results or cid in self._selected_ids
            var = tk.IntVar(value=1 if checked else 0)

            def _mk_toggle(rdict: Dict[str, Any], v: tk.IntVar) -> Callable[[], None]:
                def _toggle() -> None:
                    self._select_all_results = False
                    rid = str(rdict.get("compound_id", "") or "")
                    if v.get():
                        self._selected_ids.add(rid)
                    else:
                        self._selected_ids.discard(rid)

                return _toggle

            tk.Checkbutton(
                fr,
                variable=var,
                command=_mk_toggle(row, var),
                bg=fr["bg"],
                activebackground=fr["bg"],
                selectcolor="#1e1e1e",
                highlightthickness=0,
            ).grid(row=0, column=0, padx=4)

            col_idx = 1
            for cname in self._columns:
                val = row.get(cname, "")
                if val is None:
                    val = ""
                tk.Label(
                    fr,
                    text=str(val)[:100],
                    anchor="w",
                    bg=fr["bg"],
                    fg="#e6e6e6",
                    font=("Segoe UI", 9),
                ).grid(row=0, column=col_idx, padx=4, sticky="w")
                col_idx += 1

            self._row_widgets.append(fr)

        self._inner.configure(height=self._total * self._row_height)
        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=(0, 0, 1, self._inner.winfo_reqheight()))

    def _schedule_repaint(self) -> None:
        if self._repaint_scheduled:
            return
        self._repaint_scheduled = True
        self.after_idle(self._repaint_idle)

    def _repaint_idle(self) -> None:
        self._repaint_scheduled = False
        try:
            if not self.winfo_exists():
                return
            self._repaint()
        except tk.TclError:
            pass
