# src/ui/chromatogram_dialogs.py
"""
Modal dialogs for the chromatogram visualizer: compound picker and metadata search.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, Callable, List, Optional, Sequence, Tuple

import customtkinter as ctk
from tkinter import messagebox

from src.core.data_store import DataStore
from src.core.metadata_search import (
    append_results_text_filter,
    build_where_clause,
    sanitize_sql_column,
    validate_conditions,
)
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.query_builder_panel import QueryBuilderPanel

logger = logging.getLogger(__name__)

_MAX_LIST_DISPLAY = 5000
_MAX_SEARCH_LOAD = 5000


class CompoundPickerDialog(ctk.CTkToplevel):
    """
    Multi-select compound IDs with text filter; Proceed returns selected list keys.
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        title: str,
        list_heading: str,
        all_ids: Sequence[str],
        on_done: Callable[[Optional[List[str]]], None],
    ) -> None:
        super().__init__(master)
        self._on_done = on_done
        self._all_ids = list(all_ids)
        self.title(title)
        self.geometry("560x620")
        self.minsize(400, 400)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text=list_heading, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )

        self._filter_var = tk.StringVar(value="")
        ent = ctk.CTkEntry(self, placeholder_text="Filter by ID…", textvariable=self._filter_var)
        ent.grid(row=1, column=0, padx=12, pady=4, sticky="ew")
        ent.bind("<KeyRelease>", lambda _e: self._apply_filter())

        lf = ctk.CTkFrame(self)
        lf.grid(row=3, column=0, padx=12, pady=4, sticky="nsew")
        lf.grid_rowconfigure(0, weight=1)
        lf.grid_columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            lf,
            selectmode=tk.EXTENDED,
            exportselection=False,
            activestyle="dotbox",
        )
        self._listbox.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(lf, orient="vertical", command=self._listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=sb.set)

        self._status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._status.grid(row=4, column=0, padx=12, pady=4, sticky="w")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=12, pady=(4, 12), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", width=100, fg_color="gray40", command=self._cancel).pack(
            side="right", padx=4
        )
        ctk.CTkButton(
            btn_row,
            text="Proceed",
            width=120,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._proceed,
        ).pack(side="right", padx=4)

        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter_var.get().strip().lower()
        if q:
            filtered = [i for i in self._all_ids if q in i.lower()]
        else:
            filtered = list(self._all_ids)
        truncated = False
        if len(filtered) > _MAX_LIST_DISPLAY:
            filtered = filtered[:_MAX_LIST_DISPLAY]
            truncated = True
        self._listbox.delete(0, tk.END)
        for cid in filtered:
            self._listbox.insert(tk.END, cid)
        msg = f"{len(filtered)} shown"
        if truncated:
            msg += f" (capped at {_MAX_LIST_DISPLAY})"
        elif q and not filtered:
            msg = "No matches"
        self._status.configure(text=msg)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._on_done(None)

    def _proceed(self) -> None:
        sel = self._listbox.curselection()
        if not sel:
            messagebox.showinfo("Compound list", "Select one or more compounds (Ctrl+click).", parent=self)
            return
        keys = [self._listbox.get(i) for i in sel]
        self.grab_release()
        self.destroy()
        self._on_done(keys)


class MetadataSearchDialog(ctk.CTkToplevel):
    """
    Query builder + Search; on success returns compound IDs (caller loads ``Compound`` rows).
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        config: SpreadsheetConfig,
        data_store: DataStore,
        searchable_metadata_columns: Sequence[str],
        on_done: Callable[[Optional[List[str]]], None],
    ) -> None:
        super().__init__(master)
        self._config = config
        self._data_store = data_store
        self._searchable = list(searchable_metadata_columns)
        self._on_done = on_done

        self.title("Search compounds")
        self.geometry("760x720")
        self.minsize(560, 520)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            title_row,
            text="Metadata search (SQLite)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w")
        _, missing_cols = data_store.filter_metadata_columns_for_search(
            list(config.selected_metadata_columns or [])
        )
        if missing_cols:
            miss_txt = ", ".join(missing_cols[:10])
            if len(missing_cols) > 10:
                miss_txt += ", …"
            ctk.CTkLabel(
                title_row,
                text=(
                    "These configured columns are not in this database file "
                    f"(rebuild the DB): {miss_txt}"
                ),
                text_color="orange",
                font=ctk.CTkFont(size=11),
                wraplength=700,
                justify="left",
            ).pack(anchor="w", pady=(6, 0))

        body = ctk.CTkScrollableFrame(self, height=520)
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        body.grid_columnconfigure(0, weight=1)

        self._query_panel = QueryBuilderPanel(
            body,
            metadata_fields=self._searchable,
            on_search=self._run_search,
            on_clear=self._clear_panel,
        )
        self._query_panel.grid(row=0, column=0, sticky="ew", pady=4)

        self._result_filter_var = tk.StringVar(value="")
        ctk.CTkLabel(body, text="Filter hits (optional)", font=ctk.CTkFont(size=12)).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ctk.CTkEntry(
            body,
            placeholder_text="Matches compound ID or any searchable metadata text…",
            textvariable=self._result_filter_var,
        ).grid(row=2, column=0, sticky="ew", pady=4)

        self._msg = ctk.CTkLabel(body, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self._msg.grid(row=3, column=0, sticky="w", pady=4)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=12, pady=(4, 12), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", width=100, fg_color="gray40", command=self._cancel).pack(
            side="right", padx=4
        )

    def _clear_panel(self) -> None:
        self._msg.configure(text="")

    def _compute_where(self) -> Tuple[str, List[Any]]:
        conditions = self._query_panel.get_conditions()
        combiners = self._query_panel.get_combiners()
        while len(combiners) < max(0, len(conditions) - 1):
            combiners.append("AND")
        where_sql, params = build_where_clause(conditions, combiners)
        needle = (self._result_filter_var.get() or "").strip()
        meta_safe = [sanitize_sql_column(c) for c in self._searchable]
        or_cols = ["compound_id", *meta_safe]
        return append_results_text_filter(where_sql, list(params), needle, or_cols)

    def _run_search(self) -> None:
        conditions = self._query_panel.get_conditions()
        allowed = self._searchable or []
        errs = validate_conditions(conditions, allowed)
        if errs:
            messagebox.showerror("Search", "\n".join(errs), parent=self)
            return
        try:
            where_sql, params = self._compute_where()
        except ValueError as exc:
            messagebox.showerror("Search", str(exc), parent=self)
            return

        total = self._data_store.count_compounds_where(where_sql, params)
        if total == 0:
            self._msg.configure(text="No matches.", text_color="orange")
            return
        if total > _MAX_SEARCH_LOAD:
            messagebox.showwarning(
                "Search",
                f"This query matches {total} compounds. Only the first {_MAX_SEARCH_LOAD} "
                "will be loaded into the table. Narrow your search if needed.",
                parent=self,
            )
        self._msg.configure(text=f"Loading {min(total, _MAX_SEARCH_LOAD)} of {total}…", text_color="gray")
        self.update_idletasks()

        ids = self._data_store.list_compound_ids_where(where_sql, params)[:_MAX_SEARCH_LOAD]
        self.grab_release()
        self.destroy()
        self._on_done(ids)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._on_done(None)
