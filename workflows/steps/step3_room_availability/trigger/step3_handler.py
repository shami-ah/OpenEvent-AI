from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from workflows.common.prompts import append_footer
from workflows.common.menu_options import (
    ALLOW_CONTEXTUAL_HINTS,
    build_menu_title,
    extract_menu_request,
    format_menu_line_short,
    MENU_CONTENT_CHAR_THRESHOLD,
    normalize_menu_for_display,
    select_menu_options,
)
from workflows.common.capture import capture_workflow_requirements
from workflows.common.requirements import requirements_hash
from workflows.common.sorting import rank_rooms
from workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from workflows.common.confidence -> backend.detection.intent.confidence
from detection.intent.confidence import check_nonsense_gate
from workflows.common.timeutils import parse_ddmmyyyy
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
)
from workflows.common.detection_utils import get_unified_detection
from workflows.qna.router import generate_hybrid_qna_response
from workflows.change_propagation import (
    ChangeType,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.detour_acknowledgment import (
    generate_detour_acknowledgment,
    add_detour_acknowledgment_draft,
)
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.io.config_store import get_catering_teaser_products, get_currency_code
# MIGRATED: from workflows.common.conflict -> backend.detection.special.room_conflict
from detection.special.room_conflict import (
    detect_conflict_type,
    compose_soft_conflict_warning,
    handle_hard_conflict,
    get_available_rooms_on_date,
)
# Product arrangement detection (missing product sourcing flow)
from detection.special.product_arrangement import (
    detect_product_arrangement_intent,
    detect_continue_without_product,
)
from debug.hooks import trace_db_read, trace_db_write, trace_detour, trace_gate, trace_state, trace_step, set_subloop, trace_marker, trace_general_qa_status
from utils.profiler import profile_step
from utils.pseudolinks import generate_room_details_link, generate_qna_link
from utils.page_snapshots import create_snapshot
from workflow_verbalizer_test_hooks import render_rooms
from workflows.steps.step3_room_availability.db_pers import load_rooms_config
from workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from rooms import rank as rank_rooms_profiles, get_max_capacity, any_room_fits_capacity

from ..condition.decide import room_status_on_date
from ..llm.analysis import summarize_room_statuses
# Room choice detection (reused from Step 1)
from workflows.steps.step1_intake.trigger.room_detection import detect_room_choice as _detect_room_choice
from .constants import (
    ROOM_OUTCOME_UNAVAILABLE,
    ROOM_OUTCOME_AVAILABLE,
    ROOM_OUTCOME_OPTION,
    ROOM_OUTCOME_CAPACITY_EXCEEDED,
    ROOM_SIZE_ORDER,
    ROOM_PROPOSAL_HIL_THRESHOLD,
)

# R3 refactoring: Room selection action extracted to dedicated module
from .selection import (
    handle_select_room_action,
    _thread_id,
    _reset_room_attempts,
    _format_display_date,
)

# R4 refactoring: Evaluation functions extracted to dedicated module
from .evaluation import evaluate_room_statuses, render_rooms_response, _flatten_statuses

# R5 refactoring (Jan 2026): Conflict resolution extracted to dedicated module
from .conflict_resolution import (
    handle_conflict_response as _handle_conflict_response,
    detect_wants_alternative as _detect_wants_alternative,
    detect_wants_to_insist as _detect_wants_to_insist,
    extract_insist_reason as _extract_insist_reason,
    is_generic_question as _is_generic_question,
    collect_alternative_dates as _collect_alternative_dates,
    merge_alternative_dates as _merge_alternative_dates,
    dedupe_dates as _dedupe_dates,
    format_alternative_dates_section as _format_alternative_dates_section,
    _message_text,
    _to_iso,
    _format_short_date,
)

# R6 refactoring (Jan 2026): Detour handling extracted to dedicated module
from .detour_handling import (
    detour_to_date as _detour_to_date,
    detour_for_capacity as _detour_for_capacity,
    detour_for_time_slot as _detour_for_time_slot,
    skip_room_evaluation as _skip_room_evaluation,
    handle_capacity_exceeded as _handle_capacity_exceeded,
)

# R7 refactoring (Jan 2026): Room ranking extracted to dedicated module
from .room_ranking import (
    select_room as _select_room,
    build_ranked_rows as _build_ranked_rows,
    derive_hint as _derive_hint,
    has_explicit_preferences as _has_explicit_preferences,
    room_requirements_payload as _room_requirements_payload,
    needs_better_room_alternatives as _needs_better_room_alternatives,
    available_dates_for_rooms as _available_dates_for_rooms,
    dates_in_month_weekday_wrapper as _dates_in_month_weekday_wrapper,
    closest_alternatives_wrapper as _closest_alternatives_wrapper,
    extract_participants as _extract_participants,
)

# R7 refactoring (Jan 2026): Room presentation extracted to dedicated module
from .room_presentation import (
    compose_preselection_header as _compose_preselection_header,
    verbalizer_rooms_payload as _verbalizer_rooms_payload,
    format_requirements_line as _format_requirements_line,
    format_room_sections as _format_room_sections,
    format_range_descriptor as _format_range_descriptor,
    format_dates_list as _format_dates_list,
)

# R8 refactoring (Jan 2026): Sourcing handler extracted to dedicated module
from .sourcing_handler import (
    handle_product_sourcing_request as _handle_product_sourcing_request,
    advance_to_offer_from_sourcing as _advance_to_offer_from_sourcing,
)

# R8 refactoring (Jan 2026): HIL operations extracted to dedicated module
from .hil_ops import (
    apply_hil_decision as _apply_hil_decision,
    preferred_room as _preferred_room,
    increment_room_attempt as _increment_room_attempt,
)

__workflow_role__ = "trigger"

# Use shared threshold from menu_options; kept as alias for backward compat
QNA_SUMMARY_CHAR_THRESHOLD = MENU_CONTENT_CHAR_THRESHOLD


@trace_step("Step3_Room")
@profile_step("workflow.step3.room_availability")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment with entry guards and caching."""

    # DEBUG: Log entry point
    logger.info("[Step3][ENTRY] called with state.user_info=%s",
                {k: v for k, v in (state.user_info or {}).items() if k in ("room", "_room_choice_detected")})

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": state.event_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_eval_missing_event", payload=payload, halt=True)

    thread_id = _thread_id(state)
    state.current_step = 3

    date_confirmed_ok = bool(event_entry.get("date_confirmed"))
    trace_gate(thread_id, "Step3_Room", "date_confirmed", date_confirmed_ok, {"date_confirmed": date_confirmed_ok})
    if not date_confirmed_ok:
        return _detour_to_date(state, event_entry)

    # Time slot gate - require start_time or end_time before showing room availability
    # Room availability depends on time window (morning vs afternoon bookings differ)
    # EXCEPTION: If this is a Q&A question about rooms, bypass gate and let Q&A handle it
    captured = event_entry.get("captured") or {}
    has_time_slot = bool(captured.get("start_time") or captured.get("end_time"))

    # Check if this is a pure Q&A question about rooms (should bypass time slot gate)
    unified_detection = get_unified_detection(state)
    is_room_qna = False
    if unified_detection and getattr(unified_detection, "is_question", False):
        qna_types = getattr(unified_detection, "qna_types", None) or []
        room_related_types = {"check_availability", "free_dates", "room_features", "check_capacity", "rooms_by_feature"}
        is_room_qna = bool(set(qna_types) & room_related_types)

    trace_gate(thread_id, "Step3_Room", "time_slot", has_time_slot, {"start_time": captured.get("start_time"), "end_time": captured.get("end_time"), "is_room_qna": is_room_qna})
    if not has_time_slot and not is_room_qna:
        return _detour_for_time_slot(state, event_entry)

    requirements = event_entry.get("requirements") or {}
    current_req_hash = event_entry.get("requirements_hash")
    computed_hash = requirements_hash(requirements) if requirements else None
    if computed_hash and computed_hash != current_req_hash:
        update_event_metadata(event_entry, requirements_hash=computed_hash)
        current_req_hash = computed_hash
        state.extras["persist"] = True

    participants = _extract_participants(requirements)

    capacity_shortcut = False
    if state.user_info.get("shortcut_capacity_ok"):
        shortcuts = event_entry.setdefault("shortcuts", {})
        if not shortcuts.get("capacity_ok"):
            shortcuts["capacity_ok"] = True
            state.extras["persist"] = True
        capacity_shortcut = True
    if not capacity_shortcut:
        capacity_shortcut = bool((event_entry.get("shortcuts") or {}).get("capacity_ok"))

    capacity_ok = participants is not None or capacity_shortcut
    if not capacity_ok:
        return _detour_for_capacity(state, event_entry)
    if capacity_shortcut:
        state.extras["subloop"] = "shortcut"
        if thread_id:
            set_subloop(thread_id, "shortcut")

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 3:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_decision(state, event_entry, decision)

    # -------------------------------------------------------------------------
    # SITE VISIT HANDLING: If site_visit_state.status == "proposed", route to Step 7
    # Client's date mentions are for site visits, not event date changes
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

    # Hard guard: Step 3 should never enqueue HIL; clear any stale requests.
    pending = event_entry.get("pending_hil_requests") or []
    filtered = [entry for entry in pending if (entry.get("step") or 0) != 3]
    if len(filtered) != len(pending):
        event_entry["pending_hil_requests"] = filtered
        state.extras["persist"] = True

    # -------------------------------------------------------------------------
    # CONFLICT PENDING DECISION: Handle client response to soft conflict warning
    # When another client has an Option on the same room, we asked this client
    # to either choose alternative or insist with reason.
    # -------------------------------------------------------------------------
    conflict_pending = event_entry.get("conflict_pending_decision")
    if conflict_pending:
        result = _handle_conflict_response(state, event_entry, conflict_pending, thread_id)
        if result:
            return result
        # If no result, client didn't make a clear choice - fall through to normal flow

    # -------------------------------------------------------------------------
    # PRODUCT SOURCING STATE: Handle pending sourcing requests
    # When client asked us to arrange a missing product, we create a HIL task
    # for the manager. While waiting, or after manager response, handle state.
    # -------------------------------------------------------------------------
    sourcing_pending = event_entry.get("sourcing_pending")
    if sourcing_pending:
        # Still waiting for manager to source the product - remind client
        trace_marker(
            thread_id,
            "sourcing_pending_wait",
            detail=f"Waiting for manager to source: {sourcing_pending.get('products')}",
            owner_step="Step3_Room",
        )
        draft = {
            "body": append_footer(
                "I'm still checking with my colleague about arranging the items you requested. "
                "I'll get back to you as soon as I have an update.",
                step=3,
                next_step=3,
                thread_state="Awaiting Manager",
            ),
            "topic": "sourcing_still_pending",
            "requires_approval": False,
        }
        state.add_draft_message(draft)
        return GroupResult(
            action="sourcing_pending_reminder",
            payload={"products": sourcing_pending.get("products"), "step": 3},
            halt=True,
        )

    sourcing_declined = event_entry.get("sourcing_declined")
    if sourcing_declined:
        # Manager couldn't find the product - check if client wants to continue
        message_text = _message_text(state)
        declined_products = sourcing_declined.get("products", [])

        if message_text and detect_continue_without_product(message_text, declined_products):
            # Client wants to continue without the product
            trace_marker(
                thread_id,
                "continue_without_product",
                detail=f"Client continuing without: {declined_products}",
                owner_step="Step3_Room",
            )
            # Clear the sourcing state and advance to Step 4
            del event_entry["sourcing_declined"]
            state.extras["persist"] = True
            # The room was already locked when sourcing was requested
            return _advance_to_offer_from_sourcing(state, event_entry, thread_id)

        # Client hasn't decided yet or said something else - fall through to normal handling

    # -------------------------------------------------------------------------
    # PRODUCT ARRANGEMENT DETECTION (EARLY CHECK)
    # Must run BEFORE change detection, because "arrange the flipchart" might be
    # mistakenly detected as a requirements change. If we have room_pending_decision
    # with missing products and client wants to arrange them, handle it here.
    # -------------------------------------------------------------------------
    message_text = _message_text(state)
    room_pending_early = event_entry.get("room_pending_decision")
    locked_room_early = event_entry.get("locked_room_id")
    missing_products_early = (room_pending_early or {}).get("missing_products", [])

    logger.debug("[Step3] EARLY ARRANGEMENT CHECK: room_pending=%s, missing_products=%s, locked_room=%s",
                 bool(room_pending_early), missing_products_early, locked_room_early)

    if room_pending_early and missing_products_early and message_text and not locked_room_early:
        arrangement_result = detect_product_arrangement_intent(
            message_text,
            missing_products_early,
        )
        if arrangement_result.wants_arrangement:
            trace_marker(
                thread_id,
                "early_arrangement_request_detected",
                detail=f"Client wants to arrange: {arrangement_result.products_to_source}",
                owner_step="Step3_Room",
            )
            return _handle_product_sourcing_request(
                state,
                event_entry,
                room_pending_early,
                arrangement_result,
                thread_id,
            )

    # [CHANGE DETECTION + Q&A] Tap incoming stream BEFORE room evaluation to detect client revisions
    # ("actually we're 50 now") and route them back to dependent nodes while hashes stay valid.
    user_info = state.user_info or {}

    # Capture requirements from workflow context (statements only, not questions)
    if message_text and state.user_info:
        capture_workflow_requirements(state, message_text, state.user_info)

    # -------------------------------------------------------------------------
    # ROOM CONFIRMATION DETECTION (Step 3-specific)
    # Detect when user selects a room (e.g., "Room A sounds good", "I'll take Room B")
    # This sets _room_choice_detected so is_room_confirmation works later.
    # Must run BEFORE change detection to avoid treating confirmation as a change.
    # -------------------------------------------------------------------------
    # DEBUG: Log incoming state for room detection
    logger.info(
        "[Step3][DEBUG] BEFORE room detection: user_info._room_choice_detected=%s, user_info.room=%s, message_text=%s",
        user_info.get("_room_choice_detected"),
        user_info.get("room"),
        (message_text[:100] if message_text else None),
    )
    # Get unified detection for question guard ("Is Room A available?" should not lock)
    unified_detection = get_unified_detection(state)
    if message_text and not user_info.get("_room_choice_detected"):
        detected_room = _detect_room_choice(message_text, event_entry, unified_detection)
        logger.info("[Step3][DEBUG] _detect_room_choice returned: %s", detected_room)
        if detected_room:
            user_info["room"] = detected_room
            user_info["_room_choice_detected"] = True
            state.user_info = user_info  # Ensure state is updated
            if thread_id:
                trace_marker(
                    thread_id,
                    "room_selection_detected",
                    detail=f"User selected room: {detected_room}",
                    owner_step="Step3_Room",
                )
        elif event_entry.get("caller_step") is not None:
            # Detour smart shortcut: allow room confirmation in detour context even if
            # acceptance guard blocked room detection, but only when the room is
            # explicitly mentioned in the message and it's not a pure question.
            lowered_message = message_text.lower()
            candidate_room = None
            extracted_room = user_info.get("room")
            if extracted_room and str(extracted_room).lower() in lowered_message:
                candidate_room = extracted_room
            else:
                locked_room = event_entry.get("locked_room_id")
                if locked_room and str(locked_room).lower() in lowered_message:
                    candidate_room = locked_room
            is_pure_room_question = bool(
                unified_detection
                and getattr(unified_detection, "is_question", False)
                and not getattr(unified_detection, "is_acceptance", False)
            )
            if candidate_room and not is_pure_room_question:
                user_info["room"] = candidate_room
                user_info["_room_choice_detected"] = True
                state.user_info = user_info
                if thread_id:
                    trace_marker(
                        thread_id,
                        "room_selection_detected_detour",
                        detail=f"Detour room confirmed: {candidate_room}",
                        data={"caller_step": event_entry.get("caller_step")},
                        owner_step="Step3_Room",
                    )

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        # Silent ignore - no reply, no further processing
        return GroupResult(
            action="nonsense_ignored",
            payload={"reason": "low_confidence_no_workflow_signal", "step": 3},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=3,
                next_step=3,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=3, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 3},
            halt=True,
        )
    # -------------------------------------------------------------------------

    # Q&A classification - reuse from Step 2 if workflow_lookahead was detected
    # (prevents re-classification of sequential workflow requests as general Q&A)
    cached_classification = state.extras.get("_general_qna_classification")
    if cached_classification and cached_classification.get("workflow_lookahead"):
        classification = cached_classification
    else:
        classification = detect_general_room_query(message_text, state)
        state.extras["_general_qna_classification"] = classification
    # HYBRID FIX: Also check qna_types from unified detection for hybrid messages
    # IMPORTANT: Only use qna_types if LLM detected is_question=True
    unified_detection = get_unified_detection(state)
    has_qna_types = bool(getattr(unified_detection, "qna_types", None) if unified_detection else False)
    is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    has_valid_qna = has_qna_types and is_question  # Only valid if LLM says it's a question
    state.extras["general_qna_detected"] = bool(classification.get("is_general")) or has_valid_qna
    state.extras["_has_qna_types"] = has_valid_qna

    # HYBRID FIX: Pre-generate hybrid Q&A response for hybrid messages
    # This will be appended to the workflow response by api/routes/messages.py
    # BUT: Filter out room-related Q&A types when Step 3 will show room availability itself
    # (prevents redundant "here are our rooms" Q&A when workflow is already showing rooms)
    if has_valid_qna and not classification.get("is_general"):
        qna_types = getattr(unified_detection, "qna_types", []) or []
        # Room-related types that Step 3's room availability response already covers
        room_qna_types_to_filter = {
            "rooms_by_feature", "room_features", "check_availability", "free_dates", "check_capacity"
        }
        # Filter out room Q&A when we're about to show room availability
        # (i.e., when time slot is captured so we won't detour)
        captured = event_entry.get("captured") or {}
        has_time_slot = bool(captured.get("start_time") or captured.get("end_time"))
        if has_time_slot:
            # Step 3 will show room availability - filter out redundant room Q&A
            filtered_qna_types = [t for t in qna_types if t not in room_qna_types_to_filter]
            logger.debug("[STEP3][HYBRID_QNA] Filtered room Q&A (time_slot captured): %s -> %s", qna_types, filtered_qna_types)
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
                logger.debug("[STEP3][HYBRID_QNA] Generated hybrid Q&A response for types: %s", qna_types)

    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]

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
            owner_step="Step3_Room",
        )

    # [CHANGE DETECTION] Run BEFORE Q&A dispatch
    # Use enhanced detection with dual-condition logic (revision signal + bound target)
    # Pass unified_detection so Q&A messages don't trigger false change detours
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

    # [SKIP DUPLICATE DETOUR] If a date change is detected but the date in the message
    # matches the already-confirmed chosen_date, skip the detour. This happens when
    # Step 2's finalize_confirmation internally calls Step 3 on the same message.
    if change_type == ChangeType.DATE and event_entry.get("date_confirmed"):
        from workflows.common.datetime_parse import parse_all_dates
        from datetime import date as dt_date

        chosen_date_raw = event_entry.get("chosen_date")  # e.g., "21.02.2026"
        # Parse chosen_date (DD.MM.YYYY format) to ISO
        chosen_parsed = parse_ddmmyyyy(chosen_date_raw) if chosen_date_raw else None
        chosen_iso = chosen_parsed.isoformat() if chosen_parsed else None
        message_dates = list(parse_all_dates(message_text or "", fallback_year=dt_date.today().year))
        # Check if ANY date in the message matches chosen_date (not just the first one)
        # This handles cases where today's date or other dates are also parsed
        if message_dates and chosen_iso:
            message_isos = [d.isoformat() for d in message_dates]
            if chosen_iso in message_isos:
                # The just-confirmed date is in the message - not a new change request
                change_type = None
                if thread_id:
                    trace_marker(
                        thread_id,
                        "SKIP_DUPLICATE_DATE_DETOUR",
                        detail=f"chosen_date={chosen_iso} found in message_dates={message_isos}",
                        data={"message_dates": message_isos, "chosen_date": chosen_iso},
                        owner_step="Step3_Room",
                    )

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=3)

        # Trace logging for parity with Step 2
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 3,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step3_Room",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        if decision.next_step != 3:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # For date changes: Keep room lock, invalidate room_eval_hash so Step 3 re-verifies
            # Step 3 will check if the locked room is still available on the new date
            if change_type.value == "date" and decision.next_step == 2:
                update_event_metadata(
                    event_entry,
                    date_confirmed=False,
                    room_eval_hash=None,  # Invalidate to trigger re-verification
                    # NOTE: Keep locked_room_id to allow fast-skip if room still available
                )
            # For requirements changes, clear the lock since room may no longer fit
            elif change_type.value == "requirements" and decision.next_step in (2, 3):
                # Only clear date_confirmed when going to Step 2
                # BUG FIX: Passing None would overwrite existing True value!
                metadata_updates = {
                    "room_eval_hash": None,
                    "locked_room_id": None,
                }
                if decision.next_step == 2:
                    metadata_updates["date_confirmed"] = False
                update_event_metadata(event_entry, **metadata_updates)

            append_audit_entry(event_entry, 3, decision.next_step, f"{change_type.value}_change_detected")

            # IMMEDIATE ACKNOWLEDGMENT: Add detour acknowledgment draft
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

        else:
            # -------------------------------------------------------------------------
            # REQUIREMENTS CHANGE STAYING AT STEP 3 (Jan 2026)
            # When requirements change (e.g., guest count 30 -> 60) while already at Step 3,
            # we stay at Step 3 to re-evaluate rooms. We need to:
            # 1. Clear the room lock (room may no longer fit new requirements)
            # 2. Set change_detour flag so Q&A path is bypassed
            # 3. Continue to room evaluation (don't return, let flow continue)
            # -------------------------------------------------------------------------
            if change_type == ChangeType.REQUIREMENTS and decision.needs_reeval:
                update_event_metadata(
                    event_entry,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                state.extras["change_detour"] = True
                if thread_id:
                    trace_marker(
                        thread_id,
                        "REQUIREMENTS_REEVAL_AT_STEP3",
                        detail="Requirements changed, staying at Step 3 to re-evaluate rooms",
                        data={"change_type": change_type.value, "needs_reeval": decision.needs_reeval},
                        owner_step="Step3_Room",
                    )
                # Don't return - continue to room evaluation below

    # No change detected: check if Q&A should be handled
    # NOTE: Room can be detected via _room_choice_detected OR via ChangeType.ROOM detection
    # The change_type variable is set earlier (line ~233) if a room change was detected
    room_change_detected_flag = state.user_info.get("_room_choice_detected") or (change_type == ChangeType.ROOM)
    user_requested_room = state.user_info.get("room") if room_change_detected_flag else None

    # DEBUG: Trace user_info state from Step 1 → Step 3
    logger.info(
        "[Step3][USER_INFO_TRACE] state.user_info=%s, room_change_detected_flag=%s, user_requested_room=%s",
        {k: v for k, v in (state.user_info or {}).items() if k in ("room", "_room_choice_detected")},
        room_change_detected_flag,
        user_requested_room,
    )
    locked_room_id = event_entry.get("locked_room_id")

    # DEBUG: Trace room confirmation logic
    logger.info(
        "[Step3][DEBUG] room_change_detected_flag=%s, _room_choice_detected=%s, change_type=%s, "
        "user_info.room=%s, user_requested_room=%s, locked_room_id=%s",
        room_change_detected_flag,
        state.user_info.get("_room_choice_detected"),
        change_type,
        state.user_info.get("room"),
        user_requested_room,
        locked_room_id,
    )

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client confirms room AND asks about catering/offer, that's NOT
    # general Q&A - it's natural workflow continuation.
    # Example: "Room A looks good, what catering options do you have?"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=3)
    sequential_catering_lookahead = False
    if sequential_check.get("is_sequential"):
        # Client is selecting room AND asking about next step - natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
        # If asking about catering (step 4), we should include catering info in response
        if sequential_check.get("asks_next_step") == 4:
            sequential_catering_lookahead = True
            # Ensure catering_for is in secondary so deferred Q&A generates catering response
            if "secondary" not in classification or not classification["secondary"]:
                classification["secondary"] = ["catering_for"]
            elif "catering_for" not in classification["secondary"]:
                classification["secondary"].append("catering_for")
        if thread_id:
            trace_marker(
                thread_id,
                "SEQUENTIAL_WORKFLOW",
                detail=f"step3_to_step{sequential_check.get('asks_next_step')}",
                data=sequential_check,
            )

    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general") and not bool(locked_room_id)
    if general_qna_applicable and user_requested_room:
        deferred_general_qna = True
        general_qna_applicable = False
    # Also defer Q&A when sequential catering lookahead detected (room selection + catering question)
    elif sequential_catering_lookahead and user_requested_room:
        deferred_general_qna = True

    # -------------------------------------------------------------------------
    # DETOUR RE-ENTRY GUARD (Dec 29, 2025)
    # After a change_detour (e.g., participant change), force normal room availability
    # path instead of Q&A fallback. The change_detour flag is set by the routing loop.
    # -------------------------------------------------------------------------
    caller_step = event_entry.get("caller_step")
    is_detour_reentry = state.extras.get("change_detour", False) or caller_step is not None
    if is_detour_reentry:
        general_qna_applicable = False
        trace_marker(
            thread_id,
            "detour_reentry",
            detail="Forcing room availability path after detour",
            data={"caller_step": caller_step, "change_detour": state.extras.get("change_detour", False)},
            owner_step="Step3_Room",
        )

    # -------------------------------------------------------------------------
    # PURE Q&A DETECTION (Dec 29, 2025, updated Jan 2026)
    # Allow pure Q&A QUESTIONS about catering, parking, accessibility, etc. even on
    # first Step 3 entry. These are informational queries, not workflow requests.
    # IMPORTANT: Only detect QUESTIONS, not mentions in booking requests.
    # "coffee break needed" is NOT a question; "what catering options?" IS a question.
    # -------------------------------------------------------------------------
    message_lower = message_text.lower() if message_text else ""
    # Check for question patterns about Q&A topics (not workflow actions)
    pure_qna_patterns = [
        # Catering/food patterns
        r"what.*(catering|menu|food|drink|coffee|lunch|dinner|breakfast)",
        r"(catering|menu|food|drink).*\?",
        r"(do you|can you|could you).*(catering|menu|food|offer)",
        r"(tell me|info|information).*(catering|menu|food)",
        r"what.*available.*(catering|menu|food)",
        r"(which|what).*(options|choices).*(catering|menu|food|drink)",
        # Parking patterns
        r"(is there|do you have|where).*(parking|car park|parkplatz)",
        r"parking.*\?",
        r"(where|can i|could i).*(park)",
        # Accessibility patterns
        r"(is|are).*(wheelchair|accessible|handicap|disability|disabled)",
        r"accessibility.*\?",
        r"(do you have|is there).*(ramp|elevator|lift|accessible)",
        # Room features/equipment patterns
        r"(does|do).*(room|venue).*(have|has).*(projector|screen|av|wifi|audio|microphone)",
        r"(what|which).*(equipment|facilities|amenities).*\?",
        r"(is there|do you have).*(projector|screen|whiteboard|flipchart)",
        # Pricing/rate patterns
        r"(what|how much).*(cost|price|rate|charge)",
        r"(pricing|rates?).*\?",
    ]
    is_pure_qna = any(re.search(pat, message_lower) for pat in pure_qna_patterns)

    # Don't take Q&A path for initial inquiries (first entry to Step 3)
    # The Q&A path is for follow-up questions after rooms have been presented
    # Check if rooms have been presented by looking for:
    # - room_pending_decision (set after presenting room options)
    # - locked_room_id (set after client confirms a room)
    room_pending = event_entry.get("room_pending_decision")
    locked_room = event_entry.get("locked_room_id")
    has_step3_history = room_pending is not None or locked_room is not None

    # -------------------------------------------------------------------------
    # PRODUCT ARRANGEMENT DETECTION: Check if client wants to arrange missing products
    # This happens when we've presented rooms with missing items and asked
    # "Would you like me to check if I can arrange it separately?"
    # -------------------------------------------------------------------------
    missing_products = (room_pending or {}).get("missing_products", [])
    logger.debug("[Step3] ARRANGEMENT CHECK: room_pending=%s, missing_products=%s, message_text=%s, locked_room=%s",
                 bool(room_pending), missing_products, message_text[:50] if message_text else None, locked_room)
    if room_pending and missing_products and message_text and not locked_room:
        arrangement_result = detect_product_arrangement_intent(
            message_text,
            missing_products,
        )
        if arrangement_result.wants_arrangement:
            trace_marker(
                thread_id,
                "arrangement_request_detected",
                detail=f"Client wants to arrange: {arrangement_result.products_to_source}",
                owner_step="Step3_Room",
            )
            return _handle_product_sourcing_request(
                state,
                event_entry,
                room_pending,
                arrangement_result,
                thread_id,
            )

    if general_qna_applicable and not has_step3_history:
        # First entry to Step 3 - only block workflow questions, not pure Q&A
        # HYBRID FIX: Check unified detection intent - if it's a booking intent (event_request),
        # this is a hybrid message (booking + Q&A) and should NOT take the pure Q&A path.
        # The Q&A will be appended to the workflow response via hybrid_qna_response.
        is_booking_intent = False
        if unified_detection:
            intent = getattr(unified_detection, "intent", None) or ""
            is_booking_intent = intent in ("event_request", "change_request", "negotiation")

        if not is_pure_qna or is_booking_intent:
            general_qna_applicable = False
            if is_booking_intent:
                trace_marker(
                    thread_id,
                    "hybrid_booking_detected",
                    detail=f"Booking intent '{intent}' with Q&A - using hybrid path",
                    owner_step="Step3_Room",
                )
        else:
            trace_marker(
                thread_id,
                "pure_qna_allowed",
                detail=f"Allowing pure Q&A on first Step 3 entry: {message_text[:50]}...",
                owner_step="Step3_Room",
            )

    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, classification, thread_id)
        return result

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _detour_to_date(state, event_entry)

    locked_room_id = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")

    # [SOURCING COMPLETE BYPASS] If sourcing was completed for this room,
    # skip room evaluation and proceed to offer
    sourced_products = event_entry.get("sourced_products")
    if sourced_products and sourced_products.get("room") == locked_room_id:
        logger.debug("[Step3] SOURCING COMPLETE - bypassing room eval, room=%s", locked_room_id)
        return _skip_room_evaluation(state, event_entry)

    room_selected_flag = bool(locked_room_id)
    trace_gate(
        thread_id,
        "Step3_Room",
        "room_selected",
        room_selected_flag,
        {"locked_room_id": locked_room_id},
    )

    requirements_match_flag = bool(
        room_selected_flag
        and current_req_hash
        and room_eval_hash
        and str(current_req_hash) == str(room_eval_hash)
    )
    trace_gate(
        thread_id,
        "Step3_Room",
        "requirements_match",
        requirements_match_flag,
        {"requirements_hash": current_req_hash, "room_eval_hash": room_eval_hash},
    )

    requirements_changed = not requirements_match_flag
    explicit_room_change = bool(user_requested_room and user_requested_room != locked_room_id)
    missing_lock = not room_selected_flag

    # BUG FIX (2026-01-24): If Step 2 detected that the locked room is unavailable
    # on the new date, we MUST re-evaluate rooms even if other conditions say skip.
    # This ensures the room availability overview is shown with alternative rooms.
    locked_room_unavailable = event_entry.get("_locked_room_unavailable_on_new_date", False)
    if locked_room_unavailable:
        logger.info("[Step3] Forcing room re-evaluation: locked room unavailable on new date")
        # Clear the flag since we're handling it now
        event_entry.pop("_locked_room_unavailable_on_new_date", None)
        # STORE cleared room info so verbalization tells user their room is unavailable
        # This must be done BEFORE clearing locked_room_id
        state.extras["_cleared_room_name"] = locked_room_id
        state.extras["_cleared_room_reason"] = "unavailable_on_new_date"
        # Clear the room lock so we can select a new room
        update_event_metadata(event_entry, locked_room_id=None, room_eval_hash=None)
        # CRITICAL: Also clear LOCAL variable to bypass FAST-SKIP section at line 925
        locked_room_id = None
        room_selected_flag = False
        missing_lock = True

    eval_needed = missing_lock or explicit_room_change or requirements_changed
    if not eval_needed:
        return _skip_room_evaluation(state, event_entry)

    user_info = state.user_info or {}
    vague_month = user_info.get("vague_month") or event_entry.get("vague_month")
    vague_weekday = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    range_detected = bool(user_info.get("range_query_detected") or event_entry.get("range_query_detected"))

    room_statuses = evaluate_room_statuses(
        state.db, chosen_date, exclude_event_id=state.event_id
    )
    summary = summarize_room_statuses(room_statuses)
    trace_db_read(
        thread_id,
        "Step3_Room",
        "db.rooms.search",
        {
            "date": chosen_date,
            "participants": participants,
            "rooms_checked": len(room_statuses),
            "sample": [
                {
                    "room": room,
                    "status": status,
                }
                for entry in room_statuses[:10]
                for room, status in entry.items()
            ],
            "result_summary": summary,
        },
    )
    status_map = _flatten_statuses(room_statuses)

    # -------------------------------------------------------------------
    # FAST-SKIP: If room is already locked and still available on new date
    # after a date change detour, skip room selection and return to caller
    # -------------------------------------------------------------------
    if locked_room_id and not explicit_room_change:
        locked_room_status = status_map.get(locked_room_id, "").lower()
        room_still_available = locked_room_status in ("available", "option")
        caller_step = event_entry.get("caller_step")

        trace_gate(
            thread_id,
            "Step3_Room",
            "locked_room_still_available",
            room_still_available,
            {
                "locked_room_id": locked_room_id,
                "status_on_new_date": locked_room_status,
                "caller_step": caller_step,
            },
        )

        # ---------------------------------------------------------------
        # FIX (Dec 29, 2025): Also check if requirements changed
        # If participant count increased, room might not fit anymore
        # ---------------------------------------------------------------
        requirements_changed_since_lock = (
            room_eval_hash is not None
            and current_req_hash is not None
            and str(current_req_hash) != str(room_eval_hash)
        )
        if requirements_changed_since_lock:
            # Requirements changed - force re-evaluation even if room is available
            room_still_available = False
            trace_marker(
                thread_id,
                "requirements_changed_force_reevaluate",
                detail=f"Requirements hash changed: {room_eval_hash} -> {current_req_hash}",
                owner_step="Step3_Room",
            )

        if room_still_available:
            # Room is still available on the new date - update hash and skip to caller
            # CRITICAL: Also invalidate offer_hash - date changed, so offer must be regenerated
            # even though room is still available. The offer shows the date, so it MUST be updated.
            update_event_metadata(
                event_entry,
                room_eval_hash=current_req_hash,  # Re-validate room for new date
                offer_hash=None,  # Force Step 4 to regenerate offer with new date
            )
            append_audit_entry(event_entry, 3, caller_step or 4, "room_revalidated_after_date_change")

            trace_marker(
                thread_id,
                "fast_skip_room_still_available",
                detail=f"Room {locked_room_id} still {locked_room_status} on {chosen_date}, skipping to step {caller_step}",
                owner_step="Step3_Room",
            )

            return _skip_room_evaluation(state, event_entry)
        else:
            # Room is no longer available - clear lock and continue to room selection
            update_event_metadata(
                event_entry,
                locked_room_id=None,
                room_eval_hash=None,
            )
            append_audit_entry(event_entry, 3, 3, "room_unavailable_after_date_change")
            # Log room denied activity for manager visibility
            from activity.persistence import log_workflow_activity
            log_workflow_activity(event_entry, "room_denied", room=locked_room_id, date=chosen_date)

            # STORE cleared room info so we can tell the user their room is no longer available
            state.extras["_cleared_room_name"] = locked_room_id
            state.extras["_cleared_room_reason"] = "unavailable_on_new_date"

            trace_marker(
                thread_id,
                "room_lock_cleared",
                detail=f"Room {locked_room_id} is {locked_room_status} on {chosen_date}, clearing lock",
                owner_step="Step3_Room",
            )

    preferred_room = _preferred_room(event_entry, user_requested_room)
    preferences = event_entry.get("preferences") or state.user_info.get("preferences") or {}
    explicit_preferences = _has_explicit_preferences(preferences)
    catering_tokens = [str(token).strip().lower() for token in (preferences.get("catering") or []) if str(token).strip()]
    product_tokens = [str(token).strip().lower() for token in (preferences.get("products") or []) if str(token).strip()]
    if not product_tokens:
        product_tokens = [str(token).strip().lower() for token in (preferences.get("wish_products") or []) if str(token).strip()]
    ranked_rooms = rank_rooms(
        status_map,
        preferred_room=preferred_room,
        pax=participants,
        preferences=preferences,
    )
    profile_entries = rank_rooms_profiles(
        chosen_date,
        participants,
        status_map=status_map,
        needs_catering=catering_tokens,
        needs_products=product_tokens,
    )
    room_profiles = {entry["room"]: entry for entry in profile_entries}
    # NOTE: Do NOT re-sort ranked_rooms by profile order - that would override
    # the preferred_room bonus from rank_rooms(). The ranking from sorting.py
    # already considers availability, capacity, preferences AND preferred_room.

    # Check if ANY room can accommodate the requested capacity
    capacity_exceeded = False
    max_venue_capacity = 0
    if participants and participants > 0:
        if not any_room_fits_capacity(participants):
            capacity_exceeded = True
            max_venue_capacity = get_max_capacity()
            logger.debug("[Step3][CAPACITY_EXCEEDED] Requested %d guests, max venue capacity is %d",
                        participants, max_venue_capacity)

    # If capacity exceeds all rooms, handle it specially
    if capacity_exceeded:
        return _handle_capacity_exceeded(
            state=state,
            event_entry=event_entry,
            participants=participants,
            max_capacity=max_venue_capacity,
            chosen_date=chosen_date,
        )

    # -------------------------------------------------------------------------
    # FIX: When user explicitly requests a room (e.g., "Room B looks perfect"),
    # use THEIR choice if it's available, not the ranking algorithm's choice.
    # This ensures room confirmation works correctly for hybrid messages.
    # -------------------------------------------------------------------------
    if user_requested_room:
        # Find the user's room in the ranked list
        user_room_entry = next(
            (r for r in ranked_rooms if r.room.lower() == user_requested_room.lower()),
            None
        )
        if user_room_entry and user_room_entry.status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION):
            # User's requested room is available - use it
            selected_entry = user_room_entry
            logger.info("[Step3] Using user's explicit room choice: %s (status=%s)",
                       user_room_entry.room, user_room_entry.status)
        else:
            # User's room not available - fall back to ranking
            selected_entry = _select_room(ranked_rooms)
            logger.debug("[Step3] User requested %s but not available, using ranked: %s",
                        user_requested_room, selected_entry.room if selected_entry else None)
    else:
        selected_entry = _select_room(ranked_rooms)

    selected_room = selected_entry.room if selected_entry else None
    selected_status = selected_entry.status if selected_entry else None

    outcome = selected_status or ROOM_OUTCOME_UNAVAILABLE

    candidate_mode = "alternatives"
    candidate_iso_dates: List[str] = []
    if range_detected and (vague_month or vague_weekday):
        candidate_iso_dates = _dates_in_month_weekday_wrapper(vague_month, vague_weekday, limit=5)
        candidate_mode = "range"
    else:
        iso_anchor = _to_iso(chosen_date)
        if iso_anchor:
            candidate_iso_dates = _closest_alternatives_wrapper(
                iso_anchor,
                vague_weekday,
                vague_month,
                limit=3,
            )
        if not candidate_iso_dates and (vague_month or vague_weekday):
            candidate_iso_dates = _dates_in_month_weekday_wrapper(vague_month, vague_weekday, limit=5)
            candidate_mode = "range"

    available_dates_map = _available_dates_for_rooms(
        state.db,
        ranked_rooms,
        candidate_iso_dates,
        participants,
    )

    table_rows, actions = _build_ranked_rows(
        chosen_date,
        ranked_rooms,
        preferences if explicit_preferences else None,
        available_dates_map,
        room_profiles,
    )

    display_chosen_date = _format_display_date(chosen_date)

    outcome_topic = {
        ROOM_OUTCOME_AVAILABLE: "room_available",
        ROOM_OUTCOME_OPTION: "room_option",
        ROOM_OUTCOME_UNAVAILABLE: "room_unavailable",
    }[outcome]

    # Show ALL available rooms, not just top 3 (client needs complete visibility)
    verbalizer_rooms = _verbalizer_rooms_payload(
        ranked_rooms,
        room_profiles,
        available_dates_map,
        needs_products=product_tokens,
        limit=len(ranked_rooms),  # All rooms
    )
    rendered = render_rooms(
        state.event_id or "",
        chosen_date,
        participants or 0,
        verbalizer_rooms,
    )
    assistant_draft = rendered.get("assistant_draft", {})
    body_markdown = assistant_draft.get("body", "")
    # Headers are rendered at TOP of message in frontend
    # Per UX design principle: conversational message first, summary info via info links
    # Determine if this is a room CONFIRMATION (user selected a room) vs initial PRESENTATION
    is_room_confirmation = (
        user_requested_room
        and selected_room
        and user_requested_room.lower() == selected_room.lower()
        and outcome in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}
    )
    # DEBUG: Trace room confirmation logic
    print(f"[STEP3][ROOM_CONFIRM_CHECK] user_requested_room={user_requested_room!r}, selected_room={selected_room!r}, outcome={outcome!r}, is_room_confirmation={is_room_confirmation}")
    if is_room_confirmation:
        headers = ["Room Confirmed"]
        outcome_topic = "room_confirmed"  # Override topic for verbalizer
    else:
        headers = ["Availability overview"]
    table_blocks = rendered.get("table_blocks")
    if not table_blocks and table_rows:
        label = f"Rooms for {display_chosen_date}" if display_chosen_date else "Room options"
        table_blocks = [
            {
                "type": "room_menu",
                "label": label,
                "rows": table_rows,
            }
        ]
    elif not table_blocks:
        table_blocks = []
    actions_payload = rendered.get("actions")
    if not actions_payload:
        actions_payload = actions or [{"type": "send_reply"}]

    # Build ONLY conversational intro for chat message
    # Structured room data is in table_blocks (rendered separately in UI)
    # Keep it concise - structured data is in the link, not repeated here
    intro_lines: List[str] = []
    # CTA/closing sentence collected separately - ALWAYS appended LAST (after catering teaser etc.)
    closing_cta: Optional[str] = None
    num_rooms = len(verbalizer_rooms) if verbalizer_rooms else 0
    room_word = "room" if num_rooms == 1 else "rooms"

    # Get room capacity for selected room from verbalizer payload
    selected_room_capacity = None
    if selected_room and verbalizer_rooms:
        for vr in verbalizer_rooms:
            if vr.get("name") == selected_room:
                selected_room_capacity = vr.get("capacity")
                break

    # Get client's wish products for acknowledgment
    client_prefs = event_entry.get("preferences") or {}
    wish_products_list = client_prefs.get("wish_products") or []

    # CHECK: Was a previously selected room cleared because it became unavailable?
    # This happens when the user changes the date and their locked room is blocked on the new date
    cleared_room_name = state.extras.get("_cleared_room_name")
    if cleared_room_name:
        # Tell the user explicitly that their previously selected room is no longer available
        # This is just a PREFIX - the normal room recommendation logic will add the alternatives
        intro_lines.append(
            f"{cleared_room_name} is no longer available on {display_chosen_date or 'your new date'}."
        )
        # Clear the flag so it's not repeated
        state.extras.pop("_cleared_room_name", None)
        state.extras.pop("_cleared_room_reason", None)
        # Fall through to the recommendation logic below (don't use elif)

    if user_requested_room and user_requested_room != selected_room:
        intro_lines.append(
            f"{user_requested_room} isn't available on {display_chosen_date or 'your date'}. "
            f"I've found {num_rooms} alternative {room_word} that work."
        )
        closing_cta = f"Let me know which {room_word} you'd like and I'll prepare the offer."
    elif is_room_confirmation:
        # User confirmed a specific room - store confirmation intro for Step 4 (offer)
        # The confirmation message becomes the INTRO to the offer (one combined message)
        # No separate draft message here - Step 4 will prepend this to the offer
        confirmation_intro = (
            f"Great choice! {selected_room} on {display_chosen_date or 'your date'} is confirmed "
            f"for your event with {participants} guests."
        )
        # Store for Step 4 to prepend to offer
        event_entry["room_confirmation_prefix"] = confirmation_intro + "\n\n"
        # No closing_cta or intro_lines needed - Step 4 handles the full message
        # Set flag to skip draft message creation (handled below)
        closing_cta = None  # Explicitly no CTA - Step 4 will handle it
    elif selected_room and outcome in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
        # Build recommendation with gatekeeping variables (date, capacity, equipment)
        # Echo back client requirements ("sandwich check")
        # DECISION-010: Check which requested items are actually available vs missing
        selected_room_data = next(
            (vr for vr in verbalizer_rooms if vr.get("name") == selected_room),
            {}
        )
        room_requirements = selected_room_data.get("requirements") or {}
        matched_items = [str(m).lower() for m in (room_requirements.get("matched") or [])]
        missing_items = [str(m).lower() for m in (room_requirements.get("missing") or [])]

        reason_parts = []
        if selected_room_capacity:
            reason_parts.append(f"accommodates up to {selected_room_capacity} guests")

        # Only claim items that are actually matched, NOT all wish_products
        if wish_products_list:
            # Filter to only include items that are matched (not missing)
            available_products = [
                str(p).lower() for p in wish_products_list[:3]
                if str(p).lower() in matched_items or str(p).lower() not in missing_items
            ]
            # Also check via badges if available
            badges = selected_room_data.get("badges") or {}
            for product in list(available_products):
                product_key = product.lower().strip()
                badge = badges.get(product_key)
                if badge == "✗":
                    available_products.remove(product)
                    if product not in missing_items:
                        missing_items.append(product)

            if available_products:
                products_str = ", ".join(available_products)
                reason_parts.append(f"includes your {products_str}")

        if reason_parts:
            reason_clause = " and ".join(reason_parts)
            intro_lines.append(
                f"For your event on {display_chosen_date or 'your date'} with {participants} guests, "
                f"I recommend {selected_room} because it {reason_clause}."
            )
        else:
            intro_lines.append(
                f"For your event on {display_chosen_date or 'your date'} with {participants} guests, "
                f"I recommend {selected_room}."
            )

        # DECISION-010: Apologize for missing items and offer to source them
        if missing_items:
            missing_str = ", ".join(missing_items)
            if len(missing_items) == 1:
                intro_lines.append(
                    f"Unfortunately, {missing_str} is not included in {selected_room}. "
                    f"Would you like me to check if I can arrange it separately?"
                )
            else:
                intro_lines.append(
                    f"Unfortunately, {missing_str} are not included in {selected_room}. "
                    f"Would you like me to check if I can arrange these separately?"
                )

        # Always compare with at least 1-2 alternative rooms for context
        if num_rooms > 1:
            alternatives = [vr for vr in verbalizer_rooms if vr.get("name") != selected_room][:2]
            if alternatives:
                alt_descriptions = []
                for alt in alternatives:
                    alt_name = alt.get("name", "")
                    alt_capacity = alt.get("capacity")
                    alt_reqs = alt.get("requirements") or {}
                    alt_matched = alt_reqs.get("matched") or []
                    alt_missing = alt_reqs.get("missing") or []

                    # Build brief comparison
                    if alt_matched and not alt_missing:
                        # Alternative has everything
                        cap_note = f" (capacity {alt_capacity})" if alt_capacity else ""
                        alt_descriptions.append(f"{alt_name}{cap_note} also has all your requirements")
                    elif alt_missing:
                        # Alternative is missing something
                        missing_list = ", ".join(alt_missing[:2])
                        alt_descriptions.append(f"{alt_name} lacks {missing_list}")
                    elif alt_capacity:
                        alt_descriptions.append(f"{alt_name} (capacity {alt_capacity})")
                    else:
                        alt_descriptions.append(alt_name)

                if alt_descriptions:
                    intro_lines.append(f"Alternatives: {'; '.join(alt_descriptions)}.")

            closing_cta = f"Let me know which room you'd prefer and I'll prepare the offer."
        else:
            closing_cta = f"Would you like me to prepare an offer for {selected_room}?"
    else:
        intro_lines.append(
            f"The requested date isn't available. Here are {num_rooms} alternative {room_word}."
        )
        closing_cta = f"Let me know which {room_word} you'd like and I'll prepare the offer."

    # -------------------------------------------------------------------------
    # CATERING TEASER: Only suggest if:
    # 1. Client hasn't mentioned catering/food, AND
    # 2. Client hasn't mentioned specific equipment (projector, sound, etc.)
    # If they mentioned equipment, they'll ask about catering if they want it.
    # Uses dynamic matching from product catalog (products.json) with synonyms.
    # -------------------------------------------------------------------------
    from services.products import text_matches_category

    client_prefs = event_entry.get("preferences") or {}
    wish_products = client_prefs.get("wish_products") or []
    # Also check requirements for product keywords
    special_reqs = (event_entry.get("requirements") or {}).get("special_requirements", "") or ""
    # Include original message text - may contain product mentions not yet extracted
    all_text = " ".join([str(p) for p in wish_products] + [special_reqs, message_text or ""])

    # Dynamic matching using product catalog categories and synonyms
    has_catering_request = (
        text_matches_category(all_text, "Catering") or
        text_matches_category(all_text, "Beverages")
    )
    # Check if client mentioned equipment/add-ons - if so, don't push catering
    has_equipment_request = (
        text_matches_category(all_text, "Equipment") or
        text_matches_category(all_text, "Add-ons") or
        text_matches_category(all_text, "Entertainment")
    )

    # Products for verbalizer fact verification (catering teaser prices)
    verbalizer_products: List[Dict[str, Any]] = []
    # Only add catering teaser if client mentioned neither catering nor equipment
    if not has_catering_request and not has_equipment_request:
        teaser_products = get_catering_teaser_products()
        if teaser_products:
            currency = get_currency_code()
            product_strs = [
                f"{p['name']} ({currency} {p['unit_price']:.2f}/person)"
                for p in teaser_products[:2]
            ]
            intro_lines.append("")  # Paragraph break
            intro_lines.append(
                f"Would you like to add catering? Our {' and '.join(product_strs)} are popular choices."
            )
            # Pass catering products to verbalizer so it knows these amounts are valid
            verbalizer_products = teaser_products[:2]
            # Flag that we've asked about catering - Step 4 should NOT ask again
            products_state = event_entry.setdefault("products_state", {})
            products_state["catering_teaser_shown"] = True

    # NOTE: closing_cta is appended AFTER room_link (see below) to ensure CTA is truly last

    # body_markdown = ONLY conversational prose (structured data is in table_blocks)
    # Use double newline for paragraph breaks (empty strings in list)
    body_parts = []
    for line in intro_lines:
        if line == "":
            body_parts.append("\n\n")
        else:
            if body_parts and body_parts[-1] != "\n\n":
                body_parts.append(" ")
            body_parts.append(line)
    body_markdown = "".join(body_parts).strip()

    # Create snapshot with full room data for persistent link
    # Include client preferences so info page can show feature matching
    snapshot_data = {
        "rooms": verbalizer_rooms,
        "table_rows": table_rows,
        "selected_room": selected_room,
        "outcome": outcome,
        "chosen_date": chosen_date,
        "display_date": display_chosen_date,
        "participants": participants,
        # Client preferences for info page feature comparison
        "client_preferences": {
            "wish_products": client_prefs.get("wish_products", []),
            "keywords": client_prefs.get("keywords", []),
            "special_requirements": (event_entry.get("requirements") or {}).get("special_requirements", ""),
        },
    }
    snapshot_id = create_snapshot(
        snapshot_type="rooms",
        data=snapshot_data,
        event_id=state.event_id,
        params={
            "date": event_entry.get("chosen_date") or "",
            "capacity": str(participants) if participants else "",
        },
    )
    room_link = generate_room_details_link(
        room_name=selected_room or "all",
        date=event_entry.get("chosen_date") or (display_chosen_date or ""),
        participants=participants or event_entry.get("number_of_participants", 0),
        snapshot_id=snapshot_id,
    )
    # Conversational message FIRST, then link, then CTA at the very end
    # (UX principle: CTA/closing sentence is always the final actionable element)
    if body_markdown:
        body_markdown = "\n".join([body_markdown, "", room_link])
    else:
        body_markdown = room_link

    # CTA/closing sentence ALWAYS appended LAST (after room_link and all other content)
    if closing_cta:
        body_markdown = "\n".join([body_markdown, "", closing_cta])

    shortcut_note = None
    if state.extras.get("qna_shortcut"):
        shortcut_payload = state.extras["qna_shortcut"]
        shortcut_link = shortcut_payload.get("link")
        shortcut_note = (
            f"[VERBALIZER_SHORTCUT] Keep summary concise; if details exceed "
            f"{shortcut_payload.get('threshold')} chars, point to {shortcut_link} instead of expanding."
        )
    if shortcut_note:
        body_markdown = "\n".join([shortcut_note, "", body_markdown])

    # Universal Verbalizer: transform to warm, human-like message
    # Only the recommended room (room_name) is a required fact.
    # Other rooms are mentioned in the fallback text for LLM context but not required.
    from workflows.common.prompts import verbalize_draft_body

    body_markdown = verbalize_draft_body(
        body_markdown,
        step=3,
        topic=outcome_topic,
        event_date=display_chosen_date,
        participants_count=participants,
        rooms=verbalizer_rooms,  # Pass full room data including requirements.missing for honest claims
        room_name=selected_room,  # The recommended room (required fact)
        room_status=outcome,
        products=verbalizer_products,  # Pass catering products for fact verification
    )

    # Capture menu options separately (NOT in body_markdown - shown in info cards)
    qa_lines = _general_qna_lines(state)
    menu_content = None
    if qa_lines:
        menu_content = "\n".join(qa_lines)
        # headers already set above (either "Room Confirmed" or "Availability overview")
        state.record_subloop("general_q_a")
        state.extras["subloop"] = "general_q_a"

    # Skip draft message when room is confirmed - Step 4 will send combined message with offer
    # The confirmation intro is stored in event_entry["room_confirmation_prefix"] for Step 4
    if not is_room_confirmation:
        draft_message = {
            "body": body_markdown,
            "body_markdown": body_markdown,
            "body_md": body_markdown,
            "step": 3,
            "next_step": "Choose a room",
            "thread_state": "Awaiting Client",
            "topic": outcome_topic,
            "room": selected_room,
            "status": outcome,
            "table_blocks": table_blocks,
            "actions": actions_payload,
            "headers": headers,
            "menu_info": menu_content,  # Separate field for menu data (rendered in info cards)
        }
        # Do not escalate room availability to HIL; approvals only happen at offer/negotiation (Step 5).
        hil_required = False
        thread_state_label = "Awaiting Client"
        draft_message["thread_state"] = thread_state_label
        draft_message["requires_approval"] = hil_required
        draft_message["rooms_summary"] = verbalizer_rooms
        state.add_draft_message(draft_message)

    attempt = _increment_room_attempt(event_entry)
    hil_required = False
    thread_state_label = "Awaiting Client"

    pending_hint = _derive_hint(selected_entry, preferences, explicit_preferences) if selected_entry else None

    # Collect missing products for ALL rooms (for arrange request handling)
    # This allows us to know what's missing when client selects a different room than recommended
    rooms_missing_products = {}
    all_missing_products = []  # Union of all rooms' missing products
    for vr in verbalizer_rooms:
        room_name = vr.get("name", "")
        room_missing = (vr.get("requirements") or {}).get("missing") or []
        if room_missing:
            rooms_missing_products[room_name] = room_missing
            for product in room_missing:
                if product not in all_missing_products:
                    all_missing_products.append(product)

    # -------------------------------------------------------------------------
    # ROOM CONFIRMATION: Lock room and advance to Step 4
    # When client explicitly confirms a room, persist the selection immediately
    # -------------------------------------------------------------------------
    if is_room_confirmation and selected_room:
        # Lock the room and advance to Step 4 (offer)
        update_event_metadata(
            event_entry,
            locked_room_id=selected_room,
            room_eval_hash=current_req_hash,
            current_step=4,
            thread_state=thread_state_label,
            status="Option",  # Room selected → calendar blocked as Option
        )
        _reset_room_attempts(event_entry)
        # Clear room_pending_decision since room is now locked
        event_entry.pop("room_pending_decision", None)
        event_entry["selected_room"] = selected_room
        event_entry["selected_room_status"] = outcome
        event_entry.setdefault("flags", {})["room_selected"] = True

        state.current_step = 4
        state.set_thread_state(thread_state_label)
        state.caller_step = event_entry.get("caller_step")
        state.extras["persist"] = True

        trace_db_write(
            thread_id,
            "Step3_Room",
            "db.events.lock_room",
            {"locked_room_id": selected_room, "room_eval_hash": current_req_hash, "status": "Option"},
        )
        trace_gate(thread_id, "Step3_Room", "room_confirmed", True, {"room": selected_room})
        append_audit_entry(event_entry, 3, 4, "room_confirmed_by_client")

        logger.info("[Step3] Room confirmed by client: %s -> advancing to Step 4", selected_room)
    else:
        # Room presented but not yet confirmed - store pending decision
        event_entry["room_pending_decision"] = {
            "selected_room": selected_room,
            "selected_status": outcome,
            "requirements_hash": current_req_hash,
            "summary": summary,
            "hint": pending_hint,
            "available_dates": available_dates_map.get(selected_room or "", []),
            "missing_products": all_missing_products,  # All products that might be missing
            "rooms_missing_products": rooms_missing_products,  # Per-room breakdown
        }

        update_event_metadata(
            event_entry,
            thread_state=thread_state_label,
            current_step=3,
        )

        state.set_thread_state(thread_state_label)
        state.caller_step = event_entry.get("caller_step")
        state.current_step = 3
        state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "selected_room": selected_room,
            "room_status_preview": outcome,
            "eval_hash": current_req_hash,
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "requirements_hash": event_entry.get("requirements_hash") or current_req_hash,
            "locked_room_id": event_entry.get("locked_room_id"),
            "room_hint": pending_hint,
            "available_dates": available_dates_map,
            "subloop": state.extras.get("subloop"),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "selected_room": selected_room,
        "selected_status": outcome,
        "room_rankings": table_rows,
        "room_hint": pending_hint,
        "actions": [{"type": "send_reply"}],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "available_dates": available_dates_map,
    }
    payload["room_proposal_attempts"] = attempt
    payload["hil_escalated"] = hil_required
    if capacity_shortcut:
        payload["shortcut_capacity_ok"] = True
    # When room is confirmed, DON'T halt - continue to Step 4 to generate offer automatically
    # Step 4 will use the room_confirmation_prefix to create combined message
    should_halt = not is_room_confirmation
    result = GroupResult(action="room_avail_result", payload=payload, halt=should_halt)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


# R4: evaluate_room_statuses moved to evaluation.py


# R4: render_rooms_response moved to evaluation.py

# R8 (Jan 2026): Sourcing handler functions moved to sourcing_handler.py:
# - _handle_product_sourcing_request, _advance_to_offer_from_sourcing

# R6 (Jan 2026): Detour handling functions moved to detour_handling.py
# - _detour_to_date, _detour_for_capacity
# - _skip_room_evaluation, _handle_capacity_exceeded

# R8 (Jan 2026): HIL operations moved to hil_ops.py:
# - _apply_hil_decision, _preferred_room, _increment_room_attempt

# R4: _flatten_statuses moved to evaluation.py

# R7 (Jan 2026): Room ranking functions moved to room_ranking.py:
# - _needs_better_room_alternatives, _has_explicit_preferences
# - _extract_participants, _room_requirements_payload, _derive_hint

# R7 (Jan 2026): Room presentation functions moved to room_presentation.py:
# - _compose_preselection_header, _verbalizer_rooms_payload


def _general_qna_lines(state: WorkflowState) -> List[str]:
    # Use shared format_menu_line_short from menu_options module

    payload = state.turn_notes.get("general_qa")
    rows: Optional[List[Dict[str, Any]]] = None
    title: Optional[str] = None
    month_hint: Optional[str] = None
    request: Optional[Dict[str, Any]] = None  # Initialize to prevent NameError if payload branch taken
    event_entry = state.event_entry or {}
    if not payload:
        payload = event_entry.get("general_qa_payload")
    if isinstance(payload, dict) and payload.get("rows"):
        rows = payload["rows"]
        title = payload.get("title")
        month_hint = payload.get("month")
    else:
        request = extract_menu_request(state.message.body or "")
        if request:
            user_info = state.user_info or {}
            event_entry = state.event_entry or {}
            context_month = user_info.get("vague_month") or event_entry.get("vague_month")
            rows = select_menu_options(request, month_hint=request.get("month"))
            if not rows and ALLOW_CONTEXTUAL_HINTS and context_month:
                rows = select_menu_options(request, month_hint=context_month)
            if rows:
                title = build_menu_title(request)
        elif event_entry:
            context_month = (event_entry.get("vague_month") or "").lower() or (state.user_info or {}).get("vague_month")
            default_request = {"menu_requested": True, "wine_pairing": True, "three_course": True, "month": context_month}
            rows = select_menu_options(default_request, month_hint=context_month) if context_month else select_menu_options(default_request)
            if rows:
                title = build_menu_title(default_request)
    if not rows:
        return []
    lines = [title or "Menu options we can offer:"]
    for row in rows:
        rendered = format_menu_line_short(row)
        if rendered:
            lines.append(rendered)

    combined_len = len("\n".join(lines))

    # Build dynamic query parameters from Q&A extraction (already done by LLM)
    query_params = {}
    qna_extraction = state.extras.get("qna_extraction", {})
    q_values = qna_extraction.get("q_values", {})

    # Extract date/month from Q&A detection
    if q_values.get("date"):
        query_params["date"] = str(q_values["date"])
    elif q_values.get("date_pattern"):
        query_params["month"] = str(q_values["date_pattern"]).lower()

    # Extract capacity from Q&A detection
    if q_values.get("n_exact"):
        query_params["capacity"] = str(q_values["n_exact"])
    elif q_values.get("n_range"):
        n_range = q_values["n_range"]
        if isinstance(n_range, dict) and n_range.get("min"):
            query_params["capacity"] = str(n_range["min"])

    # Extract product attributes (vegetarian, vegan, wine pairing, etc.) from Q&A detection
    product_attrs = q_values.get("product_attributes") or []
    if isinstance(product_attrs, list):
        for attr in product_attrs:
            attr_lower = str(attr).lower()
            if "vegetarian" in attr_lower:
                query_params["vegetarian"] = "true"
            if "vegan" in attr_lower:
                query_params["vegan"] = "true"
            if "wine" in attr_lower or "pairing" in attr_lower:
                query_params["wine_pairing"] = "true"
            if ("three" in attr_lower or "3" in attr_lower) and "course" in attr_lower:
                query_params["courses"] = "3"

    # Also check the menu request for additional attributes (fallback)
    if request:
        if request.get("vegetarian") and "vegetarian" not in query_params:
            query_params["vegetarian"] = "true"
        if request.get("wine_pairing") and "wine_pairing" not in query_params:
            query_params["wine_pairing"] = "true"
        if request.get("three_course") and "courses" not in query_params:
            query_params["courses"] = "3"

    # Create snapshot with full menu data for persistent link
    # Normalize menus to frontend display format (name, price_per_person, availability_window, etc.)
    snapshot_data = {
        "menus": [normalize_menu_for_display(r) for r in rows] if rows else [],
        "title": title,
        "month_hint": month_hint,
        "lines": lines,
    }
    snapshot_id = create_snapshot(
        snapshot_type="catering",
        data=snapshot_data,
        event_id=state.event_id,
        params=query_params,
    )
    shortcut_link = generate_qna_link("Catering", query_params=query_params if query_params else None, snapshot_id=snapshot_id)
    if combined_len > QNA_SUMMARY_CHAR_THRESHOLD:
        lines = [
            f"Full menu details: {shortcut_link}",
            "(Keeping this brief so you can compare quickly.)",
            "",
        ] + lines
        state.extras["qna_shortcut"] = {"link": shortcut_link, "threshold": QNA_SUMMARY_CHAR_THRESHOLD, "snapshot_id": snapshot_id}
    else:
        lines.append("")
        lines.append(f"Full menu details: {shortcut_link}")
        state.extras["qna_shortcut"] = {"link": shortcut_link, "threshold": QNA_SUMMARY_CHAR_THRESHOLD, "snapshot_id": snapshot_id}
    # TODO(verbalizer): use shortcut_link to summarize long Q&A payloads instead of dumping full text.
    return lines


# R7 (Jan 2026): Room ranking functions moved to room_ranking.py:
# - _build_ranked_rows, _select_room
# - _dates_in_month_weekday_wrapper, _closest_alternatives_wrapper, _available_dates_for_rooms

# R7 (Jan 2026): Room presentation functions moved to room_presentation.py:
# - _format_requirements_line, _format_room_sections
# - _format_range_descriptor, _format_dates_list

# R3: Functions moved to selection.py:
# - handle_select_room_action
# - _thread_id
# - _reset_room_attempts
# - _format_display_date

# R5 (Jan 2026): CONFLICT RESPONSE HANDLING moved to conflict_resolution.py
# - _handle_conflict_response, _detect_wants_alternative, _detect_wants_to_insist
# - _extract_insist_reason, _is_generic_question
# - _handle_conflict_choose_alternative, _handle_conflict_insist_with_reason
# - _handle_conflict_ask_for_reason, _collect_alternative_dates
# - _merge_alternative_dates, _dedupe_dates, _format_alternative_dates_section
# - _strip_system_subject, _message_text, _format_short_date, _to_iso



def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 3 - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id,
        step_number=3, step_name="Room Availability"
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
        # Restore drafts to their previous count to avoid leaking the standalone Q&A draft.
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
