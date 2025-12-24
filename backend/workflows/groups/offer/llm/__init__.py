"""DEPRECATED: Use backend.workflows.steps.step4_offer.llm instead."""
from backend.workflows.steps.step4_offer.llm.send_offer_llm import ChatFollowUp, ComposeOffer, EmailOffer
from backend.workflows.steps.step4_offer.llm.client_reply_analysis import AnalyzeClientReply

__all__ = [
    "ChatFollowUp",
    "ComposeOffer",
    "EmailOffer",
    "AnalyzeClientReply",
]
