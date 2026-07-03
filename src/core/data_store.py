# src/core/data_store.py
"""
Data storage layer for compounds and chromatographic data.
"""

import sqlite3
import logging
import json
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Any, Sequence, Tuple, Set
from contextlib import contextmanager

from src.models.compound import Compound
from src.models.compound_identity import split_compound_storage_id
from src.models.chromatographic_data_point import ChromatographicDataPoint

logger = logging.getLogger(__name__)

LCSEQ_META_DB_KIND = "db_kind"
DB_KIND_FULL = "full"
DB_KIND_INDEX = "index"


class DataStore:
    """
    Manages storage and retrieval of compounds and chromatographic data.
    
    Uses SQLite database for efficient storage and fast queries.
    Supports both in-memory (small datasets) and file-based (large datasets) storage.
    """
    
    # Threshold for choosing storage mode
    MEMORY_THRESHOLD = 100000  # 100K rows
    
    def __init__(self, db_path: Optional[Path] = None, use_memory: bool = False):
        """
        Initialize data store.
        
        Args:
            db_path: Path to SQLite database file. If None and not use_memory, creates temp file.
            use_memory: If True, use in-memory database. If False and db_path is None, creates file.
        """
        if use_memory:
            self.db_path = ":memory:"
            self.is_memory = True
        else:
            if db_path is None:
                # Create temporary database file
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / "lc_seq"
                temp_dir.mkdir(parents=True, exist_ok=True)
                db_path = temp_dir / "compounds.db"
            
            self.db_path = Path(db_path)
            self.is_memory = False
        
        self.conn: Optional[sqlite3.Connection] = None
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize database connection and create schema."""
        try:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row  # Enable column access by name
            
            # Optimize SQLite for bulk inserts
            self.conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging for better concurrency
            self.conn.execute("PRAGMA synchronous = NORMAL")  # Balance between safety and speed
            self.conn.execute("PRAGMA cache_size = -10000")  # 10MB cache
            self.conn.execute("PRAGMA temp_store = MEMORY")  # Store temp tables in memory
            self.conn.execute("PRAGMA foreign_keys = OFF")  # Disable FK checks during bulk insert (re-enable later)
            
            self._create_schema()
            self._migrate_compound_identity_columns()
            self._migrate_lcseq_meta_and_raw_chromatogram()
            logger.info(f"Initialized database at {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}", exc_info=True)
            raise
    
    def _create_schema(self) -> None:
        """Create database schema."""
        cursor = self.conn.cursor()
        
        # Compounds table - stores metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compounds (
                compound_id TEXT PRIMARY KEY,
                metadata_json TEXT,
                data_point_count INTEGER DEFAULT 0,
                primary_compound_id TEXT,
                compound_variant TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Data points table - stores chromatographic data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compound_id TEXT NOT NULL,
                time REAL NOT NULL,
                count_name TEXT NOT NULL,
                count_value REAL NOT NULL,
                FOREIGN KEY (compound_id) REFERENCES compounds(compound_id) ON DELETE CASCADE
            )
        """)
        
        # Indexes for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_data_points_compound 
            ON data_points(compound_id, time)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_data_points_time 
            ON data_points(compound_id, time)
        """)
        
        self.conn.commit()
        logger.debug("Database schema created")

    def _migrate_lcseq_meta_and_raw_chromatogram(self) -> None:
        """Add application metadata table and optional raw chromatogram text column."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS lcseq_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cursor.execute("PRAGMA table_info(compounds)")
        cols = {row[1] for row in cursor.fetchall()}
        if "raw_chromatographic_data" not in cols:
            cursor.execute(
                "ALTER TABLE compounds ADD COLUMN raw_chromatographic_data TEXT"
            )
            logger.info("Migrated compounds table: added raw_chromatographic_data")
        self.conn.commit()

    def set_database_kind(self, kind: str) -> None:
        """
        Persist whether this file is a full parsed export or an index (metadata + raw text).

        Args:
            kind: ``DB_KIND_FULL`` or ``DB_KIND_INDEX``.
        """
        if kind not in (DB_KIND_FULL, DB_KIND_INDEX):
            raise ValueError(f"Invalid database kind: {kind!r}")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO lcseq_meta (key, value)
            VALUES (?, ?)
            """,
            (LCSEQ_META_DB_KIND, kind),
        )
        self.conn.commit()

    def get_database_kind(self) -> str:
        """
        Return ``DB_KIND_INDEX`` or ``DB_KIND_FULL``.

        Legacy databases without ``lcseq_meta`` are treated as full exports.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT value FROM lcseq_meta WHERE key = ?",
                (LCSEQ_META_DB_KIND,),
            )
            row = cursor.fetchone()
            if row and row[0] in (DB_KIND_FULL, DB_KIND_INDEX):
                return str(row[0])
        except sqlite3.OperationalError as exc:
            logger.debug("get_database_kind: %s", exc)
        return DB_KIND_FULL

    def is_index_database(self) -> bool:
        """True if chromatograms are stored as raw text and parsed on demand."""
        return self.get_database_kind() == DB_KIND_INDEX

    @staticmethod
    def peek_database_kind(db_path: Path) -> str:
        """
        Open a database file briefly and return ``DB_KIND_FULL`` or ``DB_KIND_INDEX``.

        Args:
            db_path: Path to the SQLite file.

        Returns:
            Database kind constant (legacy files without metadata default to full).
        """
        p = Path(db_path)
        if not p.is_file():
            return DB_KIND_FULL
        store = DataStore(db_path=p, use_memory=False)
        try:
            return store.get_database_kind()
        finally:
            store.close()

    def get_raw_chromatogram(self, compound_id: str) -> Optional[str]:
        """
        Return stored raw chromatographic cell text for index databases.

        Args:
            compound_id: Storage compound id.

        Returns:
            Stripped string or None if missing / empty.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT raw_chromatographic_data FROM compounds
                WHERE compound_id = ?
                """,
                (compound_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            raw_cell = row["raw_chromatographic_data"]
            if raw_cell is None:
                return None
            s = str(raw_cell).strip()
            return s if s else None
        except Exception as e:
            logger.error("get_raw_chromatogram: %s", e, exc_info=True)
            return None

    def add_index_compounds_batch(
        self,
        rows: List[Dict[str, Any]],
        metadata_columns: List[str],
    ) -> int:
        """
        Insert or replace compound rows for an index database (no data_points rows).

        Each dict must contain: compound_id, primary_compound_id, compound_variant (optional),
        metadata (dict), raw_chromatographic_data (str).
        """
        if not rows:
            return 0
        safe_meta = [self._sanitize_column_name(c) for c in metadata_columns]
        base_cols = [
            "compound_id",
            "metadata_json",
            "data_point_count",
            "primary_compound_id",
            "compound_variant",
            "raw_chromatographic_data",
        ]
        all_columns = base_cols + safe_meta
        placeholders = ", ".join(["?"] * len(all_columns))
        query = f"INSERT OR REPLACE INTO compounds ({', '.join(all_columns)}) VALUES ({placeholders})"

        cursor = self.conn.cursor()
        tuples: List[Tuple[Any, ...]] = []
        for r in rows:
            meta = r.get("metadata") or {}
            meta_json = json.dumps(meta, ensure_ascii=False)
            prim = r.get("primary_compound_id") or r["compound_id"]
            var = r.get("compound_variant")
            raw = r.get("raw_chromatographic_data") or ""
            vals: List[Any] = [
                r["compound_id"],
                meta_json,
                0,
                prim,
                var,
                str(raw),
            ]
            for col in metadata_columns:
                value = meta.get(col)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    vals.append(str(value))
                else:
                    vals.append(None)
            tuples.append(tuple(vals))
        cursor.executemany(query, tuples)
        self.conn.commit()
        return len(rows)

    def _migrate_compound_identity_columns(self) -> None:
        """Add primary/variant columns to legacy databases and backfill primary IDs."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(compounds)")
        cols = {row[1] for row in cursor.fetchall()}
        altered = False
        if "primary_compound_id" not in cols:
            cursor.execute("ALTER TABLE compounds ADD COLUMN primary_compound_id TEXT")
            altered = True
        if "compound_variant" not in cols:
            cursor.execute("ALTER TABLE compounds ADD COLUMN compound_variant TEXT")
            altered = True
        if altered:
            self.conn.commit()
            logger.info("Migrated compounds table: added primary_compound_id / compound_variant")
        try:
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_compounds_primary
                ON compounds(primary_compound_id)
                """
            )
        except sqlite3.OperationalError as exc:
            logger.warning("Could not create idx_compounds_primary: %s", exc)
        if altered:
            cursor.execute("SELECT compound_id FROM compounds")
            for (cid,) in cursor.fetchall():
                if not cid:
                    continue
                prim, var = split_compound_storage_id(str(cid))
                cursor.execute(
                    """
                    UPDATE compounds
                    SET primary_compound_id = ?, compound_variant = ?
                    WHERE compound_id = ?
                    """,
                    (prim, var, cid),
                )
            self.conn.commit()
    
    def create_metadata_columns(self, column_names: List[str], create_indexes: bool = False) -> None:
        """
        Create metadata columns in compounds table for fast searching.
        
        This allows direct SQL queries on metadata columns without JSON parsing.
        
        Args:
            column_names: List of metadata column names to create
            create_indexes: If True, create indexes immediately. If False, defer index creation.
        """
        if not column_names:
            return
        
        cursor = self.conn.cursor()
        
        # Get existing columns
        cursor.execute("PRAGMA table_info(compounds)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # Add new columns (but don't create indexes yet for bulk insert performance)
        for col_name in column_names:
            # Sanitize column name for SQL
            safe_name = self._sanitize_column_name(col_name)
            
            if safe_name not in existing_columns:
                try:
                    # Use TEXT for all metadata columns (flexible)
                    cursor.execute(f"ALTER TABLE compounds ADD COLUMN {safe_name} TEXT")
                    # Only create index if requested (defer for bulk inserts)
                    if create_indexes:
                        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{safe_name} ON compounds({safe_name})")
                        logger.debug(f"Created metadata column and index: {safe_name}")
                    else:
                        logger.debug(f"Created metadata column (index deferred): {safe_name}")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Could not create column {safe_name}: {e}")
        
        self.conn.commit()
    
    def create_all_indexes(self, metadata_columns: List[str]) -> None:
        """
        Create all indexes after bulk data insertion is complete.
        
        This is much faster than creating indexes during inserts.
        
        Args:
            metadata_columns: List of metadata column names to create indexes for
        """
        cursor = self.conn.cursor()
        
        # Create indexes on metadata columns
        for col_name in metadata_columns:
            safe_name = self._sanitize_column_name(col_name)
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{safe_name} ON compounds({safe_name})")
                logger.debug(f"Created index on metadata column: {safe_name}")
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not create index on {safe_name}: {e}")
        
        # Re-enable foreign keys
        self.conn.execute("PRAGMA foreign_keys = ON")
        
        self.conn.commit()
        logger.info("All indexes created and foreign keys re-enabled")
    
    @staticmethod
    def _sanitize_column_name(name: str) -> str:
        """
        Sanitize column name for SQL use.

        Args:
            name: Original column name

        Returns:
            Sanitized column name safe for SQL
        """
        # Replace invalid characters with underscore
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        # Ensure it starts with a letter or underscore
        if safe and not (safe[0].isalpha() or safe[0] == "_"):
            safe = "_" + safe
        # Ensure it's not empty
        if not safe:
            safe = "col_" + str(hash(name))[:8]
        return safe
    
    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
    
    def add_compound(self, compound: Compound, metadata_columns: List[str]) -> bool:
        """
        Add a compound to the database.
        
        Args:
            compound: Compound instance to add
            metadata_columns: List of metadata column names (for column-based storage)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            
            # Prepare metadata JSON
            metadata_json = json.dumps(compound.metadata, ensure_ascii=False)
            
            # Prepare column values for direct column storage
            column_values = {}
            for col in metadata_columns:
                safe_col = self._sanitize_column_name(col)
                value = compound.metadata.get(col)
                # Convert value to string, handling None and NaN
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    column_values[safe_col] = str(value)
                else:
                    column_values[safe_col] = None
            
            # Build INSERT statement
            prim = compound.primary_compound_id or compound.compound_id
            var = compound.variant_label
            columns = [
                "compound_id",
                "metadata_json",
                "data_point_count",
                "primary_compound_id",
                "compound_variant",
                "raw_chromatographic_data",
            ]
            values = [
                compound.compound_id,
                metadata_json,
                len(compound.data_points),
                prim,
                var,
                None,
            ]
            placeholders = ["?", "?", "?", "?", "?", "?"]
            
            # Add metadata columns
            for safe_col, value in column_values.items():
                columns.append(safe_col)
                values.append(value)
                placeholders.append("?")
            
            # Insert compound
            query = f"""
                INSERT OR REPLACE INTO compounds ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
            """
            cursor.execute(query, values)

            cursor.execute(
                "DELETE FROM data_points WHERE compound_id = ?",
                (compound.compound_id,),
            )
            
            # Insert data points
            if compound.data_points:
                data_point_values = []
                for dp in compound.data_points:
                    for count_name, count_value in dp.counts.items():
                        data_point_values.append((
                            compound.compound_id,
                            dp.time,
                            count_name,
                            count_value
                        ))
                
                cursor.executemany("""
                    INSERT INTO data_points (compound_id, time, count_name, count_value)
                    VALUES (?, ?, ?, ?)
                """, data_point_values)
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding compound {compound.compound_id}: {e}", exc_info=True)
            return False
    
    def add_compounds_batch(
        self,
        compounds: List[Compound],
        metadata_columns: List[str],
        batch_size: int = 5000
    ) -> int:
        """
        Add multiple compounds in batches for efficiency using bulk inserts.
        
        Args:
            compounds: List of compounds to add
            metadata_columns: List of metadata column names
            batch_size: Number of compounds per batch (larger = faster but more memory)
            
        Returns:
            Number of successfully added compounds
        """
        if not compounds:
            return 0
        
        cursor = self.conn.cursor()
        added = 0
        
        # Prepare column names for bulk insert
        base_columns = [
            "compound_id",
            "metadata_json",
            "data_point_count",
            "primary_compound_id",
            "compound_variant",
            "raw_chromatographic_data",
        ]
        safe_metadata_cols = [self._sanitize_column_name(col) for col in metadata_columns]
        all_columns = base_columns + safe_metadata_cols
        placeholders = ["?"] * len(all_columns)
        
        # Prepare bulk insert query
        insert_compound_query = f"""
            INSERT OR REPLACE INTO compounds ({', '.join(all_columns)})
            VALUES ({', '.join(placeholders)})
        """
        
        # Prepare data point insert query
        insert_data_point_query = """
            INSERT INTO data_points (compound_id, time, count_name, count_value)
            VALUES (?, ?, ?, ?)
        """
        
        # Process in batches
        for i in range(0, len(compounds), batch_size):
            batch = compounds[i:i + batch_size]
            
            try:
                # Prepare compound data for bulk insert
                compound_values = []
                all_data_point_values = []
                
                for compound in batch:
                    # Prepare metadata JSON
                    metadata_json = json.dumps(compound.metadata, ensure_ascii=False)
                    prim = compound.primary_compound_id or compound.compound_id
                    var = compound.variant_label
                    # Prepare compound row values
                    row_values = [
                        compound.compound_id,
                        metadata_json,
                        len(compound.data_points),
                        prim,
                        var,
                        None,
                    ]
                    
                    # Add metadata column values
                    for col in metadata_columns:
                        value = compound.metadata.get(col)
                        if value is not None and not (isinstance(value, float) and pd.isna(value)):
                            row_values.append(str(value))
                        else:
                            row_values.append(None)
                    
                    compound_values.append(tuple(row_values))

                for compound in batch:
                    cursor.execute(
                        "DELETE FROM data_points WHERE compound_id = ?",
                        (compound.compound_id,),
                    )

                for compound in batch:
                    for dp in compound.data_points:
                        for count_name, count_value in dp.counts.items():
                            all_data_point_values.append((
                                compound.compound_id,
                                dp.time,
                                count_name,
                                count_value
                            ))
                
                # Bulk insert compounds
                cursor.executemany(insert_compound_query, compound_values)
                
                # Bulk insert all data points
                if all_data_point_values:
                    cursor.executemany(insert_data_point_query, all_data_point_values)
                
                added += len(batch)
                
                # Commit after each batch (but batches are larger now)
                self.conn.commit()
                
            except Exception as e:
                logger.error(f"Error in bulk insert batch: {e}", exc_info=True)
                self.conn.rollback()
                # Fall back to individual inserts for this batch
                for compound in batch:
                    if self.add_compound(compound, metadata_columns):
                        added += 1
                self.conn.commit()
        
        logger.debug(f"Bulk inserted {added}/{len(compounds)} compounds")
        return added
    
    @staticmethod
    def _compound_from_row(
        row: sqlite3.Row,
        *,
        data_points: Optional[List[ChromatographicDataPoint]] = None,
    ) -> Compound:
        """Build a ``Compound`` from a ``compounds`` table row."""
        compound_id = str(row["compound_id"])
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        keys = row.keys()
        primary_db = (
            row["primary_compound_id"] if "primary_compound_id" in keys else None
        )
        variant_db = (
            row["compound_variant"] if "compound_variant" in keys else None
        )
        prim = (
            str(primary_db).strip()
            if primary_db is not None and str(primary_db).strip()
            else compound_id
        )
        var: Optional[str] = None
        if variant_db is not None and str(variant_db).strip():
            var = str(variant_db).strip()
        return Compound(
            compound_id=compound_id,
            primary_compound_id=prim,
            variant_label=var,
            metadata=metadata,
            data_points=list(data_points or []),
        )

    def _load_data_points(self, compound_id: str) -> List[ChromatographicDataPoint]:
        """Load parsed chromatogram points for one compound."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT time, count_name, count_value
            FROM data_points
            WHERE compound_id = ?
            ORDER BY time
            """,
            (compound_id,),
        )
        data_points_dict: Dict[float, Dict[str, float]] = {}
        for dp_row in cursor.fetchall():
            time = dp_row["time"]
            count_name = dp_row["count_name"]
            count_value = dp_row["count_value"]
            if time not in data_points_dict:
                data_points_dict[time] = {}
            data_points_dict[time][count_name] = count_value
        return [
            ChromatographicDataPoint(time=time, counts=counts)
            for time, counts in sorted(data_points_dict.items())
        ]

    def get_compound_metadata(self, compound_id: str) -> Optional[Compound]:
        """Return compound identity and metadata without loading chromatogram points."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM compounds WHERE compound_id = ?",
                (compound_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._compound_from_row(row)
        except Exception as e:
            logger.error("Error getting compound metadata %s: %s", compound_id, e, exc_info=True)
            return None

    def load_compound_metadata_map(
        self,
        compound_ids: Sequence[str],
        *,
        chunk_size: int = 500,
    ) -> Dict[str, Compound]:
        """Load metadata-only compounds for many IDs (no ``data_points`` query)."""
        if not compound_ids:
            return {}
        out: Dict[str, Compound] = {}
        cursor = self.conn.cursor()
        ids = list(compound_ids)
        for start in range(0, len(ids), chunk_size):
            chunk = ids[start : start + chunk_size]
            placeholders = ", ".join(["?"] * len(chunk))
            cursor.execute(
                f"SELECT * FROM compounds WHERE compound_id IN ({placeholders})",
                chunk,
            )
            for row in cursor.fetchall():
                compound = self._compound_from_row(row)
                out[str(compound.compound_id)] = compound
        return out

    def get_compound(self, compound_id: str) -> Optional[Compound]:
        """
        Get a compound by ID.
        
        Args:
            compound_id: Compound ID to retrieve
            
        Returns:
            Compound instance if found, None otherwise
        """
        try:
            cursor = self.conn.cursor()
            
            # Get compound metadata
            cursor.execute("SELECT * FROM compounds WHERE compound_id = ?", (compound_id,))
            row = cursor.fetchone()
            
            if not row:
                return None

            data_points = self._load_data_points(compound_id)
            return self._compound_from_row(row, data_points=data_points)
            
        except Exception as e:
            logger.error(f"Error getting compound {compound_id}: {e}", exc_info=True)
            return None

    def get_distinct_primary_compound_ids(self) -> List[str]:
        """
        Return sorted unique primary compound IDs (for grouping variants in the UI).

        Returns:
            List of primary IDs; falls back to ``compound_id`` when primary is unset.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT primary_compound_id FROM compounds
                WHERE primary_compound_id IS NOT NULL AND TRIM(primary_compound_id) != ''
                ORDER BY primary_compound_id
                """
            )
            rows = [r[0] for r in cursor.fetchall() if r[0]]
            if rows:
                return rows
            cursor.execute(
                """
                SELECT DISTINCT compound_id FROM compounds
                ORDER BY compound_id
                """
            )
            return [r[0] for r in cursor.fetchall() if r[0]]
        except Exception as e:
            logger.error("Error listing primary compound IDs: %s", e, exc_info=True)
            return []

    def get_compounds_for_primary(self, primary_compound_id: str) -> List[Compound]:
        """
        Load all stored rows that share the same primary compound ID (e.g. linear + cyclized).

        Args:
            primary_compound_id: Value from ``primary_compound_id`` / compound list.

        Returns:
            Compounds ordered by variant label then storage id.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT compound_id FROM compounds
                WHERE primary_compound_id = ?
                ORDER BY COALESCE(compound_variant, ''), compound_id
                """,
                (primary_compound_id,),
            )
            ids = [r[0] for r in cursor.fetchall()]
            out: List[Compound] = []
            for cid in ids:
                loaded = self.get_compound(cid)
                if loaded is not None:
                    out.append(loaded)
            return out
        except Exception as e:
            logger.error(
                "Error loading compounds for primary %s: %s",
                primary_compound_id,
                e,
                exc_info=True,
            )
            return []

    def list_compounds_physical_columns(self) -> Set[str]:
        """
        Return every column name currently defined on the ``compounds`` table.

        Used to align search / SELECT with databases built under an older or
        narrower metadata configuration.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(compounds)")
            return {str(row[1]) for row in cursor.fetchall()}
        except Exception as e:
            logger.error("Error reading compounds columns: %s", e, exc_info=True)
            return set()

    def filter_metadata_columns_for_search(
        self, logical_metadata_names: Sequence[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Split configured metadata names into those backed by a real table column
        vs names missing from this database file.

        Args:
            logical_metadata_names: Headers from ``SpreadsheetConfig.selected_metadata_columns``.

        Returns:
            ``(present_in_table, missing_from_table)`` preserving input order for present.
        """
        physical = self.list_compounds_physical_columns()
        present: List[str] = []
        missing: List[str] = []
        seen_safe_present: Set[str] = set()
        seen_safe_missing: Set[str] = set()
        for name in logical_metadata_names:
            safe = self._sanitize_column_name(str(name))
            if safe in physical:
                if safe not in seen_safe_present:
                    present.append(str(name))
                    seen_safe_present.add(safe)
            else:
                if safe not in seen_safe_missing:
                    missing.append(str(name))
                    seen_safe_missing.add(safe)
        return present, missing

    def count_compounds_where(self, where_sql: str, params: Sequence[Any]) -> int:
        """
        Count compound rows matching a parameterized WHERE fragment (no ``WHERE`` keyword).

        Args:
            where_sql: SQL boolean expression referencing ``compounds`` columns.
            params: Bound parameters for the fragment.

        Returns:
            Match count, or 0 on error.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                f"SELECT COUNT(*) AS c FROM compounds WHERE ({where_sql})",
                tuple(params),
            )
            row = cursor.fetchone()
            return int(row["c"]) if row else 0
        except Exception as e:
            logger.error("Error counting compounds: %s", e, exc_info=True)
            return 0

    def search_compounds_page(
        self,
        display_columns: Sequence[str],
        where_sql: str,
        where_params: Sequence[Any],
        limit: int,
        offset: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Paginated compound search for the visual query builder (Phase 11).

        Always returns ``compound_id``, ``primary_compound_id``, ``compound_variant``,
        plus each requested metadata column (original header names as dict keys).

        Args:
            display_columns: Metadata column headers from configuration (whitelist).
            where_sql: Parameterized boolean SQL (no ``WHERE`` keyword).
            where_params: Parameters for ``where_sql``.
            limit: Maximum rows (page size).
            offset: Row offset for paging.

        Returns:
            Tuple of (page rows as dicts, total matching row count).
        """
        total = self.count_compounds_where(where_sql, where_params)
        if total == 0 or limit <= 0:
            return [], total

        safe_meta = [self._sanitize_column_name(c) for c in display_columns]
        base_cols = ["compound_id", "primary_compound_id", "compound_variant"]
        select_sql_parts: List[str] = list(base_cols)
        for idx, safe in enumerate(safe_meta):
            select_sql_parts.append(f"{safe} AS meta_{idx}")

        query = (
            f"SELECT {', '.join(select_sql_parts)} FROM compounds "
            f"WHERE ({where_sql}) ORDER BY compound_id LIMIT ? OFFSET ?"
        )
        params = tuple(where_params) + (int(limit), int(offset))

        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            rows_out: List[Dict[str, Any]] = []
            for row in cursor.fetchall():
                d: Dict[str, Any] = {
                    "compound_id": row["compound_id"],
                    "primary_compound_id": row["primary_compound_id"],
                    "compound_variant": row["compound_variant"],
                }
                for idx, orig in enumerate(display_columns):
                    key = f"meta_{idx}"
                    d[orig] = row[key] if key in row.keys() else None
                rows_out.append(d)
            return rows_out, total
        except Exception as e:
            logger.error("Error in paginated search: %s", e, exc_info=True)
            return [], total

    def list_compound_ids_where(self, where_sql: str, params: Sequence[Any]) -> List[str]:
        """
        Return all ``compound_id`` values matching the WHERE fragment (no LIMIT).

        Used for "select all results" in the search UI; may be heavy on huge databases.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                f"SELECT compound_id FROM compounds WHERE ({where_sql}) ORDER BY compound_id",
                tuple(params),
            )
            return [str(r["compound_id"]) for r in cursor.fetchall() if r["compound_id"]]
        except Exception as e:
            logger.error("Error listing compound ids: %s", e, exc_info=True)
            return []

    def search_compounds(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[str]:
        """
        Search for compounds by field values.
        
        Args:
            filters: Dictionary of field_name -> value filters
                    Supports: =, !=, >, <, >=, <=, contains
            limit: Maximum number of results to return
            
        Returns:
            List of compound IDs matching the filters
        """
        try:
            cursor = self.conn.cursor()
            
            # Build WHERE clause
            conditions = []
            values = []
            
            for field, filter_value in filters.items():
                safe_field = self._sanitize_column_name(field)
                
                # Handle different filter types
                if isinstance(filter_value, dict):
                    # Advanced filter: {"operator": ">", "value": 100}
                    operator = filter_value.get("operator", "=")
                    value = filter_value.get("value")
                    
                    if operator == "contains":
                        conditions.append(f"{safe_field} LIKE ?")
                        values.append(f"%{value}%")
                    elif operator in ["=", "!=", ">", "<", ">=", "<="]:
                        conditions.append(f"{safe_field} {operator} ?")
                        values.append(value)
                else:
                    # Simple equality
                    conditions.append(f"{safe_field} = ?")
                    values.append(filter_value)
            
            # Build query
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            query = f"SELECT compound_id FROM compounds WHERE {where_clause}"
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, values)
            results = [row["compound_id"] for row in cursor.fetchall()]
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching compounds: {e}", exc_info=True)
            return []
    
    def get_all_compound_ids(self) -> List[str]:
        """
        Get all compound IDs in the database.
        
        Returns:
            List of all compound IDs
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT compound_id FROM compounds")
            return [row["compound_id"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all compound IDs: {e}", exc_info=True)
            return []
    
    def get_compound_count(self) -> int:
        """
        Get total number of compounds in database.
        
        Returns:
            Number of compounds
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM compounds")
            return cursor.fetchone()["count"]
        except Exception as e:
            logger.error(f"Error getting compound count: {e}", exc_info=True)
            return 0
    
    def clear(self) -> None:
        """Clear all data from the database."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM data_points")
            cursor.execute("DELETE FROM compounds")
            self.conn.commit()
            logger.info("Cleared all data from database")
        except Exception as e:
            logger.error(f"Error clearing database: {e}", exc_info=True)
    
    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.debug("Database connection closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
