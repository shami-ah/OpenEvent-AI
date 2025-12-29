from __future__ import annotations

import logging
import re
from datetime import date as dt_date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from backend.workflows.common.datetime_parse import parse_all_dates
from backend.workflows.common.timeutils import parse_ddmmyyyy

from backend.domain import TaskStatus, TaskType
from backend.workflows.common.billing import (
    billing_prompt_for_missing_fields,
    format_billing_display,
    missing_billing_fields,
    update_billing_details,
)
from backend.workflows.common.confirmation_gate import (
    auto_continue_if_ready,
    get_next_prompt,
)
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.pricing import derive_room_rate, normalise_rate
# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import (
    should_defer_to_human,
    should_seek_clarification,
    check_nonsense_gate,
)
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
    _fallback_structured_body,
)
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io.tasks import enqueue_task, update_task_status
from backend.workflows.nlu import detect_general_room_query
# MIGRATED: from backend.workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from backend.detection.response.matchers import (
    is_room_selection,
    matches_acceptance_pattern,
    matches_counter_pattern,
    matches_decline_pattern,
)
from backend.debug.hooks import trace_marker, trace_general_qa_status, set_subloop
from backend.debug.trace import set_hil_open
from backend.utils.profiler import profile_step
from backend.workflows.common.menu_options import DINNER_MENU_OPTIONS

# N2 refactoring: Constants and classification extracted to dedicated modules
from .constants import (
    MAX_COUNTER_PROPOSALS,
    INTENT_ACCEPT,
    INTENT_DECLINE,
    INTENT_COUNTER,
    INTENT_ROOM_SELECTION,
    INTENT_CLARIFICATION,
    OFFER_STATUS_ACCEPTED,
    OFFER_STATUS_DECLINED,
    SITE_VISIT_PROPOSED,
)
from .classification import (
    classify_message as _classify_message,
    collect_detected_intents as _collect_detected_intents,
    iso_to_ddmmyyyy as _iso_to_ddmmyyyy,
)

# Billing gate helpers (N3 refactoring → O2 consolidated to common)
from backend.workflows.common.billing_gate import (
    refresh_billing as _refresh_billing,
    flag_billing_accept_pending as _flag_billing_accept_pending,
    billing_prompt_draft as _billing_prompt_draft,
)

__all__ = ["process"]

# N2: MAX_COUNTERS moved to constants.py as MAX_COUNTER_PROPOSALS


def _menu_name_set() -> set[str]:
    return {
        str(entry.get("menu_name") or "").strip().lower()
        for entry in DINNER_MENU_OPTIONS
        if entry.get("menu_name")
    }


