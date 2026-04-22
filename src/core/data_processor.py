# src/core/data_processor.py
"""
Data processing engine for parsing and storing spreadsheet data.
"""

import logging
import threading
import pandas as pd
import time
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime

from src.models.spreadsheet_config import SpreadsheetConfig
from src.models.compound import Compound
from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.core.data_store import DataStore
from src.core.data_processing_result import DataProcessingResult, ProcessingError
from src.core import database_library
from src.utils.data_parser import DataParser

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Processes spreadsheet data into searchable database.
    
    Handles:
    - Chunked CSV processing for large files
    - Parsing chromatographic data using configured delimiters
    - Extracting metadata columns
    - Storing in SQLite database
    - Progress reporting
    """
    
    DEFAULT_CHUNK_SIZE = 10000  # Process 10K rows at a time
    DEFAULT_BATCH_SIZE = 5000  # Insert 5K compounds per batch for optimal performance
    
    def __init__(self):
        """Initialize data processor."""
        self.result: Optional[DataProcessingResult] = None
    
    @staticmethod
    def _delete_database_files(db_path: Path) -> None:
        """Remove on-disk database and SQLite sidecar files if present."""
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(db_path) + suffix) if suffix else db_path
            try:
                if path.is_file():
                    path.unlink()
                    logger.debug("Removed %s", path)
            except OSError as exc:
                logger.warning("Could not remove %s: %s", path, exc)
    
    def _finalize_cancellation(
        self,
        data_store: DataStore,
        db_path: Optional[Path],
        use_memory: bool,
        result: DataProcessingResult,
        compounds_batch: List[Any],
        progress_callback: Optional[Callable[[int, int, str], None]],
        processed_rows: int,
        total_rows: int,
    ) -> None:
        """Close store, remove partial DB, and mark result cancelled."""
        compounds_batch.clear()
        try:
            data_store.close()
        except Exception as exc:
            logger.warning("Error closing database after cancel: %s", exc)
        if not use_memory and db_path is not None:
            self._delete_database_files(Path(db_path))
        result.cancelled = True
        result.database_path = None
        result.completed_at = datetime.now()
        if result.started_at:
            result.processing_time_seconds = (
                result.completed_at - result.started_at
            ).total_seconds()
        logger.info("Processing cancelled after %s compounds written", result.successful_compounds)
        if progress_callback:
            progress_callback(processed_rows, total_rows, "Processing cancelled.")
    
    def process_spreadsheet(
        self,
        file_path: str,
        config: SpreadsheetConfig,
        db_path: Optional[Path] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> DataProcessingResult:
        """
        Process spreadsheet file into database.
        
        Args:
            file_path: Path to spreadsheet file (CSV or Excel)
            config: SpreadsheetConfig with parsing settings
            db_path: Path to database file (None for auto-generated)
            chunk_size: Number of rows to process per chunk
            progress_callback: Optional callback(processed, total, status) for progress updates
            cancel_event: When set, processing stops cooperatively and removes partial database files
            
        Returns:
            DataProcessingResult with processing statistics
        """
        file_path_obj = Path(file_path)
        result = DataProcessingResult()
        result.started_at = datetime.now()
        
        logger.info(f"Starting data processing: {file_path}")
        
        try:
            def emit_progress(processed: int, total: int, status: str) -> bool:
                """Return True if processing should abort (cancel requested)."""
                if cancel_event is not None and cancel_event.is_set():
                    return True
                if progress_callback:
                    progress_callback(processed, total, status)
                return False
            
            # Estimate total rows for progress reporting
            total_rows = self._estimate_row_count(file_path_obj)
            result.total_rows = total_rows
            
            if emit_progress(0, total_rows, "Initializing database..."):
                result.cancelled = True
                result.completed_at = datetime.now()
                if result.started_at:
                    result.processing_time_seconds = (
                        result.completed_at - result.started_at
                    ).total_seconds()
                self.result = result
                return result
            
            # Always write an on-disk database so downstream features (chromatogram
            # visualizer, search) can open the same file after processing. In-memory
            # mode left no path and no file, which broke those flows for small datasets.
            use_memory = False
            
            # Create database under managed output folder unless caller supplies a path
            if db_path is None:
                db_path = database_library.allocate_new_database_path(file_path_obj.stem)
            
            data_store = DataStore(db_path=db_path, use_memory=use_memory)
            result.database_path = str(db_path)
            
            # Create metadata columns in database (but defer index creation for performance)
            if config.selected_metadata_columns:
                data_store.create_metadata_columns(config.selected_metadata_columns, create_indexes=False)
                logger.info(f"Created {len(config.selected_metadata_columns)} metadata columns (indexes deferred)")
            
            # Create parser
            parser = DataParser(config.delimiters)
            
            # Process file in chunks
            processed_rows = 0
            compounds_batch: List[Any] = []
            batch_size = 1000  # Insert compounds in batches of 1000
            
            if cancel_event is not None and cancel_event.is_set():
                self._finalize_cancellation(
                    data_store,
                    db_path,
                    use_memory,
                    result,
                    compounds_batch,
                    progress_callback,
                    processed_rows,
                    total_rows,
                )
                self.result = result
                return result
            
            # Determine file type and create chunk iterator
            if file_path_obj.suffix.lower() == '.csv':
                # Process CSV in chunks (memory efficient for large files)
                chunk_iterator = pd.read_csv(file_path, chunksize=chunk_size, encoding='utf-8')
            else:
                # For Excel files, read entire file and split into chunks
                # Excel files are typically smaller, so this is acceptable
                # For very large Excel files, this could be optimized later
                df = pd.read_excel(
                    file_path,
                    engine='openpyxl' if file_path_obj.suffix == '.xlsx' else 'xlrd'
                )
                if cancel_event is not None and cancel_event.is_set():
                    self._finalize_cancellation(
                        data_store,
                        db_path,
                        use_memory,
                        result,
                        compounds_batch,
                        progress_callback,
                        processed_rows,
                        total_rows,
                    )
                    self.result = result
                    return result
                # Split into chunks for consistent processing
                chunk_iterator = [
                    df[i:i+chunk_size]
                    for i in range(0, len(df), chunk_size)
                ]
            
            chunk_num = 0
            cancelled = False
            for chunk_df in chunk_iterator:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                chunk_num += 1
                
                status = f"Processing chunk {chunk_num} ({len(chunk_df)} rows)..."
                if emit_progress(processed_rows, total_rows, status):
                    cancelled = True
                    break
                
                # Process each row in chunk
                for idx, row in chunk_df.iterrows():
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        break
                    row_num = processed_rows + 1
                    
                    try:
                        compound = self._process_row(
                            row,
                            config,
                            parser,
                            row_num,
                            result
                        )
                        
                        if compound:
                            compounds_batch.append(compound)
                            result.successful_compounds += 1
                            
                            # Insert batch when it reaches batch_size (larger batches = faster)
                            if len(compounds_batch) >= batch_size:
                                data_store.add_compounds_batch(
                                    compounds_batch,
                                    config.selected_metadata_columns,
                                    batch_size=batch_size
                                )
                                compounds_batch.clear()
                        else:
                            result.skipped_rows += 1
                            
                    except Exception as e:
                        # Log error but continue processing
                        error_msg = f"Error processing row {row_num}: {str(e)}"
                        logger.warning(error_msg)
                        result.add_error(
                            row_number=row_num,
                            error_type="processing_error",
                            error_message=error_msg
                        )
                        result.skipped_rows += 1
                    
                    processed_rows += 1
                
                if cancelled:
                    break
                
                if emit_progress(processed_rows, total_rows, f"Processed {processed_rows:,} rows..."):
                    cancelled = True
                    break
            
            if cancelled:
                self._finalize_cancellation(
                    data_store,
                    db_path,
                    use_memory,
                    result,
                    compounds_batch,
                    progress_callback,
                    processed_rows,
                    total_rows,
                )
                self.result = result
                return result
            
            # Insert remaining compounds
            if compounds_batch:
                data_store.add_compounds_batch(
                    compounds_batch,
                    config.selected_metadata_columns,
                    batch_size=batch_size
                )
            
            # Finalize database
            if emit_progress(processed_rows, total_rows, "Building indexes..."):
                self._finalize_cancellation(
                    data_store,
                    db_path,
                    use_memory,
                    result,
                    compounds_batch,
                    progress_callback,
                    processed_rows,
                    total_rows,
                )
                self.result = result
                return result
            
            # Create all indexes now (much faster than during inserts)
            if config.selected_metadata_columns:
                data_store.create_all_indexes(config.selected_metadata_columns)
            
            # Optimize database statistics
            data_store.conn.execute("ANALYZE")
            data_store.conn.commit()
            
            logger.info("Database indexes created and optimized")
            
            # Close database
            data_store.close()
            
            result.completed_at = datetime.now()
            result.processing_time_seconds = (
                (result.completed_at - result.started_at).total_seconds()
            )
            
            logger.info(f"Processing complete: {result.successful_compounds} compounds, "
                       f"{result.skipped_rows} skipped, {result.processing_time_seconds:.2f}s")
            
            if progress_callback:
                progress_callback(processed_rows, total_rows, "Complete!")
            
        except Exception as e:
            error_msg = f"Fatal error during processing: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result.add_error(
                error_type="fatal_error",
                error_message=error_msg
            )
        
        self.result = result
        return result

    def parse_dataframe_row_to_compound(
        self,
        row: pd.Series,
        config: SpreadsheetConfig,
        row_number: int,
    ) -> tuple[Optional[Compound], DataProcessingResult]:
        """
        Parse a single in-memory spreadsheet row into a Compound (on-demand path).

        Args:
            row: One row of the loaded dataframe (column keys = spreadsheet headers).
            config: Active spreadsheet configuration.
            row_number: 1-based row label for error reporting.

        Returns:
            (compound, result) where result holds any recorded errors.
        """
        result = DataProcessingResult()
        parser = DataParser(config.delimiters)
        compound = self._process_row(row, config, parser, row_number, result)
        return compound, result
    
    def _process_row(
        self,
        row: pd.Series,
        config: SpreadsheetConfig,
        parser: DataParser,
        row_number: int,
        result: DataProcessingResult
    ) -> Optional[Compound]:
        """
        Process a single spreadsheet row into a Compound.
        
        Args:
            row: Pandas Series representing one row
            config: SpreadsheetConfig with parsing settings
            parser: DataParser instance
            row_number: Row number for error reporting
            result: DataProcessingResult to record errors
            
        Returns:
            Compound instance if successful, None if skipped
        """
        try:
            # Extract compound ID
            compound_id = row.get(config.compound_id_column)
            if pd.isna(compound_id) or not str(compound_id).strip():
                result.add_error(
                    row_number=row_number,
                    error_type="missing_compound_id",
                    error_message="Compound ID is empty or missing"
                )
                return None
            
            compound_id = str(compound_id).strip()
            
            # Extract chromatographic data string
            chrom_data_str = row.get(config.chromatographic_data_column)
            if pd.isna(chrom_data_str) or not str(chrom_data_str).strip():
                result.add_error(
                    row_number=row_number,
                    compound_id=compound_id,
                    error_type="missing_chromatographic_data",
                    error_message="Chromatographic data is empty or missing"
                )
                return None
            
            chrom_data_str = str(chrom_data_str).strip()
            
            # Parse chromatographic data
            try:
                # Calculate items per point
                items_per_point = 1 + len(config.count_column_indices)  # time + counts
                
                # Parse structured data
                parsed_points = parser.parse_structured(chrom_data_str, items_per_point)
            except ValueError as e:
                result.add_error(
                    row_number=row_number,
                    compound_id=compound_id,
                    error_type="parsing_error",
                    error_message=f"Failed to parse chromatographic data: {str(e)}"
                )
                return None
            
            # Convert to ChromatographicDataPoint objects
            data_points = []
            for point in parsed_points:
                try:
                    # Extract time
                    time_str = point[config.time_column_index]
                    time_value = DataParser.try_parse_numeric(time_str)
                    
                    if time_value is None:
                        result.add_error(
                            row_number=row_number,
                            compound_id=compound_id,
                            error_type="invalid_time",
                            error_message=f"Non-numeric time value: {time_str}"
                        )
                        continue
                    
                    if time_value < 0:
                        result.add_error(
                            row_number=row_number,
                            compound_id=compound_id,
                            error_type="invalid_time",
                            error_message=f"Negative time value: {time_value}"
                        )
                        continue
                    
                    # Extract counts
                    counts = {}
                    for count_idx, count_name in zip(config.count_column_indices, config.count_names):
                        count_str = point[count_idx]
                        count_value = DataParser.try_parse_numeric(count_str)
                        
                        if count_value is None:
                            result.add_error(
                                row_number=row_number,
                                compound_id=compound_id,
                                error_type="invalid_count",
                                error_message=f"Non-numeric count value for {count_name}: {count_str}"
                            )
                            continue
                        
                        if count_value < 0:
                            # Allow negative but log warning
                            logger.warning(f"Negative count value for {compound_id}, {count_name}: {count_value}")
                            count_value = 0  # Set to 0 instead of skipping
                        
                        counts[count_name] = count_value
                    
                    if not counts:
                        # No valid counts, skip this data point
                        continue
                    
                    # Create data point
                    data_point = ChromatographicDataPoint(time=time_value, counts=counts)
                    data_points.append(data_point)
                    
                except Exception as e:
                    result.add_error(
                        row_number=row_number,
                        compound_id=compound_id,
                        error_type="data_point_error",
                        error_message=f"Error creating data point: {str(e)}"
                    )
                    continue
            
            if not data_points:
                result.add_error(
                    row_number=row_number,
                    compound_id=compound_id,
                    error_type="no_valid_data_points",
                    error_message="No valid data points extracted"
                )
                return None
            
            # Sort data points by time (required for Compound validation)
            data_points.sort(key=lambda dp: dp.time)
            
            # Extract metadata (only selected columns)
            metadata = {}
            for col_name in config.selected_metadata_columns:
                if col_name in row.index:
                    value = row[col_name]
                    if not pd.isna(value):
                        metadata[col_name] = value
            
            # Create compound
            compound = Compound(
                compound_id=compound_id,
                metadata=metadata,
                data_points=data_points
            )
            
            return compound
            
        except Exception as e:
            result.add_error(
                row_number=row_number,
                error_type="processing_error",
                error_message=f"Unexpected error: {str(e)}"
            )
            return None
    
    def _estimate_row_count(self, file_path: Path) -> int:
        """
        Estimate total number of rows in file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Estimated row count
        """
        try:
            if file_path.suffix.lower() == '.csv':
                # For CSV, count lines (approximate but fast)
                # Read in chunks to avoid loading entire file
                count = 0
                with open(file_path, 'r', encoding='utf-8') as f:
                    # Skip header
                    f.readline()
                    # Count remaining lines in chunks
                    chunk_size = 100000
                    while True:
                        chunk = f.readlines(chunk_size)
                        if not chunk:
                            break
                        count += len(chunk)
                return count
            else:
                # For Excel, we need to read the file to get exact count
                # This is slower but necessary for accurate progress
                try:
                    df = pd.read_excel(
                        file_path,
                        engine='openpyxl' if file_path.suffix == '.xlsx' else 'xlrd'
                    )
                    return len(df)
                except Exception:
                    # If we can't read it, return placeholder
                    return 100000
        except Exception as e:
            logger.warning(f"Could not estimate row count: {e}")
            return 100000  # Default estimate
