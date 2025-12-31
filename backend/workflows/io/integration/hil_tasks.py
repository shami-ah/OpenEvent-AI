"""
Human-in-the-Loop (HIL) task templates for Supabase integration.

CRITICAL MVP REQUIREMENT: Every AI-generated message MUST be approved
by an Event Manager before being sent to a client.

This module provides templates for creating HIL approval tasks in Supabase.

Based on EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md - HIL section.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.workflows.io.config_store import get_timezone


def _get_venue_tz() -> ZoneInfo:
    """Return venue timezone as ZoneInfo from config."""
    return ZoneInfo(get_timezone())


# =============================================================================
# Task Categories (must match frontend expectations)
# =============================================================================

class TaskCategory:
    """Task categories as defined in the frontend."""
    EVENT_TASKS = "Event Tasks"
    EMAIL_TASKS = "Email Tasks"
    CLIENT_FOLLOWUPS = "Client Follow-ups"
    INVOICE_TASKS = "Invoice Tasks"
    # NEW: Separate category for AI reply approval (when OE_HIL_ALL_LLM_REPLIES=true)
    # This keeps AI replies separate from client-initiated tasks
    AI_REPLY_TASKS = "AI Reply Approval"


class TaskPriority:
    """Task priorities."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# =============================================================================
# HIL Action Types
# =============================================================================

class HILAction:
    """HIL action types for different approval workflows."""
    APPROVE_MESSAGE = "approve_message"
    APPROVE_OFFER = "approve_offer"
    APPROVE_DATE = "approve_date"
    APPROVE_ROOM = "approve_room"
    APPROVE_PRODUCTS = "approve_products"
    MANUAL_REVIEW = "manual_review"
    CONFIRM_EVENT = "confirm_event"
    # NEW: AI reply approval (when OE_HIL_ALL_LLM_REPLIES=true)
    APPROVE_AI_REPLY = "approve_ai_reply"


# =============================================================================
# Task Template Builders
# =============================================================================