def _normalise_product_fields(product: Dict[str, Any], *, menu_names: Optional[set[str]] = None) -> Dict[str, Any]:
    menu_names = menu_names or _menu_name_set()
    normalised = dict(product)
    name = str(normalised.get("name") or "").strip()
    unit = normalised.get("unit")
    if not unit and name.lower() in menu_names:
        unit = "per_event"
    try:
        quantity = float(normalised.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    try:
        unit_price = float(normalised.get("unit_price") or 0.0)
    except (TypeError, ValueError):
        unit_price = 0.0

    if unit == "per_event":
        quantity = 1

    normalised["name"] = name or "Unnamed item"
    normalised["unit"] = unit
    normalised["quantity"] = quantity
    normalised["unit_price"] = unit_price
    return normalised


@profile_step("workflow.step5.negotiation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Step 5 — negotiation handling and close preparation."""

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
        return GroupResult(action="negotiation_missing_event", payload=payload, halt=True)

    state.current_step = 5
    thread_id = _thread_id(state)
    negotiation_state = event_entry.setdefault(
        "negotiation_state", {"counter_count": 0, "manual_review_task_id": None}
    )

    # Handle HIL decision callbacks for Step 5 (offer approval/decline).
    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 5:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_negotiation_decision(state, event_entry, decision)

    # Clear stale HIL requests from earlier steps (e.g., outdated offer drafts).
    _clear_stale_hil_requests(state, event_entry, keep_steps={5})

    # -------------------------------------------------------------------------
    # BILLING FLOW CAPTURE: Must run BEFORE pending HIL check!
    # When awaiting_billing_for_accept=True, the client's message contains
    # their billing address. We must capture it before any early returns.
    # -------------------------------------------------------------------------
    billing_req = event_entry.get("billing_requirements") or {}
    in_billing_capture_mode = billing_req.get("awaiting_billing_for_accept", False)

    if in_billing_capture_mode:
        # Skip billing capture for synthetic deposit payment messages
        # (their body is "I have paid the deposit." which would corrupt billing)
        is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
        if not is_deposit_signal:
            message_text = (state.message.body or "").strip()
            if message_text:
                event_entry.setdefault("event_data", {})["Billing Address"] = message_text
                state.extras["persist"] = True
                print(f"[BILLING_CAPTURE] Stored billing address from message: {message_text[:80]}...")

    # Refresh billing details (parses event_data["Billing Address"] into structured fields)
    billing_missing = _refresh_billing(event_entry)
    state.extras["persist"] = True

    # Clear awaiting_billing_for_accept once billing is complete
    if not billing_missing and billing_req.get("awaiting_billing_for_accept"):
        billing_req["awaiting_billing_for_accept"] = False
        billing_req["last_missing"] = []
        state.extras["persist"] = True
        print(f"[BILLING_CAPTURE] Billing complete - cleared awaiting_billing_for_accept")

    # If a manager decision is already pending, keep waiting instead of spamming duplicates.
    # BUT: Skip this check during billing flow - we need to continue to confirmation gate.
    pending_decision = event_entry.get("negotiation_pending_decision")
    pending_hil = [
        req for req in (event_entry.get("pending_hil_requests") or []) if req.get("step") == 5
    ]
    if (pending_decision or pending_hil) and not event_entry.get("offer_accepted"):
        # Only block on pending HIL if NOT in offer acceptance flow
        state.set_thread_state("Waiting on HIL")
        set_hil_open(thread_id, True)
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "pending_decision": pending_decision,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
        }
        return GroupResult(action="negotiation_hil_waiting", payload=payload, halt=True)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    # -------------------------------------------------------------------------
    # UNIFIED CONFIRMATION GATE: Order-independent check for all prerequisites
    # Uses in-memory event_entry (which has latest billing) but reloads deposit
    # status from database (in case it was paid via frontend API)
    # -------------------------------------------------------------------------
    event_id = event_entry.get("event_id")
    if event_id and event_entry.get("offer_accepted"):
        from backend.workflows.common.confirmation_gate import check_confirmation_gate

        # First check in-memory state (has latest billing)
        gate_status = check_confirmation_gate(event_entry)

        # If deposit is required but not paid in memory, check database for API updates
        if gate_status.deposit_required and not gate_status.deposit_paid:
            _, db_status, fresh_entry = auto_continue_if_ready(event_id, event_entry)
            # If deposit was paid via API, update our status
            if db_status.deposit_paid:
                gate_status = db_status
                # Also update event_entry with fresh deposit info
                event_entry["deposit_info"] = fresh_entry.get("deposit_info", {})
                event_entry["deposit_state"] = fresh_entry.get("deposit_state", {})

        if gate_status.ready_for_hil:
            # All prerequisites met - continue to HIL
            # Use the existing _handle_accept flow
            response = _handle_accept(event_entry)
            # _handle_accept returns {"draft": {"body": ...}, ...}
            accept_draft = response.get("draft") or {}
            draft = {
                "body_markdown": accept_draft.get("body", "Offer accepted - pending final approval."),
                "step": 5,
                "topic": "offer_accepted_hil_gate_passed",
                "next_step": "Pending Final Approval",
                "thread_state": "Waiting on HIL",
                "requires_approval": True,
            }
            state.add_draft_message(draft)
            update_event_metadata(event_entry, current_step=5, thread_state="Waiting on HIL")
            state.set_thread_state("Waiting on HIL")
            set_hil_open(thread_id, True)
            state.extras["persist"] = True
            return GroupResult(
                action="offer_accept_pending_hil",
                payload={
                    "client_id": state.client_id,
                    "event_id": event_id,
                    "billing_complete": gate_status.billing_complete,
                    "deposit_paid": gate_status.deposit_paid,
                },
                halt=True,
            )

        # Not ready - check if we need to prompt for missing items
        next_prompt = get_next_prompt(gate_status, step=5)
        if next_prompt:
            state.add_draft_message(next_prompt)
            update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client")
            state.set_thread_state("Awaiting Client")
            state.extras["persist"] = True
            return GroupResult(
                action="awaiting_prerequisites",
                payload={
                    "pending": gate_status.pending_items,
                    "billing_complete": gate_status.billing_complete,
                    "deposit_paid": gate_status.deposit_paid,
                },
                halt=True,
            )

    message_text = (state.message.body or "").strip()
    user_info = state.user_info or {}

    # [CHANGE DETECTION] Run FIRST to detect structural changes
    # Pass message_text so we can parse dates directly from the message
    structural = _detect_structural_change(state.user_info, event_entry, message_text)

    if structural:
        # Handle structural change detour BEFORE Q&A
        target_step, reason = structural
        update_event_metadata(event_entry, caller_step=5, current_step=target_step)
        append_audit_entry(event_entry, 5, target_step, reason)
        negotiation_state["counter_count"] = 0
        # Clear stale negotiation state when detouring - old offer no longer valid
        if target_step in {2, 3}:
            event_entry.pop("negotiation_pending_decision", None)
        state.caller_step = 5
        state.current_step = target_step
        if target_step in {2, 3}:
            state.set_thread_state("Awaiting Client")
        else:
            state.set_thread_state("Waiting on HIL")
        state.extras["persist"] = True
        return GroupResult(
            action="structural_change_detour",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "detour_to_step": target_step,
                "caller_step": 5,
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
        # Route to Step 7 for site visit handling
        update_event_metadata(event_entry, current_step=7)
        state.current_step = 7
        state.extras["persist"] = True
        return GroupResult(
            action="route_to_site_visit",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "reason": "site_visit_in_progress",
                "persisted": True,
            },
            halt=False,  # Continue to Step 7
        )
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
            owner_step="Step5_Negotiation",
        )

    classification, classification_confidence = _classify_message(message_text)
    detected_intents = _collect_detected_intents(message_text)

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(classification_confidence, message_text)
    if nonsense_action == "ignore":
        # Silent ignore - no reply, no further processing
        return GroupResult(
            action="nonsense_ignored",
            payload={"reason": "low_confidence_no_workflow_signal", "step": 5},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=5,
                next_step=5,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 5},
            halt=True,
        )
    # -------------------------------------------------------------------------

    # Handle Q&A if detected (after change detection, before negotiation classification)
    general_qna_applicable = qna_classification.get("is_general")
    deferred_general_qna = general_qna_applicable and classification in {"accept", "decline", "counter"}
    if general_qna_applicable and not deferred_general_qna:
        result = _present_general_room_qna(state, event_entry, qna_classification, thread_id)
        return result

    if should_seek_clarification(classification_confidence):
        result = _ask_classification_clarification(
            state,
            event_entry,
            message_text,
            detected_intents,
            confidence=classification_confidence,
        )
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "room_selection":
        result = _ask_classification_clarification(
            state,
            event_entry,
            message_text,
            detected_intents,
            confidence=classification_confidence,
        )
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "accept":
        # Mark offer as accepted - this MUST be set for billing flow bypass to work
        # (Bug fix: step5 was missing this, causing offer_accepted=None during billing)
        event_entry["offer_accepted"] = True
        state.extras["persist"] = True

        # ---------------------------------------------------------------------
        # COMBINED ACCEPT + BILLING: Capture billing from same message
        # When client sends "Yes, I accept. Billing: [address]", the billing
        # info is in user_info but wasn't being captured before refresh check.
        # ---------------------------------------------------------------------
        billing_from_message = user_info.get("billing_address")
        if billing_from_message and str(billing_from_message).strip():
            event_entry.setdefault("event_data", {})["Billing Address"] = str(billing_from_message).strip()
            state.extras["persist"] = True

        billing_missing = _refresh_billing(event_entry)
        if billing_missing:
            _flag_billing_accept_pending(event_entry, billing_missing)
            prompt = _billing_prompt_draft(billing_missing, step=5)
            state.add_draft_message(prompt)
            append_audit_entry(event_entry, 5, 5, "offer_accept_blocked_missing_billing")
            negotiation_state["counter_count"] = 0
            update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client", transition_ready=False)
            state.current_step = 5
            state.set_thread_state("Awaiting Client")
            set_hil_open(thread_id, False)
            state.extras["persist"] = True
            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "missing": billing_missing,
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            result = GroupResult(action="negotiation_accept_missing_billing", payload=payload, halt=True)
            if deferred_general_qna:
                _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
            return result

        result = _start_hil_acceptance(state, event_entry, thread_id, audit_label="offer_accept_pending_hil", action="negotiation_accept_pending_hil")
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "decline":
        response = _handle_decline(event_entry)
        state.add_draft_message(response)
        append_audit_entry(event_entry, 5, 7, "offer_declined")
        negotiation_state["counter_count"] = 0
        update_event_metadata(event_entry, current_step=7, thread_state="In Progress")
        state.current_step = 7
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
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
        result = GroupResult(action="negotiation_decline", payload=payload, halt=False)
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "counter":
        negotiation_state["counter_count"] = int(negotiation_state.get("counter_count") or 0) + 1
        if negotiation_state["counter_count"] > MAX_COUNTER_PROPOSALS:
            manual_id = negotiation_state.get("manual_review_task_id")
            if not manual_id:
                manual_payload = {
                    "reason": "negotiation_counter_limit",
                    "message_preview": message_text[:160],
                }
                manual_id = enqueue_task(
                    state.db,
                    TaskType.MANUAL_REVIEW,
                    state.client_id or "",
                    event_entry.get("event_id"),
                    manual_payload,
                )
                negotiation_state["manual_review_task_id"] = manual_id
            draft = {
                "body": append_footer(
                    "Thanks for the suggestions. I've escalated this to our manager to review pricing. "
                    "We'll get back to you shortly.",
                    step=5,
                    next_step=5,
                    thread_state="Awaiting Client Response",
                ),
                "step": 5,
                "topic": "negotiation_manual_review",
                "requires_approval": True,
            }
            state.add_draft_message(draft)
            update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client Response")
            state.set_thread_state("Awaiting Client Response")
            state.extras["persist"] = True
            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
                "manual_review_task_id": manual_id,
            }
            result = GroupResult(action="negotiation_manual_review", payload=payload, halt=True)
            if deferred_general_qna:
                _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
            return result

        update_event_metadata(event_entry, caller_step=5, current_step=4)
        append_audit_entry(event_entry, 5, 4, "negotiation_counter")
        state.caller_step = 5
        state.current_step = 4
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "counter_count": negotiation_state["counter_count"],
            "context": state.context_snapshot,
            "persisted": True,
        }
        result = GroupResult(action="negotiation_counter", payload=payload, halt=False)
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    # Clarification by default.
    clarification = {
        "body": append_footer(
            "Happy to clarify any part of the proposal. Let me know which detail you'd like more information on.",
            step=5,
            next_step=5,
            thread_state="Awaiting Client Response",
        ),
        "step": 5,
        "topic": "negotiation_clarification",
        "requires_approval": True,
    }
    state.add_draft_message(clarification)
    update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
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
    result = GroupResult(action="negotiation_clarification", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
    return result


def _ask_classification_clarification(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    message_text: str,
    detected_intents: List[Tuple[str, float]],
    *,
    confidence: float = 0.0,
) -> GroupResult:
    """
    Generate a clarifying question when classification is uncertain.
    """
    options: List[str] = []
    if any(intent == "accept" for intent, _ in detected_intents):
        options.append("confirm the booking")
    if any(intent == "counter" for intent, _ in detected_intents):
        options.append("discuss pricing")
    if any(intent == "decline" for intent, _ in detected_intents):
        options.append("pause or cancel")
    if any(intent == "room_selection" for intent, _ in detected_intents):
        options.append("choose a room")
    if any(intent == "clarification" for intent, _ in detected_intents):
        options.append("ask a question")

    if not options:
        options.append("clarify the proposal")

    prompt = (
        "I want to make sure I understand correctly. "
        f"Did you mean to {' or '.join(options)}? "
        "Please let me know so I can help you best."
    )
    draft = {
        "body": append_footer(
            prompt,
            step=5,
            next_step=5,
            thread_state="Awaiting Client Response",
        ),
        "step": 5,
        "topic": "classification_clarification",
        "requires_approval": should_defer_to_human(confidence),
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.current_step = 5
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "classification_confidence": confidence,
        "detected_intents": detected_intents,
    }
    return GroupResult(action="negotiation_clarification", payload=payload, halt=True)


def _detect_structural_change(
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    message_text: str = "",
) -> Optional[tuple[int, str]]:
    # -------------------------------------------------------------------------
    # ACCEPTANCE GUARD: Skip change detection for acceptance messages
    # LLM extraction may produce false positive "room" values from acceptance
    # messages like "I accept" which should NOT trigger room change detection.
    # -------------------------------------------------------------------------
    if message_text:
        is_acceptance, confidence, _ = matches_acceptance_pattern(message_text.lower())
        if is_acceptance and confidence >= 0.7:
            # Message looks like an acceptance - skip all change detection
            return None

    # Skip date change detection when in site visit mode
    # Dates mentioned are for the site visit, not event date changes
    visit_state = event_entry.get("site_visit_state") or {}
    in_site_visit_mode = visit_state.get("status") in {"proposed"}

    # First check user_info (from LLM extraction)
    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if not in_site_visit_mode and (new_iso_date or new_ddmmyyyy):
        candidate = new_ddmmyyyy or _iso_to_ddmmyyyy(new_iso_date)
        if candidate and candidate != event_entry.get("chosen_date"):
            # -------------------------------------------------------------------------
            # HALLUCINATION GUARD: Verify the date actually appears in the message
            # LLM may hallucinate dates (e.g., today's date) for messages without dates.
            # Only treat as date change if the date appears in the actual message text.
            # -------------------------------------------------------------------------
            if message_text:
                date_in_message = False
                # Check if DD.MM.YYYY format appears
                if candidate and candidate in message_text:
                    date_in_message = True
                # Check if ISO format appears
                elif new_iso_date and new_iso_date in message_text:
                    date_in_message = True
                else:
                    # Parse dates from message directly and compare
                    parsed_dates = list(parse_all_dates(message_text, fallback_year=dt_date.today().year))
                    parsed_iso = {d.isoformat() for d in parsed_dates}
                    if new_iso_date and new_iso_date in parsed_iso:
                        date_in_message = True

                if not date_in_message:
                    # Date was likely hallucinated by LLM - skip date change detection
                    # Let the requirements/room/product checks below handle it
                    pass
                else:
                    return 2, "negotiation_changed_date"
            else:
                return 2, "negotiation_changed_date"

    # Fallback: parse dates directly from message text (same as Step 2/3/4)
    # This catches cases where user_info wasn't populated with the new date
    if not in_site_visit_mode and message_text:
        chosen_date_raw = event_entry.get("chosen_date")  # e.g., "14.02.2026"
        if chosen_date_raw:
            chosen_parsed = parse_ddmmyyyy(chosen_date_raw)
            chosen_iso = chosen_parsed.isoformat() if chosen_parsed else None
            message_dates = list(parse_all_dates(message_text, fallback_year=dt_date.today().year))
            # Check if any date in the message differs from the current chosen_date
            for msg_date in message_dates:
                msg_iso = msg_date.isoformat()
                if chosen_iso and msg_iso != chosen_iso:
                    # Found a different date in the message - this is a date change request
                    return 2, "negotiation_changed_date"

    new_room = user_info.get("room")
    if new_room and new_room != event_entry.get("locked_room_id"):
        return 3, "negotiation_changed_room"

    participants = user_info.get("participants")
    req = event_entry.get("requirements") or {}
    if participants and participants != req.get("number_of_participants"):
        return 3, "negotiation_changed_participants"

    products_add = user_info.get("products_add")
    products_remove = user_info.get("products_remove")
    if products_add or products_remove:
        return 4, "negotiation_changed_products"

    return None


def _apply_hil_negotiation_decision(state: WorkflowState, event_entry: Dict[str, Any], decision: str) -> GroupResult:
    """Process HIL approval/decline for Step 5 offer acceptance."""

    thread_id = _thread_id(state)
    pending = event_entry.get("negotiation_pending_decision")
    if not pending:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_negotiation_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="negotiation_hil_missing", payload=payload, halt=True)

    if decision != "approve":
        event_entry.pop("negotiation_pending_decision", None)
        append_audit_entry(event_entry, 5, 5, "offer_hil_rejected")
        draft = {
            "body": append_footer(
                "Manager declined this offer version. Please adjust and resend.",
                step=5,
                next_step=5,
                thread_state="Awaiting Client",
            ),
            "step": 5,
            "topic": "negotiation_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        set_hil_open(thread_id, False)
        state.extras["persist"] = True
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
        return GroupResult(action="negotiation_hil_rejected", payload=payload, halt=True)

    # Approval path
    offer_id = pending.get("offer_id") or event_entry.get("current_offer_id")
    offers = event_entry.get("offers") or []
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = timestamp
    event_entry["offer_status"] = "Accepted"
    event_entry.pop("negotiation_pending_decision", None)
    append_audit_entry(event_entry, 5, 6, "offer_accepted_hil")
    update_event_metadata(event_entry, current_step=6, thread_state="In Progress")
    state.current_step = 6
    state.set_thread_state("In Progress")
    set_hil_open(thread_id, False)
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": offer_id,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="negotiation_hil_approved", payload=payload, halt=False)

# NOTE: _auto_accept_if_billing_ready was removed (dead code) - replaced by confirmation_gate.py


def _start_hil_acceptance(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    thread_id: str,
    *,
    audit_label: str,
    action: str,
) -> GroupResult:
    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    negotiation_state["counter_count"] = 0

    # Drop stale HIL requests for other steps so only one approval task remains visible.
    pending_records = event_entry.get("pending_hil_requests") or []
    pruned: list[Dict[str, Any]] = []
    existing_signatures: set[str] = set()
    for entry in pending_records:
        signature = entry.get("signature")
        if entry.get("step") != 5:
            task_id = entry.get("task_id")
            if task_id:
                try:
                    update_task_status(state.db, task_id, TaskStatus.DONE)
                except Exception:
                    pass
            continue
        if signature:
            existing_signatures.add(signature)
        pruned.append(entry)
    event_entry["pending_hil_requests"] = pruned

    response = _handle_accept(event_entry)
    state.add_draft_message(response["draft"])
    pending_records = event_entry.setdefault("pending_hil_requests", [])
    draft_signature = f"step5:{response['pending'].get('offer_id')}"
    existing_signatures = {entry.get("signature") for entry in pending_records if entry.get("signature")}
    task_id: Optional[str] = None
    if draft_signature not in existing_signatures:
        task_payload = {
            "step_id": 5,
            "intent": state.intent.value if state.intent else None,
            "event_id": event_entry.get("event_id"),
            "draft_msg": response["draft"].get("body"),
            "draft_body": response["draft"].get("body"),
            "language": (state.user_info or {}).get("language"),
            "caller_step": event_entry.get("caller_step"),
            "requirements_hash": event_entry.get("requirements_hash"),
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "thread_id": thread_id,
        }
        client_id = state.client_id or (state.message.from_email if state.message else "unknown@example.com")
        task_id = enqueue_task(
            state.db,
            TaskType.OFFER_MESSAGE,
            client_id,
            event_entry.get("event_id"),
            task_payload,
        )
        pending_records.append(
            {
                "task_id": task_id,
                "signature": draft_signature,
                "step": 5,
                "draft": dict(response["draft"]),
                "thread_id": thread_id,
            }
        )
        state.extras["persist"] = True
    else:
        task_id = next((entry.get("task_id") for entry in pending_records if entry.get("signature") == draft_signature), None)
    append_audit_entry(event_entry, 5, 5, audit_label)
    update_event_metadata(event_entry, current_step=5, thread_state="Waiting on HIL", transition_ready=False)
    event_entry["negotiation_pending_decision"] = response["pending"]
    state.current_step = 5
    state.set_thread_state("Waiting on HIL")
    set_hil_open(thread_id, True)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": response["offer_id"],
        "pending_decision": response["pending"],
        "pending_task_id": task_id,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action=action, payload=payload, halt=True)


