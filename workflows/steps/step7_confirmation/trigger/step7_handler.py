"""Step 7 - Confirmation handling with deposit/site-visit flows.

Refactored Dec 2025:
- F1: Constants, helpers, classification extracted to separate modules
- F2: Site-visit subflow extracted to site_visit.py
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from domain import EventStatus
from workflows.common.prompts import append_footer
from workflows.common.requirements import merge_client_profile
from workflows.common.room_rules import site_visit_allowed
from workflows.common.site_visit_state import is_site_visit_scheduled
from workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from workflows.common.confidence -> backend.detection.intent.confidence
from detection.intent.confidence import check_nonsense_gate
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
)
from workflows.common.detection_utils import get_unified_detection
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.nlu import detect_general_room_query
from debug.hooks import trace_marker
from utils.profiler import profile_step
from utils.page_snapshots import delete_snapshots_for_event
from workflows.steps.step5_negotiation import _offer_summary_lines

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

    # -------------------------------------------------------------------------
    # DEPOSIT JUST PAID: Check BEFORE nonsense gate (synthetic message may be empty)
    # This flag is set by the Pay Deposit button API to continue workflow
    # Skip HIL for this path since deposit payment itself confirms intent
    # -------------------------------------------------------------------------
    is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
    if is_deposit_signal:
        logger.info("[Step7] deposit_just_paid signal detected early - bypassing gates, routing to confirmation (skip_hil=True)")
        return _prepare_confirmation(state, event_entry, skip_hil=True)

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

    # -------------------------------------------------------------------------
    # BILLING GATE CONTINUATION: If we were waiting for billing and it's now provided,
    # automatically proceed to send Final Contract (no need to say "I accept" again)
    # -------------------------------------------------------------------------
    billing_reqs = event_entry.get("billing_requirements") or {}
    if billing_reqs.get("awaiting_billing_for_confirmation"):
        from workflows.common.billing import missing_billing_fields
        from workflows.common.billing_capture import capture_billing_anytime
        from detection.pre_filter import run_pre_filter

        # Try to capture billing from this message
        pf_result = run_pre_filter(message_text, event_entry=event_entry)
        if pf_result.has_billing_signal:
            capture_billing_anytime(
                state=state,
                unified_result=None,  # unified_detection not yet available
                pre_filter_signals={"billing": True},
                message_text=message_text,
            )
            state.extras["persist"] = True

        # Check if billing is now complete
        missing = missing_billing_fields(event_entry)
        if not missing:
            # Billing complete! Clear the flag and proceed to Final Contract
            billing_reqs["awaiting_billing_for_confirmation"] = False
            logger.info("[Step7][BILLING_GATE] Billing now complete - sending Final Contract")
            return _send_final_contract(state, event_entry)
        else:
            # Still incomplete - remind them what's missing
            logger.info("[Step7][BILLING_GATE] Billing still incomplete, missing: %s", missing)
            # Let it fall through to normal classification which will re-trigger gate if needed
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # EVENT DATE CHANGE GUARD: Detect event date changes during site visit flow
    # If client is requesting an EVENT date change (not site visit date),
    # reset the site visit state so structural change detection works correctly.
    # -------------------------------------------------------------------------
    visit_state_early = event_entry.get("site_visit_state") or {}
    logger.info("[Step7][DATE_GUARD] visit_state_early.status=%s, message_text=%s",
                visit_state_early.get("status"), message_text[:100] if message_text else "(empty)")
    if visit_state_early.get("status") == "proposed":
        from workflows.common.site_visit_handler import _is_event_date_change_request
        is_date_change = _is_event_date_change_request(message_text)
        logger.info("[Step7][DATE_GUARD] _is_event_date_change_request=%s", is_date_change)
        if is_date_change:
            logger.info("[Step7] Event date change detected - resetting site visit state for detour")
            from workflows.common.site_visit_state import reset_site_visit_state
            reset_site_visit_state(event_entry)
            state.extras["persist"] = True
            # Verify the reset worked
            visit_state_after = event_entry.get("site_visit_state") or {}
            logger.info("[Step7][DATE_GUARD] After reset: status=%s", visit_state_after.get("status"))
    # -------------------------------------------------------------------------

    # Get unified detection for Q&A guard in structural change detection
    unified_detection = get_unified_detection(state)
    structural = _detect_structural_change(state.user_info, event_entry, message_text, unified_detection)
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
    # Note: Event date change detection is handled BEFORE structural change detection
    # (see lines 113-125), so by the time we get here, site visit state will be reset
    # if an event date change was detected.
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

    # Get unified detection for improved site visit vs confirm classification
    unified_detection = get_unified_detection(state)
    classification = classify_message(message_text, event_entry, unified_detection)
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
        # -------------------------------------------------------------------------
        # BILLING GATE (Option B - Amazon Model):
        # Before final confirmation, ensure billing address is complete.
        # This is the "checkout" moment - natural place to request billing details.
        # -------------------------------------------------------------------------
        billing_gate_result = _check_billing_gate(state, event_entry)
        if billing_gate_result:
            return billing_gate_result
        # -------------------------------------------------------------------------
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


def _detect_structural_change(
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    message_text: str = "",
    unified_detection: Optional[Any] = None,
) -> Optional[tuple]:
    """Detect structural changes (date/room/participants/products) that require detour."""
    import re

    # -------------------------------------------------------------------------
    # Q&A GUARD: Use LLM-based detection to prevent Q&A from triggering detours
    # If unified detection says it's a question (and NOT a change request),
    # skip all change detection to allow Q&A handling downstream.
    # -------------------------------------------------------------------------
    if unified_detection is not None:
        is_qna_detected = (
            unified_detection.is_question
            or bool(unified_detection.qna_types)
        )
        is_change_by_llm = unified_detection.is_change_request

        if is_qna_detected and not is_change_by_llm:
            logger.debug(
                "[Step7][STRUCTURAL_CHANGE][QNA_GUARD] Skipping change detection: "
                "is_question=%s, qna_types=%s, is_change_request=%s",
                unified_detection.is_question,
                unified_detection.qna_types,
                unified_detection.is_change_request,
            )
            return None
    # -------------------------------------------------------------------------

    # Skip date change detection when in site visit mode
    # Dates mentioned are for the site visit, not event date changes
    visit_state = event_entry.get("site_visit_state") or {}
    in_site_visit_mode = visit_state.get("status") in {"proposed"}

    # Skip date change detection for deposit payment messages
    # "We paid the deposit on 02.01.2026" - the date is payment date, not event date
    deposit_date_pattern = re.compile(
        r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
        re.IGNORECASE
    )
    is_deposit_date_mention = bool(message_text and deposit_date_pattern.search(message_text))

    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if not in_site_visit_mode and not is_deposit_date_mention and (new_iso_date or new_ddmmyyyy):
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


def _prepare_confirmation(state: WorkflowState, event_entry: Dict[str, Any], skip_hil: bool = False) -> GroupResult:
    """Prepare final confirmation or request deposit if required.

    Args:
        skip_hil: If True, the confirmation message won't require HIL approval.
                  Used when deposit was just paid (payment itself confirms intent).
    """
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
            # Routine message - no HIL needed when toggle OFF
            "requires_approval": False,
        }
        state.add_draft_message(draft)
        conf_state["pending"] = {"kind": "deposit_request"}
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_requested", payload=payload, halt=True)

    # Mark event as Confirmed when deposit is paid (or not required)
    # This updates both canonical event["status"] and legacy event_data["Status"]
    if deposit_paid or not deposit_required:
        update_event_metadata(event_entry, status="Confirmed")
        # Also sync to event_data for backward compatibility
        event_entry.setdefault("event_data", {})["Status"] = "Confirmed"

    # Build proper offer confirmation message with all details for HIL review
    room_fragment = f"**{room_name}**" if room_name else "the venue"
    date_fragment = f"**{event_date}**" if event_date else "the requested date"

    # Get billing details for display
    billing_details = event_entry.get("billing_details") or {}
    billing_str = ", ".join(filter(None, [
        billing_details.get("company"),
        billing_details.get("street"),
        billing_details.get("postal_code"),
        billing_details.get("city"),
        billing_details.get("country"),
    ]))
    if not billing_str:
        billing_str = "Not specified"

    # Get offer total
    total_amount = 0.0
    offers = event_entry.get("offers") or []
    current_offer_id = event_entry.get("current_offer_id")
    for offer in offers:
        if offer.get("offer_id") == current_offer_id:
            total_amount = offer.get("total_amount", 0.0)
            break

    # Get participants count
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants") or event_entry.get("participants")

    # Get deposit due date
    deposit_due_date = deposit_info.get("deposit_due_date") or deposit_state.get("due_date")

    # Build comprehensive offer summary for HIL review (manager's ONLY review when toggle OFF)
    summary_lines = _offer_summary_lines(event_entry, include_cta=False)
    offer_body_markdown = "\n".join(summary_lines)

    # Build confirmation message for client (sent after HIL approval)
    client_message_parts = [
        f"We're excited to move forward with your booking for {room_fragment} on {date_fragment}.",
    ]
    if deposit_paid and deposit_amount:
        deposit_str = f"CHF {deposit_amount:,.2f}".rstrip("0").rstrip(".")
        client_message_parts.append(f"Your deposit of {deposit_str} has been received.")
    # Show appropriate next step based on site visit status
    if is_site_visit_scheduled(event_entry):
        sv_state = event_entry.get("site_visit_state") or {}
        sv_date = sv_state.get("date_iso", "")
        sv_time = sv_state.get("time_slot", "")
        sv_display = f"{sv_date} at {sv_time}" if sv_time else sv_date
        client_message_parts.append(
            f"Your site visit is already scheduled for {sv_display}. "
            "We'll finalize the details closer to your event date."
        )
    else:
        client_message_parts.append(
            "Would you like to arrange a site visit before we finalize everything?"
        )
    client_message = " ".join(client_message_parts)

    # Build deposit status string with due date
    if deposit_paid:
        deposit_status = f"CHF {deposit_amount:,.2f} ✅ Paid"
    elif deposit_due_date:
        deposit_status = f"CHF {deposit_amount:,.2f} (due: {deposit_due_date})"
    else:
        deposit_status = f"CHF {deposit_amount:,.2f} Pending"

    draft = {
        "body": append_footer(
            client_message,
            step=7,
            next_step="Finalize booking",
            thread_state="In Progress",
        ),
        "body_markdown": offer_body_markdown,  # Full offer summary for HIL panel
        "step": 7,
        "topic": "offer_confirmation",  # Changed from confirmation_final to offer_confirmation
        # Manager's ONLY review point when toggle OFF - full offer review
        # skip_hil=True when deposit just paid (payment itself confirms intent)
        "requires_approval": not skip_hil,
        # Add table blocks for HIL display
        "table_blocks": [
            {
                "type": "table",
                "header": ["Field", "Value"],
                "rows": [
                    ["Event Date", event_date or "TBD"],
                    ["Room", room_name or "TBD"],
                    ["Participants", str(participants) if participants else "TBD"],
                    ["Billing Address", billing_str],
                    ["Total", f"CHF {total_amount:,.2f}"],
                    ["Deposit", deposit_status],
                ],
            }
        ],
    }
    state.add_draft_message(draft)
    conf_state["pending"] = {"kind": "final_confirmation"}
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
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
        # Routine message - no HIL needed when toggle OFF
        "requires_approval": False,
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

    # Log cancellation activity for manager visibility
    from activity.persistence import log_workflow_activity
    log_workflow_activity(event_entry, "status_cancelled", reason="Client declined")

    # Clean up event-specific snapshots (room listings, offers) on cancellation
    event_id = event_entry.get("event_id")
    if event_id:
        try:
            delete_snapshots_for_event(event_id)
        except Exception:
            pass  # Don't fail booking flow on cleanup errors
    draft = {
        "body": append_footer(
            "Thank you for letting us know. We've released the date, and we'd be happy to assist with any future events.",
            step=7,
            next_step="Close booking",
            thread_state="In Progress",
        ),
        "step": 7,
        "topic": "confirmation_decline",
        # Routine acknowledgment - no HIL needed when toggle OFF
        "requires_approval": False,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "decline"
    }
    update_event_metadata(event_entry, thread_state="Closed")
    state.set_thread_state("Closed")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_decline", payload=payload, halt=True)


def _send_final_contract(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """
    Generate the Final Contract/Invoice after billing is complete.

    This is sent ONLY when billing was provided AFTER the initial proposal/offer.
    It's visually distinct from the proposal with clear "FINAL CONTRACT" formatting.
    """
    from workflows.steps.step5_negotiation import _offer_summary_lines

    room_name = event_entry.get("locked_room_id") or event_entry.get("room_pending_decision", {}).get("selected_room")
    event_date = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date")

    # Get complete billing details
    billing_details = event_entry.get("billing_details") or {}
    billing_parts = []
    if billing_details.get("name_or_company"):
        billing_parts.append(billing_details["name_or_company"])
    if billing_details.get("street"):
        billing_parts.append(billing_details["street"])
    postal_city = " ".join(filter(None, [
        billing_details.get("postal_code"),
        billing_details.get("city"),
    ]))
    if postal_city:
        billing_parts.append(postal_city)
    if billing_details.get("country"):
        billing_parts.append(billing_details["country"])
    billing_str = ", ".join(billing_parts) if billing_parts else "N/A"

    # Get offer total
    total_amount = 0.0
    offers = event_entry.get("offers") or []
    current_offer_id = event_entry.get("current_offer_id")
    for offer in offers:
        if offer.get("offer_id") == current_offer_id:
            total_amount = offer.get("total_amount", 0.0)
            break

    # Get participants
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants") or event_entry.get("participants")

    # Get deposit info
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_state = event_entry.get("deposit_state") or {}
    deposit_amount = deposit_info.get("deposit_amount") or deposit_state.get("due_amount", 0.0)
    deposit_paid = deposit_info.get("deposit_paid", False) or deposit_state.get("status") == "paid"

    # =========================================================================
    # BUILD FINAL CONTRACT MESSAGE (visually distinct from proposal)
    # =========================================================================
    room_fragment = f"**{room_name}**" if room_name else "your selected venue"
    date_fragment = f"**{event_date}**" if event_date else "your requested date"

    # Client-facing message (clean, professional)
    client_message = (
        f"Thank you for providing your billing details.\n\n"
        f"Here is your **Final Booking Confirmation** for {room_fragment} on {date_fragment}:\n\n"
        f"───────────────────────────────\n"
        f"**BOOKING CONFIRMATION**\n"
        f"───────────────────────────────\n\n"
        f"**Event Date:** {event_date or 'TBD'}\n"
        f"**Venue:** {room_name or 'TBD'}\n"
        f"**Guests:** {participants or 'TBD'}\n\n"
        f"**Billing Address:**\n{billing_str}\n\n"
        f"**Total:** CHF {total_amount:,.2f}\n"
    )

    if deposit_paid and deposit_amount:
        client_message += f"**Deposit:** CHF {deposit_amount:,.2f} ✓ Received\n"
    elif deposit_amount:
        client_message += f"**Deposit Due:** CHF {deposit_amount:,.2f}\n"

    client_message += (
        f"\n───────────────────────────────\n\n"
        f"Your booking is now confirmed. We look forward to hosting your event!"
    )

    # Manager view (detailed offer summary)
    summary_lines = _offer_summary_lines(event_entry, include_cta=False)
    offer_body_markdown = "\n".join(summary_lines)

    draft = {
        "body": append_footer(
            client_message,
            step=7,
            next_step="Booking confirmed",
            thread_state="Confirmed",
        ),
        "body_markdown": offer_body_markdown,  # Manager sees full details
        "step": 7,
        "topic": "final_contract_sent",
        "requires_approval": True,  # HIL reviews the final contract
        "table_blocks": [
            {
                "type": "table",
                "header": ["Field", "Value"],
                "rows": [
                    ["📄 Document", "**FINAL CONTRACT**"],
                    ["Event Date", event_date or "TBD"],
                    ["Room", room_name or "TBD"],
                    ["Participants", str(participants) if participants else "TBD"],
                    ["Billing", billing_str],
                    ["Total", f"CHF {total_amount:,.2f}"],
                    ["Deposit", f"CHF {deposit_amount:,.2f} {'✓ Paid' if deposit_paid else 'Pending'}"],
                ],
            }
        ],
    }
    state.add_draft_message(draft)

    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
    conf_state["pending"] = {"kind": "final_confirmation"}
    update_event_metadata(event_entry, thread_state="Awaiting HIL Approval")
    state.set_thread_state("Awaiting HIL Approval")
    state.extras["persist"] = True

    payload = base_payload(state, event_entry)
    payload["final_contract"] = True
    payload["billing_complete"] = True
    return GroupResult(action="final_contract_ready", payload=payload, halt=True)


def _check_billing_gate(state: WorkflowState, event_entry: Dict[str, Any]) -> Optional[GroupResult]:
    """
    Gate confirmation on complete billing address (Option B - Amazon Model).

    UX Philosophy: Like Amazon, we show the cart/offer first without asking for
    billing details. But at checkout (confirmation), we require complete billing
    to generate the final contract/invoice.

    Returns:
        - None if billing is complete (proceed with confirmation)
        - GroupResult with billing request if incomplete (gate blocks confirmation)
    """
    from workflows.common.billing import missing_billing_fields, billing_prompt_for_missing_fields

    missing = missing_billing_fields(event_entry)
    if not missing:
        # Billing complete - proceed with confirmation
        return None

    # Billing incomplete - gate the confirmation
    prompt = billing_prompt_for_missing_fields(missing)
    if not prompt:
        # Fallback generic prompt
        prompt = "To finalize your booking, could you please provide your complete billing address?"

    # Build friendly gating message
    billing_details = event_entry.get("billing_details") or {}
    existing_parts = []
    if billing_details.get("name_or_company"):
        existing_parts.append(billing_details["name_or_company"])
    if billing_details.get("city"):
        existing_parts.append(billing_details["city"])

    if existing_parts:
        existing_str = ", ".join(existing_parts)
        message = (
            f"Great — I'm ready to finalize your booking! "
            f"I have your billing as **{existing_str}**, but {prompt.lower()}"
        )
    else:
        message = (
            f"Great — I'm ready to finalize your booking! "
            f"To generate your contract, {prompt.lower()}"
        )

    draft = {
        "body": append_footer(
            message,
            step=7,
            next_step="Complete billing",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "billing_gate_at_confirmation",
        "requires_approval": False,  # No HIL needed for billing request
    }
    state.add_draft_message(draft)

    # Track that we're waiting for billing
    event_entry.setdefault("billing_requirements", {})["awaiting_billing_for_confirmation"] = True
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    logger.info("[Step7][BILLING_GATE] Blocking confirmation - missing billing fields: %s", missing)

    payload = base_payload(state, event_entry)
    payload["billing_gate_active"] = True
    payload["missing_billing_fields"] = missing
    return GroupResult(action="confirmation_billing_gate", payload=payload, halt=True)


def _handle_question(state: WorkflowState) -> GroupResult:
    """Handle general questions or unclear messages."""
    event_entry = state.event_entry
    if not event_entry:
        # Should not happen at Step 7, but handle gracefully
        return GroupResult(action="error_no_event", payload={}, halt=True)
    draft = {
        "body": append_footer(
            "Happy to help. Could you share a bit more detail so I can advise?",
            step=7,
            next_step="Provide details",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_question",
        # Routine Q&A - no HIL needed when toggle OFF
        "requires_approval": False,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
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

        # Clean up event-specific snapshots (room listings, offers) on confirmation
        event_id = event_entry.get("event_id")
        if event_id:
            try:
                delete_snapshots_for_event(event_id)
            except Exception:
                pass  # Don't fail booking flow on cleanup errors

        update_event_metadata(event_entry, transition_ready=True, thread_state="Awaiting Client")
        append_audit_entry(event_entry, 7, 7, "confirmation_sent")

        # After confirmation HIL approval, automatically offer site visit if allowed
        if site_visit_allowed(event_entry):
            logger.info("[Step7] HIL approved confirmation - auto-offering site visit")
            return handle_site_visit(state, event_entry)

        # If site visit not allowed, just confirm
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
