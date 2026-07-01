# src/ui/peak_analysis_panel.py
"""Peak analysis controls and results table for the chromatogram visualizer."""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Set, Tuple

import customtkinter as ctk

from src.core.analysis_export import export_figure, export_peaks_batch_csv
from src.core.lcseq_backend import get_peak_picker_backend
from src.core.lineage_peak_labels import (
    apply_lineage_labels_to_batch,
    is_intended_product_label,
)
from src.core.peak_analysis_service import (
    analyze_peaks_batch,
    estimate_baselines_batch,
)
from src.core.time_display import convert_time_value
from src.models.analysis_settings import AnalysisSettings, TimeUnit
from src.models.compound import Compound
from src.models.peak_result import PeakAnalysisBatchResult, PeakAnalysisResult
from src.models.pedigree_result import LineageAnalysisResult, LineageBatchResult
from src.models.spreadsheet_config import SpreadsheetConfig
from src.ui.widget_tooltip import attach_tooltip

logger = logging.getLogger(__name__)

_METRIC_COLUMNS = (
    "peak",
    "rt",
    "height",
    "area",
    "pct",
    "prominence",
    "p_value",
)

_PEAK_ROW_BG = "#2b2b2b"
_UNFOCUSED_PEAK_ALPHA = 0.15
_INTENDED_PRODUCT_TAG = "intended_product"
_INTENDED_PRODUCT_BG = "#1a5c32"
_INTENDED_PRODUCT_FG = "#aff7b8"
_PEAK_PANEL_WIDTH = 320


def _blend_hex(fg: str, bg: str, ratio: float) -> str:
    """Blend fg toward bg; ratio=1 returns fg."""

    def _parse(hex_color: str) -> Tuple[int, int, int]:
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    fr, fg_g, fb = _parse(fg)
    br, bg_g, bb = _parse(bg)
    r = int(fr * ratio + br * (1.0 - ratio))
    g = int(fg_g * ratio + bg_g * (1.0 - ratio))
    b = int(fb * ratio + bb * (1.0 - ratio))
    return f"#{r:02x}{g:02x}{b:02x}"


