# src/core/library_report.py
"""
Generate a PDF library report from a computation snapshot and plot images.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from reportlab.lib import colors
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
These are library-wide screening values. Pedigree-validated product-peak prominence is planned
for a future release.
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


def generate_library_report_pdf(
    snapshot: LibraryComputationSnapshot,
    output_path: Path,
    *,
    plot_results: Optional[Sequence[PlotResult]] = None,
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

    story: list = []
    story.append(Paragraph("LC-Seq Library Data Report", title_style))
    story.append(Spacer(1, 0.15 * inch))

    summary_rows = [
        ["Database", snapshot.database_name],
        ["Database path", snapshot.database_path],
        ["Generated", _format_timestamp(snapshot.processed_at)],
        ["Entries parsed", f"{snapshot.entries_used:,} of {snapshot.entries_attempted:,}"],
        ["Entries skipped", f"{snapshot.entries_skipped:,}"],
        ["Fraction count", str(snapshot.fraction_count)],
        ["Peak significance α", f"{snapshot.signal_quality_alpha:g}"],
        ["Count channels", ", ".join(snapshot.selected_channels) or "—"],
    ]
    story.append(_styled_table(summary_rows, col_widths=[1.6 * inch, 4.8 * inch]))
    story.append(PageBreak())

    story.append(Paragraph("Methodology", heading_style))
    story.append(Paragraph(_METHODOLOGY_TEXT, body_style))
    story.append(Spacer(1, 0.2 * inch))

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

    if coverage_metrics:
        story.append(Paragraph("Coverage metrics", heading_style))
        for metric in coverage_metrics:
            story.append(Paragraph(metric.title, styles["Heading3"]))
            story.append(_styled_table(_metric_table_rows(metric), col_widths=[1.4 * inch, 2.4 * inch, 0.8 * inch]))
            story.append(Spacer(1, 0.12 * inch))

    if signal_metrics:
        story.append(Paragraph("Signal-quality metrics", heading_style))
        story.append(
            Paragraph(
                f"All signal metrics computed with α = {snapshot.signal_quality_alpha:g}.",
                body_style,
            )
        )
        story.append(Spacer(1, 0.08 * inch))
        for metric in signal_metrics:
            story.append(Paragraph(metric.title, styles["Heading3"]))
            story.append(_styled_table(_metric_table_rows(metric), col_widths=[1.4 * inch, 2.4 * inch, 0.8 * inch]))
            story.append(Spacer(1, 0.12 * inch))

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
                img = Image(str(img_path))
                max_w = 6.5 * inch
                max_h = 4.5 * inch
                scale = min(max_w / img.drawWidth, max_h / img.drawHeight, 1.0)
                img.drawWidth *= scale
                img.drawHeight *= scale
                story.append(img)
            except Exception as exc:
                logger.warning("Could not embed plot %s: %s", plot.plot_id, exc)
                story.append(Paragraph(f"(Plot image unavailable: {exc})", caption_style))
            story.append(Spacer(1, 0.2 * inch))

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
