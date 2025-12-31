"""
Smart Shortcuts - Date Handler.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles date/time processing for the shortcuts planner:
- Time normalization and ISO parsing
- Window conversion (ConfirmationWindow <-> payload dict)
- Date intent parsing and confirmation
- Date options generation and slot formatting

Usage:
    from .date_handler import (
        normalize_time, time_from_iso,
        window_to_payload, window_from_payload,
        parse_date_intent, ensure_date_choice_intent,
    )
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from backend.workflows.common.datetime_parse import build_window_iso
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.io.config_store import get_timezone
from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
from backend.workflows.steps.step2_date_confirmation.trigger.types import ConfirmationWindow

if TYPE_CHECKING:
    from .shortcuts_types import ParsedIntent, PlannerResult
    from .smart_shortcuts import _ShortcutPlanner

# Lazy import of Step 2 process module (getattr for dynamic methods)
date_process_module = None


def _get_date_process_module():
    """Lazy-load the Step 2 process module."""
    global date_process_module
    if date_process_module is None:
        from backend.workflows.steps.step2_date_confirmation.trigger import process as mod
        date_process_module = mod
    return date_process_module


# --------------------------------------------------------------------------
# Static time utilities
# --------------------------------------------------------------------------


def normalize_time(value: Any) -> Optional[str]:
    """Normalize a time value to HH:MM format.

    Handles:
    - "18:00" -> "18:00"
    - "18.00" -> "18:00"
    - "18" -> "18:00"
    - None/empty -> None
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", ":")
    if ":" not in text:
        if text.isdigit():
            text = f"{int(text) % 24:02d}:00"
        else:
            return None
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def time_from_iso(value: Optional[str]) -> Optional[str]:
    """Extract HH:MM time from an ISO datetime string.

    Args:
        value: ISO datetime string like "2026-02-15T18:00:00+01:00"

    Returns:
        Time string like "18:00" or None
    """
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return f"{parsed.hour:02d}:{parsed.minute:02d}"
    except ValueError:
        pass
    # Fallback: extract time from position 11-16 (YYYY-MM-DDTHH:MM)
    if len(text) >= 16 and text[13] == ":":
        candidate = text[11:16]
        return normalize_time(candidate)
    return normalize_time(text)


# --------------------------------------------------------------------------
# Window conversion (ConfirmationWindow <-> Dict)
# --------------------------------------------------------------------------


def window_to_payload(window: ConfirmationWindow) -> Dict[str, Any]:
    """Convert a ConfirmationWindow to a serializable dict payload."""
    return {
        "display_date": window.display_date,
        "iso_date": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start_iso": window.start_iso,
        "end_iso": window.end_iso,
        "tz": getattr(window, "tz", None) or get_timezone(),
        "inherited_times": getattr(window, "inherited_times", False),
        "partial": getattr(window, "partial", False),
        "source_message_id": getattr(window, "source_message_id", None),
    }


def window_from_payload(payload: Dict[str, Any]) -> ConfirmationWindow:
    """Convert a dict payload back to a ConfirmationWindow."""
    return ConfirmationWindow(
        display_date=payload.get("display_date"),
        iso_date=payload.get("iso_date"),
        start_time=payload.get("start_time"),
        end_time=payload.get("end_time"),
        start_iso=payload.get("start_iso"),
        end_iso=payload.get("end_iso"),
        inherited_times=payload.get("inherited_times", False),
        partial=payload.get("partial", False),
        source_message_id=payload.get("source_message_id"),
    )


# --------------------------------------------------------------------------
# Time inference from event data
# --------------------------------------------------------------------------


