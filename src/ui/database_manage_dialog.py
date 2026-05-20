# src/ui/database_manage_dialog.py
"""
Create / load managed SQLite databases (output/databases).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from tkinter import messagebox

from src.core import database_library
from src.core.data_store import DB_KIND_FULL, DB_KIND_INDEX, DataStore
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)


class DatabaseManageDialog(BaseWindow):
    """
    Modal dialog: create a full or index database, load from the managed folder,
    delete a file, or clear the active DB reference.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        on_begin_bulk_create: Callable[[], None],
        on_begin_index_create: Callable[[], None],
        on_database_loaded: Callable[[str, str], None],
        on_active_database_cleared: Callable[[], None],
    ) -> None:
        """
        Args:
            parent: Main window
            on_begin_bulk_create: After user confirms full database build; host runs bulk flow.
            on_begin_index_create: After user confirms index build; host runs index flow.
            on_database_loaded: Called with (absolute path, "full" or "index").
            on_active_database_cleared: Called when user clears the active DB pointer.
        """
        super().__init__(parent, title="Create / Load database")

        self._on_begin_bulk_create = on_begin_bulk_create
        self._on_begin_index_create = on_begin_index_create
        self._on_database_loaded = on_database_loaded
        self._on_active_database_cleared = on_active_database_cleared

        self.geometry("580x540")
        self.center_window(580, 540)

        self._tabview = ctk.CTkTabview(self)
        self._tabview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        create_tab = self._tabview.add("Create Database")
        load_tab = self._tabview.add("Load Database")

        self._build_create_tab(create_tab)
        self._build_load_tab(load_tab)

        close_row = ctk.CTkFrame(self, fg_color="transparent")
        close_row.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="e")
        ctk.CTkButton(close_row, text="Close", width=100, command=self.on_close).grid(
            row=0, column=0, padx=4
        )

    def _build_create_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)

        intro = (
            "Choose how to create a SQLite file under the managed folder "
            f"({database_library.get_databases_dir()}).\n\n"
            "• Full database — every time point is written to the database. Best for fast plotting "
            "and filtering on fully materialized data; files can grow very large.\n\n"
            "• Index database — stores searchable metadata plus the raw chromatogram text from "
            "your sheet. Smaller on disk; chromatograms are parsed when you plot. Same Search "
            "tools as a full database."
        )
        ctk.CTkLabel(
            parent,
            text=intro,
            font=ctk.CTkFont(size=12),
            wraplength=520,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(16, 16), sticky="ew")

        ctk.CTkButton(
            parent,
            text="Build Full Database",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=42,
            command=self._on_full_create_clicked,
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")

        ctk.CTkButton(
            parent,
            text="Build Index Database",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=42,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_index_create_clicked,
        ).grid(row=2, column=0, padx=12, pady=(0, 16), sticky="ew")

    def _on_full_create_clicked(self) -> None:
        msg = (
            "Build a Full database?\n\n"
            "A Full database expands every compound’s chromatogram into individual time/count "
            "rows in SQLite. That makes plotting and repeated access very fast, but the file "
            "can be extremely large (often much larger than your spreadsheet), especially for "
            "big libraries or long traces.\n\n"
            "Only continue if you need maximum query performance on fully parsed data and have "
            "enough disk space.\n\n"
            "Proceed with Full database creation?"
        )
        if not messagebox.askyesno("Build Full Database", msg, parent=self):
            return
        host = self.master
        cb = self._on_begin_bulk_create
        self.destroy()
        if host is not None:
            host.after(50, cb)

    def _on_index_create_clicked(self) -> None:
        msg = (
            "Build an Index database?\n\n"
            "An Index database stores the same searchable metadata columns as a Full database, "
            "plus the raw chromatogram cell text. It does not store every time point separately, "
            "so the file stays much smaller and builds faster.\n\n"
            "When you plot in the Chromatogram Visualizer, LC-Seq parses the raw text on demand "
            "(same rules as your saved spreadsheet configuration). Search and compound lists work "
            "the same as with a Full database.\n\n"
            "Proceed with Index database creation?"
        )
        if not messagebox.askyesno("Build Index Database", msg, parent=self):
            return
        host = self.master
        cb = self._on_begin_index_create
        self.destroy()
        if host is not None:
            host.after(50, cb)

    def _build_load_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            parent,
            text="Managed databases (output/databases):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(16, 6), sticky="w")

        self._db_combo = ctk.CTkComboBox(parent, values=[], width=480, state="readonly")
        self._db_combo.grid(row=1, column=0, padx=12, pady=6, sticky="ew")

        self._load_hint = ctk.CTkLabel(
            parent,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=500,
            justify="left",
        )
        self._load_hint.grid(row=2, column=0, padx=12, pady=4, sticky="w")

        self._refresh_db_combo()

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.grid(row=3, column=0, padx=12, pady=10, sticky="ew")
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            btn_row, text="Load selected", command=self._on_load_selected
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        ctk.CTkButton(
            btn_row,
            text="Delete selected",
            fg_color="darkred",
            hover_color="red",
            command=self._on_delete_selected,
        ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        ctk.CTkButton(
            btn_row,
            text="Clear active DB",
            fg_color="gray40",
            hover_color="gray25",
            command=self._on_clear_active,
        ).grid(row=0, column=2, padx=4, pady=4, sticky="ew")

    def _refresh_db_combo(self) -> None:
        paths = database_library.list_managed_databases()
        display = [Path(p).name for p in paths]
        self._path_by_display = dict(zip(display, paths)) if paths else {}
        self._db_combo.configure(values=display if display else ["(no databases yet)"])
        if display:
            self._db_combo.set(display[0])
        else:
            self._db_combo.set("(no databases yet)")
        self._load_hint.configure(
            text=f"{len(paths)} file(s) in {database_library.get_databases_dir()}"
        )

    def _selected_path(self) -> str | None:
        label = self._db_combo.get()
        if not label or label.startswith("("):
            return None
        return self._path_by_display.get(label)

    def _on_load_selected(self) -> None:
        path = self._selected_path()
        if not path or not Path(path).is_file():
            messagebox.showwarning("Load database", "Select a valid database file.", parent=self)
            return
        try:
            kind = DataStore.peek_database_kind(Path(path))
        except OSError as exc:
            logger.warning("Could not read database kind: %s", exc)
            kind = DB_KIND_FULL
        type_word = "index" if kind == DB_KIND_INDEX else "full"
        self._on_database_loaded(path, type_word)
        messagebox.showinfo(
            "Database loaded",
            f"Successfully loaded {type_word} database.\n\n{path}",
            parent=self,
        )
        self.destroy()

    def _on_delete_selected(self) -> None:
        path = self._selected_path()
        if not path or not Path(path).is_file():
            messagebox.showwarning("Delete database", "Select a valid database file.", parent=self)
            return
        if not messagebox.askyesno(
            "Delete database",
            f"Permanently delete this file?\n\n{path}",
            parent=self,
        ):
            return
        database_library.delete_database_files(Path(path))
        self._refresh_db_combo()
        messagebox.showinfo("Delete database", "File removed (if it existed).", parent=self)

    def _on_clear_active(self) -> None:
        self._on_active_database_cleared()
        messagebox.showinfo(
            "Active database",
            "Cleared the active database reference. Load or build a database before "
            "opening the Chromatogram Visualizer.",
            parent=self,
        )
        self.destroy()
