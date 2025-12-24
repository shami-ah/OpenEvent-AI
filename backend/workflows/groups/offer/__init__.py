"""
DEPRECATED: Use backend.workflows.steps.step4_offer instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

import warnings as _warnings

_warnings.warn(
    "backend.workflows.groups.offer is deprecated. "
    "Use backend.workflows.steps.step4_offer instead.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.workflows.steps.step4_offer import (
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
