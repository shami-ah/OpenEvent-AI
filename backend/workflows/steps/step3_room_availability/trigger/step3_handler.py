from __future__ import annotations

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
from backend.workflows.common.general_qna import append_general_qna_to_primary, _fallback_structured_body
from backend.workflows.change_propagation import (
    ChangeType,
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata, update_event_room
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
from backend.rooms import rank as rank_rooms_profiles

from ..condition.decide import room_status_on_date
from ..llm.analysis import summarize_room_statuses

__workflow_role__ = "trigger"


ROOM_OUTCOME_UNAVAILABLE = "Unavailable"
ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"

ROOM_SIZE_ORDER = {
    "Room A": 1,
    "Room B": 2,
    "Room C": 3,
    "Punkt.Null": 4,
}

ROOM_PROPOSAL_HIL_THRESHOLD = 3  # TODO(openevent-team): make this configurable per venue
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
                update_event_metadata(
                    event_entry,
                    date_confirmed=False if decision.next_step == 2 else None,
                    room_eval_hash=None,
                    locked_room_id=None,
                )

            append_audit_entry(event_entry, 3, decision.next_step, f"{change_type.value}_change_detected")

            # Skip Q&A: return detour signal
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
    user_requested_room = state.user_info.get("room") if state.user_info.get("_room_choice_detected") else None
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

    # Don't take Q&A path for initial inquiries (first entry to Step 3)
    # The Q&A path is for follow-up questions after rooms have been presented
    # Check if this is first entry by looking for room_pending_decision or audit_log entries
    room_pending = event_entry.get("room_pending_decision")
    audit_log = event_entry.get("audit_log") or []
    has_step3_history = room_pending is not None or any(
        entry.get("to_step") == 3 or entry.get("from_step") == 3
        for entry in audit_log
    )
    if general_qna_applicable and not has_step3_history:
        # First entry to Step 3 with an inquiry - skip Q&A, show room options directly
        general_qna_applicable = False

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
    order_map = {entry["room"]: idx for idx, entry in enumerate(profile_entries)}
    ranked_rooms.sort(key=lambda entry: order_map.get(entry.room, len(order_map)))
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
    headers = assistant_draft.get("headers") or (
        [f"Room options for {display_chosen_date}"] if display_chosen_date else ["Room options"]
    )
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
    intro_lines: List[str] = []
    if user_requested_room and user_requested_room != selected_room:
        intro_lines.append(
            f"Sorry, {user_requested_room} isn't available on {display_chosen_date or 'your date'}. "
            f"I've found some great alternatives that fit your {participants or 'guest'} count and requirements."
        )
    elif selected_room and outcome in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
        descriptor = "available" if outcome == ROOM_OUTCOME_AVAILABLE else "on option"
        intro_lines.append(
            f"Great news! {selected_room} is {descriptor} on {display_chosen_date or 'your requested date'} "
            f"and is a perfect fit for your {participants or ''} guests."
        )
        intro_lines.append("I've put together the room options for you to review.")
    else:
        intro_lines.append(
            f"Unfortunately, the rooms aren't available on {display_chosen_date or 'your requested date'} as-is."
        )
        intro_lines.append("I'm showing some alternatives with nearby dates that might work.")

    intro_lines.append("Just let me know which room you'd like and I'll prepare the offer.")

    # body_markdown = ONLY conversational prose (structured data is in table_blocks)
    body_markdown = " ".join(intro_lines)

    # Create snapshot with full room data for persistent link
    # Include client preferences so info page can show feature matching
    client_prefs = event_entry.get("preferences") or {}
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
    if body_markdown:
        body_markdown = "\n".join([room_link, "", body_markdown])
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
    from backend.workflows.common.prompts import verbalize_draft_body
    body_markdown = verbalize_draft_body(
        body_markdown,
        step=3,
        topic=outcome_topic,
        event_date=display_chosen_date,
        participants_count=participants,
        rooms=verbalizer_rooms,
        room_name=selected_room,
        room_status=outcome,
    )

    # Capture menu options separately (NOT in body_markdown - shown in info cards)
    qa_lines = _general_qna_lines(state)
    menu_content = None
    if qa_lines:
        menu_content = "\n".join(qa_lines)
        headers = ["Availability overview"] + [header for header in headers if header]
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


def evaluate_room_statuses(db: Dict[str, Any], target_date: str | None) -> List[Dict[str, str]]:
    """[Trigger] Evaluate each configured room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses


def render_rooms_response(
    event_id: str,
    date_iso: str,
    pax: int,
    rooms: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Render a lightweight room summary for deterministic flow tests."""

    display_date = format_iso_date_to_ddmmyyyy(date_iso) or date_iso
    headers = [f"Room options for {display_date}"]
    lines: List[str] = []
    for room in rooms:
        matched = ", ".join(room.get("matched") or []) or "None"
        missing_items = room.get("missing") or []
        missing = ", ".join(missing_items) if missing_items else "None"
        capacity = room.get("capacity") or "—"
        name = room.get("name") or room.get("id") or "Room"
        lines.append(
            f"{name} — capacity {capacity} — matched: {matched} — missing: {missing}"
        )
    body = "\n".join(lines) if lines else "No rooms available."
    assistant_draft = {"headers": headers, "body": body}
    return {
        "action": "send_reply",
        "event_id": event_id,
        "rooms": rooms,
        "res": {
            "assistant_draft": assistant_draft,
            "assistant_draft_text": body,
        },
    }


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
    """[Trigger] Redirect to Step 1 when attendee count is missing."""

    thread_id = _thread_id(state)
    trace_detour(
        thread_id,
        "Step3_Room",
        "Step1_Intake",
        "capacity_missing",
        {},
    )
    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=1,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 1, "room_requires_capacity")
    state.current_step = 1
    state.caller_step = 3
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
    return GroupResult(action="room_detour_capacity", payload=payload, halt=False)


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


