"""Centralized Site Visit Handler.

Handles site visit booking requests from ANY workflow step (2-7).

IMPORTANT: Site visits are VENUE-WIDE (not room-specific).
- Client visits the whole venue/selection
- Manager configures available time slots via site_visit_config
- No room selection needed!

Conflict Rules:
- Site visits CANNOT be booked on event days (hard block)
- Events CAN be booked on site visit days (triggers manager notification)

Flow:
    1. Client requests site visit
    2. Check for conflicts with existing events
    3. Offer available time slots
    4. Once date is confirmed → scheduled

This module can be called from:
- Step 2 (Date Confirmation)
- Step 3 (Room Availability)
- Step 4 (Offer)
- Step 5 (Negotiation)
- Step 6 (Transition)
- Step 7 (Confirmation)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from backend.detection.unified import UnifiedDetectionResult
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.site_visit_state import (
    get_site_visit_state,
    set_site_visit_date,
    start_site_visit_flow,
)
from backend.workflows.io.config_store import (
    get_site_visit_blocked_dates,
    get_site_visit_slots,
    get_site_visit_weekdays_only,
    get_site_visit_min_days_ahead,
)
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import (
    append_audit_entry,
    get_event_dates,
    load_db,
    update_event_metadata,
)


# Default database path - can be overridden for testing
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "events_database.json"

# Injectable database loader for testing
_db_loader: Optional[Callable[[], Dict[str, Any]]] = None


def set_db_loader(loader: Optional[Callable[[], Dict[str, Any]]]) -> None:
    """Set a custom database loader (for testing).

    Args:
        loader: Callable that returns the database dict, or None to use default
    """
    global _db_loader
    _db_loader = loader


def _load_database() -> Dict[str, Any]:
    """Load the database using the configured loader."""
    if _db_loader is not None:
        return _db_loader()
    return load_db(_DEFAULT_DB_PATH)


def handle_site_visit_request(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> Optional[GroupResult]:
    """Handle a site visit request from any workflow step.

    This is the main entry point for site visit handling.
    Site visits are venue-wide (no room selection needed).

    Returns:
        GroupResult if site visit was handled, None if not applicable
    """
    sv_state = get_site_visit_state(event_entry)

    # Determine what state we're in
    status = sv_state.get("status", "idle")

    if status == "idle":
        # New site visit request
        return _start_site_visit(state, event_entry, detection)

    elif status == "date_pending":
        # Waiting for date selection
        return _handle_date_selection(state, event_entry, detection)

    elif status == "scheduled":
        # Already scheduled - offer to reschedule
        return _site_visit_already_scheduled(state, event_entry)

    elif status in ("completed", "cancelled"):
        # Offer to book a new one
        return _start_site_visit(state, event_entry, detection)

    return None


def _start_site_visit(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> GroupResult:
    """Start a new site visit booking flow.

    Since site visits are venue-wide, we go directly to date selection.
    """
    current_step = event_entry.get("current_step", 3)

    # Start the flow (records initiated_at_step)
    start_site_visit_flow(event_entry, initiated_at_step=current_step)

    # Check if client mentioned a specific date preference
    requested_date: Optional[str] = None
    if detection:
        requested_date = detection.site_visit_date

    if requested_date:
        # Client specified a date - check for conflicts
        return _check_date_conflict(state, event_entry, requested_date)

    # No specific date - offer available slots
    return _offer_date_slots(state, event_entry)


def _offer_date_slots(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Offer available site visit time slots."""
    sv_state = get_site_visit_state(event_entry)

    # Get blocked dates (event dates)
    blocked_dates = _get_blocked_dates(event_entry)

    # Generate slots avoiding blocked dates
    slots = _generate_visit_slots(event_entry, blocked_dates)
    sv_state["proposed_slots"] = slots

    slot_list = "\n".join(f"- {slot}" for slot in slots)

    body = (
        f"I'd be happy to arrange a site visit for you. "
        f"Here are some available times to see our venue:\n\n{slot_list}\n\n"
        f"Which works best for you? Or let me know if you have other preferences."
    )

    current_step = event_entry.get("current_step", 3)

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": "site_visit_date_selection",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action="site_visit_date_selection",
        payload=_base_payload(state, event_entry),
        halt=True,
    )


