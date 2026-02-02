# src/core/config_manager.py
"""
Configuration management for loading and saving application settings.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from src.models.app_settings import AppSettings
from src.models.spreadsheet_config import SpreadsheetConfig


logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages loading and saving of application configuration files.
    
    Handles:
    - Application settings (window size, log level, last loaded file, etc.)
    - Default spreadsheet configurations
    - Configuration validation and error handling
    """
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize ConfigManager.
        
        Args:
            config_dir: Directory for configuration files. If None, uses default 'config' directory.
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "config"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.settings_file = self.config_dir / "settings.json"
        self.default_config_file = self.config_dir / "default_config.json"
    
    def load_settings(self) -> AppSettings:
        """
        Load application settings from file.
        
        Returns:
            AppSettings instance. Returns default settings if file doesn't exist.
        """
        if not self.settings_file.exists():
            logger.info(f"Settings file not found at {self.settings_file}, using defaults")
            return AppSettings()
        
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            settings = AppSettings.from_dict(data)
            logger.info(f"Loaded settings from {self.settings_file}")
            return settings
        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in settings file: {e}")
            logger.info("Using default settings")
            return AppSettings()
        
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            logger.info("Using default settings")
            return AppSettings()
    
    def save_settings(self, settings: AppSettings) -> bool:
        """
        Save application settings to file.
        
        Args:
            settings: AppSettings instance to save
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            data = settings.to_dict()
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved settings to {self.settings_file}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False
    
    def load_default_config(self) -> Optional[SpreadsheetConfig]:
        """
        Load default spreadsheet configuration from file.
        
        Returns:
            SpreadsheetConfig instance if found, None otherwise
        """
        if not self.default_config_file.exists():
            logger.info(f"Default config file not found at {self.default_config_file}")
            return None
        
        try:
            with open(self.default_config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            config = SpreadsheetConfig.from_dict(data)
            logger.info(f"Loaded default config from {self.default_config_file}")
            return config
        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in default config file: {e}")
            return None
        
        except Exception as e:
            logger.error(f"Error loading default config: {e}")
            return None
    
    def save_default_config(self, config: SpreadsheetConfig) -> bool:
        """
        Save default spreadsheet configuration to file.
        
        Args:
            config: SpreadsheetConfig instance to save
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            data = config.to_dict()
            
            with open(self.default_config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved default config to {self.default_config_file}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving default config: {e}")
            return False
    
    def validate_config(self, config: SpreadsheetConfig) -> tuple[bool, Optional[str]]:
        """
        Validate a spreadsheet configuration.
        
        Args:
            config: SpreadsheetConfig to validate
            
        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        try:
            # Run post_init validation
            config.__post_init__()
            
            if not config.is_complete():
                return False, "Configuration is incomplete. Please fill in all required fields."
            
            return True, None
        
        except ValueError as e:
            return False, str(e)
        
        except Exception as e:
            return False, f"Unexpected error validating config: {e}"
