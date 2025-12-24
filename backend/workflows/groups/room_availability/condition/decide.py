"""
DEPRECATED: Use backend.workflows.steps.step3_room_availability.condition.decide instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step3_room_availability.condition.decide import room_status_on_date

__all__ = ["room_status_on_date"]
