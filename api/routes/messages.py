"""
MODULE: backend/api/routes/messages.py
PURPOSE: Message and conversation API endpoints.

ROUTES:
    POST /api/start-conversation              - Start a new conversation
    POST /api/send-message                    - Send message in conversation
    POST /api/conversation/{id}/confirm-date  - Confirm date selection
    POST /api/accept-booking/{id}             - Accept booking
    POST /api/reject-booking/{id}             - Reject booking
    GET  /api/conversation/{id}               - Get conversation state

MIGRATION: Extracted from main.py in Phase C refactoring (2025-12-18).
"""

import logging
import os
import re
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain import ConversationState, EventInformation
from legacy.session_store import (
    active_conversations,
    render_step3_reply,
    pop_step3_payload,
)
from core.fallback import wrap_fallback, create_fallback_context, SHOW_FALLBACK_DIAGNOSTICS
from adapters.calendar_adapter import get_calendar_adapter
from adapters.client_gui_adapter import ClientGUIAdapter
from workflows.common.payloads import PayloadValidationError, validate_confirm_date_payload
from workflows.steps.step2_date_confirmation import compose_date_confirmation_reply
from workflows.common.prompts import append_footer
from workflows.steps.step3_room_availability import run_availability_workflow
from utils import json_io
from workflow_email import (
    process_msg as wf_process_msg,
    load_db as wf_load_db,
    save_db as wf_save_db,
    DB_PATH as WF_DB_PATH,
)
from activity.progress import get_progress_summary

router = APIRouter(tags=["messages"])

# GUI adapter for availability workflow
GUI_ADAPTER = ClientGUIAdapter()

# DEPRECATED: Use WF_DB_PATH from workflow_email.py for canonical DB path
# Kept for backwards compatibility in response messages
EVENTS_FILE = str(WF_DB_PATH)


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class StartConversationRequest(BaseModel):
    email_body: str
    client_email: str


class SendMessageRequest(BaseModel):
    session_id: str
    message: str


class ConfirmDateRequest(BaseModel):
    date: Optional[str] = None


class ConversationResponse(BaseModel):
    session_id: str
    workflow_type: str
    response: str
    is_complete: bool
    event_info: dict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_PATTERN = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
CONFIRM_PHRASES = {
    "yes",
    "yes.",
    "yes!",
    "yes please",
    "yes please do",
    "yes it is",
    "yes that's fine",
    "yes thats fine",
    "yes confirm",
    "yes confirmed",
    "confirmed",
    "confirm",
    "sounds good",
    "that works",
    "perfect",
    "perfect thanks",
    "okay",
    "ok",
    "ok thanks",
    "great",
    "great thanks",
}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def load_events_database():
    """Load all events from the database file."""
    if WF_DB_PATH.exists():
        with open(WF_DB_PATH, 'r', encoding='utf-8') as f:
            return json_io.load(f)
    return {"events": []}


def save_events_database(database):
    """Save all events to the database file."""
    with open(WF_DB_PATH, 'w', encoding='utf-8') as f:
        json_io.dump(database, f, indent=2, ensure_ascii=False)


def _format_draft_text(draft: Dict[str, Any]) -> str:
    """Format draft message text from headers and body."""
    headers = [
        str(header).strip()
        for header in draft.get("headers") or []
        if str(header).strip()
    ]
    body = draft.get("body_markdown") or draft.get("body") or ""
    parts = headers + [body]
    return "\n\n".join(part for part in parts if part)


