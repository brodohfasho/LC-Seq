# tests/test_data_processor.py
"""
Unit tests for chromatogram row parsing in DataProcessor.
"""

import pandas as pd

from src.core.data_processor import DataProcessor
from src.models.spreadsheet_config import SpreadsheetConfig


class TestDataProcessorSingleCount:
    """Parsing when only one count channel is selected from multi-field data."""

    def test_parse_row_with_one_of_two_counts(self):
        """Raw chromatogram still has every field; only configured counts are kept."""
        config = SpreadsheetConfig(
            compound_id_column="ID",
            chromatographic_data_column="Chrom",
            delimiters=[",", ";", ":"],
            time_column_index=0,
            count_column_indices=[1],
            count_names=["Raw Count"],
        )
        row = pd.Series({"ID": "C1", "Chrom": "0;10:20,1;11:21"})
        processor = DataProcessor()
        compound, result = processor.parse_dataframe_row_to_compound(row, config, 1)

        assert not result.errors
        assert compound is not None
        assert len(compound.data_points) == 2
        assert compound.data_points[0].counts == {"Raw Count": 10.0}
        assert compound.data_points[1].counts == {"Raw Count": 11.0}

    def test_parse_row_with_second_count_only(self):
        """Selecting the deduplicated field (index 2) still parses full triplets."""
        config = SpreadsheetConfig(
            compound_id_column="ID",
            chromatographic_data_column="Chrom",
            delimiters=[",", ";", ":"],
            time_column_index=0,
            count_column_indices=[2],
            count_names=["Deduplicated"],
        )
        row = pd.Series({"ID": "C1", "Chrom": "0;10:20,1;11:21"})
        processor = DataProcessor()
        compound, result = processor.parse_dataframe_row_to_compound(row, config, 1)

        assert not result.errors
        assert compound is not None
        assert compound.data_points[0].counts == {"Deduplicated": 20.0}
        assert compound.data_points[1].counts == {"Deduplicated": 21.0}
