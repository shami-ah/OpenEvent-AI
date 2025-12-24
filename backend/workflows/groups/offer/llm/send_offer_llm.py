"""
DEPRECATED: Use backend.workflows.steps.step4_offer.llm.send_offer_llm instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step4_offer.llm.send_offer_llm import (
    ComposeOffer,
    EmailOffer,
    ChatFollowUp,
    send_offer_email,
)

__all__ = ["ComposeOffer", "EmailOffer", "ChatFollowUp", "send_offer_email"]
