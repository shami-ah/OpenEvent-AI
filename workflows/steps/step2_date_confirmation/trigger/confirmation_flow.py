"""
D-FLOW Refactoring: Confirmation flow functions with state management.

Extracted from step2_handler.py to reduce file size and improve modularity.
These functions handle the confirmation flow including window resolution,
partial confirmations, prompting, finalization, and HIL decisions.
"""

from __future__ import annotations
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional
import re
import logging

from domain import TaskStatus, TaskType
from debug.hooks import trace_marker
from workflows.io.config_store import get_timezone
from workflows.common.datetime_parse import (
    build_window_iso,
    parse_time_range,
    to_iso_date,
)
from workflows.common.prompts import format_sections_with_headers
from workflows.common.capture import promote_fields
from workflows.common.requirements import requirements_hash
from workflows.common.gatekeeper import refresh_gatekeeper
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import (
    append_audit_entry,
    link_event_to_client,
    tag_message,
    update_event_metadata,
)
from workflow.state import WorkflowStep, default_subflow, write_stage
from utils.calendar_events import update_calendar_event_status

from .types import ConfirmationWindow
from .confirmation import (
    determine_date,
    find_existing_time_window,
    record_confirmation_log,
    set_pending_time_state,
)
from .step2_utils import (
    _normalize_time_value,
    _to_time,
    _format_window,
    _window_hash,
)
from .window_helpers import (
    _reference_date_from_state,
    _extract_participants_from_state,
)
from .proposal_tracking import reset_date_attempts as _reset_date_attempts

logger = logging.getLogger(__name__)


def _thread_id(state: WorkflowState) -> str:
    """Get thread ID from state for tracing."""
    from .step2_state import thread_id as _thread_id_impl
    return _thread_id_impl(state)


