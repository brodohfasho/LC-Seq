# src/ui/library_analysis/rt_assignment_panel.py
"""Composed RT assignment responsibilities for Library Analysis."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import List, Optional, Protocol

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.data_store import DataStore
from src.core.library_signal_quality import DEFAULT_SIGNAL_QUALITY_ALPHA
from src.core.pedigree_backend import pedigree_backend_available
from src.core.rt_assignment_export import (
    build_spreadsheet_rows_from_compounds,
    export_rt_analysis_spreadsheet,
    load_compounds_for_export,
)
from src.core.del_cycle_tree import (
    DelCycleTreeData,
    DelCycleTreeView,
    build_assignments_from_del_cycle_tree,
    build_del_cycle_tree_for_path,
    render_del_cycle_tree_figure,
    resolve_compound_rt_assignments_for_path,
)
from src.core.del_cycle_tree.bb_index_scheme import format_bb_branch_label
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import PedigreeAnalysisResult
from src.ui.library_analysis.contexts import (
    LibraryPanelContext,
    RtAssignmentCallbacks,
)
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_TAB_RT_ASSIGNMENT = "RT assignment"
_RT_ANALYSIS_PEDIGREE = "pedigree"
_RT_ANALYSIS_DIRECT = "direct_pick"
_SPLITTREE_RT_SESSION = "Session RT assignment"
_SPLITTREE_VIEW_BRANCH = "BB1 branch"
_SIDEBAR_WRAP = 280


def _primary_action_font() -> ctk.CTkFont:
    """Create the primary-action font after Tk initialization."""
    return ctk.CTkFont(size=14, weight="bold")


class RtAssignmentPanelContext(LibraryPanelContext, Protocol):
    """Typed host surface supplied through composition."""


class RtAssignmentPanel:
    """Own composed RT assignment behavior without importing the host window."""

    def __init__(
        self,
        context: RtAssignmentPanelContext,
        qc_panel: QcPanel,
        callbacks: RtAssignmentCallbacks,
    ) -> None:
        self._context = context
        self._qc_panel = qc_panel
        self._callbacks = callbacks

    def _build_rt_assignment_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """RT assignment settings and run controls."""
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1
        ctk.CTkLabel(actions, text="Analysis mode", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", pady=(0, 4)
        )
        mode_row = ctk.CTkFrame(actions, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 8))
        pedigree_mode_btn = ctk.CTkRadioButton(
            mode_row,
            text="Pedigree",
            variable=self._context._rt_analysis_mode_var,
            value=_RT_ANALYSIS_PEDIGREE,
        )
        pedigree_mode_btn.pack(anchor="w")
        attach_tooltip(
            pedigree_mode_btn,
            "Full-library null-truncation RT assignment (post-paper improvement).",
        )
        direct_mode_btn = ctk.CTkRadioButton(
            mode_row,
            text="Direct pick",
            variable=self._context._rt_analysis_mode_var,
            value=_RT_ANALYSIS_DIRECT,
        )
        direct_mode_btn.pack(anchor="w")
        attach_tooltip(
            direct_mode_btn,
            "Per-compound peak pick for product RTs (paper Methods; pair with Old-school picking).",
        )
        self._context._rt_assignment_run_btn = ctk.CTkButton(
            actions,
            text="Run RT assignment",
            font=_primary_action_font(),
            height=36,
            fg_color="#1F6FEB",
            state="disabled",
            command=self._on_run_rt_assignment,
        )
        self._context._rt_assignment_run_btn.pack(fill="x", pady=(0, 8))
        self._context._busy_sensitive_widgets.append(self._context._rt_assignment_run_btn)
        self._context._pedigree_run_btn = self._context._rt_assignment_run_btn
        self._context._del_cycle_run_btn = self._context._rt_assignment_run_btn
        self._context._pedigree_save_btn = ctk.CTkButton(
            actions,
            text="Save results",
            fg_color="gray40",
            state="disabled",
            command=self._callbacks.save_pedigree,
        )
        self._context._pedigree_save_btn.pack(fill="x", pady=(0, 4))
        self._context._busy_sensitive_widgets.append(self._context._pedigree_save_btn)
        ped_row = ctk.CTkFrame(actions, fg_color="transparent")
        ped_row.pack(fill="x", pady=(0, 4))
        self._context._pedigree_load_btn = ctk.CTkButton(
            ped_row,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=self._callbacks.load_last_pedigree,
        )
        self._context._pedigree_load_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._context._pedigree_browse_btn = ctk.CTkButton(
            ped_row,
            text="Browse…",
            width=90,
            fg_color="gray40",
            command=self._callbacks.browse_pedigree,
        )
        self._context._pedigree_browse_btn.pack(side="left", expand=True, fill="x")
        self._context._busy_sensitive_widgets.extend(
            [self._context._pedigree_load_btn, self._context._pedigree_browse_btn]
        )
        self._context._pedigree_status_label = ctk.CTkLabel(
            actions,
            text="Direct pick reads chromatograms from the database.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._context._pedigree_status_label.pack(fill="x", pady=(4, 0))
        pedigree_box = ctk.CTkFrame(panel, fg_color="transparent")
        pedigree_box.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        row += 1
        assert self._context._config is not None
        pedigree_header = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        pedigree_header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            pedigree_header, text="Count channel", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="left", anchor="w")
        ctk.CTkButton(
            pedigree_header,
            text="? Help",
            width=64,
            height=22,
            fg_color="gray40",
            command=self._callbacks.show_pedigree_help,
        ).pack(side="right")
        channel_menu = ctk.CTkOptionMenu(
            pedigree_box,
            variable=self._context._pedigree_channel_var,
            values=list(self._context._config.count_names) or [""],
        )
        channel_menu.pack(fill="x", pady=(2, 6))
        self._context._busy_sensitive_widgets.append(channel_menu)
        unit_row = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        unit_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(unit_row, text="Time unit", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w"
        )
        unit_btns = ctk.CTkFrame(unit_row, fg_color="transparent")
        unit_btns.pack(fill="x", pady=(2, 0))
        ctk.CTkRadioButton(
            unit_btns,
            text="Seconds",
            variable=self._context._pedigree_time_unit_var,
            value="seconds",
            command=self._on_pedigree_time_unit_changed,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            unit_btns,
            text="Minutes",
            variable=self._context._pedigree_time_unit_var,
            value="minutes",
            command=self._on_pedigree_time_unit_changed,
        ).pack(side="left")
        ctk.CTkLabel(
            pedigree_box, text="Peak picking", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(6, 0))
        picker_menu = ctk.CTkOptionMenu(
            pedigree_box,
            variable=self._context._pedigree_picker_algorithm_var,
            values=["modern", "old_school"],
            command=lambda _v: self._sync_pedigree_picker_widgets(),
        )
        picker_menu.pack(fill="x", pady=(2, 4))
        self._context._busy_sensitive_widgets.append(picker_menu)
        attach_tooltip(
            picker_menu,
            "Modern: NB/Poisson (post-paper). Old-school: Gaussian fits (paper Methods).",
        )
        picker_cols = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        picker_cols.pack(fill="x", pady=(2, 4))
        picker_cols.grid_columnconfigure(0, weight=1, uniform="pedpicker")
        picker_cols.grid_columnconfigure(1, weight=1, uniform="pedpicker")
        modern_col = ctk.CTkFrame(picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        modern_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        old_col = ctk.CTkFrame(picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        old_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._context._pedigree_modern_col = modern_col
        self._context._pedigree_old_col = old_col
        ped_modern_hdr = ctk.CTkLabel(
            modern_col, text="Modern", font=ctk.CTkFont(size=10, weight="bold")
        )
        ped_modern_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        ped_alpha_lbl = ctk.CTkLabel(modern_col, text="Peak significance α")
        ped_alpha_lbl.pack(anchor="w", padx=6)
        ped_alpha_entry = ctk.CTkEntry(modern_col, textvariable=self._context._pedigree_alpha_var)
        ped_alpha_entry.pack(fill="x", padx=6, pady=(2, 4))
        ped_prom_lbl = ctk.CTkLabel(modern_col, text="Min prominence")
        ped_prom_lbl.pack(anchor="w", padx=6)
        ped_prom_entry = ctk.CTkEntry(
            modern_col, textvariable=self._context._pedigree_min_prominence_var
        )
        ped_prom_entry.pack(fill="x", padx=6, pady=(2, 4))
        attach_tooltip(ped_prom_entry, "Drop detected peaks below this prominence (0 = off).")
        ped_pct_lbl = ctk.CTkLabel(modern_col, text="Min % area")
        ped_pct_lbl.pack(anchor="w", padx=6)
        ped_pct_entry = ctk.CTkEntry(
            modern_col, textvariable=self._context._pedigree_min_pct_area_var
        )
        ped_pct_entry.pack(fill="x", padx=6, pady=(2, 8))
        attach_tooltip(
            ped_pct_entry,
            "Drop detected peaks below this share of total detected peak area (0 = off).",
        )
        self._context._busy_sensitive_widgets.extend(
            [ped_alpha_entry, ped_prom_entry, ped_pct_entry]
        )
        self._context._pedigree_modern_widgets.extend(
            [
                ped_modern_hdr,
                ped_alpha_lbl,
                ped_alpha_entry,
                ped_prom_lbl,
                ped_prom_entry,
                ped_pct_lbl,
                ped_pct_entry,
            ]
        )
        ped_old_hdr = ctk.CTkLabel(
            old_col, text="Old-school", font=ctk.CTkFont(size=10, weight="bold")
        )
        ped_old_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        self._context._pedigree_old_school_widgets.append(ped_old_hdr)

        def _ped_old_field(parent, label: str, var: tk.StringVar) -> None:
            lbl = ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=10))
            lbl.pack(anchor="w", padx=6)
            entry = ctk.CTkEntry(parent, textvariable=var)
            entry.pack(fill="x", padx=6, pady=(0, 4))
            self._context._busy_sensitive_widgets.append(entry)
            self._context._pedigree_old_school_widgets.extend([lbl, entry])

        _ped_old_field(old_col, "Min height factor", self._context._pedigree_gaussian_height_var)
        _ped_old_field(
            old_col, "Gaussian fit width", self._context._pedigree_gaussian_fit_width_var
        )
        _ped_old_field(old_col, "Max Gaussian σ", self._context._pedigree_gaussian_stddev_var)
        _ped_old_field(old_col, "Minimum RT", self._context._pedigree_gaussian_min_rt_var)
        ctk.CTkLabel(
            pedigree_box, text="Null RT Threshold", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", pady=(6, 0))
        tol_entry = ctk.CTkEntry(pedigree_box, textvariable=self._context._pedigree_tolerance_var)
        tol_entry.pack(fill="x", pady=(2, 4))
        self._context._busy_sensitive_widgets.append(tol_entry)
        ctk.CTkButton(
            pedigree_box,
            text="Restore defaults",
            height=24,
            fg_color="gray40",
            command=self._restore_pedigree_picker_defaults,
        ).pack(fill="x", pady=(0, 4))
        self._sync_pedigree_picker_widgets()
        pedigree_ready = (
            self._context._config.pedigree_configured()
            and pedigree_backend_available()
            and bool(self._context._config.count_names)
        )
        if not pedigree_ready:
            tip = "Map BB1..BBn columns in Configure Spreadsheet and build the Rust lcseq extension to enable pedigree analysis."
            if not pedigree_backend_available():
                tip = "The Rust lcseq extension is required. See docs/DEVELOPER_SETUP.md."
            attach_tooltip(self._context._rt_assignment_run_btn, tip)
        else:
            attach_tooltip(
                self._context._rt_assignment_run_btn,
                "Assign retention times using pedigree or direct chromatogram pick. Use visualization tabs after a successful run.",
            )
        ctk.CTkLabel(
            panel,
            text="Full databases can assign RTs without a scan. Run library scan first to speed up chromatogram loading. After RT assignment, open Pedigree visualization or Split-tree visualization to view figures.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _build_pedigree_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        """Legacy hook — use ``_build_rt_assignment_sidebar_content``."""
        self._build_rt_assignment_sidebar_content(panel)

    def _init_pedigree_settings(self) -> None:
        """Set pedigree control defaults from loaded spreadsheet config."""
        if self._context._config is None:
            return
        default_channel = (
            self._context._config.count_names[0] if self._context._config.count_names else ""
        )
        self._context._pedigree_channel_var.set(default_channel)
        self._context._pedigree_time_unit_var.set(self._context._config.analysis_time_unit)
        self._context._pedigree_tolerance_var.set(
            "30" if self._context._config.analysis_time_unit == "seconds" else "0.5"
        )
        self._context._pedigree_alpha_var.set(str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._context._pedigree_picker_algorithm_var.set("modern")
        self._apply_pedigree_gaussian_defaults(self._context._config.analysis_time_unit)
        self._context._splittree_isoform_var.set("All")
        self._context._pedigree_variant_choices = self._collect_variant_choices()
        self._sync_pedigree_picker_widgets()
        self._qc_panel._init_qc_picker_settings()

    def _apply_pedigree_gaussian_defaults(self, time_unit: str) -> None:
        unit = "minutes" if time_unit == "minutes" else "seconds"
        g = AnalysisSettings.default_gaussian_params(unit)
        self._context._pedigree_gaussian_height_var.set(str(g["gaussian_min_height_factor"]))
        self._context._pedigree_gaussian_fit_width_var.set(str(g["gaussian_fit_width"]))
        self._context._pedigree_gaussian_stddev_var.set(str(g["gaussian_stddev_threshold"]))
        self._context._pedigree_gaussian_min_rt_var.set(str(g["gaussian_minimum_rt"]))

    def _restore_pedigree_picker_defaults(self) -> None:
        self._context._pedigree_alpha_var.set(str(AnalysisSettings.default_modern_alpha()))
        self._apply_pedigree_gaussian_defaults(self._context._pedigree_time_unit_var.get())
        tol = "30" if self._context._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._context._pedigree_tolerance_var.set(tol)
        self._sync_pedigree_picker_widgets()

    def _on_pedigree_time_unit_changed(self) -> None:
        self._apply_pedigree_gaussian_defaults(self._context._pedigree_time_unit_var.get())
        tol = "30" if self._context._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._context._pedigree_tolerance_var.set(tol)

    def _sync_pedigree_picker_widgets(self) -> None:
        old_school = self._context._pedigree_picker_algorithm_var.get() == "old_school"
        modern_state = "disabled" if old_school else "normal"
        old_state = "normal" if old_school else "disabled"
        modern_fg = ("gray85", "gray25") if not old_school else ("gray78", "gray20")
        old_fg = ("gray85", "gray25") if old_school else ("gray78", "gray20")
        if self._context._pedigree_modern_col is not None:
            self._context._pedigree_modern_col.configure(fg_color=modern_fg)
        if self._context._pedigree_old_col is not None:
            self._context._pedigree_old_col.configure(fg_color=old_fg)
        for widget in self._context._pedigree_modern_widgets:
            try:
                widget.configure(state=modern_state)
            except Exception:
                pass
        for widget in self._context._pedigree_old_school_widgets:
            try:
                widget.configure(state=old_state)
            except Exception:
                pass

    def _collect_variant_choices(self) -> List[str]:
        """Distinct isoform labels from the active database."""
        choices = ["All"]
        if self._context._data_store is None or self._context._config is None:
            return choices
        if not self._context._config.compound_variant_column:
            return choices
        try:
            cursor = self._context._data_store.conn.execute(
                "\n                SELECT DISTINCT compound_variant\n                FROM compounds\n                WHERE compound_variant IS NOT NULL AND TRIM(compound_variant) != ''\n                ORDER BY compound_variant\n                "
            )
            for row in cursor.fetchall():
                label = str(row[0]).strip()
                if label and label not in choices:
                    choices.append(label)
        except Exception as exc:
            logger.warning("Could not load variant choices: %s", exc)
        return choices

    def _ensure_session_del_cycle_after_pedigree(self) -> None:
        """Build split-tree session data after pedigree RT assignment completes."""
        if self._context._pedigree_result is None:
            return
        if self._context._is_busy():
            self._context._schedule_on_main(self._ensure_session_del_cycle_after_pedigree)
            return
        self._context._last_rt_analysis_mode = _RT_ANALYSIS_PEDIGREE
        self._refresh_del_cycle_tree(render_figure=False, show_loading=False)

    def _peek_pedigree_settings(self) -> Optional[AnalysisSettings]:
        """Read pedigree fields without validation dialogs (for cache checks)."""
        if self._context._config is None:
            return None
        channel = self._context._pedigree_channel_var.get().strip()
        if not channel:
            return None
        try:
            tolerance = float(self._context._pedigree_tolerance_var.get().strip())
            alpha = float(self._context._pedigree_alpha_var.get().strip())
            gaussian_min_height_factor = float(
                self._context._pedigree_gaussian_height_var.get().strip()
            )
            gaussian_fit_width = float(self._context._pedigree_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(
                self._context._pedigree_gaussian_stddev_var.get().strip()
            )
            gaussian_minimum_rt = float(self._context._pedigree_gaussian_min_rt_var.get().strip())
        except ValueError:
            return None
        if tolerance <= 0 or alpha <= 0 or alpha >= 1:
            return None
        time_unit = self._context._pedigree_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            return None
        min_prominence, min_pct_area = self._peek_pedigree_quality_params()
        algorithm = self._context._pedigree_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            return None
        stored_unit = (
            "minutes" if self._context._config.analysis_time_unit == "minutes" else "seconds"
        )
        return AnalysisSettings(
            count_channel=channel,
            time_unit=time_unit,
            chromatogram_time_unit=stored_unit,
            peak_picking_algorithm=algorithm,
            alpha=alpha,
            tolerance=tolerance,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            selected_variants=None,
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _picker_label(self) -> str:
        picker = self._context._pedigree_picker_algorithm_var.get()
        return "old-school Gaussian" if picker == "old_school" else "modern NB"

    def _format_analysis_mode_label(self, mode: str) -> str:
        if mode == _RT_ANALYSIS_PEDIGREE:
            return "Pedigree"
        return "Direct pick"

    def _session_rt_assignment_available(self) -> bool:
        return (
            self._context._del_cycle_tree_data is not None
            or self._context._pedigree_result is not None
        )

    def _session_rt_ready_for_splittree(self) -> bool:
        mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
        if mode == _RT_ANALYSIS_PEDIGREE:
            return (
                self._context._pedigree_result is not None
                and self._context._del_cycle_tree_data is not None
            )
        return self._context._del_cycle_tree_data is not None

    def _update_splittree_rt_assignment_status(self) -> None:
        if self._context._splittree_rt_assignment_status_label is None:
            return
        if not self._session_rt_assignment_available():
            self._context._splittree_rt_assignment_status_label.configure(
                text="No RT assignment run in this session.", text_color="gray"
            )
            return
        mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
        if mode == _RT_ANALYSIS_PEDIGREE and self._context._pedigree_result is not None:
            picker = self._context._pedigree_result.settings.peak_picking_algorithm
            lines = [
                "Analysis mode: Pedigree",
                f"Peak picking mode: {self._context._format_peak_picking_mode_label(picker)}",
                f"Nodes evaluated: {len(self._context._pedigree_result.records):,} · chromatograms: {self._context._pedigree_result.n_chromatograms:,}",
            ]
            if self._context._del_cycle_tree_data is not None:
                data = self._context._del_cycle_tree_data
                lines.append(
                    f"Split-tree verification: {data.n_verified:,} RT-verified of {len(data.verified_sequences):,} products."
                )
            elif self._context._is_busy():
                lines.append("Preparing split-tree data…")
            else:
                lines.append("Split-tree data not ready — click Generate plot to build.")
            text_color = ("gray10", "gray90")
        elif self._context._del_cycle_tree_data is not None:
            data = self._context._del_cycle_tree_data
            picker = data.peak_picking_algorithm or ""
            lines = [
                "Analysis mode: Direct pick",
                f"Peak picking mode: {self._context._format_peak_picking_mode_label(picker)}",
                f"RT verified: {data.n_verified:,} of {len(data.verified_sequences):,} products.",
            ]
            text_color = ("gray10", "gray90")
        else:
            lines = ["No RT assignment run in this session."]
            text_color = "gray"
        self._context._splittree_rt_assignment_status_label.configure(
            text="\n".join(lines), text_color=text_color
        )

    def _parse_pedigree_quality_params(self) -> Optional[tuple[float, float]]:
        try:
            min_prominence = float(self._context._pedigree_min_prominence_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Pedigree", "Min prominence must be a number (0 = off).", parent=self._context
            )
            return None
        try:
            min_pct_area = float(self._context._pedigree_min_pct_area_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Pedigree", "Min % area must be a number (0 = off).", parent=self._context
            )
            return None
        if min_prominence < 0:
            messagebox.showerror("Pedigree", "Min prominence must be >= 0.", parent=self._context)
            return None
        if min_pct_area < 0 or min_pct_area > 100:
            messagebox.showerror(
                "Pedigree", "Min % area must be between 0 and 100.", parent=self._context
            )
            return None
        return (min_prominence, min_pct_area)

    def _peek_pedigree_quality_params(self) -> tuple[float, float]:
        try:
            min_prominence = float(self._context._pedigree_min_prominence_var.get().strip())
            min_pct_area = float(self._context._pedigree_min_pct_area_var.get().strip())
        except ValueError:
            return (0.0, 0.0)
        if min_prominence < 0 or min_pct_area < 0 or min_pct_area > 100:
            return (0.0, 0.0)
        return (min_prominence, min_pct_area)

    def _parse_pedigree_settings(self) -> Optional[AnalysisSettings]:
        channel = self._context._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showerror("Pedigree", "Select a count channel.", parent=self._context)
            return None
        try:
            tolerance = float(self._context._pedigree_tolerance_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Pedigree", "Null RT threshold must be a number.", parent=self._context
            )
            return None
        if tolerance <= 0:
            messagebox.showerror(
                "Pedigree", "Null RT threshold must be positive.", parent=self._context
            )
            return None
        try:
            alpha = float(self._context._pedigree_alpha_var.get().strip())
        except ValueError:
            messagebox.showerror("Pedigree", "α must be a number.", parent=self._context)
            return None
        if alpha <= 0 or alpha >= 1:
            messagebox.showerror(
                "Pedigree", "α must be between 0 and 1 (exclusive).", parent=self._context
            )
            return None
        time_unit = self._context._pedigree_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            messagebox.showerror("Pedigree", "Invalid time unit.", parent=self._context)
            return None
        quality = self._parse_pedigree_quality_params()
        if quality is None:
            return None
        min_prominence, min_pct_area = quality
        algorithm = self._context._pedigree_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            messagebox.showerror(
                "Pedigree", "Invalid peak picking algorithm.", parent=self._context
            )
            return None
        try:
            gaussian_min_height_factor = float(
                self._context._pedigree_gaussian_height_var.get().strip()
            )
            gaussian_fit_width = float(self._context._pedigree_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(
                self._context._pedigree_gaussian_stddev_var.get().strip()
            )
            gaussian_minimum_rt = float(self._context._pedigree_gaussian_min_rt_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Pedigree",
                "Old-school peak picker parameters must be numbers.",
                parent=self._context,
            )
            return None
        stored_unit = (
            "minutes"
            if self._context._config and self._context._config.analysis_time_unit == "minutes"
            else "seconds"
        )
        return AnalysisSettings(
            count_channel=channel,
            time_unit=time_unit,
            chromatogram_time_unit=stored_unit,
            peak_picking_algorithm=algorithm,
            alpha=alpha,
            tolerance=tolerance,
            min_prominence=min_prominence,
            min_pct_area=min_pct_area,
            selected_variants=None,
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _update_rt_assignment_results(
        self,
        data: Optional[DelCycleTreeData] = None,
        *,
        pedigree_result: Optional[PedigreeAnalysisResult] = None,
    ) -> None:
        if self._context._rt_assignment_results_label is None:
            return
        if pedigree_result is not None:
            picker = pedigree_result.settings.peak_picking_algorithm
            lines = [
                "Analysis mode: Pedigree",
                f"Peak picking mode: {self._context._format_peak_picking_mode_label(picker)}",
                f"Nodes evaluated: {len(pedigree_result.records):,}",
                f"Chromatograms: {pedigree_result.n_chromatograms:,}",
                "Open Pedigree visualization and click Generate plot to view the tier-ring.",
            ]
            if data is not None:
                lines.append(
                    f"Split-tree verification (optional): {data.n_verified:,} RT-verified products."
                )
            self._context._rt_assignment_results_label.configure(text="\n".join(lines))
            return
        if data is None:
            self._context._rt_assignment_results_label.configure(text="No RT assignment run yet.")
            return
        mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
        picker = data.peak_picking_algorithm or ""
        if mode == _RT_ANALYSIS_PEDIGREE and self._context._pedigree_result is not None:
            if not picker:
                picker = self._context._pedigree_result.settings.peak_picking_algorithm
            self._context._rt_assignment_results_label.configure(
                text=f"Analysis mode: Pedigree\nPeak picking mode: {self._context._format_peak_picking_mode_label(picker)}\nNodes evaluated: {len(self._context._pedigree_result.records):,}\nChromatograms: {self._context._pedigree_result.n_chromatograms:,}\nSplit-tree verification: {data.n_verified:,} RT-verified products.\nOpen Pedigree visualization and click Generate plot to view the tier-ring."
            )
            return
        self._context._rt_assignment_results_label.configure(
            text=f"Analysis mode: Direct pick\nPeak picking mode: {self._context._format_peak_picking_mode_label(picker)}\nProducts with RT: {data.n_rows:,}\nRT verified: {data.n_verified:,}\nFrom pedigree lookup: {data.n_rt_from_pedigree:,} · direct pick: {data.n_rt_from_peak_pick:,} · metadata: {data.n_rt_from_metadata:,}\nOpen Split-tree visualization to view the combinatorial split-tree."
        )

    def _on_run_rt_assignment(self) -> None:
        self._context._session_state.invalidate_splittree()
        self._context._rt_assignment_artifact = None
        self._context._pedigree_viz_artifact = None
        if self._context._rt_analysis_mode_var.get() == _RT_ANALYSIS_PEDIGREE:
            self._context._last_rt_analysis_mode = _RT_ANALYSIS_PEDIGREE
            self._callbacks.run_pedigree()
        else:
            self._context._last_rt_analysis_mode = _RT_ANALYSIS_DIRECT
            self._on_run_direct_pick_assignment()

    def _on_run_direct_pick_assignment(self) -> None:
        if self._context._is_busy():
            return
        if (
            self._context._data_store is None
            or self._context._db_path is None
            or self._context._config is None
        ):
            return
        if not self._context._config.pedigree_configured():
            messagebox.showinfo(
                "RT assignment",
                "Map BB1..BBn columns in Configure Spreadsheet before assigning RTs.",
                parent=self._context,
            )
            return
        if self._parse_pedigree_settings() is None:
            return
        channel = self._context._pedigree_channel_var.get().strip()
        if self._context._cached_scan is not None and channel:
            if channel not in self._context._cached_scan.channel_names:
                messagebox.showinfo(
                    "RT assignment",
                    f"Channel “{channel}” is not in the cached library scan.\n\nAvailable: {', '.join(self._context._cached_scan.channel_names) or 'none'}.\n\nRe-run library scan with this channel selected, or clear the scan to read chromatograms from the database.",
                    parent=self._context,
                )
                return
        if self._context._data_store.get_compound_count() == 0:
            messagebox.showinfo(
                "RT assignment", "The database has no compounds.", parent=self._context
            )
            return
        n = self._context._data_store.get_compound_count()
        if not messagebox.askyesno(
            "RT assignment",
            f"Run full-library direct-pick RT assignment on {n:,} compound(s)?",
            parent=self._context,
        ):
            return
        self._context._focus_tab(_TAB_RT_ASSIGNMENT)
        self._refresh_del_cycle_tree(render_figure=False)

    def _refresh_del_cycle_tree(
        self, *, render_figure: bool = True, show_loading: bool = True
    ) -> None:
        if self._context._is_busy():
            return
        if self._context._data_store is None or self._context._config is None:
            return
        if not self._context._config.pedigree_configured():
            messagebox.showinfo(
                "Split-tree",
                "Map BB1..BBn columns in Configure Spreadsheet before building the tree.",
                parent=self._context,
            )
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return
        channel = self._context._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showinfo("Split-tree", "Select a channel first.", parent=self._context)
            return
        scan = self._context._cached_scan
        self._context._del_build_show_loading = show_loading
        if show_loading:
            scan_note = (
                "Using cached library scan chromatograms…"
                if scan is not None
                else "Loading chromatograms from database…"
            )
            self._context._show_loading_page("Assigning retention times", scan_note)
        assert self._context._db_path is not None
        db_path = self._context._db_path
        config = self._context._config
        use_pedigree = (
            self._context._pedigree_result is not None
            and self._context._last_rt_analysis_mode == _RT_ANALYSIS_PEDIGREE
        )
        pedigree_result = self._context._pedigree_result if use_pedigree else None
        rt_threshold = float(settings.tolerance)
        time_unit = settings.time_unit
        color_by_rt = bool(self._context._pedigree_del_color_rt_var.get())
        color_mode = self._callbacks.split_tree_color_mode()
        pass_pct_cutoff = self._callbacks.split_tree_pass_cutoff()
        view_mode = self._context._splittree_view_mode_var.get()
        branch_selection = self._context._pedigree_del_branch_var.get().strip()
        render_figure = False

        def worker() -> None:
            try:

                def progress(step: int, total: int, status: str) -> None:
                    self._context._raise_if_cancelled()
                    if not self._context._del_build_show_loading:
                        return
                    if total == 1000:
                        fraction = step / 1000.0
                    else:
                        fraction = step / total if total > 0 else 0.0
                    self._context._thread_loading_progress(
                        min(0.95, fraction), status or "Resolving retention times…"
                    )

                data = build_del_cycle_tree_for_path(
                    db_path,
                    config,
                    settings,
                    channel,
                    time_unit,
                    rt_threshold=rt_threshold,
                    pedigree_result=pedigree_result,
                    isoform_label="All",
                    scan=scan,
                    use_metadata_rt=False,
                    progress_callback=progress,
                )
                figure = None
                selected_branch = branch_selection
                if render_figure:
                    view = (
                        DelCycleTreeView.BRANCH
                        if view_mode == _SPLITTREE_VIEW_BRANCH
                        else DelCycleTreeView.FULL
                    )
                    if view == DelCycleTreeView.BRANCH:
                        branches = self._callbacks.sorted_branch_names(data)
                        resolved = self._callbacks.resolve_branch(data, branch_selection)
                        if resolved in branches:
                            selected_branch = resolved
                        elif branches:
                            selected_branch = branches[0]
                    self._context._thread_loading_progress(0.96, "Rendering split-tree figure…")
                    figure = render_del_cycle_tree_figure(
                        data,
                        view=view,
                        branch_bb1=selected_branch if view == DelCycleTreeView.BRANCH else None,
                        color_by_rt=color_by_rt,
                        color_mode=color_mode,
                        pass_pct_cutoff=pass_pct_cutoff,
                    )
                self._context._bind_worker_callback(
                    self._on_del_cycle_tree_ready, data, figure, selected_branch
                )
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Split-tree build failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._on_del_cycle_tree_failed, str(exc))

        self._context._start_worker(worker)

    def _on_del_cycle_tree_ready(
        self, data: DelCycleTreeData, figure: Optional[object], selected_branch: str
    ) -> None:
        self._context._worker_thread = None
        self._context._del_cycle_tree_data = data
        self._context._del_cycle_tree_isoform = "All"
        if self._context._splittree_rt_source_var.get() == _SPLITTREE_RT_SESSION:
            self._context._splittree_viz_data = data
            self._context._splittree_viz_isoform = "All"
        self._callbacks.update_branch_choices(data)
        if selected_branch:
            self._context._pedigree_del_branch_var.set(
                format_bb_branch_label(
                    selected_branch, data.bb_index_global, null_token=data.null_token
                )
            )
        self._callbacks.update_tree_status(data)
        self._update_rt_assignment_results(data)
        settings = self._peek_pedigree_settings()
        if settings is not None:
            mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
            self._callbacks.capture_rt_artifact(
                data,
                analysis_mode=mode,
                settings=settings,
                isoform=self._context._del_cycle_tree_isoform or "All",
            )
        if figure is not None and self._context._splittree_viz_data is data:
            self._callbacks.mount_split_tree(figure)
        if self._context._pedigree_status_label is not None:
            mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
            picker = data.peak_picking_algorithm or ""
            if not picker and self._context._pedigree_result is not None:
                picker = self._context._pedigree_result.settings.peak_picking_algorithm
            self._context._pedigree_status_label.configure(
                text=f"RT assignment ready — {data.n_verified:,} RT-verified of {len(data.verified_sequences):,} products. Analysis mode: {self._format_analysis_mode_label(mode)}. Peak picking mode: {self._context._format_peak_picking_mode_label(picker)}.",
                text_color=("gray10", "gray90"),
            )
        if self._context._del_build_show_loading:
            self._context._hide_loading_page()
        pending_isoform = self._context._pending_splittree_isoform
        if pending_isoform is not None:
            self._context._pending_splittree_isoform = None
            self._callbacks.render_cached_split_tree(pending_isoform, True)
        self._update_splittree_rt_assignment_status()
        self._context._update_action_states()

    def _on_del_cycle_tree_failed(self, message: str) -> None:
        self._context._worker_thread = None
        self._context._pending_splittree_isoform = None
        if self._context._del_build_show_loading:
            self._context._hide_loading_page()
        if not message.strip():
            self._update_splittree_rt_assignment_status()
            self._context._update_action_states()
            return
        self._callbacks.show_split_tree_placeholder(message)
        if self._context._pedigree_status_label is not None:
            self._context._pedigree_status_label.configure(text=message, text_color="#D29922")
        messagebox.showerror("RT assignment", message, parent=self._context)
        self._update_splittree_rt_assignment_status()
        self._context._update_action_states()

    def _on_run_del_cycle_analysis(self) -> None:
        """Legacy alias — direct-pick RT assignment."""
        self._context._rt_analysis_mode_var.set(_RT_ANALYSIS_DIRECT)
        self._on_run_rt_assignment()

    def _on_export_assigned_rts(self) -> None:
        if self._context._is_busy():
            return
        if self._context._pedigree_result is None and self._context._del_cycle_tree_data is None:
            messagebox.showinfo("Export RTs", "Run RT assignment first.", parent=self._context)
            return
        if self._context._config is None or self._context._db_path is None:
            return
        settings = self._parse_pedigree_settings()
        if settings is None:
            return
        channel = self._context._pedigree_channel_var.get().strip()
        if not channel:
            messagebox.showinfo("Export RTs", "Select a channel first.", parent=self._context)
            return
        source_path: Optional[Path] = None
        if self._context.app_state.spreadsheet_path:
            candidate = Path(self._context.app_state.spreadsheet_path)
            if candidate.is_file():
                source_path = candidate
        if source_path is not None:
            default_name = f"{source_path.stem}_rt_analysis{source_path.suffix or '.xlsx'}"
            default_ext = source_path.suffix or ".xlsx"
        else:
            default_name = f"{self._context._db_path.stem}_rt_analysis.xlsx"
            default_ext = ".xlsx"
        dest = filedialog.asksaveasfilename(
            parent=self._context,
            title="Export RT analysis to spreadsheet",
            initialfile=default_name,
            defaultextension=default_ext,
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not dest:
            return
        db_path = self._context._db_path
        config = self._context._config
        scan = self._context._cached_scan
        del_data = self._context._del_cycle_tree_data
        use_pedigree = (
            self._context._pedigree_result is not None
            and self._context._last_rt_analysis_mode == _RT_ANALYSIS_PEDIGREE
        )
        pedigree_result = self._context._pedigree_result if use_pedigree else None
        time_unit = settings.time_unit
        rt_threshold = float(settings.tolerance)
        sheet_name = self._context.config_manager.load_settings().last_loaded_sheet
        self._context._show_loading_page(
            "Exporting RT analysis", "Resolving assigned retention times and null verification…"
        )

        def worker() -> None:
            try:
                store = DataStore(db_path=db_path, use_memory=False)
                try:

                    def load_progress(processed: int, total: int, status: str) -> None:
                        fraction = processed / total if total else 0.0
                        self._context._thread_loading_progress(
                            min(0.45, 0.05 + 0.4 * fraction), status or "Loading library metadata…"
                        )

                    compounds = load_compounds_for_export(
                        store, config, progress_callback=load_progress
                    )
                    self._context._thread_loading_progress(
                        0.55, "Building RT assignments from session results…"
                    )
                    if del_data is not None:
                        assignments = build_assignments_from_del_cycle_tree(
                            compounds, config, del_data, pedigree_result=pedigree_result
                        )
                    else:
                        assignments = resolve_compound_rt_assignments_for_path(
                            db_path,
                            config,
                            settings,
                            channel,
                            time_unit,
                            pedigree_result=pedigree_result,
                            isoform_label="All",
                            scan=scan,
                            use_metadata_rt=False,
                        )
                    spreadsheet_rows = None
                    if source_path is None:

                        def row_progress(processed: int, total: int, status: str) -> None:
                            fraction = processed / total if total else 0.0
                            self._context._thread_loading_progress(
                                min(0.72, 0.58 + 0.14 * fraction),
                                status or "Preparing export rows…",
                            )

                        spreadsheet_rows = build_spreadsheet_rows_from_compounds(
                            compounds, config, store, progress_callback=row_progress
                        )
                    self._context._thread_loading_progress(0.78, "Writing spreadsheet…")
                    result = export_rt_analysis_spreadsheet(
                        dest,
                        config,
                        assignments,
                        source_path=source_path,
                        sheet_name=sheet_name,
                        time_unit=time_unit,
                        rt_threshold=rt_threshold,
                        spreadsheet_rows=spreadsheet_rows,
                    )
                    self._context._bind_worker_callback(self._on_export_rts_ready, result)
                finally:
                    store.close()
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("RT spreadsheet export failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._on_export_rts_failed, str(exc))

        self._context._start_worker(worker)
        self._context._update_action_states()

    def _on_export_rts_ready(self, result) -> None:
        self._context._worker_thread = None
        self._context._hide_loading_page()
        self._context._update_action_states()
        if self._context._pedigree_status_label is not None:
            self._context._pedigree_status_label.configure(
                text=f"Exported RTs — {result.rows_assigned:,} of {result.rows_written:,} row(s) assigned.",
                text_color="green",
            )
        messagebox.showinfo(
            "Export RTs",
            f"Saved to:\n{result.output_path}\n\nAssigned RTs for {result.rows_assigned:,} of {result.rows_written:,} row(s).\nNull pass/fail recorded for {result.rows_with_verification:,} full product(s).",
            parent=self._context,
        )

    def _on_export_rts_failed(self, message: str) -> None:
        self._context._worker_thread = None
        self._context._hide_loading_page()
        self._context._update_action_states()
        messagebox.showerror("Export RTs", message, parent=self._context)
