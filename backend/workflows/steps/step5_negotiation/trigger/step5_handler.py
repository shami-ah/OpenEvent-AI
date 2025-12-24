from __future__ import annotations

import re
from datetime import date as dt_date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
from backend.workflows.common.general_qna import append_general_qna_to_primary, _fallback_structured_body
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io import database as db_io
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

__all__ = ["process"]

MAX_COUNTERS = 3


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

    # If a manager decision is already pending, keep waiting instead of spamming duplicates.
    pending_decision = event_entry.get("negotiation_pending_decision")
    pending_hil = [
        req for req in (event_entry.get("pending_hil_requests") or []) if req.get("step") == 5
    ]
    if pending_decision or pending_hil:
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

    billing_req = event_entry.get("billing_requirements") or {}
    print(f"[Step5][DEBUG] awaiting_billing_for_accept={billing_req.get('awaiting_billing_for_accept')}")
    if billing_req.get("awaiting_billing_for_accept"):
        # Skip billing capture for synthetic deposit payment messages
        # (their body is "I have paid the deposit." which would corrupt billing)
        is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
        print(f"[Step5][DEBUG] is_deposit_signal={is_deposit_signal}")
        if not is_deposit_signal:
            message_text = (state.message.body or "").strip()
            print(f"[Step5][DEBUG] message_text={repr(message_text[:100] if message_text else '')}")
            if message_text:
                event_entry.setdefault("event_data", {})["Billing Address"] = message_text
                state.extras["persist"] = True
                print(f"[Step5][DEBUG] ✅ Captured billing address: {message_text[:50]}...")
                # FORCE SAVE: Ensure billing is persisted immediately
                # This fixes the bug where deferred persistence wasn't saving billing
                try:
                    db_io.save_db(state.db, state.db_path)
                    print(f"[Step5][DEBUG] ✅ FORCE SAVED billing to database")
                except Exception as save_err:
                    print(f"[Step5][ERROR] Failed to force save billing: {save_err}")

    billing_missing = _refresh_billing(event_entry)
    state.extras["persist"] = True
    # FORCE SAVE after billing refresh to ensure billing_details is persisted
    try:
        db_io.save_db(state.db, state.db_path)
        print(f"[Step5][DEBUG] ✅ FORCE SAVED after billing refresh (billing_missing={billing_missing})")
    except Exception as save_err:
        print(f"[Step5][ERROR] Failed to save after billing refresh: {save_err}")

    # Clear awaiting_billing_for_accept once billing is complete
    if not billing_missing and billing_req.get("awaiting_billing_for_accept"):
        billing_req["awaiting_billing_for_accept"] = False
        billing_req["last_missing"] = []
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
            print(f"[Step5] Confirmation gate passed: billing_complete={gate_status.billing_complete}, "
                  f"deposit_required={gate_status.deposit_required}, deposit_paid={gate_status.deposit_paid}")
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
        if negotiation_state["counter_count"] > MAX_COUNTERS:
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
                    "Thanks for the suggestions — I’ve escalated this to our manager to review pricing. "
                    "We’ll get back to you shortly.",
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
            "Happy to clarify any part of the proposal — let me know which detail you’d like more information on.",
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


def _collect_detected_intents(message_text: str) -> List[Tuple[str, float]]:
    lowered = (message_text or "").lower()
    intents: List[Tuple[str, float]] = []

    if is_room_selection(lowered):
        intents.append(("room_selection", 0.85))

    accept, accept_conf, _ = matches_acceptance_pattern(lowered)
    if accept:
        intents.append(("accept", accept_conf))

    decline, decline_conf, _ = matches_decline_pattern(lowered)
    if decline:
        intents.append(("decline", decline_conf))

    counter, counter_conf, _ = matches_counter_pattern(lowered)
    if counter:
        intents.append(("counter", counter_conf))

    if re.search(r"\bchf\s*\d", lowered) or re.search(r"\d+\s*(?:franc|price|total)", lowered):
        intents.append(("counter", 0.65))

    if "?" in lowered:
        intents.append(("clarification", 0.6))

    return intents


def _classify_message(message_text: str) -> Tuple[str, float]:
    lowered = (message_text or "").lower()
    candidates = _collect_detected_intents(lowered)

    if candidates:
        best = max(candidates, key=lambda item: item[1])
        if best[1] > 0.4:
            return best

    if "?" in lowered:
        return "clarification", 0.6

    return "clarification", 0.3


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


def _refresh_billing(event_entry: Dict[str, Any]) -> list[str]:
    """Parse and persist billing details, returning missing required fields."""

    update_billing_details(event_entry)
    details = event_entry.get("billing_details") or {}
    missing = missing_billing_fields(event_entry)
    has_filled_required = len(missing) < 5
    display = format_billing_display(details, (event_entry.get("event_data") or {}).get("Billing Address"))
    if display and has_filled_required:
        event_entry.setdefault("event_data", {})["Billing Address"] = display

    validation = event_entry.setdefault("billing_validation", {})
    if missing:
        validation["missing"] = list(missing)
    else:
        validation.pop("missing", None)
    return missing


def _flag_billing_accept_pending(event_entry: Dict[str, Any], missing_fields: list[str]) -> None:
    gate = event_entry.setdefault("billing_requirements", {})
    gate["awaiting_billing_for_accept"] = True
    gate["last_missing"] = list(missing_fields)


def _auto_accept_if_billing_ready(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    thread_id: str,
    missing_fields: list[str],
) -> Optional[GroupResult]:
    gate = event_entry.get("billing_requirements") or {}
    if not gate.get("awaiting_billing_for_accept"):
        return None
    if missing_fields:
        gate["last_missing"] = list(missing_fields)
        return None

    gate["awaiting_billing_for_accept"] = False
    gate["last_missing"] = []
    return _start_hil_acceptance(
        state,
        event_entry,
        thread_id,
        audit_label="offer_accept_pending_hil_auto",
        action="negotiation_accept_pending_hil",
    )


def _billing_prompt_draft(missing_fields: list[str], *, step: int) -> Dict[str, Any]:
    prompt = (
        "Thanks for confirming — I need the billing address before I can send this for approval.\n"
        f"{billing_prompt_for_missing_fields(missing_fields)} "
        "Example: \"Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland\". "
        "As soon as I have it, I'll forward the offer automatically."
    )
    return {
        "body_markdown": prompt,
        "step": step,
        "topic": "billing_details_required",
        "next_step": "Await billing details",
        "thread_state": "Awaiting Client",
        "requires_approval": False,
    }


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
        lines.append(f"Great — {intro_room} on {intro_date} is ready for manager review.")
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
            "Thank you for letting me know. I’ve noted the cancellation — we’d be happy to help with future events anytime.",
            step=5,
            next_step=7,
            thread_state="In Progress",
        ),
        "step": 5,
        "topic": "negotiation_decline",
        "requires_approval": True,
    }


def _iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not match:
        return None
    year, month, day = match.groups()
    return f"{day}.{month}.{year}"


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
    """Handle general Q&A at Step 5 using the same pattern as Step 2."""
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
            step=5,
            next_step=5,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 5,
            "next_step": 5,
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
            current_step=5,
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
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
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
        "step": 5,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 5 Negotiation · Next: 5 Negotiation · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 5,
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
        current_step=5,
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
