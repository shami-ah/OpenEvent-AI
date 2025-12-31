from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.workflows.common.prompts import append_footer
from backend.workflows.common.menu_options import (
    ALLOW_CONTEXTUAL_HINTS,
    build_menu_title,
    extract_menu_request,
    format_menu_line,
    format_menu_line_short,
    MENU_CONTENT_CHAR_THRESHOLD,
    normalize_menu_for_display,
    select_menu_options,
)
from backend.workflows.common.capture import capture_workflow_requirements
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.sorting import rank_rooms, RankedRoom
from backend.workflows.common.room_rules import find_better_room_dates
from backend.workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import check_nonsense_gate
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy, parse_ddmmyyyy
from backend.workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
    _fallback_structured_body,
)
from backend.workflows.change_propagation import (
    ChangeType,
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata, update_event_room
from backend.workflows.io.config_store import get_catering_teaser_products, get_currency_code
# MIGRATED: from backend.workflows.common.conflict -> backend.detection.special.room_conflict
from backend.detection.special.room_conflict import (
    ConflictType,
    detect_conflict_type,
    compose_soft_conflict_warning,
)
from backend.debug.hooks import trace_db_read, trace_db_write, trace_detour, trace_gate, trace_state, trace_step, set_subloop, trace_marker, trace_general_qa_status
from backend.utils.profiler import profile_step
from backend.utils.pseudolinks import generate_room_details_link, generate_qna_link
from backend.utils.page_snapshots import create_snapshot
from backend.workflow_verbalizer_test_hooks import render_rooms
from backend.workflows.steps.step3_room_availability.db_pers import load_rooms_config
from backend.workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from backend.rooms import rank as rank_rooms_profiles, get_max_capacity, any_room_fits_capacity

from ..condition.decide import room_status_on_date
from ..llm.analysis import summarize_room_statuses
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

__workflow_role__ = "trigger"

# Use shared threshold from menu_options; kept as alias for backward compat
QNA_SUMMARY_CHAR_THRESHOLD = MENU_CONTENT_CHAR_THRESHOLD


@trace_step("Step3_Room")
@profile_step("workflow.step3.room_availability")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment with entry guards and caching."""

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

    # [CHANGE DETECTION + Q&A] Tap incoming stream BEFORE room evaluation to detect client revisions
    # ("actually we're 50 now") and route them back to dependent nodes while hashes stay valid.
    message_text = _message_text(state)
    user_info = state.user_info or {}

    # Capture requirements from workflow context (statements only, not questions)
    if message_text and state.user_info:
        capture_workflow_requirements(state, message_text, state.user_info)

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
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
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
    enhanced_result = detect_change_type_enhanced(event_entry, user_info, message_text=message_text)
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

    # [SKIP DUPLICATE DETOUR] If a date change is detected but the date in the message
    # matches the already-confirmed chosen_date, skip the detour. This happens when
    # Step 2's finalize_confirmation internally calls Step 3 on the same message.
    if change_type == ChangeType.DATE and event_entry.get("date_confirmed"):
        from backend.workflows.common.datetime_parse import parse_all_dates
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

            # Skip Q&A: return detour signal
            # CRITICAL: Update event_entry BEFORE state.current_step so routing loop sees the change
            update_event_metadata(event_entry, current_step=decision.next_step)
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True

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

    # No change detected: check if Q&A should be handled
    # NOTE: Room can be detected via _room_choice_detected OR via ChangeType.ROOM detection
    # The change_type variable is set earlier (line ~233) if a room change was detected
    room_change_detected_flag = state.user_info.get("_room_choice_detected") or (change_type == ChangeType.ROOM)
    user_requested_room = state.user_info.get("room") if room_change_detected_flag else None
    locked_room_id = event_entry.get("locked_room_id")

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client confirms room AND asks about catering/offer, that's NOT
    # general Q&A - it's natural workflow continuation.
    # Example: "Room A looks good, what catering options do you have?"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=3)
    if sequential_check.get("is_sequential"):
        # Client is selecting room AND asking about next step - natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
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

    # -------------------------------------------------------------------------
    # DETOUR RE-ENTRY GUARD (Dec 29, 2025)
    # After a change_detour (e.g., participant change), force normal room availability
    # path instead of Q&A fallback. The change_detour flag is set by the routing loop.
    # -------------------------------------------------------------------------
    is_detour_reentry = state.extras.get("change_detour", False)
    if is_detour_reentry:
        general_qna_applicable = False
        trace_marker(
            thread_id,
            "detour_reentry",
            detail="Forcing room availability path after change_detour",
            owner_step="Step3_Room",
        )

    # -------------------------------------------------------------------------
    # PURE Q&A DETECTION (Dec 29, 2025)
    # Allow pure Q&A QUESTIONS about catering, menu, etc. even on first Step 3 entry.
    # These are informational queries, not workflow requests.
    # IMPORTANT: Only detect QUESTIONS, not mentions of catering in booking requests.
    # "coffee break needed" is NOT a question; "what catering options?" IS a question.
    # -------------------------------------------------------------------------
    message_lower = message_text.lower() if message_text else ""
    # Check for question patterns about catering/food
    catering_question_patterns = [
        r"what.*(catering|menu|food|drink|coffee|lunch|dinner|breakfast)",
        r"(catering|menu|food|drink).*\?",
        r"(do you|can you|could you).*(catering|menu|food|offer)",
        r"(tell me|info|information).*(catering|menu|food)",
        r"what.*available.*(catering|menu|food)",
        r"(which|what).*(options|choices).*(catering|menu|food|drink)",
    ]
    is_pure_qna = any(re.search(pat, message_lower) for pat in catering_question_patterns)

    # Don't take Q&A path for initial inquiries (first entry to Step 3)
    # The Q&A path is for follow-up questions after rooms have been presented
    # Check if rooms have been presented by looking for:
    # - room_pending_decision (set after presenting room options)
    # - locked_room_id (set after client confirms a room)
    room_pending = event_entry.get("room_pending_decision")
    locked_room = event_entry.get("locked_room_id")
    has_step3_history = room_pending is not None or locked_room is not None
    if general_qna_applicable and not has_step3_history:
        # First entry to Step 3 - only block workflow questions, not pure Q&A
        if not is_pure_qna:
            general_qna_applicable = False
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

    eval_needed = missing_lock or explicit_room_change or requirements_changed
    if not eval_needed:
        return _skip_room_evaluation(state, event_entry)

    user_info = state.user_info or {}
    vague_month = user_info.get("vague_month") or event_entry.get("vague_month")
    vague_weekday = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    range_detected = bool(user_info.get("range_query_detected") or event_entry.get("range_query_detected"))

    room_statuses = evaluate_room_statuses(state.db, chosen_date)
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
            update_event_metadata(
                event_entry,
                room_eval_hash=current_req_hash,  # Re-validate room for new date
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
            print(f"[Step3][CAPACITY_EXCEEDED] Requested {participants} guests, max venue capacity is {max_venue_capacity}")

    # If capacity exceeds all rooms, handle it specially
    if capacity_exceeded:
        return _handle_capacity_exceeded(
            state=state,
            event_entry=event_entry,
            participants=participants,
            max_capacity=max_venue_capacity,
            chosen_date=chosen_date,
        )

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

    verbalizer_rooms = _verbalizer_rooms_payload(
        ranked_rooms,
        room_profiles,
        available_dates_map,
        needs_products=product_tokens,
        limit=3,
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
    # Keep headers minimal - just "Availability overview" for context
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

    if user_requested_room and user_requested_room != selected_room:
        intro_lines.append(
            f"{user_requested_room} isn't available on {display_chosen_date or 'your date'}. "
            f"I've found {num_rooms} alternative {room_word} that work."
        )
        intro_lines.append(f"Let me know which {room_word} you'd like and I'll prepare the offer.")
    elif selected_room and outcome in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
        # Build recommendation with gatekeeping variables (date, capacity, equipment)
        # Echo back client requirements ("sandwich check")
        reason_parts = []
        if selected_room_capacity:
            reason_parts.append(f"accommodates up to {selected_room_capacity} guests")
        if wish_products_list:
            products_str = ", ".join(str(p).lower() for p in wish_products_list[:3])
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

        if num_rooms > 1:
            intro_lines.append(f"Would you like {selected_room}, or see other options?")
        else:
            intro_lines.append(f"Would you like me to prepare an offer for {selected_room}?")
    else:
        intro_lines.append(
            f"The requested date isn't available. Here are {num_rooms} alternative {room_word}."
        )
        intro_lines.append(f"Let me know which {room_word} you'd like and I'll prepare the offer.")

    # -------------------------------------------------------------------------
    # CATERING TEASER: Only suggest if:
    # 1. Client hasn't mentioned catering/food, AND
    # 2. Client hasn't mentioned specific equipment (projector, sound, etc.)
    # If they mentioned equipment, they'll ask about catering if they want it.
    # Uses dynamic matching from product catalog (products.json) with synonyms.
    # -------------------------------------------------------------------------
    from backend.services.products import text_matches_category

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
    # Conversational message FIRST, then summary/link at end
    # (per UX design principle: direct address to client first)
    if body_markdown:
        body_markdown = "\n".join([body_markdown, "", room_link])
    else:
        body_markdown = room_link

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
    from backend.workflows.common.prompts import verbalize_draft_body

    body_markdown = verbalize_draft_body(
        body_markdown,
        step=3,
        topic=outcome_topic,
        event_date=display_chosen_date,
        participants_count=participants,
        rooms=[],  # Don't require other rooms - only room_name is required
        room_name=selected_room,  # The recommended room (required fact)
        room_status=outcome,
        products=verbalizer_products,  # Pass catering products for fact verification
    )

    # Capture menu options separately (NOT in body_markdown - shown in info cards)
    qa_lines = _general_qna_lines(state)
    menu_content = None
    if qa_lines:
        menu_content = "\n".join(qa_lines)
        # headers already set to ["Availability overview"] above
        state.record_subloop("general_q_a")
        state.extras["subloop"] = "general_q_a"

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
    attempt = _increment_room_attempt(event_entry)
    # Do not escalate room availability to HIL; approvals only happen at offer/negotiation (Step 5).
    hil_required = False
    thread_state_label = "Awaiting Client"
    draft_message["thread_state"] = thread_state_label
    draft_message["requires_approval"] = hil_required
    draft_message["rooms_summary"] = verbalizer_rooms
    state.add_draft_message(draft_message)

    pending_hint = _derive_hint(selected_entry, preferences, explicit_preferences) if selected_entry else None

    event_entry["room_pending_decision"] = {
        "selected_room": selected_room,
        "selected_status": outcome,
        "requirements_hash": current_req_hash,
        "summary": summary,
        "hint": pending_hint,
        "available_dates": available_dates_map.get(selected_room or "", []),
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
    result = GroupResult(action="room_avail_result", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


# R4: evaluate_room_statuses moved to evaluation.py


# R4: render_rooms_response moved to evaluation.py


def _detour_to_date(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Redirect to Step 2 when no chosen date exists."""

    thread_id = _thread_id(state)
    trace_detour(
        thread_id,
        "Step3_Room",
        "Step2_Date",
        "date_confirmed_missing",
        {"date_confirmed": event_entry.get("date_confirmed")},
    )
    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=2,
        date_confirmed=False,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 2, "room_requires_confirmed_date")
    state.current_step = 2
    state.caller_step = 3
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "date_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_detour_date", payload=payload, halt=False)