def _emit_step2_snapshot(
    state: WorkflowState,
    event_entry: dict,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a step 2 snapshot for debugging."""
    from .step2_state import emit_step2_snapshot as _emit_step2_snapshot_impl
    _emit_step2_snapshot_impl(state, event_entry, extra=extra)


def resolve_confirmation_window(
    state: WorkflowState,
    event_entry: dict,
) -> Optional[ConfirmationWindow]:
    """Resolve the requested window from the latest client message.

    Parses the user's message to extract date and time information,
    then constructs a ConfirmationWindow with all available details.

    Returns:
        ConfirmationWindow if a valid date could be determined, None otherwise.
    """

    user_info = state.user_info or {}
    body_text = state.message.body or ""
    subject_text = state.message.subject or ""

    reference_day = _reference_date_from_state(state)
    display_date, iso_date = determine_date(
        user_info,
        body_text,
        subject_text,
        event_entry,
        reference_day,
    )
    if not display_date or not iso_date:
        return None

    start_time = _normalize_time_value(user_info.get("start_time"))
    end_time = _normalize_time_value(user_info.get("end_time"))

    inherited_times = False
    start_obj: Optional[time] = None
    end_obj: Optional[time] = None

    if start_time:
        try:
            start_obj = _to_time(start_time)
        except ValueError:
            start_time = None
            start_obj = None
    if end_time:
        try:
            end_obj = _to_time(end_time)
        except ValueError:
            end_time = None
            end_obj = None

    if start_obj and end_obj and start_obj >= end_obj:
        end_time = None
        end_obj = None

    if not (start_time and end_time):
        parsed_start, parsed_end, matched = parse_time_range(body_text)
        if parsed_start and parsed_end:
            start_obj = parsed_start
            end_obj = parsed_end
            start_time = f"{parsed_start.hour:02d}:{parsed_start.minute:02d}"
            end_time = f"{parsed_end.hour:02d}:{parsed_end.minute:02d}"
        elif matched and not start_time:
            start_time = None

    if start_time and not end_time and (body_text or subject_text):
        combined_text = " ".join(value for value in (subject_text, body_text) if value)
        time_tokens: List[str] = []
        for match in re.findall(r"\b(\d{1,2}:\d{2})\b", combined_text):
            normalized_token = _normalize_time_value(match)
            if normalized_token and normalized_token not in time_tokens:
                time_tokens.append(normalized_token)
        if time_tokens:
            if start_time and not start_obj:
                try:
                    start_obj = _to_time(start_time)
                except ValueError:
                    start_obj = None
            chosen_token: Optional[str] = None
            chosen_obj: Optional[time] = None
            for token in time_tokens:
                if start_time and token == start_time:
                    continue
                try:
                    candidate_obj = _to_time(token)
                except ValueError:
                    continue
                if start_obj and candidate_obj <= start_obj:
                    continue
                chosen_token = token
                chosen_obj = candidate_obj
                break
            if chosen_obj is None:
                for token in time_tokens:
                    if start_time and token == start_time:
                        continue
                    try:
                        candidate_obj = _to_time(token)
                    except ValueError:
                        continue
                    chosen_token = token
                    chosen_obj = candidate_obj
                    break
            if chosen_token and chosen_obj:
                end_time = chosen_token
                end_obj = chosen_obj

    if not (start_time and end_time):
        fallback = find_existing_time_window(event_entry, iso_date)
        if fallback:
            start_time, end_time = fallback
            inherited_times = True
            try:
                start_obj = _to_time(start_time)
            except (TypeError, ValueError):
                start_obj = None
            try:
                end_obj = _to_time(end_time)
            except (TypeError, ValueError):
                end_obj = None

    if start_obj and end_obj and start_obj >= end_obj:
        end_time = None
        end_obj = None

    if start_time and not start_obj:
        try:
            start_obj = _to_time(start_time)
        except ValueError:
            start_obj = None
            start_time = None
    if end_time and not end_obj:
        try:
            end_obj = _to_time(end_time)
        except ValueError:
            end_obj = None
            end_time = None

    # [FIX] Infer 4-hour default duration when only start time is provided
    # This prevents the loop of repeatedly asking for time when user provides single time
    if start_obj and not end_obj:
        # Check if we're already in a pending_time_request loop for this date
        pending = event_entry.get("pending_time_request") or {}
        if pending.get("iso_date") == iso_date:
            # Already asked for time once - infer 4-hour default duration
            default_duration_hours = 4
            start_dt = datetime.combine(datetime.today(), start_obj)
            end_dt = start_dt + timedelta(hours=default_duration_hours)
            end_obj = end_dt.time()
            end_time = f"{end_obj.hour:02d}:{end_obj.minute:02d}"
            logger.debug("[Step2][TIME_INFER] Single time %s detected, inferring end_time=%s (4-hour default)",
                        start_time, end_time)

    if start_time:
        user_info["start_time"] = start_time
    elif "start_time" in user_info:
        user_info.pop("start_time", None)
    if end_time:
        user_info["end_time"] = end_time
    elif "end_time" in user_info:
        user_info.pop("end_time", None)

    partial = not (start_time and end_time)
    start_iso = end_iso = None
    if start_obj and end_obj:
        start_iso, end_iso = build_window_iso(iso_date, start_obj, end_obj)

    return ConfirmationWindow(
        display_date=display_date,
        iso_date=iso_date,
        start_time=start_time,
        end_time=end_time,
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=inherited_times,
        partial=partial,
        source_message_id=state.message.msg_id,
    )


def handle_partial_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
    with_greeting_fn,
) -> Optional[GroupResult]:
    """Persist the date and request a time clarification without stalling the flow.

    Args:
        state: Current workflow state
        event_entry: Event data dict
        window: Partial confirmation window (date confirmed, time needed)
        with_greeting_fn: Function to add greeting to body

    Returns:
        GroupResult for time clarification, or None if loop detected (use defaults).
    """

    # [FIX] Loop detection: If we've already asked for time on this date, use defaults
    pending = event_entry.get("pending_time_request") or {}
    if pending.get("iso_date") == window.iso_date:
        # Check for loop - if pending was set recently and we're still partial, break the loop
        time_request_count = pending.get("_request_count", 0) + 1
        if time_request_count >= 2:
            # Already asked twice - use default time window
            logger.debug("[Step2][LOOP_BREAK] Time request loop detected for %s, using default window",
                        window.display_date)
            window = ConfirmationWindow(
                display_date=window.display_date,
                iso_date=window.iso_date,
                start_time="14:00",
                end_time="18:00",
                start_iso=None,  # Will be computed downstream
                end_iso=None,
                inherited_times=False,
                partial=False,  # No longer partial!
                source_message_id=window.source_message_id,
            )
            # Clean up pending state
            event_entry.pop("pending_time_request", None)
            # Return successful confirmation instead of asking again
            state.user_info["event_date"] = window.display_date
            state.user_info["date"] = window.iso_date
            state.user_info["start_time"] = window.start_time
            state.user_info["end_time"] = window.end_time
            # [TIME VALIDATION] Validate default times against operating hours
            from workflows.common.time_validation import validate_event_times
            time_validation = validate_event_times(window.start_time, window.end_time)
            if not time_validation.is_valid:
                logger.info(
                    "[Step2][TIME_VALIDATION] Default times outside hours: %s",
                    time_validation.issue
                )
                state.extras["time_warning"] = time_validation.friendly_message
                state.extras["time_warning_issue"] = time_validation.issue
                # Persist to event_entry for traceability
                event_entry.setdefault("time_validation", {})
                event_entry["time_validation"]["issue"] = time_validation.issue
                event_entry["time_validation"]["warning"] = time_validation.friendly_message
            # Continue with full confirmation flow - return None to let caller proceed
            return None  # Signal to caller to use non-partial path

    _reset_date_attempts(event_entry)

    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    set_pending_time_state(event_entry, window)
    # Track request count for loop detection
    event_entry["pending_time_request"]["_request_count"] = pending.get("_request_count", 0) + 1

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date

    prompt = with_greeting_fn(
        state,
        f"Great, I've noted **{window.display_date}**. What time works best for you? For example, 14:00–18:00 or 18:00–22:00.",
    )
    state.add_draft_message({"body": prompt, "step": 2, "topic": "date_time_clarification"})

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
        current_step=2,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_time": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_time": True,
        "event_date": window.display_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    return GroupResult(action="date_time_clarification", payload=payload, halt=True)


def prompt_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
    with_greeting_fn,
) -> GroupResult:
    """Prompt the user to confirm a proposed date/time window.

    Args:
        state: Current workflow state
        event_entry: Event data dict
        window: Confirmation window to propose
        with_greeting_fn: Function to add greeting to body

    Returns:
        GroupResult for pending confirmation.
    """
    formatted_window = _format_window(window)
    prompt = with_greeting_fn(
        state,
        f"**{formatted_window}** works on our end! Should I check room availability for this time? Just say yes, or let me know if you'd prefer a different date or time.",
    )

    draft_message = {
        "body": prompt,
        "step": 2,
        "topic": "date_confirmation_pending",
        "proposed_date": window.display_date,
        "proposed_time": f"{window.start_time or ''}–{window.end_time or ''}".strip("–"),
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        current_step=2,
        thread_state="Awaiting Client Response",
        date_confirmed=False,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_confirmation": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_confirmation": True,
        "proposed_date": window.iso_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="date_confirmation_pending", payload=payload, halt=True)


def finalize_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Persist the requested window and trigger availability.

    This is the main confirmation finalization function that:
    1. Validates and normalizes the window
    2. Updates event state
    3. Proceeds to Step 3 (room availability)

    Args:
        state: Current workflow state
        event_entry: Event data dict
        window: Confirmed window

    Returns:
        GroupResult - either from Step 3 autorun or date_confirmed action.
    """

    _reset_date_attempts(event_entry)

    thread_id = _thread_id(state)
    if isinstance(window, str):
        try:
            parsed_date = datetime.strptime(window, "%Y-%m-%d")
            display_date = parsed_date.strftime("%d.%m.%Y")
            iso_date = window
        except ValueError:
            display_date = window
            iso_date = to_iso_date(window) or window
        fallback_window = event_entry.get("requested_window") or {}
        start_time = fallback_window.get("start_time")
        end_time = fallback_window.get("end_time")
        start_iso = fallback_window.get("start")
        end_iso = fallback_window.get("end")
        window = ConfirmationWindow(
            display_date=display_date,
            iso_date=iso_date,
            start_time=start_time,
            end_time=end_time,
            start_iso=start_iso,
            end_iso=end_iso,
            inherited_times=bool(start_time and end_time),
            partial=not (start_time and end_time),
            source_message_id=fallback_window.get("source_message_id"),
        )

    state.event_id = event_entry.get("event_id")
    clear_step2_hil_tasks(state, event_entry)
    tag_message(event_entry, window.source_message_id)
    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    event_entry["event_data"]["Start Time"] = window.start_time
    event_entry["event_data"]["End Time"] = window.end_time

    requirements = dict(event_entry.get("requirements") or {})
    requirements["event_duration"] = {"start": window.start_time, "end": window.end_time}
    new_req_hash = requirements_hash(requirements)

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date
    state.user_info["start_time"] = window.start_time
    state.user_info["end_time"] = window.end_time

    # [TIME VALIDATION] Validate finalized times against operating hours
    from workflows.common.time_validation import validate_event_times
    time_validation = validate_event_times(window.start_time, window.end_time)
    if not time_validation.is_valid:
        logger.info(
            "[Step2][TIME_VALIDATION] Finalized times outside hours: %s",
            time_validation.issue
        )
        state.extras["time_warning"] = time_validation.friendly_message
        state.extras["time_warning_issue"] = time_validation.issue

    previous_window = event_entry.get("requested_window") or {}
    new_hash = _window_hash(window.iso_date, window.start_iso, window.end_iso)
    reuse_previous = previous_window.get("hash") == new_hash

    requested_payload = {
        "display_date": window.display_date,
        "date_iso": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start": window.start_iso,
        "end": window.end_iso,
        "tz": get_timezone(),
        "hash": new_hash,
        "times_inherited": window.inherited_times,
        "source_message_id": window.source_message_id,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "cached": reuse_previous,
    }
    event_entry["requested_window"] = requested_payload
    event_entry.pop("pending_time_request", None)

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=True,
        requirements=requirements,
        requirements_hash=new_req_hash,
        thread_state="In Progress",
    )
    # Log date confirmation activity for manager visibility
    from activity.persistence import log_workflow_activity
    log_workflow_activity(event_entry, "date_confirmed", date=window.display_date)

    if event_entry.get("calendar_event_id"):
        try:
            update_calendar_event_status(event_entry.get("event_id", ""), event_entry.get("status", ""), "lead")
            from utils.calendar_events import create_calendar_event

            create_calendar_event(event_entry, "lead")
        except Exception as exc:  # pragma: no cover - best-effort calendar logging
            logger.warning("Failed to update calendar event: %s", exc)
    if not reuse_previous:
        # Invalidate room_eval_hash so Step 3 re-verifies room availability
        # on the new date. KEEP locked_room_id so Step 3 can fast-skip if
        # the same room is still available on the new date.
        update_event_metadata(
            event_entry,
            room_eval_hash=None,
            # NOTE: Do NOT clear locked_room_id here - Step 3 will verify
            # availability and clear it only if the room is no longer available
        )

    # Always proceed to Step 3 (Room Availability) after confirming a date.
    #
    # If a previous step (e.g. Step 5) triggered a detour and the window is
    # unchanged, Step 3's own hash + caller_step guards will immediately skip
    # reevaluation and route control back to the caller. This keeps the
    # detour semantics intact while avoiding stale caller_step values causing
    # Step 2 to jump directly to unrelated steps.
    next_step = 3

    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "confirmed_date": window.display_date,
            "date_confirmed": True,
        },
    )
    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step)
    try:
        next_stage = WorkflowStep(f"step_{next_step}")
    except ValueError:
        next_stage = WorkflowStep.STEP_3
    write_stage(event_entry, current_step=next_stage, subflow_group=default_subflow(next_stage))

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    record_confirmation_log(event_entry, state, window, reuse_previous)

    state.set_thread_state("In Progress")
    state.current_step = next_step
    # Preserve caller_step so Step 3 can optionally hand control back.
    state.caller_step = event_entry.get("caller_step")
    state.subflow_group = default_subflow(next_stage)
    state.extras["persist"] = True

    gatekeeper = refresh_gatekeeper(event_entry)
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": window.display_date,
        "requested_window": requested_payload,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "next_step": next_step,
        "cache_reused": reuse_previous,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    payload["actions"] = [{"type": "send_reply"}]
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.intent_detail = "event_update"

    promote_fields(
        state,
        event_entry,
        {
            ("date",): window.iso_date,
            ("event_date",): window.display_date,
            ("start_time",): window.start_time,
            ("end_time",): window.end_time,
        },
        remove_deferred=["date_confirmation"],
    )
    if event_entry.get("caller_step") is not None:
        # Prevent downstream steps from re-detecting the same date change
        # within this routing loop (e.g., Step 4 looping back to Step 2).
        state.extras["detour_change_applied"] = "date"
        # BUG-024 FIX: Also persist to event_entry for acknowledgment in step5
        # The flag in state.extras is lost between routing loops
        event_entry["_pending_date_change_ack"] = True
        state.extras["persist"] = True

    autorun_failed = False
    autorun_result: Optional[GroupResult] = None
    autorun_error: Optional[Dict[str, Any]] = None
    if next_step == 3:
        try:
            from workflows.steps.step3_room_availability.trigger.process import process as room_process

            room_result = room_process(state)
            if isinstance(room_result.payload, dict):
                room_result.payload.setdefault("confirmed_date", window.display_date)
                room_result.payload.setdefault("gatekeeper_passed", dict(gatekeeper))
            autorun_result = room_result
        except Exception as exc:  # pragma: no cover - defensive guard
            autorun_failed = True
            state.extras["room_autorun_failed"] = True
            autorun_error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            trace_marker(
                thread_id,
                "STEP3_AUTORUN_FAILED",
                detail=str(exc),
                data={
                    "type": exc.__class__.__name__,
                    "event_id": state.event_id,
                },
                owner_step="Step2_Date",
            )

    participants = _extract_participants_from_state(state)
    noted_line = (
        f"Perfect! I've locked in **{window.display_date}** for **{participants} guests**."
        if participants
        else f"Perfect! **{window.display_date}** is confirmed."
    )
    follow_up_line = "Let me find the best rooms for you now."
    ack_body, ack_headers = format_sections_with_headers(
        [("Next step", [noted_line, follow_up_line])]
    )
    if not autorun_result:
        state.add_draft_message(
            {
                "body": ack_body,
                "body_markdown": ack_body,
                "step": next_step,
                "topic": "date_confirmed",
                "headers": ack_headers,
            }
        )
    if autorun_failed:
        payload["room_autorun_failed"] = True
        if autorun_error:
            payload["room_autorun_error"] = autorun_error
        return GroupResult(action="date_confirmed", payload=payload, halt=False)
    if autorun_result:
        if isinstance(autorun_result.payload, dict):
            autorun_result.payload.setdefault("confirmed_date", window.display_date)
            autorun_result.payload.setdefault("gatekeeper_passed", dict(gatekeeper))
            autorun_result.payload.setdefault("room_autorun", True)
        state.extras["room_autorun_action"] = autorun_result.action
        return autorun_result
    return GroupResult(action="date_confirmed", payload=payload, halt=True)


