# src/core/library_report.py
"""
Generate a PDF library report from a computation snapshot and plot images.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.core.library_metrics import (
    LIBRARY_METRIC_DEFINITIONS,
    LibraryComputationSnapshot,
    MetricResult,
    PlotResult,
)
from src.core.library_report_assets import (
    BRANCHES_PER_GRID_PAGE,
    BRANCH_GRID_COLS,
    BRANCH_GRID_ROWS,
    merge_report_pedigree_figures,
)
from src.core.library_report_models import (
    LibraryReportAuditTrail,
    LibraryReportOptions,
    LibraryReportPedigreeBranchFigure,
    LibraryReportPedigreeFigures,
)
from src.core.library_report_session import (
    PedigreeVizReportArtifact,
    RtAssignmentReportArtifact,
    SplittreeVizReportArtifact,
)

logger = logging.getLogger(__name__)

_METHODOLOGY_TEXT = """
<b>Signal-quality methodology</b><br/>
<br/>
Baseline μ and σ use the same σ-clipped median as Chromatogram Visualizer: iteratively
remove points above mean+2σ, then take the median of remaining points as μ and their sample
standard deviation as σ.<br/>
<br/>
Peaks are called <i>significant</i> when the peak picker's height or area p-value is below
α (same engine as Chromatogram Visualizer). Peak height, SNR excess, SNR ratio, and dynamic
range metrics use the <b>tallest significant peak</b> on each trace—not the tallest local
maximum.<br/>
<br/>
These are library-wide screening values (Approach A). When a pedigree run is available,
compare with <b>Product peak prominence (pedigree)</b> in Library Data — prominence measured
at the algorithm-chosen product RT on each passed full compound (Approach B).
"""


def _format_timestamp(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_channel_stats(mean: float, std_dev: float, n: int) -> str:
    return f"{mean:,.4g} ± {std_dev:,.4g}  (n={n:,})"


def _metric_table_rows(metric: MetricResult) -> List[List[str]]:
    rows: List[List[str]] = [["Channel", "Mean ± SD", "n"]]
    for ch in metric.channels:
        rows.append(
            [
                ch.count_name,
                f"{ch.mean:,.4g} ± {ch.std_dev:,.4g}",
                f"{ch.n:,}",
            ]
        )
    return rows


def _styled_table(data: List[List[str]], col_widths: Optional[List[float]] = None) -> Table:
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _scaled_image(path: Path, *, max_w: float, max_h: float) -> Image:
    img = Image(str(path))
    scale = min(max_w / img.drawWidth, max_h / img.drawHeight, 1.0)
    img.drawWidth *= scale
    img.drawHeight *= scale
    return img


def _branch_label_html(branch: LibraryReportPedigreeBranchFigure) -> str:
    """Bold branch title with optional blue global index prefix."""
    name = escape(branch.bb1_name)
    if branch.bb1_index is not None and branch.bb1_index > 0:
        return f'<font color="#2563EB">#{branch.bb1_index}</font> {name}'
    return name


def _branch_cell(
    branch: LibraryReportPedigreeBranchFigure,
    *,
    label_style: ParagraphStyle,
    image_w: float,
    image_h: float,
) -> Table:
    """One branch panel: bold name centered above the split-tree image."""
    label_html = _branch_label_html(branch)
    try:
        img = _scaled_image(branch.image_path, max_w=image_w, max_h=image_h)
        body: List[List[object]] = [[Paragraph(label_html, label_style)], [img]]
    except Exception as exc:
        logger.warning("Could not embed DEL branch %s: %s", branch.bb1_name, exc)
        body = [[Paragraph(f"{label_html}<br/>(unavailable: {exc})", label_style)]]

    cell = Table(body, colWidths=[image_w])
    cell.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
            ]
        )
    )
    return cell


def _append_bb_index_reference(
    story: list,
    pedigree: LibraryReportPedigreeFigures,
    *,
    subheading_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    if not pedigree.bb_index_reference:
        return

    story.append(Paragraph("Building-block index reference", subheading_style))
    null_note = (
        f" Null / placeholder token “{pedigree.null_token}” is labeled 0 on the tree."
        if pedigree.null_token
        else ""
    )
    story.append(
        Paragraph(
            "Numbers on the split-tree full tree label BB1 branches only (matching "
            "branch plot roots and CSV bb1_index). The outer BB2 ring is unlabeled."
            f"{null_note}",
            body_style,
        )
    )
    story.append(Spacer(1, 0.08 * inch))

    rows: List[List[str]] = [["Index", "Building block"]]
    rows.extend([str(index), name] for index, name in pedigree.bb_index_reference)
    story.append(_styled_table(rows, col_widths=[0.9 * inch, 5.5 * inch]))
    story.append(Spacer(1, 0.16 * inch))


def _append_rt_assignment_section(
    story: list,
    artifact: RtAssignmentReportArtifact,
    *,
    heading_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> None:
    story.append(PageBreak())
    story.append(Paragraph("RT assignment", heading_style))
    story.append(
        Paragraph(
            "Summary of the RT assignment run captured from the active session.",
            body_style,
        )
    )
    story.append(Spacer(1, 0.12 * inch))
    mode_label = {
        "pedigree": "Pedigree",
        "direct_pick": "Direct pick",
    }.get(artifact.analysis_mode, artifact.analysis_mode)
    rows = [
        ["Analysis mode", mode_label],
        ["Count channel", artifact.channel],
        ["Time unit", artifact.time_unit],
        ["Null RT threshold", f"{artifact.rt_threshold:g}"],
        ["Isoform filter", artifact.isoform],
        ["Peak picker", artifact.peak_picking_algorithm or "—"],
        ["RT resolution source", artifact.rt_source],
        ["Full products", f"{artifact.n_products:,}"],
        ["Null-verified products", f"{artifact.n_verified:,}"],
        ["RT from pedigree", f"{artifact.n_rt_from_pedigree:,}"],
        ["RT from peak pick", f"{artifact.n_rt_from_peak_pick:,}"],
        ["RT from metadata", f"{artifact.n_rt_from_metadata:,}"],
        ["Captured", _format_timestamp(artifact.generated_at)],
    ]
    story.append(_styled_table(rows, col_widths=[2.0 * inch, 4.4 * inch]))


def _append_splittree_session_section(
    story: list,
    artifact: SplittreeVizReportArtifact,
    *,
    heading_style: ParagraphStyle,
    caption_style: ParagraphStyle,
    body_style: ParagraphStyle,
    subheading_style: ParagraphStyle,
) -> None:
    story.append(PageBreak())
    story.append(Paragraph("Split-tree visualization", heading_style))
    story.append(
        Paragraph(
            "Split-tree figure generated on the Split-tree visualization tab "
            "with the settings recorded in the audit trail.",
            body_style,
        )
    )
    story.append(Spacer(1, 0.12 * inch))
    config_rows = [
        ["RT source", artifact.rt_source],
        ["RT column", artifact.rt_column or "—"],
        ["Verification column", artifact.verified_column or "—"],
        ["Isoform", artifact.isoform],
        ["View", artifact.view_mode],
        ["Branch BB1", artifact.branch_bb1 or "—"],
        ["Color mode", artifact.color_mode],
        ["Color by RT", "Yes" if artifact.color_by_rt else "No"],
        ["Pass-rate cutoff (%)", f"{artifact.pass_pct_cutoff:g}"],
        ["Null RT threshold", f"{artifact.rt_threshold:g}"],
        ["Tree RT source", artifact.del_rt_source],
        ["Verified products", f"{artifact.n_verified:,}"],
        ["Captured", _format_timestamp(artifact.generated_at)],
    ]
    story.append(_styled_table(config_rows, col_widths=[2.0 * inch, 4.4 * inch]))
    story.append(Spacer(1, 0.16 * inch))
    if artifact.image_path.is_file():
        title = (
            f"Split-tree ({artifact.view_mode})"
            if artifact.view_mode
            else "Split-tree"
        )
        story.append(Paragraph(title, subheading_style))
        if artifact.caption:
            story.append(Paragraph(artifact.caption, caption_style))
        try:
            story.append(
                _scaled_image(artifact.image_path, max_w=6.8 * inch, max_h=6.8 * inch)
            )
        except Exception as exc:
            logger.warning("Could not embed split-tree figure: %s", exc)
            story.append(Paragraph(f"(Image unavailable: {exc})", caption_style))
        story.append(Spacer(1, 0.2 * inch))


def _append_pedigree_tier_section(
    story: list,
    pedigree: LibraryReportPedigreeFigures,
    *,
    heading_style: ParagraphStyle,
    caption_style: ParagraphStyle,
    body_style: ParagraphStyle,
    subheading_style: ParagraphStyle,
) -> None:
    story.append(PageBreak())
    story.append(Paragraph("Pedigree visualization", heading_style))
    story.append(
        Paragraph(
            "Pedigree tier-ring using the display options active in Library Data "
            "when the report was generated.",
            body_style,
        )
    )
    story.append(Spacer(1, 0.12 * inch))

    if pedigree.tier_ring_path is not None and pedigree.tier_ring_path.is_file():
        story.append(Paragraph("Pedigree tier-ring tree", subheading_style))
        if pedigree.tier_ring_caption:
            story.append(Paragraph(pedigree.tier_ring_caption, caption_style))
        try:
            story.append(_scaled_image(pedigree.tier_ring_path, max_w=6.8 * inch, max_h=6.8 * inch))
        except Exception as exc:
            logger.warning("Could not embed pedigree tier-ring: %s", exc)
            story.append(Paragraph(f"(Image unavailable: {exc})", caption_style))
        story.append(Spacer(1, 0.2 * inch))


def _append_del_cycle_section(
    story: list,
    pedigree: LibraryReportPedigreeFigures,
    *,
    heading_style: ParagraphStyle,
    caption_style: ParagraphStyle,
    body_style: ParagraphStyle,
    subheading_style: ParagraphStyle,
    branch_label_style: ParagraphStyle,
    include_full_tree: bool = True,
    include_section_heading: bool = True,
) -> None:
    branches = [
        branch
        for branch in pedigree.del_branch_figures
        if branch.image_path.is_file()
    ]
    has_full = (
        include_full_tree
        and pedigree.del_full_tree_path is not None
        and pedigree.del_full_tree_path.is_file()
    )
    if not has_full and not branches:
        return

    story.append(PageBreak())
    if include_section_heading:
        story.append(Paragraph("Split-tree visualization", heading_style))
        story.append(
            Paragraph(
                "Split-tree figures using the null RT threshold, coloring, and pass-rate "
                "settings active in Library Data when the report was generated.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.12 * inch))

    bb_index_shown = False

    if has_full:
        story.append(Paragraph("Split-tree (full)", subheading_style))
        if pedigree.del_full_tree_caption:
            story.append(Paragraph(pedigree.del_full_tree_caption, caption_style))
        try:
            story.append(
                _scaled_image(pedigree.del_full_tree_path, max_w=6.8 * inch, max_h=6.8 * inch)
            )
        except Exception as exc:
            logger.warning("Could not embed DEL full tree: %s", exc)
            story.append(Paragraph(f"(Image unavailable: {exc})", caption_style))
        story.append(Spacer(1, 0.2 * inch))
        _append_bb_index_reference(
            story,
            pedigree,
            subheading_style=subheading_style,
            body_style=body_style,
        )
        bb_index_shown = True

    if not branches:
        return

    if has_full:
        story.append(PageBreak())

    story.append(Paragraph("Split-tree BB1 branches", subheading_style))
    if not bb_index_shown:
        _append_bb_index_reference(
            story,
            pedigree,
            subheading_style=subheading_style,
            body_style=body_style,
        )
    story.append(
        Paragraph(
            f"{len(branches)} branch plot(s) in a {BRANCH_GRID_COLS}×{BRANCH_GRID_ROWS} grid "
            f"({BRANCHES_PER_GRID_PAGE} per page).",
            caption_style,
        )
    )
    story.append(Spacer(1, 0.1 * inch))

    col_w = 3.15 * inch
    image_w = 3.0 * inch
    image_h = 2.35 * inch
    for page_start in range(0, len(branches), BRANCHES_PER_GRID_PAGE):
        page_branches = branches[page_start : page_start + BRANCHES_PER_GRID_PAGE]
        grid_rows: List[List[object]] = []
        for row_idx in range(BRANCH_GRID_ROWS):
            row_cells: List[object] = []
            for col_idx in range(BRANCH_GRID_COLS):
                branch_idx = row_idx * BRANCH_GRID_COLS + col_idx
                if branch_idx < len(page_branches):
                    row_cells.append(
                        _branch_cell(
                            page_branches[branch_idx],
                            label_style=branch_label_style,
                            image_w=image_w,
                            image_h=image_h,
                        )
                    )
                else:
                    row_cells.append(Spacer(1, image_h + 0.25 * inch))
            grid_rows.append(row_cells)
        table = Table(grid_rows, colWidths=[col_w] * BRANCH_GRID_COLS)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(table)
        if page_start + BRANCHES_PER_GRID_PAGE < len(branches):
            story.append(PageBreak())


def _append_pedigree_section(
    story: list,
    pedigree: LibraryReportPedigreeFigures,
    *,
    heading_style: ParagraphStyle,
    caption_style: ParagraphStyle,
    body_style: ParagraphStyle,
    subheading_style: ParagraphStyle,
    branch_label_style: ParagraphStyle,
    include_pedigree: bool,
    include_del_cycle: bool,
) -> None:
    """Embed pedigree tier-ring and/or split-tree figures based on report options."""
    if include_pedigree:
        _append_pedigree_tier_section(
            story,
            pedigree,
            heading_style=heading_style,
            caption_style=caption_style,
            body_style=body_style,
            subheading_style=subheading_style,
        )
    if include_del_cycle:
        _append_del_cycle_section(
            story,
            pedigree,
            heading_style=heading_style,
            caption_style=caption_style,
            body_style=body_style,
            subheading_style=subheading_style,
            branch_label_style=branch_label_style,
        )


def generate_library_report_pdf(
    snapshot: LibraryComputationSnapshot,
    output_path: Path,
    *,
    plot_results: Optional[Sequence[PlotResult]] = None,
    report_options: Optional[LibraryReportOptions] = None,
    audit: Optional[LibraryReportAuditTrail] = None,
    rt_assignment: Optional[RtAssignmentReportArtifact] = None,
    pedigree_viz: Optional[PedigreeVizReportArtifact] = None,
    splittree_viz: Optional[SplittreeVizReportArtifact] = None,
    pedigree_figures: Optional[LibraryReportPedigreeFigures] = None,
) -> Path:
    """
    Write a multi-section PDF report for one library analysis session.

    Args:
        snapshot: Metrics and provenance to include.
        output_path: Destination ``.pdf`` file.
        plot_results: Plot PNG paths to embed; defaults to ``snapshot.plot_results``.

    Returns:
        Resolved path to the written PDF.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    plots = list(plot_results if plot_results is not None else snapshot.plot_results)
    opts = report_options or LibraryReportOptions(
        include_metrics=bool(snapshot.metric_results),
        include_plots=bool(plots),
        include_rt_assignment=rt_assignment is not None,
        include_pedigree_viz=pedigree_viz is not None,
        include_splittree=splittree_viz is not None,
        metric_ids=list(snapshot.selected_metrics),
        plot_ids=list(snapshot.selected_plots),
        channels=list(snapshot.selected_channels),
    )
    if pedigree_viz is not None:
        pedigree_figures = merge_report_pedigree_figures(
            pedigree_figures,
            LibraryReportPedigreeFigures(
                tier_ring_path=pedigree_viz.image_path,
                tier_ring_caption=pedigree_viz.caption,
            ),
        )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        spaceAfter=14,
    )
    heading_style = ParagraphStyle(
        "ReportHeading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#1F3A5F"),
        spaceBefore=12,
        spaceAfter=8,
    )
    subheading_style = ParagraphStyle(
        "ReportSubheading",
        parent=styles["Heading3"],
        fontSize=12,
        textColor=colors.HexColor("#1F3A5F"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
    )
    caption_style = ParagraphStyle(
        "PlotCaption",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=10,
    )
    branch_label_style = ParagraphStyle(
        "BranchLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        alignment=TA_CENTER,
        spaceAfter=4,
    )

    story: list = []
    story.append(Paragraph("LC-Seq Library Data Report", title_style))
    story.append(Spacer(1, 0.15 * inch))

    summary_rows = [
        ["Database", snapshot.database_name],
        ["Database path", snapshot.database_path],
        ["Generated", _format_timestamp(snapshot.processed_at)],
        ["Entries parsed", f"{snapshot.entries_used:,} of {snapshot.entries_attempted:,}"],
        ["Entries skipped", f"{snapshot.entries_skipped:,}"],
    ]
    if opts.include_metrics:
        qc_opts = snapshot.signal_quality_options
        summary_rows.extend(
            [
                ["Fraction count", str(snapshot.fraction_count)],
                ["QC peak picker", qc_opts.picker_label()],
            ]
        )
        if qc_opts.peak_picking_algorithm == "modern":
            summary_rows.append(["QC peak significance α", f"{qc_opts.alpha:g}"])
    summary_rows.append(["Count channels", ", ".join(snapshot.selected_channels) or "—"])
    sections = []
    if opts.include_metrics:
        sections.append("Summary metrics")
    if opts.include_plots:
        sections.append("Visualizations")
    if opts.include_rt_assignment:
        sections.append("RT assignment")
    if opts.include_pedigree_viz:
        sections.append("Pedigree visualization")
    if opts.include_splittree:
        sections.append("Split-tree visualization")
    summary_rows.append(["Report sections", ", ".join(sections) or "—"])
    story.append(_styled_table(summary_rows, col_widths=[1.6 * inch, 4.8 * inch]))

    if audit is not None:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Audit trail", heading_style))
        story.append(
            Paragraph(
                "Settings and provenance captured at report generation time.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.08 * inch))
        story.append(_styled_table(audit.audit_rows(), col_widths=[2.0 * inch, 4.4 * inch]))

    story.append(PageBreak())
    story.append(Paragraph("Methodology", heading_style))
    if opts.include_metrics or opts.include_plots:
        story.append(Paragraph(_METHODOLOGY_TEXT, body_style))
        story.append(Spacer(1, 0.2 * inch))
    else:
        story.append(
            Paragraph(
                "This report embeds session artifacts generated in Library Analysis. "
                "Run additional analyses in the app before generating a report if you "
                "need library QC methodology sections.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.2 * inch))

    if opts.include_rt_assignment and rt_assignment is not None:
        _append_rt_assignment_section(
            story,
            rt_assignment,
            heading_style=heading_style,
            body_style=body_style,
        )

    if opts.include_metrics:
        coverage_metrics = [
            m
            for m in snapshot.metric_results
            if LIBRARY_METRIC_DEFINITIONS.get(m.metric_id, None)
            and LIBRARY_METRIC_DEFINITIONS[m.metric_id].category == "coverage"
        ]
        signal_metrics = [
            m
            for m in snapshot.metric_results
            if LIBRARY_METRIC_DEFINITIONS.get(m.metric_id, None)
            and LIBRARY_METRIC_DEFINITIONS[m.metric_id].category == "signal"
        ]

        if coverage_metrics or signal_metrics:
            story.append(PageBreak())
            story.append(Paragraph("Summary metrics", heading_style))

        if coverage_metrics:
            story.append(Paragraph("Coverage metrics", subheading_style))
            for metric in coverage_metrics:
                story.append(Paragraph(metric.title, styles["Heading3"]))
                story.append(
                    _styled_table(
                        _metric_table_rows(metric),
                        col_widths=[1.4 * inch, 2.4 * inch, 0.8 * inch],
                    )
                )
                story.append(Spacer(1, 0.12 * inch))

        if signal_metrics:
            qc_opts = snapshot.signal_quality_options
            if qc_opts.peak_picking_algorithm == "old_school":
                signal_intro = (
                    "All signal metrics computed with old-school Gaussian peak picking."
                )
            else:
                signal_intro = (
                    f"All signal metrics computed with modern peak picking (α = {qc_opts.alpha:g})."
                )
            story.append(Paragraph("Signal-quality metrics", subheading_style))
            story.append(Paragraph(signal_intro, body_style))
            story.append(Spacer(1, 0.08 * inch))
            for metric in signal_metrics:
                story.append(Paragraph(metric.title, styles["Heading3"]))
                story.append(
                    _styled_table(
                        _metric_table_rows(metric),
                        col_widths=[1.4 * inch, 2.4 * inch, 0.8 * inch],
                    )
                )
                story.append(Spacer(1, 0.12 * inch))

    if opts.include_plots:
        valid_plots = [
            p
            for p in plots
            if p.image_path is not None and Path(p.image_path).is_file()
        ]
        if valid_plots:
            story.append(PageBreak())
            story.append(Paragraph("Visualizations", heading_style))
            for plot in valid_plots:
                story.append(Paragraph(plot.title, styles["Heading3"]))
                if plot.help_text:
                    story.append(Paragraph(plot.help_text, caption_style))
                img_path = Path(plot.image_path)
                try:
                    story.append(_scaled_image(img_path, max_w=6.5 * inch, max_h=4.5 * inch))
                except Exception as exc:
                    logger.warning("Could not embed plot %s: %s", plot.plot_id, exc)
                    story.append(Paragraph(f"(Plot image unavailable: {exc})", caption_style))
                story.append(Spacer(1, 0.2 * inch))

    if pedigree_figures is not None and opts.include_pedigree_viz:
        _append_pedigree_section(
            story,
            pedigree_figures,
            heading_style=heading_style,
            caption_style=caption_style,
            body_style=body_style,
            subheading_style=subheading_style,
            branch_label_style=branch_label_style,
            include_pedigree=True,
            include_del_cycle=False,
        )

    if opts.include_splittree and splittree_viz is not None:
        _append_splittree_session_section(
            story,
            splittree_viz,
            heading_style=heading_style,
            caption_style=caption_style,
            body_style=body_style,
            subheading_style=subheading_style,
        )
        if pedigree_figures is not None and pedigree_figures.del_branch_figures:
            splittree_shows_full = splittree_viz.view_mode.strip().lower() in (
                "full tree",
                "full",
            )
            _append_del_cycle_section(
                story,
                pedigree_figures,
                heading_style=heading_style,
                caption_style=caption_style,
                body_style=body_style,
                subheading_style=subheading_style,
                branch_label_style=branch_label_style,
                include_full_tree=not splittree_shows_full,
                include_section_heading=False,
            )

    doc = SimpleDocTemplate(
        str(target),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"LC-Seq Library Report — {snapshot.database_name}",
    )
    doc.build(story)
    logger.info("Wrote library report PDF: %s", target)
    return target.resolve()