def _check_date_conflict(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    requested_date: str,
) -> GroupResult:
    """Check if requested date has a conflict with events.

    If the date conflicts with an event, we BLOCK and offer alternatives.
    Site visits CANNOT be booked on event days.
    """
    blocked_dates = _get_blocked_dates(event_entry)

    # Normalize the date for comparison
    try:
        if "." in requested_date:
            day, month, year = map(int, requested_date.split("."))
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"
        else:
            date_iso = requested_date[:10]  # Take just the date part
    except (ValueError, IndexError):
        date_iso = requested_date

    if date_iso in blocked_dates:
        # Conflict! Offer alternatives
        return _date_conflict_response(state, event_entry, requested_date)

    # No conflict - confirm the date
    sv_state = get_site_visit_state(event_entry)
    set_site_visit_date(event_entry, date_iso, None)
    return _confirm_site_visit(state, event_entry, requested_date)


def _date_conflict_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    requested_date: str,
) -> GroupResult:
    """Response when requested date conflicts with an event.

    Site visits CANNOT be booked on event days (hard block).
    """
    sv_state = get_site_visit_state(event_entry)
    blocked_dates = _get_blocked_dates(event_entry)

    # Generate alternative slots
    slots = _generate_visit_slots(event_entry, blocked_dates)
    sv_state["proposed_slots"] = slots

    slot_list = "\n".join(f"- {slot}" for slot in slots)

    body = (
        f"Unfortunately, {requested_date} isn't available for site visits "
        f"as we have an event scheduled that day. "
        f"Here are some alternative times:\n\n{slot_list}\n\n"
        f"Would any of these work for you?"
    )

    current_step = event_entry.get("current_step", 3)

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": "site_visit_date_conflict",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action="site_visit_date_conflict",
        payload=_base_payload(state, event_entry),
        halt=True,
    )


def _handle_date_selection(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> GroupResult:
    """Handle client's date selection for site visit.

    When in date_pending state, ANY date mentioned should be interpreted
    as the desired site visit date - the client doesn't need to explicitly
    say "site visit" again.
    """
    sv_state = get_site_visit_state(event_entry)
    slots = sv_state.get("proposed_slots", [])
    message_text = (state.message.body or "").strip()

    # Try to parse selection from message (check if it matches a proposed slot)
    selected_slot = _parse_slot_selection(message_text, slots)

    # Also check detection result for site_visit_date
    if not selected_slot and detection and detection.site_visit_date:
        selected_slot = detection.site_visit_date

    # CONTEXT-AWARE: If we're in date_pending, ANY date in the message is a site visit date
    # The client doesn't need to say "site visit" - they're replying to our date question
    if not selected_slot and detection and detection.date:
        # Use the generic date field as site visit date
        selected_slot = detection.date

    # Last resort: try to extract date directly from message text
    if not selected_slot:
        extracted = _extract_date_from_message(message_text)
        if extracted:
            selected_slot = extracted

    if selected_slot:
        # Check for conflicts before confirming
        blocked_dates = _get_blocked_dates(event_entry)

        # Normalize the date
        try:
            if " at " in selected_slot:
                date_part = selected_slot.split(" at ")[0]
                day, month, year = map(int, date_part.split("."))
                date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            elif "." in selected_slot:
                day, month, year = map(int, selected_slot.split("."))
                date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            else:
                date_iso = selected_slot[:10]
        except (ValueError, IndexError):
            date_iso = selected_slot

        if date_iso in blocked_dates:
            return _date_conflict_response(state, event_entry, selected_slot)

        # No conflict - parse and confirm
        confirmed_date, confirmed_time = _parse_slot(selected_slot)
        if confirmed_date:
            set_site_visit_date(event_entry, confirmed_date, confirmed_time)
            return _confirm_site_visit(state, event_entry, selected_slot)

    # Couldn't parse - ask again
    return _ask_for_date_clarification(state, event_entry)


def _ask_for_date_clarification(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Ask for clarification when date selection wasn't understood."""
    body = (
        "I couldn't determine which date and time you'd prefer. "
        "Could you please specify when you'd like to visit? "
        "For example: 'Next Tuesday at 14:00' or 'January 15th in the morning'."
    )

    current_step = event_entry.get("current_step", 3)

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": "site_visit_date_clarification",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action="site_visit_date_clarification",
        payload=_base_payload(state, event_entry),
        halt=True,
    )


def _confirm_site_visit(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    selected_slot: str,
) -> GroupResult:
    """Confirm the scheduled site visit."""
    current_step = event_entry.get("current_step", 3)

    body = (
        f"Your site visit is confirmed for **{selected_slot}**. "
        f"We look forward to showing you our venue!"
    )

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step="Site visit scheduled",
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": "site_visit_confirmed",
        "requires_approval": False,  # Direct confirm
    }
    state.add_draft_message(draft)
    append_audit_entry(event_entry, current_step, current_step, "site_visit_confirmed")
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action="site_visit_confirmed",
        payload=_base_payload(state, event_entry),
        halt=True,
    )


