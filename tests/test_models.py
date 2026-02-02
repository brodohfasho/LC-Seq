# tests/test_models.py
"""
Unit tests for data models.
"""

import pytest

from src.models.chromatographic_data_point import ChromatographicDataPoint
from src.models.compound import Compound
from src.models.spreadsheet_config import SpreadsheetConfig
from src.models.app_settings import AppSettings


class TestChromatographicDataPoint:
    """Test cases for ChromatographicDataPoint model."""
    
    def test_create_valid_point(self):
        """Test creating a valid data point."""
        point = ChromatographicDataPoint(time=10.5, counts={"Count1": 100.0, "Count2": 200.0})
        assert point.time == 10.5
        assert point.counts == {"Count1": 100.0, "Count2": 200.0}
    
    def test_create_point_negative_time(self):
        """Test creating point with negative time raises error."""
        with pytest.raises(ValueError, match="Time must be non-negative"):
            ChromatographicDataPoint(time=-1.0, counts={"Count1": 100.0})
    
    def test_create_point_empty_counts(self):
        """Test creating point with empty counts raises error."""
        with pytest.raises(ValueError, match="At least one count value"):
            ChromatographicDataPoint(time=10.0, counts={})
    
    def test_get_count(self):
        """Test getting count by name."""
        point = ChromatographicDataPoint(time=10.0, counts={"Count1": 100.0})
        assert point.get_count("Count1") == 100.0
        assert point.get_count("Count2") is None
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        point = ChromatographicDataPoint(time=10.0, counts={"Count1": 100.0})
        data = point.to_dict()
        assert data["time"] == 10.0
        assert data["counts"] == {"Count1": 100.0}
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {"time": 10.0, "counts": {"Count1": 100.0}}
        point = ChromatographicDataPoint.from_dict(data)
        assert point.time == 10.0
        assert point.counts == {"Count1": 100.0}


class TestCompound:
    """Test cases for Compound model."""
    
    def test_create_valid_compound(self):
        """Test creating a valid compound."""
        point1 = ChromatographicDataPoint(time=10.0, counts={"Count1": 100.0})
        point2 = ChromatographicDataPoint(time=20.0, counts={"Count1": 150.0})
        compound = Compound(
            compound_id="Compound1",
            metadata={"Column1": "Value1"},
            data_points=[point1, point2]
        )
        assert compound.compound_id == "Compound1"
        assert len(compound.data_points) == 2
    
    def test_create_compound_empty_id(self):
        """Test creating compound with empty ID raises error."""
        with pytest.raises(ValueError, match="Compound ID must be a non-empty"):
            Compound(compound_id="")
    
    def test_get_count_names(self):
        """Test getting count names from compound."""
        point1 = ChromatographicDataPoint(time=10.0, counts={"Count1": 100.0, "Count2": 200.0})
        point2 = ChromatographicDataPoint(time=20.0, counts={"Count1": 150.0, "Count2": 250.0})
        compound = Compound(compound_id="C1", data_points=[point1, point2])
        count_names = compound.get_count_names()
        assert "Count1" in count_names
        assert "Count2" in count_names
    
    def test_get_time_series(self):
        """Test getting time series data."""
        point1 = ChromatographicDataPoint(time=10.0, counts={"Count1": 100.0})
        point2 = ChromatographicDataPoint(time=20.0, counts={"Count1": 150.0})
        compound = Compound(compound_id="C1", data_points=[point1, point2])
        times, counts = compound.get_time_series("Count1")
        assert times == [10.0, 20.0]
        assert counts == [100.0, 150.0]


class TestSpreadsheetConfig:
    """Test cases for SpreadsheetConfig model."""
    
    def test_create_valid_config(self):
        """Test creating a valid configuration."""
        config = SpreadsheetConfig(
            compound_id_column="ID",
            chromatographic_data_column="Data",
            delimiters=[",", ";"],
            time_column_index=0,
            count_column_indices=[1, 2],
            count_names=["Count1", "Count2"]
        )
        assert config.compound_id_column == "ID"
        assert config.is_complete() is True
    
    def test_config_incomplete(self):
        """Test incomplete configuration."""
        config = SpreadsheetConfig(
            compound_id_column="ID",
            chromatographic_data_column="Data"
        )
        assert config.is_complete() is False
    
    def test_config_mismatched_counts(self):
        """Test configuration with mismatched count indices and names."""
        with pytest.raises(ValueError, match="must match"):
            SpreadsheetConfig(
                compound_id_column="ID",
                chromatographic_data_column="Data",
                count_column_indices=[1],
                count_names=["Count1", "Count2"]  # Mismatch
            )


class TestAppSettings:
    """Test cases for AppSettings model."""
    
    def test_create_default_settings(self):
        """Test creating default settings."""
        settings = AppSettings()
        assert settings.window_width == 1200
        assert settings.window_height == 800
        assert settings.log_level == "INFO"
    
    def test_settings_invalid_window_size(self):
        """Test settings with invalid window size."""
        with pytest.raises(ValueError, match="Window width"):
            AppSettings(window_width=100)
    
    def test_settings_invalid_log_level(self):
        """Test settings with invalid log level."""
        with pytest.raises(ValueError, match="Log level"):
            AppSettings(log_level="INVALID")
