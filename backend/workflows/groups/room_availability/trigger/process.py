"""
DEPRECATED: Use backend.workflows.steps.step3_room_availability.trigger.process instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step3_room_availability.trigger.process import (
    process,
    evaluate_room_statuses,
    handle_select_room_action,
    render_rooms_response,
    _flatten_statuses,
    ROOM_OUTCOME_AVAILABLE,
    ROOM_OUTCOME_OPTION,
)

__all__ = [
    "process",
    "evaluate_room_statuses",
    "handle_select_room_action",
    "render_rooms_response",
    "_flatten_statuses",
    "ROOM_OUTCOME_AVAILABLE",
    "ROOM_OUTCOME_OPTION",
]
