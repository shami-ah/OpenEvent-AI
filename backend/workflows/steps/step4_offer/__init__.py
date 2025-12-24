"""
Step 4: Offer - Compose and deliver professional offers to clients.

This step handles:
- Composing professional offers based on room and product selection
- Handling client replies to offers
- Managing offer variations and follow-ups

CANONICAL LOCATION: backend/workflows/steps/step4_offer/
MIGRATED FROM: backend/workflows/groups/offer/

Submodules:
    trigger/    - Main entry point (process function)
    condition/  - Gate checks
    llm/        - LLM-based composition (ComposeOffer, EmailOffer, etc.)
    hil/        - Human-in-the-loop approval (CreateProfessionalOffer)
    db_pers/    - Database persistence
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
