"""
DEPRECATED: Use backend.workflows.steps.step1_intake.trigger.process instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

# Re-export the main process function from new location
from backend.workflows.steps.step1_intake.trigger.process import process

__all__ = ["process"]
