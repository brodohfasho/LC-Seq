# src/ui/library_report_dialog.py
"""Modal dialog for Library Data PDF report section selection."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, List, Optional

import customtkinter as ctk
from tkinter import messagebox

from src.core.library_report_models import (
    LibraryReportOptions,
    LibraryReportPrerequisites,
    LibraryReportSectionStatus,
)


@dataclass(frozen=True)
class LibraryReportDialogResult:
    """Outcome from the generate-report dialog."""

    options: LibraryReportOptions
    prerequisites: LibraryReportPrerequisites


class LibraryReportDialog(ctk.CTkToplevel):
    """Choose report sections from session artifacts already computed in Library Analysis."""

    _SECTION_KEYS = ("metrics", "plots", "rt_assignment", "pedigree_viz", "splittree")

    def __init__(
        self,
        master: tk.Misc,
        *,
        section_statuses: List[LibraryReportSectionStatus],
        prerequisites: LibraryReportPrerequisites,
        on_confirm: Callable[[LibraryReportDialogResult], None],
        reassess: Optional[
            Callable[[LibraryReportOptions], LibraryReportPrerequisites]
        ] = None,
    ) -> None:
        super().__init__(master)
        self._on_confirm = on_confirm
        self._reassess = reassess
        self._prerequisites = prerequisites
        self._section_statuses = {status.key: status for status in section_statuses}
        self._status_labels: dict[str, ctk.CTkLabel] = {}

        self.title("Generate library report")
        self.geometry("580x560")
        self.minsize(520, 480)
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text="Select report sections",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 6))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text=(
                "The report includes only analyses you have already run in this session. "
                "Run metrics, plots, RT assignment, or split-tree steps in Library Analysis "
                "first, then return here to assemble the PDF."
            ),
            wraplength=520,
            justify="left",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        self._vars: dict[str, tk.BooleanVar] = {}
        row = 1
        for key in self._SECTION_KEYS:
            status = self._section_statuses.get(key)
            if status is None:
                continue
            enabled = status.ready
            var = tk.BooleanVar(value=status.selected and enabled)
            self._vars[key] = var
            frame = ctk.CTkFrame(body, fg_color=("gray92", "gray18"))
            frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
            frame.grid_columnconfigure(1, weight=1)

            ctk.CTkCheckBox(
                frame,
                text=status.label,
                variable=var,
                font=ctk.CTkFont(size=14, weight="bold"),
                state="normal" if enabled else "disabled",
                command=self._refresh_status_text,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))

            ctk.CTkLabel(
                frame,
                text=status.detail,
                wraplength=500,
                justify="left",
                font=ctk.CTkFont(size=12),
                text_color=("gray25", "gray75"),
            ).grid(row=1, column=0, columnspan=2, sticky="w", padx=32, pady=(0, 4))

            readiness = "Ready" if status.ready else "Not available — run this step first"
            status_color = "#238636" if status.ready else "#B8860B"
            self._status_labels[key] = ctk.CTkLabel(
                frame,
                text=readiness,
                font=ctk.CTkFont(size=11),
                text_color=status_color,
            )
            self._status_labels[key].grid(row=2, column=0, columnspan=2, sticky="w", padx=32, pady=(0, 12))
            row += 1

        self._warning_label = ctk.CTkLabel(
            self,
            text="",
            wraplength=520,
            justify="left",
            font=ctk.CTkFont(size=12),
            text_color="#B8860B",
        )
        self._warning_label.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="e", padx=20, pady=(0, 16))
        ctk.CTkButton(
            buttons,
            text="Cancel",
            width=100,
            fg_color="gray40",
            command=self._on_cancel,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            buttons,
            text="Continue…",
            width=120,
            fg_color="#238636",
            hover_color="#2ea043",
            command=self._on_continue,
        ).pack(side="right")

        self._refresh_status_text()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.after(100, self.focus_set)

    def _current_options(self) -> LibraryReportOptions:
        metrics_status = self._section_statuses.get("metrics")
        plots_status = self._section_statuses.get("plots")
        metric_ids = list(metrics_status.item_ids) if metrics_status else []
        plot_ids = list(plots_status.item_ids) if plots_status else []
        channels = list(metrics_status.channels) if metrics_status else []
        if plots_status and plots_status.channels:
            channels = list(dict.fromkeys([*channels, *plots_status.channels]))
        return LibraryReportOptions(
            include_metrics=bool(self._vars.get("metrics") and self._vars["metrics"].get()),
            include_plots=bool(self._vars.get("plots") and self._vars["plots"].get()),
            include_rt_assignment=bool(
                self._vars.get("rt_assignment") and self._vars["rt_assignment"].get()
            ),
            include_pedigree_viz=bool(
                self._vars.get("pedigree_viz") and self._vars["pedigree_viz"].get()
            ),
            include_splittree=bool(
                self._vars.get("splittree") and self._vars["splittree"].get()
            ),
            metric_ids=metric_ids,
            plot_ids=plot_ids,
            channels=channels,
        )

    def _refresh_status_text(self) -> None:
        options = self._current_options()
        prerequisites = (
            self._reassess(options) if self._reassess is not None else self._prerequisites
        )
        selected = any(
            (
                options.include_metrics,
                options.include_plots,
                options.include_rt_assignment,
                options.include_pedigree_viz,
                options.include_splittree,
            )
        )
        if prerequisites.missing_sections and selected:
            notes = "\n".join(f"• {note}" for note in prerequisites.missing_sections)
            self._warning_label.configure(
                text=(
                    "Some selected sections are not available in this session yet:\n\n"
                    f"{notes}"
                )
            )
        elif selected:
            self._warning_label.configure(
                text=(
                    "All selected sections are ready. The PDF will embed the current "
                    "session artifacts and audit settings."
                )
            )
        else:
            self._warning_label.configure(text="Select at least one available report section.")

    def _on_cancel(self) -> None:
        self.grab_release()
        self.destroy()

    def _on_continue(self) -> None:
        include_metrics = bool(self._vars.get("metrics") and self._vars["metrics"].get())
        include_plots = bool(self._vars.get("plots") and self._vars["plots"].get())
        include_rt_assignment = bool(
            self._vars.get("rt_assignment") and self._vars["rt_assignment"].get()
        )
        include_pedigree_viz = bool(
            self._vars.get("pedigree_viz") and self._vars["pedigree_viz"].get()
        )
        include_splittree = bool(
            self._vars.get("splittree") and self._vars["splittree"].get()
        )
        if not any(
            (
                include_metrics,
                include_plots,
                include_rt_assignment,
                include_pedigree_viz,
                include_splittree,
            )
        ):
            messagebox.showinfo(
                "Generate report",
                "Select at least one available report section.",
                parent=self,
            )
            return

        options = self._current_options()
        prerequisites = (
            self._reassess(options) if self._reassess is not None else self._prerequisites
        )
        if prerequisites.missing_sections:
            messagebox.showinfo(
                "Generate report",
                "Some selected sections are not available yet:\n\n"
                + "\n".join(f"• {note}" for note in prerequisites.missing_sections),
                parent=self,
            )
            return

        final_options = LibraryReportOptions(
            include_metrics=options.include_metrics,
            include_plots=options.include_plots,
            include_rt_assignment=options.include_rt_assignment,
            include_pedigree_viz=options.include_pedigree_viz,
            include_splittree=options.include_splittree,
            metric_ids=options.metric_ids if options.include_metrics else [],
            plot_ids=options.plot_ids if options.include_plots else [],
            channels=options.channels
            if (options.include_metrics or options.include_plots)
            else [],
        )
        result = LibraryReportDialogResult(
            options=final_options,
            prerequisites=prerequisites,
        )
        self.grab_release()
        self.destroy()
        self._on_confirm(result)


def show_library_report_dialog(
    master: tk.Misc,
    *,
    section_statuses: List[LibraryReportSectionStatus],
    prerequisites: LibraryReportPrerequisites,
    on_confirm: Callable[[LibraryReportDialogResult], None],
    reassess: Optional[
        Callable[[LibraryReportOptions], LibraryReportPrerequisites]
    ] = None,
) -> None:
    """Open the generate-report dialog."""
    LibraryReportDialog(
        master,
        section_statuses=section_statuses,
        prerequisites=prerequisites,
        on_confirm=on_confirm,
        reassess=reassess,
    )
