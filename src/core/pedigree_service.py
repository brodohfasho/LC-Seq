# src/core/pedigree_service.py
"""
Full-library pedigree (split-tree) analysis service.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from src.core.data_store import DataStore
from src.core.lineage_service import load_all_compounds
from src.core.pedigree_adapter import (
    build_chromatogram_map,
    filter_compounds_by_variant,
    infer_bbs_per_position,
)
from src.core.pedigree_backend import get_pedigree_backend
from src.core.pedigree_product_prominence import compute_product_prominence_summary
from src.models.analysis_settings import AnalysisSettings
from src.models.pedigree_result import (
    PedigreeAnalysisResult,
    PedigreeNodeRecord,
    PedigreeTierSummary,
    ProductProminenceSummary,
)
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]


def summarize_by_tier(records: List[PedigreeNodeRecord]) -> List[PedigreeTierSummary]:
    """Match buddy CLI ``_summarise`` tier pass/fail/pruned counts."""
    by_tier_pass: Counter[int] = Counter()
    by_tier_fail: Counter[int] = Counter()
    by_tier_pruned: Counter[int] = Counter()
    for record in records:
        if record.passed:
            by_tier_pass[record.tier] += 1
        elif record.evaluated:
            by_tier_fail[record.tier] += 1
        else:
            by_tier_pruned[record.tier] += 1
    tiers = sorted(set(by_tier_pass) | set(by_tier_fail) | set(by_tier_pruned))
    return [
        PedigreeTierSummary(
            tier=tier,
            pass_count=by_tier_pass[tier],
            fail_count=by_tier_fail[tier],
            pruned_count=by_tier_pruned[tier],
        )
        for tier in tiers
    ]


def default_max_display_tier(config: SpreadsheetConfig) -> Optional[int]:
    """Hide the final compound-leaf tier by default (noisy cycle cluster)."""
    n = config.library_cycle_count
    if n <= 0:
        return None
    return max(0, n - 1)


def run_pedigree_analysis(
    store: DataStore,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    index_database: bool,
    progress_callback: Optional[ProgressCallback] = None,
    max_display_tier: Optional[int] = None,
    isoform_label: str = "All",
) -> PedigreeAnalysisResult:
    """
    Run full-library pedigree evaluation on the active database.

    ``store`` must be opened in the calling thread (see ``run_pedigree_analysis_for_path``).
    """
    if not config.pedigree_configured():
        raise ValueError(
            "Pedigree is not configured. Map BB1..BBn columns in Configure Spreadsheet."
        )

    backend = get_pedigree_backend()
    display_tier = (
        default_max_display_tier(config) if max_display_tier is None else max_display_tier
    )

    def emit(step: int, status: str) -> None:
        if progress_callback is not None:
            progress_callback(step, 3, status)

    emit(0, "Loading library compounds…")
    all_compounds = load_all_compounds(
        store,
        config,
        index_database=index_database,
        progress_callback=progress_callback,
    )

    emit(1, "Building chromatogram map…")
    filtered = filter_compounds_by_variant(all_compounds, settings.selected_variants)
    chromatogram_map = build_chromatogram_map(
        filtered,
        settings.count_channel,
        config,
        time_unit=settings.time_unit,
    )
    if not chromatogram_map:
        raise ValueError(
            f"No chromatograms found for channel {settings.count_channel!r}. "
            f"Loaded {len(filtered)} compound(s). "
            "For index databases, ensure BB metadata and chromatogram data are present."
        )

    emit(2, "Running pedigree evaluation…")
    bbs_per_position = infer_bbs_per_position(filtered, config)
    records = backend.evaluate_library(
        bbs_per_position,
        config.null_token,
        chromatogram_map,
        settings.tolerance,
        settings.alpha,
        min_prominence=settings.min_prominence,
        min_pct_area=settings.min_pct_area,
        settings=settings,
    )
    tier_summaries = summarize_by_tier(records)

    product_prominence = compute_product_prominence_summary(
        records,
        filtered,
        config,
        settings.count_channel,
    )

    return PedigreeAnalysisResult(
        database_path=str(store.db_path),
        channel=settings.count_channel,
        settings=settings,
        null_token=config.null_token,
        library_cycle_count=config.library_cycle_count,
        records=records,
        tier_summaries=tier_summaries,
        backend_name=backend.info(),
        computed_at=datetime.now(timezone.utc),
        n_compounds_loaded=len(filtered),
        n_chromatograms=len(chromatogram_map),
        max_display_tier=display_tier,
        isoform_label=isoform_label,
        product_prominence=product_prominence,
    )


def run_pedigree_analysis_for_path(
    db_path: Path,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    max_display_tier: Optional[int] = None,
    isoform_label: str = "All",
) -> PedigreeAnalysisResult:
    """Thread-safe: open the database in the current thread, then run pedigree analysis."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        return run_pedigree_analysis(
            store,
            config,
            settings,
            index_database=store.is_index_database(),
            progress_callback=progress_callback,
            max_display_tier=max_display_tier,
            isoform_label=isoform_label,
        )
    finally:
        store.close()