def _preferred_room(event_entry: dict, user_requested_room: Optional[str]) -> Optional[str]:
    """[Trigger] Determine the preferred room priority."""

    if user_requested_room:
        return user_requested_room
    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room")
    if preferred_room:
        return preferred_room
    return event_entry.get("locked_room_id")


def _flatten_statuses(statuses: List[Dict[str, str]]) -> Dict[str, str]:
    """[Trigger] Convert list of {room: status} mappings into a single dict."""

    result: Dict[str, str] = {}
    for entry in statuses:
        result.update(entry)
    return result


def _increment_room_attempt(event_entry: dict) -> int:
    try:
        current = int(event_entry.get("room_proposal_attempts") or 0)
    except (TypeError, ValueError):
        current = 0
    updated = current + 1
    event_entry["room_proposal_attempts"] = updated
    update_event_metadata(event_entry, room_proposal_attempts=updated)
    return updated


def _reset_room_attempts(event_entry: dict) -> None:
    if not event_entry.get("room_proposal_attempts"):
        return
    event_entry["room_proposal_attempts"] = 0
    update_event_metadata(event_entry, room_proposal_attempts=0)


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


def _format_display_date(chosen_date: Optional[str]) -> str:
    display = format_iso_date_to_ddmmyyyy(chosen_date)
    if display:
        return display
    return chosen_date or "your requested date"


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
    for entry in ranked:
        if entry.status == ROOM_OUTCOME_AVAILABLE and entry.capacity_ok:
            return entry
    for entry in ranked:
        if entry.status == ROOM_OUTCOME_AVAILABLE:
            return entry
    for entry in ranked:
        if entry.status == ROOM_OUTCOME_OPTION and entry.capacity_ok:
            return entry
    for entry in ranked:
        if entry.status == ROOM_OUTCOME_OPTION:
            return entry
    return ranked[0] if ranked else None


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def handle_select_room_action(
    state: WorkflowState,
    *,
    room: str,
    status: str,
    date: Optional[str] = None,
) -> GroupResult:
    """[OpenEvent Action] Persist the client's room choice and prompt for products."""

    thread_id = _thread_id(state)
    event_entry = state.event_entry
    if not event_entry or not event_entry.get("event_id"):
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_select_missing", payload=payload, halt=True)

    event_id = event_entry["event_id"]

    # [SOFT CONFLICT CHECK] Detect if another client has an Option on this room/date
    chosen_date = date or event_entry.get("chosen_date") or ""
    conflict_type, conflict_info = detect_conflict_type(
        db=state.db,
        event_id=event_id,
        room_id=room,
        event_date=chosen_date,
        action="select",  # Client is selecting (becoming Option)
    )

    # Handle soft conflict: create HIL notification but don't block the client
    soft_conflict_note = ""
    if conflict_type == ConflictType.SOFT and conflict_info:
        # Create HIL notification task for manager (NOT blocking)
        tasks = state.db.setdefault("tasks", {})
        from datetime import datetime as dt
        task_id = f"soft_conflict_{event_id}_{dt.now().strftime('%Y%m%d%H%M%S')}"
        tasks[task_id] = {
            "type": "soft_room_conflict_notification",
            "status": "pending",
            "created_at": dt.now().isoformat(),
            "event_id": event_id,
            "data": {
                "room_id": room,
                "event_date": chosen_date,
                "client_1": {
                    "event_id": conflict_info.get("conflicting_event_id"),
                    "email": conflict_info.get("conflicting_client_email"),
                    "name": conflict_info.get("conflicting_client_name"),
                    "status": conflict_info.get("status"),
                },
                "client_2": {
                    "event_id": event_id,
                    "email": event_entry.get("client_email"),
                    "name": event_entry.get("client_name"),
                    "status": "Option (new)",
                },
            },
            "description": (
                f"Soft Conflict: {room} on {chosen_date}\n\n"
                f"Client 1: {conflict_info.get('conflicting_client_email')} (already {conflict_info.get('status')})\n"
                f"Client 2: {event_entry.get('client_email')} (newly selecting)\n\n"
                f"Both clients now have Option status on this room. "
                f"Monitor and resolve before either tries to confirm."
            ),
        }
        # Mark event with soft conflict flag (for later hard conflict detection)
        event_entry["has_conflict"] = True
        event_entry["conflict_with"] = conflict_info.get("conflicting_event_id")
        event_entry["conflict_type"] = "soft"
        event_entry["conflict_task_id"] = task_id
        # NOTE: Neither client is notified - manager just gets visibility
        state.extras["persist"] = True

    update_event_room(
        state.db,
        event_id,
        selected_room=room,
        status=status,
    )

    # Get requirements_hash to lock the room with current requirements snapshot
    requirements_hash = event_entry.get("requirements_hash")

    update_event_metadata(
        event_entry,
        locked_room_id=room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="Awaiting Client",
        status="Option",  # Room selected → calendar blocked as Option
    )
    _reset_room_attempts(event_entry)

    event_entry["selected_room"] = room
    event_entry["selected_room_status"] = status
    flags = event_entry.setdefault("flags", {})
    flags["room_selected"] = True
    pending = event_entry.setdefault("room_pending_decision", {})
    pending["selected_room"] = room
    pending["selected_status"] = status

    if not hasattr(state, "flags") or not isinstance(getattr(state, "flags"), dict):
        state.flags = {}
    state.flags["room_selected"] = True

    preferences = event_entry.get("preferences") or state.user_info.get("preferences") or {}
    wish_products: List[str] = []
    if isinstance(preferences, dict):
        raw_wishes = preferences.get("wish_products") or []
        if isinstance(raw_wishes, (list, tuple)):
            wish_products = [str(item).strip() for item in raw_wishes if str(item).strip()]

    top_summary = (
        f"Top picks: {', '.join(wish_products[:3])}."
        if wish_products
        else "Products available for this room."
    )

    chosen_date = date or event_entry.get("chosen_date") or ""
    display_date = _format_display_date(chosen_date)

    body_lines = [
        f"Great — {room} on {display_date} is reserved as an option.",
        "Would you like to (A) review products for this room, or (B) confirm products now?",
        top_summary,
    ]
    body_text = "\n\n".join(body_lines)
    body_with_footer = append_footer(
        body_text,
        step=4,
        next_step="Pick products",
        thread_state="Awaiting Client",
    )

    state.draft_messages.clear()
    follow_up = {
        "body": body_with_footer,
        "step": 4,
        "next_step": "Pick products",
        "thread_state": "Awaiting Client",
        "topic": "room_selected_follow_up",
        "actions": [
            {
                "type": "explore_products",
                "label": f"Explore products for {room}",
                "room": room,
                "date": chosen_date or display_date,
            },
            {
                "type": "confirm_products",
                "label": f"Confirm products for {room}",
                "room": room,
                "date": chosen_date or display_date,
            },
        ],
        "requires_approval": False,
    }
    state.add_draft_message(follow_up)

    state.current_step = 4
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    trace_db_write(
        thread_id,
        "Step3_Room",
        "db.events.update_room",
        {"selected_room": room, "status": status},
    )

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "selected_room": room,
            "selected_status": status,
            "room_hint": top_summary if wish_products else "Products available",
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_id,
        "intent": state.intent.value if state.intent else None,
        "selected_room": room,
        "selected_status": status,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_selected", payload=payload, halt=False)


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


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state."""
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 3 using the same pattern as Step 2."""
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
            step=3,
            next_step=3,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 3,
            "next_step": 3,
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
            current_step=3,
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
        "step": 3,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 3 Room Availability · Next: 3 Room Availability · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 3,
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
        current_step=3,
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
        # Restore drafts to their previous count to avoid leaking the standalone Q&A draft.
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
