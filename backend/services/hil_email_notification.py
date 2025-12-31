"""
HIL Email Notification Service

Sends email notifications to the Event Manager when HIL tasks are created.
This runs IN ADDITION to the frontend HIL panel (not instead of).

Architecture:
- Frontend HIL panel: Still works as-is, polls /api/tasks/pending
- Email notification: ALSO sends email when task is created
- Manager email: Comes from logged-in user (Supabase) or config fallback

For production, the manager email is fetched from Supabase auth.
For testing, use EVENT_MANAGER_EMAIL env var or /api/config/hil-email endpoint.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
import logging

from backend.workflows.io.config_store import (
    get_timezone,
    get_from_email,
    get_from_name,
    get_frontend_url,
)

logger = logging.getLogger(__name__)


def _get_venue_timezone() -> ZoneInfo:
    """Get venue timezone from config."""
    return ZoneInfo(get_timezone())




# =============================================================================
# Configuration
# =============================================================================

def get_hil_email_config() -> Dict[str, Any]:
    """
    Get HIL email notification configuration.

    Priority:
    1. Database config (set via /api/config/hil-email)
    2. Environment variables
    3. Disabled by default

    Returns:
        Config dict with enabled, manager_email, smtp settings
    """
    from backend.workflow_email import load_db

    # Get venue-specific defaults from config store
    venue_from_email = get_from_email()
    venue_from_name = get_from_name()

    config = {
        "enabled": False,
        "manager_email": None,
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER"),
        "smtp_password": os.getenv("SMTP_PASSWORD"),
        "from_email": os.getenv("HIL_FROM_EMAIL", venue_from_email),
        "from_name": os.getenv("HIL_FROM_NAME", venue_from_name),
    }

    # Check database config first
    try:
        db = load_db()
        hil_email_config = db.get("config", {}).get("hil_email", {})
        if hil_email_config.get("enabled"):
            config["enabled"] = True
            config["manager_email"] = hil_email_config.get("manager_email")
            # SMTP settings from DB if provided
            if hil_email_config.get("smtp_host"):
                config["smtp_host"] = hil_email_config["smtp_host"]
            if hil_email_config.get("smtp_port"):
                config["smtp_port"] = hil_email_config["smtp_port"]
            if hil_email_config.get("smtp_user"):
                config["smtp_user"] = hil_email_config["smtp_user"]
            if hil_email_config.get("from_email"):
                config["from_email"] = hil_email_config["from_email"]
    except Exception as e:
        logger.warning(f"[HIL_EMAIL] Failed to load DB config: {e}")

    # Fall back to environment variable
    if not config["manager_email"]:
        config["manager_email"] = os.getenv("EVENT_MANAGER_EMAIL")

    # Enable if we have manager email and SMTP credentials
    if config["manager_email"] and config["smtp_user"] and config["smtp_password"]:
        config["enabled"] = True

    return config


def is_hil_email_enabled() -> bool:
    """Check if HIL email notifications are enabled."""
    config = get_hil_email_config()
    return config["enabled"] and config["manager_email"] is not None


# =============================================================================
# Email Templates
# =============================================================================

def _build_hil_email_html(
    task_type: str,
    client_name: str,
    client_email: str,
    draft_body: str,
    event_summary: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    frontend_url: Optional[str] = None,
) -> str:
    """
    Build HTML email for HIL notification.

    Args:
        task_type: Type of HIL task (offer_message, date_confirmation, etc.)
        client_name: Client's name
        client_email: Client's email
        draft_body: The AI-generated draft message
        event_summary: Optional event details
        task_id: Task ID for approve/reject links
        frontend_url: Base URL for the frontend

    Returns:
        HTML email body
    """
    # Use config for frontend URL if not provided
    if frontend_url is None:
        frontend_url = get_frontend_url()

    # Task type display names
    task_type_names = {
        "offer_message": "Offer Message",
        "date_confirmation_message": "Date Confirmation",
        "room_availability_message": "Room Availability",
        "ask_for_date": "Date Request",
        "manual_review": "Manual Review Required",
        "ai_reply_approval": "AI Reply",
    }
    task_display = task_type_names.get(task_type, task_type.replace("_", " ").title())

    # Build event details section
    event_details_html = ""
    if event_summary:
        details = []
        if event_summary.get("chosen_date"):
            details.append(f"<li><strong>Date:</strong> {event_summary['chosen_date']}</li>")
        if event_summary.get("locked_room"):
            details.append(f"<li><strong>Room:</strong> {event_summary['locked_room']}</li>")
        if event_summary.get("offer_total"):
            details.append(f"<li><strong>Total:</strong> CHF {event_summary['offer_total']:,.2f}</li>")
        if event_summary.get("line_items"):
            items = ", ".join(event_summary["line_items"][:3])
            if len(event_summary["line_items"]) > 3:
                items += f" (+{len(event_summary['line_items']) - 3} more)"
            details.append(f"<li><strong>Items:</strong> {items}</li>")

        if details:
            event_details_html = f"""
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0;">
                <h4 style="margin: 0 0 10px 0; color: #495057;">Event Details</h4>
                <ul style="margin: 0; padding-left: 20px;">
                    {"".join(details)}
                </ul>
            </div>
            """

    # Approve/Reject buttons (link to frontend)
    approve_url = f"{frontend_url}?action=approve&task_id={task_id}"
    reject_url = f"{frontend_url}?action=reject&task_id={task_id}"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">HIL Approval Required</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">{task_display} for {client_name}</p>
        </div>

        <div style="background: white; border: 1px solid #e9ecef; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <p><strong>Client:</strong> {client_name} ({client_email})</p>

            {event_details_html}

            <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 15px 0;">
                <h4 style="margin: 0 0 10px 0; color: #856404;">AI-Generated Draft</h4>
                <div style="white-space: pre-wrap; font-size: 14px; color: #333;">
{draft_body}
                </div>
            </div>

            <div style="margin-top: 20px; text-align: center;">
                <p style="color: #6c757d; font-size: 14px;">
                    Review and approve this message in the OpenEvent dashboard:
                </p>
                <a href="{frontend_url}" style="display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: 500; margin-top: 10px;">
                    Open Dashboard
                </a>
            </div>

            <hr style="border: none; border-top: 1px solid #e9ecef; margin: 20px 0;">

            <p style="color: #6c757d; font-size: 12px; text-align: center; margin: 0;">
                This is an automated notification from OpenEvent AI.<br>
                Task ID: {task_id}
            </p>
        </div>
    </body>
    </html>
    """

    return html


