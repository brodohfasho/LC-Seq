# src/models/spreadsheet_config.py
"""
Data model for spreadsheet configuration (delimiters, column mappings, parsing rules).
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class SpreadsheetConfig:
    """
    Configuration for parsing and processing spreadsheet data.
    
    Attributes:
        compound_id_column: Name of the column containing compound IDs
        chromatographic_data_column: Name of the column containing chromatographic data
        delimiters: Ordered list of delimiters to use for parsing (order matters)
        time_column_index: Index of the time column in parsed data (0-based)
        count_column_indices: List of indices for count columns in parsed data
        count_names: List of names for each count column (must match count_column_indices)
        selected_metadata_columns: List of metadata column names to include in database
                                  (excludes compound_id_column and chromatographic_data_column)
        compound_variant_column: Optional column that distinguishes versions of the same
                                 primary compound (e.g. linear vs cyclized). When set, each
                                 row must have a non-empty value; storage IDs are unique
                                 per (primary, variant).
        null_token: Token marking unfilled coupling positions in BB columns (pedigree).
        library_cycle_count: Number of coupling cycles (2, 3, or 4) in this DEL library.
        bb_position_columns: Up to four spreadsheet columns for BB1..BB4 (C→N coupling order).
        bb_index_map: Optional user CSV mapping of building-block name → display index.
        bb_index_csv_path: Source file path when index map was loaded from CSV (informational).
        analysis_time_unit: Default time unit for peak/pedigree analysis UI (seconds/minutes).
    """
    
    compound_id_column: str
    chromatographic_data_column: str
    compound_variant_column: Optional[str] = None
    delimiters: List[str] = field(default_factory=list)
    time_column_index: Optional[int] = None
    count_column_indices: List[int] = field(default_factory=list)
    count_names: List[str] = field(default_factory=list)
    selected_metadata_columns: List[str] = field(default_factory=list)
    null_token: str = "AgxNull"
    library_cycle_count: int = 3
    bb_position_columns: List[str] = field(default_factory=lambda: ["", "", "", ""])
    bb_index_map: Dict[str, int] = field(default_factory=dict)
    bb_index_csv_path: Optional[str] = None
    analysis_time_unit: str = "seconds"
    
    def __post_init__(self) -> None:
        """
        Validate configuration after initialization.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if not self.compound_id_column or not str(self.compound_id_column).strip():
            raise ValueError("Compound ID column must be a non-empty string")
        
        if not self.chromatographic_data_column or not str(self.chromatographic_data_column).strip():
            raise ValueError("Chromatographic data column must be a non-empty string")
        
        if self.time_column_index is not None and self.time_column_index < 0:
            raise ValueError("Time column index must be non-negative")
        
        if len(self.count_column_indices) != len(self.count_names):
            raise ValueError(
                f"Number of count column indices ({len(self.count_column_indices)}) "
                f"must match number of count names ({len(self.count_names)})"
            )
        
        # Validate count names are unique and non-empty
        if self.count_names:
            if any(not name or not str(name).strip() for name in self.count_names):
                raise ValueError("All count names must be non-empty strings")
            if len(self.count_names) != len(set(self.count_names)):
                raise ValueError("Count names must be unique")
        
        # Validate column indices are unique and non-negative
        if self.count_column_indices:
            if any(idx < 0 for idx in self.count_column_indices):
                raise ValueError("All count column indices must be non-negative")
            if len(self.count_column_indices) != len(set(self.count_column_indices)):
                raise ValueError("Count column indices must be unique")

        if self.compound_variant_column is not None:
            v = str(self.compound_variant_column).strip()
            if not v:
                self.compound_variant_column = None
            else:
                self.compound_variant_column = v
                if v == str(self.compound_id_column).strip():
                    raise ValueError(
                        "Compound variant column must differ from compound ID column"
                    )
                if v == str(self.chromatographic_data_column).strip():
                    raise ValueError(
                        "Compound variant column must differ from chromatographic data column"
                    )

        self._validate_pedigree_fields()
    
    def _validate_pedigree_fields(self) -> None:
        """Validate DEL / pedigree configuration when partially set."""
        if self.library_cycle_count not in (2, 3, 4):
            raise ValueError("library_cycle_count must be 2, 3, or 4")
        if len(self.bb_position_columns) != 4:
            raise ValueError("bb_position_columns must have exactly 4 entries (BB1..BB4 slots)")
        if self.analysis_time_unit not in ("seconds", "minutes"):
            raise ValueError("analysis_time_unit must be 'seconds' or 'minutes'")
        if not self.null_token or not str(self.null_token).strip():
            raise ValueError("null_token must be a non-empty string")
        self._validate_bb_index_map()

    def _validate_bb_index_map(self) -> None:
        """Light validation of optional user BB index overrides."""
        if not self.bb_index_map:
            return
        seen_indices: Dict[int, str] = {}
        for name, index in self.bb_index_map.items():
            if not str(name).strip():
                raise ValueError("bb_index_map keys must be non-empty building-block names")
            if not isinstance(index, int):
                raise ValueError(f"bb_index_map index for {name!r} must be an integer")
            if index in seen_indices and seen_indices[index] != name:
                raise ValueError(
                    f"bb_index_map duplicate index {index} for {name!r} and "
                    f"{seen_indices[index]!r}"
                )
            seen_indices[index] = str(name)

    def active_bb_position_columns(self) -> List[str]:
        """BB column names for the configured cycle count (C→N: BB1 = C-term)."""
        cols = [c.strip() for c in self.bb_position_columns if c and str(c).strip()]
        n = self.library_cycle_count
        active = self.bb_position_columns[:n]
        return [str(c).strip() for c in active if c and str(c).strip()]

    def pedigree_configured(self) -> bool:
        """True when enough BB columns are mapped for pedigree analysis."""
        return len(self.active_bb_position_columns()) == self.library_cycle_count

    def uses_bb_index_csv(self) -> bool:
        """True when split-tree labels use a user-supplied index map."""
        return bool(self.bb_index_map)

    def bb_index_override(self) -> Optional[Dict[str, int]]:
        """Return the override map when configured, else ``None`` for auto indexing."""
        return dict(self.bb_index_map) if self.bb_index_map else None

    def parsed_fields_per_point(self) -> int:
        """
        Number of parsed fields per chromatogram data point.

        Matches the delimiter test in Configure Spreadsheet (``len(delimiters)``).
        Raw chromatogram strings retain every field even when only a subset of count
        columns is selected for export or plotting.
        """
        if self.delimiters:
            return len(self.delimiters)
        indices: List[int] = []
        if self.time_column_index is not None:
            indices.append(self.time_column_index)
        if self.count_column_indices:
            indices.extend(self.count_column_indices)
        if indices:
            return max(indices) + 1
        return 1 + len(self.count_column_indices)
    
    def is_complete(self) -> bool:
        """
        Check if configuration is complete and ready to use.
        
        Returns:
            True if configuration has all required fields set
        """
        return (
            self.compound_id_column and
            self.chromatographic_data_column and
            len(self.delimiters) > 0 and
            self.time_column_index is not None and
            len(self.count_column_indices) > 0 and
            len(self.count_names) > 0 and
            len(self.count_column_indices) == len(self.count_names)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary representation.
        
        Returns:
            Dictionary with all configuration fields
        """
        return {
            "compound_id_column": self.compound_id_column,
            "chromatographic_data_column": self.chromatographic_data_column,
            "compound_variant_column": self.compound_variant_column,
            "delimiters": self.delimiters.copy(),
            "time_column_index": self.time_column_index,
            "count_column_indices": self.count_column_indices.copy(),
            "count_names": self.count_names.copy(),
            "selected_metadata_columns": self.selected_metadata_columns.copy(),
            "null_token": self.null_token,
            "library_cycle_count": self.library_cycle_count,
            "bb_position_columns": self.bb_position_columns.copy(),
            "bb_index_map": dict(self.bb_index_map),
            "bb_index_csv_path": self.bb_index_csv_path,
            "analysis_time_unit": self.analysis_time_unit,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpreadsheetConfig":
        """
        Create SpreadsheetConfig from dictionary.
        
        Args:
            data: Dictionary with configuration fields
            
        Returns:
            SpreadsheetConfig instance
            
        Raises:
            ValueError: If dictionary is missing required keys
        """
        if "compound_id_column" not in data:
            raise ValueError("Dictionary must contain 'compound_id_column' key")
        if "chromatographic_data_column" not in data:
            raise ValueError("Dictionary must contain 'chromatographic_data_column' key")
        
        raw_variant = data.get("compound_variant_column")
        variant_col: Optional[str] = None
        if raw_variant is not None and str(raw_variant).strip():
            variant_col = str(raw_variant).strip()

        bb_cols = data.get("bb_position_columns", ["", "", "", ""])
        if len(bb_cols) < 4:
            bb_cols = list(bb_cols) + [""] * (4 - len(bb_cols))
        bb_cols = [str(c) if c else "" for c in bb_cols[:4]]

        raw_index_map = data.get("bb_index_map") or {}
        bb_index_map: Dict[str, int] = {}
        if isinstance(raw_index_map, dict):
            for name, index in raw_index_map.items():
                try:
                    bb_index_map[str(name).strip()] = int(index)
                except (TypeError, ValueError):
                    continue
        raw_csv_path = data.get("bb_index_csv_path")
        bb_index_csv_path = str(raw_csv_path).strip() if raw_csv_path else None

        return cls(
            compound_id_column=str(data["compound_id_column"]),
            chromatographic_data_column=str(data["chromatographic_data_column"]),
            compound_variant_column=variant_col,
            delimiters=data.get("delimiters", []),
            time_column_index=data.get("time_column_index"),
            count_column_indices=data.get("count_column_indices", []),
            count_names=data.get("count_names", []),
            selected_metadata_columns=data.get("selected_metadata_columns", []),
            null_token=str(data.get("null_token", "AgxNull")),
            library_cycle_count=int(data.get("library_cycle_count", 3)),
            bb_position_columns=bb_cols,
            bb_index_map=bb_index_map,
            bb_index_csv_path=bb_index_csv_path,
            analysis_time_unit=str(data.get("analysis_time_unit", "seconds")),
        )
