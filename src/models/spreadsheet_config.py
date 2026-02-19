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
    """
    
    compound_id_column: str
    chromatographic_data_column: str
    delimiters: List[str] = field(default_factory=list)
    time_column_index: Optional[int] = None
    count_column_indices: List[int] = field(default_factory=list)
    count_names: List[str] = field(default_factory=list)
    selected_metadata_columns: List[str] = field(default_factory=list)
    
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
            "delimiters": self.delimiters.copy(),
            "time_column_index": self.time_column_index,
            "count_column_indices": self.count_column_indices.copy(),
            "count_names": self.count_names.copy(),
            "selected_metadata_columns": self.selected_metadata_columns.copy()
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
        
        return cls(
            compound_id_column=str(data["compound_id_column"]),
            chromatographic_data_column=str(data["chromatographic_data_column"]),
            delimiters=data.get("delimiters", []),
            time_column_index=data.get("time_column_index"),
            count_column_indices=data.get("count_column_indices", []),
            count_names=data.get("count_names", []),
            selected_metadata_columns=data.get("selected_metadata_columns", [])
        )
