"""
DEPRECATED: Use backend.workflows.steps.step4_offer.hil.create_offer instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step4_offer.hil.create_offer import CreateProfessionalOffer

__workflow_role__ = "hil"

__all__ = ["CreateProfessionalOffer"]