def _offer_summary_lines(event_entry: Dict[str, Any], *, include_cta: bool = True) -> list[str]:
    """Recreate the offer body (with totals) so HIL sees exactly what the client saw."""

    chosen_date = event_entry.get("chosen_date") or "Date TBD"
    room = event_entry.get("locked_room_id") or "Room TBD"
    event_data = event_entry.get("event_data") or {}
    billing_details = event_entry.get("billing_details") or {}
    billing_address = format_billing_display(billing_details, event_data.get("Billing Address"))
    email = (event_data.get("Email") or "").strip() or None
    contact_parts = [
        part.strip()
        for part in (event_data.get("Name"), event_data.get("Company"))
        if isinstance(part, str) and part.strip() and part.strip().lower() != "not specified"
    ]
    if email and email.lower() != "not specified":
        contact_parts.append(email)
    products = event_entry.get("products") or []
    products_state = event_entry.get("products_state") or {}
    autofill_summary = products_state.get("autofill_summary") or {}
    matched_summary = autofill_summary.get("matched") or []
    product_alternatives = autofill_summary.get("alternatives") or []
    catering_alternatives = autofill_summary.get("catering_alternatives") or []
    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))

    intro_room = room if room != "Room TBD" else "your preferred room"
    intro_date = chosen_date if chosen_date != "Date TBD" else "your requested date"
    lines: list[str] = []
    if manager_requested:
        lines.append(f"Great, {intro_room} on {intro_date} is ready for manager review.")
    lines.append(f"Offer draft for {chosen_date} · {room}")
    lines.append("")

    if contact_parts or billing_address:
        if contact_parts:
            lines.append("Client: " + " · ".join(contact_parts))
        if billing_address:
            lines.append(f"Billing address: {billing_address}")
        lines.append("")

    if matched_summary:
        lines.append("**Included products**")
        for entry in matched_summary:
            normalised = _normalise_product_fields(entry, menu_names=_menu_name_set())
            quantity = int(normalised.get("quantity") or 1)
            name = normalised.get("name") or "Unnamed item"
            unit_price = float(normalised.get("unit_price") or 0.0)
            total_line = float(entry.get("total") or quantity * unit_price)
            unit = normalised.get("unit")
            wish = entry.get("wish")

            price_text = f"CHF {total_line:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"
            elif unit == "per_event":
                price_text += " (per event)"

            details = []
            if entry.get("match_pct") is not None:
                details.append(f"match {entry.get('match_pct')}%")
            if wish:
                details.append(f'for "{wish}"')
            detail_text = f" ({', '.join(details)})" if details else ""

            lines.append(f"- {quantity}× {name}{detail_text} · {price_text}")
    elif products:
        lines.append("**Included products**")
        for product in products:
            normalised = _normalise_product_fields(product, menu_names=_menu_name_set())
            quantity = int(normalised.get("quantity") or 1)
            name = normalised.get("name") or "Unnamed item"
            unit_price = float(normalised.get("unit_price") or 0.0)
            unit = normalised.get("unit")

            price_text = f"CHF {unit_price * quantity:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"
            elif unit == "per_event":
                price_text += " (per event)"

            lines.append(f"- {quantity}× {name} · {price_text}")
    else:
        lines.append("No optional products selected yet.")

    total_amount = _determine_offer_total(event_entry)

    lines.extend(
        [
            "",
            "---",
            f"**Total: CHF {total_amount:,.2f}**",
            "---",
            "",
        ]
    )

    has_alternatives = product_alternatives or catering_alternatives
    if has_alternatives:
        lines.append("**Suggestions for you**")
        lines.append("")

    if product_alternatives:
        lines.append("*Other close matches you can add:*")
        for entry in product_alternatives:
            name = entry.get("name") or "Unnamed add-on"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit = entry.get("unit")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            price_text = f"CHF {unit_price:,.2f}"
            if unit == "per_person":
                price_text += " per person"

            qualifiers = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            qualifier_text = f" ({', '.join(qualifiers)})" if qualifiers else ""

            lines.append(f"- {name}{qualifier_text} · {price_text}")
        if catering_alternatives:
            lines.append("")

    if catering_alternatives:
        lines.append("*Catering alternatives with a close fit:*")
        for entry in catering_alternatives:
            name = entry.get("name") or "Catering option"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit_label = (entry.get("unit") or "per event").replace("_", " ")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            qualifiers = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            detail = ", ".join(qualifiers)
            detail_text = f" ({detail})" if detail else ""

            lines.append(f"- {name}{detail_text} · CHF {unit_price:,.2f} {unit_label}")

    if has_alternatives:
        lines.append("")

    if include_cta:
        manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))
        if manager_requested:
            lines.append("Please review and approve before sending to the manager.")
        else:
            lines.append("Please review and approve to confirm.")
    return lines


