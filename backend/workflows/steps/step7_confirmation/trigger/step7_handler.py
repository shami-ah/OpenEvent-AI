from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.domain import EventStatus
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.room_rules import site_visit_allowed
from backend.workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import check_nonsense_gate
from backend.workflows.common.general_qna import append_general_qna_to_primary, _fallback_structured_body
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import trace_marker, trace_general_qa_status, set_subloop
from backend.utils.profiler import profile_step

__workflow_role__ = "trigger"


CONFIRM_KEYWORDS = ("confirm", "go ahead", "locked", "booked", "ready to proceed", "accept")
RESERVE_KEYWORDS = ("reserve", "hold", "pencil", "option")
VISIT_KEYWORDS = ("visit", "tour", "view", "walkthrough", "see the space", "stop by")
DECLINE_KEYWORDS = ("cancel", "decline", "not interested", "no longer", "won't proceed")
CHANGE_KEYWORDS = ("change", "adjust", "different", "increase", "decrease", "move", "switch")
QUESTION_KEYWORDS = ("could", "would", "do you", "can you")


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
    thread_id = _thread_id(state)
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
        date_preference = _extract_site_visit_preference(user_info, message_text)
        if date_preference:
            # Client gave date/time preference - generate matching slots
            return _handle_site_visit_preference(state, event_entry, date_preference)

        # Check for slot confirmation (yes, proceed, first option, etc.)
        slots = visit_state.get("proposed_slots", [])
        if slots and _parse_slot_selection(message_text, slots):
            return _handle_site_visit_confirmation(state, event_entry)
    # -------------------------------------------------------------------------

    # [Q&A DETECTION] Check for general Q&A AFTER change detection
    qna_classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = qna_classification
    state.extras["general_qna_detected"] = bool(qna_classification.get("is_general"))

    if thread_id:
        trace_marker(
            thread_id,
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

    classification = _classify_message(message_text, event_entry)
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
        result = _present_general_room_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "confirm":
        result = _prepare_confirmation(state, event_entry)
    elif classification == "deposit_paid":
        result = _handle_deposit_paid(state, event_entry)
    elif classification == "reserve":
        result = _handle_reserve(state, event_entry)
    elif classification == "site_visit":
        result = _handle_site_visit(state, event_entry)
    elif classification == "decline":
        result = _handle_decline(state, event_entry)
    elif classification == "change":
        result = _handle_question(state)
    else:
        result = _handle_question(state)

    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
    return result


def _classify_message(message_text: str, event_entry: Dict[str, Any]) -> str:
    lowered = message_text.lower()

    deposit_state = event_entry.get("deposit_state") or {}
    if deposit_state.get("status") in {"requested", "awaiting_payment"}:
        if _contains_word(lowered, "deposit") and any(
            _contains_word(lowered, token) for token in ("paid", "sent", "transferred", "settled")
        ):
            return "deposit_paid"

    if _any_keyword_match(lowered, CONFIRM_KEYWORDS):
        return "confirm"
    if _any_keyword_match(lowered, VISIT_KEYWORDS):
        return "site_visit"
    if _any_keyword_match(lowered, RESERVE_KEYWORDS):
        return "reserve"
    if _any_keyword_match(lowered, DECLINE_KEYWORDS):
        return "decline"
    if _any_keyword_match(lowered, CHANGE_KEYWORDS):
        return "change"
    if "?" in lowered or any(token in lowered for token in QUESTION_KEYWORDS):
        return "question"
    return "question"


def _detect_structural_change(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    # Skip date change detection when in site visit mode
    # Dates mentioned are for the site visit, not event date changes
    visit_state = event_entry.get("site_visit_state") or {}
    in_site_visit_mode = visit_state.get("status") in {"proposed"}

    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if not in_site_visit_mode and (new_iso_date or new_ddmmyyyy):
        candidate = new_ddmmyyyy or _iso_to_ddmmyyyy(new_iso_date)
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
            "I’ll send payment details now. Once received, I’ll confirm your event officially."
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
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_requested", payload=payload, halt=True)

    room_fragment = f" for {room_name}" if room_name else ""
    date_fragment = f" on {event_date}" if event_date else ""
    final_message = (
        f"Wonderful — we’re ready to proceed with your booking{room_fragment}{date_fragment}. "
        "I’ll place the booking and send a confirmation message shortly."
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
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_draft", payload=payload, halt=True)


def _handle_deposit_paid(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    deposit_state["status"] = "paid"
    return _prepare_confirmation(state, event_entry)


def _handle_reserve(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
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
        "We’ve reserved",
        room_name or "the room",
        "on",
        event_date or "the requested date",
        "for you.",
        validity_sentence,
        f"To confirm the booking, please proceed with the deposit of {amount_text}.",
        "I’ll send payment details now.",
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
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_reserve", payload=payload, halt=True)


def _handle_site_visit(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    if not site_visit_allowed(event_entry):
        conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
        conf_state["pending"] = None
        return _site_visit_unavailable_response(state, event_entry)

    slots = _generate_visit_slots(event_entry)
    visit_state = event_entry.setdefault(
        "site_visit_state", {"status": "idle", "proposed_slots": [], "scheduled_slot": None}
    )
    visit_state["status"] = "proposed"
    visit_state["proposed_slots"] = slots
    draft_lines = ["We’d be happy to arrange a site visit. Here are some possible times:"]
    draft_lines.extend(f"- {slot}" for slot in slots)
    draft_lines.append("Which would suit you? If you have other preferences, let me know and I’ll try to accommodate.")
    draft = {
        "body": append_footer(
            "\n".join(draft_lines),
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_site_visit",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "site_visit"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_site_visit", payload=payload, halt=True)


def _site_visit_unavailable_response(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    draft = {
        "body": append_footer(
            "Thanks for checking — for this room we aren't able to offer on-site visits before confirmation, "
            "but I'm happy to share additional details or photos.",
            step=7,
            next_step="Share any questions",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_question",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def _handle_decline(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    event_entry.setdefault("event_data", {})["Status"] = EventStatus.CANCELLED.value
    draft = {
        "body": append_footer(
            "Thank you for letting us know. We’ve released the date, and we’d be happy to assist with any future events.",
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
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_decline", payload=payload, halt=True)


def _handle_question(state: WorkflowState) -> GroupResult:
    draft = {
        "body": append_footer(
            "Happy to help — could you share a bit more detail so I can advise?",
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
    payload = _base_payload(state, state.event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def _process_hil_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
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
        _ensure_calendar_block(event_entry)
        event_entry.setdefault("event_data", {})["Status"] = EventStatus.CONFIRMED.value
        conf_state["pending"] = None
        update_event_metadata(event_entry, transition_ready=True, thread_state="Awaiting Client")
        append_audit_entry(event_entry, 7, 7, "confirmation_sent")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_finalized", payload=payload, halt=True)

    if kind == "decline":
        conf_state["pending"] = None
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        append_audit_entry(event_entry, 7, 7, "confirmation_declined")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_decline_sent", payload=payload, halt=True)

    if kind == "site_visit":
        if not site_visit_allowed(event_entry):
            conf_state["pending"] = None
            return _site_visit_unavailable_response(state, event_entry)

        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "site_visit_proposed")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_site_visit_sent", payload=payload, halt=True)

    if kind == "deposit_request":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "deposit_requested")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_notified", payload=payload, halt=True)

    if kind == "reserve_notification":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "reserve_notified")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_reserve_sent", payload=payload, halt=True)

    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_hil_noop", payload=payload, halt=True)


def _generate_visit_slots(event_entry: Dict[str, Any]) -> List[str]:
    base = event_entry.get("chosen_date") or "15.03.2025"
    try:
        day, month, year = map(int, base.split("."))
        anchor = datetime(year, month, day)
    except ValueError:
        anchor = datetime.utcnow()
    slots: List[str] = []
    for offset in range(3):
        candidate = anchor - timedelta(days=offset + 1)
        slot = candidate.replace(hour=10 + offset, minute=0)
        slots.append(slot.strftime("%d.%m.%Y at %H:%M"))
    return slots


# ---------------------------------------------------------------------------
# Site Visit Preference Handling (Phase 1)
# ---------------------------------------------------------------------------

def _extract_site_visit_preference(user_info: Dict[str, Any], message_text: str) -> Optional[Dict[str, Any]]:
    """Extract site visit date/time preference from client message."""
    # Check for date in user_info (from LLM extraction)
    raw_date = user_info.get("date") or user_info.get("event_date")

    # Parse time preference (e.g., "4 pm", "16:00", "around 4")
    time_match = re.search(r"(\d{1,2})\s*(?:pm|am|:00|h|uhr)?", message_text.lower())
    time_pref = None
    if time_match:
        hour = int(time_match.group(1))
        if "pm" in message_text.lower() and hour < 12:
            hour += 12
        elif "am" not in message_text.lower() and hour < 6:
            # Assume afternoon for small numbers without am/pm
            hour += 12
        time_pref = f"{hour:02d}:00"

    # Check for day-of-week preference (EN + DE)
    day_keywords = {
        "monday": 0, "montag": 0, "tuesday": 1, "dienstag": 1,
        "wednesday": 2, "mittwoch": 2, "thursday": 3, "donnerstag": 3,
        "friday": 4, "freitag": 4,
    }
    weekday_pref = None
    for day, num in day_keywords.items():
        if day in message_text.lower():
            weekday_pref = num
            break

    # Check for month references (parse "april" -> base date in that month)
    month_keywords = {
        "january": 1, "januar": 1, "february": 2, "februar": 2,
        "march": 3, "märz": 3, "marz": 3, "april": 4,
        "may": 5, "mai": 5, "june": 6, "juni": 6,
        "july": 7, "juli": 7, "august": 8,
        "september": 9, "october": 10, "oktober": 10,
        "november": 11, "december": 12, "dezember": 12,
    }
    month_pref = None
    for month_name, month_num in month_keywords.items():
        if month_name in message_text.lower():
            month_pref = month_num
            break

    if raw_date or time_pref or weekday_pref or month_pref:
        return {
            "requested_date": raw_date,        # ISO date from LLM
            "requested_time": time_pref,       # "16:00" format
            "requested_weekday": weekday_pref, # 0-4 Mon-Fri
            "requested_month": month_pref,     # 1-12
        }
    return None


def _generate_preferred_visit_slots(
    event_entry: Dict[str, Any],
    preference: Dict[str, Any],
) -> List[str]:
    """Generate visit slots matching client's preference (before event date)."""
    event_date_str = event_entry.get("chosen_date") or "15.03.2025"
    try:
        day, month, year = map(int, event_date_str.split("."))
        event_date = datetime(year, month, day)
    except ValueError:
        event_date = datetime.utcnow() + timedelta(days=30)

    # Parse preference
    requested_date = preference.get("requested_date")
    requested_time = preference.get("requested_time") or "16:00"
    requested_weekday = preference.get("requested_weekday")
    requested_month = preference.get("requested_month")

    # Determine base date for slot search
    base: Optional[datetime] = None
    if requested_date:
        try:
            base = datetime.fromisoformat(requested_date.replace("Z", ""))
        except ValueError:
            pass
    if base is None and requested_month:
        # Use first day of requested month in event year
        base = datetime(event_date.year, requested_month, 1)
        # If month already passed this year, try next year
        if base < datetime.utcnow():
            base = datetime(event_date.year + 1, requested_month, 1)
    if base is None:
        # Default to 2-3 weeks before event
        base = event_date - timedelta(days=21)

    # Generate up to 3 slots matching weekday preference, before event date
    slots: List[str] = []
    candidate = base
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    for _ in range(60):  # Search 60 days max
        if candidate >= event_date:
            break
        if candidate < today:
            candidate += timedelta(days=1)
            continue
        if requested_weekday is None or candidate.weekday() == requested_weekday:
            try:
                hour = int(requested_time.split(":")[0])
            except (ValueError, IndexError):
                hour = 16
            slot_dt = candidate.replace(hour=hour, minute=0)
            slots.append(slot_dt.strftime("%d.%m.%Y at %H:%M"))
            if len(slots) >= 3:
                break
        candidate += timedelta(days=1)

    return slots


def _handle_site_visit_preference(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    preference: Dict[str, Any],
) -> GroupResult:
    """Handle site visit date/time preference from client."""
    visit_state = event_entry.get("site_visit_state") or {}

    # Store the client's preference (Supabase-compatible)
    visit_state["requested_date"] = preference.get("requested_date")
    visit_state["requested_time"] = preference.get("requested_time")
    visit_state["requested_weekday"] = preference.get("requested_weekday")

    # Generate slots based on preference
    slots = _generate_preferred_visit_slots(event_entry, preference)
    if not slots:
        # Fallback to default slots if preference yields no results
        slots = _generate_visit_slots(event_entry)

    visit_state["proposed_slots"] = slots
    event_entry["site_visit_state"] = visit_state

    # Build response
    draft_lines = ["Here are available times matching your preference:"]
    draft_lines.extend(f"- {slot}" for slot in slots)
    draft_lines.append("Which would work best for you?")

    draft = {
        "body": append_footer(
            "\n".join(draft_lines),
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "site_visit_preference_slots",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "site_visit"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="site_visit_preference_slots", payload=payload, halt=True)


def _parse_slot_selection(message_text: str, slots: List[str]) -> Optional[str]:
    """Parse which slot client selected from their message."""
    lowered = message_text.lower()

    # Check for ordinal selection
    ordinals = [("first", 0), ("1st", 0), ("second", 1), ("2nd", 1), ("third", 2), ("3rd", 2)]
    for word, idx in ordinals:
        if word in lowered and idx < len(slots):
            return slots[idx]

    # Check for date match in message
    for slot in slots:
        date_part = slot.split(" at ")[0]  # "15.04.2026"
        if date_part in message_text:
            return slot

    # Generic confirmation = first slot
    confirm_words = ("yes", "proceed", "ok", "confirm", "sounds good", "perfect", "ja", "bitte")
    if any(word in lowered for word in confirm_words) and slots:
        return slots[0]

    return None


def _handle_site_visit_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Confirm the selected site visit slot (direct confirm, no HIL)."""
    visit_state = event_entry.get("site_visit_state") or {}
    slots = visit_state.get("proposed_slots", [])
    message_text = (state.message.body or "").strip()

    # Parse slot selection
    selected_slot = _parse_slot_selection(message_text, slots)

    if selected_slot:
        # Parse into confirmed_date and confirmed_time
        try:
            date_part, time_part = selected_slot.split(" at ")
            parsed_date = datetime.strptime(date_part, "%d.%m.%Y")
            confirmed_date = parsed_date.date().isoformat()
            confirmed_time = time_part
        except (ValueError, IndexError):
            confirmed_date = None
            confirmed_time = None

        # Update state (Supabase-compatible)
        visit_state["status"] = "scheduled"
        visit_state["confirmed_date"] = confirmed_date
        visit_state["confirmed_time"] = confirmed_time
        event_entry["site_visit_state"] = visit_state

        room_name = event_entry.get("locked_room_id") or "the venue"
        draft = {
            "body": append_footer(
                f"Your site visit is confirmed for {selected_slot}. "
                f"We look forward to showing you {room_name}!",
                step=7,
                next_step="Site visit scheduled - continue booking",
                thread_state="Awaiting Client",
            ),
            "step": 7,
            "topic": "site_visit_confirmed",
            "requires_approval": False,  # Direct confirm, no HIL
        }
        state.add_draft_message(draft)
        append_audit_entry(event_entry, 7, 7, "site_visit_confirmed")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="site_visit_confirmed", payload=payload, halt=True)

    # Couldn't parse selection - ask for clarification
    draft = {
        "body": append_footer(
            "I couldn't determine which slot you'd prefer. "
            "Could you please specify which date and time works best for your visit?",
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "site_visit_clarification",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="site_visit_clarification", payload=payload, halt=True)


def _ensure_calendar_block(event_entry: Dict[str, Any]) -> None:
    blocks = event_entry.setdefault("calendar_blocks", [])
    date_label = event_entry.get("chosen_date") or ""
    room = event_entry.get("locked_room_id") or "Room"
    blocks.append({"date": date_label, "room": room, "created_at": datetime.utcnow().isoformat()})


def _iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%d.%m.%Y")


def _base_payload(state: WorkflowState, event_entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return payload


def _any_keyword_match(lowered: str, keywords: Tuple[str, ...]) -> bool:
    return any(_contains_word(lowered, keyword) for keyword in keywords)


def _contains_word(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text) is not None


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 7 using the same pattern as Step 2."""
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    resolved_thread_id = thread_id or state.thread_id

    if thread_id:
        set_subloop(thread_id, subloop_label)

    # Extract fresh from current message (multi-turn Q&A fix)
    message = state.message
    subject = (message.subject if message else "") or ""
    body = (message.body if message else "") or ""
    message_text = f"{subject}\n{body}".strip() or body or subject

    scan = state.extras.get("general_qna_scan")
    # Force fresh extraction for multi-turn Q&A
    ensure_qna_extraction(state, message_text, scan, force_refresh=True)
    extraction = state.extras.get("qna_extraction")

    # Clear stale qna_cache AFTER extraction
    if isinstance(event_entry, dict):
        event_entry.pop("qna_cache", None)

    structured = build_structured_qna_result(state, extraction) if extraction else None

    if structured and structured.handled:
        rooms = structured.action_payload.get("db_summary", {}).get("rooms", [])
        date_lookup: Dict[str, str] = {}
        for entry in rooms:
            iso_date = entry.get("date") or entry.get("iso_date")
            if not iso_date:
                continue
            try:
                parsed = datetime.fromisoformat(iso_date)
            except ValueError:
                try:
                    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
                except ValueError:
                    continue
            label = parsed.strftime("%d.%m.%Y")
            date_lookup.setdefault(label, parsed.date().isoformat())

        candidate_dates = sorted(date_lookup.keys(), key=lambda label: date_lookup[label])[:5]
        actions = [
            {
                "type": "select_date",
                "label": f"Confirm {label}",
                "date": label,
                "iso_date": date_lookup[label],
            }
            for label in candidate_dates
        ]

        body_markdown = (structured.body_markdown or _fallback_structured_body(structured.action_payload)).strip()
        footer_body = append_footer(
            body_markdown,
            step=7,
            next_step=7,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 7,
            "next_step": 7,
            "thread_state": "Awaiting Client",
            "topic": "general_room_qna",
            "candidate_dates": candidate_dates,
            "actions": actions,
            "subloop": subloop_label,
            "headers": ["Availability overview"],
        }

        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            thread_state="Awaiting Client",
            current_step=7,
            candidate_dates=candidate_dates,
        )
        state.set_thread_state("Awaiting Client")
        state.record_subloop(subloop_label)
        state.intent_detail = "event_intake_with_question"
        state.extras["persist"] = True

        # Store minimal last_general_qna context for follow-up detection only
        if extraction and isinstance(event_entry, dict):
            q_values = extraction.get("q_values") or {}
            event_entry["last_general_qna"] = {
                "topic": structured.action_payload.get("qna_subtype"),
                "date_pattern": q_values.get("date_pattern"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "candidate_dates": candidate_dates,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "general_qna": True,
            "structured_qna": structured.handled,
            "qna_select_result": structured.action_payload,
            "structured_qna_debug": structured.debug,
            "actions": actions,
        }
        if extraction:
            payload["qna_extraction"] = extraction
        return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    # Fallback if structured Q&A failed
    fallback_prompt = "[STRUCTURED_QNA_FALLBACK]\nI couldn't load the structured Q&A context for this request. Please review extraction logs."
    draft_message = {
        "step": 7,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 7 Confirmation · Next: 7 Confirmation · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 7,
        "thread_state": "Awaiting Client",
        "headers": ["Availability overview"],
        "requires_approval": False,
        "subloop": subloop_label,
        "actions": [],
        "candidate_dates": [],
    }
    state.add_draft_message(draft_message)
    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=7,
        candidate_dates=[],
    )
    state.set_thread_state("Awaiting Client")
    state.record_subloop(subloop_label)
    state.intent_detail = "event_intake_with_question"
    state.extras["structured_qna_fallback"] = True
    structured_payload = structured.action_payload if structured else {}
    structured_debug = structured.debug if structured else {"reason": "missing_structured_context"}

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": [],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "general_qna": True,
        "structured_qna": False,
        "structured_qna_fallback": True,
        "qna_select_result": structured_payload,
        "structured_qna_debug": structured_debug,
    }
    if extraction:
        payload["qna_extraction"] = extraction
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)


def _append_deferred_general_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> None:
    pre_count = len(state.draft_messages)
    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        return
    appended = append_general_qna_to_primary(state)
    if not appended:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
