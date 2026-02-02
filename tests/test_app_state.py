# tests/test_app_state.py
"""
Unit tests for application state management.
"""

import pytest

from src.core.app_state import AppState


class TestAppState:
    """Test cases for AppState class."""
    
    def test_initial_state(self):
        """Test initial state is correct."""
        state = AppState()
        assert state.spreadsheet_loaded is False
        assert state.spreadsheet_configured is False
        assert state.config_valid is False
        assert state.can_enter_visualizer() is False
    
    def test_can_enter_visualizer(self):
        """Test can_enter_visualizer logic."""
        state = AppState()
        
        # Not ready
        assert state.can_enter_visualizer() is False
        
        # Load spreadsheet
        state.set_spreadsheet_loaded("test.xlsx")
        assert state.can_enter_visualizer() is False
        
        # Configure spreadsheet
        state.set_spreadsheet_configured(True)
        assert state.can_enter_visualizer() is False
        
        # Make config valid
        state.set_config_valid(True)
        assert state.can_enter_visualizer() is True
    
    def test_set_spreadsheet_loaded(self):
        """Test setting spreadsheet loaded state."""
        state = AppState()
        state.set_spreadsheet_loaded("test.xlsx")
        assert state.spreadsheet_loaded is True
        assert state.spreadsheet_path == "test.xlsx"
    
    def test_set_spreadsheet_configured(self):
        """Test setting spreadsheet configured state."""
        state = AppState()
        state.set_spreadsheet_configured(True)
        assert state.spreadsheet_configured is True
    
    def test_set_config_valid(self):
        """Test setting config valid state."""
        state = AppState()
        state.set_config_valid(True)
        assert state.config_valid is True
    
    def test_reset(self):
        """Test resetting state."""
        state = AppState()
        state.set_spreadsheet_loaded("test.xlsx")
        state.set_spreadsheet_configured(True)
        state.set_config_valid(True)
        
        state.reset()
        assert state.spreadsheet_loaded is False
        assert state.spreadsheet_configured is False
        assert state.config_valid is False
    
    def test_get_status_message(self):
        """Test getting status messages."""
        state = AppState()
        
        # No spreadsheet loaded
        message = state.get_status_message()
        assert "No spreadsheet loaded" in message
        
        # Spreadsheet loaded but not configured
        state.set_spreadsheet_loaded("test.xlsx")
        message = state.get_status_message()
        assert "Configure Spreadsheet" in message
        
        # Configured but not valid
        state.set_spreadsheet_configured(True)
        message = state.get_status_message()
        assert "incomplete" in message.lower() or "complete" in message.lower()
        
        # Ready
        state.set_config_valid(True)
        message = state.get_status_message()
        assert "Ready" in message or "visualize" in message.lower()
    
    def test_state_change_callback(self):
        """Test state change callbacks."""
        callback_called = []
        
        def callback():
            callback_called.append(True)
        
        state = AppState()
        state.register_state_change_callback(callback)
        
        state.set_spreadsheet_loaded("test.xlsx")
        assert len(callback_called) == 1
        
        state.set_spreadsheet_configured(True)
        assert len(callback_called) == 2
