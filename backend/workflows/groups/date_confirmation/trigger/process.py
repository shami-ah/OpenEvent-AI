"""
DEPRECATED: Use backend.workflows.steps.step2_date_confirmation.trigger.process instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step2_date_confirmation.trigger.process import (
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
