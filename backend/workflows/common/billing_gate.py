"""
Billing gate utilities for offer acceptance flow.

Shared module used by Step4 (Offer) and Step5 (Negotiation) for billing
address capture and validation during offer acceptance.

Originally extracted from step5_handler.py (N3 refactoring), then moved
to common/ for O2 consolidation.

Usage:
    from backend.workflows.common.billing_gate import (
        refresh_billing,
        flag_billing_accept_pending,
        billing_prompt_draft,
    )

    missing = refresh_billing(event_entry)
    if missing:
        flag_billing_accept_pending(event_entry, missing)
        return billing_prompt_draft(missing, step=4)
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.workflows.common.billing import (
    billing_prompt_for_missing_fields,
    format_billing_display,
    missing_billing_fields,
    update_billing_details,
)


def refresh_billing(event_entry: Dict[str, Any]) -> List[str]:
    """
    Parse and persist billing details, returning missing required fields.

    Updates event_entry with:
    - billing_details parsed from client messages
    - event_data.Billing Address display string
    - billing_validation.missing list

    Args:
        event_entry: The event record to update

    Returns:
        List of missing required field names (empty if complete)
    """
    update_billing_details(event_entry)
    details = event_entry.get("billing_details") or {}
    missing = missing_billing_fields(event_entry)
    has_filled_required = len(missing) < 5
    display = format_billing_display(
        details, (event_entry.get("event_data") or {}).get("Billing Address")
    )
    if display and has_filled_required:
        event_entry.setdefault("event_data", {})["Billing Address"] = display

    validation = event_entry.setdefault("billing_validation", {})
    if missing:
        validation["missing"] = list(missing)
    else:
        validation.pop("missing", None)
    return missing


def flag_billing_accept_pending(
    event_entry: Dict[str, Any], missing_fields: List[str]
) -> None:
    """
    Mark the event as awaiting billing for acceptance.

    Sets billing_requirements.awaiting_billing_for_accept = True and
    records which fields are still missing.

    Args:
        event_entry: The event record to update
        missing_fields: List of missing billing field names
    """
    gate = event_entry.setdefault("billing_requirements", {})
    gate["awaiting_billing_for_accept"] = True
    gate["last_missing"] = list(missing_fields)


def billing_prompt_draft(missing_fields: List[str], *, step: int) -> Dict[str, Any]:
    """
    Create a draft message requesting billing details from the client.

    Args:
        missing_fields: List of missing billing field names
        step: Current workflow step number

    Returns:
        Draft message dict with body_markdown, step, topic, etc.
    """
    prompt = (
        "Thanks for confirming. I need the billing address before I can send this for approval.\n"
        f"{billing_prompt_for_missing_fields(missing_fields)} "
        'Example: "Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland". '
        "As soon as I have it, I'll forward the offer automatically."
    )
    return {
        "body_markdown": prompt,
        "step": step,
        "topic": "billing_details_required",
        "next_step": "Await billing details",
        "thread_state": "Awaiting Client",
        "requires_approval": False,
    }


__all__ = [
    "refresh_billing",
    "flag_billing_accept_pending",
    "billing_prompt_draft",
]
