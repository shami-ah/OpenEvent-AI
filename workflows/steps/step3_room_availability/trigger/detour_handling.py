"""
Step 3 Detour Handling Module.

Handles workflow detours and redirects from Step 3 (Room Availability).
Extracted from step3_handler.py as part of god-file refactoring (Jan 2026).

This module contains:
- Date detour (redirect to Step 2 for date confirmation)
- Capacity detour (request attendee count)
- Room evaluation skip (cache hit)
- Capacity exceeded handling

Detour Pattern:
- Set caller_step to preserve return path
- Add self-contained draft message (ensures client gets a response)
- Return with halt=True to prevent further processing

Usage:
    from .detour_handling import (
        detour_to_date,
        detour_for_capacity,
        skip_room_evaluation,
        handle_capacity_exceeded,
    )
"""
from __future__ import annotations

import logging
from typing import Optional

from workflows.common.prompts import append_footer
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import append_audit_entry, update_event_metadata
from workflow.state import WorkflowStep
from debug.hooks import trace_detour
from workflows.qna.router import generate_hybrid_qna_response
from workflows.common.detection_utils import get_unified_detection

from .constants import ROOM_OUTCOME_CAPACITY_EXCEEDED
from .selection import _thread_id, _format_display_date

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Date Detour
# -----------------------------------------------------------------------------


