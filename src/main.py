# src/main.py
"""
Main entry point for LC-Seq application.

This is the primary entry point that launches the LC-Seq
chromatographic data analysis application.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.logging_config import setup_logging, get_logger

# Set up logging
setup_logging()
logger = get_logger(__name__)


def main():
    """
    Main application entry point.
    
    This function will be implemented in Phase 3 when the UI is built.
    """
    logger.info("LC-Seq application starting...")
    logger.info("Application not yet implemented - Phase 1 setup complete")
    print("LC-Seq: Chromatographic Data Analysis Application")
    print("Phase 1 setup complete. UI implementation coming in Phase 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
