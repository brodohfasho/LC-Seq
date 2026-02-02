# src/utils/data_parser.py
"""
Data parsing utilities for chromatographic data strings.
"""

import re
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class DataParser:
    """
    Parser for chromatographic data strings with configurable delimiters.
    
    Handles parsing of delimited data like:
    - "Time;Count1:Count2,Time;Count1:Count2"
    - "Time;Count,Time;Count"
    """
    
    def __init__(self, delimiters: List[str]):
        """
        Initialize parser with delimiter sequence.
        
        Args:
            delimiters: Ordered list of delimiters to use for parsing (order matters)
                       e.g., [",", ";", ":"] means split by comma first, then semicolon, then colon
        """
        if not delimiters:
            raise ValueError("At least one delimiter must be provided")
        
        self.delimiters = delimiters
        logger.debug(f"Initialized parser with delimiters: {delimiters}")
    
    def parse(self, data_string: str) -> List[List[str]]:
        """
        Parse a chromatographic data string into a structured format.
        
        Args:
            data_string: String containing delimited chromatographic data
            
        Returns:
            List of lists, where each inner list represents one data point
            e.g., [["Time1", "Count1", "Count2"], ["Time2", "Count1", "Count2"]]
            
        Raises:
            ValueError: If data_string is empty or parsing fails
        """
        if not data_string or not data_string.strip():
            raise ValueError("Data string cannot be empty")
        
        # Start with the full string
        current_data = [data_string.strip()]
        
        # Apply delimiters in sequence
        for delimiter in self.delimiters:
            new_data = []
            for item in current_data:
                # Split by current delimiter
                split_items = item.split(delimiter)
                # Add all split items to new_data
                new_data.extend([s.strip() for s in split_items if s.strip()])
            
            current_data = new_data
        
        # Group items into data points
        # The number of items per data point depends on the structure
        # We need to infer this from the data or it should be specified
        # For now, we'll return a flat list and let the caller group it
        
        logger.debug(f"Parsed {len(current_data)} items from data string")
        return current_data
    
    def parse_structured(self, data_string: str, items_per_point: int) -> List[List[str]]:
        """
        Parse data string into structured data points with known items per point.
        
        Args:
            data_string: String containing delimited chromatographic data
            items_per_point: Number of items (columns) per data point
                            e.g., 2 for "Time,Count" or 3 for "Time,Count1,Count2"
        
        Returns:
            List of data points, where each point is a list of items
            e.g., [["Time1", "Count1"], ["Time2", "Count2"]]
            
        Raises:
            ValueError: If data_string is empty, items_per_point is invalid, 
                       or data doesn't divide evenly
        """
        if items_per_point < 1:
            raise ValueError(f"Items per point must be at least 1, got {items_per_point}")
        
        # Parse into flat list
        flat_items = self.parse(data_string)
        
        # Check if data divides evenly
        if len(flat_items) % items_per_point != 0:
            raise ValueError(
                f"Data has {len(flat_items)} items, which is not divisible by "
                f"{items_per_point} items per point"
            )
        
        # Group into data points
        data_points = []
        for i in range(0, len(flat_items), items_per_point):
            data_point = flat_items[i:i + items_per_point]
            data_points.append(data_point)
        
        logger.debug(f"Parsed into {len(data_points)} data points with {items_per_point} items each")
        return data_points
    
    def parse_preview(self, data_string: str, max_items: int = 100) -> Dict:
        """
        Parse a sample of data for preview/testing purposes.
        
        Args:
            data_string: String containing delimited chromatographic data
            max_items: Maximum number of items to parse (for performance)
        
        Returns:
            Dictionary with:
            - "items": List of parsed items
            - "item_count": Total number of items
            - "sample": First few items as sample
            - "success": Whether parsing succeeded
            - "error": Error message if parsing failed
        """
        try:
            items = self.parse(data_string)
            
            # Limit items for preview
            preview_items = items[:max_items] if len(items) > max_items else items
            
            return {
                "items": preview_items,
                "item_count": len(items),
                "sample": preview_items[:10],  # First 10 for display
                "success": True,
                "error": None
            }
        
        except Exception as e:
            logger.error(f"Error in parse_preview: {e}")
            return {
                "items": [],
                "item_count": 0,
                "sample": [],
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def try_parse_numeric(value: str) -> Optional[float]:
        """
        Try to parse a string value as a numeric value.
        
        Args:
            value: String value to parse
            
        Returns:
            Float value if parseable, None otherwise
        """
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def validate_parsed_data(
        parsed_data: List[List[str]], 
        time_index: int, 
        count_indices: List[int]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that parsed data can be used with given column indices.
        
        Args:
            parsed_data: List of data points (each is a list of strings)
            time_index: Index of time column
            count_indices: List of indices for count columns
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not parsed_data:
            return False, "No data points found in parsed data"
        
        # Check that all data points have the same number of items
        first_length = len(parsed_data[0])
        for i, point in enumerate(parsed_data):
            if len(point) != first_length:
                return False, f"Data point {i} has {len(point)} items, expected {first_length}"
        
        # Check that indices are valid
        max_index = first_length - 1
        if time_index < 0 or time_index > max_index:
            return False, f"Time index {time_index} is out of range (0-{max_index})"
        
        for count_idx in count_indices:
            if count_idx < 0 or count_idx > max_index:
                return False, f"Count index {count_idx} is out of range (0-{max_index})"
        
        # Check that time column contains numeric values
        for i, point in enumerate(parsed_data):
            time_value = DataParser.try_parse_numeric(point[time_index])
            if time_value is None:
                return False, f"Data point {i} has non-numeric time value: {point[time_index]}"
        
        # Check that count columns contain numeric values
        for count_idx in count_indices:
            for i, point in enumerate(parsed_data):
                count_value = DataParser.try_parse_numeric(point[count_idx])
                if count_value is None:
                    return False, (
                        f"Data point {i} has non-numeric count value at index {count_idx}: "
                        f"{point[count_idx]}"
                    )
        
        return True, None
