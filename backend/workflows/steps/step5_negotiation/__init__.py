"""
Step 5: Negotiation - Handle offer acceptance, decline, and counter-offers.

This step handles:
- Classifying client responses to offers (accept, decline, counter)
- Processing acceptance flow with billing requirements
- Handling counter-offers and changes
- Managing decline scenarios

CANONICAL LOCATION: backend/workflows/steps/step5_negotiation/
MIGRATED FROM: backend/workflows/groups/negotiation_close.py

Submodules:
    trigger/    - Main entry point (process function)
"""

from .trigger.step5_handler import (
    process,
    _handle_accept,
    _offer_summary_lines,
    _apply_hil_negotiation_decision,
    _classify_message,
    _ask_classification_clarification,
)
from backend.workflows.io.database import update_event_metadata

__all__ = [
    "process",
    "_handle_accept",
    "_offer_summary_lines",
    "_apply_hil_negotiation_decision",
    "_classify_message",
    "_ask_classification_clarification",
    "update_event_metadata",
]
