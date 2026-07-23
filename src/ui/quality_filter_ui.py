# src/ui/quality_filter_ui.py
"""Shared labels and tooltips for min-prominence / min-%-area quality filters.

These post-detection filters are the same scalars across Chromatogram Visualizer,
Library QC, and Pedigree RT assignment. Direct pick RT assignment does not use them.
"""

from __future__ import annotations

# Section titles — scope differs by surface (QC/Visualizer vs RT Assignment).
QUALITY_FILTERS_BOTH_PICKERS_TITLE = "Quality filters (both pickers)"
QUALITY_FILTERS_PEDIGREE_ONLY_TITLE = "Quality filters (Pedigree mode only)"

QUALITY_MIN_PROMINENCE_LABEL = "Min prominence"
QUALITY_MIN_PCT_AREA_LABEL = "Min % area"

QUALITY_BOTH_PICKERS_NOTE = (
    "Applied after detection for modern and old-school picking."
)
QUALITY_PEDIGREE_ACTIVE_NOTE = (
    "Applied after detection for modern and old-school Pedigree runs."
)
QUALITY_PEDIGREE_INACTIVE_NOTE = (
    "Not used in Direct pick — product RT is the latest peak after picker "
    "rules only. Values are kept if you switch back to Pedigree."
)

QUALITY_PROMINENCE_TOOLTIP_BOTH = (
    "Minimum peak prominence (counts). Applied after detection for both modern "
    "and old-school. Set 0 to disable."
)
QUALITY_PCT_AREA_TOOLTIP_BOTH = (
    "Minimum percent of total detected peak area. Applied after detection for "
    "both modern and old-school. Set 0 to disable."
)
QUALITY_PROMINENCE_TOOLTIP_PEDIGREE = (
    "Pedigree mode only: drop detected peaks below this prominence after picking "
    "(modern or old-school). 0 = off. Not used by Direct pick."
)
QUALITY_PCT_AREA_TOOLTIP_PEDIGREE = (
    "Pedigree mode only: drop detected peaks below this share of total detected "
    "peak area (modern or old-school). 0 = off. Not used by Direct pick."
)
