"""
DEPRECATED: Use backend.workflows.steps.step5_negotiation instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "backend.workflows.groups.negotiation_close is deprecated. "
    "Use backend.workflows.steps.step5_negotiation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.workflows.steps.step5_negotiation import (
    process,
    _handle_accept,
    _offer_summary_lines,
    _apply_hil_negotiation_decision,
    _classify_message,
    _ask_classification_clarification,
    update_event_metadata,
)

__all__ = [
    "process",
    "_handle_accept",
    "_offer_summary_lines",
    "_apply_hil_negotiation_decision",
    "_classify_message",
    "_ask_classification_clarification",
    "update_event_metadata",
]