def _build_hil_email_plain(
    task_type: str,
    client_name: str,
    client_email: str,
    draft_body: str,
    event_summary: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    frontend_url: Optional[str] = None,
) -> str:
    """Build plain text email for HIL notification."""
    # Use config for frontend URL if not provided
    if frontend_url is None:
        frontend_url = get_frontend_url()
    task_type_names = {
        "offer_message": "Offer Message",
        "date_confirmation_message": "Date Confirmation",
        "room_availability_message": "Room Availability",
        "ask_for_date": "Date Request",
        "manual_review": "Manual Review Required",
        "ai_reply_approval": "AI Reply",
    }
    task_display = task_type_names.get(task_type, task_type.replace("_", " ").title())

    text = f"""
HIL APPROVAL REQUIRED
=====================

Task: {task_display}
Client: {client_name} ({client_email})
"""

    if event_summary:
        text += "\nEvent Details:\n"
        if event_summary.get("chosen_date"):
            text += f"  - Date: {event_summary['chosen_date']}\n"
        if event_summary.get("locked_room"):
            text += f"  - Room: {event_summary['locked_room']}\n"
        if event_summary.get("offer_total"):
            text += f"  - Total: CHF {event_summary['offer_total']:,.2f}\n"

    text += f"""
AI-Generated Draft:
-------------------
{draft_body}
-------------------

Review and approve in the OpenEvent dashboard:
{frontend_url}

Task ID: {task_id}
"""

    return text


# =============================================================================
# Email Sending
# =============================================================================

