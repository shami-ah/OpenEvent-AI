"""
D8 Refactoring: Pure confirmation helper functions.

Extracted from step2_handler.py to reduce file size and improve modularity.
These functions handle date determination, time window lookup, and logging
without modifying workflow state.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

# Import from correct locations
from backend.workflows.conditions.checks import is_valid_ddmmyyyy
from backend.workflows.common.datetime_parse import build_window_iso, parse_first_date, to_iso_date
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.relative_dates import resolve_relative_date
from backend.workflows.common.types import WorkflowState
from backend.workflows.io.config_store import get_timezone

from .date_parsing import normalize_iso_candidate as _normalize_iso_candidate
from .step2_utils import (
    _normalize_time_value,
    _strip_system_subject,
    _to_time,
)
from .constants import TIME_HINT_DEFAULTS as _TIME_HINT_DEFAULTS
from .types import ConfirmationWindow


def determine_date(
    user_info: Dict[str, Optional[str]],
    body_text: str,
    subject_text: str,
    event_entry: dict,
    reference_day: date,
) -> Tuple[Optional[str], Optional[str]]:
    """Determine the DD.MM.YYYY and ISO representations for the confirmed date.

    Returns:
        Tuple of (display_date in DD.MM.YYYY format, iso_date in YYYY-MM-DD format)
        or (None, None) if no date could be determined.
    """

    user_event_date = user_info.get("event_date")
    if user_event_date and is_valid_ddmmyyyy(user_event_date):
        iso_value = to_iso_date(user_event_date)
        if iso_value:
            return user_event_date, iso_value

    iso_candidate = user_info.get("date")
    if iso_candidate:
        ddmmyyyy = format_iso_date_to_ddmmyyyy(iso_candidate)
        if ddmmyyyy and is_valid_ddmmyyyy(ddmmyyyy):
            return ddmmyyyy, iso_candidate

    # BUG FIX: Strip system-generated timestamps from subject before parsing
    clean_subject = _strip_system_subject(subject_text)
    parsed = parse_first_date(body_text, reference=reference_day, allow_relative=True) or parse_first_date(
        clean_subject, reference=reference_day, allow_relative=True
    )
    if parsed:
        return parsed.strftime("%d.%m.%Y"), parsed.isoformat()

    # Also use clean subject for relative date resolution
    combined_text = " ".join(value for value in (clean_subject, body_text) if value)
    candidate_isos = collect_candidate_iso_list(event_entry)
    relative_candidates = candidate_isos if candidate_isos else None
    relative_date = resolve_relative_date(combined_text, reference_day, candidates=relative_candidates)
    if relative_date:
        relative_iso = relative_date.isoformat()
        display_value = format_iso_date_to_ddmmyyyy(relative_iso) or relative_iso
        return display_value, relative_iso

    pending = event_entry.get("pending_time_request") or {}
    if pending.get("display_date") and pending.get("iso_date"):
        return pending["display_date"], pending["iso_date"]

    chosen_date = event_entry.get("chosen_date")
    if chosen_date and is_valid_ddmmyyyy(chosen_date):
        iso_value = to_iso_date(chosen_date)
        if iso_value:
            return chosen_date, iso_value
    return None, None


def find_existing_time_window(event_entry: dict, iso_date: str) -> Optional[Tuple[str, str]]:
    """Locate the last known time window associated with the same date.

    Searches through:
    1. requested_window (current request)
    2. requirements.event_duration
    3. event_data (Start Time, End Time)
    4. pending_time_request

    Returns:
        Tuple of (start_time, end_time) in HH:MM format, or None if not found.
    """

    requested = event_entry.get("requested_window") or {}
    if requested.get("date_iso") == iso_date:
        start = _normalize_time_value(requested.get("start_time"))
        end = _normalize_time_value(requested.get("end_time"))
        if start and end:
            return start, end

    requirements = event_entry.get("requirements") or {}
    duration = requirements.get("event_duration") or {}
    start = _normalize_time_value(duration.get("start"))
    end = _normalize_time_value(duration.get("end"))
    if start and end:
        return start, end

    event_data = event_entry.get("event_data") or {}
    start = _normalize_time_value(event_data.get("Start Time"))
    end = _normalize_time_value(event_data.get("End Time"))
    if start and end:
        return start, end

    pending = event_entry.get("pending_time_request") or {}
    if pending.get("iso_date") == iso_date:
        start = _normalize_time_value(pending.get("start_time"))
        end = _normalize_time_value(pending.get("end_time"))
        if start and end:
            return start, end
    return None


def collect_candidate_iso_list(event_entry: dict) -> List[str]:
    """Collect all candidate ISO dates from the event entry.

    Gathers dates from:
    - candidate_dates
    - date_proposal_history
    - pending_date_confirmation
    - pending_future_confirmation
    - requested_window
    - chosen_date

    Returns:
        List of unique ISO date strings.
    """
    seen: List[str] = []

    def _add(value: Any) -> None:
        iso = _normalize_iso_candidate(value)
        if iso and iso not in seen:
            seen.append(iso)

    for source in (
        event_entry.get("candidate_dates"),
        event_entry.get("date_proposal_history"),
    ):
        if not source:
            continue
        for entry in source:
            _add(entry)

    pending = event_entry.get("pending_date_confirmation") or {}
    _add(pending.get("iso_date") or pending.get("date"))

    pending_future = event_entry.get("pending_future_confirmation") or {}
    _add(pending_future.get("iso_date") or pending_future.get("date"))

    requested = event_entry.get("requested_window") or {}
    _add(requested.get("date_iso") or requested.get("iso_date"))

    _add(event_entry.get("chosen_date"))

    return seen


def record_confirmation_log(
    event_entry: dict,
    state: WorkflowState,
    window: ConfirmationWindow,
    reused: bool,
) -> None:
    """Record a confirmation event in the event logs.

    Appends a structured log entry with:
    - Timestamp
    - Intent
    - Requested window details
    - Whether times were inherited
    - Source message ID
    - Whether this was a cache reuse
    """
    logs = event_entry.setdefault("logs", [])
    details = {
        "intent": state.intent.value if state.intent else None,
        "requested_window": {
            "date": window.iso_date,
            "start": window.start_iso,
            "end": window.end_iso,
            "tz": get_timezone(),
        },
        "times_inherited": window.inherited_times,
        "source_message_id": window.source_message_id,
        "reused": reused,
    }
    logs.append(
        {
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "actor": "workflow",
            "action": "date_confirmed",
            "details": details,
        }
    )


def set_pending_time_state(event_entry: dict, window: ConfirmationWindow) -> None:
    """Set the pending time request state on the event entry.

    Used when a date is confirmed but time still needs clarification.
    """
    event_entry["pending_time_request"] = {
        "display_date": window.display_date,
        "iso_date": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "source_message_id": window.source_message_id,
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def complete_from_time_hint(
    window: ConfirmationWindow,
    time_hint: Optional[str],
) -> Optional[ConfirmationWindow]:
    """Complete a partial ConfirmationWindow using a time-of-day hint.

    Extracted from step2_handler.py as part of D11 refactoring.

    Args:
        window: Partial ConfirmationWindow with date but missing times
        time_hint: Vague time hint like "evening", "afternoon", etc.

    Returns:
        Complete ConfirmationWindow with times filled in, or None if hint invalid.
    """
    if not time_hint:
        return None
    defaults = _TIME_HINT_DEFAULTS.get(str(time_hint).lower())
    if not defaults:
        return None
    try:
        start_iso, end_iso = build_window_iso(
            window.iso_date,
            _to_time(defaults[0]),
            _to_time(defaults[1]),
        )
    except ValueError:
        return None
    return ConfirmationWindow(
        display_date=window.display_date,
        iso_date=window.iso_date,
        start_time=defaults[0],
        end_time=defaults[1],
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=True,
        partial=False,
        source_message_id=window.source_message_id,
    )


def should_auto_accept_first_date(event_entry: dict) -> bool:
    """Determine if the first date should be auto-accepted.

    Extracted from step2_handler.py as part of D13c refactoring.

    Returns True only when:
    - No hash exists on requested_window
    - No pending date confirmation
    - No already-confirmed date

    Args:
        event_entry: Event data dict

    Returns:
        True if first date can be auto-accepted
    """
    requested_window = event_entry.get("requested_window") or {}
    if requested_window.get("hash"):
        return False
    if event_entry.get("pending_date_confirmation"):
        return False
    if event_entry.get("chosen_date") and event_entry.get("date_confirmed"):
        return False
    return True
