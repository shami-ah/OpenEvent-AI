"""
DEPRECATED: Import from step5_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step5_handler import process, _handle_accept, _offer_summary_lines

__all__ = ["process", "_handle_accept", "_offer_summary_lines"]
