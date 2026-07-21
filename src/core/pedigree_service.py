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
from src.core.library_metrics import LibraryScanData
from src.core.lineage_service import load_all_compounds
from src.core.pedigree_adapter import (
    build_chromatogram_map,
    build_chromatogram_map_from_scan,
    compounds_with_scan_chromatograms,
    filter_compounds_by_variant,
    infer_bbs_per_position,
    infer_bbs_per_position_from_map,
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

_PROGRESS_SCALE = 1000


def _make_fraction_emitter(
    progress_callback: Optional[ProgressCallback],
) -> Callable[[float, str], None]:
    """Adapt a ``(step, total, status)`` callback to a ``(fraction, status)`` API.

    Fractions are reported on a fixed 0..1000 scale so the UI progress bar advances
    smoothly through every phase instead of snapping between coarse integer steps.
    """

    def emit(fraction: float, status: str) -> None:
        if progress_callback is None:
            return
        clamped = min(1.0, max(0.0, fraction))
        progress_callback(int(round(clamped * _PROGRESS_SCALE)), _PROGRESS_SCALE, status)

    return emit


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


def run_pedigree_analysis_from_scan(
    store: DataStore,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    scan: LibraryScanData,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    max_display_tier: Optional[int] = None,
    isoform_label: str = "All",
) -> PedigreeAnalysisResult:
    """
    Run pedigree evaluation using a cached library scan instead of reloading chromatograms.

    Metadata (BB positions, isoform labels) is loaded from SQLite without ``data_points``.
    """
    if not config.pedigree_configured():
        raise ValueError(
            "Pedigree is not configured. Map BB1..BBn columns in Configure Spreadsheet."
        )
    if settings.count_channel not in scan.channel_names:
        raise ValueError(
            f"Scan does not include pedigree channel {settings.count_channel!r}. "
            f"Available channels: {', '.join(scan.channel_names) or 'none'}."
        )

    backend = get_pedigree_backend()
    display_tier = (
        default_max_display_tier(config) if max_display_tier is None else max_display_tier
    )

    emit = _make_fraction_emitter(progress_callback)

    emit(0.05, "Loading compound metadata from scan…")
    compound_ids = [str(entry.compound_id) for entry in scan.entries]
    metadata_by_id = store.load_compound_metadata_map(compound_ids)

    emit(0.30, "Building chromatogram map from scan…")
    chromatogram_map, metadata_stubs = build_chromatogram_map_from_scan(
        scan,
        metadata_by_id,
        settings.count_channel,
        config,
        time_unit=settings.time_unit,
        selected_variants=settings.selected_variants,
    )
    if not chromatogram_map:
        raise ValueError(
            f"No chromatograms found for channel {settings.count_channel!r} "
            f"from {len(scan.entries):,} scanned entr"
            f"{'y' if len(scan.entries) == 1 else 'ies'}. "
            "Ensure BB metadata is present and the scan includes the selected channel."
        )

    # Rust evaluation cannot report sub-progress, so hold an honest mid-run value
    # while it runs rather than jumping to near-complete.
    emit(0.50, "Running pedigree evaluation…")
    bbs_per_position = infer_bbs_per_position_from_map(chromatogram_map, config)
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
    emit(0.72, "Summarizing pedigree tiers…")
    tier_summaries = summarize_by_tier(records)

    emit(0.85, "Computing product prominence…")
    prominence_compounds = compounds_with_scan_chromatograms(
        scan,
        metadata_stubs,
        selected_variants=settings.selected_variants,
    )
    product_prominence = compute_product_prominence_summary(
        records,
        prominence_compounds,
        config,
        settings.count_channel,
    )

    emit(0.93, "Finalizing pedigree result…")
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
        n_compounds_loaded=len(metadata_stubs),
        n_chromatograms=len(chromatogram_map),
        max_display_tier=display_tier,
        isoform_label=isoform_label,
        product_prominence=product_prominence,
    )


def run_pedigree_analysis(
    store: DataStore,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    index_database: bool,
    scan: Optional[LibraryScanData] = None,
    progress_callback: Optional[ProgressCallback] = None,
    max_display_tier: Optional[int] = None,
    isoform_label: str = "All",
) -> PedigreeAnalysisResult:
    """
    Run full-library pedigree evaluation on the active database.

    When ``scan`` is provided, chromatogram arrays are taken from the cached library
    scan and only compound metadata is read from SQLite.

    ``store`` must be opened in the calling thread (see ``run_pedigree_analysis_for_path``).
    """
    if scan is not None:
        return run_pedigree_analysis_from_scan(
            store,
            config,
            settings,
            scan,
            progress_callback=progress_callback,
            max_display_tier=max_display_tier,
            isoform_label=isoform_label,
        )

    if not config.pedigree_configured():
        raise ValueError(
            "Pedigree is not configured. Map BB1..BBn columns in Configure Spreadsheet."
        )

    backend = get_pedigree_backend()
    display_tier = (
        default_max_display_tier(config) if max_display_tier is None else max_display_tier
    )

    emit = _make_fraction_emitter(progress_callback)

    # Loading rows dominates this path; map its own row-level callback into an
    # early 0.05..0.40 band so the bar climbs through loading, not to completion.
    def load_progress(done: int, total: int, status: str) -> None:
        fraction = (done / total) if total > 0 else 0.0
        emit(0.05 + 0.35 * min(1.0, max(0.0, fraction)), status)

    emit(0.05, "Loading library compounds…")
    all_compounds = load_all_compounds(
        store,
        config,
        index_database=index_database,
        progress_callback=load_progress,
    )

    emit(0.45, "Building chromatogram map…")
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

    # Rust evaluation cannot report sub-progress, so hold an honest mid-run value
    # while it runs rather than jumping to near-complete.
    emit(0.55, "Running pedigree evaluation…")
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
    emit(0.78, "Summarizing pedigree tiers…")
    tier_summaries = summarize_by_tier(records)

    emit(0.88, "Computing product prominence…")
    product_prominence = compute_product_prominence_summary(
        records,
        filtered,
        config,
        settings.count_channel,
    )

    emit(0.93, "Finalizing pedigree result…")
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
    scan: Optional[LibraryScanData] = None,
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
            scan=scan,
            progress_callback=progress_callback,
            max_display_tier=max_display_tier,
            isoform_label=isoform_label,
        )
    finally:
        store.close()
