"""
MODULE: backend/api/routes/events.py
PURPOSE: Event management and deposit handling endpoints.

ENDPOINTS:
    GET  /api/events              - List all events
    GET  /api/events/{event_id}   - Get specific event
    GET  /api/event/{id}/deposit  - Get deposit status
    POST /api/event/deposit/pay   - Mark deposit as paid

DEPENDS ON:
    - backend/workflow_email.py  # Database operations
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.utils.errors import raise_safe_error

logger = logging.getLogger(__name__)

from workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
    process_msg as wf_process_msg,
)
from workflows.common.confirmation_gate import check_confirmation_gate
from workflows.common.types import IncomingMessage, WorkflowState
from workflows.io.database import update_event_metadata
from workflows.io import database as db_io


router = APIRouter(tags=["events"])


# --- Request Models ---

class DepositPaymentRequest(BaseModel):
    """Request to mark a deposit as paid."""
    event_id: str


# --- Helper Functions ---

def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


# --- Route Handlers ---

@router.post("/api/event/deposit/pay")
async def pay_deposit(request: DepositPaymentRequest):
    """
    Mark the deposit as paid for an event.

    This is a mock endpoint for testing. In production, this would be
    triggered by a payment gateway webhook after successful payment.

    SECURITY: This endpoint is disabled by default.
    Set ENABLE_TEST_ENDPOINTS=true to enable (development/testing only).

    Requirements:
    - Event must exist
    - Event must be at Step 4 (offer step)
    - Deposit must be required (configured by manager)
    - Deposit must not already be paid

    See docs/plans/OPEN_DECISIONS.md DECISION-001 for handling deposit changes after payment.
    """
    # Production guard - mock payment endpoint should only be used in dev/test
    if os.getenv("ENABLE_TEST_ENDPOINTS", "false").lower() != "true":
        raise HTTPException(
            status_code=403,
            detail="Mock deposit payment disabled. In production, use payment gateway webhooks. "
                   "Set ENABLE_TEST_ENDPOINTS=true for testing."
        )

    try:
        db = wf_load_db()
        events = db.get("events") or []
        event_entry = None
        event_index = None
        for idx, event in enumerate(events):
            if event.get("event_id") == request.event_id:
                event_entry = event
                event_index = idx
                break

        if not event_entry:
            raise HTTPException(status_code=404, detail="Event not found")

        current_step = event_entry.get("current_step", 1)
        if current_step not in (4, 5):
            raise HTTPException(
                status_code=400,
                detail=f"Deposit can only be paid at Step 4 (offer) or Step 5 (negotiation). Current step: {current_step}"
            )

        deposit_info = event_entry.get("deposit_info")
        if not deposit_info or not deposit_info.get("deposit_required"):
            raise HTTPException(
                status_code=400,
                detail="No deposit is required for this event"
            )

        if deposit_info.get("deposit_paid"):
            return {
                "status": "already_paid",
                "event_id": request.event_id,
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
            }

        # Mark deposit as paid
        deposit_info["deposit_paid"] = True
        deposit_info["deposit_paid_at"] = _now_iso()
        event_entry["deposit_info"] = deposit_info

        # Log activity
        from activity.persistence import log_workflow_activity
        deposit_amount = deposit_info.get("deposit_amount", "")
        log_workflow_activity(event_entry, "deposit_paid", amount=str(deposit_amount))

        wf_save_db(db)
        logger.info("Event %s: Deposit marked as paid", request.event_id)

        # Check if prerequisites are met to continue workflow using unified gate
        # Note: We just updated deposit_paid above, so use fresh event_entry state
        gate_status = check_confirmation_gate(event_entry)
        # Email is stored in event_data.Email, NOT directly as client_email
        client_email = (event_entry.get("event_data") or {}).get("Email", "")
        thread_id = event_entry.get("thread_id", request.event_id)

        if not gate_status.offer_accepted:
            logger.info("Event %s: Offer not accepted, not continuing workflow", request.event_id)
            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": False,
                "reason": "offer_not_accepted",
            }

        if not gate_status.billing_complete:
            logger.info("Event %s: Billing incomplete (missing: %s), not continuing workflow",
                        request.event_id, gate_status.billing_missing)
            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": False,
                "reason": "billing_address_missing",
                "billing_missing": gate_status.billing_missing,
            }

        # All prerequisites met - continue directly to Step 7 for site visit question
        logger.info("Event %s: All prerequisites met (billing=%s, deposit=%s, offer=%s) - continuing to Step 7",
                    request.event_id, gate_status.billing_complete, gate_status.deposit_paid, gate_status.offer_accepted)
        logger.debug("Event %s: client_email=%s, thread_id=%s", request.event_id, client_email, thread_id)

        # Update event to Step 7 and call Step 7 handler directly
        # This ensures the site visit question is generated (similar to HIL approval flow)
        try:
            from workflows.steps.step7_confirmation.trigger.process import process as process_step7
            from pathlib import Path

            # Get database path
            db_path = Path(os.getenv("WF_DB_PATH", "events_team-shami.json"))
            lock_path = db_path.with_suffix(".lock")

            # Update event metadata to Step 7
            update_event_metadata(event_entry, current_step=7, thread_state="Processing")

            # Create a fresh state for Step 7 processing
            step7_message = IncomingMessage.from_dict({
                "msg_id": f"deposit-continue-{request.event_id}",
                "from_email": client_email,
                "subject": "Deposit paid - continue to confirmation",
                "body": "",  # Empty body - just continuing the workflow
                "ts": _now_iso(),
                "deposit_just_paid": True,
            })
            step7_state = WorkflowState(message=step7_message, db_path=db_path, db=db)
            step7_state.client_id = client_email.lower() if client_email else ""
            step7_state.event_entry = event_entry
            step7_state.current_step = 7
            step7_state.thread_state = "Processing"

            # Call Step 7 to generate the site visit message
            _step7_result = process_step7(step7_state)

            # Get the generated message from state
            draft_messages = step7_state.draft_messages or []
            response_text = None
            if draft_messages:
                draft = draft_messages[0]
                # Use body (client message) first, not body_markdown (manager display)
                response_text = draft.get("body") or draft.get("body_markdown") or ""
            else:
                # Fallback message if Step 7 didn't generate one
                response_text = "Thank you for the deposit. We will be in touch shortly to finalize the details."

            # Persist changes
            if step7_state.extras.get("persist"):
                wf_save_db(db)
            else:
                wf_save_db(db)

            logger.info("Event %s: Step 7 generated response, action=%s",
                       request.event_id, _step7_result.action if _step7_result else "none")

            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": True,
                "workflow_action": _step7_result.action if _step7_result else "step7_continue",
                "response": response_text,
                "draft_messages": draft_messages,
            }

        except Exception as exc:
            logger.exception("Failed to continue workflow to Step 7: %s", exc)
            # Fallback: still return success but note the workflow didn't continue
            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": False,
                "reason": "step7_processing_failed",
                "error": str(exc),
            }

    except HTTPException:
        raise
    except Exception as exc:
        raise_safe_error(500, "process deposit payment", exc, logger)


@router.get("/api/event/{event_id}/deposit")
async def get_deposit_status(event_id: str):
    """
    Get the deposit status for an event.

    Returns deposit info including:
    - Whether deposit is required
    - Deposit amount and due date
    - Whether deposit has been paid
    """
    try:
        db = wf_load_db()
        events = db.get("events") or []
        event_entry = None
        for event in events:
            if event.get("event_id") == event_id:
                event_entry = event
                break

        if not event_entry:
            raise HTTPException(status_code=404, detail="Event not found")

        deposit_info = event_entry.get("deposit_info")
        current_step = event_entry.get("current_step", 1)

        if not deposit_info:
            return {
                "event_id": event_id,
                "deposit_required": False,
                "current_step": current_step,
            }

        return {
            "event_id": event_id,
            "current_step": current_step,
            **deposit_info,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise_safe_error(500, "get deposit status", exc, logger)


@router.get("/api/events")
async def get_all_events():
    """
    Get all saved events from database
    """
    db = wf_load_db()
    events = db.get("events") or []
    return {
        "total_events": len(events),
        "events": events
    }


@router.get("/api/events/{event_id}")
async def get_event_by_id(event_id: str):
    """
    Get a specific event by ID
    """
    db = wf_load_db()
    events = db.get("events") or []

    for event in events:
        if event.get("event_id") == event_id:
            return event

    raise HTTPException(status_code=404, detail="Event not found")


# --- Cancellation Models ---

class CancelEventRequest(BaseModel):
    """Request to cancel an event booking.

    Requires explicit confirmation string to prevent accidental cancellations.
    """
    event_id: str
    confirmation: str  # Must be exactly "CANCEL"
    reason: Optional[str] = None  # Optional reason for cancellation


class CancelEventResponse(BaseModel):
    """Response from cancel event endpoint."""
    status: str
    event_id: str
    previous_step: int
    had_site_visit: bool
    cancellation_type: str  # "site_visit" or "standard"
    archived_at: str


# --- Cancel Endpoint ---

@router.post("/api/event/{event_id}/cancel")
async def cancel_event(event_id: str, request: CancelEventRequest):
    """
    Cancel an event booking.

    This is a manager action that requires explicit confirmation by typing "CANCEL".
    The confirmation is case-sensitive to prevent accidental cancellations.

    Behavior varies based on event state:
    - If site visit was scheduled: Archives event, manager should send regret email
    - Standard flow: Archives event immediately

    The event is NOT deleted but moved to "cancelled" status for audit purposes.

    See docs/plans/OPEN_DECISIONS.md DECISION-012 for full spec.
    """
    # Validate confirmation string
    if request.confirmation != "CANCEL":
        raise HTTPException(
            status_code=400,
            detail="Confirmation must be exactly 'CANCEL' (case-sensitive)"
        )

    if request.event_id != event_id:
        raise HTTPException(
            status_code=400,
            detail="Event ID in path must match event_id in request body"
        )

    try:
        db = wf_load_db()
        events = db.get("events") or []
        event_entry = None
        event_index = None

        for idx, event in enumerate(events):
            if event.get("event_id") == event_id:
                event_entry = event
                event_index = idx
                break

        if not event_entry:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check if already cancelled
        if event_entry.get("status") == "cancelled":
            return {
                "status": "already_cancelled",
                "event_id": event_id,
                "cancelled_at": event_entry.get("cancelled_at"),
            }

        # Determine cancellation type
        current_step = event_entry.get("current_step", 1)
        had_site_visit = current_step >= 7 or event_entry.get("site_visit_scheduled", False)
        cancellation_type = "site_visit" if had_site_visit else "standard"

        # Archive the event (don't delete for audit trail)
        cancelled_at = _now_iso()
        event_entry["status"] = "cancelled"
        event_entry["cancelled_at"] = cancelled_at
        event_entry["cancellation_reason"] = request.reason
        event_entry["cancellation_type"] = cancellation_type
        event_entry["previous_step"] = current_step

        # Mark thread state for UI
        event_entry["thread_state"] = "Cancelled"

        wf_save_db(db)
        logger.info(
            "Event %s cancelled: type=%s, previous_step=%d, reason=%s",
            event_id, cancellation_type, current_step, request.reason
        )

        return CancelEventResponse(
            status="cancelled",
            event_id=event_id,
            previous_step=current_step,
            had_site_visit=had_site_visit,
            cancellation_type=cancellation_type,
            archived_at=cancelled_at,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to cancel event: %s", exc)
        raise_safe_error(500, "cancel event", exc, logger)
