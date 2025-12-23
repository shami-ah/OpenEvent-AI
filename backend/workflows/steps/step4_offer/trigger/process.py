"""
DEPRECATED: Import from step4_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step4_handler import process, build_offer, _record_offer
from ..llm.send_offer_llm import ComposeOffer

__all__ = ["process", "build_offer", "_record_offer", "ComposeOffer"]
