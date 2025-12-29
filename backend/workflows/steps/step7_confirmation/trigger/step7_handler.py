"""Step 7 - Confirmation handling with deposit/site-visit flows.

Refactored Dec 2025:
- F1: Constants, helpers, classification extracted to separate modules
- F2: Site-visit subflow extracted to site_visit.py
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.domain import EventStatus
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.room_rules import site_visit_allowed
from backend.workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import check_nonsense_gate
from backend.workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
)
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import trace_marker
from backend.utils.profiler import profile_step

# F1: Extracted modules
from .classification import classify_message
from .helpers import iso_to_ddmmyyyy, base_payload, thread_id

# F2: Site-visit subflow
from .site_visit import (
    handle_site_visit,
    site_visit_unavailable_response,
    extract_site_visit_preference,
    handle_site_visit_preference,
    parse_slot_selection,
    handle_site_visit_confirmation,
    ensure_calendar_block,
)

__workflow_role__ = "trigger"


@profile_step("workflow.step7.confirmation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Step 7 — final confirmation handling with deposit/site-visit flows."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": None,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event",
            "context": state.context_snapshot,
        }
        return GroupResult(action="confirmation_missing_event", payload=payload, halt=True)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    state.current_step = 7
    tid = thread_id(state)
    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})

    if state.user_info.get("hil_approve_step") == 7:
        return _process_hil_confirmation(state, event_entry)

    # [CHANGE DETECTION] Run FIRST to detect structural changes
    message_text = (state.message.body or "").strip()
    user_info = state.user_info or {}

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        # Silent ignore - no reply, no further processing
        return GroupResult(
            action="nonsense_ignored",
            payload={"reason": "low_confidence_no_workflow_signal", "step": 7},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=7,
                next_step=7,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=7, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 7},
            halt=True,
        )
    # -------------------------------------------------------------------------

    structural = _detect_structural_change(state.user_info, event_entry)
    if structural:
        # Handle structural change detour BEFORE Q&A
        target_step, reason = structural
        update_event_metadata(event_entry, caller_step=7, current_step=target_step)
        append_audit_entry(event_entry, 7, target_step, reason)
        state.caller_step = 7
        state.current_step = target_step
        state.set_thread_state("Waiting on HIL" if target_step == 4 else "Awaiting Client")
        state.extras["persist"] = True
        return GroupResult(
            action="structural_change_detour",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "detour_to_step": target_step,
                "caller_step": 7,
                "reason": reason,
                "persisted": True,
            },
            halt=False,
        )

    # -------------------------------------------------------------------------
    # SITE VISIT HANDLING: Check if client is responding to site visit proposal
    # -------------------------------------------------------------------------
    visit_state = event_entry.get("site_visit_state") or {}
    if visit_state.get("status") == "proposed":
        # Client may be specifying preferred visit date/time OR confirming a slot
        date_preference = extract_site_visit_preference(user_info, message_text)
        if date_preference:
            # Client gave date/time preference - generate matching slots
            return handle_site_visit_preference(state, event_entry, date_preference)

        # Check for slot confirmation (yes, proceed, first option, etc.)
        slots = visit_state.get("proposed_slots", [])
        if slots and parse_slot_selection(message_text, slots):
            return handle_site_visit_confirmation(state, event_entry)
    # -------------------------------------------------------------------------

    # [Q&A DETECTION] Check for general Q&A AFTER change detection
    qna_classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = qna_classification
    state.extras["general_qna_detected"] = bool(qna_classification.get("is_general"))

    if tid:
        trace_marker(
            tid,
            "QNA_CLASSIFY",
            detail="general_room_query" if qna_classification["is_general"] else "not_general",
            data={
                "heuristics": qna_classification.get("heuristics"),
                "parsed": qna_classification.get("parsed"),
                "constraints": qna_classification.get("constraints"),
                "llm_called": qna_classification.get("llm_called"),
                "llm_result": qna_classification.get("llm_result"),
                "cached": qna_classification.get("cached"),
            },
            owner_step="Step7_Confirmation",
        )

    classification = classify_message(message_text, event_entry)
    conf_state["last_response_type"] = classification
    general_qna_applicable = qna_classification.get("is_general")
    deferred_general_qna = general_qna_applicable and classification in {
        "confirm",
        "deposit_paid",
        "reserve",
        "site_visit",
        "decline",
        "change",
    }
    if general_qna_applicable and not deferred_general_qna:
        result = _present_general_room_qna(state, event_entry, qna_classification, tid)
        return result

    if classification == "confirm":
        result = _prepare_confirmation(state, event_entry)
    elif classification == "deposit_paid":
        result = _handle_deposit_paid(state, event_entry)
    elif classification == "reserve":
        result = _handle_reserve(state, event_entry)
    elif classification == "site_visit":
        result = handle_site_visit(state, event_entry)
    elif classification == "decline":
        result = _handle_decline(state, event_entry)
    elif classification == "change":
        result = _handle_question(state)
    else:
        result = _handle_question(state)

    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, qna_classification, tid)
    return result


def _detect_structural_change(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> Optional[tuple]:
    """Detect structural changes (date/room/participants/products) that require detour."""
    # Skip date change detection when in site visit mode
    # Dates mentioned are for the site visit, not event date changes
    visit_state = event_entry.get("site_visit_state") or {}
    in_site_visit_mode = visit_state.get("status") in {"proposed"}

    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if not in_site_visit_mode and (new_iso_date or new_ddmmyyyy):
        candidate = new_ddmmyyyy or iso_to_ddmmyyyy(new_iso_date)
        if candidate and candidate != event_entry.get("chosen_date"):
            return 2, "confirmation_changed_date"

    new_room = user_info.get("room")
    if new_room and new_room != event_entry.get("locked_room_id"):
        return 3, "confirmation_changed_room"

    participants = user_info.get("participants")
    req = event_entry.get("requirements") or {}
    if participants and participants != req.get("number_of_participants"):
        return 3, "confirmation_changed_participants"

    products_add = user_info.get("products_add")
    products_remove = user_info.get("products_remove")
    if products_add or products_remove:
        return 4, "confirmation_changed_products"

    return None


def _prepare_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Prepare final confirmation or request deposit if required."""
    # Check deposit_info (new schema) first, then fall back to deposit_state (legacy)
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )

    # Bridge: Use deposit_info if available, otherwise fall back to deposit_state
    deposit_required = deposit_info.get("deposit_required") or deposit_state.get("required", False)
    deposit_paid = deposit_info.get("deposit_paid", False) or deposit_state.get("status") == "paid"
    deposit_amount = deposit_info.get("deposit_amount") or deposit_state.get("due_amount", 0.0)
    deposit_percent = deposit_info.get("deposit_percentage") or deposit_state.get("percent", 0)

    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
    room_name = event_entry.get("locked_room_id") or event_entry.get("room_pending_decision", {}).get("selected_room")
    event_date = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date")

    if deposit_required and not deposit_paid:
        deposit_state["status"] = "requested"
        if deposit_amount:
            amount_text = f"CHF {deposit_amount:,.2f}".rstrip("0").rstrip(".")
        elif deposit_percent:
            amount_text = f"a {deposit_percent}% deposit"
        else:
            amount_text = "the agreed deposit"
        message = (
            f"To finalise your booking, please proceed with the deposit of {amount_text}. "
            "I'll send payment details now. Once received, I'll confirm your event officially."
        )
        draft = {
            "body": append_footer(
                message,
                step=7,
                next_step="Confirm deposit payment",
                thread_state="Awaiting Client",
            ),
            "step": 7,
            "topic": "confirmation_deposit_pending",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        conf_state["pending"] = {"kind": "deposit_request"}
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_requested", payload=payload, halt=True)

    room_fragment = f" for {room_name}" if room_name else ""
    date_fragment = f" on {event_date}" if event_date else ""
    final_message = (
        f"Wonderful, we're ready to proceed with your booking{room_fragment}{date_fragment}. "
        "I'll place the booking and send a confirmation message shortly."
    )
    draft = {
        "body": append_footer(
            final_message,
            step=7,
            next_step="Finalize booking (HIL)",
            thread_state="Waiting on HIL",
        ),
        "step": 7,
        "topic": "confirmation_final",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    conf_state["pending"] = {"kind": "final_confirmation"}
    update_event_metadata(event_entry, thread_state="Waiting on HIL")
    state.set_thread_state("Waiting on HIL")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_draft", payload=payload, halt=True)


def _handle_deposit_paid(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Handle deposit paid confirmation."""
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    deposit_state["status"] = "paid"
    return _prepare_confirmation(state, event_entry)


def _handle_reserve(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Handle reservation/option request."""
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    deposit_state["required"] = True
    deposit_state["status"] = "requested"
    room_name = event_entry.get("locked_room_id") or event_entry.get("room_pending_decision", {}).get("selected_room")
    event_date = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date")
    option_deadline = (
        event_entry.get("reservation_expires_at")
        or event_entry.get("option_valid_until")
        or event_entry.get("reservation_valid_until")
    )
    amount = deposit_state.get("due_amount")
    if amount:
        amount_text = f"CHF {amount:,.2f}".rstrip("0").rstrip(".")
    elif deposit_state.get("percent"):
        amount_text = f"a {deposit_state['percent']}% deposit"
    else:
        amount_text = "the deposit"
    validity_sentence = (
        f"The option is valid until {option_deadline}."
        if option_deadline
        else "The option is valid while we hold the date."
    )
    reservation_text_parts = [
        "We've reserved",
        room_name or "the room",
        "on",
        event_date or "the requested date",
        "for you.",
        validity_sentence,
        f"To confirm the booking, please proceed with the deposit of {amount_text}.",
        "I'll send payment details now.",
    ]
    body = " ".join(part for part in reservation_text_parts if part)
    draft = {
        "body": append_footer(
            body,
            step=7,
            next_step="Confirm deposit payment",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_reserve",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "reserve_notification"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_reserve", payload=payload, halt=True)


def _handle_decline(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Handle booking decline/cancellation."""
    event_entry.setdefault("event_data", {})["Status"] = EventStatus.CANCELLED.value
    draft = {
        "body": append_footer(
            "Thank you for letting us know. We've released the date, and we'd be happy to assist with any future events.",
            step=7,
            next_step="Close booking (HIL)",
            thread_state="Waiting on HIL",
        ),
        "step": 7,
        "topic": "confirmation_decline",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "decline"
    }
    update_event_metadata(event_entry, thread_state="Waiting on HIL")
    state.set_thread_state("Waiting on HIL")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_decline", payload=payload, halt=True)


def _handle_question(state: WorkflowState) -> GroupResult:
    """Handle general questions or unclear messages."""
    draft = {
        "body": append_footer(
            "Happy to help. Could you share a bit more detail so I can advise?",
            step=7,
            next_step="Provide details",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_question",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(state.event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, state.event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def _process_hil_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Process HIL approval for pending confirmations."""
    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
    pending = conf_state.get("pending") or {}
    kind = pending.get("kind")

    if not kind:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_confirmation",
            "context": state.context_snapshot,
        }
        return GroupResult(action="confirmation_hil_noop", payload=payload, halt=True)

    if kind == "final_confirmation":
        ensure_calendar_block(event_entry)
        event_entry.setdefault("event_data", {})["Status"] = EventStatus.CONFIRMED.value
        conf_state["pending"] = None
        update_event_metadata(event_entry, transition_ready=True, thread_state="Awaiting Client")
        append_audit_entry(event_entry, 7, 7, "confirmation_sent")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_finalized", payload=payload, halt=True)

    if kind == "decline":
        conf_state["pending"] = None
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        append_audit_entry(event_entry, 7, 7, "confirmation_declined")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_decline_sent", payload=payload, halt=True)

    if kind == "site_visit":
        if not site_visit_allowed(event_entry):
            conf_state["pending"] = None
            return site_visit_unavailable_response(state, event_entry)

        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "site_visit_proposed")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_site_visit_sent", payload=payload, halt=True)

    if kind == "deposit_request":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "deposit_requested")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_notified", payload=payload, halt=True)

    if kind == "reserve_notification":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "reserve_notified")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_reserve_sent", payload=payload, halt=True)

    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_hil_noop", payload=payload, halt=True)


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id_val: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 7 - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id_val,
        step_number=7, step_name="Confirmation"
    )


def _append_deferred_general_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id_val: Optional[str],
) -> None:
    """Append general Q&A to primary draft if applicable."""
    pre_count = len(state.draft_messages)
    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id_val)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        return
    appended = append_general_qna_to_primary(state)
    if not appended:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
