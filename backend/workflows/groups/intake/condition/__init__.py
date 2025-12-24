"""
DEPRECATED: Use backend.workflows.steps.step1_intake.condition instead.
"""
# Re-export from new location (checks.py still exists for direct imports)
from backend.workflows.steps.step1_intake.condition.checks import (
    has_event_date,
    is_event_request,
    room_status_on_date,
    suggest_dates,
    blackout_days,
)

__all__ = [
    "has_event_date",
    "is_event_request",
    "room_status_on_date",
    "suggest_dates",
    "blackout_days",
]
