# src/models/chromatographic_data_point.py
"""
Data model for a single chromatographic data point (time, count values).
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ChromatographicDataPoint:
    """
    Represents a single chromatographic data point with time and count values.
    
    Attributes:
        time: Time value for this data point (must be numeric)
        counts: Dictionary mapping count names to their values
                e.g., {"Count1": 1234.5, "Count2": 567.8}
    """
    
    time: float
    counts: Dict[str, float]
    
    def __post_init__(self) -> None:
        """
        Validate data point after initialization.
        
        Raises:
            ValueError: If time is negative or counts contain invalid values.
        """
        if self.time < 0:
            raise ValueError(f"Time must be non-negative, got {self.time}")
        
        if not self.counts:
            raise ValueError("At least one count value must be provided")
        
        for name, value in self.counts.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Count name must be a non-empty string, got {name}")
            if not isinstance(value, (int, float)):
                raise ValueError(f"Count value must be numeric, got {value} for {name}")
            if value < 0:
                raise ValueError(f"Count value must be non-negative, got {value} for {name}")
    
    def get_count(self, count_name: str) -> Optional[float]:
        """
        Get a specific count value by name.
        
        Args:
            count_name: Name of the count to retrieve
            
        Returns:
            Count value if found, None otherwise
        """
        return self.counts.get(count_name)
    
    def get_count_names(self) -> List[str]:
        """
        Get list of all count names for this data point.
        
        Returns:
            List of count names
        """
        return list(self.counts.keys())
    
    def to_dict(self) -> Dict:
        """
        Convert data point to dictionary representation.
        
        Returns:
            Dictionary with time and counts
        """
        return {
            "time": self.time,
            "counts": self.counts.copy()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ChromatographicDataPoint":
        """
        Create ChromatographicDataPoint from dictionary.
        
        Args:
            data: Dictionary with 'time' and 'counts' keys
            
        Returns:
            ChromatographicDataPoint instance
            
        Raises:
            ValueError: If dictionary is missing required keys or invalid
        """
        if "time" not in data:
            raise ValueError("Dictionary must contain 'time' key")
        if "counts" not in data:
            raise ValueError("Dictionary must contain 'counts' key")
        
        return cls(
            time=float(data["time"]),
            counts={str(k): float(v) for k, v in data["counts"].items()}
        )