def send_hil_notification(
    task_id: str,
    task_type: str,
    client_name: str,
    client_email: str,
    draft_body: str,
    event_summary: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send HIL notification email to the Event Manager.

    This function is called when a HIL task is created to ALSO send
    an email notification (in addition to the frontend panel).

    Args:
        task_id: Unique task ID
        task_type: Type of HIL task
        client_name: Client's name
        client_email: Client's email
        draft_body: AI-generated draft message
        event_summary: Optional event details for context
        event_id: Optional event ID

    Returns:
        Result dict with success status and message
    """
    config = get_hil_email_config()

    if not config["enabled"]:
        return {"success": False, "error": "HIL email notifications not enabled"}

    if not config["manager_email"]:
        return {"success": False, "error": "No manager email configured"}

    if not config["smtp_user"] or not config["smtp_password"]:
        return {"success": False, "error": "SMTP credentials not configured"}

    try:
        # Build email - use config store with env var override
        frontend_url = os.getenv("FRONTEND_URL") or get_frontend_url()

        subject = f"[OpenEvent] HIL: {task_type.replace('_', ' ').title()} - {client_name}"

        html_body = _build_hil_email_html(
            task_type=task_type,
            client_name=client_name,
            client_email=client_email,
            draft_body=draft_body,
            event_summary=event_summary,
            task_id=task_id,
            frontend_url=frontend_url,
        )

        plain_body = _build_hil_email_plain(
            task_type=task_type,
            client_name=client_name,
            client_email=client_email,
            draft_body=draft_body,
            event_summary=event_summary,
            task_id=task_id,
            frontend_url=frontend_url,
        )

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config['from_name']} <{config['from_email']}>"
        msg["To"] = config["manager_email"]

        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Send via SMTP
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["smtp_user"], config["smtp_password"])
            server.send_message(msg)

        logger.info(f"[HIL_EMAIL] Sent notification for task {task_id} to {config['manager_email']}")

        return {
            "success": True,
            "message": f"Email sent to {config['manager_email']}",
            "task_id": task_id,
        }

    except smtplib.SMTPException as e:
        logger.error(f"[HIL_EMAIL] SMTP error: {e}")
        return {"success": False, "error": f"SMTP error: {str(e)}"}
    except Exception as e:
        logger.error(f"[HIL_EMAIL] Failed to send: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# Client Email Sending (Offer/Response to Client)
# =============================================================================

def send_client_email(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send email to a client (offer, confirmation, etc).

    This is for OUTBOUND emails to clients after HIL approval.

    Args:
        to_email: Client's email address
        to_name: Client's name
        subject: Email subject
        body_text: Plain text body
        body_html: Optional HTML body
        event_id: Optional event ID for tracking

    Returns:
        Result dict with success status
    """
    config = get_hil_email_config()

    if not config["smtp_user"] or not config["smtp_password"]:
        return {"success": False, "error": "SMTP credentials not configured"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config['from_name']} <{config['from_email']}>"
        msg["To"] = f"{to_name} <{to_email}>"

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["smtp_user"], config["smtp_password"])
            server.send_message(msg)

        logger.info(f"[CLIENT_EMAIL] Sent email to {to_email}, subject: {subject}")

        return {
            "success": True,
            "message": f"Email sent to {to_email}",
            "to_email": to_email,
        }

    except smtplib.SMTPException as e:
        logger.error(f"[CLIENT_EMAIL] SMTP error: {e}")
        return {"success": False, "error": f"SMTP error: {str(e)}"}
    except Exception as e:
        logger.error(f"[CLIENT_EMAIL] Failed to send: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# Hook for HIL Task Creation
# =============================================================================

def notify_hil_task_created(
    task: Dict[str, Any],
    event_entry: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Hook called when a HIL task is created.

    Sends email notification if enabled.

    Args:
        task: The HIL task record
        event_entry: Optional event entry for context

    Returns:
        Email send result or None if disabled
    """
    if not is_hil_email_enabled():
        return None

    # Extract info from task
    task_id = task.get("task_id", "")
    task_type = task.get("type", "unknown")

    # Get client info
    payload = task.get("payload") or {}
    event_data = (event_entry or {}).get("event_data") or {}

    client_name = (
        payload.get("client_name") or
        event_data.get("Name") or
        task.get("client_id", "Unknown Client")
    )
    client_email = (
        payload.get("recipient_email") or
        event_data.get("Email") or
        task.get("client_id", "")
    )

    # Get draft body
    draft_body = (
        payload.get("draft_body") or
        payload.get("draft_msg") or
        payload.get("draft_message") or
        ""
    )

    # If no draft in payload, try to get from pending_hil_requests
    if not draft_body and event_entry:
        for req in event_entry.get("pending_hil_requests", []):
            if req.get("task_id") == task_id:
                draft = req.get("draft") or {}
                draft_body = draft.get("body") or draft.get("body_markdown", "")
                break

    # Build event summary
    event_summary = None
    if event_entry:
        event_summary = {
            "chosen_date": event_entry.get("chosen_date"),
            "locked_room": event_entry.get("locked_room_id"),
            "offer_total": None,
            "line_items": [],
        }
        # Try to get offer total
        try:
            from backend.workflows.steps.step5_negotiation.trigger.step5_handler import _determine_offer_total
            event_summary["offer_total"] = _determine_offer_total(event_entry)
        except Exception:
            pass

    return send_hil_notification(
        task_id=task_id,
        task_type=task_type,
        client_name=client_name,
        client_email=client_email,
        draft_body=draft_body,
        event_summary=event_summary,
        event_id=task.get("event_id"),
    )
