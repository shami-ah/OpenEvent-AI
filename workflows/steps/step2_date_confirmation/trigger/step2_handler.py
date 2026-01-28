from __future__ import annotations
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Sequence
import logging

from debug.hooks import trace_marker, trace_step
from workflows.common.datetime_parse import build_window_iso, parse_first_date
from workflows.common.prompts import append_footer
from workflows.common.capture import capture_user_fields, capture_workflow_requirements
from workflows.common.gatekeeper import refresh_gatekeeper
from utils.pseudolinks import generate_qna_link
from utils.page_snapshots import create_snapshot
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    enrich_general_qna_step2,
)
from workflows.change_propagation import (
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.detour_acknowledgment import (
    generate_detour_acknowledgment,
    add_detour_acknowledgment_draft,
)
from workflows.qna.router import route_general_qna, generate_hybrid_qna_response
from workflows.common.types import GroupResult, WorkflowState
from detection.intent.confidence import check_nonsense_gate
from workflows.common.detection_utils import get_unified_detection
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from utils.profiler import profile_step
from services.availability import next_five_venue_dates, validate_window
from workflow.state import WorkflowStep, write_stage

# Re-exports for backwards compatibility (used by tests for monkeypatching)
from workflows.steps.step1_intake.condition.checks import suggest_dates  # noqa: F401

# D1 refactoring: Types and constants extracted to dedicated modules
from .types import ConfirmationWindow
# D12: Constants moved to step2_utils.py and confirmation.py - no longer needed here

# D2 refactoring: Date parsing utilities extracted to dedicated module
from .date_parsing import (
    safe_parse_iso_date as _safe_parse_iso_date,
    iso_date_is_past as _iso_date_is_past,
    next_matching_date as _next_matching_date,
    format_display_dates as _format_display_dates,
    human_join as _human_join,
    parse_weekday_mentions as _parse_weekday_mentions,
    weekday_indices_from_hint as _weekday_indices_from_hint,
    normalize_month_token as _normalize_month_token,
    normalize_weekday_tokens as _normalize_weekday_tokens,
)

# D3 refactoring: Proposal tracking utilities extracted to dedicated module
from .proposal_tracking import (
    increment_date_attempt as _increment_date_attempt,
    reset_date_attempts as _reset_date_attempts,
    proposal_skip_dates as _proposal_skip_dates,
    update_proposal_history as _update_proposal_history,
)

# D4 refactoring: Calendar check utilities extracted to dedicated module
# D13b: preferred_room added, D14a: calendar_conflict_reason added
from .calendar_checks import (
    candidate_is_calendar_free as _candidate_is_calendar_free,
    maybe_fuzzy_friday_candidates as _maybe_fuzzy_friday_candidates,
    preferred_room as _preferred_room,
    calendar_conflict_reason as _calendar_conflict_reason,
)

# D5 refactoring: General Q&A bridge extracted to dedicated module
# Window helpers provide shared functions used by both step2_handler and general_qna
from .window_helpers import (
    _reference_date_from_state,
    _resolve_window_hints,
    _has_window_constraints,
    _window_filters,
    _extract_participants_from_state,
    _candidate_dates_for_constraints,
)
from .general_qna import (
    _present_general_room_qna,
    _search_range_availability,
)

# D6 refactoring: Pure utilities extracted to step2_utils.py
# D13: compose_greeting, with_greeting added
from .step2_utils import (
    _extract_first_name,
    _extract_signature_name,
    compose_greeting,
    with_greeting,
    _extract_candidate_tokens,
    _strip_system_subject,
    _preface_with_apology,
    _format_label_text,
    _date_header_label,
    _format_time_label,
    _format_day_list,
    _weekday_label_from_dates,
    _month_label_from_dates,
    _pluralize_weekday_hint,
    _describe_constraints,
    _format_window,
    _normalize_time_value,
    _to_time,
    _window_hash,
    _is_affirmative_reply,
    _message_signals_confirmation,
    _message_mentions_new_date,
    # D10: _is_weekend_token now used in candidate_dates.py
    _window_payload,
    _window_from_payload,
    # D9: Additional utilities
    has_range_tokens,
    range_query_pending,
    get_message_text,
    build_select_date_action,
    format_room_availability,
    compact_products_summary,
    user_requested_products,
    # D13d: Tracing
    trace_candidate_gate as _trace_candidate_gate,
)

# D7 refactoring: Candidate date generation extracted to candidate_dates.py
from .candidate_dates import (
    _collect_preferred_weekday_alternatives,
    collect_candidates_from_week_scope,
    collect_candidates_from_fuzzy,
    collect_candidates_from_constraints,
    collect_candidates_from_suggestions,
    collect_supplemental_candidates,
    prioritize_by_weekday,
    prioritize_by_day_hints,
    resolve_week_scope,
    preferred_weekday_label,
)

# D8 refactoring: Pure confirmation helpers extracted to confirmation.py
# D13c: should_auto_accept_first_date added
from .confirmation import (
    determine_date,
    find_existing_time_window,
    collect_candidate_iso_list,
    record_confirmation_log,
    set_pending_time_state,
    complete_from_time_hint,
    should_auto_accept_first_date as _should_auto_accept_first_date,
)

# D15 refactoring: State-dependent helpers extracted to step2_state.py
from .step2_state import (
    thread_id as _thread_id_impl,
    emit_step2_snapshot as _emit_step2_snapshot_impl,
    client_requested_dates as _client_requested_dates_impl,
    maybe_general_qa_payload as _maybe_general_qa_payload_impl,
)

# D16b refactoring: Menu handling extracted to step2_menu.py
from .step2_menu import append_menu_options_if_requested as _append_menu_impl

# D-PRES refactoring: Candidate presentation extracted to candidate_presentation.py
from .candidate_presentation import (
    build_past_date_message,
    build_reason_message,
    build_attempt_message,
    build_unavailable_message,
    build_date_list_lines,
    build_closing_prompt,
    build_date_table_rows,
    build_date_actions,
    build_table_label,
    assemble_candidate_draft,
    verbalize_candidate_message,
)

# D-CTX refactoring: Date context resolution extracted to date_context.py
from .date_context import (
    parse_requested_dates,
    resolve_weekday_preferences,
    resolve_time_hints,
    resolve_anchor_date,
    calculate_collection_limits,
    get_preferred_room,
)

# D-FLOW refactoring: Confirmation flow functions extracted to confirmation_flow.py
from .confirmation_flow import (
    resolve_confirmation_window as _resolve_confirmation_window,
    handle_partial_confirmation as _handle_partial_confirmation_impl,
    prompt_confirmation as _prompt_confirmation_impl,
    finalize_confirmation as _finalize_confirmation,
    clear_step2_hil_tasks as _clear_step2_hil_tasks,
    apply_step2_hil_decision as _apply_step2_hil_decision_impl,
)

__workflow_role__ = "trigger"

logger = logging.getLogger(__name__)


# D15a: Thin wrapper delegating to step2_state.thread_id
def _thread_id(state: WorkflowState) -> str:
    return _thread_id_impl(state)


# D15b: Thin wrapper delegating to step2_state.emit_step2_snapshot
def _emit_step2_snapshot(
    state: WorkflowState,
    event_entry: dict,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    _emit_step2_snapshot_impl(state, event_entry, extra=extra)


# D15c: Thin wrapper delegating to step2_state.client_requested_dates
def _client_requested_dates(state: WorkflowState) -> List[str]:
    return _client_requested_dates_impl(state)


# D16b: Thin wrapper delegating to step2_menu.append_menu_options_if_requested
def _append_menu_options_if_requested(state: WorkflowState, message_lines: List[str], month_hint: Optional[str]) -> None:
    _append_menu_impl(state, message_lines, month_hint)


def _maybe_append_general_qna(
    result: GroupResult,
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: str,
    qa_payload: Optional[Dict[str, Any]],
    requested_client_dates: Sequence[str],
    deferred_general_qna: bool,
) -> GroupResult:
    # HYBRID FIX: Also allow Q&A appending when qna_types exist (workflow + Q&A in same message)
    has_qna_types = state.extras.get("_has_qna_types", False)
    has_qna_signal = classification.get("is_general") or has_qna_types
    if not deferred_general_qna or not requested_client_dates or not has_qna_signal:
        return result

    pre_count = len(state.draft_messages)
    original_candidate_dates = list(event_entry.get("candidate_dates") or [])
    original_thread_state = event_entry.get("thread_state")
    original_current_step = event_entry.get("current_step")
    original_state_thread = state.thread_state

    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    structured_ok = bool(qa_result.payload.get("structured_qna"))
    if not structured_ok:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    attached = append_general_qna_to_primary(state)
    if not attached:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    event_entry["candidate_dates"] = list(original_candidate_dates)
    update_event_metadata(
        event_entry,
        candidate_dates=event_entry.get("candidate_dates"),
        current_step=original_current_step,
        thread_state=original_thread_state,
    )
    state.thread_state = original_state_thread

    return result


# D14a: _calendar_conflict_reason moved to calendar_checks.py


# D13: Thin wrapper delegating to pure compose_greeting
def _compose_greeting(state: WorkflowState) -> str:
    profile = (state.client or {}).get("profile", {}) if state.client else {}
    user_info_name = None
    if state.user_info:
        user_info_name = state.user_info.get("name") or state.user_info.get("company_contact")
    raw_name = user_info_name or profile.get("name")
    msg = state.message
    return compose_greeting(raw_name, msg.body if msg else None, msg.from_name if msg else None)


# D13: Thin wrapper delegating to pure with_greeting
def _with_greeting(state: WorkflowState, body: str) -> str:
    return with_greeting(_compose_greeting(state), body)


@trace_step("Step2_Date")
@profile_step("workflow.step2.date_confirmation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Group B — date negotiation and confirmation."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_invalid", payload=payload, halt=True)

    state.current_step = 2
    state.subflow_group = "date_confirmation"
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    capture_user_fields(state, current_step=2, source=state.message.msg_id if state.message else None)

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 2:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_step2_hil_decision(state, event_entry, decision)

    # D9: Use extracted function
    msg = state.message
    message_text = get_message_text(msg.subject if msg else None, msg.body if msg else None)

    # Capture requirements from workflow context (statements only, not questions)
    if message_text and state.user_info:
        capture_workflow_requirements(state, message_text, state.user_info)

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        # Provide guidance instead of silent ignore (F-04 fix)
        guidance_message = (
            "Thanks for your message! We're waiting for you to confirm your preferred event date. "
            "Please let us know which date works best for you."
        )
        state.add_draft_message({
            "body_markdown": guidance_message,
            "topic": "nonsense_guidance",
        })
        return GroupResult(
            action="nonsense_guided",  # Changed from _ignored to _guided
            payload={"reason": "low_confidence_no_workflow_signal", "step": 2},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=2,
                next_step=2,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=2, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 2},
            halt=True,
        )
    # -------------------------------------------------------------------------

    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    # HYBRID FIX: Also check qna_types from unified detection for hybrid messages
    # (workflow action + Q&A in same message, e.g., "Book May 15 for 30. Parking available?")
    # IMPORTANT: Only use qna_types if LLM detected is_question=True
    unified_detection = get_unified_detection(state)
    has_qna_types = bool(getattr(unified_detection, "qna_types", None) if unified_detection else False)
    is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    has_valid_qna = has_qna_types and is_question  # Only valid if LLM says it's a question
    state.extras["general_qna_detected"] = bool(classification.get("is_general")) or has_valid_qna
    state.extras["_has_qna_types"] = has_valid_qna  # Track for deferred Q&A logic

    # HYBRID FIX: Pre-generate hybrid Q&A response for hybrid messages
    # This will be appended to the workflow response by api/routes/messages.py
    # BUT: Filter out room-related Q&A types when both date AND time are provided
    # (because we'll proceed to Step 3 room availability, which answers the room question)
    if has_valid_qna and not classification.get("is_general"):
        qna_types = getattr(unified_detection, "qna_types", []) or []
        # Room-related types that Step 3's room availability response already covers
        room_qna_types_to_filter = {
            "rooms_by_feature", "room_features", "check_availability", "free_dates", "check_capacity"
        }
        # Check if time slot is provided in this message (means we'll go to room availability)
        has_time_in_message = bool(
            getattr(unified_detection, "start_time", None) or
            getattr(unified_detection, "end_time", None)
        )
        if has_time_in_message:
            # Will proceed to room availability - filter out redundant room Q&A
            filtered_qna_types = [t for t in qna_types if t not in room_qna_types_to_filter]
            logger.debug("[STEP2][HYBRID_QNA] Filtered room Q&A (time provided): %s -> %s", qna_types, filtered_qna_types)
            qna_types = filtered_qna_types
        if qna_types:
            hybrid_qna_response = generate_hybrid_qna_response(
                qna_types=qna_types,
                message_text=state.message.body or "",
                event_entry=event_entry,
                db=state.db,
            )
            if hybrid_qna_response:
                state.extras["hybrid_qna_response"] = hybrid_qna_response
                logger.debug("[STEP2][HYBRID_QNA] Generated hybrid Q&A response for types: %s", qna_types)

    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    thread_id = _thread_id(state)
    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step2_Date",
        )
    qa_payload = _maybe_general_qa_payload(state)

    # [CHANGE DETECTION] Tap incoming stream BEFORE Q&A dispatch to detect client revisions
    # ("actually we're 50 now") and route them back to dependent nodes while hashes stay valid.
    # Use enhanced detection with dual-condition logic (revision signal + bound target)
    #
    # GUARD: Skip date change detection when site visit flow is active
    # When client selects a date for site visit, it should NOT update the event date
    from workflows.common.site_visit_state import is_site_visit_active
    site_visit_active = is_site_visit_active(event_entry)

    user_info = state.user_info or {}
    # Pass unified_detection so Q&A messages don't trigger false change detours
    unified_detection = get_unified_detection(state)
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

    # If site visit is active, suppress date change detection
    # Date in message is for site visit selection, not event date change
    if site_visit_active and change_type and change_type.value == "date":
        logger.info("[STEP2][SV_GUARD] Site visit active - suppressing date change detection")
        change_type = None

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=2)

        # Trace logging for parity with Step 1
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 2,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step2_Date",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        if decision.next_step != 2:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # For date changes: Update the date, keep room lock, invalidate room_eval_hash
            # Step 3 will check if the locked room is still available on the new date
            if change_type.value == "date":
                # Get the new date from user_info
                new_date = user_info.get("date") or user_info.get("event_date")
                if new_date:
                    # Normalize to DD.MM.YYYY format
                    from workflows.common.datetime_parse import parse_all_dates
                    from datetime import date as dt_date
                    parsed = list(parse_all_dates(str(new_date), fallback_year=dt_date.today().year, limit=1))
                    if parsed:
                        new_date_str = parsed[0].strftime("%d.%m.%Y")
                        update_event_metadata(
                            event_entry,
                            chosen_date=new_date_str,
                            date_confirmed=True,  # Date is now confirmed
                            room_eval_hash=None,  # Invalidate to trigger re-verification in Step 3
                            # NOTE: Keep locked_room_id to allow fast-skip if room still available
                        )
                        logger.info("[STEP2][DATE_CHANGE] Updated date from %s to %s",
                                    event_entry.get("chosen_date"), new_date_str)
                elif decision.next_step == 2:
                    # No new date found, just invalidate for re-confirmation
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                    )
            # For requirements changes, clear the lock since room may no longer fit
            elif change_type.value == "requirements" and decision.next_step in (2, 3):
                # BUG FIX: Only set date_confirmed=False when going to Step 2
                # Passing None would overwrite existing True value!
                metadata_updates = {
                    "room_eval_hash": None,
                    "locked_room_id": None,
                }
                if decision.next_step == 2:
                    metadata_updates["date_confirmed"] = False
                update_event_metadata(event_entry, **metadata_updates)

            append_audit_entry(event_entry, 2, decision.next_step, f"{change_type.value}_change_detected")

            # BUG-024 FIX: Set flag for date change acknowledgment in step5
            # This flag is persisted to event_entry so it survives across routing loops
            if change_type.value == "date":
                event_entry["_pending_date_change_ack"] = True

            # IMMEDIATE ACKNOWLEDGMENT: Add detour acknowledgment draft
            # This provides immediate feedback to the user about the change
            ack_result = generate_detour_acknowledgment(
                change_type=change_type,
                decision=decision,
                event_entry=event_entry,
                user_info=user_info,
            )
            if ack_result.generated:
                add_detour_acknowledgment_draft(state, ack_result)

            # Skip Q&A: return detour signal
            # CRITICAL: Update event_entry BEFORE state.current_step so routing loop sees the change
            update_event_metadata(event_entry, current_step=decision.next_step)
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True
            # Clear stale hybrid Q&A from previous turns (prevents old Q&A being appended to detour response)
            state.extras.pop("hybrid_qna_response", None)

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "change_type": change_type.value,
                "detour_to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="change_detour", payload=payload, halt=False)

    # No change detected: proceed with Q&A dispatch as normal
    explicit_confirmation = bool(
        user_info.get("date")
        or user_info.get("event_date")
        or _message_signals_confirmation(message_text)
    )

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client confirms the current step AND asks about the next step,
    # that's NOT general Q&A - it's natural workflow continuation.
    # Example: "Please confirm May 8 and show me available rooms"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=2)
    if sequential_check.get("is_sequential"):
        # Client is confirming date AND asking about rooms - this is natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
        if thread_id:
            trace_marker(
                thread_id,
                "SEQUENTIAL_WORKFLOW",
                detail=f"step2_to_step{sequential_check.get('asks_next_step')}",
                data=sequential_check,
            )
    elif classification.get("is_general") and explicit_confirmation:
        classification["is_general"] = False
        state.extras["general_qna_detected"] = False
        state.extras["_general_qna_classification"] = classification

    requested_client_dates = _client_requested_dates(state)
    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general") and not bool(event_entry.get("date_confirmed"))
    # HYBRID FIX: Also defer Q&A when qna_types exist (workflow + Q&A in same message)
    has_qna_types = state.extras.get("_has_qna_types", False)
    if general_qna_applicable and requested_client_dates:
        deferred_general_qna = True
        general_qna_applicable = False
    elif has_qna_types and requested_client_dates and not general_qna_applicable:
        # Hybrid message: workflow action (date) + Q&A question - defer Q&A to append after workflow response
        deferred_general_qna = True
    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
        enrich_general_qna_step2(state, classification)
        return result

    # FIX: Handle Q&A even when date is already confirmed
    # "Does Room A have a projector?" should be answered inline, not trigger Step 3 auto-run
    llm_is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    llm_general_qna = bool(
        getattr(unified_detection, "intent", "") in ("general_qna", "non_event") if unified_detection else False
    )
    is_likely_qna = classification.get("is_general") or llm_is_question or llm_general_qna

    if is_likely_qna and bool(event_entry.get("date_confirmed")):
        # Pure Q&A when date already confirmed - answer inline and halt
        # Don't progress to Step 3 for room selection
        logger.info("[STEP2][QNA_GUARD] Q&A detected with date_confirmed=True - handling inline (is_general=%s, llm_is_question=%s)",
                    classification.get("is_general"), llm_is_question)
        result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
        enrich_general_qna_step2(state, classification)
        return result

    pending_future_payload = event_entry.get("pending_future_confirmation")
    if pending_future_payload:
        body_text = state.message.body or ""
        if _message_mentions_new_date(body_text):
            event_entry.pop("pending_future_confirmation", None)
        elif _message_signals_confirmation(body_text):
            pending_future_window = _window_from_payload(pending_future_payload)
            event_entry.pop("pending_future_confirmation", None)
            if pending_future_window:
                return _finalize_confirmation(state, event_entry, pending_future_window)

    user_info = state.user_info or {}

    # If the current message contains an explicit date (e.g., "change to 2026-02-28"),
    # skip range_pending check and try to confirm that date directly
    message_has_explicit_date = bool(requested_client_dates)
    # D9: Use extracted function
    range_pending = False if message_has_explicit_date else range_query_pending(user_info, event_entry)

    window = None if range_pending else _resolve_confirmation_window(state, event_entry)
    if window is None:
        result = _present_candidate_dates(
            state,
            event_entry,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    if window.partial:
        # D11: Use extracted complete_from_time_hint with explicit time hint
        time_hint = (state.user_info or {}).get("vague_time_of_day") or event_entry.get("vague_time_of_day")
        filled = complete_from_time_hint(window, time_hint)
        if filled:
            window = filled
        else:
            # If room is already locked (detour case), skip time confirmation.
            # Time is handled in Step 3 (room availability), not Step 2.
            locked_room = event_entry.get("locked_room_id")
            if locked_room:
                # Complete the window with default time and proceed
                default_start = time(14, 0)
                default_end = time(22, 0)
                start_iso, end_iso = build_window_iso(window.iso_date, default_start, default_end)
                window = ConfirmationWindow(
                    display_date=window.display_date,
                    iso_date=window.iso_date,
                    start_time="14:00",
                    end_time="22:00",
                    start_iso=start_iso,
                    end_iso=end_iso,
                    inherited_times=True,
                    partial=False,
                    source_message_id=window.source_message_id,
                )
            else:
                return _handle_partial_confirmation(state, event_entry, window)

    pending_window_payload = event_entry.get("pending_date_confirmation")
    if pending_window_payload:
        pending_window = _window_from_payload(pending_window_payload)
        if _is_affirmative_reply(state.message.body or "") and pending_window:
            event_entry.pop("pending_date_confirmation", None)
            return _finalize_confirmation(state, event_entry, pending_window)
        if _message_mentions_new_date(state.message.body or ""):
            event_entry.pop("pending_date_confirmation", None)
        elif pending_window and not window.partial:
            if (
                pending_window.iso_date == window.iso_date
                and pending_window.start_time == window.start_time
                and pending_window.end_time == window.end_time
            ):
                event_entry.pop("pending_date_confirmation", None)
                return _finalize_confirmation(state, event_entry, window)

    reference_day = _reference_date_from_state(state)
    feasible, reason = validate_window(window.iso_date, window.start_time, window.end_time, reference=reference_day)
    if not feasible:
        result = _present_candidate_dates(
            state,
            event_entry,
            reason,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    conflict_reason = _calendar_conflict_reason(event_entry, window)
    if conflict_reason:
        event_entry.pop("pending_date_confirmation", None)
        result = _present_candidate_dates(
            state,
            event_entry,
            conflict_reason,
            skip_dates=[window.iso_date],
            focus_iso=window.iso_date,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    auto_accept = _should_auto_accept_first_date(event_entry) and not range_pending
    if user_info.get("date") or user_info.get("event_date"):
        auto_accept = True
    if _message_signals_confirmation(state.message.body or "") or auto_accept:
        event_entry.pop("pending_date_confirmation", None)
        return _finalize_confirmation(state, event_entry, window)

    event_entry["pending_date_confirmation"] = _window_payload(window)
    return _prompt_confirmation(state, event_entry, window)


def _present_candidate_dates(
    state: WorkflowState,
    event_entry: dict,
    reason: Optional[str] = None,
    *,
    skip_dates: Optional[Sequence[str]] = None,
    focus_iso: Optional[str] = None,
    requested_client_dates: Optional[Sequence[str]] = None,
) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    requested_dates = list(requested_client_dates or _client_requested_dates(state))
    # D-CTX: Use extracted function for parsing requested dates
    requested_date_objs, min_requested_date, preferred_weekdays = parse_requested_dates(requested_dates)
    attempt = _increment_date_attempt(event_entry)
    skip_set = _proposal_skip_dates(event_entry, attempt, skip_dates)
    escalate_to_hil = attempt >= 3
    user_info = state.user_info or {}

    user_text = f"{state.message.subject or ''} {state.message.body or ''}".strip()
    reference_day = _reference_date_from_state(state)

    # D-CTX: Use extracted functions for context resolution
    preferred_weekdays = resolve_weekday_preferences(
        user_text, user_info, event_entry, preferred_weekdays
    )
    fuzzy_candidates = _maybe_fuzzy_friday_candidates(user_text, reference_day)

    preferred_room = get_preferred_room(event_entry)
    start_hint, end_hint, start_time_obj, end_time_obj = resolve_time_hints(user_info)
    start_pref = start_hint or "18:00"
    end_pref = end_hint or "22:00"

    # D-CTX: Use extracted functions for anchor and limits
    anchor, anchor_dt = resolve_anchor_date(user_text, reference_day, requested_dates, focus_iso)
    limit, collection_cap = calculate_collection_limits(reason, attempt, preferred_weekdays)

    formatted_dates: List[str] = []
    seen_iso: set[str] = set()
    busy_skipped: set[str] = set()
    event_entry.pop("pending_future_confirmation", None)

    # D10: Use extracted resolve_week_scope from candidate_dates.py
    week_scope = None if attempt > 1 else resolve_week_scope(user_info, event_entry, reference_day)
    week_label_value: Optional[str] = None
    if not preferred_weekdays and week_scope:
        preferred_weekdays = _weekday_indices_from_hint(week_scope.get("weekdays_hint"))

    if week_scope:
        limit = min(len(week_scope["dates"]), max(limit, 5))

    if week_scope:
        # D7: Use extracted collection function
        formatted_dates, seen_iso, busy_skipped = collect_candidates_from_week_scope(
            week_scope,
            skip_set=skip_set,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
        )
        week_label_value = week_scope["label"]
        event_entry["week_index"] = week_scope["week_index"]
        event_entry["weekdays_hint"] = list(week_scope.get("weekdays_hint") or [])
        event_entry["window_scope"] = {
            "month": week_scope["month_label"],
            "week_index": week_scope["week_index"],
            "weekdays_hint": list(week_scope.get("weekdays_hint") or []),
        }
        update_event_metadata(
            event_entry,
            week_index=week_scope["week_index"],
            weekdays_hint=list(week_scope.get("weekdays_hint") or []),
            window_scope=event_entry["window_scope"],
        )
    elif fuzzy_candidates:
        # D7: Use extracted collection function
        formatted_dates, seen_iso, busy_skipped = collect_candidates_from_fuzzy(
            fuzzy_candidates,
            skip_set=skip_set,
            seen_iso=seen_iso,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
        )
    else:
        # D-COLL: Use extracted collection functions
        days_ahead = min(180, 45 + (attempt - 1) * 30)

        # Collect from window constraints first
        constraint_dates, seen_iso, constraint_busy = collect_candidates_from_constraints(
            state,
            user_info,
            event_entry,
            attempt=attempt,
            limit=limit,
            skip_set=skip_set,
            seen_iso=seen_iso,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
        )
        formatted_dates.extend(constraint_dates)
        busy_skipped.update(constraint_busy)

        # Collect from date suggestions
        suggestion_dates, seen_iso, suggestion_busy = collect_candidates_from_suggestions(
            state,
            _thread_id(state),
            anchor_dt,
            attempt=attempt,
            skip_set=skip_set,
            seen_iso=seen_iso,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
            collection_cap=collection_cap,
        )
        formatted_dates.extend(suggestion_dates)
        busy_skipped.update(suggestion_busy)

        # Collect supplemental if needed
        if len(formatted_dates) < limit:
            supplemental_dates, seen_iso, supplemental_busy = collect_supplemental_candidates(
                _thread_id(state),
                anchor_dt,
                limit=limit,
                attempt=attempt,
                skip_set=skip_set,
                seen_iso=seen_iso,
                busy_skipped=busy_skipped,
                min_requested_date=min_requested_date,
                preferred_room=preferred_room,
                start_time_obj=start_time_obj,
                end_time_obj=end_time_obj,
                collection_cap=collection_cap,
                days_ahead=days_ahead,
            )
            formatted_dates.extend(supplemental_dates)
            busy_skipped.update(supplemental_busy)

    # D-COLL: Use extracted prioritization function
    preferred_weekday_list = sorted(preferred_weekdays)
    formatted_dates, prioritized_dates, weekday_shortfall = prioritize_by_weekday(
        formatted_dates,
        preferred_weekdays,
        preferred_weekday_list=preferred_weekday_list,
        min_requested_date=min_requested_date,
        reference_day=reference_day,
        preferred_room=preferred_room,
        start_time_obj=start_time_obj,
        end_time_obj=end_time_obj,
        skip_set=skip_set,
        busy_skipped=busy_skipped,
        seen_iso=seen_iso,
        collection_cap=collection_cap,
    )

    if fuzzy_candidates:
        formatted_dates = formatted_dates[:4]
    formatted_dates = formatted_dates[:limit]
    unavailable_requested = [iso for iso in requested_dates if iso not in seen_iso]

    if start_pref and end_pref:
        slot_text = f"{start_pref}–{end_pref}"
    elif start_pref:
        slot_text = start_pref
    elif end_pref:
        slot_text = end_pref
    else:
        slot_text = "18:00–22:00"

    # D-COLL: Use extracted day hint prioritization
    formatted_dates = prioritize_by_day_hints(formatted_dates, week_scope)

    greeting = _compose_greeting(state)
    message_lines: List[str] = [greeting, ""]

    original_requested = parse_first_date(
        user_text,
        fallback_year=reference_day.year,
        reference=reference_day,
    )
    future_suggestion = None
    future_display: Optional[str] = None
    if original_requested and original_requested < reference_day:
        future_suggestion = _next_matching_date(original_requested, reference_day)

    if reason and "past" in reason.lower() and future_suggestion and original_requested:
        # D-PRES: Use extracted function for past date message
        past_msg, original_display, future_display = build_past_date_message(
            original_requested, future_suggestion
        )
        message_lines.append(past_msg)

        future_iso = future_suggestion.isoformat()
        start_iso_val = end_iso_val = None
        if start_hint and end_hint:
            try:
                start_iso_val, end_iso_val = build_window_iso(
                    future_iso,
                    _to_time(start_hint),
                    _to_time(end_hint),
                )
            except ValueError:
                start_iso_val = end_iso_val = None
        pending_window = ConfirmationWindow(
            display_date=future_display,
            iso_date=future_iso,
            start_time=start_hint,
            end_time=end_hint,
            start_iso=start_iso_val,
            end_iso=end_iso_val,
            inherited_times=False,
            partial=not (start_hint and end_hint),
            source_message_id=state.message.msg_id,
        )
        event_entry["pending_future_confirmation"] = _window_payload(pending_window)
        # Don't add redundant phrases - the date suggestion above is sufficient
    elif reason:
        # D-PRES: Use extracted function for reason message
        message_lines.extend(build_reason_message(reason))
    else:
        # D-PRES: Use extracted function for attempt message
        message_lines.append(build_attempt_message(attempt))

    if unavailable_requested:
        # D-PRES: Use extracted function for unavailable message
        message_lines.extend(build_unavailable_message(unavailable_requested))
        # Log date denied activity for manager visibility
        from activity.persistence import log_workflow_activity
        for denied_date in unavailable_requested:
            log_workflow_activity(event_entry, "date_denied", date=denied_date)
    if weekday_shortfall and formatted_dates:
        message_lines.append(
            "I couldn't find a free Thursday or Friday in that range. These are the closest available slots right now."
        )

    if future_suggestion:
        target_month = future_suggestion.strftime("%Y-%m")
        filtered_dates = [iso for iso in formatted_dates if iso.startswith(target_month)]
        if filtered_dates:
            formatted_dates = filtered_dates[:4]
            prioritized_dates = []  # Clear - we're using target month dates now
        else:
            # No dates found in the target month - collect dates starting from future_suggestion
            # This happens when past date is requested and initial collection didn't reach target month
            future_anchor = datetime.combine(future_suggestion, time(hour=12))
            skip_parsed = {_safe_parse_iso_date(iso) for iso in seen_iso if iso}
            supplemental_for_month = next_five_venue_dates(
                future_anchor,
                skip_dates={dt for dt in skip_parsed if dt is not None},
                count=5,
            )
            month_dates = []
            for iso_candidate in supplemental_for_month:
                if iso_candidate.startswith(target_month):
                    if not _candidate_is_calendar_free(preferred_room, iso_candidate, start_time_obj, end_time_obj):
                        continue
                    month_dates.append(iso_candidate)
            if month_dates:
                formatted_dates = month_dates[:4]
                prioritized_dates = []  # Clear - we're using target month dates now

    sample_dates = prioritized_dates[:4] if prioritized_dates else formatted_dates[:4]
    if week_scope:
        sample_dates = list(formatted_dates)
    day_line, day_year = _format_day_list(sample_dates)
    month_hint_value = (
        week_scope["month_label"]
        if week_scope
        else user_info.get("vague_month") or event_entry.get("vague_month")
    )
    date_header_label = _date_header_label(month_hint_value, week_label_value)
    weekday_hint_value = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    weekday_label = None
    if not week_scope:
        # D10: Use extracted preferred_weekday_label from candidate_dates.py
        preferred_label = preferred_weekday_label(preferred_weekday_list, sample_dates)
        if preferred_label:
            weekday_label = preferred_label
        elif len(preferred_weekdays) == 1:
            weekday_label = _weekday_label_from_dates(sample_dates, _pluralize_weekday_hint(weekday_hint_value))
    parsed_sample_dates = [_safe_parse_iso_date(iso_value) for iso_value in sample_dates]
    sample_month_pairs = {(value.year, value.month) for value in parsed_sample_dates if value}
    sample_years = {value.year for value in parsed_sample_dates if value}
    multi_month = len(sample_month_pairs) > 1 or len(sample_years) > 1
    month_for_line: Optional[str] = None
    if parsed_sample_dates and multi_month:
        formatted_labels = [
            value.strftime("%d %b %Y") for value in parsed_sample_dates if value
        ]
        if formatted_labels:
            message_lines.append("")
            label_prefix = weekday_label or "Dates"
            message_lines.append(f"{label_prefix} coming up: {', '.join(formatted_labels)}")
            message_lines.append("")
            date_header_label = f"{label_prefix} coming up"
    else:
        month_for_line = week_scope["label"] if week_scope else _month_label_from_dates(
            sample_dates, month_hint_value
        )
        if day_line and month_for_line and day_year:
            message_lines.append("")
            if week_scope:
                message_lines.append(
                    f"Dates available in {_format_label_text(week_scope['label'])} {day_year}: {day_line}"
                )
            else:
                label_prefix = weekday_label or "Dates"
                message_lines.append(
                    f"{label_prefix} available in {_format_label_text(month_for_line)} {day_year}: {day_line}"
                )
            message_lines.append("")

    _append_menu_options_if_requested(state, message_lines, month_hint_value or month_for_line)

    # Show available dates in a friendly format
    if formatted_dates:
        message_lines.append("")
        message_lines.append("Here are some dates that work:")
        for iso_value in formatted_dates[:5]:
            message_lines.append(f"- {iso_value} {slot_text}")
    else:
        message_lines.append("")
        message_lines.append("I couldn't find suitable slots within the next 60 days, but I'm still looking.")

    # D-PRES: Next step guidance via extracted function
    message_lines.append("")
    message_lines.append(build_closing_prompt(future_display))
    prompt = "\n".join(message_lines)

    weekday_hint = weekday_hint_value
    time_hint = user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day")
    time_display = str(time_hint).strip().capitalize() if time_hint else slot_text

    # D-COLL: Use extracted day hint prioritization (before building table/actions)
    formatted_dates = prioritize_by_day_hints(formatted_dates, week_scope)

    # D-PRES: Use extracted functions for table/actions building
    table_rows = build_date_table_rows(formatted_dates, time_display, limit=5)
    actions_payload = build_date_actions(formatted_dates, time_display, limit=5)
    label_base = build_table_label(
        weekday_label, month_for_line, date_header_label, time_hint, time_display
    )

    _trace_candidate_gate(_thread_id(state), formatted_dates[:5])

    # D-PRES: Universal Verbalizer via extracted function
    participants = _extract_participants_from_state(state)
    body_markdown = verbalize_candidate_message(prompt, participants, formatted_dates)

    # D-PRES: Use extracted function for draft assembly
    headers = ["Availability overview"]
    if date_header_label:
        headers.append(date_header_label)
    if escalate_to_hil:
        headers.append("Manual follow-up required")

    draft_message = assemble_candidate_draft(
        body_markdown=body_markdown,
        formatted_dates=formatted_dates,
        table_rows=table_rows,
        actions_payload=actions_payload,
        label_base=label_base,
        headers=headers,
        escalate_to_hil=escalate_to_hil,
    )
    thread_state_label = draft_message["thread_state"]
    if actions_payload:
        event_entry["candidate_dates"] = [action["date"] for action in actions_payload]
    history = _update_proposal_history(event_entry, event_entry.get("candidate_dates") or formatted_dates[:5])
    state.add_draft_message(draft_message)

    # Check for secondary Q&A types (catering_for, products_for, etc.) and append router content
    classification = state.extras.get("_general_qna_classification") or {}
    secondary_types = list(classification.get("secondary") or [])
    router_types = {"catering_for", "products_for", "rooms_by_feature", "room_features", "free_dates", "parking_policy", "site_visit_overview"}
    router_applicable = bool(set(secondary_types) & router_types)

    if router_applicable:
        message = state.message
        msg_payload = {
            "subject": (message.subject if message else "") or "",
            "body": (message.body if message else "") or "",
            "thread_id": state.thread_id,
        }
        router_result = route_general_qna(
            msg_payload,
            event_entry,
            event_entry,
            None,  # db not needed for catering/products router responses
            classification,
        )
        router_blocks = router_result.get("post_step") or router_result.get("pre_step") or []
        if router_blocks:
            router_body = router_blocks[0].get("body", "")
            if router_body:
                # Add info link for catering Q&A
                qna_link_suffix = ""
                if "catering_for" in secondary_types:
                    query_params = {"room": event_entry.get("preferred_room") or "general"}
                    snapshot_data = {"catering_options": router_body, "event_id": event_entry.get("event_id")}
                    snapshot_id = create_snapshot(
                        snapshot_type="catering",
                        data=snapshot_data,
                        event_id=event_entry.get("event_id"),
                        params=query_params,
                    )
                    qna_link = generate_qna_link("Catering", query_params=query_params, snapshot_id=snapshot_id)
                    qna_link_suffix = f"\n\nFull menu details: {qna_link}"
                # Append router Q&A content to the draft message body
                original_body = draft_message.get("body", "")
                draft_message["body"] = f"{original_body}\n\n---\n\n{router_body}{qna_link_suffix}"
                draft_message["body_markdown"] = draft_message["body"]
                draft_message["router_qna_appended"] = True

    update_event_metadata(
        event_entry,
        thread_state=thread_state_label,
        current_step=2,
        candidate_dates=event_entry.get("candidate_dates"),
        date_proposal_attempts=attempt,
        date_proposal_history=history,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state(thread_state_label)
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "candidate_dates": formatted_dates[:5],
            "slot_text": slot_text,
            "attempt": attempt,
            "hil_escalated": escalate_to_hil,
            "calendar_omitted": sorted(busy_skipped),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": formatted_dates[:5],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "date_proposal_attempts": attempt,
        "hil_escalated": escalate_to_hil,
        "calendar_skipped": sorted(busy_skipped),
        "answered_question_first": True,
    }
    payload["actions"] = list(actions_payload) if actions_payload else [{"type": "send_reply"}]
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    message_text = f"{state.message.subject or ''} {state.message.body or ''}"
    lowered_msg = message_text.lower()
    question_triggers = (
        "?" in message_text,
        "please advise" in lowered_msg,
        "could you" in lowered_msg,
        "can you" in lowered_msg,
        "would you" in lowered_msg,
        "let me know" in lowered_msg,
    )
    if any(question_triggers) or state.extras.get("general_qna_detected"):
        state.intent_detail = "event_intake_with_question"
    elif not state.intent_detail:
        state.intent_detail = "event_intake"
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


# D13c: _should_auto_accept_first_date moved to confirmation.py
# D13b: _preferred_room moved to calendar_checks.py
# D-FLOW: _resolve_confirmation_window moved to confirmation_flow.py


# D-FLOW: Thin wrappers delegating to confirmation_flow module
def _handle_partial_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> Optional[GroupResult]:
    """Persist the date and request a time clarification without stalling the flow."""
    return _handle_partial_confirmation_impl(state, event_entry, window, _with_greeting)


def _prompt_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Prompt the user to confirm a proposed date/time window."""
    return _prompt_confirmation_impl(state, event_entry, window, _with_greeting)


# D-FLOW: _finalize_confirmation, _clear_step2_hil_tasks moved to confirmation_flow.py


def _apply_step2_hil_decision(state: WorkflowState, event_entry: dict, decision: str) -> GroupResult:
    """Handle HIL approval or rejection for pending date confirmation."""
    return _apply_step2_hil_decision_impl(state, event_entry, decision, _window_from_payload)


# D15d: Thin wrapper delegating to step2_state.maybe_general_qa_payload
def _maybe_general_qa_payload(state: WorkflowState) -> Optional[Dict[str, Any]]:
    return _maybe_general_qa_payload_impl(state)
