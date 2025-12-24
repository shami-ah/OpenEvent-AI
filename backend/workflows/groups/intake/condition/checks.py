"""
DEPRECATED: Use backend.workflows.steps.step1_intake.condition.checks instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

# Re-export everything from the new location
from backend.workflows.steps.step1_intake.condition.checks import (
    is_event_request,
    has_event_date,
    suggest_dates,
    blackout_days,
    room_status_on_date,
)

__all__ = [
    "is_event_request",
    "has_event_date",
    "suggest_dates",
    "blackout_days",
    "room_status_on_date",
]
