"""
DEPRECATED: Use backend.workflows.steps.step4_offer.trigger.process instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step4_offer.trigger.process import (
    process,
    build_offer,
    _record_offer,
    ComposeOffer,
)

__all__ = [
    "process",
    "build_offer",
    "_record_offer",
    "ComposeOffer",
]
