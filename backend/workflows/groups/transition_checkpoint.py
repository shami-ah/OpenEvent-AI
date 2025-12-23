"""
DEPRECATED: Use backend.workflows.steps.step6_transition instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "backend.workflows.groups.transition_checkpoint is deprecated. "
    "Use backend.workflows.steps.step6_transition instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.workflows.steps.step6_transition import process

__all__ = ["process"]
