"""
DEPRECATED: Import from step2_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step2_handler import (
    process,
    ConfirmationWindow,
    _finalize_confirmation,
    _resolve_confirmation_window,
)

__all__ = [
    "process",
    "ConfirmationWindow",
    "_finalize_confirmation",
    "_resolve_confirmation_window",
]
