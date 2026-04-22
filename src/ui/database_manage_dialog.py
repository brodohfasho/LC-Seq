# src/ui/database_manage_dialog.py
"""
Create / load / delete managed bulk SQLite databases (output/databases).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from tkinter import messagebox

from src.core import database_library
from src.ui.base_window import BaseWindow

logger = logging.getLogger(__name__)


class DatabaseManageDialog(BaseWindow):
    """
    Modal dialog: optional bulk database create (delegates to ProcessDataDialog flow),
    load from managed folder, delete, or clear active DB reference.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        on_begin_bulk_create: Callable[[], None],
        on_database_loaded: Callable[[str], None],
        on_active_database_cleared: Callable[[], None],
    ) -> None:
        """
        Args:
            parent: Main window
            on_begin_bulk_create: Called after user confirms bulk export; host should
                ``wait_window(ProcessDataDialog)`` (this dialog is destroyed first).
            on_database_loaded: Called with absolute path when user loads a managed DB.
            on_active_database_cleared: Called when user clears the active DB pointer.
        """
        super().__init__(parent, title="Create / Load database")

        self._on_begin_bulk_create = on_begin_bulk_create
        self._on_database_loaded = on_database_loaded
        self._on_active_database_cleared = on_active_database_cleared

        self.geometry("560x480")
        self.center_window(560, 480)

        self._tabview = ctk.CTkTabview(self)
        self._tabview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        create_tab = self._tabview.add("Create database")
        load_tab = self._tabview.add("Load database")

        self._build_create_tab(create_tab)
        self._build_load_tab(load_tab)

        close_row = ctk.CTkFrame(self, fg_color="transparent")
        close_row.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="e")
        ctk.CTkButton(close_row, text="Close", width=100, command=self.on_close).grid(
            row=0, column=0, padx=4
        )

    def _build_create_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)

        warn = (
            "Bulk export builds a full SQLite copy of your spreadsheet under "
            f"{database_library.get_databases_dir()}.\n\n"
            "These files can be very large (often tens of MB or more for rich chromatograms). "
            "Use this when you need fast repeated access or future indexed search — not for casual viewing.\n\n"
            "The default workflow is on-demand parsing inside the Chromatogram Visualizer."
        )
        ctk.CTkLabel(
            parent,
            text=warn,
            font=ctk.CTkFont(size=12),
            wraplength=500,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(16, 12), sticky="ew")

        ctk.CTkButton(
            parent,
            text="Start bulk export…",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._on_create_clicked,
        ).grid(row=1, column=0, padx=12, pady=12, sticky="ew")

    def _on_create_clicked(self) -> None:
        if not messagebox.askyesno(
            "Create large database file?",
            "This will create a potentially large SQLite file under output/databases. "
            "Continue with bulk export?",
            parent=self,
        ):
            return
        host = self.master
        cb = self._on_begin_bulk_create
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

    def _selected_path(self) -> Optional[str]:
        label = self._db_combo.get()
        if not label or label.startswith("("):
            return None
        return self._path_by_display.get(label)

    def _on_load_selected(self) -> None:
        path = self._selected_path()
        if not path or not Path(path).is_file():
            messagebox.showwarning("Load database", "Select a valid database file.", parent=self)
            return
        self._on_database_loaded(path)
        messagebox.showinfo(
            "Database loaded",
            f"The application will use:\n{path}\n\n"
            "Open the Chromatogram Visualizer to query this database.",
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
            "Cleared the active database reference. The visualizer will use on-demand "
            "parsing until you load or create another database.",
            parent=self,
        )
        self.destroy()