def _site_visit_already_scheduled(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Handle when site visit is already scheduled."""
    sv_state = get_site_visit_state(event_entry)
    date = sv_state.get("date_iso") or sv_state.get("confirmed_date")
    time_slot = sv_state.get("time_slot") or sv_state.get("confirmed_time")

    date_display = date
    if date and time_slot:
        date_display = f"{date} at {time_slot}"

    current_step = event_entry.get("current_step", 3)

    body = (
        f"You already have a site visit scheduled for **{date_display}**. "
        f"Would you like to reschedule?"
    )

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step="Confirm or reschedule",
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": "site_visit_already_scheduled",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action="site_visit_already_scheduled",
        payload=_base_payload(state, event_entry),
        halt=True,
    )


# =============================================================================
# Conflict Detection
# =============================================================================


def _get_blocked_dates(
    event_entry: Dict[str, Any],
    db: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """Get dates that are blocked for site visits (event days).

    Returns a set of ISO date strings (YYYY-MM-DD) that cannot be booked
    for site visits because events are scheduled on those days.

    Conflict Rule: Site visits CANNOT be booked on event days (hard block).

    Args:
        event_entry: Current event being processed
        db: Optional database dict (if None, loads from file)

    Returns:
        Set of ISO date strings that are blocked for site visits
    """
    blocked: Set[str] = set()

    # Load database if not provided
    if db is None:
        db = _load_database()

    # Get current event's ID to exclude from query (avoid blocking its own date twice)
    current_event_id = event_entry.get("event_id")

    # Query ALL event dates from the database
    all_event_dates = get_event_dates(
        db,
        exclude_event_id=None,  # Include all events, even current one
        exclude_cancelled=True,
    )
    blocked.update(all_event_dates)

    # Also add current event's date if not yet in database
    # (handles case where event is being created and not persisted yet)
    event_date = event_entry.get("chosen_date") or event_entry.get("user_info", {}).get("date")
    if event_date:
        try:
            if "." in event_date:
                day, month, year = map(int, event_date.split("."))
                blocked.add(f"{year:04d}-{month:02d}-{day:02d}")
            else:
                blocked.add(event_date[:10])  # ISO format
        except (ValueError, IndexError):
            pass

    # Load additional blocked dates from config (holidays, maintenance, etc.)
    config_blocked = get_site_visit_blocked_dates()
    blocked.update(config_blocked)

    return blocked


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_visit_slots(
    event_entry: Dict[str, Any],
    blocked_dates: Set[str],
) -> List[str]:
    """Generate available site visit slots.

    Slots are generated BEFORE the event date and exclude blocked dates.
    """
    # Get event date
    event_date_str = event_entry.get("chosen_date") or event_entry.get(
        "user_info", {}
    ).get("date")

    try:
        if event_date_str:
            # Parse dd.mm.yyyy format
            if "." in event_date_str:
                day, month, year = map(int, event_date_str.split("."))
                event_date = datetime(year, month, day)
            else:
                event_date = datetime.fromisoformat(event_date_str.replace("Z", ""))
        else:
            event_date = datetime.utcnow() + timedelta(days=30)
    except (ValueError, IndexError):
        event_date = datetime.utcnow() + timedelta(days=30)

    # Generate slots before the event date
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    slots: List[str] = []

    # Load time slots from config (morning, early afternoon, late afternoon)
    times = get_site_visit_slots()

    # Load weekday preference and min days ahead from config
    weekdays_only = get_site_visit_weekdays_only()
    min_days_ahead = get_site_visit_min_days_ahead()

    # Start from 1 week before event, work backwards
    candidate = event_date - timedelta(days=7)

    for _ in range(30):  # Search up to 30 days back
        if candidate < today + timedelta(days=min_days_ahead):
            candidate -= timedelta(days=1)
            continue

        # Check if date is blocked
        candidate_iso = candidate.date().isoformat()
        if candidate_iso in blocked_dates:
            candidate -= timedelta(days=1)
            continue

        # Check weekday requirement (configurable)
        if not weekdays_only or candidate.weekday() < 5:
            for hour in times:
                slot_dt = candidate.replace(hour=hour, minute=0)
                slots.append(slot_dt.strftime("%d.%m.%Y at %H:%M"))
                if len(slots) >= 3:
                    break

        if len(slots) >= 3:
            break

        candidate -= timedelta(days=1)

    # If no slots found before event, try after today
    if not slots:
        candidate = today + timedelta(days=min_days_ahead + 1)
        for _ in range(30):
            candidate_iso = candidate.date().isoformat()
            is_valid_day = not weekdays_only or candidate.weekday() < 5
            if candidate_iso not in blocked_dates and is_valid_day:
                for hour in times:
                    slot_dt = candidate.replace(hour=hour, minute=0)
                    slots.append(slot_dt.strftime("%d.%m.%Y at %H:%M"))
                    if len(slots) >= 3:
                        break
            if len(slots) >= 3:
                break
            candidate += timedelta(days=1)

    return slots


def _extract_date_from_message(message_text: str) -> Optional[str]:
    """Extract a date from message text using regex patterns.

    This is a fallback when detection doesn't extract the date.
    Returns format like "15.02.2026 at 10:00" or just "15.02.2026".
    """
    import re

    # Pattern for DD.MM.YYYY with optional time
    # e.g., "15.02.2026 at 10:00" or "15.02.2026"
    pattern_eu = r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
    match = re.search(pattern_eu, message_text)

    if match:
        day, month, year = match.groups()
        date_str = f"{int(day):02d}.{int(month):02d}.{year}"

        # Check for time
        time_pattern = r"at\s+(\d{1,2}[:.]\d{2})"
        time_match = re.search(time_pattern, message_text, re.IGNORECASE)
        if time_match:
            time_str = time_match.group(1).replace(".", ":")
            return f"{date_str} at {time_str}"
        return date_str

    # Pattern for YYYY-MM-DD (ISO format)
    pattern_iso = r"(\d{4})-(\d{2})-(\d{2})"
    match = re.search(pattern_iso, message_text)
    if match:
        return match.group(0)

    return None


def _parse_slot_selection(message_text: str, slots: List[str]) -> Optional[str]:
    """Parse which slot client selected from their message."""
    lowered = message_text.lower()

    # Check for ordinal selection
    ordinals = [
        ("first", 0),
        ("1st", 0),
        ("second", 1),
        ("2nd", 1),
        ("third", 2),
        ("3rd", 2),
    ]
    for word, idx in ordinals:
        if word in lowered and idx < len(slots):
            return slots[idx]

    # Check for date match in message
    for slot in slots:
        date_part = slot.split(" at ")[0]  # "15.04.2026"
        if date_part in message_text:
            return slot

    # Generic confirmation = first slot
    confirm_words = (
        "yes",
        "proceed",
        "ok",
        "confirm",
        "sounds good",
        "perfect",
        "ja",
        "bitte",
    )
    if any(word in lowered for word in confirm_words) and slots:
        return slots[0]

    return None


def _parse_slot(slot: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a slot string into (date_iso, time)."""
    try:
        if " at " in slot:
            date_part, time_part = slot.split(" at ")
            parsed_date = datetime.strptime(date_part, "%d.%m.%Y")
            return parsed_date.date().isoformat(), time_part
        else:
            # Might be ISO format
            parsed_date = datetime.fromisoformat(slot.replace("Z", ""))
            return parsed_date.date().isoformat(), None
    except (ValueError, IndexError):
        return None, None


def _base_payload(state: WorkflowState, event_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Build base payload for GroupResult."""
    return {
        "event_id": event_entry.get("id") or state.event_id,
        "current_step": event_entry.get("current_step"),
        "thread_state": state.thread_state,
        "site_visit_state": event_entry.get("site_visit_state", {}),
    }


def is_site_visit_intent(detection: Optional[UnifiedDetectionResult]) -> bool:
    """Check if detection result indicates a site visit intent."""
    if not detection:
        return False

    # Check qna_types
    if "site_visit_request" in detection.qna_types:
        return True
    if "site_visit_overview" in detection.qna_types:
        return True

    # Check step_anchor
    if detection.step_anchor == "Site Visit":
        return True

    return False


__all__ = [
    "handle_site_visit_request",
    "is_site_visit_intent",
    "set_db_loader",
    "_get_blocked_dates",  # Exported for testing
]
