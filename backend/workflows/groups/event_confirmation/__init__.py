"""
DEPRECATED: Use backend.workflows.steps.step7_confirmation instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "backend.workflows.groups.event_confirmation is deprecated. "
    "Use backend.workflows.steps.step7_confirmation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.workflows.steps.step7_confirmation import (
    WorkflowNode,
    OpenEventAction,
    LLMNode,
    TriggerNode,
    ClientReply,
)

__all__ = [
    "WorkflowNode",
    "OpenEventAction",
    "LLMNode",
    "TriggerNode",
    "ClientReply",
]
