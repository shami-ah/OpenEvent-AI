"""
Step 7: Confirmation - Final event confirmation and booking.

This step handles:
- Site visits, deposits, reserves, declines, final confirmations
- Option/deposit branches via policy rules
- All transitions audited through HIL gates

CANONICAL LOCATION: backend/workflows/steps/step7_confirmation/
MIGRATED FROM: backend/workflows/groups/event_confirmation/

Submodules:
    trigger/    - Main entry point (process function)
    condition/  - Gate checks (route_by_response_type)
    db_pers/    - Database persistence (post_offer, update_event_status)
    llm/        - LLM-based analysis
    hil/        - Human-in-the-loop approval
    follow_up/  - Follow-up handling
    ui_adapter/ - UI integration
"""

from __future__ import annotations

from typing import Any, Dict


class WorkflowNode:
    """Minimal base node with a common run signature."""

    role: str = "node"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError("Subclasses must implement run()")


class OpenEventAction(WorkflowNode):
    """Manager/system action node (light-blue)."""

    role = "OpenEvent Action"


class LLMNode(WorkflowNode):
    """Generative reasoning node (green/orange)."""

    role = "LLM"


class TriggerNode(WorkflowNode):
    """Client-trigger node (purple)."""

    role = "Trigger"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Triggers simply pass through the payload for downstream nodes."""

        return payload


class ClientReply(TriggerNode):
    """Shim for the client reply trigger feeding the AnalyzeClientReply node."""

    role = "Client Reply Trigger"


__all__ = [
    "WorkflowNode",
    "OpenEventAction",
    "LLMNode",
    "TriggerNode",
    "ClientReply",
]
