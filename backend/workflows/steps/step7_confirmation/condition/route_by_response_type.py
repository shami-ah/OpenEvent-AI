from __future__ import annotations

from typing import Any, Dict, Optional

from ..db_pers.post_offer import attach_post_offer_classification, enqueue_post_offer_routing_task

__workflow_role__ = "condition"

__all__ = ["route_by_response_type"]

_ROUTING_HINT_MAP: Dict[str, str] = {
    "confirm_booking": "confirm_booking",
    "site_visit": "site_visit",
    "change_request": "change_request",
    "reserve_date": "reserve_date",
    "not_interested": "negotiate_or_close",
    "general_question": "general_question",
}


def route_by_response_type(
    db: Dict[str, Any],
    *,
    client_email: str,
    message_id: str,
    classification: Dict[str, Any],
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist the classification and enqueue a routing task."""

    response_type = classification.get("response_type")
    if response_type not in _ROUTING_HINT_MAP:
        raise ValueError(f"Unsupported response_type '{response_type}'")
    routing_hint = _ROUTING_HINT_MAP[response_type]

    attach_post_offer_classification(db, client_email, message_id, classification)
    task_id = enqueue_post_offer_routing_task(db, client_email, event_id, message_id, routing_hint)

    return {
        "task_id": task_id,
        "routing_hint": routing_hint,
        "message_msg_id": message_id,
        "response_type": response_type,
    }
