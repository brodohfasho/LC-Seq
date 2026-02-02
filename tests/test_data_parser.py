# tests/test_data_parser.py
"""
Unit tests for data parser functionality.
"""

import pytest

from src.utils.data_parser import DataParser


class TestDataParser:
    """Test cases for DataParser class."""
    
    def test_init_with_delimiters(self):
        """Test parser initialization with delimiters."""
        parser = DataParser([",", ";"])
        assert parser.delimiters == [",", ";"]
    
    def test_init_without_delimiters(self):
        """Test parser initialization fails without delimiters."""
        with pytest.raises(ValueError, match="At least one delimiter"):
            DataParser([])
    
    def test_parse_simple_comma_delimited(self):
        """Test parsing simple comma-delimited data."""
        parser = DataParser([","])
        result = parser.parse("Time1,Count1,Time2,Count2")
        assert result == ["Time1", "Count1", "Time2", "Count2"]
    
    def test_parse_multiple_delimiters(self):
        """Test parsing with multiple delimiters in sequence."""
        parser = DataParser([",", ";"])
        result = parser.parse("Time1;Count1,Time2;Count2")
        # First split by comma: ["Time1;Count1", "Time2;Count2"]
        # Then split by semicolon: ["Time1", "Count1", "Time2", "Count2"]
        assert result == ["Time1", "Count1", "Time2", "Count2"]
    
    def test_parse_structured_two_items(self):
        """Test parsing structured data with 2 items per point."""
        parser = DataParser([","])
        result = parser.parse_structured("Time1,Count1,Time2,Count2", items_per_point=2)
        assert result == [["Time1", "Count1"], ["Time2", "Count2"]]
    
    def test_parse_structured_three_items(self):
        """Test parsing structured data with 3 items per point."""
        parser = DataParser([",", ";", ":"])
        result = parser.parse_structured("Time1;Count1:Count2,Time2;Count1:Count2", items_per_point=3)
        assert result == [["Time1", "Count1", "Count2"], ["Time2", "Count1", "Count2"]]
    
    def test_parse_structured_uneven_division(self):
        """Test parsing structured data that doesn't divide evenly."""
        parser = DataParser([","])
        with pytest.raises(ValueError, match="not divisible"):
            parser.parse_structured("Time1,Count1,Time2", items_per_point=2)
    
    def test_parse_empty_string(self):
        """Test parsing empty string raises error."""
        parser = DataParser([","])
        with pytest.raises(ValueError, match="cannot be empty"):
            parser.parse("")
    
    def test_parse_preview_success(self):
        """Test parse preview with valid data."""
        parser = DataParser([","])
        result = parser.parse_preview("Time1,Count1,Time2,Count2")
        assert result["success"] is True
        assert result["item_count"] == 4
        assert len(result["sample"]) == 4
    
    def test_parse_preview_failure(self):
        """Test parse preview handles errors gracefully."""
        parser = DataParser([","])
        # Empty string should fail
        result = parser.parse_preview("")
        assert result["success"] is False
        assert result["error"] is not None
    
    def test_try_parse_numeric_valid(self):
        """Test parsing valid numeric strings."""
        assert DataParser.try_parse_numeric("123.45") == 123.45
        assert DataParser.try_parse_numeric("0") == 0.0
        assert DataParser.try_parse_numeric("-10.5") == -10.5
    
    def test_try_parse_numeric_invalid(self):
        """Test parsing invalid numeric strings returns None."""
        assert DataParser.try_parse_numeric("abc") is None
        assert DataParser.try_parse_numeric("") is None
        assert DataParser.try_parse_numeric("12.34.56") is None
    
    def test_validate_parsed_data_valid(self):
        """Test validation of valid parsed data."""
        parsed_data = [["10.5", "100", "200"], ["20.5", "150", "250"]]
        is_valid, error = DataParser.validate_parsed_data(
            parsed_data, time_index=0, count_indices=[1, 2]
        )
        assert is_valid is True
        assert error is None
    
    def test_validate_parsed_data_invalid_time_index(self):
        """Test validation fails with invalid time index."""
        parsed_data = [["10.5", "100"], ["20.5", "150"]]
        is_valid, error = DataParser.validate_parsed_data(
            parsed_data, time_index=5, count_indices=[1]
        )
        assert is_valid is False
        assert "out of range" in error
    
    def test_validate_parsed_data_non_numeric_time(self):
        """Test validation fails with non-numeric time."""
        parsed_data = [["abc", "100"], ["20.5", "150"]]
        is_valid, error = DataParser.validate_parsed_data(
            parsed_data, time_index=0, count_indices=[1]
        )
        assert is_valid is False
        assert "non-numeric time" in error
    
    def test_validate_parsed_data_uneven_lengths(self):
        """Test validation fails when data points have different lengths."""
        parsed_data = [["10.5", "100"], ["20.5", "150", "extra"]]
        is_valid, error = DataParser.validate_parsed_data(
            parsed_data, time_index=0, count_indices=[1]
        )
        assert is_valid is False
        assert "different number of items" in error or "has" in error
