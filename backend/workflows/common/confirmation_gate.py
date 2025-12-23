"""
Generic Prerequisites Gate for Offer Confirmation

This module provides ORDER-INDEPENDENT checking of confirmation prerequisites:
1. Billing address must be complete
2. Deposit must be paid (if required)

The gate works regardless of which order the client completes these:
- Accept → Billing → Deposit → HIL
- Accept → Deposit → Billing → HIL
- Deposit → Accept → Billing → HIL
- etc.

Once BOTH conditions are met, the workflow automatically continues to HIL.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.billing import missing_billing_fields


@dataclass
class GateStatus:
    """Current status of confirmation prerequisites."""

    billing_complete: bool
    billing_missing: List[str]
    deposit_required: bool
    deposit_paid: bool
    deposit_amount: float
    offer_accepted: bool

    @property
    def ready_for_hil(self) -> bool:
        """True if all prerequisites are met and we can proceed to HIL."""
        if not self.offer_accepted:
            return False
        if not self.billing_complete:
            return False
        if self.deposit_required and not self.deposit_paid:
            return False
        return True

    @property
    def pending_items(self) -> List[str]:
        """List of items still needed before HIL."""
        items = []
        if not self.billing_complete:
            items.append("billing_address")
        if self.deposit_required and not self.deposit_paid:
            items.append("deposit_payment")
        return items


def check_confirmation_gate(event_entry: Dict[str, Any]) -> GateStatus:
    """
    Check the current status of confirmation prerequisites.

    This reads from the event_entry dict which should contain the latest state.
    For truly fresh data, reload from database before calling this.

    Args:
        event_entry: The event data dict

    Returns:
        GateStatus with current state of all prerequisites
    """
    # Check billing status
    billing_missing = missing_billing_fields(event_entry)
    billing_complete = len(billing_missing) == 0

    # Check deposit status from BOTH sources (deposit_info and deposit_state)
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_state = event_entry.get("deposit_state") or {}

    deposit_required = (
        deposit_info.get("deposit_required", False)
        or deposit_state.get("required", False)
    )
    deposit_paid = (
        deposit_info.get("deposit_paid", False)
        or deposit_state.get("status") == "paid"
    )
    deposit_amount = (
        deposit_info.get("deposit_amount")
        or deposit_state.get("due_amount")
        or 0.0
    )

    # Check offer acceptance
    offer_accepted = bool(event_entry.get("offer_accepted"))

    return GateStatus(
        billing_complete=billing_complete,
        billing_missing=billing_missing,
        deposit_required=deposit_required,
        deposit_paid=deposit_paid,
        deposit_amount=deposit_amount,
        offer_accepted=offer_accepted,
    )


def reload_and_check_gate(
    event_id: str,
    db_path: Optional[Path] = None,
) -> Tuple[GateStatus, Dict[str, Any]]:
    """
    Reload event from database and check gate status.

    This ensures we're using the LATEST state, including any changes
    made via the API (like deposit marked paid via frontend).

    Args:
        event_id: The event ID to check
        db_path: Optional path to database file

    Returns:
        Tuple of (GateStatus, fresh_event_entry)
    """
    from backend.workflows.io.database import load_db

    # Default database path
    default_path = Path(__file__).resolve().parents[2] / "events_database.json"
    path = db_path or default_path
    db = load_db(path)
    events = db.get("events", [])

    # Find the event
    event_entry = None
    for ev in events:
        if ev.get("event_id") == event_id:
            event_entry = ev
            break

    if event_entry is None:
        # Return empty status if event not found
        return GateStatus(
            billing_complete=False,
            billing_missing=["company", "street", "city", "postal_code", "country"],
            deposit_required=False,
            deposit_paid=False,
            deposit_amount=0.0,
            offer_accepted=False,
        ), {}

    status = check_confirmation_gate(event_entry)
    return status, event_entry


def get_next_prompt(status: GateStatus, step: int = 5) -> Optional[Dict[str, Any]]:
    """
    Get the appropriate prompt based on what's still missing.

    Returns None if all prerequisites are met (ready for HIL).

    Args:
        status: Current gate status
        step: Current workflow step (for footer)

    Returns:
        Draft message dict or None if ready for HIL
    """
    from backend.workflows.common.billing import billing_prompt_for_missing_fields

    if status.ready_for_hil:
        return None

    # Prioritize: billing first if both missing (arbitrary but consistent)
    if not status.billing_complete:
        prompt = (
            "Thanks for confirming — I need the billing address before I can send this for approval.\n"
            f"{billing_prompt_for_missing_fields(status.billing_missing)} "
            'Example: "Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland". '
            "As soon as I have it, I'll forward the offer automatically."
        )
        # Add deposit note if also needed
        if status.deposit_required and not status.deposit_paid and status.deposit_amount > 0:
            prompt += f"\n\nNote: The deposit of CHF {status.deposit_amount:,.2f} is also required before final confirmation."
        return {
            "body_markdown": prompt,
            "step": step,
            "topic": "billing_details_required",
            "next_step": "Await billing details",
            "thread_state": "Awaiting Client",
            "requires_approval": False,
        }

    if status.deposit_required and not status.deposit_paid:
        prompt = (
            f"Thank you for providing your billing details! Before I can proceed with your booking, "
            f"please complete the deposit payment of CHF {status.deposit_amount:,.2f}. "
            f"Once the deposit is received, I'll immediately send your confirmation for final approval."
        )
        return {
            "body_markdown": prompt,
            "step": step,
            "topic": "deposit_reminder",
            "next_step": "Awaiting deposit payment",
            "thread_state": "Awaiting Client",
            "requires_approval": False,
        }

    return None


def auto_continue_if_ready(
    event_id: str,
    event_entry: Dict[str, Any],
    db_path: Optional[Path] = None,
) -> Tuple[bool, GateStatus, Dict[str, Any]]:
    """
    Check if prerequisites are met and return updated state.

    This is the main entry point for order-independent gate checking.
    Call this after ANY action that might complete a prerequisite:
    - After billing address is provided
    - After deposit is marked as paid
    - After offer acceptance

    Args:
        event_id: The event ID
        event_entry: Current event entry (may be stale)
        db_path: Optional database path

    Returns:
        Tuple of (ready_for_hil, gate_status, fresh_event_entry)
    """
    # Reload from database to get latest state
    status, fresh_entry = reload_and_check_gate(event_id, db_path)

    # Update the passed event_entry with fresh data (mutates in place)
    if fresh_entry:
        event_entry.update(fresh_entry)

    return status.ready_for_hil, status, fresh_entry


__all__ = [
    "GateStatus",
    "check_confirmation_gate",
    "reload_and_check_gate",
    "get_next_prompt",
    "auto_continue_if_ready",
]