def _extract_workflow_reply(wf_res: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    """Extract assistant reply and actions from workflow result."""
    wf_action = wf_res.get("action")
    if wf_action in {
        "offer_accept_pending_hil",
        "negotiation_accept_pending_hil",
        "negotiation_hil_waiting",
        "offer_waiting_hil",
    }:
        waiting_text = (
            "Thanks for confirming! I'll review your booking details and get back to you shortly."
        )
        return waiting_text, wf_res.get("actions") or []

    # Check if HIL approval for ALL LLM replies is enabled - don't show message until approved
    res_meta = wf_res.get("res") or {}
    if res_meta.get("pending_hil_approval"):
        # Message is pending manager approval - return empty string (no chat message)
        # The frontend will show the task in the approval queue instead
        return "", wf_res.get("actions") or []

    drafts = wf_res.get("draft_messages") or []
    if drafts:
        draft = drafts[-1]
        text = _format_draft_text(draft)
        actions = draft.get("actions") or wf_res.get("actions") or []
    else:
        text = wf_res.get("assistant_message") or ""
        actions = wf_res.get("actions") or []

    # Append hybrid Q&A response if present (handles booking + Q&A in same message)
    # e.g., "Book room for April 5 + what menu options do you have?"
    # SKIP for pure_info_qna - the Q&A content is already in the draft message
    # SKIP for detour flows - Q&A should not be appended to date/room change responses
    # SKIP when workflow action already answers the Q&A (prevents redundant responses)
    # Mapping of workflow actions to Q&A they already answer:
    # - room_avail_result: rooms are shown, so room Q&A is redundant
    # - date_confirmed/date_time_clarification: date info shown, so date Q&A is redundant
    # - offer_generated: pricing shown, so pricing Q&A is redundant
    ACTIONS_THAT_ANSWER_QNA = {
        "room_avail_result",           # Step 3 shows room availability
        "room_selected",               # Step 3 shows room selection
        "offer_generated",             # Step 4 shows pricing/products
        "offer_sent",                  # Step 4 shows offer
    }
    is_pure_qna = wf_res.get("pure_info_qna", False)
    wf_action = wf_res.get("action", "")
    is_detour = wf_action in ("change_detour", "structural_change_detour")
    workflow_answers_qna = wf_action in ACTIONS_THAT_ANSWER_QNA
    hybrid_qna = wf_res.get("hybrid_qna_response")
    if hybrid_qna and text and not is_pure_qna and not is_detour and not workflow_answers_qna:
        text = text.strip() + "\n\n---\n\n" + hybrid_qna
    elif hybrid_qna and not is_pure_qna and not is_detour and not workflow_answers_qna:
        text = hybrid_qna

    return text.strip(), actions


def _merge_field(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    """Merge event field, preferring non-empty candidate."""
    if not candidate:
        return current
    candidate_str = str(candidate).strip()
    if not candidate_str or candidate_str.lower() == "not specified":
        return current
    return candidate_str


def _update_event_info_from_db(event_info: EventInformation, event_id: Optional[str]) -> EventInformation:
    """Update event info with latest data from database."""
    if not event_id:
        return event_info
    try:
        db = wf_load_db()
    except Exception as exc:
        logger.warning("Unable to refresh event info from DB: %s", exc)
        return event_info

    events = db.get("events") or []
    entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not entry:
        return event_info

    event_info.status = _merge_field(event_info.status, entry.get("status"))
    data = entry.get("event_data") or {}

    event_info.event_date = _merge_field(event_info.event_date, data.get("Event Date"))
    event_info.name = _merge_field(event_info.name, data.get("Name"))
    event_info.email = _merge_field(event_info.email, data.get("Email"))
    event_info.phone = _merge_field(event_info.phone, data.get("Phone"))
    event_info.company = _merge_field(event_info.company, data.get("Company"))
    event_info.billing_address = _merge_field(event_info.billing_address, data.get("Billing Address"))
    event_info.start_time = _merge_field(event_info.start_time, data.get("Start Time"))
    event_info.end_time = _merge_field(event_info.end_time, data.get("End Time"))
    event_info.preferred_room = _merge_field(event_info.preferred_room, data.get("Preferred Room"))
    event_info.number_of_participants = _merge_field(
        event_info.number_of_participants, data.get("Number of Participants")
    )
    event_info.type_of_event = _merge_field(event_info.type_of_event, data.get("Type of Event"))
    event_info.catering_preference = _merge_field(
        event_info.catering_preference, data.get("Catering Preference")
    )
    event_info.billing_amount = _merge_field(event_info.billing_amount, data.get("Billing Amount"))
    event_info.deposit = _merge_field(event_info.deposit, data.get("Deposit"))
    event_info.language = _merge_field(event_info.language, data.get("Language"))
    event_info.additional_info = _merge_field(event_info.additional_info, data.get("Additional Info"))

    requirements = entry.get("requirements") or {}
    participants_req = requirements.get("number_of_participants")
    if participants_req:
        event_info.number_of_participants = _merge_field(
            event_info.number_of_participants, str(participants_req)
        )

    return event_info


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def _to_iso_date(date_str: Optional[str]) -> Optional[str]:
    """Convert date string to ISO format (YYYY-MM-DD)."""
    if not date_str:
        return None
    text = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _format_participants_label(raw: Optional[str]) -> str:
    """Format participant count for display."""
    if not raw:
        return "your group"
    text = str(raw).strip()
    if not text or text.lower() in {"not specified", "none"}:
        return "your group"
    match = re.search(r"\d{1,4}", text)
    if match:
        try:
            number = int(match.group(0))
            if number > 0:
                return "1 guest" if number == 1 else f"{number} guests"
        except ValueError:
            pass
    return text


def _trigger_room_availability(event_id: Optional[str], chosen_date: str) -> Optional[str]:
    """Trigger room availability workflow after date confirmation.

    Returns:
        Error message if something failed, None if successful.
    """
    # Note: create_fallback_context imported at module level from core.fallback

    if not event_id:
        ctx = create_fallback_context(
            source="api.routes.messages.trigger_availability",
            trigger="missing_event_id",
        )
        logger.error("Fallback: %s | %s", ctx.source, ctx.trigger)
        return "I couldn't check room availability because the event record is missing."

    try:
        db = wf_load_db()
    except Exception as exc:
        ctx = create_fallback_context(
            source="api.routes.messages.trigger_availability",
            trigger="db_load_failed",
            event_id=event_id,
            error=exc,
        )
        logger.error("Fallback: %s | %s | %s", ctx.source, ctx.trigger, exc)
        return "I couldn't access the booking database. I've escalated this for manual follow-up."

    events = db.get("events", [])
    event_entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not event_entry:
        ctx = create_fallback_context(
            source="api.routes.messages.trigger_availability",
            trigger="event_not_found",
            event_id=event_id,
        )
        logger.error("Fallback: %s | %s | event_id=%s", ctx.source, ctx.trigger, event_id)
        return "I couldn't find the event record. I've asked a teammate to verify it manually."

    event_data = event_entry.setdefault("event_data", {})
    event_data["Status"] = "Date Confirmed"
    iso_date = _to_iso_date(chosen_date) or _to_iso_date(event_data.get("Event Date"))
    if iso_date:
        event_data["Event Date"] = iso_date

    logs = event_entry.setdefault("logs", [])
    if iso_date:
        for log in reversed(logs):
            if log.get("action") == "room_availability_assessed":
                details = log.get("details") or {}
                requested_days = details.get("requested_days") or []
                first_day = requested_days[0] if requested_days else None
                if first_day == iso_date:
                    wf_save_db(db)
                    logger.info("Availability already assessed for %s; skipping rerun", iso_date)
                    return None

    logs.append(
        {
            "ts": _now_iso(),
            "actor": "Platform",
            "action": "room_availability_triggered_after_date_confirm",
            "details": {"event_id": event_id},
        }
    )

    wf_save_db(db)

    try:
        # interactive=False to skip console input() - HIL toggle handles manager review
        run_availability_workflow(event_id, get_calendar_adapter(), GUI_ADAPTER, interactive=False)
        return None  # Success
    except Exception as exc:
        ctx = create_fallback_context(
            source="api.routes.messages.trigger_availability",
            trigger="workflow_failed",
            event_id=event_id,
            error=exc,
        )
        logger.error("Fallback: %s | %s | %s", ctx.source, ctx.trigger, exc)
        return "Room availability check encountered an issue. I'll follow up with availability options shortly."


def _persist_confirmed_date(conversation_state: ConversationState, chosen_date: str) -> Dict[str, Any]:
    """Persist confirmed date and trigger availability workflow."""
    # Note: create_fallback_context imported at module level from core.fallback

    conversation_state.event_info.event_date = chosen_date
    conversation_state.event_info.status = "Date Confirmed"

    # NOTE: AGENT_MODE is now set at startup in main.py with smart defaults
    # (hybrid if Gemini key present, openai-only otherwise)
    synthetic_msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Client (GUI)",
        "from_email": conversation_state.event_info.email,
        "subject": f"Confirmed event date {chosen_date}",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": f"The client confirms the preferred event date is {chosen_date}.",
    }

    # Track any fallback messages to append to the response
    fallback_notices: List[str] = []

    wf_res = {}
    try:
        wf_res = wf_process_msg(synthetic_msg)
        logger.info(
            "confirm_date action=%s event_id=%s intent=%s",
            wf_res.get('action'), wf_res.get('event_id'), wf_res.get('intent')
        )
    except Exception as exc:
        ctx = create_fallback_context(
            source="api.routes.messages.persist_confirmed_date",
            trigger="persistence_failed",
            event_id=conversation_state.event_id,
            error=exc,
        )
        logger.error("Fallback: %s | %s | %s", ctx.source, ctx.trigger, exc)
        fallback_notices.append(
            "I logged your confirmation, but our booking system didn't save the update. "
            "I've escalated it for manual follow-up."
        )

    event_id = wf_res.get("event_id") or conversation_state.event_id
    conversation_state.event_id = event_id

    iso_confirmed = _to_iso_date(chosen_date)
    if event_id and iso_confirmed:
        try:
            validate_confirm_date_payload({
                "action": "confirm_date",
                "event_id": event_id,
                "date": iso_confirmed,
            })
        except PayloadValidationError as exc:
            logger.warning("confirm_date payload validation failed: %s", exc)

    # Trigger availability and capture any error message
    availability_error = _trigger_room_availability(event_id, chosen_date)
    if availability_error:
        fallback_notices.append(availability_error)

    rendered = render_step3_reply(conversation_state, wf_res.get("draft_messages"))
    actions: List[Dict[str, Any]] = []
    subject: Optional[str] = None
    assistant_reply = wf_res.get("assistant_message")

    if rendered:
        subject = rendered.get("subject")
        actions = rendered.get("actions") or []
        assistant_reply = rendered.get("body_markdown") or rendered.get("body") or assistant_reply

    if not assistant_reply:
        pax_label = _format_participants_label(conversation_state.event_info.number_of_participants)
        assistant_reply = compose_date_confirmation_reply(chosen_date, pax_label)
        assistant_reply = append_footer(
            assistant_reply,
            step=3,
            next_step="Availability result",
            thread_state="Checking",
        )

    # Append any fallback notices to the response
    if fallback_notices:
        notice_text = "\n\n---\n\n" + "\n\n".join(fallback_notices)
        assistant_reply = (assistant_reply or "") + notice_text

    return {
        "body": assistant_reply,
        "actions": actions,
        "subject": subject,
    }


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------

@router.post("/api/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """Start a new conversation workflow."""
    # NOTE: AGENT_MODE is now set at startup in main.py with smart defaults
    subject_line = (request.email_body.splitlines()[0][:80] if request.email_body else "No subject")
    session_id = str(uuid.uuid4())
    msg = {
        "msg_id": str(uuid.uuid4()),
        "from_name": "Not specified",
        "from_email": request.client_email,
        "subject": subject_line,
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.email_body or "",
        "session_id": session_id,
        "thread_id": session_id,
    }
    wf_res = None
    wf_action = None
    try:
        wf_res = wf_process_msg(msg)
        wf_action = wf_res.get("action")
        logger.info("start action=%s client=%s event_id=%s task_id=%s",
                    wf_action, request.client_email, wf_res.get('event_id'), wf_res.get('task_id'))
    except Exception as e:
        logger.exception("start_conversation workflow failed: %s", e)
    if not wf_res:
        raise HTTPException(status_code=500, detail="Workflow processing failed")
    if wf_action == "manual_review_enqueued":
        response_text = (
            "Thanks for your message. We routed it for manual review and will get back to you shortly."
        )
        return {
            "session_id": None,
            "workflow_type": "other",
            "response": response_text,
            "is_complete": False,
            "event_info": None,
        }
    # Handle standalone Q&A (questions without existing event)
    if wf_action == "standalone_qna":
        draft_messages = wf_res.get("draft_messages", [])
        response_text = draft_messages[0].get("body", "") if draft_messages else ""
        return {
            "session_id": session_id,
            "workflow_type": "standalone_qna",
            "response": response_text,
            "is_complete": False,
            "event_info": None,
        }
    # [DEV TEST MODE] Return choice prompt when existing event detected
    # Note: payload fields are merged at top level by GroupResult.merged()
    if wf_action == "dev_choice_required":
        return {
            "session_id": session_id,
            "workflow_type": "dev_choice",
            "response": wf_res.get("message", "Existing event detected"),
            "is_complete": False,
            "event_info": None,
            "dev_choice": {
                "client_id": wf_res.get("client_id"),
                "event_id": wf_res.get("event_id"),
                "current_step": wf_res.get("current_step"),
                "step_name": wf_res.get("step_name"),
                "event_date": wf_res.get("event_date"),
                "locked_room": wf_res.get("locked_room"),
                "offer_accepted": wf_res.get("offer_accepted"),
                "options": wf_res.get("options", []),
            },
        }
    if wf_action == "ask_for_date_enqueued":
        event_info = EventInformation(
            date_email_received=datetime.now().strftime("%d.%m.%Y"),
            email=request.client_email,
        )
        user_info = (wf_res or {}).get("user_info") or {}
        if user_info.get("phone"):
            event_info.phone = str(user_info["phone"])
        if user_info.get("company"):
            event_info.company = str(user_info["company"])
        if user_info.get("language"):
            event_info.language = str(user_info["language"])
        if user_info.get("participants"):
            event_info.number_of_participants = str(user_info["participants"])
        if user_info.get("room"):
            event_info.preferred_room = str(user_info["room"])
        if user_info.get("type"):
            event_info.type_of_event = str(user_info["type"])
        if user_info.get("catering"):
            event_info.catering_preference = str(user_info["catering"])
        if user_info.get("start_time"):
            event_info.start_time = str(user_info["start_time"])
        if user_info.get("end_time"):
            event_info.end_time = str(user_info["end_time"])
        suggested_dates = (wf_res or {}).get("suggested_dates") or []
        dates_text = ", ".join(suggested_dates) if suggested_dates else "No specific dates yet."
        assistant_reply = (
            f"Hello,\n\nDo you already have a date in mind? Here are a few available dates: {dates_text}"
        )
        conversation_state = ConversationState(
            session_id=session_id,
            event_info=event_info,
            conversation_history=[
                {"role": "user", "content": request.email_body or ""},
                {"role": "assistant", "content": assistant_reply},
            ],
            workflow_type="new_event",
            event_id=(wf_res or {}).get("event_id"),
        )
        active_conversations[session_id] = conversation_state
        logger.info("start pause ask_for_date session=%s task=%s", session_id, wf_res.get('task_id'))
        return {
            "session_id": session_id,
            "workflow_type": "new_event",
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.model_dump(),
            "pending_actions": None,
        }

    workflow_type = "new_event"
    event_info = EventInformation(
        date_email_received=datetime.now().strftime("%d.%m.%Y"),
        email=request.client_email
    )
    event_id = (wf_res or {}).get("event_id")

    conversation_state = ConversationState(
        session_id=session_id,
        event_info=event_info,
        conversation_history=[],
        workflow_type=workflow_type,
        event_id=event_id,
    )

    conversation_state.conversation_history.append({"role": "user", "content": request.email_body or ""})

    assistant_reply, action_items = _extract_workflow_reply(wf_res)
    # Only use fallback message if reply is empty AND HIL approval is NOT pending
    res_meta = wf_res.get("res") or {}
    hil_pending = res_meta.get("pending_hil_approval", False)
    if not assistant_reply and not hil_pending:
        # DIAGNOSTIC: Log what wf_res contained so we can debug recurring fallbacks
        logger.warning(
            "start_conversation empty reply: action=%s drafts=%d has_assistant=%s event_id=%s",
            wf_res.get('action'),
            len(wf_res.get('draft_messages') or []),
            bool(wf_res.get('assistant_message')),
            wf_res.get('event_id')
        )

        # Create diagnostic fallback context
        fallback_ctx = create_fallback_context(
            source="api.routes.messages.start_conversation",
            trigger="empty_workflow_reply",
            event_id=wf_res.get("event_id"),
            thread_id=session_id,
            action=wf_res.get("action"),
            draft_count=len(wf_res.get("draft_messages") or []),
            has_assistant_msg=bool(wf_res.get("assistant_message")),
        )
        assistant_reply = wrap_fallback(
            "Thanks for your message. I'll follow up shortly with availability details.",
            fallback_ctx
        )

    conversation_state.event_id = wf_res.get("event_id") or event_id
    conversation_state.event_info = _update_event_info_from_db(conversation_state.event_info, conversation_state.event_id)
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    active_conversations[session_id] = conversation_state

    pending_actions = {"type": "workflow_actions", "actions": action_items} if action_items else None

    return {
        "session_id": session_id,
        "workflow_type": workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump(),
        "pending_actions": pending_actions,
    }


@router.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """Send a message in an existing conversation."""
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[request.session_id]

    # Handle workflow continuation after source_missing_product approval
    # This is a system-triggered message, not a real client message
    is_continuation = request.message == "[CONTINUE_AFTER_SOURCING]"
    if is_continuation:
        # Don't add the system marker to conversation history
        # Use a marker that won't trigger offer acceptance detection
        # Step 3 will detect sourced_products and advance to offer generation
        actual_message = "[SYSTEM_OFFER_GENERATION]"
    else:
        actual_message = request.message
        # NOTE: Removed redundant extract_information_incremental() call (Dec 2025)
        # It was making a separate gpt-4o-mini API call that updated in-memory state
        # but didn't persist to the workflow database. The workflow's own detection
        # in step1_handler.py handles all entity extraction properly.
        conversation_state.conversation_history.append({"role": "user", "content": request.message})

    payload = {
        "msg_id": str(uuid.uuid4()),
        "from_name": conversation_state.event_info.name or "Client",
        "from_email": conversation_state.event_info.email,
        "subject": f"Client follow-up ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')})",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": actual_message,
        "thread_id": request.session_id,
        "session_id": request.session_id,
        "is_continuation": is_continuation,  # Flag for workflow to handle specially
    }

    try:
        wf_res = wf_process_msg(payload)
    except Exception as exc:
        logger.exception("send_message workflow failed: %s", exc)

        # Detect critical API/infrastructure errors that should ALWAYS be visible
        # These are not workflow logic fallbacks - they're system failures
        error_str = str(exc).lower()
        error_type = type(exc).__name__

        is_critical_api_error = any([
            "billing" in error_str,
            "account is not active" in error_str,
            "authentication" in error_str,
            "api_key" in error_str,
            "invalid_api_key" in error_str,
            "quota" in error_str and "exceeded" in error_str,
            error_type in ("AuthenticationError", "RateLimitError", "APIConnectionError"),
        ])

        if is_critical_api_error:
            # CRITICAL: Surface API errors explicitly in dev; keep prod safe.
            fallback_ctx = create_fallback_context(
                source="api.routes.messages.send_message",
                trigger="workflow_exception",
                thread_id=request.session_id,
                event_id=conversation_state.event_id,
                error=exc,
                message_preview=request.message[:50] if request.message else None,
                error_category="critical_api_error",
            )
            env_value = os.getenv("ENV", "prod").lower()
            is_dev_env = env_value in ("dev", "development", "local")
            if SHOW_FALLBACK_DIAGNOSTICS:
                base_message = (
                    "System error: LLM provider request failed. "
                    "See diagnostics for details."
                )
            elif is_dev_env:
                base_message = (
                    "System error: LLM provider request failed.\n\n"
                    f"{error_type}: {exc}"
                )
            else:
                base_message = (
                    "System error: The system cannot process your message right now. "
                    "Please contact support."
                )
            assistant_reply = wrap_fallback(base_message, fallback_ctx)
            logger.critical("CRITICAL API ERROR (surfaced): %s: %s", error_type, exc)
        else:
            # Regular workflow exception - use standard fallback with diagnostics
            fallback_ctx = create_fallback_context(
                source="api.routes.messages.send_message",
                trigger="workflow_exception",
                thread_id=request.session_id,
                event_id=conversation_state.event_id,
                error=exc,
                message_preview=request.message[:50] if request.message else None,
            )
            assistant_reply = wrap_fallback(
                "Thanks for the update. I'll follow up shortly with the latest availability.",
                fallback_ctx
            )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    wf_action = wf_res.get("action")
    if wf_action == "manual_review_enqueued":
        assistant_reply = (
            "Thanks for your message. We routed it for manual review and will get back to you shortly."
        )
        conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
        conversation_state.event_info = _update_event_info_from_db(
            conversation_state.event_info,
            conversation_state.event_id,
        )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    if wf_action == "ask_for_date_enqueued":
        suggested_dates = (wf_res or {}).get("suggested_dates") or []
        dates_text = ", ".join(suggested_dates) if suggested_dates else "No specific dates yet."
        assistant_reply = (
            f"Hello again,\n\nHere are the next available dates that fit your window: {dates_text}"
        )
        conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
        conversation_state.event_info = _update_event_info_from_db(
            conversation_state.event_info,
            conversation_state.event_id,
        )
        conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
        return {
            "session_id": request.session_id,
            "workflow_type": conversation_state.workflow_type,
            "response": assistant_reply,
            "is_complete": conversation_state.is_complete,
            "event_info": conversation_state.event_info.dict(),
            "pending_actions": None,
        }

    assistant_reply, action_items = _extract_workflow_reply(wf_res)
    # Only use fallback message if reply is empty AND HIL approval is NOT pending
    res_meta = wf_res.get("res") or {}
    hil_pending = res_meta.get("pending_hil_approval", False)

    # NOTE: Silent actions (out_of_context_ignored, nonsense_ignored) were removed in F-04 fix.
    # These now return helpful guidance messages via out_of_context_guided/nonsense_guided actions.
    # The normal flow below processes their draft messages and returns them to the user.

    if not assistant_reply and not hil_pending:
        # Create diagnostic fallback context for empty workflow reply
        fallback_ctx = create_fallback_context(
            source="api.routes.messages.send_message",
            trigger="empty_workflow_reply",
            thread_id=request.session_id,
            event_id=wf_res.get("event_id") or conversation_state.event_id,
            action=wf_res.get("action"),
            draft_count=len(wf_res.get("draft_messages") or []),
            has_assistant_msg=bool(wf_res.get("assistant_message")),
            current_step=wf_res.get("current_step"),
        )
        assistant_reply = wrap_fallback(
            "Thanks for the update. I'll keep you posted as I gather the details.",
            fallback_ctx
        )

    # Only apply step3_payload override if HIL is NOT pending
    if not hil_pending:
        step3_payload = pop_step3_payload(request.session_id)
        if step3_payload:
            body_pref = step3_payload.get("body_markdown") or step3_payload.get("body")
            if body_pref:
                assistant_reply = body_pref
            actions_override = step3_payload.get("actions") or []
            if actions_override:
                action_items = actions_override

    conversation_state.event_id = wf_res.get("event_id") or conversation_state.event_id
    conversation_state.event_info = _update_event_info_from_db(
        conversation_state.event_info,
        conversation_state.event_id,
    )
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})

    pending_actions = {"type": "workflow_actions", "actions": action_items} if action_items else None

    # Include deposit_info and progress from the event for frontend
    # IMPORTANT: Only send deposit_info at Step 4+ (after offer is generated with pricing)
    deposit_info = None
    progress = None
    if conversation_state.event_id:
        try:
            db = wf_load_db()
            for event in db.get("events") or []:
                if event.get("event_id") == conversation_state.event_id:
                    current_step = event.get("current_step", 1)

                    # Progress bar data (always included)
                    progress = get_progress_summary(event)

                    # Only include deposit info at Step 4+ (after room selection and offer generation)
                    if current_step >= 4:
                        raw_deposit = event.get("deposit_info")
                        if raw_deposit and raw_deposit.get("deposit_required"):
                            deposit_info = {
                                "deposit_required": raw_deposit.get("deposit_required", False),
                                "deposit_amount": raw_deposit.get("deposit_amount"),
                                "deposit_due_date": raw_deposit.get("deposit_due_date"),
                                "deposit_paid": raw_deposit.get("deposit_paid", False),
                                "offer_accepted": bool(event.get("offer_accepted")),
                                "event_id": conversation_state.event_id,
                            }
                    break
        except Exception:
            pass

    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "assistant_reply": assistant_reply,  # Alias for frontend continuation flow
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": pending_actions,
        "deposit_info": deposit_info,
        "progress": progress,  # Workflow progress bar state
    }


@router.post("/api/conversation/{session_id}/confirm-date")
async def confirm_date(session_id: str, request: ConfirmDateRequest):
    """Confirm the selected date for an event."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[session_id]
    raw_date = (request.date or conversation_state.event_info.event_date or "").strip()
    iso_candidate = _to_iso_date(raw_date)
    if not iso_candidate:
        raise HTTPException(status_code=400, detail="Invalid or missing date. Use YYYY-MM-DD.")
    try:
        chosen_date = datetime.strptime(iso_candidate, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid or missing date. Use YYYY-MM-DD.") from exc

    assistant_payload = _persist_confirmed_date(conversation_state, chosen_date)
    assistant_reply = assistant_payload.get("body") or ""
    actions = assistant_payload.get("actions") or []
    conversation_state.conversation_history.append({"role": "assistant", "content": assistant_reply})
    pending_actions = {"type": "workflow_actions", "actions": actions} if actions else None

    return {
        "session_id": session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": assistant_reply,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.dict(),
        "pending_actions": pending_actions,
    }


@router.post("/api/accept-booking/{session_id}")
async def accept_booking(session_id: str):
    """Accept and save the booking to the database."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[session_id]

    # Load existing database
    database = load_events_database()

    # Add new event with unique ID and timestamp
    event_entry = {
        "event_id": session_id,
        "created_at": datetime.now().isoformat(),
        "event_data": conversation_state.event_info.to_dict()
    }

    database["events"].append(event_entry)

    # Save back to file
    save_events_database(database)

    # Clean up conversation
    del active_conversations[session_id]

    return {
        "message": "Booking accepted and saved",
        "filename": EVENTS_FILE,
        "event_id": session_id,
        "total_events": len(database["events"]),
        "event_info": conversation_state.event_info.to_dict()
    }


@router.post("/api/reject-booking/{session_id}")
async def reject_booking(session_id: str):
    """Reject and discard the booking."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Just remove from memory
    del active_conversations[session_id]

    return {"message": "Booking rejected and discarded"}


@router.get("/api/conversation/{session_id}")
async def get_conversation(session_id: str):
    """Get the current conversation state."""
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_state = active_conversations[session_id]

    return {
        "session_id": session_id,
        "conversation_history": conversation_state.conversation_history,
        "event_info": conversation_state.event_info.dict(),
        "is_complete": conversation_state.is_complete
    }