class PeakAnalysisPanel(ctk.CTkFrame):
    """Sidebar panel: settings, pick peaks, baseline, export, peak table."""

    def __init__(
        self,
        master,
        config: SpreadsheetConfig,
        *,
        on_result_changed: Callable[[Optional[PeakAnalysisBatchResult]], None],
        on_view_changed: Callable[[], None],
        get_figure: Callable[[], object],
        get_target_compounds: Callable[[], List[Compound]],
        get_plot_color: Callable[[str], str],
        on_analyze_lineage: Optional[Callable[[], None]] = None,
        on_view_lineage: Optional[Callable[[], None]] = None,
        pedigree_configured: bool = False,
    ) -> None:
        super().__init__(master, fg_color=("gray90", "gray20"))
        self._config = config
        self._on_result_changed = on_result_changed
        self._on_view_changed = on_view_changed
        self._get_figure = get_figure
        self._get_target_compounds = get_target_compounds
        self._get_plot_color = get_plot_color
        self._on_analyze_lineage = on_analyze_lineage
        self._on_view_lineage = on_view_lineage
        self._pedigree_configured = pedigree_configured
        self._batch: Optional[PeakAnalysisBatchResult] = None
        self._lineage_result: Optional[LineageAnalysisResult] = None
        self._lineage_batch: Optional[LineageBatchResult] = None
        self._show_suspected_peak_column = False
        self._show_baseline_flag = False
        self._show_integration_flag = False
        self._show_legend_flag = False
        self._peak_row_meta: Dict[str, Tuple[str, int, str, Optional[str]]] = {}
        self._color_tags_configured: Set[str] = set()
        self._uses_variants = bool(config.compound_variant_column)
        self._id_heading = config.compound_id_column
        self._variant_heading = config.compound_variant_column or "Variant"
        self._stored_time_unit: TimeUnit = (
            "minutes" if config.analysis_time_unit == "minutes" else "seconds"
        )
        self._table_columns = self._build_table_columns()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        backend = get_peak_picker_backend().info()
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        top_row.grid_columnconfigure(0, weight=1)

        self._engine_label = ctk.CTkLabel(
            top_row,
            text=f"Engine: {backend.name}",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        )
        self._engine_label.grid(row=0, column=0, sticky="w")
        if not backend.is_native:
            attach_tooltip(self._engine_label, backend.detail)

        ctk.CTkButton(
            top_row,
            text="? Help",
            width=64,
            height=24,
            fg_color="gray40",
            command=self._on_peak_help,
        ).grid(row=0, column=1, sticky="e")

        settings = ctk.CTkFrame(self, fg_color="transparent")
        settings.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        settings.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(settings, text="Count channel:").grid(row=0, column=0, sticky="w", pady=2)
        self._channel_var = tk.StringVar(value=config.count_names[0] if config.count_names else "")
        self._channel_menu = ctk.CTkOptionMenu(
            settings,
            variable=self._channel_var,
            values=list(config.count_names) or ["(none)"],
            width=160,
        )
        self._channel_menu.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        ctk.CTkLabel(settings, text="Time unit:").grid(row=1, column=0, sticky="w", pady=2)
        unit_frame = ctk.CTkFrame(settings, fg_color="transparent")
        unit_frame.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)
        self._time_unit_var = tk.StringVar(value=config.analysis_time_unit)
        ctk.CTkRadioButton(
            unit_frame, text="Seconds", variable=self._time_unit_var, value="seconds"
        ).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(
            unit_frame, text="Minutes", variable=self._time_unit_var, value="minutes"
        ).pack(side="left")
        attach_tooltip(
            unit_frame,
            "Display times relative to the unit set in Configure Spreadsheet "
            f"(stored as {self._stored_time_unit}). Switching multiplies or divides by 60.",
        )
        self._time_unit_var.trace_add("write", self._on_time_unit_changed)

        ctk.CTkLabel(settings, text="Significance (α):").grid(row=2, column=0, sticky="w", pady=2)
        self._alpha_entry = ctk.CTkEntry(settings, width=100)
        self._alpha_entry.insert(0, "0.001")
        self._alpha_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=2)
        attach_tooltip(
            self._alpha_entry,
            "Significance threshold (α). Peaks with p-value below α are kept. "
            "Smaller α = stricter (fewer peaks). Default 0.001.",
        )

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=8, pady=4)

        self._pick_btn = ctk.CTkButton(
            actions,
            text="Pick peaks",
            fg_color="#238636",
            command=self._on_pick_peaks,
        )
        self._pick_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(
            self._pick_btn,
            "Detect peaks on every selected table row (overlaid traces) "
            "using the count channel above.",
        )

        self._baseline_btn = ctk.CTkButton(
            actions,
            text="Show baseline",
            command=self._on_show_baseline,
        )
        self._baseline_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(
            self._baseline_btn,
            "Show or hide per-trace baseline levels for all selected compounds.",
        )

        self._integration_btn = ctk.CTkButton(
            actions,
            text="Show integration",
            command=self._on_show_integration,
        )
        self._integration_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(
            self._integration_btn,
            "Show or hide shaded integration windows (valley-to-valley) on the plot.",
        )

        self._legend_btn = ctk.CTkButton(
            actions,
            text="Show legend",
            command=self._on_show_legend,
        )
        self._legend_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(
            self._legend_btn,
            "Show or hide the chromatogram trace legend (off by default during peak analysis).",
        )

        self._clear_btn = ctk.CTkButton(
            actions,
            text="Clear",
            fg_color="gray40",
            command=self._on_clear,
        )
        self._clear_btn.pack(side="left", padx=(0, 6))

        export_row = ctk.CTkFrame(self, fg_color="transparent")
        export_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
        ctk.CTkButton(export_row, text="Export CSV…", width=72, command=self._on_export_csv).pack(
            side="left", padx=(0, 4)
        )
        ctk.CTkButton(export_row, text="Export plot…", width=72, command=self._on_export_plot).pack(
            side="left", padx=(0, 4)
        )
        self._lineage_btn = ctk.CTkButton(
            export_row,
            text="Analyze lineage",
            width=72,
            fg_color="#1F6FEB",
            command=self._on_lineage_clicked,
        )
        self._lineage_btn.pack(side="left", padx=(0, 4))
        self._view_lineage_btn = ctk.CTkButton(
            export_row,
            text="View lineage",
            width=72,
            fg_color="#238636",
            state="disabled",
            command=self._on_view_lineage_clicked,
        )
        self._view_lineage_btn.pack(side="left")
        if not pedigree_configured:
            self._lineage_btn.configure(state="disabled")
            self._view_lineage_btn.configure(state="disabled")
            attach_tooltip(
                self._lineage_btn,
                "Map BB1..BBn columns in Configure Spreadsheet to enable lineage analysis.",
            )
        elif on_analyze_lineage is None:
            self._lineage_btn.configure(state="disabled")
            self._view_lineage_btn.configure(state="disabled")
        else:
            attach_tooltip(
                self._lineage_btn,
                "Run lineage for all plotted compounds (up to 50). Updates suspected peak IDs when peaks are picked.",
            )
            attach_tooltip(
                self._view_lineage_btn,
                "Open lineage figure(s). Select compounds from the list when multiple are analyzed.",
            )
        if on_view_lineage is None:
            self._view_lineage_btn.configure(state="disabled")

        self._status = ctk.CTkLabel(
            self,
            text="Select table rows to plot, choose a count channel, then Pick peaks.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
            wraplength=280,
            justify="left",
        )
        self._status.grid(row=5, column=0, sticky="ew", padx=8, pady=(4, 8))

        table_wrap = ctk.CTkFrame(self)
        table_wrap.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            table_wrap,
            columns=self._table_columns,
            show="headings",
            height=8,
        )
        self._apply_tree_columns()
        attach_tooltip(
            self._tree,
            "Rows are color-coded by trace. Click one or more peaks to focus them on the plot; "
            "click again with nothing selected to show all peaks. RT uses the display time unit. "
            "After lineage analysis, the intended product row is highlighted in bold green. "
            "Scroll horizontally if all columns do not fit.",
        )
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self._tree.yview)
        xsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=xsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self._configure_peak_tree_style()
        self._tree.bind("<<TreeviewSelect>>", self._on_peak_table_selection)

    def _configure_peak_tree_style(self) -> None:
        style = ttk.Style(self)
        style.configure(
            "PeakAnalysis.Treeview",
            background=_PEAK_ROW_BG,
            foreground="white",
            fieldbackground=_PEAK_ROW_BG,
            rowheight=24,
        )
        style.configure("PeakAnalysis.Treeview.Heading", background="#3d3d3d", foreground="#ffffff")
        style.map("PeakAnalysis.Treeview", background=[("selected", "#1f538d")])
        self._tree.configure(style="PeakAnalysis.Treeview")

    def _tree_column_width(self, col: str) -> int:
        if col in ("p_value", "library_id", "compound_id", "variant"):
            return 88
        if col == "suspected_peak_id":
            return 150
        return 72

    def _apply_tree_columns(self) -> None:
        """Apply column headings and fixed widths (horizontal scroll when needed)."""
        self._tree.configure(columns=self._table_columns)
        for col in self._table_columns:
            self._tree.heading(col, text=self._column_heading(col))
            self._tree.column(
                col,
                width=self._tree_column_width(col),
                stretch=False,
                minwidth=40,
            )

    def _build_table_columns(self) -> Tuple[str, ...]:
        base: Tuple[str, ...]
        if self._uses_variants:
            base = ("library_id", "variant", *_METRIC_COLUMNS)
        else:
            base = ("compound_id", *_METRIC_COLUMNS)
        if self._show_suspected_peak_column:
            return (*base, "suspected_peak_id")
        return base

    def _ensure_suspected_peak_column(self) -> None:
        if self._show_suspected_peak_column:
            return
        self._show_suspected_peak_column = True
        self._table_columns = self._build_table_columns()
        self._apply_tree_columns()

    def _column_heading(self, col: str) -> str:
        if col == "library_id" or col == "compound_id":
            return self._id_heading
        if col == "variant":
            return self._variant_heading
        if col == "suspected_peak_id":
            return "Suspected peak ID"
        headings = {
            "peak": "#",
            "rt": "RT",
            "height": "Height",
            "area": "Area",
            "pct": "% Area",
            "prominence": "Prom.",
            "p_value": "p-value",
        }
        return headings.get(col, col)

    @property
    def batch(self) -> Optional[PeakAnalysisBatchResult]:
        return self._batch

    @property
    def show_baseline(self) -> bool:
        return self._show_baseline_flag

    @property
    def show_integration(self) -> bool:
        return self._show_integration_flag

    @property
    def show_legend(self) -> bool:
        return self._show_legend_flag

    @property
    def unfocused_peak_alpha(self) -> float:
        return _UNFOCUSED_PEAK_ALPHA

    @property
    def selected_peak_keys(self) -> Optional[Set[Tuple[str, int]]]:
        """Selected (compound_id, peak_index) keys; None means no focus filter."""
        sel = self._tree.selection()
        if not sel:
            return None
        keys: Set[Tuple[str, int]] = set()
        for iid in sel:
            meta = self._peak_row_meta.get(str(iid))
            if meta is not None:
                keys.add((meta[0], meta[1]))
        return keys if keys else None

    @property
    def stored_time_unit(self) -> TimeUnit:
        return self._stored_time_unit

    @property
    def display_time_unit(self) -> TimeUnit:
        unit = self._time_unit_var.get()
        return "minutes" if unit == "minutes" else "seconds"

    def _display_rt(self, rt_stored: float) -> float:
        return convert_time_value(rt_stored, self._stored_time_unit, self.display_time_unit)

    def _build_settings(self) -> AnalysisSettings:
        try:
            alpha = float(self._alpha_entry.get().strip())
        except ValueError as exc:
            raise ValueError("Significance (α) must be a number") from exc
        channel = self._channel_var.get().strip()
        if not channel or channel == "(none)":
            raise ValueError("Select a count channel")
        tol = 30.0 if self._time_unit_var.get() == "seconds" else 0.5
        return AnalysisSettings(
            count_channel=channel,
            time_unit=self._time_unit_var.get(),  # type: ignore[arg-type]
            alpha=alpha,
            tolerance=tol,
        )

    def _resolve_targets(self) -> tuple[List[Compound], AnalysisSettings]:
        compounds = [c for c in self._get_target_compounds() if c is not None]
        if not compounds:
            raise ValueError("Select at least one compound in the table to plot")
        settings = self._build_settings()
        return compounds, settings

    def _apply_plot_colors(self, batch: PeakAnalysisBatchResult) -> None:
        for entry in batch.results:
            entry.plot_color = self._get_plot_color(str(entry.compound_id))

    def _compound_label(self, entry: PeakAnalysisResult) -> str:
        label = str(entry.primary_compound_id or entry.compound_id).strip()
        if entry.variant_label:
            return f"{label} ({entry.variant_label})"
        return label

    @property
    def lineage_result(self) -> Optional[LineageAnalysisResult]:
        if self._lineage_batch is not None and self._lineage_batch.results:
            return self._lineage_batch.results[0]
        return self._lineage_result

    @property
    def lineage_batch(self) -> Optional[LineageBatchResult]:
        return self._lineage_batch

    @property
    def lineage_results(self) -> List[LineageAnalysisResult]:
        if self._lineage_batch is not None:
            return list(self._lineage_batch.results)
        if self._lineage_result is not None:
            return [self._lineage_result]
        return []

    def set_lineage_busy(self, message: str) -> None:
        """Disable lineage actions while a background analysis runs."""
        self._lineage_btn.configure(state="disabled")
        self._view_lineage_btn.configure(state="disabled")
        self._status.configure(text=message, text_color=("gray10", "gray90"))

    def set_lineage_progress(self, message: str) -> None:
        self._status.configure(text=message, text_color=("gray10", "gray90"))

    def set_lineage_result(self, result: LineageAnalysisResult) -> None:
        """Store a single completed lineage analysis and enable the viewer."""
        self.set_lineage_batch_results(LineageBatchResult(results=(result,)))

    def set_lineage_batch_results(self, batch: LineageBatchResult) -> None:
        """Store one or more lineage results and enable the viewer."""
        self._lineage_batch = batch
        self._lineage_result = batch.results[0] if batch.results else None
        n_ok = batch.success_count
        n_fail = batch.failure_count
        self._lineage_btn.configure(state="normal")
        self._view_lineage_btn.configure(state="normal" if n_ok else "disabled")
        if n_ok == 1 and self._lineage_result is not None:
            n_panels = len(self._lineage_result.panels)
            status = (
                f"Lineage ready for {self._lineage_result.compound_id} — {n_panels} tier(s). "
                "Peak IDs updated when peaks are picked. Click View lineage to open the figure."
            )
        elif n_ok > 1:
            status = (
                f"Lineage ready for {n_ok} compound(s). "
                "Click View lineage to browse figures and batch-export."
            )
        else:
            status = "Lineage analysis finished with no successful compounds."
        if n_fail:
            status += f" {n_fail} compound(s) failed."
        self._status.configure(text=status, text_color=("gray10", "gray90"))

    def set_lineage_failed(self, message: str) -> None:
        self._lineage_result = None
        self._lineage_batch = None
        self._lineage_btn.configure(state="normal")
        self._view_lineage_btn.configure(state="disabled")
        self._status.configure(text=message, text_color="#D29922")

    def apply_lineage_labels(self, result: LineageAnalysisResult, compound_id: str) -> None:
        """Fill suspected peak IDs on the peak table from a lineage analysis result."""
        if self._batch is None or not self._batch.total_peak_count:
            return
        self._batch = apply_lineage_labels_to_batch(
            self._batch,
            result,
            compound_id,
            stored_time_unit=self._stored_time_unit,
        )
        self._ensure_suspected_peak_column()
        self._populate_table(self._batch)
        labeled = sum(
            1
            for entry in self._batch.results
            for peak in entry.peaks
            if peak.suspected_peak_id and peak.suspected_peak_id != "unknown"
        )
        unknown = sum(
            1
            for entry in self._batch.results
            for peak in entry.peaks
            if peak.suspected_peak_id == "unknown"
        )
        self._status.configure(
            text=(
                f"Lineage labels applied — {labeled} peak(s) matched, "
                f"{unknown} unknown (tolerance={result.settings.tolerance:g} "
                f"{result.settings.time_unit})."
            ),
            text_color=("gray10", "gray90"),
        )
        self._on_result_changed(self._batch)

    def _on_pick_peaks(self) -> None:
        try:
            compounds, settings = self._resolve_targets()
            self._batch = analyze_peaks_batch(compounds, settings)
            self._apply_plot_colors(self._batch)
            self._populate_table(self._batch)
            n_comp = len(self._batch.results)
            n_peaks = self._batch.total_peak_count
            self._status.configure(
                text=(
                    f"{n_peaks} peak(s) across {n_comp} compound(s) "
                    f"({settings.count_channel})."
                ),
                text_color=("gray10", "gray90"),
            )
            self._on_result_changed(self._batch)
        except Exception as exc:
            logger.warning("Peak pick failed: %s", exc)
            messagebox.showerror("Peak analysis", str(exc), parent=self.winfo_toplevel())

    def _on_show_integration(self) -> None:
        self._show_integration_flag = not self._show_integration_flag
        self._integration_btn.configure(
            text="Hide integration" if self._show_integration_flag else "Show integration"
        )
        self._on_view_changed()

    def _on_show_legend(self) -> None:
        self._show_legend_flag = not self._show_legend_flag
        self._legend_btn.configure(
            text="Hide legend" if self._show_legend_flag else "Show legend"
        )
        self._on_view_changed()

    def _on_peak_table_selection(self, _event: Optional[tk.Event] = None) -> None:
        self._refresh_peak_row_tags()
        self._on_view_changed()

    def _color_tag_name(self, color: str) -> str:
        return "pk_" + color.lstrip("#").lower()

    def _ensure_color_tag(self, color: str) -> str:
        tag = self._color_tag_name(color)
        if tag not in self._color_tags_configured:
            self._tree.tag_configure(
                tag,
                background=_blend_hex(color, _PEAK_ROW_BG, 0.22),
                foreground=color,
            )
            self._color_tags_configured.add(tag)
        return tag

    def _ensure_intended_product_tag(self) -> str:
        if _INTENDED_PRODUCT_TAG not in self._color_tags_configured:
            bold = tkfont.Font(family="Segoe UI", size=10, weight="bold")
            self._tree.tag_configure(
                _INTENDED_PRODUCT_TAG,
                background=_INTENDED_PRODUCT_BG,
                foreground=_INTENDED_PRODUCT_FG,
                font=bold,
            )
            self._color_tags_configured.add(_INTENDED_PRODUCT_TAG)
        return _INTENDED_PRODUCT_TAG

    def _row_tags_for_peak(
        self,
        *,
        color: str,
        suspected_peak_id: Optional[str],
        selected: bool,
    ) -> Tuple[str, ...]:
        if suspected_peak_id and is_intended_product_label(suspected_peak_id):
            tags: List[str] = [self._ensure_intended_product_tag()]
        else:
            tags = [self._ensure_color_tag(color)]
        if selected:
            if "peak_focus" not in self._color_tags_configured:
                self._tree.tag_configure(
                    "peak_focus",
                    background=_blend_hex("#ffffff", _PEAK_ROW_BG, 0.14),
                )
                self._color_tags_configured.add("peak_focus")
            tags.append("peak_focus")
        return tuple(tags)

    def _refresh_peak_row_tags(self) -> None:
        selected = {str(iid) for iid in self._tree.selection()}
        for iid in self._tree.get_children():
            meta = self._peak_row_meta.get(str(iid))
            if meta is None:
                continue
            _cid, _pidx, color, suspected = meta
            self._tree.item(
                iid,
                tags=self._row_tags_for_peak(
                    color=color,
                    suspected_peak_id=suspected,
                    selected=str(iid) in selected,
                ),
            )

    def _peak_row_iid(self, compound_id: str, peak_index: int) -> str:
        safe = str(compound_id).replace("|", "/")
        return f"{safe}|{peak_index}"

    def _on_show_baseline(self) -> None:
        if self._show_baseline_flag:
            self._show_baseline_flag = False
            self._baseline_btn.configure(text="Show baseline")
            self._on_view_changed()
            return

        self._show_baseline_flag = True
        self._baseline_btn.configure(text="Hide baseline")
        try:
            compounds, settings = self._resolve_targets()
            if self._batch is None:
                self._batch = estimate_baselines_batch(compounds, settings)
            else:
                existing = {
                    str(r.compound_id).strip(): r for r in self._batch.results
                }
                updated: List[PeakAnalysisResult] = []
                for compound in compounds:
                    cid = str(compound.compound_id).strip()
                    prior = existing.get(cid)
                    if prior is not None and prior.baseline is not None:
                        updated.append(prior)
                        continue
                    one = estimate_baselines_batch([compound], settings)
                    if prior is not None and prior.peaks:
                        entry = one.results[0]
                        entry.peaks = prior.peaks
                        updated.append(entry)
                    else:
                        updated.append(one.results[0])
                self._batch = PeakAnalysisBatchResult(
                    settings=settings,
                    channel=settings.count_channel,
                    results=updated,
                    backend_name=self._batch.backend_name,
                )
            self._apply_plot_colors(self._batch)
        except Exception as exc:
            self._show_baseline_flag = False
            self._baseline_btn.configure(text="Show baseline")
            messagebox.showerror("Baseline", str(exc), parent=self.winfo_toplevel())
            return
        self._on_view_changed()

    def _on_time_unit_changed(self, *_args) -> None:
        if self._batch is not None and self._batch.total_peak_count:
            self._populate_table(self._batch)
        self._on_view_changed()

    def _on_peak_help(self) -> None:
        from src.ui.help_window import open_help_window

        open_help_window(self.winfo_toplevel(), "peak_picking")

    def _on_lineage_clicked(self) -> None:
        if self._on_analyze_lineage is not None:
            self._on_analyze_lineage()

    def _on_view_lineage_clicked(self) -> None:
        if self._on_view_lineage is not None:
            self._on_view_lineage()

    def _on_clear(self) -> None:
        self._batch = None
        self._lineage_result = None
        self._lineage_batch = None
        self._show_suspected_peak_column = False
        self._table_columns = self._build_table_columns()
        self._apply_tree_columns()
        self._show_baseline_flag = False
        self._show_integration_flag = False
        self._show_legend_flag = False
        self._baseline_btn.configure(text="Show baseline")
        self._integration_btn.configure(text="Show integration")
        self._legend_btn.configure(text="Show legend")
        self._peak_row_meta.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._status.configure(
            text="Select table rows to plot, choose a count channel, then Pick peaks.",
            text_color="gray",
        )
        self._on_result_changed(None)
        self._on_view_changed()
        if self._pedigree_configured and self._on_analyze_lineage is not None:
            self._view_lineage_btn.configure(state="disabled")

    def _row_values(self, entry: PeakAnalysisResult, peak) -> tuple:
        id_val = str(entry.primary_compound_id or entry.compound_id).strip()
        metrics = (
            peak.peak_index,
            f"{self._display_rt(peak.rt):.4g}",
            f"{peak.intensity:.4g}",
            f"{peak.area:.4g}",
            f"{peak.pct_area:.2f}",
            f"{peak.prominence:.4g}",
            f"{peak.p_value:.2e}",
        )
        if self._show_suspected_peak_column:
            metrics = (*metrics, peak.suspected_peak_id or "")
        if self._uses_variants:
            return (id_val, str(entry.variant_label or "").strip(), *metrics)
        return (id_val, *metrics)

    def _populate_table(self, batch: PeakAnalysisBatchResult) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._peak_row_meta.clear()
        for entry in batch.results:
            color = entry.plot_color
            cid = str(entry.compound_id).strip()
            for peak in entry.peaks:
                row_iid = self._peak_row_iid(cid, peak.peak_index)
                suspected = peak.suspected_peak_id
                self._peak_row_meta[row_iid] = (cid, peak.peak_index, color, suspected)
                self._tree.insert(
                    "",
                    "end",
                    iid=row_iid,
                    values=self._row_values(entry, peak),
                    tags=self._row_tags_for_peak(
                        color=color,
                        suspected_peak_id=suspected,
                        selected=False,
                    ),
                )
        self._refresh_peak_row_tags()

    def _on_export_csv(self) -> None:
        if self._batch is None or not self._batch.total_peak_count:
            messagebox.showwarning("Export", "Pick peaks first.", parent=self.winfo_toplevel())
            return
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        export_peaks_batch_csv(
            self._batch,
            path,
            id_column_name=self._id_heading,
            include_variant=self._uses_variants,
        )
        messagebox.showinfo("Export", f"Saved:\n{path}", parent=self.winfo_toplevel())

    def _on_export_plot(self) -> None:
        fig = self._get_figure()
        if fig is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
        )
        if not path:
            return
        export_figure(fig, path)
        messagebox.showinfo("Export", f"Saved:\n{path}", parent=self.winfo_toplevel())
