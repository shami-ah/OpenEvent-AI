"""
DEPRECATED: Use backend.workflows.steps.step3_room_availability.llm.analysis instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step3_room_availability.llm.analysis import summarize_room_statuses

__all__ = ["summarize_room_statuses"]