def detour_to_date(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Redirect to Step 2 when no chosen date exists.

    This function is self-contained: it adds a draft message explaining that
    we need the date confirmed before checking room availability. This ensures
    a response is always generated, even when the original message was about
    room selection (which Step 2 wouldn't know how to handle).
    """
    target_step = WorkflowStep.STEP_2
    current_step = WorkflowStep.STEP_3

    thread_id = _thread_id(state)
    trace_detour(
        thread_id,
        "Step3_Room",
        "Step2_Date",
        "date_confirmed_missing",
        {"date_confirmed": event_entry.get("date_confirmed")},
    )
    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=current_step.numeric)
    update_event_metadata(
        event_entry,
        current_step=target_step.numeric,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
    )
    append_audit_entry(event_entry, current_step.numeric, target_step.numeric, "room_requires_confirmed_date")
    state.current_step = target_step.numeric
    state.caller_step = current_step.numeric
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True

    # Add draft message explaining we need date confirmation first
    guidance = (
        "Thank you for your interest! Before I can check room availability, "
        "I need to confirm your preferred event date. "
        "Could you please let me know which date works best for you?"
    )
    state.add_draft_message({
        "body_markdown": guidance,
        "topic": "date_confirmation_required",
    })

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "date_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    # halt=True since we're providing a response (self-contained detour pattern)
    return GroupResult(action="room_detour_date", payload=payload, halt=True)


# -----------------------------------------------------------------------------
# Capacity Detour
# -----------------------------------------------------------------------------


def detour_for_capacity(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Ask for attendee count when missing, stay at Step 3.

    Instead of detouring to Step 1 (which has no handler in the routing loop),
    we generate a response asking for capacity and stay at Step 3. When the
    client responds with capacity, intake will extract it and routing will
    return to Step 3 for room evaluation.
    """
    thread_id = _thread_id(state)
    trace_detour(
        thread_id,
        "Step3_Room",
        "Step3_Room",  # Stay at Step 3
        "capacity_missing",
        {},
    )

    # Generate message asking for participant count
    draft_body = append_footer(
        "To find the best room for your event, I need to know how many people will be attending. "
        "Could you please share the expected number of participants?",
        step=3,
        next_step=3,
        thread_state="Awaiting Client",
    )
    draft = {
        "body": draft_body,
        "body_markdown": draft_body,
        "topic": "capacity_request",
        "requires_approval": False,
    }
    state.add_draft_message(draft)

    # Stay at Step 3, waiting for capacity
    update_event_metadata(
        event_entry,
        current_step=3,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 3, "room_requires_capacity")
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "capacity_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    # halt=True so the draft message is returned to the client
    return GroupResult(action="room_detour_capacity", payload=payload, halt=True)


# -----------------------------------------------------------------------------
# Time Slot Detour
# -----------------------------------------------------------------------------


def detour_for_time_slot(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Ask for time slot when missing, stay at Step 3.

    Time slot (start_time/end_time) is mandatory before showing room availability
    because room availability depends on the time window - a room might be
    available in the morning but booked in the afternoon.

    If the client also asked about rooms (hybrid Q&A), include room info in response.
    """
    thread_id = _thread_id(state)
    trace_detour(
        thread_id,
        "Step3_Room",
        "Step3_Room",  # Stay at Step 3
        "time_slot_missing",
        {},
    )

    # Check for hybrid Q&A - if client asked about rooms, include that info
    hybrid_qna_part = ""
    unified_detection = get_unified_detection(state)
    if unified_detection:
        is_question = getattr(unified_detection, "is_question", False)
        qna_types = getattr(unified_detection, "qna_types", None) or []
        # Check if asking about rooms/availability - use actual qna_type names from unified detection
        room_qna_types = [t for t in qna_types if t in (
            "check_availability", "free_dates", "room_features", "check_capacity"
        )]
        if is_question and room_qna_types:
            # Generate room Q&A response
            qna_response = generate_hybrid_qna_response(
                qna_types=room_qna_types,
                message_text=state.message.body or "",
                event_entry=event_entry,
                db=state.db,
            )
            if qna_response:
                hybrid_qna_part = f"\n\n{qna_response}"
                logger.debug("[TIME_SLOT_DETOUR] Including hybrid Q&A for types: %s", room_qna_types)

    # Generate message asking for time slot
    base_message = (
        "To check room availability, I also need to know your preferred time window. "
        "What time would your event start and end? For example: 9am to 5pm, or morning/afternoon."
    )
    full_message = base_message + hybrid_qna_part
    draft_body = append_footer(
        full_message,
        step=3,
        next_step=3,
        thread_state="Awaiting Client",
    )
    draft = {
        "body": draft_body,
        "body_markdown": draft_body,
        "topic": "time_slot_request",
        "requires_approval": False,
    }
    state.add_draft_message(draft)

    # Stay at Step 3, waiting for time slot
    update_event_metadata(
        event_entry,
        current_step=3,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 3, "room_requires_time_slot")
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "time_slot_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    # halt=True so the draft message is returned to the client
    return GroupResult(action="room_detour_time_slot", payload=payload, halt=True)


# -----------------------------------------------------------------------------
# Room Evaluation Skip (Cache Hit)
# -----------------------------------------------------------------------------


def skip_room_evaluation(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Skip Step 3 and return to the caller when caching allows."""
    caller = event_entry.get("caller_step")
    logger.debug("[Step3] skip_room_evaluation caller_step=%s", caller)

    # CRITICAL: If offer_hash is None, we MUST go through Step 4 to regenerate the offer
    # This happens after date changes - the offer shows the date, so it must be updated
    # Don't skip directly to caller (e.g., Step 5) without regenerating the offer first
    needs_offer_regen = event_entry.get("offer_hash") is None and caller and caller >= 4

    if caller is not None and not needs_offer_regen:
        append_audit_entry(event_entry, 3, caller, "room_eval_cache_hit")
        update_event_metadata(event_entry, current_step=caller, caller_step=None)
        state.current_step = caller
        state.caller_step = None
        logger.debug("[Step3] skip_room_evaluation -> returning to caller step %s", caller)
    elif needs_offer_regen:
        # Date changed - must regenerate offer even though room is still available
        # Route to Step 4, but preserve caller_step so Step 4 knows to return there after
        logger.info("[Step3] skip_room_evaluation -> routing to Step 4 for offer regeneration (caller=%s)", caller)
        append_audit_entry(event_entry, 3, 4, "offer_regen_required_after_date_change")
        update_event_metadata(event_entry, current_step=4)  # Keep caller_step so we return there after
        state.current_step = 4
        # Don't clear caller_step - Step 4/5 will use it to return after offer is regenerated
    else:
        # No caller - proceeding to step 4 (offer), update current_step so product detection works
        logger.warning("[Step3] NO CALLER - updating current_step to 4 for product detection")
        # IMPORTANT: Update room_eval_hash to match requirements_hash stored in event
        # Step 4's P2 gate compares event["room_eval_hash"] with event["requirements_hash"]
        # So we just copy the stored requirements_hash to room_eval_hash
        stored_req_hash = event_entry.get("requirements_hash")
        logger.debug("[Step3] Setting room_eval_hash to stored requirements_hash=%s, locked_room_id=%s",
                     stored_req_hash, event_entry.get('locked_room_id'))
        update_event_metadata(event_entry, current_step=4, room_eval_hash=stored_req_hash)
        # Also update the event_entry directly to ensure it's set
        event_entry["room_eval_hash"] = stored_req_hash
        state.current_step = 4
        logger.debug("[Step3] skip_room_evaluation -> advancing to step 4")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "cached": True,
        "thread_state": event_entry.get("thread_state"),
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_eval_skipped", payload=payload, halt=False)


# -----------------------------------------------------------------------------
# Capacity Exceeded Handling
# -----------------------------------------------------------------------------


def handle_capacity_exceeded(
    state: WorkflowState,
    event_entry: dict,
    participants: int,
    max_capacity: int,
    chosen_date: Optional[str],
) -> GroupResult:
    """
    Handle the case where requested capacity exceeds all available rooms.

    Per workflow spec S3_Unavailable:
    - Verbalize unavailability
    - Propose capacity change (reduce to fit largest room)
    - Offer alternatives (split event, external venue)
    """
    from workflows.common.prompts import verbalize_draft_body

    display_date = _format_display_date(chosen_date) if chosen_date else "your requested date"

    # Build core facts for verbalizer
    body_lines = [
        f"[CAPACITY_LIMIT] Client requested {participants} guests.",
        f"Maximum venue capacity is {max_capacity} guests (Room E).",
        f"Event date: {display_date}.",
        "",
        "OPTIONS:",
        f"1. Reduce to {max_capacity} or fewer guests",
        "2. Try a different date (some rooms may have higher capacity on other days)",
        "3. Split into two sessions/time slots",
        "4. External venue partnership for larger groups",
        "",
        "ASK: Which option works best, or provide updated guest count.",
    ]
    raw_body = "\n".join(body_lines)

    # Verbalize to professional, warm message
    body_markdown = verbalize_draft_body(
        raw_body,
        step=3,
        topic="capacity_exceeded",
        event_date=display_date,
        participants_count=participants,
        rooms=[],  # No rooms available
        room_name=None,
        room_status=ROOM_OUTCOME_CAPACITY_EXCEEDED,
    )

    # Log and audit
    append_audit_entry(event_entry, 3, 3, "capacity_exceeded", {
        "requested": participants,
        "max_available": max_capacity,
    })
    logger.debug("[Step3][CAPACITY_EXCEEDED] Generated response for %d guests (max: %d)",
                participants, max_capacity)

    # Update state - stay at Step 3 awaiting client response
    state.extras["persist"] = True
    state.extras["capacity_exceeded"] = True

    # Build actions for frontend
    actions_payload = [
        {
            "type": "reduce_capacity",
            "label": f"Proceed with {max_capacity} guests",
            "capacity": max_capacity,
        },
        {
            "type": "change_date",
            "label": "Try a different date",
            "detour_to_step": 2,
        },
        {
            "type": "contact_manager",
            "label": "Discuss alternatives with manager",
        },
    ]

    draft_message = {
        "body": body_markdown,
        "body_markdown": body_markdown,
        "step": 3,
        "next_step": "Capacity confirmation",
        "thread_state": "Awaiting Client",
        "topic": "capacity_exceeded",
        "room": None,
        "status": ROOM_OUTCOME_CAPACITY_EXCEEDED,
        "table_blocks": [],
        "actions": actions_payload,
        "headers": ["Capacity exceeded"],
        "requires_approval": False,
        "created_at_step": 3,
    }

    # Add draft to state (standard pattern for all step handlers)
    state.add_draft_message(draft_message)

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "draft_messages": state.draft_messages,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "persisted": True,
        "thread_state": "Awaiting Client",
        "context": state.context_snapshot,
        "capacity_exceeded": True,
        "requested_capacity": participants,
        "max_capacity": max_capacity,
    }
    return GroupResult(action="capacity_exceeded", payload=payload, halt=True)


# -----------------------------------------------------------------------------
# Backwards compatibility aliases (underscore prefix)
# -----------------------------------------------------------------------------

_detour_to_date = detour_to_date
_detour_for_capacity = detour_for_capacity
_skip_room_evaluation = skip_room_evaluation
_handle_capacity_exceeded = handle_capacity_exceeded
_detour_for_time_slot = detour_for_time_slot


__all__ = [
    # Main functions
    "detour_to_date",
    "detour_for_capacity",
    "detour_for_time_slot",
    "skip_room_evaluation",
    "handle_capacity_exceeded",
    # Backwards compat aliases
    "_detour_to_date",
    "_detour_for_capacity",
    "_detour_for_time_slot",
    "_skip_room_evaluation",
    "_handle_capacity_exceeded",
]