def _clear_stale_hil_requests(state: WorkflowState, event_entry: Dict[str, Any], keep_steps: set[int]) -> None:
    """Mark older HIL requests as done so only the relevant step stays visible."""

    pending = event_entry.get("pending_hil_requests") or []
    remaining = []
    changed = False
    for entry in pending:
        step = entry.get("step")
        task_id = entry.get("task_id")
        if step in keep_steps:
            remaining.append(entry)
            continue
        if task_id:
            try:
                update_task_status(state.db, task_id, TaskStatus.DONE)
            except Exception:
                pass
        changed = True
    if changed:
        event_entry["pending_hil_requests"] = remaining
        state.extras["persist"] = True


def _handle_accept(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pending = {
        "type": "accept",
        "offer_id": offer_id,
        "created_at": timestamp,
    }
    summary_lines = _offer_summary_lines(event_entry)
    draft = {
        "body": append_footer(
            "Client accepted the offer. Please approve to proceed to confirmation.\n\n" + "\n".join(summary_lines),
            step=5,
            next_step=5,
            thread_state="Waiting on HIL",
        ),
        "step": 5,
        "topic": "negotiation_accept",
        "requires_approval": True,
    }
    return {"offer_id": offer_id, "draft": draft, "pending": pending}


def _handle_decline(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offers = event_entry.get("offers") or []
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Declined"
            offer["declined_at"] = timestamp
    event_entry["offer_status"] = "Declined"
    return {
        "body": append_footer(
            "Thank you for letting me know. I've noted the cancellation. We'd be happy to help with future events anytime.",
            step=5,
            next_step=7,
            thread_state="In Progress",
        ),
        "step": 5,
        "topic": "negotiation_decline",
        "requires_approval": True,
    }


def _determine_offer_total(event_entry: Dict[str, Any]) -> float:
    """Compute the offer total with multiple fallbacks so HIL sees the real number."""

    offers = event_entry.get("offers") or []
    current_offer_id = event_entry.get("current_offer_id")
    total_candidates = []
    for offer in offers:
        if offer.get("offer_id") == current_offer_id:
            total_candidates.append(offer.get("total_amount"))
            break

    pricing_inputs = event_entry.get("pricing_inputs") or {}
    total_candidates.extend([pricing_inputs.get("total_amount"), pricing_inputs.get("total")])

    computed_total = 0.0
    base_rate = normalise_rate(pricing_inputs.get("base_rate"))
    if base_rate is None:
        base_rate = derive_room_rate(event_entry)
    if base_rate is not None:
        computed_total += base_rate

    for product in event_entry.get("products") or []:
        normalised = _normalise_product_fields(product, menu_names=_menu_name_set())
        try:
            quantity = float(normalised.get("quantity") or 0)
            unit_price = float(normalised.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            continue
        computed_total += quantity * unit_price

    for candidate in total_candidates:
        try:
            value = float(candidate)
            if value > 0:
                return round(value, 2)
        except (TypeError, ValueError):
            continue

    if computed_total > 0:
        return round(computed_total, 2)
    return 0.0


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
    """Handle general Q&A at Step 5 - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id,
        step_number=5, step_name="Negotiation"
    )


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
