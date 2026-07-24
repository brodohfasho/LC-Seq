# src/ui/library_analysis/rt_assignment_panel.py
"""Composed RT assignment responsibilities for Library Analysis."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import List, Optional, Protocol, Tuple

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
from src.models.pedigree_result import PedigreeAnalysisResult, PedigreeTierSummary
from src.ui.library_analysis.contexts import (
    LibraryPanelContext,
    RtAssignmentCallbacks,
)
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.qc_panel import QcPanel
from src.ui.quality_filter_ui import (
    QUALITY_MIN_PCT_AREA_LABEL,
    QUALITY_MIN_PROMINENCE_LABEL,
    QUALITY_PCT_AREA_TOOLTIP,
    QUALITY_PROMINENCE_TOOLTIP,
)
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
        self._context._pedigree_modern_widgets.clear()
        self._context._pedigree_old_school_widgets.clear()
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1
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
        self._context._pedigree_status_label = ctk.CTkLabel(
            actions,
            text="Direct pick reads chromatograms from the database.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        )
        self._context._pedigree_status_label.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(actions, text="Analysis mode", font=ctk.CTkFont(size=11, weight="bold")).pack(
            anchor="w", pady=(0, 4)
        )
        mode_row = ctk.CTkFrame(actions, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 4))
        pedigree_mode_btn = ctk.CTkRadioButton(
            mode_row,
            text="Pedigree",
            variable=self._context._rt_analysis_mode_var,
            value=_RT_ANALYSIS_PEDIGREE,
            command=self._sync_rt_parameter_widgets,
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
            command=self._sync_rt_parameter_widgets,
        )
        direct_mode_btn.pack(anchor="w")
        attach_tooltip(
            direct_mode_btn,
            "Per-compound peak pick for product RTs (paper Methods; pair with Old-school picking).",
        )
        pedigree_box = ctk.CTkFrame(panel, fg_color="transparent")
        pedigree_box.grid(row=row, column=0, sticky="ew", padx=8, pady=(0, 8))
        row += 1
        assert self._context._config is not None
        pedigree_header = ctk.CTkFrame(pedigree_box, fg_color="transparent")
        pedigree_header.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            pedigree_header, text="Count channel", font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="left", anchor="w")
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
            command=lambda _v: self._sync_rt_parameter_widgets(),
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
        attach_tooltip(
            ped_alpha_entry,
            "Modern detection only: both height and area p-values must be below α/2.",
        )
        self._context._busy_sensitive_widgets.append(ped_alpha_entry)
        ped_prom_lbl = ctk.CTkLabel(modern_col, text=QUALITY_MIN_PROMINENCE_LABEL)
        ped_prom_lbl.pack(anchor="w", padx=6)
        ped_prom_entry = ctk.CTkEntry(
            modern_col, textvariable=self._context._pedigree_min_prominence_var
        )
        ped_prom_entry.pack(fill="x", padx=6, pady=(2, 4))
        attach_tooltip(ped_prom_entry, QUALITY_PROMINENCE_TOOLTIP)
        ped_pct_lbl = ctk.CTkLabel(modern_col, text=QUALITY_MIN_PCT_AREA_LABEL)
        ped_pct_lbl.pack(anchor="w", padx=6)
        ped_pct_entry = ctk.CTkEntry(
            modern_col, textvariable=self._context._pedigree_min_pct_area_var
        )
        ped_pct_entry.pack(fill="x", padx=6, pady=(2, 8))
        attach_tooltip(ped_pct_entry, QUALITY_PCT_AREA_TOOLTIP)
        self._context._busy_sensitive_widgets.extend([ped_prom_entry, ped_pct_entry])
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
        attach_tooltip(
            tol_entry,
            "Both analysis modes: maximum RT gap for null-truncation checks on the "
            "split-tree. In Pedigree mode this is also the parent→child RT tolerance "
            "during evaluation.",
        )
        self._context._busy_sensitive_widgets.append(tol_entry)
        ctk.CTkButton(
            pedigree_box,
            text="Restore defaults",
            height=24,
            fg_color="gray40",
            command=self._restore_pedigree_picker_defaults,
        ).pack(fill="x", pady=(0, 4))
        self._sync_rt_parameter_widgets()
        pedigree_ready = (
            self._context._config.pedigree_configured()
            and pedigree_backend_available()
            and bool(self._context._config.count_names)
        )
        if not pedigree_ready:
            tip = "Map BB1..BBn columns in Configure Spreadsheet and build the Rust lcseq extension to enable pedigree analysis."
            if not pedigree_backend_available():
                tip = "The Rust lcseq extension is required. See dev/DEVELOPER_SETUP.md."
            attach_tooltip(self._context._rt_assignment_run_btn, tip)
        else:
            attach_tooltip(
                self._context._rt_assignment_run_btn,
                "Assign retention times using pedigree or direct chromatogram pick. Use visualization tabs after a successful run.",
            )

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
        self._sync_rt_parameter_widgets()
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
        prom, pct = AnalysisSettings.default_quality_params()
        self._context._pedigree_min_prominence_var.set(str(prom))
        self._context._pedigree_min_pct_area_var.set(str(pct))
        self._apply_pedigree_gaussian_defaults(self._context._pedigree_time_unit_var.get())
        tol = "30" if self._context._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._context._pedigree_tolerance_var.set(tol)
        self._sync_rt_parameter_widgets()

    def _on_pedigree_time_unit_changed(self) -> None:
        self._apply_pedigree_gaussian_defaults(self._context._pedigree_time_unit_var.get())
        tol = "30" if self._context._pedigree_time_unit_var.get() == "seconds" else "0.5"
        self._context._pedigree_tolerance_var.set(tol)

    def _sync_pedigree_picker_widgets(self) -> None:
        """Backward-compatible alias for ``_sync_rt_parameter_widgets``."""
        self._sync_rt_parameter_widgets()

    def _sync_rt_parameter_widgets(self) -> None:
        """Enable picker controls for the selected analysis mode × picker."""
        old_school = self._context._pedigree_picker_algorithm_var.get() == "old_school"
        busy = False
        try:
            busy = bool(self._context._is_busy())
        except Exception:
            busy = False
        modern_state = "disabled" if (busy or old_school) else "normal"
        old_state = "disabled" if (busy or not old_school) else "normal"
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
        """Render the centered RT assignment summary table."""
        frame = getattr(self._context, "_rt_assignment_results_frame", None)
        if frame is None:
            logger.warning("RT assignment results frame is missing; cannot show summary.")
            return
        try:
            self._qc_panel._clear_frame_children(frame)

            if pedigree_result is not None:
                self._render_rt_results_table(
                    frame,
                    title="Pedigree RT assignment",
                    subtitle=self._format_rt_results_subtitle(
                        mode=_RT_ANALYSIS_PEDIGREE,
                        picker=pedigree_result.settings.peak_picking_algorithm,
                    ),
                    rows=self._pedigree_result_rows(pedigree_result, data),
                    footnote=(
                        "Open Pedigree visualization and click Generate plot to view the tier-ring."
                    ),
                    tier_summaries=list(pedigree_result.tier_summaries),
                )
            elif data is None:
                empty = ctk.CTkFrame(
                    frame,
                    corner_radius=14,
                    fg_color=("gray92", "gray20"),
                    border_width=1,
                    border_color=("gray80", "gray30"),
                )
                empty.pack(fill="x", padx=24, pady=40)
                ctk.CTkLabel(
                    empty,
                    text="No RT assignment run yet",
                    font=ctk.CTkFont(size=20, weight="bold"),
                    anchor="center",
                ).pack(padx=28, pady=(28, 8), fill="x")
                ctk.CTkLabel(
                    empty,
                    text=(
                        "Choose Direct pick or Pedigree in the sidebar, set parameters, "
                        "then click Run RT assignment."
                    ),
                    font=ctk.CTkFont(size=14),
                    text_color="gray",
                    anchor="center",
                    wraplength=640,
                    justify="center",
                ).pack(padx=28, pady=(0, 28), fill="x")
            else:
                mode = self._context._last_rt_analysis_mode or _RT_ANALYSIS_DIRECT
                picker = data.peak_picking_algorithm or ""
                if mode == _RT_ANALYSIS_PEDIGREE and self._context._pedigree_result is not None:
                    pedigree = self._context._pedigree_result
                    if not picker:
                        picker = pedigree.settings.peak_picking_algorithm
                    self._render_rt_results_table(
                        frame,
                        title="Pedigree RT assignment",
                        subtitle=self._format_rt_results_subtitle(mode=mode, picker=picker),
                        rows=self._pedigree_result_rows(pedigree, data),
                        footnote=(
                            "Open Pedigree visualization and click Generate plot "
                            "to view the tier-ring."
                        ),
                        tier_summaries=list(pedigree.tier_summaries),
                    )
                else:
                    self._render_rt_results_table(
                        frame,
                        title="Direct pick RT assignment",
                        subtitle=self._format_rt_results_subtitle(mode=mode, picker=picker),
                        rows=self._direct_pick_result_rows(data),
                        footnote=(
                            "Open Split-tree visualization to view the combinatorial split-tree."
                        ),
                    )
            try:
                self._context._focus_tab(_TAB_RT_ASSIGNMENT)
                frame.update_idletasks()
            except tk.TclError:
                pass
        except Exception:
            logger.exception("Failed to render RT assignment results summary")
            try:
                self._qc_panel._clear_frame_children(frame)
                ctk.CTkLabel(
                    frame,
                    text="RT assignment finished, but the results summary could not be displayed.",
                    font=ctk.CTkFont(size=14),
                    text_color="#D29922",
                    anchor="w",
                    wraplength=640,
                    justify="left",
                ).pack(fill="x", padx=24, pady=24)
            except Exception:
                logger.exception("Could not show RT assignment results fallback message")

    def _format_rt_results_subtitle(self, *, mode: str, picker: str) -> str:
        return (
            f"{self._format_analysis_mode_label(mode)}"
            f"  ·  Peak picking: {self._context._format_peak_picking_mode_label(picker)}"
        )

    def _direct_pick_result_rows(
        self, data: DelCycleTreeData
    ) -> List[Tuple[str, str]]:
        n_products = len(data.verified_sequences) or data.n_rows
        n_failed = max(0, n_products - data.n_verified)
        return [
            ("Products with assigned RT", f"{data.n_rows:,}"),
            (
                "Passed null verification",
                f"{data.n_verified:,} of {n_products:,}",
            ),
            (
                "Null-matching products",
                f"{n_failed:,} of {n_products:,}",
            ),
            ("Null RT threshold", f"{data.rt_threshold:g}"),
            ("Library cycles", f"{data.library_cycle_count}"),
        ]

    def _pedigree_result_rows(
        self,
        pedigree: PedigreeAnalysisResult,
        data: Optional[DelCycleTreeData],
    ) -> List[Tuple[str, str]]:
        settings = pedigree.settings
        picker_label = self._context._format_peak_picking_mode_label(
            settings.peak_picking_algorithm
        )
        rows: List[Tuple[str, str]] = [
            ("Nodes evaluated", f"{len(pedigree.records):,}"),
            ("Chromatograms", f"{pedigree.n_chromatograms:,}"),
            ("Count channel", str(pedigree.channel)),
            ("Peak picking mode", picker_label),
            (
                "Null RT threshold",
                f"{settings.tolerance:g} {settings.time_unit}",
            ),
        ]
        if settings.uses_modern_peak_picker:
            rows.append(("Modern α", f"{settings.alpha:g}"))
        if settings.uses_modern_peak_picker and (
            settings.min_prominence > 0 or settings.min_pct_area > 0
        ):
            rows.append(
                (
                    "Quality filters",
                    (
                        f"prominence ≥ {settings.min_prominence:g}, "
                        f"%area ≥ {settings.min_pct_area:g}"
                    ),
                )
            )
        if pedigree.isoform_label and pedigree.isoform_label != "All":
            rows.append(("Isoform filter", pedigree.isoform_label))
        if data is not None:
            n_products = len(data.verified_sequences) or data.n_rows
            n_failed = max(0, n_products - data.n_verified)
            rows.extend(
                [
                    (
                        "Passed null verification",
                        f"{data.n_verified:,} of {n_products:,}",
                    ),
                    (
                        "Null-matching products",
                        f"{n_failed:,} of {n_products:,}",
                    ),
                ]
            )
        return rows

    def _render_rt_results_table(
        self,
        parent: ctk.CTkFrame,
        *,
        title: str,
        subtitle: str,
        rows: List[Tuple[str, str]],
        footnote: str = "",
        tier_summaries: Optional[List[PedigreeTierSummary]] = None,
    ) -> None:
        """Build a large centered results card with Metric | Value rows."""
        card = ctk.CTkFrame(
            parent,
            corner_radius=14,
            fg_color=("gray94", "gray18"),
            border_width=1,
            border_color=("gray78", "gray32"),
        )
        card.pack(fill="x", padx=24, pady=(16, 24))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=28, pady=(24, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text=subtitle,
            font=ctk.CTkFont(size=14),
            text_color=("gray35", "gray70"),
            anchor="w",
        ).grid(row=1, column=0, padx=28, pady=(0, 16), sticky="w")

        table = ctk.CTkFrame(card, fg_color="transparent")
        table.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))
        table.grid_columnconfigure(0, weight=1)
        table.grid_columnconfigure(1, weight=1)

        header = ctk.CTkFrame(
            table,
            corner_radius=8,
            fg_color=("gray88", "gray24"),
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="Metric",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=16, pady=10, sticky="w")
        ctk.CTkLabel(
            header,
            text="Value",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="e",
        ).grid(row=0, column=1, padx=16, pady=10, sticky="e")

        for index, (metric, value) in enumerate(rows):
            row_bg = ("gray90", "gray22") if index % 2 == 0 else ("gray96", "gray16")
            row_frame = ctk.CTkFrame(
                table,
                corner_radius=8,
                fg_color=row_bg,
            )
            row_frame.grid(row=index + 1, column=0, columnspan=2, sticky="ew", pady=3)
            row_frame.grid_columnconfigure(0, weight=1)
            row_frame.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row_frame,
                text=metric,
                font=ctk.CTkFont(size=15),
                anchor="w",
            ).grid(row=0, column=0, padx=16, pady=12, sticky="w")
            ctk.CTkLabel(
                row_frame,
                text=value,
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=("#0969da", "#58a6ff"),
                anchor="e",
            ).grid(row=0, column=1, padx=16, pady=12, sticky="e")

        next_row = 3
        if tier_summaries:
            tier_card = ctk.CTkFrame(card, fg_color="transparent")
            tier_card.grid(row=next_row, column=0, sticky="ew", padx=20, pady=(12, 4))
            tier_card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                tier_card,
                text="By coupling tier",
                font=ctk.CTkFont(size=16, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, padx=8, pady=(4, 8), sticky="w")

            tier_table = ctk.CTkFrame(tier_card, fg_color="transparent")
            tier_table.grid(row=1, column=0, sticky="ew", padx=4)
            for col in range(4):
                tier_table.grid_columnconfigure(col, weight=1)

            for col, heading in enumerate(("Tier", "Pass", "Fail", "Pruned")):
                ctk.CTkLabel(
                    tier_table,
                    text=heading,
                    font=ctk.CTkFont(size=13, weight="bold"),
                    anchor="center",
                ).grid(row=0, column=col, padx=6, pady=(0, 6), sticky="ew")

            for row_idx, summary in enumerate(tier_summaries, start=1):
                values = (
                    str(summary.tier),
                    f"{summary.pass_count:,}",
                    f"{summary.fail_count:,}",
                    f"{summary.pruned_count:,}",
                )
                row_bg = (
                    ("gray90", "gray22") if row_idx % 2 else ("gray96", "gray16")
                )
                for col, value in enumerate(values):
                    cell = ctk.CTkFrame(
                        tier_table,
                        corner_radius=6,
                        fg_color=row_bg,
                    )
                    cell.grid(row=row_idx, column=col, sticky="ew", padx=3, pady=2)
                    ctk.CTkLabel(
                        cell,
                        text=value,
                        font=ctk.CTkFont(size=15, weight="bold" if col else "normal"),
                        anchor="center",
                    ).pack(padx=8, pady=10)
            next_row += 1

        if footnote:
            ctk.CTkLabel(
                card,
                text=footnote,
                font=ctk.CTkFont(size=13),
                text_color=("gray40", "gray65"),
                anchor="w",
                wraplength=720,
                justify="left",
            ).grid(row=next_row, column=0, padx=28, pady=(12, 24), sticky="w")

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
        # Hide the overlay before painting results — updating a CTkScrollableFrame while
        # the content tabview is grid_removed often leaves a blank results area.
        if self._context._del_build_show_loading:
            self._context._hide_loading_page()
        self._update_rt_assignment_results(data)
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
