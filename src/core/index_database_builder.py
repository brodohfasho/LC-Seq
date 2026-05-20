# src/core/index_database_builder.py
"""
Build SQLite index databases: searchable metadata columns plus raw chromatogram text (no data_points).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from src.core.data_processing_result import DataProcessingResult
from src.core.data_processor import DataProcessor
from src.core.data_store import DB_KIND_INDEX, DataStore
from src.models.spreadsheet_config import SpreadsheetConfig

logger = logging.getLogger(__name__)

_INDEX_BATCH_SIZE = 2000


def build_index_database_from_dataframe(
    df: pd.DataFrame,
    config: SpreadsheetConfig,
    db_path: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_event: Optional[object] = None,
) -> DataProcessingResult:
    """
    Write an index database from an in-memory dataframe.

    Args:
        df: Loaded spreadsheet data.
        config: Saved spreadsheet configuration.
        db_path: Target SQLite path (typically unused empty path from allocator).
        progress_callback: Optional (processed, total, status) updates.
        cancel_event: Optional ``threading.Event`` with ``is_set()``.

    Returns:
        Processing result with counts and ``database_path`` set.
    """
    result = DataProcessingResult()
    result.started_at = datetime.now()
    result.database_path = str(db_path.resolve())
    total = len(df)
    result.total_rows = total

    processor = DataProcessor()
    store: Optional[DataStore] = None
    try:
        store = DataStore(db_path=db_path, use_memory=False)
        store.set_database_kind(DB_KIND_INDEX)
        meta_cols = list(config.selected_metadata_columns or [])
        if meta_cols:
            store.create_metadata_columns(meta_cols, create_indexes=False)

        batch: List[Dict] = []
        inserted = 0

        def flush() -> None:
            nonlocal batch, inserted
            if not batch:
                return
            n = store.add_index_compounds_batch(batch, meta_cols)
            inserted += n
            batch = []

        for row_num, (_, series) in enumerate(df.iterrows(), start=1):
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                result.cancelled = True
                break
            extracted = processor.extract_index_row_from_series(
                series, config, row_num, result
            )
            if extracted is not None:
                batch.append(extracted)
            if len(batch) >= _INDEX_BATCH_SIZE:
                flush()
            if progress_callback and (row_num % 500 == 0 or row_num == total):
                progress_callback(row_num, total, f"Indexing row {row_num:,} / {total:,}")

        if not result.cancelled:
            flush()

        if meta_cols and not result.cancelled:
            store.create_all_indexes(meta_cols)

        result.successful_compounds = inserted
    finally:
        if store is not None:
            store.close()

    result.completed_at = datetime.now()
    if result.started_at:
        result.processing_time_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
    logger.info(
        "Index database build: %s compounds -> %s (cancelled=%s)",
        result.successful_compounds,
        db_path,
        result.cancelled,
    )
    return result
