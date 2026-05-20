# src/core/config_manager.py
"""
Configuration management for loading and saving application settings.
"""

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict

from src.core.app_paths import get_application_root
from src.models.app_settings import AppSettings
from src.models.spreadsheet_config import SpreadsheetConfig


logger = logging.getLogger(__name__)

# Configuration file version for migration support
CONFIG_VERSION = "1.0"


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
            config_dir = get_application_root() / "config"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.settings_file = self.config_dir / "settings.json"
        self.default_config_file = self.config_dir / "default_config.json"
        self.configs_dir = self.config_dir / "configs"
        self.configs_dir.mkdir(parents=True, exist_ok=True)
    
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
    
    def save_named_config(self, config: SpreadsheetConfig, name: str) -> bool:
        """
        Save a named spreadsheet configuration to file.
        
        Args:
            config: SpreadsheetConfig instance to save
            name: Name for the configuration (will be sanitized for filename)
            
        Returns:
            True if save was successful, False otherwise
        """
        try:
            # Sanitize name for filename
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            if not safe_name:
                safe_name = "unnamed_config"
            
            config_file = self.configs_dir / f"{safe_name}.json"
            
            # Add version and metadata
            data = {
                "version": CONFIG_VERSION,
                "name": name,
                "config": config.to_dict()
            }
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved named config '{name}' to {config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving named config: {e}")
            return False
    
    def load_named_config(self, name: str) -> Optional[SpreadsheetConfig]:
        """
        Load a named spreadsheet configuration from file.
        
        Args:
            name: Name of the configuration (will be sanitized for filename)
            
        Returns:
            SpreadsheetConfig instance if found, None otherwise
        """
        try:
            # Sanitize name for filename
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            if not safe_name:
                return None
            
            config_file = self.configs_dir / f"{safe_name}.json"
            
            if not config_file.exists():
                logger.warning(f"Named config file not found: {config_file}")
                return None
            
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle versioning/migration
            if "version" in data:
                version = data["version"]
                if version != CONFIG_VERSION:
                    logger.warning(f"Config version mismatch: {version} vs {CONFIG_VERSION}")
                    # Future: Add migration logic here
            
            # Extract config data
            config_data = data.get("config", data)  # Support both old and new format
            
            config = SpreadsheetConfig.from_dict(config_data)
            logger.info(f"Loaded named config '{name}' from {config_file}")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in named config file: {e}")
            return None
        except Exception as e:
            logger.error(f"Error loading named config: {e}")
            return None
    
    def list_named_configs(self) -> List[Dict[str, str]]:
        """
        List all available named configurations.
        
        Returns:
            List of dictionaries with 'name' and 'file' keys
        """
        configs = []
        
        try:
            for config_file in self.configs_dir.glob("*.json"):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Extract name from file or data
                    if "name" in data:
                        name = data["name"]
                    else:
                        # Fallback to filename without extension
                        name = config_file.stem.replace('_', ' ')
                    
                    configs.append({
                        "name": name,
                        "file": str(config_file)
                    })
                except Exception as e:
                    logger.warning(f"Error reading config file {config_file}: {e}")
                    continue
            
            # Sort by name
            configs.sort(key=lambda x: x["name"].lower())
            
        except Exception as e:
            logger.error(f"Error listing named configs: {e}")
        
        return configs
    
    def delete_named_config(self, name: str) -> bool:
        """
        Delete a named configuration file.
        
        Args:
            name: Name of the configuration to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            # Sanitize name for filename
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(' ', '_')
            if not safe_name:
                return False
            
            config_file = self.configs_dir / f"{safe_name}.json"
            
            if not config_file.exists():
                logger.warning(f"Config file not found for deletion: {config_file}")
                return False
            
            config_file.unlink()
            logger.info(f"Deleted named config '{name}' at {config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting named config: {e}")
            return False
    
    def validate_config_against_spreadsheet(
        self, 
        config: SpreadsheetConfig, 
        available_columns: List[str]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that a configuration is compatible with the current spreadsheet.
        
        Args:
            config: SpreadsheetConfig to validate
            available_columns: List of column names in the current spreadsheet
            
        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        # Check compound ID column exists
        if config.compound_id_column not in available_columns:
            return False, (
                f"Compound ID column '{config.compound_id_column}' not found in spreadsheet. "
                f"Available columns: {', '.join(available_columns)}"
            )
        
        # Check chromatographic data column exists
        if config.chromatographic_data_column not in available_columns:
            return False, (
                f"Chromatographic data column '{config.chromatographic_data_column}' not found in spreadsheet. "
                f"Available columns: {', '.join(available_columns)}"
            )
        
        # Check columns are different
        if config.compound_id_column == config.chromatographic_data_column:
            return False, "Compound ID and Chromatographic Data columns must be different"

        if config.compound_variant_column:
            vcol = config.compound_variant_column
            if vcol not in available_columns:
                return False, (
                    f"Compound variant column '{vcol}' not found in spreadsheet. "
                    f"Available columns: {', '.join(available_columns)}"
                )
            if vcol == config.compound_id_column:
                return False, "Variant column must differ from Compound ID column"
            if vcol == config.chromatographic_data_column:
                return False, "Variant column must differ from Chromatographic Data column"
        
        return True, None