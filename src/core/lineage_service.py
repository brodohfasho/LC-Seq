# src/core/lineage_service.py
"""
Single-compound null-truncation lineage analysis service.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.data_processor import DataProcessor
from src.core.data_store import DataStore
from src.core.library_metrics import _hydrate_index_compound
from src.core.lineage_ancestors import (
    class_id_for,
    compound_id_for,
    enumerate_lineage_ancestors,
)
from src.core.pedigree_adapter import (
    ChromatogramKey,
    build_chromatogram_map,
    class_key_from_positions,
    filter_compounds_by_variant,
    infer_bbs_per_position,
    members_of_class,
    truncate_positions_from_metadata,
)
from src.core.lineage_cache import LineageSessionCache
from src.core.pedigree_backend import get_pedigree_backend
from src.models.analysis_settings import AnalysisSettings
from src.models.compound import Compound
from src.models.pedigree_result import (
    LineageAnalysisResult,
    LineageBatchResult,
    LineagePanel,
    PedigreeNodeRecord,
)
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

ChromatogramMap = Dict[ChromatogramKey, Tuple[Any, Any]]


def load_all_compounds(
    store: DataStore,
    config: SpreadsheetConfig,
    *,
    index_database: bool,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Compound]:
    """
    Load every compound row from the active database in the **current thread**.

    Index databases parse raw chromatogram text on demand (same as library scan).
    """
    processor = DataProcessor()
    compound_ids = store.get_all_compound_ids()
    total = len(compound_ids)
    compounds: List[Compound] = []

    for i, cid in enumerate(compound_ids, start=1):
        base = store.get_compound(cid)
        if base is None:
            continue
        compound = base
        if index_database:
            compound = _hydrate_index_compound(store, config, processor, base)
        if compound is not None:
            compounds.append(compound)
        if progress_callback is not None and (i % 250 == 0 or i == total):
            progress_callback(
                i,
                total,
                f"Loading library compounds… {i:,} / {total:,}",
            )

    return compounds


def analyze_lineage(
    store: DataStore,
    compound: Compound,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    index_database: bool,
    progress_callback: Optional[ProgressCallback] = None,
    session_cache: Optional[LineageSessionCache] = None,
) -> LineageAnalysisResult:
    """
    Run full-library pedigree evaluation and extract ancestor panels for one compound.

    ``store`` must be opened in the calling thread (see ``analyze_lineage_for_path``).
    """
    if not config.pedigree_configured():
        raise ValueError(
            "Pedigree is not configured. Map BB1..BBn columns in Configure Spreadsheet."
        )

    positions = truncate_positions_from_metadata(compound, config)
    if positions is None:
        raise ValueError(
            f"Compound {compound.compound_id!r} is missing BB metadata required for lineage."
        )

    leaf_class_bbs = class_key_from_positions(positions, config.null_token)
    backend = get_pedigree_backend()

    def emit(step: int, status: str) -> None:
        if progress_callback is not None:
            progress_callback(step, 4, status)

    if session_cache is None:
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
            with_bb = sum(
                1
                for c in filtered
                if truncate_positions_from_metadata(c, config) is not None
            )
            with_data = sum(1 for c in filtered if c.data_points)
            raise ValueError(
                f"No chromatograms found for channel {settings.count_channel!r}. "
                f"Loaded {len(filtered)} compound(s) ({with_bb} with BB metadata, "
                f"{with_data} with parsed chromatogram data). "
                "For index databases, parsing every entry can take several minutes."
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
        records_by_id = {r.id: r for r in records}
    else:
        all_compounds = session_cache.get_or_load_compounds(
            store,
            config,
            index_database=index_database,
            progress_callback=progress_callback,
        )
        pedigree = session_cache.get_or_evaluate_pedigree(
            all_compounds,
            config,
            settings,
            progress_callback=progress_callback,
        )
        chromatogram_map = pedigree.chromatogram_map
        records_by_id = pedigree.records_by_id

    emit(3, "Resolving lineage panels…")
    ancestor_classes = enumerate_lineage_ancestors(leaf_class_bbs)
    panels: List[LineagePanel] = []
    for class_bbs in ancestor_classes:
        cid_class = class_id_for(class_bbs)
        cid_compound = compound_id_for(class_bbs) if class_bbs else None
        record = records_by_id.get(cid_class)
        if record is None and cid_compound:
            record = records_by_id.get(cid_compound)
        if record is None:
            continue
        members = members_of_class(class_bbs, chromatogram_map, config.null_token)
        if not members and record.tier > 0:
            logger.warning("No chromatograms for lineage node %s", class_bbs)
        eff_thr = record.effective_threshold if record.effective_threshold is not None else 0.0
        panels.append(
            LineagePanel(
                class_bbs=list(class_bbs),
                tier=record.tier,
                n_replicates=len(members),
                effective_threshold=float(eff_thr),
                record=record,
            )
        )

    panels.sort(key=lambda p: p.tier)

    return LineageAnalysisResult(
        compound_id=str(compound.compound_id),
        leaf_class_bbs=leaf_class_bbs,
        channel=settings.count_channel,
        settings=settings,
        panels=panels,
        records_by_id=records_by_id,
        backend_name=backend.info(),
        computed_at=datetime.now(timezone.utc),
        chromatogram_map=chromatogram_map,
    )


def analyze_lineage_for_path(
    db_path: Path,
    compound: Compound,
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    session_cache: Optional[LineageSessionCache] = None,
) -> LineageAnalysisResult:
    """Thread-safe: open the database in the current thread, then run lineage analysis."""
    store = DataStore(db_path=db_path, use_memory=False)
    try:
        return analyze_lineage(
            store,
            compound,
            config,
            settings,
            index_database=store.is_index_database(),
            progress_callback=progress_callback,
            session_cache=session_cache,
        )
    finally:
        store.close()


def analyze_lineage_batch_for_path(
    db_path: Path,
    compounds: List[Compound],
    config: SpreadsheetConfig,
    settings: AnalysisSettings,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    session_cache: Optional[LineageSessionCache] = None,
) -> LineageBatchResult:
    """
    Run lineage analysis for multiple compounds, reusing one library/pedigree cache.

    Thread-safe: opens the database once in the calling thread.
    """
    if not compounds:
        return LineageBatchResult()

    store = DataStore(db_path=db_path, use_memory=False)
    results: List[LineageAnalysisResult] = []
    failed: List[Tuple[str, str]] = []
    total = len(compounds)
    try:
        index_db = store.is_index_database()
        for index, compound in enumerate(compounds, start=1):
            cid = str(compound.compound_id).strip()

            def emit_per_compound(step: int, _total: int, status: str) -> None:
                if progress_callback is not None:
                    progress_callback(
                        index - 1,
                        total,
                        f"({index}/{total}) {cid}: {status}",
                    )

            try:
                result = analyze_lineage(
                    store,
                    compound,
                    config,
                    settings,
                    index_database=index_db,
                    progress_callback=emit_per_compound,
                    session_cache=session_cache,
                )
                results.append(result)
            except Exception as exc:
                logger.warning("Lineage failed for %s: %s", cid, exc)
                failed.append((cid, str(exc)))
    finally:
        store.close()

    return LineageBatchResult(
        results=tuple(results),
        failed=tuple(failed),
    )
