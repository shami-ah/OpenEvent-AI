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

import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
    process_msg as wf_process_msg,
)
from backend.workflows.common.confirmation_gate import check_confirmation_gate


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

    Requirements:
    - Event must exist
    - Event must be at Step 4 (offer step)
    - Deposit must be required (configured by manager)
    - Deposit must not already be paid

    See docs/internal/OPEN_DECISIONS.md DECISION-001 for handling deposit changes after payment.
    """
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

        wf_save_db(db)
        print(f"[Deposit] Event {request.event_id}: Deposit marked as paid")

        # Check if prerequisites are met to continue workflow using unified gate
        # Note: We just updated deposit_paid above, so use fresh event_entry state
        gate_status = check_confirmation_gate(event_entry)
        # Email is stored in event_data.Email, NOT directly as client_email
        client_email = (event_entry.get("event_data") or {}).get("Email", "")
        thread_id = event_entry.get("thread_id", request.event_id)

        if not gate_status.offer_accepted:
            print(f"[Deposit] Event {request.event_id}: Offer not accepted, not continuing workflow")
            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": False,
                "reason": "offer_not_accepted",
            }

        if not gate_status.billing_complete:
            print(f"[Deposit] Event {request.event_id}: Billing incomplete (missing: {gate_status.billing_missing}), not continuing workflow")
            return {
                "status": "ok",
                "event_id": request.event_id,
                "deposit_amount": deposit_info.get("deposit_amount"),
                "deposit_paid_at": deposit_info.get("deposit_paid_at"),
                "workflow_continued": False,
                "reason": "billing_address_missing",
                "billing_missing": gate_status.billing_missing,
            }

        # All prerequisites met - continue to HIL
        print(f"[Deposit] Event {request.event_id}: All prerequisites met (billing_complete={gate_status.billing_complete}, "
              f"deposit_paid={gate_status.deposit_paid}, offer_accepted={gate_status.offer_accepted}) - continuing to HIL")
        print(f"[Deposit] Using client_email={client_email}, thread_id={thread_id}")

        # Continue workflow with synthetic message about deposit payment
        synthetic_msg = {
            "msg_id": str(uuid.uuid4()),
            "from_name": "Client (GUI)",
            "from_email": client_email,
            "subject": f"Deposit paid for event {request.event_id}",
            "ts": _now_iso(),
            "body": "I have paid the deposit.",
            "thread_id": thread_id,
            "session_id": thread_id,
            "event_id": request.event_id,
            "deposit_just_paid": True,  # Signal to workflow handler
        }

        wf_res = {}
        try:
            wf_res = wf_process_msg(synthetic_msg)
            print(f"[Deposit] Workflow continued: action={wf_res.get('action')} event_id={wf_res.get('event_id')}")
        except Exception as exc:
            print(f"[Deposit][ERROR] Failed to continue workflow: {exc}")
            import traceback
            traceback.print_exc()

        # Extract response from draft_messages (workflow returns draft_messages, not reply_text)
        draft_messages = wf_res.get("draft_messages") or []
        response_text = None
        if draft_messages:
            latest_draft = draft_messages[-1]
            response_text = latest_draft.get("body_markdown") or latest_draft.get("body")

        return {
            "status": "ok",
            "event_id": request.event_id,
            "deposit_amount": deposit_info.get("deposit_amount"),
            "deposit_paid_at": deposit_info.get("deposit_paid_at"),
            "workflow_continued": True,
            "workflow_action": wf_res.get("action"),
            "response": response_text,
            "draft_messages": draft_messages,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to process deposit payment: {exc}"
        ) from exc


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
        raise HTTPException(
            status_code=500, detail=f"Failed to get deposit status: {exc}"
        ) from exc


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
