# src/ui/library_analysis/qc_panel.py
"""Composed QcPanel responsibilities for Library Analysis."""

from __future__ import annotations

import logging
import os
import shutil
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Tuple

import customtkinter as ctk
from tkinter import filedialog, messagebox

from src.core.library_metrics import (
    DEFAULT_FRACTION_COUNT,
    ChannelAggregateStats,
    LibraryComputationSnapshot,
    LibraryScanData,
    PlotResult,
    build_snapshot_from_scan,
    compute_metrics_from_scan,
    export_metrics_summary_csv,
    list_library_metric_definitions_by_category,
    scan_library_for_path,
)
from src.core.library_metrics import LIBRARY_METRIC_DEFINITIONS, SIGNAL_QUALITY_METRIC_IDS
from src.core.library_metrics_store import (
    database_paths_match,
    delete_all_saved_snapshots,
    delete_all_session_scans,
    export_scan_pickle,
    get_latest_snapshot_path,
    get_library_data_dir,
    list_session_scan_paths,
    list_snapshots,
    load_scan_pickle,
    load_session_scan,
    load_snapshot,
    save_session_scan,
    save_snapshot,
    session_plots_dir,
    snapshot_plots_dir,
    suggested_scan_export_filename,
    validate_scan_for_database,
)
from src.core.library_plots import (
    generate_plots,
    list_library_plot_definitions_by_category,
)
from src.core.library_signal_quality import (
    DEFAULT_SIGNAL_QUALITY_ALPHA,
    SignalQualityComputeOptions,
    attach_signal_quality_to_entries,
    export_per_entry_signal_csv,
)
from src.models.analysis_settings import AnalysisSettings
from src.ui.library_analysis.contexts import LibraryPanelContext, QcPanelCallbacks
from src.ui.library_analysis.models import LibraryOperationCancelled
from src.ui.library_analysis.task_coordinator import TaskCoordinator
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_TAB_METRICS = "Library QC metrics"
_TAB_PLOTS = "Library QC visualizations"

_SIDEBAR_WRAP = 280
_PLOT_PREVIEW_MAX_WIDTH = 820
_PLOT_LIST_BUTTON_HEIGHT = 52
_SECTION_HEADER_COLOR = ("#0969da", "#58a6ff")


def _section_header_font() -> ctk.CTkFont:
    """Create the shared section-header font after Tk initialization."""
    return ctk.CTkFont(size=14, weight="bold")


def _primary_action_font() -> ctk.CTkFont:
    """Create the shared primary-action font after Tk initialization."""
    return ctk.CTkFont(size=14, weight="bold")


def _tk_preview_bg() -> str:
    """Return the appearance-aware background for Tk plot previews."""
    return ctk.ThemeManager.theme["CTkFrame"]["fg_color"][
        1 if ctk.get_appearance_mode() == "Dark" else 0
    ]


class QcPanelContext(LibraryPanelContext, Protocol):
    """Typed host surface supplied by the composed Library Analysis window."""


