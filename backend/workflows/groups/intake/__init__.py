"""
DEPRECATED: Use backend.workflows.steps.step1_intake instead.

This module re-exports from the new canonical location for backwards compatibility.
All new code should import from backend.workflows.steps.step1_intake.

Migration:
    OLD: from backend.workflows.groups.intake import process
    NEW: from backend.workflows.steps.step1_intake import process

    OLD: from backend.workflows.groups.intake.condition.checks import suggest_dates
    NEW: from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
"""

import warnings as _warnings

# Emit deprecation warning on import (only once per session)
_warnings.warn(
    "backend.workflows.groups.intake is deprecated. "
    "Use backend.workflows.steps.step1_intake instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything from the new location
from backend.workflows.steps.step1_intake import (
    process,
    classify_intent,
    extract_user_information,
    sanitize_user_info,
    has_event_date,
    room_status_on_date,
    suggest_dates,
    blackout_days,
    enqueue_task,
    update_task_status,
)

__all__ = [
    "process",
    "classify_intent",
    "extract_user_information",
    "sanitize_user_info",
    "has_event_date",
    "room_status_on_date",
    "suggest_dates",
    "blackout_days",
    "enqueue_task",
    "update_task_status",
]