def infer_times_for_date(
    planner: "_ShortcutPlanner", iso_date: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Infer start/end times for a given date from event data.

    Checks in order:
    1. requested_window (if date matches)
    2. requirements.event_duration
    3. event_data Start/End Time
    """
    if not iso_date:
        return None, None

    # Check requested_window
    requested = planner.event.get("requested_window") or {}
    if requested:
        date_match = requested.get("date_iso") == iso_date
        display_match = requested.get("display_date") == format_iso_date_to_ddmmyyyy(iso_date)
        if date_match or display_match:
            start_time = requested.get("start_time")
            end_time = requested.get("end_time")
            if not start_time and requested.get("start"):
                start_time = requested.get("start")[11:16]
            if not end_time and requested.get("end"):
                end_time = requested.get("end")[11:16]
            return start_time, end_time

    # Check requirements.event_duration
    requirements = planner.event.get("requirements") or {}
    duration = requirements.get("event_duration") or {}
    if duration.get("start") and duration.get("end"):
        return duration.get("start"), duration.get("end")

    # Check event_data
    event_data = planner.event.get("event_data") or {}
    start = event_data.get("Start Time")
    end = event_data.get("End Time")
    return start, end


# --------------------------------------------------------------------------
# Preferred date slot formatting
# --------------------------------------------------------------------------


def preferred_date_slot(planner: "_ShortcutPlanner") -> str:
    """Build a formatted time slot string like '18:00-22:00'.

    Checks user_info, requested_window, and requirements for times.
    Falls back to 18:00-22:00 if no times found.
    """
    start = normalize_time(planner.user_info.get("start_time"))
    end = normalize_time(planner.user_info.get("end_time"))

    requested = planner.event.get("requested_window") or {}
    if not start:
        start = normalize_time(requested.get("start_time")) or time_from_iso(requested.get("start"))
    if not end:
        end = normalize_time(requested.get("end_time")) or time_from_iso(requested.get("end"))

    requirements = planner.event.get("requirements") or {}
    duration = requirements.get("event_duration") or {}
    if not start:
        start = normalize_time(duration.get("start"))
    if not end:
        end = normalize_time(duration.get("end"))

    start = start or "18:00"
    end = end or "22:00"
    if start and end:
        return f"{start}–{end}"
    return start or end or "18:00–22:00"


# --------------------------------------------------------------------------
# Date options generation
# --------------------------------------------------------------------------


def candidate_date_options(planner: "_ShortcutPlanner") -> List[str]:
    """Generate a list of up to 5 candidate dates from availability."""
    requirements = planner.event.get("requirements") or {}
    preferred_room = requirements.get("preferred_room") or ""
    raw_dates = suggest_dates(
        planner.state.db,
        preferred_room=preferred_room,
        start_from_iso=planner.state.message.ts,
        days_ahead=45,
        max_results=5,
    )
    return raw_dates[:5]


def maybe_emit_date_options_answer(planner: "_ShortcutPlanner") -> Optional["PlannerResult"]:
    """Emit a date options answer if date_choice is the pending question.

    Returns a PlannerResult with the date options list, or None if not applicable.
    """
    if planner.verifiable:
        return None

    date_needed = next((intent for intent in planner.needs_input if intent.type == "date_choice"), None)
    if not date_needed:
        return None

    slot_label = preferred_date_slot(planner)
    options = candidate_date_options(planner)
    lines: List[str] = [f"AVAILABLE DATES ({slot_label}):"]

    if options:
        for idx, option in enumerate(options, start=1):
            lines.append(f"{idx}) {option}")
    else:
        lines.append("No availability in the next 45 days. Share another window and I'll check.")

    lines.append("")
    option_count = len(options)
    if option_count == 0:
        lines.append("Tell me another date/time window and I'll check it right away.")
    elif option_count == 1:
        lines.append("Reply with 1, or tell me another date/time window.")
    else:
        lines.append(f"Reply with a number (1–{option_count}), or tell me another date/time window.")

    planner.telemetry.needs_input_next = "date_choice"
    planner.telemetry.answered_question_first = True
    planner.telemetry.combined_confirmation = False
    planner.telemetry.menus_included = "false"
    planner.telemetry.menus_phase = "none"
    planner.state.telemetry.answered_question_first = True
    planner._set_dag_block("room_requires_date")
    return planner._build_payload(planner._with_greeting("\n".join(lines)))


# --------------------------------------------------------------------------
# Window resolution from Step 2 module
# --------------------------------------------------------------------------


def resolve_window_from_module(
    planner: "_ShortcutPlanner", preview: bool = False
) -> Optional[ConfirmationWindow]:
    """Resolve a ConfirmationWindow using Step 2's resolver.

    Falls back to manual_window_from_user_info if resolver returns None.
    """
    mod = _get_date_process_module()
    resolver = getattr(mod, "_resolve_confirmation_window", None)
    if not resolver:
        return None

    window = resolver(planner.state, planner.event)
    if not window:
        return manual_window_from_user_info(planner)

    if preview and window.partial and not window.start_time:
        return None
    return window


def manual_window_from_user_info(planner: "_ShortcutPlanner") -> Optional[ConfirmationWindow]:
    """Build a ConfirmationWindow from user_info fields.

    Requires date + display_date + start_time + end_time to be present.
    """
    date_iso = planner.user_info.get("date")
    display = planner.user_info.get("event_date") or format_iso_date_to_ddmmyyyy(date_iso)

    start_raw = planner.user_info.get("start_time")
    end_raw = planner.user_info.get("end_time")

    if not (start_raw and end_raw):
        inferred_start, inferred_end = infer_times_for_date(planner, date_iso)
        start_raw = start_raw or inferred_start
        end_raw = end_raw or inferred_end

    if not (date_iso and display and start_raw and end_raw):
        return None

    start_norm = normalize_time(start_raw)
    end_norm = normalize_time(end_raw)
    if not (start_norm and end_norm):
        return None

    start_time_obj = datetime.strptime(start_norm, "%H:%M").time()
    end_time_obj = datetime.strptime(end_norm, "%H:%M").time()
    start_iso, end_iso = build_window_iso(date_iso, start_time_obj, end_time_obj)

    return ConfirmationWindow(
        display_date=display,
        iso_date=date_iso,
        start_time=start_norm,
        end_time=end_norm,
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=False,
        partial=False,
        source_message_id=planner.state.message.msg_id,
    )


# --------------------------------------------------------------------------
# Date intent parsing
# --------------------------------------------------------------------------


def parse_date_intent(planner: "_ShortcutPlanner") -> None:
    """Parse date intent from user_info and add to verifiable intents.

    Checks for date/event_date in user_info, resolves window, and creates
    a date_confirmation intent if complete. Otherwise adds time needs_input.
    """
    if not (planner.user_info.get("date") or planner.user_info.get("event_date")):
        return

    window = manual_window_from_user_info(planner)
    if window is None:
        window = resolve_window_from_module(planner, preview=False)
    if window is None:
        planner._add_needs_input("time", {"reason": "missing_time"}, reason="missing_time")
        return
    if getattr(window, "partial", False):
        planner._add_needs_input("time", {"reason": "missing_time"}, reason="missing_time")
        return

    # Import here to avoid circular imports at module level
    from .shortcuts_types import ParsedIntent

    intent = ParsedIntent("date_confirmation", {"window": window_to_payload(window)}, verifiable=True)
    planner.verifiable.append(intent)


def ensure_date_choice_intent(planner: "_ShortcutPlanner") -> None:
    """Ensure a date_choice needs_input is emitted if date is missing.

    Only runs at step 1-2, skips if date already chosen or intent exists.
    """
    current_step = planner.event.get("current_step")
    if current_step not in (None, 1, 2):
        return
    if planner.event.get("chosen_date"):
        return
    if any(intent.type == "date_confirmation" for intent in planner.verifiable):
        return
    if any(intent.type in {"time", "date_choice"} for intent in planner.needs_input):
        return

    planner._add_needs_input("date_choice", {"reason": "date_missing"}, reason="date_missing")


# --------------------------------------------------------------------------
# Date confirmation application
# --------------------------------------------------------------------------


def apply_date_confirmation(planner: "_ShortcutPlanner", window_payload: Dict[str, Any]) -> bool:
    """Apply a date confirmation using Step 2's finalize function.

    Args:
        planner: The shortcuts planner instance
        window_payload: Dict with window fields (display_date, iso_date, times, etc.)

    Returns:
        True if confirmation was successful, False otherwise.
    """
    mod = _get_date_process_module()
    finalize = getattr(mod, "_finalize_confirmation", None)
    if not finalize:
        return False

    window_obj = window_from_payload(window_payload)
    result = finalize(planner.state, planner.event, window_obj)

    # Remove legacy draft message; planner will compose new reply.
    planner.state.draft_messages.clear()
    planner.state.extras["persist"] = True
    planner.telemetry.executed_intents.append("date_confirmation")

    start = window_payload.get("start_time")
    end = window_payload.get("end_time")
    iso = window_payload.get("display_date")
    tz = window_payload.get("tz") or get_timezone()

    if start and end:
        slot = f"{start}–{end}"
    elif start:
        slot = start
    else:
        slot = "time pending"

    planner.summary_lines.append(f"• Date confirmed: {iso} {slot} ({tz})")
    return result is not None


# --------------------------------------------------------------------------
# Date + Room combo execution
# --------------------------------------------------------------------------


def should_execute_date_room_combo(planner: "_ShortcutPlanner") -> bool:
    """Check if both date and room intents can be executed together.

    Requires:
    - Both date_confirmation and room_selection in verifiable
    - Window is not partial
    - Room can be locked
    """
    date_intent = next((intent for intent in planner.verifiable if intent.type == "date_confirmation"), None)
    room_intent = next((intent for intent in planner.verifiable if intent.type == "room_selection"), None)

    if not date_intent or not room_intent:
        return False

    window = date_intent.data.get("window") or {}
    if window.get("partial"):
        return False

    requested_room = room_intent.data.get("room")
    if not requested_room or not planner._can_lock_room(requested_room):
        return False

    return True


def execute_date_room_combo(planner: "_ShortcutPlanner") -> bool:
    """Execute both date confirmation and room selection together.

    Returns True if both operations succeeded.
    """
    date_intent = next((intent for intent in planner.verifiable if intent.type == "date_confirmation"), None)
    room_intent = next((intent for intent in planner.verifiable if intent.type == "room_selection"), None)

    if not date_intent or not room_intent:
        return False

    window_payload = date_intent.data.get("window") or {}
    if not apply_date_confirmation(planner, window_payload):
        return False

    requested_room = room_intent.data.get("room")
    if not planner._apply_room_selection(requested_room):
        return False

    return True


__all__ = [
    # Time utilities
    "normalize_time",
    "time_from_iso",
    # Window conversion
    "window_to_payload",
    "window_from_payload",
    # Time inference
    "infer_times_for_date",
    # Date slot/options
    "preferred_date_slot",
    "candidate_date_options",
    "maybe_emit_date_options_answer",
    # Window resolution
    "resolve_window_from_module",
    "manual_window_from_user_info",
    # Date intent
    "parse_date_intent",
    "ensure_date_choice_intent",
    # Date confirmation
    "apply_date_confirmation",
    # Combo execution
    "should_execute_date_room_combo",
    "execute_date_room_combo",
]
