# src/models/app_settings.py
"""
Data model for application settings (default configs, last loaded file, preferences).
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

from src.models.spreadsheet_config import SpreadsheetConfig


@dataclass
class AppSettings:
    """
    Application-wide settings and preferences.
    
    Attributes:
        last_loaded_file: Path to the last loaded spreadsheet file
        window_width: Default window width in pixels
        window_height: Default window height in pixels
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        default_spreadsheet_config: Default spreadsheet configuration to use
    """
    
    last_loaded_file: Optional[str] = None
    window_width: int = 1200
    window_height: int = 800
    log_level: str = "INFO"
    log_file: str = "logs/lc_seq.log"
    default_spreadsheet_config: Optional[SpreadsheetConfig] = None
    
    def __post_init__(self) -> None:
        """
        Validate settings after initialization.
        
        Raises:
            ValueError: If settings contain invalid values
        """
        if self.window_width < 400:
            raise ValueError(f"Window width must be at least 400, got {self.window_width}")
        if self.window_height < 300:
            raise ValueError(f"Window height must be at least 300, got {self.window_height}")
        
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(
                f"Log level must be one of {valid_log_levels}, got {self.log_level}"
            )
        
        if self.last_loaded_file:
            # Validate file path exists (if file was provided)
            path = Path(self.last_loaded_file)
            if not path.exists() and path.is_absolute():
                # File doesn't exist, but that's okay - might have been moved
                # Just log a warning, don't raise error
                pass
    
    def set_last_loaded_file(self, file_path: str) -> None:
        """
        Set the last loaded file path.
        
        Args:
            file_path: Path to the spreadsheet file
        """
        if file_path:
            self.last_loaded_file = str(Path(file_path).resolve())
        else:
            self.last_loaded_file = None
    
    def set_default_config(self, config: SpreadsheetConfig) -> None:
        """
        Set the default spreadsheet configuration.
        
        Args:
            config: SpreadsheetConfig instance to use as default
        """
        self.default_spreadsheet_config = config
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert settings to dictionary representation.
        
        Returns:
            Dictionary with all settings fields
        """
        result = {
            "last_loaded_file": self.last_loaded_file,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "log_level": self.log_level,
            "log_file": self.log_file
        }
        
        if self.default_spreadsheet_config:
            result["default_spreadsheet_config"] = self.default_spreadsheet_config.to_dict()
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        """
        Create AppSettings from dictionary.
        
        Args:
            data: Dictionary with settings fields
            
        Returns:
            AppSettings instance
        """
        settings = cls(
            last_loaded_file=data.get("last_loaded_file"),
            window_width=data.get("window_width", 1200),
            window_height=data.get("window_height", 800),
            log_level=data.get("log_level", "INFO"),
            log_file=data.get("log_file", "logs/lc_seq.log")
        )
        
        if "default_spreadsheet_config" in data and data["default_spreadsheet_config"]:
            settings.default_spreadsheet_config = SpreadsheetConfig.from_dict(
                data["default_spreadsheet_config"]
            )
        
        return settings