def clear_step2_hil_tasks(state: WorkflowState, event_entry: dict) -> None:
    """Remove pending Step 2 HIL artifacts once a date is confirmed."""

    pending = event_entry.get("pending_hil_requests") or []
    filtered = [entry for entry in pending if entry.get("step") != 2]
    if len(filtered) != len(pending):
        event_entry["pending_hil_requests"] = filtered
        state.extras["persist"] = True

    tasks = state.db.get("tasks") if state.db else None
    if not tasks:
        return
    changed = False
    for task in tasks:
        if (
            task.get("event_id") == event_entry.get("event_id")
            and task.get("type") == TaskType.DATE_CONFIRMATION_MESSAGE.value
            and task.get("status") == TaskStatus.PENDING.value
        ):
            task["status"] = TaskStatus.DONE.value
            changed = True
    if changed:
        state.extras["persist"] = True


def apply_step2_hil_decision(
    state: WorkflowState,
    event_entry: dict,
    decision: str,
    window_from_payload_fn,
) -> GroupResult:
    """Handle HIL approval or rejection for pending date confirmation.

    Args:
        state: Current workflow state
        event_entry: Event data dict
        decision: HIL decision string ("approve" or other for reject)
        window_from_payload_fn: Function to convert payload to ConfirmationWindow

    Returns:
        GroupResult for HIL decision outcome.
    """

    pending_window = window_from_payload_fn(event_entry.get("pending_date_confirmation") or {})
    if not pending_window:
        pending_window = window_from_payload_fn(event_entry.get("pending_future_confirmation") or {})

    normalized_decision = (decision or "").strip().lower() or "approve"
    if normalized_decision != "approve":
        event_entry.pop("pending_date_confirmation", None)
        event_entry.pop("pending_future_confirmation", None)
        clear_step2_hil_tasks(state, event_entry)
        draft_message = {
            "body": "Manual review declined. Please advise which alternative dates to offer next.",
            "step": 2,
            "topic": "date_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft_message)
        update_event_metadata(event_entry, current_step=2, thread_state="Waiting on HIL")
        state.set_thread_state("Waiting on HIL")
        state.extras["persist"] = True
        append_audit_entry(event_entry, 2, 2, "date_hil_rejected")
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
        return GroupResult(action="date_hil_rejected", payload=payload, halt=True)

    if not pending_window:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_date_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_hil_missing", payload=payload, halt=True)

    event_entry.pop("pending_date_confirmation", None)
    event_entry.pop("pending_future_confirmation", None)
    return finalize_confirmation(state, event_entry, pending_window)