def _detour_for_capacity(state: WorkflowState, event_entry: dict) -> GroupResult:
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


def _skip_room_evaluation(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Skip Step 3 and return to the caller when caching allows."""

    caller = event_entry.get("caller_step")
    if caller is not None:
        append_audit_entry(event_entry, 3, caller, "room_eval_cache_hit")
        update_event_metadata(event_entry, current_step=caller, caller_step=None)
        state.current_step = caller
        state.caller_step = None
    else:
        state.current_step = event_entry.get("current_step")
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


def _handle_capacity_exceeded(
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
    from backend.workflows.common.prompts import verbalize_draft_body

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
    print(f"[Step3][CAPACITY_EXCEEDED] Generated response for {participants} guests (max: {max_capacity})")

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


def _preferred_room(event_entry: dict, user_requested_room: Optional[str]) -> Optional[str]:
    """[Trigger] Determine the preferred room priority."""

    if user_requested_room:
        return user_requested_room
    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room")
    if preferred_room:
        return preferred_room
    return event_entry.get("locked_room_id")


# R4: _flatten_statuses moved to evaluation.py


def _increment_room_attempt(event_entry: dict) -> int:
    try:
        current = int(event_entry.get("room_proposal_attempts") or 0)
    except (TypeError, ValueError):
        current = 0
    updated = current + 1
    event_entry["room_proposal_attempts"] = updated
    update_event_metadata(event_entry, room_proposal_attempts=updated)
    return updated


def _apply_hil_decision(state: WorkflowState, event_entry: Dict[str, Any], decision: str) -> GroupResult:
    """Handle HIL approval or rejection for the latest room evaluation."""

    thread_id = _thread_id(state)
    pending = event_entry.get("room_pending_decision")
    if not pending:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_room_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_hil_missing", payload=payload, halt=True)

    if decision != "approve":
        # Reset pending decision and keep awaiting further actions.
        event_entry.pop("room_pending_decision", None)
        draft = {
            "body": "Approval rejected — please provide updated guidance on the room.",
            "step": 3,
            "topic": "room_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=3, thread_state="Waiting on HIL")
        state.set_thread_state("Waiting on HIL")
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
        return GroupResult(action="room_hil_rejected", payload=payload, halt=True)

    selected_room = pending.get("selected_room")
    requirements_hash = event_entry.get("requirements_hash") or pending.get("requirements_hash")

    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))
    next_thread_state = "Waiting on HIL" if manager_requested else "Awaiting Client"

    update_event_metadata(
        event_entry,
        locked_room_id=selected_room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state=next_thread_state,
        status="Option",  # Room selected → calendar blocked as Option
    )
    _reset_room_attempts(event_entry)
    trace_gate(
        thread_id,
        "Step3_Room",
        "room_selected",
        True,
        {"locked_room_id": selected_room, "status": "Option"},
    )
    trace_gate(
        thread_id,
        "Step3_Room",
        "requirements_match",
        bool(requirements_hash),
        {"requirements_hash": requirements_hash, "room_eval_hash": requirements_hash},
    )
    trace_db_write(
        thread_id,
        "Step3_Room",
        "db.events.lock_room",
        {"locked_room_id": selected_room, "room_eval_hash": requirements_hash, "status": "Option"},
    )
    append_audit_entry(event_entry, 3, 4, "room_hil_approved")
    event_entry.pop("room_pending_decision", None)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state(next_thread_state)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "selected_room": selected_room,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_hil_approved", payload=payload, halt=False)


def _needs_better_room_alternatives(
    user_info: Dict[str, Any],
    status_map: Dict[str, str],
    event_entry: Dict[str, Any],
) -> bool:
    if (user_info or {}).get("room_feedback") != "not_good_enough":
        return False

    requirements = event_entry.get("requirements") or {}
    baseline_room = event_entry.get("locked_room_id") or requirements.get("preferred_room")
    baseline_rank = ROOM_SIZE_ORDER.get(str(baseline_room), 0)
    if baseline_rank == 0:
        return True

    larger_available = False
    for room_name, status in status_map.items():
        if ROOM_SIZE_ORDER.get(room_name, 0) > baseline_rank and status == ROOM_OUTCOME_AVAILABLE:
            larger_available = True
            break

    if not larger_available:
        return True

    participants = (requirements.get("number_of_participants") or 0)
    participants_val: Optional[int]
    try:
        participants_val = int(participants)
    except (TypeError, ValueError):
        participants_val = None

    capacity_map = {
        1: 36,
        2: 54,
        3: 96,
        4: 140,
    }
    if participants_val is not None:
        baseline_capacity = capacity_map.get(baseline_rank)
        if baseline_capacity and participants_val > baseline_capacity:
            return True

    return False


def _has_explicit_preferences(preferences: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(preferences, dict):
        return False
    wish_products = preferences.get("wish_products")
    if isinstance(wish_products, (list, tuple)):
        for item in wish_products:
            if isinstance(item, str) and item.strip():
                return True
    keywords = preferences.get("keywords")
    if isinstance(keywords, (list, tuple)):
        for item in keywords:
            if isinstance(item, str) and item.strip():
                return True
    return False


def _compose_preselection_header(
    status: str,
    room_name: Optional[str],
    chosen_date: str,
    participants: Optional[int],
    skip_capacity_prompt: bool,
) -> str:
    """Compose the lead sentence for the Step-3 draft before room selection."""

    date_label = _format_display_date(chosen_date)
    if status == ROOM_OUTCOME_AVAILABLE and room_name:
        if participants and not skip_capacity_prompt:
            return f"Good news — {room_name} is available on {date_label} and fits {participants} guests."
        return f"Good news — {room_name} is available on {date_label}."
    if status == ROOM_OUTCOME_OPTION and room_name:
        if participants and not skip_capacity_prompt:
            return f"Heads up — {room_name} is currently on option for {date_label}. It fits {participants} guests."
        return f"Heads up — {room_name} is currently on option for {date_label}."
    if participants and not skip_capacity_prompt:
        return f"I checked availability for {date_label} and captured the latest room status for {participants} guests."
    return f"I checked availability for {date_label} and captured the latest room status."


def _extract_participants(requirements: Dict[str, Any]) -> Optional[int]:
    raw = requirements.get("number_of_participants")
    if raw in (None, "", "Not specified", "none"):
        raw = requirements.get("participants")
    if raw in (None, "", "Not specified", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _room_requirements_payload(entry: RankedRoom) -> Dict[str, List[str]]:
    return {
        "matched": list(entry.matched),
        "closest": list(entry.closest),  # Moderate matches with context
        "missing": list(entry.missing),
    }


def _derive_hint(entry: Optional[RankedRoom], preferences: Optional[Dict[str, Any]], explicit: bool) -> str:
    if not entry:
        return "No room selected"
    matched = [item for item in entry.matched if item]
    if matched:
        return ", ".join(matched[:3])
    # Show closest matches (partial/similar products) if no exact matches
    closest = [item for item in entry.closest if item]
    if closest:
        # Extract just the product name from "Classic Apéro (closest to dinner)" format
        clean_closest = [item.split(" (closest")[0] for item in closest]
        return ", ".join(clean_closest[:3])
    if explicit:
        missing = [item for item in entry.missing if item]
        if missing:
            return f"Missing: {', '.join(missing[:3])}"
        base_hint = (entry.hint or "").strip()
        if base_hint and base_hint.lower() != "products available":
            return base_hint[0].upper() + base_hint[1:]
        return "No preference match"
    base_hint = (entry.hint or "").strip()
    if base_hint and base_hint.lower() != "products available":
        return base_hint[0].upper() + base_hint[1:]
    return "Available"


def _verbalizer_rooms_payload(
    ranked: List[RankedRoom],
    profiles: Dict[str, Dict[str, Any]],
    available_dates_map: Dict[str, List[str]],
    *,
    needs_products: Sequence[str],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    rooms_catalog = load_rooms_config() or []
    capacity_map = {}
    for item in rooms_catalog:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        capacity = (
            item.get("capacity_max")
            or item.get("capacity")
            or item.get("max_capacity")
            or item.get("capacity_maximum")
        )
        try:
            capacity_map[name] = int(capacity)
        except (TypeError, ValueError):
            capacity_map[name] = capacity
    payload: List[Dict[str, Any]] = []
    for entry in ranked[:limit]:
        profile = profiles.get(entry.room, {})
        badges_map = profile.get("requirements_badges") or {}
        coffee_badge = profile.get("coffee_badge", "—")
        capacity_badge = profile.get("capacity_badge", "—")
        normalized_products = {str(token).strip().lower() for token in needs_products}
        if "coffee" not in normalized_products and "tea" not in normalized_products and "drinks" not in normalized_products:
            coffee_badge = None
        alt_dates = [
            format_iso_date_to_ddmmyyyy(value) or value
            for value in available_dates_map.get(entry.room, [])
        ]
        hint_label = _derive_hint(entry, None, bool(entry.matched or entry.missing))
        payload.append(
            {
                "id": entry.room,
                "name": entry.room,
                "capacity": capacity_map.get(entry.room),
                "badges": {
                    "coffee": coffee_badge,
                    "capacity": capacity_badge,
                    "u-shape": badges_map.get("u-shape") if "u-shape" in normalized_products else badges_map.get("u-shape"),
                    "projector": badges_map.get("projector") if "projector" in normalized_products else badges_map.get("projector"),
                },
                "requirements": {
                    "matched": list(entry.matched),
                    "closest": list(entry.closest),  # Partial matches with context
                    "missing": list(entry.missing),
                },
                "hint": hint_label,
                "alternatives": alt_dates,
            }
        )
    return payload


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


def _build_ranked_rows(
    chosen_date: str,
    ranked: List[RankedRoom],
    preferences: Optional[Dict[str, Any]],
    available_dates_map: Dict[str, List[str]],
    room_profiles: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    explicit_prefs = _has_explicit_preferences(preferences)

    for entry in ranked:
        hint_label = _derive_hint(entry, preferences, explicit_prefs)
        available_dates = available_dates_map.get(entry.room, [])
        requirements_info = _room_requirements_payload(entry) if explicit_prefs else {"matched": [], "missing": []}
        profile = room_profiles.get(entry.room, {})
        badges = profile.get("requirements_badges") or {}
        row = {
            "date": chosen_date,
            "room": entry.room,
            "status": entry.status,
            "hint": hint_label,
            "requirements_score": round(profile.get("requirements_score", entry.score), 2),
            "available_dates": available_dates,
            "requirements": requirements_info,
            "coffee_match": profile.get("coffee_badge"),
            "u_shape_match": badges.get("u-shape"),
            "projector_match": badges.get("projector"),
        }
        rows.append(row)
        if entry.status in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
            actions.append(
                {
                    "type": "select_room",
                    "label": f"Proceed with {entry.room} ({hint_label})",
                    "room": entry.room,
                    "date": chosen_date,
                    "status": entry.status,
                    "hint": hint_label,
                    "available_dates": available_dates,
                    "requirements": dict(requirements_info),
                }
            )

    return rows, actions


def _dates_in_month_weekday_wrapper(
    month_hint: Optional[Any],
    weekday_hint: Optional[Any],
    *,
    limit: int,
) -> List[str]:
    from backend.workflows.io import dates as dates_module

    return dates_module.dates_in_month_weekday(month_hint, weekday_hint, limit=limit)


def _closest_alternatives_wrapper(
    anchor_iso: str,
    weekday_hint: Optional[Any],
    month_hint: Optional[Any],
    *,
    limit: int,
) -> List[str]:
    from backend.workflows.io import dates as dates_module

    return dates_module.closest_alternatives(anchor_iso, weekday_hint, month_hint, limit=limit)


def _available_dates_for_rooms(
    db: Dict[str, Any],
    ranked: List[RankedRoom],
    candidate_iso_dates: List[str],
    participants: Optional[int],
) -> Dict[str, List[str]]:
    availability: Dict[str, List[str]] = {}
    for entry in ranked:
        dates: List[str] = []
        for iso_date in candidate_iso_dates:
            display_date = format_iso_date_to_ddmmyyyy(iso_date)
            if not display_date:
                continue
            status = room_status_on_date(db, display_date, entry.room)
            if status.lower() in {"available", "option"}:
                dates.append(iso_date)
        availability[entry.room] = dates
    return availability


def _format_requirements_line(requirements: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(requirements, dict):
        return None
    matched = [str(item).strip() for item in requirements.get("matched", []) if str(item).strip()]
    missing = [str(item).strip() for item in requirements.get("missing", []) if str(item).strip()]
    tokens: List[str] = []
    tokens.extend(f"✔ {label}" for label in matched)
    tokens.extend(f"○ {label}" for label in missing)
    if not tokens:
        return None
    max_tokens = 4
    display = "; ".join(tokens[:max_tokens])
    overflow = len(tokens) - max_tokens
    if overflow > 0:
        display += f" (+{overflow} more)"
    return f"- Requirements: {display}"


def _format_room_sections(
    actions: List[Dict[str, Any]],
    mode: str,
    vague_month: Optional[Any],
    vague_weekday: Optional[Any],
) -> List[str]:
    lines: List[str] = []
    if not actions:
        return lines

    descriptor = _format_range_descriptor(vague_month, vague_weekday)
    max_display = 5 if mode == "range" else 3

    for action in actions:
        room = action.get("room")
        status = action.get("status") or "Available"
        hint = action.get("hint")
        iso_dates = action.get("available_dates") or []
        if not room:
            continue
        lines.append(f"### {room} — {status}")
        if hint:
            lines.append(f"- _{hint}_")
        requirements_line = _format_requirements_line(action.get("requirements"))
        if requirements_line:
            lines.append(requirements_line)
        if iso_dates:
            display_text, remainder = _format_dates_list(iso_dates, max_display)
            if mode == "range":
                prefix = "Available dates"
                if descriptor:
                    prefix += f" {descriptor}"
            else:
                prefix = "Alternative dates (closest)"
            line = f"- **{prefix}:** {display_text}"
            if remainder:
                line += f" (+{remainder} more)"
            lines.append(line)
        lines.append("")

    return lines


def _format_range_descriptor(month_hint: Optional[Any], weekday_hint: Optional[Any]) -> str:
    parts: List[str] = []
    if month_hint:
        parts.append(str(month_hint).strip().capitalize())
    if weekday_hint:
        parts.append(str(weekday_hint).strip().capitalize())
    if not parts:
        return ""
    if len(parts) == 2:
        return f"in {parts[0]} ({parts[1]})"
    return f"in {parts[0]}"


def _format_dates_list(dates: List[str], max_count: int) -> Tuple[str, int]:
    shown = dates[:max_count]
    display = ", ".join(_format_short_date(iso) for iso in shown)
    remainder = max(0, len(dates) - max_count)
    return display, remainder


def _format_short_date(iso_date: str) -> str:
    """Format ISO date to DD.MM.YYYY for display."""
    try:
        parsed = datetime.strptime(iso_date, "%Y-%m-%d")
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


def _to_iso(display_date: Optional[str]) -> Optional[str]:
    if not display_date:
        return None
    parsed = parse_ddmmyyyy(display_date)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d")


def _select_room(ranked: List[RankedRoom]) -> Optional[RankedRoom]:
    """Return the top-ranked room that's available or on option.

    The ranking already incorporates status weight (Available=60, Option=35)
    plus preferred_room bonus (30 points). We trust the ranking order and
    return the first available/option room.
    """
    for entry in ranked:
        if entry.status in (ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION):
            return entry
    return ranked[0] if ranked else None


# R3: Functions moved to selection.py:
# - handle_select_room_action
# - _thread_id
# - _reset_room_attempts
# - _format_display_date



def _collect_alternative_dates(
    state: WorkflowState,
    preferred_room: Optional[str],
    chosen_date: Optional[str],
    *,
    count: int = 7,
) -> List[str]:
    from backend.workflows.common.catalog import list_free_dates

    try:
        alt = list_free_dates(count=count, db=state.db, preferred_room=preferred_room)
    except Exception:  # pragma: no cover - safety net for missing fixtures
        alt = []

    chosen_iso = _to_iso(chosen_date)
    iso_dates: List[str] = []
    for value in alt:
        label = str(value).strip()
        if not label:
            continue
        candidate_iso = _to_iso(label) or label if len(label) == 10 and label.count("-") == 2 else None
        if not candidate_iso:
            continue
        if chosen_iso and candidate_iso == chosen_iso:
            continue
        if candidate_iso not in iso_dates:
            iso_dates.append(candidate_iso)
    return iso_dates


def _merge_alternative_dates(primary: List[str], fallback: List[str]) -> List[str]:
    combined: List[str] = []
    for source in (primary, fallback):
        for value in source:
            if value and value not in combined:
                combined.append(value)
    return combined


def _dedupe_dates(dates: List[str], chosen_date: Optional[str]) -> List[str]:
    result: List[str] = []
    for date in dates:
        if not date:
            continue
        if chosen_date and date == chosen_date:
            continue
        if date not in result:
            result.append(date)
    return result


def _format_alternative_dates_section(dates: List[str], more_available: bool) -> str:
    if not dates and not more_available:
        return "Alternative Dates:\n- Let me know if you'd like me to explore additional dates."
    if not dates:
        return "Alternative Dates:\n- More options are available on request."

    label = "Alternative Dates"
    if len(dates) > 1:
        label = f"Alternative Dates (top {len(dates)})"

    lines = [f"{label}:"]
    for value in dates:
        display = _format_short_date(value)
        lines.append(f"- {display}")
    if more_available:
        lines.append("More options are available on request.")
    return "\n".join(lines)


def _strip_system_subject(subject: str) -> str:
    """Strip system-generated metadata from subject lines.

    The API adds "Client follow-up (YYYY-MM-DD HH:MM)" to follow-up messages.
    This timestamp should NOT be used for change detection as it represents
    when the message was sent, not the requested event date.
    """
    import re
    # Pattern: "Client follow-up (YYYY-MM-DD HH:MM)" or similar system-generated prefixes
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state.

    BUG FIX: Strips system-generated timestamps from subject before combining.
    These timestamps were incorrectly triggering DATE change detection.
    """
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    # Strip system-generated timestamps from subject
    clean_subject = _strip_system_subject(subject)
    if clean_subject and body:
        return f"{clean_subject}\n{body}"
    return clean_subject or body


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
