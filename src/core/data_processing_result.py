# src/core/data_processing_result.py
"""
Data processing result model for tracking processing statistics and errors.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProcessingError:
    """
    Represents a single processing error.
    
    Attributes:
        row_number: Row number where error occurred (1-based, or None if unknown)
        compound_id: Compound ID if available
        error_type: Type of error (e.g., "parsing_error", "validation_error")
        error_message: Human-readable error message
    """
    
    row_number: Optional[int]
    compound_id: Optional[str]
    error_type: str
    error_message: str


@dataclass
class DataProcessingResult:
    """
    Result of data processing operation.
    
    Attributes:
        total_rows: Total number of rows processed
        successful_compounds: Number of compounds successfully processed
        skipped_rows: Number of rows skipped due to errors
        errors: List of processing errors
        processing_time_seconds: Time taken to process (in seconds)
        database_path: Path to created database file (if applicable)
        started_at: Timestamp when processing started
        completed_at: Timestamp when processing completed
        cancelled: True if the user stopped processing before completion
    """
    
    total_rows: int = 0
    successful_compounds: int = 0
    skipped_rows: int = 0
    errors: List[ProcessingError] = field(default_factory=list)
    processing_time_seconds: float = 0.0
    database_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled: bool = False
    
    def add_error(
        self,
        row_number: Optional[int] = None,
        compound_id: Optional[str] = None,
        error_type: str = "unknown_error",
        error_message: str = ""
    ) -> None:
        """
        Add an error to the result.
        
        Args:
            row_number: Row number where error occurred
            compound_id: Compound ID if available
            error_type: Type of error
            error_message: Error message
        """
        self.errors.append(ProcessingError(
            row_number=row_number,
            compound_id=compound_id,
            error_type=error_type,
            error_message=error_message
        ))
        self.skipped_rows += 1
    
    def get_summary(self) -> str:
        """
        Get a human-readable summary of processing results.
        
        Returns:
            Summary string
        """
        if self.cancelled:
            lines = [
                "Processing was cancelled before completion.",
                f"  Compounds written before stop: {self.successful_compounds:,}",
                f"  Skipped rows: {self.skipped_rows:,}",
            ]
        else:
            lines = [
                f"Processing Complete:",
                f"  Total rows: {self.total_rows:,}",
                f"  Successful compounds: {self.successful_compounds:,}",
                f"  Skipped rows: {self.skipped_rows:,}",
            ]
        
        if self.processing_time_seconds > 0:
            lines.append(f"  Processing time: {self.processing_time_seconds:.2f} seconds")
        
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
            # Show first few errors
            for i, error in enumerate(self.errors[:5], 1):
                lines.append(f"    {i}. Row {error.row_number or '?'}: {error.error_message}")
            if len(self.errors) > 5:
                lines.append(f"    ... and {len(self.errors) - 5} more errors")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        """
        Convert result to dictionary representation.
        
        Returns:
            Dictionary with all result fields
        """
        return {
            "total_rows": self.total_rows,
            "successful_compounds": self.successful_compounds,
            "skipped_rows": self.skipped_rows,
            "cancelled": self.cancelled,
            "errors": [
                {
                    "row_number": e.row_number,
                    "compound_id": e.compound_id,
                    "error_type": e.error_type,
                    "error_message": e.error_message
                }
                for e in self.errors
            ],
            "processing_time_seconds": self.processing_time_seconds,
            "database_path": self.database_path,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }
