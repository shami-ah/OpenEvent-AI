from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
from typing import Any, Dict

from workflows.common.prompts import append_footer
from workflows.common.requirements import merge_client_profile
from workflows.common.types import GroupResult, WorkflowState
from workflows.change_propagation import route_change_on_updated_variable

from domain import IntentLabel
from debug.hooks import (
    trace_entity,
    trace_marker,
    trace_state,
    trace_step,
)
from workflows.io.database import (
    append_history,
    append_audit_entry,
    context_snapshot,
    last_event_for_email,
    tag_message,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
from services import client_memory
from ..billing_flow import handle_billing_capture
from workflows.qna.router import generate_hybrid_qna_response
from detection.intent.classifier import _detect_qna_types

# Extracted pure helpers (I1 refactoring)
from .normalization import normalize_quotes as _normalize_quotes
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from workflows.common.detection_utils import get_unified_detection

# I2 refactoring: Extracted modules
from .event_bootstrap import ensure_event_record as _ensure_event_record
from .billing_detection import extract_billing_from_body as _extract_billing_from_body
from .early_detection import (
    detect_confirmation as _detect_confirmation,
    detect_offer_acceptance as _detect_offer_acceptance,
    detect_qna_signals as _detect_qna_signals,
    detect_early_room_choice as _detect_early_room_choice,
    detect_early_menu_choice as _detect_early_menu_choice,
    should_boost_confidence as _should_boost_confidence,
)
from .manual_review_gate import (
    check_manual_review_gate as _check_manual_review_gate,
    GateDecision as _GateDecision,
)
from .room_shortcut import (
    check_past_date as _check_past_date,
    check_shortcut_eligibility as _check_shortcut_eligibility,
    evaluate_smart_shortcut as _evaluate_smart_shortcut,
    apply_smart_shortcut as _apply_smart_shortcut,
)
from .room_confirmation import (
    check_room_confirmation as _check_room_confirmation,
    apply_room_confirmation as _apply_room_confirmation,
    RoomConfirmDecision as _RoomConfirmDecision,
)
from .change_routing_step1 import (
    build_change_context as _build_change_context,
    detect_change_with_guards as _detect_change_with_guards,
    should_skip_vague_date_reset as _should_skip_vague_date_reset,
)
from .change_fallback import (
    check_date_fallback as _check_date_fallback,
    check_missing_date_fallback as _check_missing_date_fallback,
    check_requirements_hash_fallback as _check_requirements_hash_fallback,
    check_room_preference_fallback as _check_room_preference_fallback,
    FallbackAction as _FallbackAction,
)
from .change_application import apply_dag_routing as _apply_dag_routing
from .classification_extraction import classify_and_extract as _classify_and_extract

# I1 Phase 1: Intent helpers
from .intent_helpers import resolve_owner_step as _resolve_owner_step

# I1 Phase 2: Product detection
from .product_detection import detect_product_update_request as _detect_product_update_request

# I2: Requirements fallback
from .requirements_fallback import process_requirements as _process_requirements

# Dev/test mode helper (I2 refactoring)
from .dev_test_mode import maybe_show_dev_choice as _maybe_show_dev_choice

__workflow_role__ = "trigger"


# Generic product suffixes that shouldn't match standalone.
# These appear as the last word in product names (e.g., "Vegetarian Menu")
# but are too ambiguous to match without the full product name context.
@trace_step("Step1_Intake")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""
    message_payload = state.message.to_payload()
    thread_id = _thread_id(state)

    # Resolve owner step for tracing based on existing conversation state
    email = (message_payload.get("from_email") or "").lower()
    linked_event = last_event_for_email(state.db, email) if email else None
    current_step = linked_event.get("current_step") if linked_event else 1
    # Fallback if current_step is None/invalid
    if not isinstance(current_step, int):
        current_step = 1
    owner_step = _resolve_owner_step(current_step)

    # [TESTING CONVENIENCE] Dev/test mode choice prompt (I2 extraction)
    skip_dev_choice = state.extras.get("skip_dev_choice", False)
    dev_choice_result = _maybe_show_dev_choice(
        linked_event=linked_event,
        current_step=current_step,
        owner_step=owner_step,
        client_email=email,
        skip_dev_choice=skip_dev_choice,
    )
    if dev_choice_result:
        return dev_choice_result

    trace_marker(
        thread_id,
        "TRIGGER_Intake",
        detail=message_payload.get("subject"),
        data={"msg_id": state.message.msg_id},
        owner_step=owner_step,
    )

    # LLM classification and entity extraction (extracted module)
    classification = _classify_and_extract(message_payload, thread_id, owner_step)
    intent = classification.intent
    confidence = classification.confidence
    user_info = classification.user_info
    needs_vague_date_confirmation = classification.needs_vague_date_confirmation
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = classification.intent_detail
    if classification.shortcut_detected:
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")
    _trace_user_entities(state, message_payload, user_info, owner_step)

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    # linked_event is already fetched above
    body_text_raw = message_payload.get("body") or ""
    body_text = _normalize_quotes(body_text_raw)
    fallback_year = _fallback_year_from_ts(message_payload.get("ts"))

    # [EARLY DETECTION] Use extracted module for confirmation detection
    confirmation_result = _detect_confirmation(body_text, linked_event, user_info, fallback_year)
    confirmation_detected = confirmation_result.detected
    if confirmation_detected:
        user_info["date"] = confirmation_result.iso_date
        user_info["event_date"] = confirmation_result.event_date
        if confirmation_result.start_time and "start_time" not in user_info:
            user_info["start_time"] = confirmation_result.start_time
        if confirmation_result.end_time and "end_time" not in user_info:
            user_info["end_time"] = confirmation_result.end_time

    # [EARLY DETECTION] Use extracted module for offer acceptance detection
    acceptance_result = _detect_offer_acceptance(body_text, linked_event)
    if acceptance_result.detected and linked_event:
        intent = IntentLabel.EVENT_REQUEST
        confidence = max(confidence, 0.99)
        state.intent = intent
        state.confidence = confidence
        if state.intent_detail in (None, "intake"):
            state.intent_detail = "event_intake_negotiation_accept"
        user_info.setdefault("hil_approve_step", acceptance_result.target_step)
        update_event_metadata(
            linked_event,
            current_step=acceptance_result.target_step,
            thread_state="Waiting on HIL",
            caller_step=None,
        )
        state.extras["persist"] = True

    # [EARLY DETECTION] Get unified detection for Q&A and room signals
    unified_detection = get_unified_detection(state)
    qna_signals = _detect_qna_signals(unified_detection)
    if qna_signals.should_set_general_qna:
        state.extras["general_qna_detected"] = True
        state.extras["_has_qna_types"] = True

    # [EARLY VALIDATION] Time slot validation against operating hours
    # Use unified detection times (LLM-extracted) - never re-parse from text
    from workflows.common.time_validation import validate_event_times
    time_validation = validate_event_times(
        start_time=unified_detection.start_time if unified_detection else None,
        end_time=unified_detection.end_time if unified_detection else None,
        is_site_visit=False,
    )
    if not time_validation.is_valid:
        logger.info(
            "[Step1][TIME_VALIDATION] Times outside hours: %s (start=%s, end=%s)",
            time_validation.issue, time_validation.start_time, time_validation.end_time
        )
        state.extras["time_warning"] = time_validation.friendly_message
        state.extras["time_warning_issue"] = time_validation.issue
        # Persist time warning to event_entry for traceability
        if linked_event is not None:
            linked_event.setdefault("time_validation", {})
            linked_event["time_validation"]["issue"] = time_validation.issue
            linked_event["time_validation"]["warning"] = time_validation.friendly_message
            linked_event["time_validation"]["start_time"] = time_validation.start_time
            linked_event["time_validation"]["end_time"] = time_validation.end_time

    # [EARLY DETECTION] Room choice detection
    room_result = _detect_early_room_choice(body_text, linked_event, unified_detection)
    if room_result.room_name:
        user_info["room"] = room_result.room_name
        user_info["_room_choice_detected"] = True
        state.extras["room_choice_selected"] = room_result.room_name
        logger.info("[Step1] Set _room_choice_detected=True for room=%s", room_result.room_name)
        if room_result.should_bump_confidence:
            confidence = 1.0
            intent = IntentLabel.EVENT_REQUEST
            state.intent = intent
            state.confidence = confidence

    # [EARLY DETECTION] Menu choice detection
    menu_result = _detect_early_menu_choice(body_text, linked_event, user_info)
    if menu_result.menu_name:
        user_info["menu_choice"] = menu_result.menu_name
        if menu_result.product_payload:
            existing = user_info.get("products_add") or []
            if isinstance(existing, list):
                user_info["products_add"] = existing + [menu_result.product_payload]
            else:
                user_info["products_add"] = [menu_result.product_payload]

    product_update_detected = _detect_product_update_request(message_payload, user_info, linked_event)
    if product_update_detected:
        state.extras["product_update_detected"] = True
        if not is_event_request(intent):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_product_update"
        elif state.intent_detail in (None, "intake", "event_intake"):
            state.intent_detail = "event_intake_product_update"
    state.user_info = user_info
    append_history(client, message_payload, intent.value, confidence, user_info)

    # Store in client memory for personalization (if enabled)
    client_memory.append_message(
        client,
        role="client",
        text=message_payload.get("body") or "",
        metadata={"intent": intent.value, "confidence": confidence},
    )
    # Update profile with detected language/preferences
    if user_info.get("language"):
        client_memory.update_profile(client, language=user_info["language"])

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    # [CONFIDENCE BOOST] Use extracted module for clear event request boost
    should_boost, boosted_confidence = _should_boost_confidence(intent, confidence, user_info)
    if should_boost:
        confidence = boosted_confidence
        state.confidence = confidence

    # [MANUAL REVIEW GATE] Check if message needs special handling
    gate_result = _check_manual_review_gate(
        intent=intent,
        confidence=confidence,
        linked_event=linked_event,
        message_payload=message_payload,
        user_info=user_info,
        unified_detection=unified_detection,
        state_message=state.message,
    )

    # Apply gate result
    if gate_result.decision != _GateDecision.CONTINUE:
        if gate_result.decision == _GateDecision.STANDALONE_QNA:
            state.add_draft_message({
                "body": gate_result.qna_response,
                "step": 1,
                "topic": "standalone_qna",
            })
            state.set_thread_state("Awaiting Client")
            return GroupResult(
                action="standalone_qna",
                payload={
                    "client_id": state.client_id,
                    "event_id": None,
                    "intent": gate_result.intent.value,
                    "confidence": round(gate_result.confidence, 3),
                    "draft_messages": state.draft_messages,
                    "thread_state": state.thread_state,
                    "standalone_qna": True,
                },
                halt=True,
            )
        elif gate_result.decision == _GateDecision.MANUAL_REVIEW:
            trace_marker(
                thread_id,
                "CONDITIONAL_HIL",
                detail="manual_review_required",
                data={"intent": gate_result.intent.value, "confidence": round(gate_result.confidence, 3)},
                owner_step=owner_step,
            )
            linked_event_id = linked_event.get("event_id") if linked_event else None
            task_id = enqueue_manual_review_task(
                state.db,
                state.client_id,
                linked_event_id,
                {
                    "subject": message_payload.get("subject"),
                    "snippet": (message_payload.get("body") or "")[:200],
                    "ts": message_payload.get("ts"),
                    "reason": "manual_review_required",
                    "thread_id": thread_id,
                },
            )
            state.extras.update({"task_id": task_id, "persist": True})
            clarification = append_footer(
                "Thanks for your message. A member of our team will review it shortly "
                "to make sure it reaches the right place.",
                step=1,
                next_step="Team review (HIL)",
                thread_state="Waiting on HIL",
            )
            state.add_draft_message({"body": clarification, "step": 1, "topic": "manual_review"})
            state.set_thread_state("Waiting on HIL")
            return GroupResult(
                action="manual_review_enqueued",
                payload={
                    "client_id": state.client_id,
                    "event_id": linked_event_id,
                    "intent": gate_result.intent.value,
                    "confidence": round(gate_result.confidence, 3),
                    "persisted": True,
                    "task_id": task_id,
                    "user_info": user_info,
                    "context": context,
                    "draft_messages": state.draft_messages,
                    "thread_state": state.thread_state,
                },
                halt=True,
            )

    # Apply updates from gate (for CONTINUE decisions with modifications)
    intent = gate_result.intent
    confidence = gate_result.confidence
    state.intent = intent
    state.confidence = confidence
    if gate_result.intent_detail:
        state.intent_detail = gate_result.intent_detail
    if gate_result.user_info_updates:
        user_info.update(gate_result.user_info_updates)
    if gate_result.room_choice:
        state.extras["room_choice_selected"] = gate_result.room_choice
        if gate_result.should_lock_room and linked_event:
            req_hash = linked_event.get("requirements_hash")
            update_event_metadata(
                linked_event,
                locked_room_id=gate_result.room_choice,
                room_eval_hash=req_hash,
                room_status="Available",
                caller_step=None,
            )

    event_entry = _ensure_event_record(state, message_payload, user_info)
    if event_entry.get("pending_hil_requests"):
        event_entry["pending_hil_requests"] = []
        state.extras["persist"] = True

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True

    # Extract billing from message body if not already captured
    # This allows billing to be captured even from event requests that include billing info
    if not user_info.get("billing_address"):
        body_text = message_payload.get("body") or ""
        extracted_billing = _extract_billing_from_body(body_text)
        if extracted_billing:
            user_info["billing_address"] = extracted_billing
            trace_entity(thread_id, owner_step, "billing_address", extracted_billing[:100], True)

    handle_billing_capture(state, event_entry)
    menu_choice_name = user_info.get("menu_choice")
    if menu_choice_name:
        catering_list = event_entry.setdefault("selected_catering", [])
        if menu_choice_name not in catering_list:
            catering_list.append(menu_choice_name)
            event_entry.setdefault("event_data", {})["Catering Preference"] = menu_choice_name
            state.extras["persist"] = True
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    # Process requirements with fallback and products-only detection
    req_result = _process_requirements(user_info, event_entry)
    requirements = req_result.requirements
    new_req_hash = req_result.requirements_hash

    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    # [SMART SHORTCUT] Use extracted modules for past date check and shortcut eligibility
    event_date_from_msg = user_info.get("event_date") or user_info.get("date")
    past_date_result = _check_past_date(event_date_from_msg, event_entry.get("date_confirmed", False))
    past_date_detected = past_date_result.is_past
    if past_date_detected:
        state.extras["past_date_rejected"] = past_date_result.original_date
        event_date_from_msg = None  # Don't use for shortcut

    # Check shortcut eligibility
    eligibility = _check_shortcut_eligibility(
        event_entry, requirements, user_info, past_date_detected, needs_vague_date_confirmation
    )

    # Route to Step 2 if past date was detected
    if past_date_detected:
        logger.info("[Step1][PAST_DATE] Routing to Step 2 for date alternatives")
        update_event_metadata(event_entry, chosen_date=None, date_confirmed=False, current_step=2)
        state.current_step = 2
        state.extras["persist"] = True

    # Evaluate smart shortcut if eligible
    if eligibility.is_eligible:
        shortcut_result = _evaluate_smart_shortcut(event_entry, state.db, eligibility, user_info)
        if shortcut_result.success:
            # Apply the shortcut
            _apply_smart_shortcut(
                event_entry, shortcut_result, eligibility.event_date,
                new_req_hash, eligibility.participants
            )
            state.current_step = 4
            state.set_thread_state("Awaiting Client")
            state.extras["persist"] = True

            # Generate Q&A response if detected
            if state.extras.get("general_qna_detected"):
                unified_det = state.extras.get("unified_detection") or {}
                qna_types = unified_det.get("qna_types") or _detect_qna_types((state.message.body or "").lower())
                if qna_types:
                    hybrid_qna_response = generate_hybrid_qna_response(
                        qna_types=qna_types, message_text=state.message.body or "",
                        event_entry=event_entry, db=state.db,
                    )
                    if hybrid_qna_response:
                        state.extras["hybrid_qna_response"] = hybrid_qna_response

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": intent.value,
                "confidence": round(confidence, 3),
                "locked_room_id": shortcut_result.room_name,
                "thread_state": state.thread_state,
                "persisted": True,
                "smart_shortcut": True,
            }
            return GroupResult(action="smart_shortcut_to_offer", payload=payload, halt=False)

    # Apply metadata updates from preferences and vague date hints
    metadata_updates = _build_metadata_updates(user_info)
    if metadata_updates:
        update_event_metadata(event_entry, **metadata_updates)

    # [ROOM CONFIRMATION] Use extracted module for room choice handling
    room_choice_selected = state.extras.pop("room_choice_selected", None)
    if room_choice_selected:
        confirm_result = _check_room_confirmation(
            room_choice_selected, event_entry, user_info,
            state.extras, state.message.body or "", state.db
        )

        if confirm_result.decision == _RoomConfirmDecision.DEFER_ARRANGEMENT:
            # Missing products - defer to Step 3
            user_info["room"] = room_choice_selected
            user_info["_room_choice_detected"] = True
        elif confirm_result.decision == _RoomConfirmDecision.CONFIRM_AND_ADVANCE:
            # Apply room confirmation
            _apply_room_confirmation(event_entry, confirm_result, state.current_step or 1)
            state.current_step = 4
            state.caller_step = None
            state.set_thread_state("Awaiting Client")
            state.extras["persist"] = True

            # Store hybrid Q&A response if generated
            if confirm_result.hybrid_qna_response:
                state.extras["hybrid_qna_response"] = confirm_result.hybrid_qna_response

            # Add draft message
            if confirm_result.draft_message:
                state.add_draft_message(confirm_result.draft_message)

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": intent.value,
                "confidence": round(confidence, 3),
                "locked_room_id": room_choice_selected,
                "thread_state": state.thread_state,
                "persisted": True,
            }
            return GroupResult(action="room_choice_captured", payload=payload, halt=False)
        # SKIP decision falls through to normal flow

    new_preferred_room = requirements.get("preferred_room")

    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1
    detoured_to_step2 = False

    # Use centralized change detection with Step1-specific guards
    message_text = state.message.body or ""

    # Build context for change detection (billing flow, deposit date, site visit guards)
    change_context = _build_change_context(
        event_entry=event_entry,
        message_text=message_text,
        unified_detection=unified_detection,
        state_extras=state.extras,
    )

    # Detect changes with guards applied
    change_result = _detect_change_with_guards(
        event_entry=event_entry,
        user_info=user_info,
        message_text=message_text,
        unified_detection=unified_detection,
        context=change_context,
    )
    change_type = change_result.change_type
    is_qna_no_change = change_result.is_qna_no_change

    # Q&A guard for vague date reset
    skip_vague_date_reset = _should_skip_vague_date_reset(
        has_qna_question=change_context.has_qna_question,
        date_already_confirmed=change_context.date_already_confirmed,
    )

    # Extract guards from context for fallback routing
    in_billing_flow = change_context.in_billing_flow
    skip_guards = {
        "in_billing_flow": change_context.in_billing_flow,
        "is_deposit_date_context": change_context.is_deposit_date_context,
        "site_visit_active": change_context.site_visit_active,
        "site_visit_change": change_context.site_visit_scheduled and change_context.is_sv_change_request,
        "is_qna_no_change": is_qna_no_change,
    }

    if needs_vague_date_confirmation and not in_billing_flow and not skip_vague_date_reset:
        event_entry["range_query_detected"] = True
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
            thread_state="Awaiting Client Response",
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_pending_vague_request")
        detoured_to_step2 = True
        state.set_thread_state("Awaiting Client Response")
    elif needs_vague_date_confirmation and skip_vague_date_reset:
        logger.debug("[Step1] Skipping vague date reset - Q&A detected and date already confirmed")

    # Handle change routing using DAG-based change propagation
    logger.info("[Step1][CHANGE_ROUTING] change_type=%s, previous_step=%s", change_type, previous_step)
    if change_type is not None and previous_step > 1:
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)
        logger.info("[Step1][CHANGE_ROUTING] decision: next_step=%s, caller_step=%s",
                   decision.next_step, decision.updated_caller_step)

        # Apply routing decision using extracted module
        routing_result = _apply_dag_routing(
            event_entry=event_entry,
            decision=decision,
            change_type=change_type,
            previous_step=previous_step,
            in_billing_flow=in_billing_flow,
            thread_id=_thread_id(state),
            trace_marker_fn=trace_marker,
        )
        if routing_result.detoured_to_step2:
            detoured_to_step2 = True
        if routing_result.change_detour:
            state.extras["change_detour"] = True

    # Fallback: date routing for cases not handled by DAG change propagation
    elif change_type is None:
        date_fb = _check_date_fallback(
            new_date=new_date,
            event_entry=event_entry,
            previous_step=previous_step,
            skip_guards=skip_guards,
        )
        if date_fb.action != _FallbackAction.NONE:
            if date_fb.set_caller_step is not None:
                update_event_metadata(event_entry, caller_step=date_fb.set_caller_step)
            if date_fb.next_step is not None:
                update_event_metadata(
                    event_entry,
                    chosen_date=date_fb.new_date if date_fb.action != _FallbackAction.PAST_DATE_TO_STEP2 else None,
                    date_confirmed=date_fb.date_confirmed,
                    current_step=date_fb.next_step,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                if date_fb.new_date:
                    event_entry.setdefault("event_data", {})["Event Date"] = date_fb.new_date
                if date_fb.action == _FallbackAction.PAST_DATE_TO_STEP2:
                    state.extras["past_date_rejected"] = new_date
                append_audit_entry(event_entry, previous_step, date_fb.next_step, date_fb.audit_reason or "date_fallback")
                if date_fb.next_step == 2:
                    detoured_to_step2 = True

    # Fallback: missing date routing
    missing_date_fb = _check_missing_date_fallback(
        new_date=new_date,
        event_entry=event_entry,
        change_type=change_type,
        needs_vague_date_confirmation=needs_vague_date_confirmation,
        previous_step=previous_step,
    )
    if missing_date_fb.action != _FallbackAction.NONE:
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, missing_date_fb.audit_reason or "date_missing")
        detoured_to_step2 = True

    # Fallback: requirements hash mismatch routing
    req_fb = _check_requirements_hash_fallback(
        prev_req_hash=prev_req_hash,
        new_req_hash=new_req_hash,
        event_entry=event_entry,
        previous_step=previous_step,
        change_type=change_type,
        detoured_to_step2=detoured_to_step2,
        is_qna_no_change=is_qna_no_change,
    )
    if req_fb.action != _FallbackAction.NONE:
        if req_fb.set_caller_step is not None:
            update_event_metadata(event_entry, caller_step=req_fb.set_caller_step)
        if req_fb.next_step is not None:
            update_event_metadata(event_entry, current_step=req_fb.next_step)
            append_audit_entry(event_entry, previous_step, req_fb.next_step, req_fb.audit_reason or "requirements_updated")
            event_entry.pop("negotiation_pending_decision", None)

    # Fallback: room preference change routing
    room_fb = _check_room_preference_fallback(
        new_preferred_room=new_preferred_room,
        event_entry=event_entry,
        previous_step=previous_step,
        change_type=change_type,
        detoured_to_step2=detoured_to_step2,
        is_qna_no_change=is_qna_no_change,
        in_billing_flow=in_billing_flow,
    )
    if room_fb.action != _FallbackAction.NONE:
        if room_fb.set_caller_step is not None:
            update_event_metadata(event_entry, caller_step=room_fb.set_caller_step)
        if room_fb.next_step is not None:
            update_event_metadata(event_entry, current_step=room_fb.next_step)
            append_audit_entry(event_entry, room_fb.set_caller_step or previous_step, room_fb.next_step, room_fb.audit_reason or "room_preference_updated")

    tag_message(event_entry, message_payload.get("msg_id"))

    if not event_entry.get("thread_state"):
        update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    state.extras["persist"] = True

    # Handle hybrid messages: booking intent + Q&A questions in same message
    _generate_hybrid_qna_if_needed(state, event_entry)

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": intent.value,
        "confidence": round(confidence, 3),
        "user_info": user_info,
        "context": context,
        "persisted": True,
        "current_step": event_entry.get("current_step"),
        "caller_step": event_entry.get("caller_step"),
        "thread_state": event_entry.get("thread_state"),
        "draft_messages": state.draft_messages,
    }
    trace_state(
        _thread_id(state),
        "Step1_Intake",
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "current_step": event_entry.get("current_step"),
            "caller_step": event_entry.get("caller_step"),
            "thread_state": event_entry.get("thread_state"),
        },
    )
    return GroupResult(action="intake_complete", payload=payload)


def _build_metadata_updates(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """Build metadata updates dict from user_info preferences and vague date hints."""
    preferences = user_info.get("preferences") or {}
    wish_products = list((preferences.get("wish_products") or []))
    vague_month = user_info.get("vague_month")
    vague_weekday = user_info.get("vague_weekday")
    vague_time = user_info.get("vague_time_of_day")
    week_index = user_info.get("week_index")
    weekdays_hint = user_info.get("weekdays_hint")
    window_scope = user_info.get("window") if isinstance(user_info.get("window"), dict) else None

    metadata_updates: Dict[str, Any] = {}
    if wish_products:
        metadata_updates["wish_products"] = wish_products
    if preferences:
        metadata_updates["preferences"] = preferences
    if vague_month:
        metadata_updates["vague_month"] = vague_month
    if vague_weekday:
        metadata_updates["vague_weekday"] = vague_weekday
    if vague_time:
        metadata_updates["vague_time_of_day"] = vague_time
    if week_index:
        metadata_updates["week_index"] = week_index
    if weekdays_hint:
        metadata_updates["weekdays_hint"] = list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else weekdays_hint
    if window_scope:
        metadata_updates["window_scope"] = {
            key: value
            for key, value in window_scope.items()
            if key in {"month", "week_index", "weekdays_hint"}
        }
    return metadata_updates


def _generate_hybrid_qna_if_needed(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    """Generate hybrid Q&A response if detected and not already generated."""
    if not state.extras.get("general_qna_detected"):
        return
    if state.extras.get("hybrid_qna_response"):
        return

    # Try unified_detection first, fall back to keyword detection
    unified_detection = state.extras.get("unified_detection") or {}
    qna_types = unified_detection.get("qna_types") or []
    if not qna_types:
        message_text = state.message.body or ""
        qna_types = _detect_qna_types(message_text.lower())
        if not qna_types:
            qna_types = ["general"]

    if qna_types:
        message_text = state.message.body or ""
        hybrid_qna_response = generate_hybrid_qna_response(
            qna_types=qna_types,
            message_text=message_text,
            event_entry=event_entry,
            db=state.db,
        )
        if hybrid_qna_response:
            state.extras["hybrid_qna_response"] = hybrid_qna_response


def _trace_user_entities(state: WorkflowState, message_payload: Dict[str, Any], user_info: Dict[str, Any], owner_step: str) -> None:
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
    if email:
        trace_entity(thread_id, owner_step, "email", "message_header", True, {"value": email})

    event_date = user_info.get("event_date") or user_info.get("date")
    if event_date:
        trace_entity(thread_id, owner_step, "event_date", "llm", True, {"value": event_date})

    participants = user_info.get("participants") or user_info.get("number_of_participants")
    if participants:
        trace_entity(thread_id, owner_step, "participants", "llm", True, {"value": participants})


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