class QcPanel:
    """Own extracted qcpanel behavior without importing the window."""

    def __init__(self, context: QcPanelContext, callbacks: QcPanelCallbacks) -> None:
        self._context = context
        self._callbacks = callbacks
        self._restore_tasks: Optional[TaskCoordinator] = None

    def close(self) -> None:
        """Cancel a pending background session-scan restore."""
        if self._restore_tasks is not None:
            self._restore_tasks.cancel_active()

    def _pack_save_load_row(
        self,
        parent: ctk.CTkFrame,
        *,
        save_command: Callable[[], None],
        load_command: Callable[[], None],
        browse_command: Callable[[], None],
    ) -> Tuple[ctk.CTkButton, ctk.CTkButton, ctk.CTkButton]:
        """Build the shared QC save/load/browse controls."""
        save_btn = ctk.CTkButton(parent, text="Save results", command=save_command)
        save_btn.pack(fill="x", pady=(0, 4))
        self._context._busy_sensitive_widgets.append(save_btn)

        row_btns = ctk.CTkFrame(parent, fg_color="transparent")
        row_btns.pack(fill="x", pady=(0, 4))
        load_btn = ctk.CTkButton(
            row_btns,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=load_command,
        )
        load_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        browse_btn = ctk.CTkButton(
            row_btns,
            text="Browse…",
            width=90,
            fg_color="gray40",
            command=browse_command,
        )
        browse_btn.pack(side="left", expand=True, fill="x")
        self._context._busy_sensitive_widgets.extend([load_btn, browse_btn])
        return save_btn, load_btn, browse_btn

    def _build_metrics_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        self._context._metrics_btn = ctk.CTkButton(
            actions,
            text="Calculate metrics",
            font=_primary_action_font(),
            height=36,
            command=self._on_calculate_metrics,
        )
        self._context._metrics_btn.pack(fill="x", pady=(0, 8))
        self._context._busy_sensitive_widgets.append(self._context._metrics_btn)

        self._context._save_btn = ctk.CTkButton(
            actions,
            text="Save results",
            command=self._on_save,
        )
        self._context._save_btn.pack(fill="x", pady=(0, 4))
        self._context._busy_sensitive_widgets.append(self._context._save_btn)

        metrics_load_row = ctk.CTkFrame(actions, fg_color="transparent")
        metrics_load_row.pack(fill="x", pady=(0, 4))
        self._context._load_last_btn = ctk.CTkButton(
            metrics_load_row,
            text="Load last",
            width=90,
            fg_color="gray40",
            command=self._on_load_last,
        )
        self._context._load_last_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._context._clear_metrics_results_btn = ctk.CTkButton(
            metrics_load_row,
            text="Clear all results",
            width=90,
            fg_color="gray40",
            command=self._on_clear_all_metrics_results,
        )
        self._context._clear_metrics_results_btn.pack(side="left", expand=True, fill="x")
        self._context._busy_sensitive_widgets.extend(
            [self._context._load_last_btn, self._context._clear_metrics_results_btn]
        )

        self._context._browse_btn = ctk.CTkButton(
            actions,
            text="Browse…",
            fg_color="gray40",
            command=self._on_browse_saved,
        )
        self._context._browse_btn.pack(fill="x", pady=(0, 4))
        self._context._busy_sensitive_widgets.append(self._context._browse_btn)

        ctk.CTkLabel(
            panel,
            text="Count channels",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 4))
        row += 1

        assert self._context._config is not None
        for channel_name in self._context._config.count_names:
            var = tk.BooleanVar(value=True)
            self._context._channel_vars[channel_name] = var
            cb = ctk.CTkCheckBox(
                panel,
                text=channel_name,
                variable=var,
                command=self._context._update_action_states,
            )
            cb.grid(row=row, column=0, sticky="w", padx=12, pady=1)
            self._context._busy_sensitive_widgets.append(cb)
            row += 1

        ctk.CTkLabel(
            panel,
            text="Metrics",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(10, 4))
        row += 1

        for category, label in (("coverage", "Coverage"), ("signal", "Signal quality")):
            ctk.CTkLabel(
                panel,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
            ).grid(row=row, column=0, sticky="w", padx=12, pady=(2, 0))
            row += 1
            for definition in list_library_metric_definitions_by_category(category):
                var = tk.BooleanVar(value=True)
                self._context._metric_vars[definition.metric_id] = var
                cb = ctk.CTkCheckBox(
                    panel,
                    text=definition.title.split(" — ")[0],
                    variable=var,
                    command=self._context._update_action_states,
                )
                cb.grid(row=row, column=0, sticky="w", padx=16, pady=1)
                attach_tooltip(cb, definition.help_text)
                self._context._busy_sensitive_widgets.append(cb)
                row += 1

        params = ctk.CTkFrame(panel, fg_color="transparent")
        params.grid(row=row, column=0, sticky="ew", padx=8, pady=(10, 4))
        row += 1
        ctk.CTkLabel(params, text="Fraction count", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w"
        )
        frac_entry = ctk.CTkEntry(params, textvariable=self._context._fraction_count_var)
        frac_entry.pack(fill="x", pady=(2, 6))
        attach_tooltip(frac_entry, "Used for library coverage index.")

        ctk.CTkLabel(params, text="Peak picking", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", pady=(4, 0)
        )
        qc_picker_menu = ctk.CTkOptionMenu(
            params,
            variable=self._context._qc_picker_algorithm_var,
            values=["modern", "old_school"],
            command=lambda _v: self._sync_qc_picker_widgets(),
        )
        qc_picker_menu.pack(fill="x", pady=(2, 4))
        self._context._busy_sensitive_widgets.append(qc_picker_menu)
        attach_tooltip(
            qc_picker_menu,
            "Modern: NB/Poisson significance for QC signal metrics (post-paper). "
            "Old-school: Gaussian fits (paper Methods).",
        )

        qc_picker_cols = ctk.CTkFrame(params, fg_color="transparent")
        qc_picker_cols.pack(fill="x", pady=(2, 4))
        qc_picker_cols.grid_columnconfigure(0, weight=1, uniform="qcpicker")
        qc_picker_cols.grid_columnconfigure(1, weight=1, uniform="qcpicker")

        qc_modern_col = ctk.CTkFrame(qc_picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        qc_modern_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        qc_old_col = ctk.CTkFrame(qc_picker_cols, fg_color=("gray85", "gray25"), corner_radius=6)
        qc_old_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._context._qc_modern_col = qc_modern_col
        self._context._qc_old_col = qc_old_col

        qc_modern_hdr = ctk.CTkLabel(
            qc_modern_col, text="Modern", font=ctk.CTkFont(size=10, weight="bold")
        )
        qc_modern_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        qc_alpha_lbl = ctk.CTkLabel(qc_modern_col, text="Peak significance α")
        qc_alpha_lbl.pack(anchor="w", padx=6)
        qc_alpha_entry = ctk.CTkEntry(qc_modern_col, textvariable=self._context._qc_alpha_var)
        qc_alpha_entry.pack(fill="x", padx=6, pady=(2, 8))
        attach_tooltip(
            qc_alpha_entry,
            "α for significant-peak metrics and signal plots. A local maximum counts as "
            "significant only when both height and area p-values are below α/2. Lower α → "
            "fewer significant peaks.",
        )
        self._context._busy_sensitive_widgets.append(qc_alpha_entry)
        self._context._qc_modern_widgets.extend([qc_modern_hdr, qc_alpha_lbl, qc_alpha_entry])

        qc_old_hdr = ctk.CTkLabel(
            qc_old_col, text="Old-school", font=ctk.CTkFont(size=10, weight="bold")
        )
        qc_old_hdr.pack(anchor="w", padx=6, pady=(6, 2))
        self._context._qc_old_school_widgets.append(qc_old_hdr)

        def _qc_old_field(parent, label: str, var: tk.StringVar) -> None:
            lbl = ctk.CTkLabel(parent, text=label, font=ctk.CTkFont(size=10))
            lbl.pack(anchor="w", padx=6)
            entry = ctk.CTkEntry(parent, textvariable=var)
            entry.pack(fill="x", padx=6, pady=(0, 4))
            self._context._busy_sensitive_widgets.append(entry)
            self._context._qc_old_school_widgets.extend([lbl, entry])

        _qc_old_field(qc_old_col, "Min height factor", self._context._qc_gaussian_height_var)
        _qc_old_field(qc_old_col, "Gaussian fit width", self._context._qc_gaussian_fit_width_var)
        _qc_old_field(qc_old_col, "Max Gaussian σ", self._context._qc_gaussian_stddev_var)
        _qc_old_field(qc_old_col, "Minimum RT", self._context._qc_gaussian_min_rt_var)

        ctk.CTkButton(
            params,
            text="Restore QC picker defaults",
            height=24,
            fg_color="gray40",
            command=self._restore_qc_picker_defaults,
        ).pack(fill="x", pady=(0, 4))
        self._sync_qc_picker_widgets()

        ctk.CTkLabel(
            panel,
            text=(
                "Run library scan first (top bar). Metrics are computed from that "
                "parsed scan without re-reading the database."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _build_plots_sidebar_content(self, panel: ctk.CTkScrollableFrame) -> None:
        row = 0
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=row, column=0, sticky="ew", padx=8, pady=(4, 12))
        row += 1

        self._context._plots_btn = ctk.CTkButton(
            actions,
            text="Generate plots",
            font=_primary_action_font(),
            height=36,
            command=self._on_generate_plots,
        )
        self._context._plots_btn.pack(fill="x", pady=(0, 8))
        self._context._busy_sensitive_widgets.append(self._context._plots_btn)

        (
            self._context._plots_save_btn,
            self._context._plots_load_btn,
            self._context._plots_browse_btn,
        ) = self._pack_save_load_row(
            actions,
            save_command=self._on_save,
            load_command=self._on_load_last,
            browse_command=self._on_browse_saved,
        )

        self._context._export_plots_csv_btn = ctk.CTkButton(
            actions,
            text="Export plot data CSV…",
            fg_color="gray40",
            command=self._on_export_signal_csv,
        )
        self._context._export_plots_csv_btn.pack(fill="x", pady=(0, 4))
        self._context._busy_sensitive_widgets.append(self._context._export_plots_csv_btn)

        ctk.CTkLabel(
            panel,
            text="Plots",
            font=_section_header_font(),
            text_color=_SECTION_HEADER_COLOR,
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 4))
        row += 1

        for category, label in (("coverage", "Coverage"), ("signal", "Signal quality")):
            ctk.CTkLabel(
                panel,
                text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="gray",
            ).grid(row=row, column=0, sticky="w", padx=12, pady=(2, 0))
            row += 1
            for definition in list_library_plot_definitions_by_category(category):
                var = tk.BooleanVar(value=True)
                self._context._plot_vars[definition.plot_id] = var
                cb = ctk.CTkCheckBox(
                    panel,
                    text=definition.title,
                    variable=var,
                    command=self._context._update_action_states,
                )
                cb.grid(row=row, column=0, sticky="w", padx=16, pady=1)
                attach_tooltip(cb, definition.help_text)
                self._context._busy_sensitive_widgets.append(cb)
                row += 1

        ctk.CTkLabel(
            panel,
            text=(
                "Plots reuse the library scan from the top bar. Signal-quality plots "
                "use peak parameters from the Summary metrics sidebar."
            ),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=_SIDEBAR_WRAP,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 6))

    def _init_qc_picker_settings(self) -> None:
        """Set library QC picker defaults from loaded spreadsheet config."""
        if self._context._config is None:
            return
        unit = self._context._config.analysis_time_unit
        self._context._qc_time_unit_var.set(unit)
        self._context._qc_alpha_var.set(str(DEFAULT_SIGNAL_QUALITY_ALPHA))
        self._context._qc_picker_algorithm_var.set("modern")
        self._apply_qc_gaussian_defaults(unit)
        self._sync_qc_picker_widgets()

    def _apply_qc_gaussian_defaults(self, time_unit: str) -> None:
        unit = "minutes" if time_unit == "minutes" else "seconds"
        g = AnalysisSettings.default_gaussian_params(unit)  # type: ignore[arg-type]
        self._context._qc_gaussian_height_var.set(str(g["gaussian_min_height_factor"]))
        self._context._qc_gaussian_fit_width_var.set(str(g["gaussian_fit_width"]))
        self._context._qc_gaussian_stddev_var.set(str(g["gaussian_stddev_threshold"]))
        self._context._qc_gaussian_min_rt_var.set(str(g["gaussian_minimum_rt"]))

    def _restore_qc_picker_defaults(self) -> None:
        self._context._qc_alpha_var.set(str(AnalysisSettings.default_modern_alpha()))
        self._apply_qc_gaussian_defaults(self._context._qc_time_unit_var.get())
        self._sync_qc_picker_widgets()

    def _sync_qc_picker_widgets(self) -> None:
        old_school = self._context._qc_picker_algorithm_var.get() == "old_school"
        modern_state = "disabled" if old_school else "normal"
        old_state = "normal" if old_school else "disabled"
        modern_fg = ("gray85", "gray25") if not old_school else ("gray78", "gray20")
        old_fg = ("gray85", "gray25") if old_school else ("gray78", "gray20")
        if self._context._qc_modern_col is not None:
            self._context._qc_modern_col.configure(fg_color=modern_fg)
        if self._context._qc_old_col is not None:
            self._context._qc_old_col.configure(fg_color=old_fg)
        for widget in self._context._qc_modern_widgets:
            try:
                widget.configure(state=modern_state)
            except Exception:
                pass
        for widget in self._context._qc_old_school_widgets:
            try:
                widget.configure(state=old_state)
            except Exception:
                pass

    def _selected_signal_metric_ids(self) -> List[str]:
        return [mid for mid in self._get_selected_metric_ids() if mid in SIGNAL_QUALITY_METRIC_IDS]

    def _selected_signal_plot_ids(self) -> List[str]:
        signal_ids = {p.plot_id for p in list_library_plot_definitions_by_category("signal")}
        return [pid for pid in self._get_selected_plot_ids() if pid in signal_ids]

    def _signal_quality_is_cached(
        self,
        channels: List[str],
        options: SignalQualityComputeOptions,
    ) -> bool:
        scan = self._context._cached_scan
        if scan is None or scan.signal_quality_options is None:
            return False
        if scan.signal_quality_options != options:
            return False
        return all(ch in scan.signal_quality_by_channel for ch in channels)

    def _confirm_library_scan(self, entry_count: int) -> bool:
        overwrite_note = ""
        if self._context._cached_scan is not None:
            loaded = self._scan_entry_count(self._context._cached_scan)
            overwrite_note = (
                f"A library scan is already loaded ({loaded:,} entries parsed). "
                "Running a new scan will replace it and discard metrics, plots, and "
                "other results that depend on the current scan.\n\n"
            )
        index_note = (
            "Index databases parse raw chromatogram text for each entry, so this step "
            "is often the slowest part of a session.\n\n"
            if self._context._index_db_mode
            else ""
        )
        return self._context._confirm_long_operation(
            f"This will scan {entry_count:,} library entries across the selected "
            f"count channel(s).\n\n"
            f"{overwrite_note}"
            f"{index_note}"
            "Large libraries can take several minutes. You can cancel while the scan "
            "runs, but partial results will be discarded.\n\n"
            "Continue?"
        )

    def _confirm_metrics_computation(self, entry_count: int, metric_ids: List[str]) -> bool:
        signal_metrics = [mid for mid in metric_ids if mid in SIGNAL_QUALITY_METRIC_IDS]
        channels = self._get_selected_channels()
        qc_settings = self._peek_qc_signal_settings()
        if (
            signal_metrics
            and qc_settings is not None
            and self._signal_quality_is_cached(channels, qc_settings)
        ):
            signal_note = (
                "Signal metrics are selected, but per-entry peak analysis was already "
                "computed for the current scan and QC picker settings — aggregation "
                "should be relatively quick.\n\n"
            )
        elif signal_metrics:
            signal_note = (
                "Signal metrics are selected. This includes per-entry peak analysis across "
                f"{entry_count:,} entries and may take a long time.\n\n"
            )
        else:
            signal_note = (
                "Coverage-only metrics aggregate the existing scan and are usually faster "
                "than signal metrics.\n\n"
            )
        return self._context._confirm_long_operation(
            f"Calculate {len(metric_ids)} metric(s) for {entry_count:,} scanned entries?\n\n"
            f"{signal_note}"
            "You can cancel while this runs; previously calculated metrics in this "
            "session will be kept.\n\n"
            "Continue?"
        )

    def _confirm_plot_generation(self, entry_count: int, plot_ids: List[str]) -> bool:
        signal_plots = self._selected_signal_plot_ids()
        channels = self._get_selected_channels()
        qc_settings = self._peek_qc_signal_settings()
        if (
            signal_plots
            and qc_settings is not None
            and self._signal_quality_is_cached(channels, qc_settings)
        ):
            signal_note = (
                "Signal plots are selected, but per-entry peak analysis is already cached "
                "from metrics or a prior plot run — rendering should be faster.\n\n"
            )
        elif signal_plots:
            signal_note = (
                "Signal plots are selected. Peak analysis runs across "
                f"{entry_count:,} entries before rendering and may take a long time.\n\n"
            )
        else:
            signal_note = (
                "Coverage plots use the existing scan only and are usually the quickest "
                "plots to generate.\n\n"
            )
        return self._context._confirm_long_operation(
            f"Generate {len(plot_ids)} plot type(s) for {len(channels)} channel(s)?\n\n"
            f"{signal_note}"
            "You can cancel while this runs; plots already on screen will be kept.\n\n"
            "Continue?"
        )

    def _get_selected_channels(self) -> List[str]:
        return [name for name, var in self._context._channel_vars.items() if var.get()]

    def _get_selected_plot_ids(self) -> List[str]:
        return [pid for pid, var in self._context._plot_vars.items() if var.get()]

    def _get_selected_metric_ids(self) -> List[str]:
        return [mid for mid, var in self._context._metric_vars.items() if var.get()]

    def _parse_fraction_count(self) -> Optional[int]:
        raw = self._context._fraction_count_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Fraction count must be a positive integer.",
                parent=self,
            )
            return None
        if value <= 0:
            messagebox.showerror(
                "Library Analysis",
                "Fraction count must be greater than zero.",
                parent=self,
            )
            return None
        return value

    def _parse_qc_signal_settings(self) -> Optional[SignalQualityComputeOptions]:
        algorithm = self._context._qc_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            messagebox.showerror(
                "Library Analysis",
                "Invalid peak picking algorithm for QC metrics.",
                parent=self,
            )
            return None
        time_unit = self._context._qc_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            messagebox.showerror("Library Analysis", "Invalid QC time unit.", parent=self)
            return None
        try:
            gaussian_min_height_factor = float(self._context._qc_gaussian_height_var.get().strip())
            gaussian_fit_width = float(self._context._qc_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(self._context._qc_gaussian_stddev_var.get().strip())
            gaussian_minimum_rt = float(self._context._qc_gaussian_min_rt_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Library Analysis",
                "Old-school QC peak picker parameters must be numbers.",
                parent=self,
            )
            return None
        alpha = DEFAULT_SIGNAL_QUALITY_ALPHA
        if algorithm == "modern":
            try:
                alpha = float(self._context._qc_alpha_var.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Library Analysis",
                    "Peak significance α must be a number (e.g. 0.001).",
                    parent=self,
                )
                return None
            if alpha <= 0.0 or alpha >= 1.0:
                messagebox.showerror(
                    "Library Analysis",
                    "Peak significance α must be between 0 and 1 (exclusive).",
                    parent=self,
                )
                return None
        return SignalQualityComputeOptions(
            peak_picking_algorithm=algorithm,
            alpha=alpha,
            time_unit=time_unit,  # type: ignore[arg-type]
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _peek_qc_signal_settings(self) -> Optional[SignalQualityComputeOptions]:
        algorithm = self._context._qc_picker_algorithm_var.get()
        if algorithm not in ("modern", "old_school"):
            return None
        time_unit = self._context._qc_time_unit_var.get()
        if time_unit not in ("seconds", "minutes"):
            return None
        try:
            gaussian_min_height_factor = float(self._context._qc_gaussian_height_var.get().strip())
            gaussian_fit_width = float(self._context._qc_gaussian_fit_width_var.get().strip())
            gaussian_stddev_threshold = float(self._context._qc_gaussian_stddev_var.get().strip())
            gaussian_minimum_rt = float(self._context._qc_gaussian_min_rt_var.get().strip())
        except ValueError:
            return None
        alpha = DEFAULT_SIGNAL_QUALITY_ALPHA
        if algorithm == "modern":
            try:
                alpha = float(self._context._qc_alpha_var.get().strip())
            except ValueError:
                return None
            if alpha <= 0.0 or alpha >= 1.0:
                return None
        return SignalQualityComputeOptions(
            peak_picking_algorithm=algorithm,
            alpha=alpha,
            time_unit=time_unit,  # type: ignore[arg-type]
            gaussian_min_height_factor=gaussian_min_height_factor,
            gaussian_fit_width=gaussian_fit_width,
            gaussian_stddev_threshold=gaussian_stddev_threshold,
            gaussian_minimum_rt=gaussian_minimum_rt,
        )

    def _apply_qc_settings_to_form(self, options: SignalQualityComputeOptions) -> None:
        self._context._qc_picker_algorithm_var.set(options.peak_picking_algorithm)
        self._context._qc_alpha_var.set(str(options.alpha))
        self._context._qc_time_unit_var.set(options.time_unit)
        self._context._qc_gaussian_height_var.set(str(options.gaussian_min_height_factor))
        self._context._qc_gaussian_fit_width_var.set(str(options.gaussian_fit_width))
        self._context._qc_gaussian_stddev_var.set(str(options.gaussian_stddev_threshold))
        self._context._qc_gaussian_min_rt_var.set(str(options.gaussian_minimum_rt))
        self._sync_qc_picker_widgets()

    def _parse_signal_alpha(self) -> Optional[float]:
        settings = self._parse_qc_signal_settings()
        if settings is None:
            return None
        return settings.alpha

    def _clear_frame_children(self, frame: Optional[ctk.CTkScrollableFrame]) -> None:
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()

    def _clear_metrics_view(self) -> None:
        self._clear_frame_children(self._context._metrics_frame)

    def _clear_plots_view(self) -> None:
        self._context._plot_photo = None
        self._context._selected_plot_index = None
        self._context._plot_list_buttons.clear()
        self._clear_frame_children(self._context._plot_list_frame)
        if self._context._plot_preview_tk is not None:
            self._context._plot_preview_tk.configure(image="", text="No plot selected")
        if self._context._plot_preview_title is not None:
            self._context._plot_preview_title.configure(text="Select a plot from the list")
        if self._context._plot_preview_help is not None:
            self._context._plot_preview_help.configure(text="")
        try:
            self._context._plot_export_btn.configure(state="disabled")
        except (tk.TclError, AttributeError):
            pass

    def _clear_results(self) -> None:
        self._clear_metrics_view()
        self._clear_plots_view()

    def _show_empty_library_message(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._context._metrics_frame,
            "No data",
            "Build or load a database that contains at least one compound.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)
        self._context._scan_btn.configure(state="disabled")
        self._context._metrics_btn.configure(state="disabled")
        self._context._plots_btn.configure(state="disabled")

    def _show_idle_placeholder(self) -> None:
        self._clear_results()
        card = self._make_info_card(
            self._context._metrics_frame,
            "Ready",
            "Select count channels in the sidebar, then click Run library scan "
            "in the top bar. After the scan completes, use Calculate metrics and/or "
            "Generate plots from the same parsed scan.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)
        self._update_plots_summary([])

    def _show_scan_ready_placeholder(self, scan: LibraryScanData) -> None:
        self._clear_metrics_view()
        card = self._make_info_card(
            self._context._metrics_frame,
            "Scan complete",
            (
                f"Parsed {scan.entries_used:,} of {scan.entries_attempted:,} entries "
                f"({scan.entries_skipped:,} skipped). "
                "Select metrics and click Calculate metrics, or select plots and "
                "open the Visualizations tab."
            ),
        )
        card.grid(row=0, column=0, sticky="ew", pady=8)

    def _on_run_library_scan(self) -> None:
        if self._context._is_busy():
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        if self._context._data_store is None or self._context._data_store.get_compound_count() == 0:
            self._show_empty_library_message()
            return
        entry_count = self._context._data_store.get_compound_count()
        if not self._confirm_library_scan(entry_count):
            return
        self._start_library_scan(channels)

    def _scan_entry_count(self, scan: LibraryScanData) -> int:
        return scan.entries_used or len(scan.entries)

    def _apply_loaded_scan(
        self,
        scan: LibraryScanData,
        *,
        persist: bool = True,
    ) -> None:
        """Activate a scan and optionally persist newly imported scan data."""
        assert self._context._db_path is not None and self._context._config is not None
        kind = "index" if self._context._index_db_mode else "full"
        channels = list(scan.channel_names) or self._get_selected_channels()
        for name, var in self._context._channel_vars.items():
            var.set(name in channels)
        fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
        qc_settings = self._parse_qc_signal_settings() or SignalQualityComputeOptions()
        snapshot = build_snapshot_from_scan(
            scan,
            database_path=self._context._db_path,
            database_kind=kind,
            channel_names=channels,
            metric_ids=[],
            plot_ids=[],
            plot_results=[],
            fraction_count=fraction_count,
            signal_quality=qc_settings,
        )
        self._context._session_state.activate_scan(scan, snapshot)
        if persist:
            save_session_scan(scan, self._context._db_path)
        self._show_scan_ready_placeholder(scan)
        self._clear_plots_view()
        self._update_plots_summary([])
        self._update_status_label()
        self._context._update_action_states()

    def _on_clear_library_scan(self) -> None:
        if self._context._is_busy():
            return
        has_memory = self._context._cached_scan is not None
        saved_count = len(list_session_scan_paths())
        if not has_memory and saved_count == 0:
            messagebox.showinfo(
                "Library Analysis",
                "No library scan is loaded or saved.",
                parent=self,
            )
            return
        saved_note = (
            f"This deletes {saved_count:,} saved scan file(s) for all databases.\n\n"
            if saved_count
            else ""
        )
        if not messagebox.askyesno(
            "Clear library scan",
            "Remove all cached library scans?\n\n"
            f"{saved_note}"
            "Use Export scan… first if you need to keep a scan between sessions.\n\n"
            "Metrics, plots, and RT assignment results that depend on the scan "
            "will no longer be available until you run or import a scan again.",
            parent=self,
            icon="warning",
        ):
            return
        deleted = delete_all_session_scans()
        self._context._session_state.invalidate_scan()
        self._clear_metrics_view()
        self._clear_plots_view()
        self._show_idle_placeholder()
        self._update_status_label()
        self._context._update_action_states()
        if deleted:
            detail = f"Removed {deleted:,} saved scan file(s)."
        elif has_memory:
            detail = "Cleared the in-memory scan."
        else:
            detail = "No saved scan files were found."
        messagebox.showinfo(
            "Library Analysis",
            f"Library scans cleared.\n\n{detail}",
            parent=self,
        )

    def _on_export_library_scan(self) -> None:
        if (
            self._context._is_busy()
            or self._context._cached_scan is None
            or self._context._db_path is None
        ):
            return
        scan = self._context._cached_scan
        default_name = suggested_scan_export_filename(self._context._db_path, scan)
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export library scan",
            initialfile=default_name,
            defaultextension=".pkl",
            filetypes=[
                ("LC-Seq library scan", "*.pkl"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return
        try:
            export_scan_pickle(scan, Path(dest))
        except OSError as exc:
            messagebox.showerror(
                "Export library scan",
                f"Could not save scan:\n{exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Export library scan",
            f"Scan exported to:\n{dest}",
            parent=self,
        )

    def _on_import_library_scan(self) -> None:
        if (
            self._context._is_busy()
            or self._context._db_path is None
            or self._context._config is None
        ):
            return
        source = filedialog.askopenfilename(
            parent=self,
            title="Import library scan",
            filetypes=[
                ("LC-Seq library scan", "*.pkl"),
                ("All files", "*.*"),
            ],
        )
        if not source:
            return
        try:
            scan = load_scan_pickle(Path(source))
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Import library scan",
                f"Could not read scan file:\n{exc}",
                parent=self,
            )
            return
        compound_count = (
            self._context._data_store.get_compound_count()
            if self._context._data_store is not None
            else 0
        )
        report = validate_scan_for_database(
            scan,
            database_path=self._context._db_path,
            config=self._context._config,
            compound_count=compound_count,
        )
        if not report.ok:
            messagebox.showerror(
                "Import library scan",
                "This scan cannot be used with the active library:\n\n"
                + "\n".join(f"• {line}" for line in report.errors),
                parent=self,
            )
            return
        if report.warnings:
            warning_text = "\n".join(f"• {line}" for line in report.warnings)
            if not messagebox.askyesno(
                "Import library scan",
                "The scan loaded, but please review these warnings:\n\n"
                f"{warning_text}\n\n"
                "Import this scan anyway?",
                parent=self,
                icon="warning",
            ):
                return
        self._apply_loaded_scan(scan)
        messagebox.showinfo(
            "Import library scan",
            f"Imported scan with {self._scan_entry_count(scan):,} entries "
            f"({', '.join(scan.channel_names) or 'no channels'}).",
            parent=self,
        )

    def _on_calculate_metrics(self) -> None:
        if self._context._is_busy() or self._context._cached_scan is None:
            return
        metric_ids = self._get_selected_metric_ids()
        if not metric_ids:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one metric.",
                parent=self,
            )
            return
        if self._parse_fraction_count() is None or self._parse_qc_signal_settings() is None:
            return
        entry_count = (
            self._context._cached_scan.entries_used or self._context._cached_scan.entries_attempted
        )
        if not self._confirm_metrics_computation(entry_count, metric_ids):
            return
        self._start_metrics_computation(metric_ids)

    def _start_library_scan(self, channels: List[str]) -> None:
        assert self._context._db_path is not None and self._context._config is not None

        self._context._show_loading_page(
            "Running library scan",
            "Parsing chromatograms from database entries…",
        )
        self._context._update_action_states()

        db_path = self._context._db_path
        config = self._context._config
        kind = "index" if self._context._index_db_mode else "full"
        fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
        qc_settings = self._parse_qc_signal_settings() or SignalQualityComputeOptions()

        def worker() -> None:
            try:

                def scan_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._context._thread_loading_progress(
                        fraction,
                        status or "Parsing library entries…",
                    )

                scan = scan_library_for_path(
                    db_path,
                    config,
                    channel_names=channels,
                    progress_callback=scan_progress,
                )
                self._context._raise_if_cancelled()
                snapshot = build_snapshot_from_scan(
                    scan,
                    database_path=db_path,
                    database_kind=kind,
                    channel_names=channels,
                    metric_ids=[],
                    plot_ids=[],
                    plot_results=[],
                    fraction_count=fraction_count,
                    signal_quality=qc_settings,
                )
                self._context._bind_worker_callback(self._on_scan_ready, scan, snapshot)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library scan failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))

        self._context._start_worker(worker)

    def _start_metrics_computation(self, metric_ids: List[str]) -> None:
        assert self._context._db_path is not None and self._context._cached_scan is not None
        scan = self._context._cached_scan
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        fraction_count = self._parse_fraction_count()
        qc_settings = self._parse_qc_signal_settings()
        if fraction_count is None or qc_settings is None:
            return

        self._context._show_loading_page(
            "Calculating metrics",
            "Aggregating library summary metrics…",
        )
        self._context._update_action_states()

        db_path = self._context._db_path
        kind = "index" if self._context._index_db_mode else "full"
        plot_ids = self._get_selected_plot_ids()
        plot_results = list(self._context._plot_results)

        def worker() -> None:
            try:

                def metrics_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._context._thread_loading_progress(
                        fraction,
                        status or "Computing library metrics…",
                    )

                metric_results = compute_metrics_from_scan(
                    scan,
                    metric_ids,
                    channels=channels,
                    fraction_count=fraction_count,
                    signal_quality=qc_settings,
                    progress_callback=metrics_progress,
                )
                snapshot = LibraryComputationSnapshot(
                    processed_at=datetime.now(timezone.utc),
                    database_path=str(db_path.resolve()),
                    database_kind=kind,
                    fraction_count=fraction_count,
                    selected_channels=list(channels),
                    selected_metrics=list(metric_ids),
                    selected_plots=list(plot_ids),
                    entries_attempted=scan.entries_attempted,
                    entries_used=scan.entries_used,
                    entries_skipped=scan.entries_skipped,
                    metric_results=metric_results,
                    plot_results=plot_results,
                    signal_quality_options=qc_settings,
                )
                self._context._raise_if_cancelled()
                self._context._bind_worker_callback(self._on_metrics_ready, snapshot)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Library metrics failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))

        self._context._start_worker(worker)

    def _on_scan_ready(
        self,
        scan: LibraryScanData,
        snapshot: LibraryComputationSnapshot,
    ) -> None:
        if not self._context._ui_is_active():
            return
        self._context._worker_thread = None
        self._context._session_state.activate_scan(scan, snapshot)
        if self._context._db_path is not None:
            save_session_scan(scan, self._context._db_path)
        self._context._update_loading_progress(
            0.98,
            (
                f"Scan complete: {scan.entries_used:,} of {scan.entries_attempted:,} "
                f"entries parsed ({scan.entries_skipped:,} skipped)."
            ),
        )

        def finish() -> None:
            if not self._context._ui_is_active():
                return
            try:
                self._show_scan_ready_placeholder(scan)
                self._clear_plots_view()
                self._update_plots_summary([])
                self._update_status_label()
            except tk.TclError:
                pass
            finally:
                self._context._hide_loading_page()
                self._context._update_action_states()

        self._context.after(30, finish)

    def _on_metrics_ready(self, snapshot: LibraryComputationSnapshot) -> None:
        if not self._context._ui_is_active():
            return
        self._context._worker_thread = None
        self._context._update_loading_progress(0.98, "Preparing metric display…")

        def finish() -> None:
            if not self._context._ui_is_active():
                return
            try:
                self._context._current_snapshot = snapshot
                self._context._current_snapshot_path = None
                self._callbacks.capture_metrics(snapshot)
                self._render_metrics()
                self._update_status_label()
                self._context._focus_tab(_TAB_METRICS)
            except tk.TclError:
                pass
            finally:
                self._context._hide_loading_page()
                self._context._update_action_states()

        self._context.after(30, finish)

    def _on_generate_plots(self) -> None:
        if (
            self._context._is_busy()
            or self._context._cached_scan is None
            or self._context._db_path is None
        ):
            return
        plot_ids = self._get_selected_plot_ids()
        channels = self._get_selected_channels()
        if not plot_ids or not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one plot and one count channel.",
                parent=self,
            )
            return
        qc_settings = self._parse_qc_signal_settings()
        if qc_settings is None:
            return
        entry_count = (
            self._context._cached_scan.entries_used or self._context._cached_scan.entries_attempted
        )
        if not self._confirm_plot_generation(entry_count, plot_ids):
            return

        self._context._show_loading_page(
            "Generating plots",
            "Rendering library visualizations…",
        )
        self._context._update_action_states()

        scan = self._context._cached_scan
        plot_dir = session_plots_dir(self._context._db_path)

        def worker() -> None:
            try:

                def plot_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._context._thread_loading_progress(
                        fraction,
                        status or "Generating plots…",
                    )

                plots = generate_plots(
                    scan,
                    plot_ids,
                    channels,
                    plot_dir,
                    signal_quality=qc_settings,
                    progress_callback=plot_progress,
                )
                self._context._raise_if_cancelled()
                kept = {
                    p.image_path.resolve()
                    for p in plots
                    if p.image_path is not None and p.image_path.is_file()
                }
                for old in plot_dir.glob("*.png"):
                    try:
                        if old.resolve() not in kept:
                            old.unlink()
                    except OSError:
                        pass
                self._context._bind_worker_callback(self._on_plots_ready, plots, plot_ids)
            except LibraryOperationCancelled:
                raise
            except Exception as exc:
                logger.error("Plot generation failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))

        self._context._start_worker(worker)

    def _on_plots_ready(self, plots: List[PlotResult], plot_ids: List[str]) -> None:
        if not self._context._ui_is_active():
            return
        self._context._worker_thread = None
        self._context._plot_results = plots
        if self._context._current_snapshot is not None:
            self._context._current_snapshot.selected_plots = list(plot_ids)
            self._context._current_snapshot.plot_results = plots
        elif self._context._cached_scan is not None and self._context._db_path is not None:
            channels = self._get_selected_channels()
            fraction_count = self._parse_fraction_count() or DEFAULT_FRACTION_COUNT
            qc_settings = self._peek_qc_signal_settings() or SignalQualityComputeOptions()
            scan = self._context._cached_scan
            kind = "index" if self._context._index_db_mode else "full"
            self._context._current_snapshot = LibraryComputationSnapshot(
                processed_at=datetime.now(timezone.utc),
                database_path=str(self._context._db_path.resolve()),
                database_kind=kind,
                fraction_count=fraction_count,
                selected_channels=list(channels),
                selected_metrics=[],
                selected_plots=list(plot_ids),
                entries_attempted=scan.entries_attempted,
                entries_used=scan.entries_used,
                entries_skipped=scan.entries_skipped,
                metric_results=[],
                plot_results=plots,
                signal_quality_options=qc_settings,
            )

        self._context._update_loading_progress(
            0.98,
            f"Generated {len(plots)} plot(s). Loading images…",
        )

        def finish() -> None:
            if not self._context._ui_is_active():
                return
            try:
                self._callbacks.capture_plots(plots, plot_ids)
                self._update_plots_summary(plots)
                self._context._focus_tab(_TAB_PLOTS)
                self._refresh_plot_gallery(plots)
                self._update_status_label()
            except tk.TclError:
                pass
            finally:
                self._context._hide_loading_page()
                self._context._update_action_states()

        self._context.after(30, finish)

    def _thread_progress(self, processed: int, total: int, status: str) -> None:
        fraction = (processed / total) if total > 0 else 0.0
        self._context._thread_loading_progress(fraction, status)

    def _update_progress(self, processed: int, total: int, status: str) -> None:
        fraction = (processed / total) if total > 0 else 0.0
        self._context._update_loading_progress(fraction, status)

    def _on_save(self) -> None:
        if self._context._current_snapshot is None or self._context._db_path is None:
            return
        plot_dir = session_plots_dir(self._context._db_path)
        try:
            saved = save_snapshot(
                self._context._current_snapshot,
                plot_source_dir=plot_dir if plot_dir.is_dir() else None,
            )
            self._context._current_snapshot_path = saved
            self._update_status_label()
            messagebox.showinfo(
                "Library Analysis",
                f"Saved results to:\n{saved}\n\nPlots: {snapshot_plots_dir(saved)}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror("Library Analysis", f"Could not save results:\n{exc}", parent=self)

    def _on_load_last(self) -> None:
        if self._context._db_path is None:
            return
        path = get_latest_snapshot_path(self._context._db_path)
        if path is None:
            messagebox.showinfo(
                "Library Analysis",
                "No saved results were found for this database.",
                parent=self,
            )
            return
        self._load_snapshot_from_path(path)

    def _on_clear_all_metrics_results(self) -> None:
        if self._context._is_busy():
            return
        saved_paths = list_snapshots()
        if not saved_paths:
            messagebox.showinfo(
                "Library Analysis",
                "No saved Library QC metrics results were found.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Clear all results",
            f"Delete all {len(saved_paths):,} saved Library QC metrics result file(s)?\n\n"
            "This removes snapshot JSON files and their plot folders under "
            f"{get_library_data_dir()}.\n\n"
            "This does not clear the in-memory library scan or unsaved metrics on screen.\n\n"
            "Continue?",
            parent=self,
            icon="warning",
        ):
            return
        deleted = delete_all_saved_snapshots()
        if (
            self._context._current_snapshot_path is not None
            and not self._context._current_snapshot_path.is_file()
        ):
            self._context._current_snapshot_path = None
        self._update_status_label()
        self._context._update_action_states()
        messagebox.showinfo(
            "Library Analysis",
            f"Removed {deleted:,} saved result file(s).",
            parent=self,
        )

    def _on_browse_saved(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open saved library data",
            initialdir=str(get_library_data_dir()),
            filetypes=[("Library data JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self._load_snapshot_from_path(Path(path))

    def _load_snapshot_from_path(self, path: Path) -> None:
        try:
            snapshot = load_snapshot(path)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not load saved results:\n{exc}",
                parent=self,
            )
            return
        self._context._session_state.invalidate_qc_results()
        self._context._cached_scan = None
        self._apply_snapshot(snapshot, path, warn_database_mismatch=True)

    def _apply_snapshot(
        self,
        snapshot: LibraryComputationSnapshot,
        path: Optional[Path],
        *,
        warn_database_mismatch: bool,
    ) -> None:
        if warn_database_mismatch and self._context._db_path is not None:
            if not database_paths_match(snapshot.database_path, self._context._db_path):
                messagebox.showwarning(
                    "Database mismatch",
                    "The saved results were computed from a different database:\n\n"
                    f"Saved: {snapshot.database_name}\n"
                    f"Active: {self._context._db_path.name}\n\n"
                    "Results will still be shown, but they may not match the current library.",
                    parent=self,
                )

        self._context._current_snapshot = snapshot
        self._context._current_snapshot_path = path
        self._context._plot_results = list(snapshot.plot_results)
        self._sync_channel_selection(snapshot)
        self._sync_metric_selection(snapshot)
        self._sync_plot_selection(snapshot)
        self._context._fraction_count_var.set(str(snapshot.fraction_count))
        self._apply_qc_settings_to_form(snapshot.signal_quality_options)
        self._render_results()
        self._update_status_label()
        self._context._update_action_states()

    def _sync_channel_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        for channel_name, var in self._context._channel_vars.items():
            var.set(channel_name in snapshot.selected_channels)

    def _sync_metric_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        if not snapshot.selected_metrics:
            return
        for metric_id, var in self._context._metric_vars.items():
            var.set(metric_id in snapshot.selected_metrics)

    def _sync_plot_selection(self, snapshot: LibraryComputationSnapshot) -> None:
        if not snapshot.selected_plots:
            return
        for plot_id, var in self._context._plot_vars.items():
            var.set(plot_id in snapshot.selected_plots)

    def _update_status_label(self) -> None:
        scan = self._context._cached_scan
        snapshot = self._context._current_snapshot
        if snapshot is None and scan is None:
            self._context._status_label.configure(text="No scan loaded.")
            return

        if snapshot is not None:
            processed = snapshot.processed_at
            if processed.tzinfo is not None:
                processed_local = processed.astimezone()
            else:
                processed_local = processed
            stamp = processed_local.strftime("%Y-%m-%d %H:%M:%S")
            channels = ", ".join(snapshot.selected_channels) or "—"
            metrics_count = len(snapshot.metric_results)
            plots = ", ".join(snapshot.selected_plots) or "—"
            source = (
                "current session (unsaved)"
                if self._context._current_snapshot_path is None
                else str(self._context._current_snapshot_path)
            )
            scan_note = (
                "scan in memory" if scan is not None else "metrics/plots only (rescan to refresh)"
            )
            qc_opts = snapshot.signal_quality_options
            picker_note = (
                f"picker: {qc_opts.picker_label()}"
                if qc_opts.peak_picking_algorithm == "old_school"
                else f"α: {qc_opts.alpha:g}"
            )
            self._context._status_label.configure(
                text=(
                    f"Processed: {stamp}  ·  Database: {snapshot.database_name} "
                    f"({snapshot.database_kind})  ·  Entries: {snapshot.entries_used:,} / "
                    f"{snapshot.entries_attempted:,}  ·  Fractions: {snapshot.fraction_count}  ·  "
                    f"QC {picker_note}  ·  Channels: {channels}  ·  "
                    f"Metrics: {metrics_count}  ·  Plots: {plots}  ·  "
                    f"{scan_note}  ·  Source: {source}"
                )
            )
            return

        assert scan is not None
        channels = ", ".join(scan.channel_names) or "—"
        self._context._status_label.configure(
            text=(
                f"Scan in memory  ·  Entries: {scan.entries_used:,} / "
                f"{scan.entries_attempted:,} ({scan.entries_skipped:,} skipped)  ·  "
                f"Channels: {channels}  ·  Metrics: not calculated  ·  Plots: not generated"
            )
        )

    def _on_export_signal_csv(self) -> None:
        if self._context._cached_scan is None:
            messagebox.showinfo(
                "Library Analysis",
                "Run library scan first.",
                parent=self,
            )
            return
        channels = self._get_selected_channels()
        if not channels:
            messagebox.showinfo(
                "Library Analysis",
                "Select at least one count channel.",
                parent=self,
            )
            return
        qc_settings = self._parse_qc_signal_settings()
        if qc_settings is None:
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export per-entry signal CSV",
            initialfile="library_signal_per_entry.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not dest:
            return

        self._context._show_loading_page(
            "Exporting signal CSV",
            "Computing per-entry signal metrics…",
        )
        scan = self._context._cached_scan
        assert scan is not None

        def worker() -> None:
            try:

                def export_progress(processed: int, total: int, status: str) -> None:
                    fraction = (processed / total) if total > 0 else 0.0
                    self._context._thread_loading_progress(fraction, status)

                stats = attach_signal_quality_to_entries(
                    scan.entries,
                    channels,
                    options=qc_settings,
                    progress_callback=export_progress,
                )
                export_per_entry_signal_csv(stats, dest, options=qc_settings)
                self._context._bind_worker_callback(self._on_export_csv_ready, str(dest))
            except LibraryOperationCancelled:
                raise
            except OSError as exc:
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))
            except Exception as exc:
                logger.error("CSV export failed: %s", exc, exc_info=True)
                self._context._bind_worker_callback(self._context._on_worker_error, str(exc))

        self._context._start_worker(worker)
        self._context._update_action_states()

    def _on_export_csv_ready(self, dest: str) -> None:
        if not self._context._ui_is_active():
            return
        self._context._worker_thread = None
        self._context._hide_loading_page()
        self._context._update_action_states()
        messagebox.showinfo(
            "Library Analysis",
            f"Exported per-entry signal metrics to:\n{dest}",
            parent=self,
        )

    def _render_results(self) -> None:
        self._render_metrics()
        plots = self._context._plot_results
        if self._context._current_snapshot is not None and not plots:
            plots = list(self._context._current_snapshot.plot_results)
            self._context._plot_results = plots
        self._update_plots_summary(plots)
        self._refresh_plot_gallery(plots)

    def _render_metrics(self) -> None:
        assert self._context._metrics_frame is not None
        self._clear_metrics_view()
        snapshot = self._context._current_snapshot
        if snapshot is None:
            self._update_metrics_summary_label(0)
            return

        row = 0
        qc_opts = snapshot.signal_quality_options
        if any(m.metric_id in SIGNAL_QUALITY_METRIC_IDS for m in snapshot.metric_results):
            if qc_opts.peak_picking_algorithm == "old_school":
                signal_note = (
                    "Signal-quality metrics use old-school Gaussian peak picking "
                    f"(time unit {qc_opts.time_unit}). Baseline μ and σ come from a "
                    "σ-clipped median (iteratively drop points above mean+2σ)."
                )
            else:
                signal_note = (
                    "Signal-quality metrics (significant peaks): peak height, SNR, and dynamic "
                    "range use the tallest peak with p-value < α from the modern peak picker. "
                    "Baseline μ and σ come from a σ-clipped median "
                    f"(iteratively drop points above mean+2σ). α = {qc_opts.alpha:g}."
                )
            banner = ctk.CTkFrame(
                self._context._metrics_frame,
                corner_radius=10,
                fg_color=("gray90", "gray22"),
                border_width=1,
                border_color=("gray78", "gray28"),
            )
            banner.grid(row=row, column=0, sticky="ew", pady=(4, 14), padx=2)
            ctk.CTkLabel(
                banner,
                text=signal_note,
                font=ctk.CTkFont(size=11),
                anchor="w",
                wraplength=760,
                justify="left",
            ).pack(padx=14, pady=12, anchor="w")
            row += 1

        if snapshot.metric_results:
            self._update_metrics_summary_label(len(snapshot.metric_results))
            last_category: Optional[str] = None
            for metric in snapshot.metric_results:
                definition = LIBRARY_METRIC_DEFINITIONS.get(metric.metric_id)
                category = definition.category if definition else "other"
                if category != last_category:
                    category_label = (
                        "Coverage metrics"
                        if category == "coverage"
                        else "Signal-quality metrics" if category == "signal" else "Metrics"
                    )
                    ctk.CTkLabel(
                        self._context._metrics_frame,
                        text=category_label,
                        font=_section_header_font(),
                        text_color=_SECTION_HEADER_COLOR,
                        anchor="w",
                    ).grid(row=row, column=0, sticky="w", padx=6, pady=(12, 6))
                    row += 1
                    last_category = category
                self._render_stat_card(
                    parent=self._context._metrics_frame,
                    row=row,
                    title=metric.title,
                    help_txt=metric.help_text,
                    channels=metric.channels,
                )
                row += 1
        else:
            self._update_metrics_summary_label(0)

        if row == 0:
            card = self._make_info_card(
                self._context._metrics_frame,
                "No metrics",
                "Run library scan, then click Calculate metrics.",
            )
            card.grid(row=0, column=0, sticky="ew", pady=8)

    def _update_metrics_summary_label(self, metric_count: int) -> None:
        if not hasattr(self, "_metrics_summary_label"):
            return
        if metric_count == 0:
            text = "Summary metrics appear after Calculate metrics."
        else:
            text = f"{metric_count} metric(s) calculated — values by channel below."
        try:
            self._context._metrics_summary_label.configure(text=text)
        except tk.TclError:
            pass

    def _on_export_metrics_csv(self) -> None:
        snapshot = self._context._current_snapshot
        if snapshot is None or not snapshot.metric_results:
            messagebox.showinfo(
                "Library Analysis",
                "Calculate metrics first.",
                parent=self,
            )
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export summary metrics CSV",
            initialfile="library_summary_metrics.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not dest:
            return
        try:
            saved = export_metrics_summary_csv(snapshot, dest)
            messagebox.showinfo(
                "Library Analysis",
                f"Exported summary metrics to:\n{saved}",
                parent=self,
            )
        except OSError as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not export metrics:\n{exc}",
                parent=self,
            )

    def _update_plots_summary(self, plots: List[PlotResult]) -> None:
        if not hasattr(self, "_plots_summary_label"):
            return
        available = sum(1 for p in plots if p.image_path is not None and p.image_path.is_file())
        total = len(plots)
        if total == 0:
            text = "No plots generated yet. Run library scan, then Generate plots."
        elif available == total:
            text = f"{available} plot(s) ready — select one from the list to preview."
        else:
            text = (
                f"{available} of {total} plot(s) available "
                f"({total - available} missing or failed to render)."
            )
        try:
            self._context._plots_summary_label.configure(text=text)
        except tk.TclError:
            pass

    @staticmethod
    def _format_plot_list_label(title: str) -> str:
        """Wrap long plot titles onto two lines for the selection list."""
        if " — " in title:
            plot_name, channel = title.split(" — ", 1)
            return f"{plot_name}\n— {channel}"
        if len(title) > 28:
            split_at = title.rfind(" ", 0, 28)
            if split_at > 10:
                return f"{title[:split_at]}\n{title[split_at + 1:]}"
        return title

    def _refresh_plot_gallery(self, plots: List[PlotResult]) -> None:
        """Rebuild plot list and show the first available plot."""
        self._clear_plots_view()
        if not plots:
            if self._context._plot_preview_tk is not None:
                self._context._plot_preview_tk.configure(
                    image="",
                    text="Generate plots to preview visualizations here.",
                )
            return

        assert self._context._plot_list_frame is not None
        for index, plot in enumerate(plots):
            available = plot.image_path is not None and plot.image_path.is_file()
            label = self._format_plot_list_label(
                plot.title if available else f"{plot.title} (missing)"
            )
            btn = ctk.CTkButton(
                self._context._plot_list_frame,
                text=label,
                anchor="w",
                height=_PLOT_LIST_BUTTON_HEIGHT,
                fg_color="gray40" if not available else ("gray75", "gray30"),
                hover_color=("gray70", "gray35"),
                command=lambda i=index: self._select_plot(i),
            )
            btn.pack(fill="x", pady=2, padx=2)
            self._context._plot_list_buttons.append(btn)

        first_ok = next(
            (i for i, p in enumerate(plots) if p.image_path and p.image_path.is_file()),
            None,
        )
        if first_ok is not None:
            self._select_plot(first_ok)
        elif plots:
            self._select_plot(0)

    def _select_plot(self, index: int) -> None:
        if index < 0 or index >= len(self._context._plot_results):
            return
        self._context._selected_plot_index = index
        plot = self._context._plot_results[index]

        for i, btn in enumerate(self._context._plot_list_buttons):
            try:
                if i == index:
                    btn.configure(fg_color=("#238636", "#2ea043"))
                else:
                    available = (
                        self._context._plot_results[i].image_path is not None
                        and self._context._plot_results[i].image_path.is_file()
                    )
                    btn.configure(fg_color="gray40" if not available else ("gray75", "gray30"))
            except tk.TclError:
                pass

        if self._context._plot_preview_title is not None:
            self._context._plot_preview_title.configure(text=plot.title)
        if self._context._plot_preview_help is not None:
            self._context._plot_preview_help.configure(text=plot.help_text or "")

        image_path: Optional[Path] = None
        if plot.image_path is not None:
            try:
                image_path = plot.image_path.resolve()
            except OSError:
                image_path = plot.image_path

        has_file = image_path is not None and image_path.is_file()
        try:
            self._context._plot_export_btn.configure(state="normal" if has_file else "disabled")
        except (tk.TclError, AttributeError):
            pass

        if not has_file or self._context._plot_preview_tk is None or image_path is None:
            if self._context._plot_preview_tk is not None:
                self._context._plot_preview_tk.configure(
                    image="",
                    text="Plot image not available. Try Generate plots.",
                    bg=_tk_preview_bg(),
                )
            self._context._plot_photo = None
            return

        try:
            from PIL import Image, ImageTk

            with Image.open(image_path) as pil_image:
                width, height = pil_image.size
                scale = min(1.0, _PLOT_PREVIEW_MAX_WIDTH / float(width))
                display_w = max(1, int(width * scale))
                display_h = max(1, int(height * scale))
                resized = pil_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
                self._context._plot_photo = ImageTk.PhotoImage(resized)
            self._context._plot_preview_tk.configure(
                image=self._context._plot_photo,
                text="",
                bg=_tk_preview_bg(),
            )
        except Exception as exc:
            logger.warning("Failed to display plot preview %s: %s", image_path, exc)
            self._context._plot_photo = None
            self._context._plot_preview_tk.configure(
                image="",
                text=f"Could not load preview.\nUse Open to view:\n{image_path}",
                bg=_tk_preview_bg(),
            )

    def _current_plot_path(self) -> Optional[Path]:
        if self._context._selected_plot_index is None:
            return None
        plot = self._context._plot_results[self._context._selected_plot_index]
        if plot.image_path is None:
            return None
        try:
            path = plot.image_path.resolve()
        except OSError:
            path = plot.image_path
        return path if path.is_file() else None

    def _on_export_current_plot(self) -> None:
        path = self._current_plot_path()
        if path is None:
            return
        self._export_plot_image(path)

    def _on_export_all_plots(self) -> None:
        plots = [
            p
            for p in self._context._plot_results
            if p.image_path is not None and p.image_path.is_file()
        ]
        if not plots:
            messagebox.showinfo(
                "Library Analysis",
                "No plot files are available to export. Generate plots first.",
                parent=self,
            )
            return
        dest = filedialog.askdirectory(
            parent=self,
            title="Choose folder for exported plots",
        )
        if not dest:
            return
        out_dir = Path(dest)
        exported = 0
        errors: List[str] = []
        for plot in plots:
            assert plot.image_path is not None
            target = out_dir / plot.image_path.name
            try:
                shutil.copy2(plot.image_path, target)
                exported += 1
            except OSError as exc:
                errors.append(f"{plot.image_path.name}: {exc}")
        if errors:
            messagebox.showwarning(
                "Library Analysis",
                f"Exported {exported} plot(s) to:\n{out_dir}\n\n"
                f"Some files failed:\n" + "\n".join(errors[:5]),
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Library Analysis",
                f"Exported {exported} plot(s) to:\n{out_dir}",
                parent=self,
            )

    def _on_open_plots_folder(self) -> None:
        if self._context._db_path is None:
            return
        folder = session_plots_dir(self._context._db_path)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder.resolve()))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(
                "Library Analysis",
                f"Could not open plots folder:\n{folder}\n\n{exc}",
                parent=self,
            )

    def _render_stat_card(
        self,
        *,
        parent: ctk.CTkScrollableFrame,
        row: int,
        title: str,
        help_txt: str,
        channels: List[ChannelAggregateStats],
    ) -> None:
        card = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color=("gray95", "gray18"),
            border_width=1,
            border_color=("gray82", "gray30"),
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16), padx=2)
        card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(card, fg_color=("gray88", "gray22"), corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            header,
            text=help_txt,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        if not channels or all(ch.n == 0 for ch in channels):
            ctk.CTkLabel(
                card,
                text="No values could be computed.",
                text_color="orange",
            ).grid(row=1, column=0, padx=14, pady=(0, 14), sticky="w")
            return

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, padx=12, pady=(0, 14), sticky="ew")
        body.grid_columnconfigure(0, weight=1)

        for row_i, ch in enumerate(channels):
            self._add_channel_row(body, row_i, ch)

    def _open_plot_file(self, path: Path) -> None:
        if not path.is_file():
            messagebox.showwarning("Open plot", "Plot file was not found.", parent=self)
            return
        try:
            os.startfile(str(path.resolve()))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open plot", f"Could not open plot:\n{exc}", parent=self)

    def _export_plot_image(self, source: Path) -> None:
        if not source.is_file():
            messagebox.showwarning("Export", "Plot file was not found.", parent=self)
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="Export plot image",
            initialfile=source.name,
            defaultextension=".png",
            filetypes=[
                ("PNG image", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if not dest:
            return
        try:
            shutil.copy2(source, dest)
            messagebox.showinfo("Export", f"Saved plot to:\n{dest}", parent=self)
        except OSError as exc:
            messagebox.showerror("Export", f"Could not export plot:\n{exc}", parent=self)

    def _add_channel_row(
        self,
        parent: ctk.CTkFrame,
        row_i: int,
        ch: ChannelAggregateStats,
    ) -> None:
        row_frame = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("gray90", "gray24"),
            border_width=1,
            border_color=("gray80", "gray32"),
        )
        row_frame.grid(row=row_i, column=0, sticky="ew", pady=4)
        row_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_frame,
            text=ch.count_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=(12, 16), pady=10, sticky="w")

        if ch.n == 0:
            value_text = "—"
        elif ch.n == 1:
            value_text = f"{ch.mean:,.4g}  (n = 1, SD undefined)"
        else:
            value_text = f"{ch.mean:,.4g} ± {ch.std_dev:,.4g}  (n = {ch.n:,})"

        ctk.CTkLabel(
            row_frame,
            text=value_text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#0969da", "#58a6ff"),
            anchor="e",
        ).grid(row=0, column=1, padx=12, pady=10, sticky="e")

    @staticmethod
    def _make_info_card(
        parent: ctk.CTkFrame,
        title: str,
        body: str,
        *,
        wraplength: int = 760,
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")
        ctk.CTkLabel(
            card,
            text=body,
            font=ctk.CTkFont(size=12),
            anchor="w",
            wraplength=wraplength,
            justify="left",
        ).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")
        return card

    def _try_restore_session_scan(self) -> None:
        """Start a non-blocking restore of the persisted session scan."""
        if (
            not self._context._ui_is_active()
            or self._context._cached_scan is not None
            or self._context._db_path is None
            or (self._restore_tasks is not None and self._restore_tasks.is_busy)
        ):
            return
        db_path = self._context._db_path
        assert db_path is not None
        if self._restore_tasks is None:
            self._restore_tasks = TaskCoordinator(
                self._context._dispatch_to_tk,
                self._context._ui_is_active,
            )
        restore_tasks = self._restore_tasks

        def worker() -> None:
            try:
                scan = load_session_scan(db_path)
                restore_tasks.dispatch_current(
                    self._accept_restored_session_scan,
                    scan,
                    complete=True,
                )
            except Exception as exc:
                logger.warning("Could not restore session library scan: %s", exc)
                restore_tasks.dispatch_current(
                    self._finish_failed_session_scan_restore,
                    complete=True,
                )

        restore_tasks.start(worker)

    def _accept_restored_session_scan(self, scan: Optional[LibraryScanData]) -> None:
        """Apply a background-loaded scan when no newer operation superseded it."""
        if scan is None:
            return
        if self._context._cached_scan is not None or self._context._is_busy():
            return
        self._apply_loaded_scan(scan, persist=False)
        logger.info(
            "Restored session library scan (%s entries)",
            self._scan_entry_count(scan),
        )

    @staticmethod
    def _finish_failed_session_scan_restore() -> None:
        """Complete a failed optional restore without changing visible state."""
