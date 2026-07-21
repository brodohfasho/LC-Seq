# src/ui/library_analysis/models.py
"""Shared models for composed Library Analysis controllers."""


class LibraryOperationCancelled(Exception):
    """Signal cooperative cancellation from a Library Analysis worker."""
