"""
MODULE: backend/api/routes/emails.py
PURPOSE: Email sending endpoints for client communications.

ENDPOINTS:
    POST /api/emails/send-to-client    - Send email to client (after HIL approval)
    POST /api/emails/send-offer        - Send offer email to client
    POST /api/emails/test              - Send test email to verify SMTP config

INTEGRATION NOTE:
These endpoints are called AFTER HIL approval to send the actual email to
the client. The email content is the approved/edited draft from the HIL task.

In production, these integrate with:
- Supabase emails table (for history/tracking)
- SMTP for actual delivery
- Event manager's email account
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import load_db as wf_load_db
from backend.workflows.io.config_store import get_venue_name


router = APIRouter(prefix="/api/emails", tags=["emails"])


# --- Request Models ---

class SendClientEmailRequest(BaseModel):
    """Request to send email to a client."""
    to_email: str
    to_name: str
    subject: str
    body_text: str
    body_html: Optional[str] = None
    event_id: Optional[str] = None
    task_id: Optional[str] = None  # Link to approved HIL task


class SendOfferEmailRequest(BaseModel):
    """Request to send offer email to a client."""
    event_id: str
    subject: Optional[str] = None  # Auto-generated if not provided
    custom_message: Optional[str] = None  # Prepended to offer


class TestEmailRequest(BaseModel):
    """Request to send test email."""
    to_email: str
    to_name: Optional[str] = "Test Recipient"


# --- Endpoints ---

@router.post("/send-to-client")
async def send_email_to_client(request: SendClientEmailRequest):
    """
    Send email to a client.

    This is called AFTER HIL approval to send the actual email.
    The body_text should be the approved (and optionally edited) draft.

    In production, this:
    1. Sends via SMTP
    2. Records in Supabase emails table
    3. Links to event for history

    Returns:
        success: bool
        message: str
        email_id: Optional[str] - ID in emails table (for Supabase)
    """
    try:
        from backend.services.hil_email_notification import (
            send_client_email,
            get_hil_email_config,
        )

        config = get_hil_email_config()

        if not config.get("smtp_user") or not config.get("smtp_password"):
            # SMTP not configured - return success but note it's simulated
            return {
                "success": True,
                "message": "Email queued (SMTP not configured - would send in production)",
                "simulated": True,
                "to_email": request.to_email,
                "subject": request.subject,
            }

        result = send_client_email(
            to_email=request.to_email,
            to_name=request.to_name,
            subject=request.subject,
            body_text=request.body_text,
            body_html=request.body_html,
            event_id=request.event_id,
        )

        if result["success"]:
            # Log the sent email for tracking
            _log_sent_email(
                to_email=request.to_email,
                subject=request.subject,
                body=request.body_text,
                event_id=request.event_id,
                task_id=request.task_id,
            )

        return result

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/send-offer")
async def send_offer_email(request: SendOfferEmailRequest):
    """
    Send offer email to a client.

    Fetches the offer details from the event and composes a professional
    offer email. Used after Step 4 HIL approval.

    Returns:
        success: bool
        message: str
        offer_total: Optional[float]
    """
    try:
        db = wf_load_db()

        # Find the event
        event = None
        for e in db.get("events", []):
            if e.get("event_id") == request.event_id:
                event = e
                break

        if not event:
            raise HTTPException(status_code=404, detail=f"Event {request.event_id} not found")

        # Extract client info
        event_data = event.get("event_data") or {}
        client_email = event_data.get("Email")
        client_name = event_data.get("Name", "Valued Client")

        if not client_email:
            raise HTTPException(status_code=400, detail="No client email on event")

        # Build offer content
        chosen_date = event.get("chosen_date", "TBD")
        locked_room = event.get("locked_room_id", "TBD")

        # Calculate total
        try:
            from backend.workflows.steps.step5_negotiation.trigger.step5_handler import _determine_offer_total
            offer_total = _determine_offer_total(event)
        except Exception:
            offer_total = None

        # Build subject
        subject = request.subject or f"Event Offer - {chosen_date}"

        # Build body
        body_lines = []
        if request.custom_message:
            body_lines.append(request.custom_message)
            body_lines.append("")

        venue_name = get_venue_name()
        body_lines.extend([
            f"Dear {client_name},",
            "",
            f"Thank you for your interest in booking with {venue_name}.",
            "",
            f"We are pleased to offer the following for your event:",
            "",
            f"- Date: {chosen_date}",
            f"- Room: {locked_room}",
        ])

        if offer_total:
            body_lines.append(f"- Total: CHF {offer_total:,.2f}")

        body_lines.extend([
            "",
            "Please let us know if you have any questions or would like to proceed.",
            "",
            "Best regards,",
            f"{venue_name} Team",
        ])

        body_text = "\n".join(body_lines)

        # Send via the client email endpoint
        from backend.services.hil_email_notification import (
            send_client_email,
            get_hil_email_config,
        )

        config = get_hil_email_config()

        if not config.get("smtp_user") or not config.get("smtp_password"):
            return {
                "success": True,
                "message": "Offer email queued (SMTP not configured)",
                "simulated": True,
                "to_email": client_email,
                "subject": subject,
                "offer_total": offer_total,
            }

        result = send_client_email(
            to_email=client_email,
            to_name=client_name,
            subject=subject,
            body_text=body_text,
            event_id=request.event_id,
        )

        result["offer_total"] = offer_total
        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/test")
async def send_test_email(request: TestEmailRequest):
    """
    Send a test email to verify SMTP configuration.

    Use this to confirm email sending works before going live.
    """
    try:
        from backend.services.hil_email_notification import (
            send_client_email,
            get_hil_email_config,
        )

        config = get_hil_email_config()

        if not config.get("smtp_user") or not config.get("smtp_password"):
            return {
                "success": False,
                "error": "SMTP not configured. Set SMTP_USER, SMTP_PASSWORD environment variables.",
                "smtp_host": config.get("smtp_host"),
            }

        result = send_client_email(
            to_email=request.to_email,
            to_name=request.to_name,
            subject="[OpenEvent] Test Email",
            body_text="This is a test email from OpenEvent.\n\nIf you received this, email sending is configured correctly!",
        )

        return result

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- Helper Functions ---

def _log_sent_email(
    to_email: str,
    subject: str,
    body: str,
    event_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    """
    Log sent email for tracking.

    In production with Supabase, this would insert into the emails table.
    For now, we just log to console and could add to event history.
    """
    print(f"[EMAIL_SENT] To: {to_email}, Subject: {subject}")

    if event_id:
        try:
            from backend.workflow_email import load_db, save_db

            db = load_db()
            for event in db.get("events", []):
                if event.get("event_id") == event_id:
                    event.setdefault("email_history", []).append({
                        "to_email": to_email,
                        "subject": subject,
                        "sent_at": datetime.utcnow().isoformat() + "Z",
                        "task_id": task_id,
                    })
                    save_db(db)
                    break
        except Exception as e:
            print(f"[EMAIL_LOG] Failed to log to event: {e}")
