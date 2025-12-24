"""
DEPRECATED: Use backend.workflows.steps.step7_confirmation.db_pers.post_offer instead.

This module re-exports from the new canonical location for backwards compatibility.
"""

from backend.workflows.steps.step7_confirmation.db_pers.post_offer import (
    attach_post_offer_classification,
    enqueue_post_offer_routing_task,
    enqueue_site_visit_followup,
    enqueue_site_visit_hil_review,
    HandlePostOfferRoute,
    HandleSiteVisitRoute,
)

__all__ = [
    "attach_post_offer_classification",
    "enqueue_post_offer_routing_task",
    "enqueue_site_visit_followup",
    "enqueue_site_visit_hil_review",
    "HandlePostOfferRoute",
    "HandleSiteVisitRoute",
]
