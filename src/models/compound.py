# src/models/compound.py
"""
Data model for a compound with ID, metadata, and chromatographic data.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound_identity import split_compound_storage_id


@dataclass
class Compound:
    """
    Represents a compound with ID, metadata columns, and chromatographic data.
    
    Attributes:
        compound_id: Unique storage key (primary, or primary + variant separator + variant)
        metadata: Dictionary of additional metadata columns from spreadsheet
        data_points: List of chromatographic data points (time, count pairs)
        primary_compound_id: Shared identity for coplotting variants (defaults from compound_id)
        variant_label: Optional variant label (e.g. linear / cyclized) when configured
    """
    
    compound_id: str
    metadata: Dict[str, any] = field(default_factory=dict)
    data_points: List[ChromatographicDataPoint] = field(default_factory=list)
    primary_compound_id: Optional[str] = None
    variant_label: Optional[str] = None
    
    def __post_init__(self) -> None:
        """
        Validate compound after initialization.
        
        Raises:
            ValueError: If compound_id is empty or data_points are invalid
        """
        if not self.compound_id or not str(self.compound_id).strip():
            raise ValueError("Compound ID must be a non-empty string")

        if self.primary_compound_id is None or not str(self.primary_compound_id).strip():
            prim, var = split_compound_storage_id(self.compound_id)
            object.__setattr__(self, "primary_compound_id", prim)
            if self.variant_label is None:
                object.__setattr__(self, "variant_label", var)
        
        # Validate data points are sorted by time
        if self.data_points:
            times = [dp.time for dp in self.data_points]
            if times != sorted(times):
                raise ValueError("Data points must be sorted by time")
    
    def get_count_names(self) -> List[str]:
        """
        Get all unique count names across all data points.
        
        Returns:
            List of unique count names
        """
        count_names = set()
        for dp in self.data_points:
            count_names.update(dp.get_count_names())
        return sorted(list(count_names))
    
    def get_time_series(self, count_name: Optional[str] = None) -> tuple[List[float], List[float]]:
        """
        Get time series data for a specific count or all counts.
        
        Args:
            count_name: Name of count to retrieve. If None, returns first available count.
            
        Returns:
            Tuple of (times, counts) lists
            
        Raises:
            ValueError: If count_name not found or no data points available
        """
        if not self.data_points:
            raise ValueError("No data points available for this compound")
        
        times = [dp.time for dp in self.data_points]
        
        if count_name is None:
            # Get first available count name
            count_name = self.get_count_names()[0]
        
        if count_name not in self.get_count_names():
            raise ValueError(f"Count name '{count_name}' not found in compound data")
        
        counts = [dp.get_count(count_name) for dp in self.data_points]
        
        # Filter out None values (shouldn't happen, but safety check)
        valid_indices = [i for i, c in enumerate(counts) if c is not None]
        times = [times[i] for i in valid_indices]
        counts = [counts[i] for i in valid_indices]
        
        return times, counts
    
    def get_metadata_value(self, column_name: str) -> Optional[any]:
        """
        Get metadata value for a specific column.
        
        Args:
            column_name: Name of the metadata column
            
        Returns:
            Metadata value if found, None otherwise
        """
        return self.metadata.get(column_name)
    
    def to_dict(self) -> Dict:
        """
        Convert compound to dictionary representation.
        
        Returns:
            Dictionary with compound_id, metadata, and data_points
        """
        return {
            "compound_id": self.compound_id,
            "metadata": self.metadata.copy(),
            "data_points": [dp.to_dict() for dp in self.data_points],
            "primary_compound_id": self.primary_compound_id,
            "variant_label": self.variant_label,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Compound":
        """
        Create Compound from dictionary.
        
        Args:
            data: Dictionary with 'compound_id', 'metadata', and 'data_points'
            
        Returns:
            Compound instance
            
        Raises:
            ValueError: If dictionary is missing required keys
        """
        if "compound_id" not in data:
            raise ValueError("Dictionary must contain 'compound_id' key")
        
        from src.models.chromatographic_data_point import ChromatographicDataPoint
        
        return cls(
            compound_id=str(data["compound_id"]),
            metadata=data.get("metadata", {}),
            data_points=[
                ChromatographicDataPoint.from_dict(dp) 
                for dp in data.get("data_points", [])
            ],
            primary_compound_id=data.get("primary_compound_id"),
            variant_label=data.get("variant_label"),
        )