def create_message_approval_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    client_email: str,
    draft_message: str,
    subject: Optional[str] = None,
    priority: str = TaskPriority.HIGH,
) -> Dict[str, Any]:
    """
    Create a task for approving an AI-generated message.

    This is the CORE HIL requirement - every AI draft goes through this.

    Args:
        team_id: Team UUID
        user_id: System user UUID (who created the task)
        event_id: Event UUID this message relates to
        client_name: Name of the client
        client_email: Email of the client
        draft_message: The AI-generated message text
        subject: Email subject line
        priority: Task priority (default: high)

    Returns:
        Task record ready for Supabase insertion
    """
    return {
        "title": f"Approve message to {client_name}",
        "description": "Review and approve AI-generated message before sending to client.",
        "category": TaskCategory.EMAIL_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.APPROVE_MESSAGE,
            "draft_message": draft_message,
            "subject": subject,
            "recipient_email": client_email,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_offer_approval_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    offer_summary: Dict[str, Any],
    priority: str = TaskPriority.HIGH,
) -> Dict[str, Any]:
    """
    Create a task for approving an offer before sending.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        event_id: Event UUID
        client_name: Client name
        offer_summary: Summary of the offer (total, items, etc.)
        priority: Task priority

    Returns:
        Task record ready for Supabase insertion
    """
    total = offer_summary.get("total_amount", 0)

    return {
        "title": f"Approve offer for {client_name} (CHF {total:,.2f})",
        "description": "Review and approve offer before sending to client.",
        "category": TaskCategory.EVENT_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.APPROVE_OFFER,
            "offer_summary": offer_summary,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_date_confirmation_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    proposed_dates: List[str],
    priority: str = TaskPriority.MEDIUM,
) -> Dict[str, Any]:
    """
    Create a task for confirming date options.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        event_id: Event UUID
        client_name: Client name
        proposed_dates: List of proposed dates (ISO format)
        priority: Task priority

    Returns:
        Task record ready for Supabase insertion
    """
    dates_display = ", ".join(proposed_dates[:3])

    return {
        "title": f"Confirm dates for {client_name}",
        "description": f"Review proposed dates: {dates_display}",
        "category": TaskCategory.EVENT_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.APPROVE_DATE,
            "proposed_dates": proposed_dates,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_room_approval_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    room_name: str,
    room_status: str,
    conflict_info: Optional[Dict[str, Any]] = None,
    priority: str = TaskPriority.MEDIUM,
) -> Dict[str, Any]:
    """
    Create a task for approving room selection.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        event_id: Event UUID
        client_name: Client name
        room_name: Selected room name
        room_status: Room availability status
        conflict_info: Any conflict information
        priority: Task priority

    Returns:
        Task record ready for Supabase insertion
    """
    title = f"Approve room '{room_name}' for {client_name}"
    if conflict_info:
        title = f"CONFLICT: {title}"
        priority = TaskPriority.HIGH

    return {
        "title": title,
        "description": f"Room status: {room_status}",
        "category": TaskCategory.EVENT_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.APPROVE_ROOM,
            "room_name": room_name,
            "room_status": room_status,
            "conflict_info": conflict_info,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_manual_review_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    reason: str,
    context: Dict[str, Any],
    priority: str = TaskPriority.HIGH,
) -> Dict[str, Any]:
    """
    Create a task for manual review (escalation).

    Used when the AI cannot handle a situation automatically.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        event_id: Event UUID
        client_name: Client name
        reason: Why manual review is needed
        context: Relevant context for the reviewer
        priority: Task priority

    Returns:
        Task record ready for Supabase insertion
    """
    return {
        "title": f"Manual review needed: {client_name}",
        "description": reason,
        "category": TaskCategory.EVENT_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.MANUAL_REVIEW,
            "reason": reason,
            "context": context,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_confirmation_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    event_details: Dict[str, Any],
    requires_deposit: bool = False,
    deposit_amount: Optional[float] = None,
    priority: str = TaskPriority.HIGH,
) -> Dict[str, Any]:
    """
    Create a task for final event confirmation.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        event_id: Event UUID
        client_name: Client name
        event_details: Summary of event details
        requires_deposit: Whether deposit is required
        deposit_amount: Deposit amount if required
        priority: Task priority

    Returns:
        Task record ready for Supabase insertion
    """
    title = f"Confirm event for {client_name}"
    if requires_deposit:
        title = f"{title} (Deposit: CHF {deposit_amount:,.2f})"

    return {
        "title": title,
        "description": "Review and confirm final event booking.",
        "category": TaskCategory.EVENT_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.CONFIRM_EVENT,
            "event_details": event_details,
            "requires_deposit": requires_deposit,
            "deposit_amount": deposit_amount,
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


def create_ai_reply_approval_task(
    team_id: str,
    user_id: str,
    event_id: str,
    client_name: str,
    client_email: str,
    draft_message: str,
    workflow_step: int,
    context: Optional[Dict[str, Any]] = None,
    priority: str = TaskPriority.HIGH,
) -> Dict[str, Any]:
    """
    Create a task for approving an AI-generated reply (when toggle is ON).

    This is used when OE_HIL_ALL_LLM_REPLIES=true to require manager approval
    for ALL AI-generated outbound messages before they are sent to clients.

    This task goes to a SEPARATE category "AI Reply Approval" to keep it
    distinct from client-initiated tasks like offer approvals.

    Args:
        team_id: Team UUID
        user_id: System user UUID (who created the task)
        event_id: Event UUID this reply relates to
        client_name: Name of the client
        client_email: Email of the client
        draft_message: The AI-generated reply text
        workflow_step: Current workflow step (1-7)
        context: Additional context (event status, etc.)
        priority: Task priority (default: high)

    Returns:
        Task record ready for insertion (JSON or Supabase)
    """
    step_names = {
        1: "Intake",
        2: "Date Confirmation",
        3: "Room Availability",
        4: "Offer",
        5: "Negotiation",
        6: "Transition",
        7: "Confirmation",
    }
    step_name = step_names.get(workflow_step, f"Step {workflow_step}")

    return {
        "title": f"Review AI reply to {client_name} ({step_name})",
        "description": f"Review and optionally edit AI-generated reply before sending. Step: {step_name}",
        "category": TaskCategory.AI_REPLY_TASKS,
        "priority": priority,
        "team_id": team_id,
        "user_id": user_id,
        "event_id": event_id,
        "client_name": client_name,
        "status": "pending",
        "payload": {
            "action": HILAction.APPROVE_AI_REPLY,
            "draft_message": draft_message,
            "recipient_email": client_email,
            "workflow_step": workflow_step,
            "step_name": step_name,
            "context": context or {},
            "editable": True,  # Manager can edit before approving
            "created_at": datetime.now(_get_venue_tz()).isoformat(),
        },
    }


# =============================================================================
# Task Resolution Helpers
# =============================================================================

def mark_task_completed(task: Dict[str, Any], resolution: str = "approved") -> Dict[str, Any]:
    """
    Mark a task as completed with resolution.

    Args:
        task: Task record
        resolution: Resolution status (approved, rejected, etc.)

    Returns:
        Updated task record
    """
    task["status"] = "completed"
    task["completed_at"] = datetime.now(_get_venue_tz()).isoformat()
    if "payload" not in task:
        task["payload"] = {}
    task["payload"]["resolution"] = resolution
    return task


def extract_approved_message(task: Dict[str, Any]) -> Optional[str]:
    """
    Extract the approved message from a completed task.

    The manager may have edited the draft before approving.

    Args:
        task: Completed task record

    Returns:
        Final message text (edited or original)
    """
    payload = task.get("payload", {})

    # Check for edited version first
    if payload.get("edited_message"):
        return payload["edited_message"]

    # Fall back to original draft
    return payload.get("draft_message")


# =============================================================================
# Email Record Helper
# =============================================================================

def create_email_record(
    team_id: str,
    user_id: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    event_id: Optional[str] = None,
    client_id: Optional[str] = None,
    is_sent: bool = False,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create an email record for Supabase storage.

    Args:
        team_id: Team UUID
        user_id: System user UUID
        from_email: Sender email
        to_email: Recipient email
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body (optional)
        event_id: Linked event UUID (optional)
        client_id: Linked client UUID (optional)
        is_sent: True for outgoing, False for incoming
        thread_id: Email thread ID for conversation grouping

    Returns:
        Email record ready for Supabase insertion
    """
    return {
        "team_id": team_id,
        "user_id": user_id,
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "event_id": event_id,
        "client_id": client_id,
        "is_sent": is_sent,
        "thread_id": thread_id,
        "received_at": datetime.now(_get_venue_tz()).isoformat() if not is_sent else None,
    }