"""
DEPRECATED: Use backend.workflows.steps.step2_date_confirmation instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "backend.workflows.groups.date_confirmation is deprecated. "
    "Use backend.workflows.steps.step2_date_confirmation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.workflows.steps.step2_date_confirmation import (
    process,
    compose_date_confirmation_reply,
    is_valid_ddmmyyyy,
)

__all__ = ["process", "compose_date_confirmation_reply", "is_valid_ddmmyyyy"]
