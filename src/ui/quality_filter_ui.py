# src/ui/quality_filter_ui.py
"""Shared labels and tooltips for modern-only min-prominence / min-%-area filters.

These post-detection filters apply with the modern (NB/Poisson) picker across
Chromatogram Visualizer, Library QC, and RT assignment (Pedigree and Direct pick).
Old-school picking uses its own height / Gaussian / minimum-RT parameters instead.
"""

from __future__ import annotations

QUALITY_FILTERS_MODERN_TITLE = "Quality filters (modern only)"

QUALITY_MIN_PROMINENCE_LABEL = "Min prominence"
QUALITY_MIN_PCT_AREA_LABEL = "Min % area"

QUALITY_MODERN_NOTE = (
    "Applied after modern detection. Not used with old-school picking."
)

QUALITY_PROMINENCE_TOOLTIP = (
    "Modern only: minimum peak prominence (counts) after NB/Poisson detection. "
    "Set 0 to disable. Not applied with old-school picking."
)
QUALITY_PCT_AREA_TOOLTIP = (
    "Modern only: minimum percent of total detected peak area after NB/Poisson "
    "detection. Set 0 to disable. Not applied with old-school picking."
)
