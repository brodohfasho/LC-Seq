# tests/test_spreadsheet_loader.py
"""
Unit tests for spreadsheet loader functionality.
"""

import pytest
import pandas as pd
import tempfile
import os
from pathlib import Path

from src.core.spreadsheet_loader import SpreadsheetLoader


class TestSpreadsheetLoader:
    """Test cases for SpreadsheetLoader class."""
    
    def test_is_supported_file(self):
        """Test file extension validation."""
        loader = SpreadsheetLoader()
        
        assert loader.is_supported_file("test.xlsx") is True
        assert loader.is_supported_file("test.XLSX") is True  # Case insensitive
        assert loader.is_supported_file("test.xls") is True
        assert loader.is_supported_file("test.csv") is True
        assert loader.is_supported_file("test.txt") is False
        assert loader.is_supported_file("test") is False
    
    def test_load_csv_file(self):
        """Test loading a CSV file."""
        loader = SpreadsheetLoader()
        
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Column1,Column2,Column3\n")
            f.write("Value1,Value2,Value3\n")
            f.write("Value4,Value5,Value6\n")
            temp_path = f.name
        
        try:
            success, error, df = loader.load_file(temp_path)
            assert success is True
            assert error is None
            assert df is not None
            assert df.shape[0] == 2
            assert df.shape[1] == 3
            assert list(df.columns) == ["Column1", "Column2", "Column3"]
        finally:
            os.unlink(temp_path)
    
    def test_load_nonexistent_file(self):
        """Test loading a non-existent file."""
        loader = SpreadsheetLoader()
        success, error, df = loader.load_file("nonexistent.xlsx")
        assert success is False
        assert error is not None
        assert "not found" in error.lower()
        assert df is None
    
    def test_load_unsupported_file(self):
        """Test loading an unsupported file type."""
        loader = SpreadsheetLoader()
        
        # Create temporary file with unsupported extension
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Some text")
            temp_path = f.name
        
        try:
            success, error, df = loader.load_file(temp_path)
            assert success is False
            assert error is not None
            assert "unsupported" in error.lower()
            assert df is None
        finally:
            os.unlink(temp_path)
    
    def test_load_empty_csv(self):
        """Test loading an empty CSV file."""
        loader = SpreadsheetLoader()
        
        # Create empty CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            # Write only header
            f.write("Column1,Column2\n")
            temp_path = f.name
        
        try:
            success, error, df = loader.load_file(temp_path)
            # Empty file might be handled differently by pandas
            # This test verifies we handle it gracefully
            assert df is None or df.empty
        finally:
            os.unlink(temp_path)
    
    def test_get_column_names(self):
        """Test getting column names from loaded data."""
        loader = SpreadsheetLoader()
        
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Column1,Column2,Column3\n")
            f.write("Value1,Value2,Value3\n")
            temp_path = f.name
        
        try:
            success, _, _ = loader.load_file(temp_path)
            assert success is True
            
            columns = loader.get_column_names()
            assert len(columns) == 3
            assert "Column1" in columns
            assert "Column2" in columns
            assert "Column3" in columns
        finally:
            os.unlink(temp_path)
    
    def test_get_column_names_no_data(self):
        """Test getting column names when no data is loaded."""
        loader = SpreadsheetLoader()
        columns = loader.get_column_names()
        assert columns == []
    
    def test_validate_required_columns(self):
        """Test validating required columns."""
        loader = SpreadsheetLoader()
        
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("CompoundID,Data,Other\n")
            f.write("C1,Data1,Other1\n")
            temp_path = f.name
        
        try:
            success, _, _ = loader.load_file(temp_path)
            assert success is True
            
            # Test with existing columns
            is_valid, error = loader.validate_required_columns(["CompoundID", "Data"])
            assert is_valid is True
            assert error is None
            
            # Test with missing column
            is_valid, error = loader.validate_required_columns(["CompoundID", "MissingColumn"])
            assert is_valid is False
            assert error is not None
            assert "MissingColumn" in error
        finally:
            os.unlink(temp_path)
    
    def test_validate_required_columns_no_data(self):
        """Test validating columns when no data is loaded."""
        loader = SpreadsheetLoader()
        is_valid, error = loader.validate_required_columns(["Column1"])
        assert is_valid is False
        assert "No spreadsheet loaded" in error
    
    def test_clear_data(self):
        """Test clearing loaded data."""
        loader = SpreadsheetLoader()
        
        # Create and load temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("Column1,Column2\n")
            f.write("Value1,Value2\n")
            temp_path = f.name
        
        try:
            success, _, _ = loader.load_file(temp_path)
            assert success is True
            assert loader.get_data() is not None
            
            loader.clear_data()
            assert loader.get_data() is None
            assert loader.get_column_names() == []
        finally:
            os.unlink(temp_path)
