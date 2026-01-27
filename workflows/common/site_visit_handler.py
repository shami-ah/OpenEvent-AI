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

import logging
import re

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from detection.unified import UnifiedDetectionResult
from workflows.common.prompts import append_footer
from workflows.common.site_visit_state import (
    confirm_pending_site_visit,
    get_site_visit_state,
    is_site_visit_change_request,
    is_site_visit_pending_time,
    parse_slot_string,
    set_pending_confirmation,
    set_site_visit_date,
    set_time_pending,
    start_site_visit_flow,
)
from workflows.io.config_store import (
    get_site_visit_blocked_dates,
    get_site_visit_slots,
    get_site_visit_weekdays_only,
    get_site_visit_min_days_ahead,
)
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import (
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


# =============================================================================
# Response Helpers
# =============================================================================


def _send_draft_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    body: str,
    action: str,
    next_step: str,
    requires_approval: bool = True,
) -> GroupResult:
    """Create and send a draft response with standard site visit handling.

    Consolidates the repeated pattern of:
    1. Creating draft dict with footer
    2. Adding draft to state
    3. Updating thread state
    4. Setting persist flag
    5. Returning GroupResult

    Note: requires_approval respects the HIL toggle setting.
    If HIL is OFF (hil_all_llm_replies=False), site visit messages
    are sent directly without manager approval.
    """
    from workflows.io.integration.config import is_hil_all_replies_enabled

    current_step = event_entry.get("current_step", 3)

    # Respect the HIL toggle - if OFF, don't require approval for site visits
    # Site visits are automated responses, not critical workflow steps
    actual_requires_approval = requires_approval and is_hil_all_replies_enabled()

    draft = {
        "body": append_footer(
            body,
            step=current_step,
            next_step=next_step,
            thread_state="Awaiting Client",
        ),
        "step": current_step,
        "topic": action,
        "requires_approval": actual_requires_approval,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    return GroupResult(
        action=action,
        payload=_base_payload(state, event_entry),
        halt=True,
    )


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
    selected_date = sv_state.get("selected_date")
    proposed_slots = sv_state.get("proposed_slots", [])
    logger.debug("[SV_HANDLER] Entry: status=%s, selected_date=%s, slots=%d",
                 status, selected_date, len(proposed_slots))

    if status == "idle":
        # New site visit request
        return _start_site_visit(state, event_entry, detection)

    elif status == "date_pending":
        # Waiting for date selection
        return _handle_date_selection(state, event_entry, detection)

    elif status == "time_pending":
        # Date selected, waiting for time slot selection
        return _handle_time_selection(state, event_entry, detection)

    elif status == "confirm_pending":
        # Date+time validated, waiting for explicit client confirmation
        return _handle_confirmation_response(state, event_entry, detection)

    elif status == "scheduled":
        # Already scheduled - check if this is a reschedule request
        message_text = (state.message.body or "").strip()
        if is_site_visit_change_request(message_text):
            print("[SV_HANDLER] Reschedule request detected - restarting site visit flow")
            # Reset state to idle and restart the flow
            sv_state["status"] = "idle"
            sv_state["date_iso"] = None
            sv_state["time_slot"] = None
            sv_state["proposed_slots"] = []
            sv_state["selected_date"] = None
            sv_state["pending_slot"] = None
            # Check if client provided a new date/time
            return _start_site_visit(state, event_entry, detection)
        else:
            # Just inform them it's already scheduled
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
    Shows all available date+time combinations upfront for UX improvement.
    Only goes to conflict check path when BOTH date AND time are explicit.
    """
    current_step = event_entry.get("current_step", 3)

    # Start the flow (records initiated_at_step)
    start_site_visit_flow(event_entry, initiated_at_step=current_step)

    # Check if client mentioned a SPECIFIC date+time preference
    # Only use conflict check path when both date AND time are explicit
    requested_slot: Optional[str] = None
    if detection and detection.site_visit_date:
        date_iso, time_slot = parse_slot_string(detection.site_visit_date)
        # Check if time is in the separate site_visit_time field
        if date_iso and not time_slot and detection.site_visit_time:
            # Combine date from site_visit_date with time from site_visit_time
            time_slot = detection.site_visit_time
            requested_slot = f"{date_iso} at {time_slot}"
            logger.info("[SV] Combined date+time from separate fields: %s", requested_slot)
        elif date_iso and time_slot:
            # Both were in site_visit_date
            requested_slot = detection.site_visit_date

    if requested_slot:
        # Client specified date+time explicitly - check for conflicts
        return _check_date_conflict(state, event_entry, requested_slot)

    # No full date+time specified - offer all available slots (combined format)
    return _offer_date_slots(state, event_entry)


def _offer_date_slots(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Offer available site visit dates WITH their time slots in one message.

    This is a UX improvement: instead of asking for date first, then time,
    we show all available date+time combinations upfront so the client
    can pick in one go.
    """
    sv_state = get_site_visit_state(event_entry)
    blocked_dates = _get_blocked_dates(event_entry)

    # Generate dates with their available time slots
    date_time_slots = _generate_date_time_slots(event_entry, blocked_dates)
    sv_state["proposed_dates"] = list(date_time_slots.keys())
    # Store all proposed slots for validation
    all_proposed_slots: List[str] = []
    for date_iso, times in date_time_slots.items():
        for time in times:
            all_proposed_slots.append(f"{date_iso} at {time}")
    sv_state["proposed_slots"] = all_proposed_slots

    # Format for display
    slot_lines = []
    for date_iso, times in date_time_slots.items():
        try:
            year, month, day = map(int, date_iso.split("-"))
            formatted_date = f"{day:02d}.{month:02d}.{year}"
        except (ValueError, IndexError):
            formatted_date = date_iso
        times_str = ", ".join(times)
        slot_lines.append(f"- **{formatted_date}**: {times_str}")

    slot_list = "\n".join(slot_lines)
    body = (
        f"I'd be happy to arrange a site visit for you. "
        f"Here are the available dates and time slots:\n\n{slot_list}\n\n"
        f"Please let me know which date and time works best for you "
        f"(e.g., 'August 4th at 14:00')."
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_date_selection",
        next_step="Pick a visit slot",
        requires_approval=True,
    )


def _check_date_conflict(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    requested_date: str,
) -> GroupResult:
    """Check if requested date/time has a conflict.

    Checks two levels of conflicts:
    1. Date blocked entirely (event day) - hard block
    2. Specific time slot already booked - offer alternative times
    """
    blocked_dates = _get_blocked_dates(event_entry)
    booked_slots = _get_booked_site_visit_slots(event_entry)

    # Parse date and time
    date_iso, time_slot = parse_slot_string(requested_date)
    if not date_iso:
        date_iso = requested_date  # Fallback to raw string
    if not time_slot:
        time_slot = "10:00"  # Default time

    # Check for date blocked entirely (event day)
    if date_iso in blocked_dates:
        return _date_conflict_response(state, event_entry, requested_date)

    # Check for specific slot already booked
    if (date_iso, time_slot) in booked_slots:
        return _slot_conflict_response(state, event_entry, requested_date, date_iso, time_slot, booked_slots)

    # No conflict - ask for explicit confirmation
    pending_slot = requested_date if " at " in requested_date else f"{requested_date} at {time_slot}"
    set_pending_confirmation(event_entry, pending_slot)
    return _ask_for_confirmation(state, event_entry, pending_slot)


def _date_conflict_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    requested_date: str,
) -> GroupResult:
    """Response when requested date conflicts with an event (hard block).

    Offers alternative DATES (not times) to keep the 2-step flow consistent.
    Stay in date_pending state so client can pick another date.
    """
    sv_state = get_site_visit_state(event_entry)
    blocked_dates = _get_blocked_dates(event_entry)

    # Generate alternative dates (staying in date_pending)
    dates = _generate_available_dates(event_entry, blocked_dates)
    sv_state["proposed_dates"] = dates

    # Format dates for display
    date_list = []
    for date_iso in dates:
        try:
            year, month, day = map(int, date_iso.split("-"))
            date_list.append(f"- **{day:02d}.{month:02d}.{year}**")
        except (ValueError, IndexError):
            date_list.append(f"- **{date_iso}**")

    formatted_dates = "\n".join(date_list)
    body = (
        f"I regret to inform you that **{requested_date}** is booked for an event, "
        f"so site visits won't be possible then.\n\n"
        f"However, here are some alternative dates:\n{formatted_dates}\n\n"
        f"Which date works best for you? Once you select a date, I can provide the available time slots."
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_date_conflict",
        next_step="Pick a visit date",
        requires_approval=True,
    )


def _slot_conflict_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    requested_date: str,
    date_iso: str,
    time_slot: str,
    booked_slots: Set[tuple[str, str]],
) -> GroupResult:
    """Response when specific time slot is already booked.

    Unlike date conflicts (hard block), slot conflicts offer alternative times
    on the same day or nearby days.
    """
    sv_state = get_site_visit_state(event_entry)
    blocked_dates = _get_blocked_dates(event_entry)
    times = get_site_visit_slots()

    # Find alternative times on the same day
    same_day_alternatives: List[str] = []
    for hour in times:
        alt_time = f"{hour:02d}:00"
        if alt_time != time_slot and (date_iso, alt_time) not in booked_slots:
            try:
                dt = datetime.fromisoformat(date_iso)
                same_day_alternatives.append(dt.strftime("%d.%m.%Y") + f" at {alt_time}")
            except ValueError:
                same_day_alternatives.append(f"{date_iso} at {alt_time}")

    # Generate slots on other days
    other_day_slots = _generate_visit_slots(event_entry, blocked_dates, booked_slots)

    # Combine: prioritize same day alternatives, then other days
    all_alternatives = same_day_alternatives[:2] + [
        s for s in other_day_slots if s not in same_day_alternatives
    ][:3]
    sv_state["proposed_slots"] = all_alternatives

    slot_list = "\n".join(f"- {slot}" for slot in all_alternatives)
    date_display = requested_date.split(" at ")[0] if " at " in requested_date else requested_date

    # NOTE: This is a SITE VISIT slot conflict, not a room/event conflict.
    # The date mentioned here is the site visit date, not the main event date.
    if same_day_alternatives:
        body = (
            f"The **{time_slot}** site visit slot on **{date_display}** is already reserved "
            f"by another client, but other times are available that day.\n\n"
            f"Here are some alternative site visit times:\n\n{slot_list}\n\n"
            f"Would any of these work for your venue tour?"
        )
    else:
        body = (
            f"Unfortunately, the site visit slot on **{requested_date}** is already reserved "
            f"by another client.\n\n"
            f"Here are some alternative times for your venue tour:\n\n{slot_list}\n\n"
            f"Would any of these work for you?"
        )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_slot_conflict",
        next_step="Pick a visit slot",
        requires_approval=False,
    )


def _is_event_date_change_request(message_text: str) -> bool:
    """Check if message is requesting an EVENT date change (not site visit date).

    When in site visit date_pending state, we need to distinguish between:
    1. Site visit date selection: "Tuesday at 2pm", "the first one", "15.04.2026"
    2. Event date change: "change the date to...", "actually, different date for the event"

    Returns True if this is an EVENT date change request that should bypass
    the site visit handler and go through normal change propagation.
    """
    text_lower = message_text.lower()

    # Event date change signals (regex patterns)
    event_date_patterns = [
        r"\b(change|switch|move)\s+(the\s+)?(event\s+)?(date|booking|reservation)\b",
        r"\bevent\s+date\b",
        r"\bbooking\s+date\b",
        r"\breservation\s+date\b",
        r"\bactually[,.]?\s*(i|we)?\s*(need|want|prefer|would\s+like)\s+(a\s+)?(different|another|new)\s+date\b",
        r"\b(change|reschedule)\s+(the\s+)?event\b",
        r"\bdate\s+of\s+(the\s+)?(event|booking|meeting|conference)\b",
        r"\b(instead|rather)\b.*\bdate\b",
    ]

    if any(re.search(p, text_lower) for p in event_date_patterns):
        return True

    # Check for change verb + date keyword without site visit context
    change_verbs = {"change", "switch", "move", "reschedule", "modify"}
    site_visit_keywords = {"site visit", "visit", "tour", "viewing", "walkthrough", "besichtigung"}
    date_keywords = {
        "date", "day", "april", "may", "june", "july", "august", "september",
        "october", "november", "december", "january", "february", "march"
    }

    has_change_verb = any(verb in text_lower for verb in change_verbs)
    has_site_visit_keyword = any(kw in text_lower for kw in site_visit_keywords)
    has_date_keyword = any(kw in text_lower for kw in date_keywords)

    return has_change_verb and has_date_keyword and not has_site_visit_keyword


def _handle_date_selection(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> Optional[GroupResult]:
    """Handle client's date selection for site visit (step 1 of 2-step).

    When in date_pending state, dates are interpreted as site visit dates UNLESS
    the message clearly indicates an EVENT date change request.

    After date selection, transitions to time_pending state to offer time slots.

    Returns:
        GroupResult if site visit date handled, None if this is an event date change
        that should be handled by normal workflow.
    """
    sv_state = get_site_visit_state(event_entry)
    proposed_dates = sv_state.get("proposed_dates", [])
    proposed_slots = sv_state.get("proposed_slots", [])  # Full "date at time" slots
    message_text = (state.message.body or "").strip()

    logger.debug("[SV_DATE_SEL] Entry: proposed_dates=%s", proposed_dates)

    # GUARD: Check if this is actually an EVENT date change request
    is_event_change = _is_event_date_change_request(message_text)
    if is_event_change:
        from workflows.common.site_visit_state import reset_site_visit_state
        reset_site_visit_state(event_entry)
        state.extras["persist"] = True
        return None  # Let normal workflow handle event date change

    # Try to parse date AND time together (new combined flow)
    selected_date, selected_time = _parse_date_time_selection(message_text, proposed_dates, proposed_slots)

    # If no date found, try legacy date-only parsing
    if not selected_date:
        selected_date = _parse_date_selection(message_text, proposed_dates)

    if not selected_date:
        # Try from detection (LLM-extracted)
        if detection and detection.site_visit_date:
            selected_date, _ = parse_slot_string(detection.site_visit_date)
            # Use LLM-extracted time if available (handles "14:00", "2pm", "afternoon")
            if detection.site_visit_time and not selected_time:
                selected_time = detection.site_visit_time
        elif detection and detection.date:
            selected_date, _ = parse_slot_string(detection.date)
            # Also check for time from detection
            if detection.site_visit_time and not selected_time:
                selected_time = detection.site_visit_time

    if not selected_date:
        # Try extracting from message
        extracted = _extract_date_from_message(message_text)
        if extracted:
            selected_date, extracted_time = parse_slot_string(extracted)
            if extracted_time and not selected_time:
                selected_time = extracted_time

    logger.debug("[SV_DATE_SEL] Final: date=%s, time=%s", selected_date, selected_time)
    if not selected_date:
        return _ask_for_date_clarification(state, event_entry)

    # Check for conflicts
    blocked_dates = _get_blocked_dates(event_entry)
    if selected_date in blocked_dates:
        return _date_conflict_response(state, event_entry, selected_date)

    # Get available time slots for this date
    time_slots = _generate_time_slots_for_date(event_entry, selected_date)

    if not time_slots:
        # No time slots available on this date (all booked)
        return _date_conflict_response(state, event_entry, selected_date)

    # If we have both date AND time, go directly to confirmation
    if selected_time and selected_time in time_slots:
        try:
            year, month, day = map(int, selected_date.split("-"))
            formatted_date = f"{day:02d}.{month:02d}.{year}"
        except (ValueError, IndexError):
            formatted_date = selected_date

        # Schedule the visit directly
        set_site_visit_date(event_entry, selected_date, selected_time)
        selected_slot = f"{formatted_date} at {selected_time}"
        return _confirm_site_visit(state, event_entry, selected_slot)

    # Only date selected - transition to time_pending and offer time slots
    set_time_pending(event_entry, selected_date, time_slots)
    return _offer_time_slots(state, event_entry, selected_date, time_slots)


def _ask_for_date_clarification(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Ask for clarification when date selection wasn't understood."""
    body = (
        "I couldn't determine which date you'd prefer. "
        "Could you please specify when you'd like to visit? "
        "For example: 'Next Tuesday' or 'January 15th'."
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_date_clarification",
        next_step="Pick a visit date",
        requires_approval=True,
    )


def _parse_date_selection(message_text: str, proposed_dates: List[str]) -> Optional[str]:
    """Parse which date the client selected from their message.

    Args:
        message_text: Client's message
        proposed_dates: List of ISO date strings that were offered

    Returns:
        Selected date in ISO format, or None if not found
    """
    lowered = message_text.lower()

    # Check for ordinal selection ("first", "second", "third")
    ordinals = [
        ("first", 0), ("1st", 0), ("one", 0),
        ("second", 1), ("2nd", 1), ("two", 1),
        ("third", 2), ("3rd", 2), ("three", 2),
    ]
    for word, idx in ordinals:
        if word in lowered and idx < len(proposed_dates):
            return proposed_dates[idx]

    # Check if message contains any of the proposed dates
    for date_iso in proposed_dates:
        # Convert ISO to DD.MM.YYYY for matching
        try:
            year, month, day = map(int, date_iso.split("-"))
            formatted = f"{day:02d}.{month:02d}.{year}"
            if formatted in message_text or date_iso in message_text:
                return date_iso
            # Also check short forms like "9th" for day 9
            day_ordinals = [f"{day}st", f"{day}nd", f"{day}rd", f"{day}th", str(day)]
            if any(do in lowered for do in day_ordinals):
                return date_iso
        except (ValueError, IndexError):
            continue

    # Generic confirmation = first option
    confirm_words = ("yes", "proceed", "ok", "confirm", "sounds good", "perfect", "ja", "bitte")
    if any(word in lowered for word in confirm_words) and proposed_dates:
        return proposed_dates[0]

    return None


def _parse_date_time_selection(
    message_text: str,
    proposed_dates: List[str],
    proposed_slots: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Parse both date AND time from a combined selection message.

    Handles messages like:
    - "August 4th at 14:00"
    - "04.08 at 10:00"
    - "the second option at 14:00"
    - "first date, afternoon slot"

    Args:
        message_text: Client's message
        proposed_dates: List of ISO date strings that were offered
        proposed_slots: List of "YYYY-MM-DD at HH:MM" strings that were offered

    Returns:
        Tuple of (date_iso, time_str) - either or both may be None
    """
    import re
    lowered = message_text.lower()

    # First, try to match against the full proposed_slots ("2026-08-04 at 14:00")
    for slot in proposed_slots:
        if " at " in slot:
            date_part, time_part = slot.split(" at ", 1)
            # Check if the slot is mentioned in the message
            # Convert date to various formats for matching
            try:
                year, month, day = map(int, date_part.split("-"))
                formatted = f"{day:02d}.{month:02d}.{year}"
                formatted_short = f"{day:02d}.{month:02d}"
                # Match patterns like "04.08 at 14:00" or "04.08.2026 at 14:00"
                if (formatted in message_text or formatted_short in message_text) and time_part in message_text:
                    return date_part, time_part
            except (ValueError, IndexError):
                continue

    # Try to parse time first, then associate with date
    # IMPORTANT: Require colon/dot separator to avoid matching day numbers as times
    # (e.g., "May 13 at 14:00" should extract 14:00, not 13:00)
    extracted_time = None

    # First try: times with explicit separator (14:00, 14.00)
    time_with_sep_pattern = r'\b(\d{1,2})[:\.](\d{2})\b'
    time_match = re.search(time_with_sep_pattern, lowered)
    if time_match:
        hour = int(time_match.group(1))
        if 8 <= hour <= 20:  # Reasonable site visit hours
            extracted_time = f"{hour:02d}:00"
    else:
        # Fallback: "at N" or "um N" pattern (for "at 14", "um 10 Uhr")
        time_indicator_pattern = r'(?:at|um)\s+(\d{1,2})\s*(?:uhr|h)?'
        time_match = re.search(time_indicator_pattern, lowered)
        if time_match:
            hour = int(time_match.group(1))
            if 8 <= hour <= 20:  # Reasonable site visit hours
                extracted_time = f"{hour:02d}:00"

    # Try ordinal selection with time
    ordinals = [
        ("first", 0), ("1st", 0), ("one", 0), ("erste", 0),
        ("second", 1), ("2nd", 1), ("two", 1), ("zweite", 1),
        ("third", 2), ("3rd", 2), ("three", 2), ("dritte", 2),
    ]

    # Check for ordinal date reference
    selected_date_idx = None
    for word, idx in ordinals:
        if word in lowered and idx < len(proposed_dates):
            selected_date_idx = idx
            break

    if selected_date_idx is not None:
        selected_date = proposed_dates[selected_date_idx]
        return selected_date, extracted_time

    # Try to find date from message (DD.MM or month name)
    # Check for DD.MM.YYYY or DD.MM format
    date_pattern = r'\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b'
    date_match = re.search(date_pattern, message_text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else None
        # Find matching proposed date
        for date_iso in proposed_dates:
            y, m, d = map(int, date_iso.split("-"))
            if d == day and m == month:
                if year is None or y == year:
                    return date_iso, extracted_time

    # Check for month names (English and German)
    month_names = {
        "january": 1, "jan": 1, "januar": 1,
        "february": 2, "feb": 2, "februar": 2,
        "march": 3, "mar": 3, "märz": 3, "maerz": 3,
        "april": 4, "apr": 4,
        "may": 5, "mai": 5,
        "june": 6, "jun": 6, "juni": 6,
        "july": 7, "jul": 7, "juli": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "oktober": 10, "okt": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12, "dezember": 12, "dez": 12,
    }

    for month_name, month_num in month_names.items():
        if month_name in lowered:
            # Look for day number near month
            day_pattern = rf'(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(?:of\s*)?{month_name}|{month_name}\s*(\d{{1,2}})'
            day_match = re.search(day_pattern, lowered)
            if day_match:
                day = int(day_match.group(1) or day_match.group(2))
                # Find matching proposed date
                for date_iso in proposed_dates:
                    y, m, d = map(int, date_iso.split("-"))
                    if d == day and m == month_num:
                        return date_iso, extracted_time

    # If only time extracted but no date, return (None, time)
    return None, extracted_time


def _offer_time_slots(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    selected_date: str,
    time_slots: List[str],
) -> GroupResult:
    """Offer available time slots for the selected date (step 2 of 2-step)."""
    # Format date for display
    try:
        year, month, day = map(int, selected_date.split("-"))
        formatted_date = f"{day:02d}.{month:02d}.{year}"
    except (ValueError, IndexError):
        formatted_date = selected_date

    slot_list = "\n".join(f"- {slot}" for slot in time_slots)
    body = (
        f"Great! Here are the available time slots on **{formatted_date}**:\n\n"
        f"{slot_list}\n\n"
        f"Which time works best for you?"
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_time_selection",
        next_step="Pick a visit time",
        requires_approval=True,
    )


def _handle_time_selection(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> Optional[GroupResult]:
    """Handle client's time slot selection (step 2 of 2-step).

    After time selection, transitions to confirm_pending state.
    """
    sv_state = get_site_visit_state(event_entry)
    selected_date = sv_state.get("selected_date")
    proposed_times = sv_state.get("proposed_slots", [])
    message_text = (state.message.body or "").strip()

    logger.debug("[SV_TIME_SEL] Entry: selected_date=%s, proposed_times=%s",
                 selected_date, proposed_times)

    if not selected_date:
        # Lost state - restart flow
        from workflows.common.site_visit_state import reset_site_visit_state
        reset_site_visit_state(event_entry)
        return _offer_date_slots(state, event_entry)

    # Try to find selected time from message
    selected_time = _parse_time_selection(message_text, proposed_times)

    if not selected_time:
        # Try from detection
        if detection and detection.site_visit_date:
            _, selected_time = parse_slot_string(detection.site_visit_date)

    if not selected_time:
        return _ask_for_time_clarification(state, event_entry, selected_date, proposed_times)

    # Validate that the time slot is still available
    booked_slots = _get_booked_site_visit_slots(event_entry)
    if (selected_date, selected_time) in booked_slots:
        # Slot was booked in the meantime - offer remaining times
        available_times = _generate_time_slots_for_date(event_entry, selected_date)
        if not available_times:
            # All times booked - go back to date selection
            return _date_conflict_response(state, event_entry, selected_date)
        set_time_pending(event_entry, selected_date, available_times)
        return _offer_time_slots(state, event_entry, selected_date, available_times)

    # Time is valid - confirm immediately (client already confirmed by selecting)
    # No need to ask again - they explicitly chose this time slot
    try:
        year, month, day = map(int, selected_date.split("-"))
        formatted_date = f"{day:02d}.{month:02d}.{year}"
    except (ValueError, IndexError):
        formatted_date = selected_date

    # Schedule the visit directly
    set_site_visit_date(event_entry, selected_date, selected_time)
    selected_slot = f"{formatted_date} at {selected_time}"
    return _confirm_site_visit(state, event_entry, selected_slot)


def _parse_time_selection(message_text: str, proposed_times: List[str]) -> Optional[str]:
    """Parse which time slot the client selected from their message."""
    lowered = message_text.lower()

    # Check for ordinal selection
    ordinals = [
        ("first", 0), ("1st", 0), ("one", 0),
        ("second", 1), ("2nd", 1), ("two", 1),
        ("third", 2), ("3rd", 2), ("three", 2),
    ]
    for word, idx in ordinals:
        if word in lowered and idx < len(proposed_times):
            return proposed_times[idx]

    # Check if message contains any of the proposed times
    for time_slot in proposed_times:
        if time_slot in message_text:
            return time_slot
        # Check without leading zero (e.g., "10:00" or "10")
        hour = time_slot.split(":")[0]
        if hour in lowered:
            return time_slot

    # Check for time keywords
    time_keywords = {
        "morning": ["09:00", "10:00", "11:00"],
        "afternoon": ["14:00", "15:00", "16:00"],
        "evening": ["17:00", "18:00"],
    }
    for keyword, times in time_keywords.items():
        if keyword in lowered:
            for t in times:
                if t in proposed_times:
                    return t

    # Generic confirmation = first option
    confirm_words = ("yes", "proceed", "ok", "confirm", "sounds good", "perfect", "ja", "bitte")
    if any(word in lowered for word in confirm_words) and proposed_times:
        return proposed_times[0]

    return None


def _ask_for_time_clarification(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    selected_date: str,
    proposed_times: List[str],
) -> GroupResult:
    """Ask for clarification when time selection wasn't understood."""
    # Format date for display
    try:
        year, month, day = map(int, selected_date.split("-"))
        formatted_date = f"{day:02d}.{month:02d}.{year}"
    except (ValueError, IndexError):
        formatted_date = selected_date

    slot_list = "\n".join(f"- {slot}" for slot in proposed_times)
    body = (
        f"I couldn't determine which time you'd prefer. "
        f"Please choose one of the available times on {formatted_date}:\n\n"
        f"{slot_list}"
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_time_clarification",
        next_step="Pick a visit time",
        requires_approval=True,
    )


def _ask_for_confirmation(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    pending_slot: str,
) -> GroupResult:
    """Ask client to explicitly confirm the proposed site visit slot.

    This is the confirmation gate - we never auto-confirm site visits.
    """
    body = (
        f"I've checked and **{pending_slot}** is available for your site visit. "
        f"Would you like me to confirm this slot for you?"
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_confirm_pending",
        next_step="Confirm visit slot",
        requires_approval=False,  # Routine question, no HIL needed
    )


def _handle_confirmation_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult] = None,
) -> Optional[GroupResult]:
    """Handle client's response to confirmation prompt.

    If client confirms (yes, ok, confirm, etc.) -> schedule the visit.
    If client declines or wants different slot -> offer alternatives.
    """
    message_text = (state.message.body or "").strip().lower()
    sv_state = get_site_visit_state(event_entry)
    pending_slot = sv_state.get("pending_slot") or ""

    # Check for positive confirmation
    confirm_patterns = [
        r"\b(yes|yeah|yep|ja|si|oui)\b",
        r"\b(ok|okay|sure|fine|good|great|perfect)\b",
        r"\b(confirm|confirmed|book\s+it|let'?s\s+do\s+it)\b",
        r"\b(sounds\s+good|works\s+for\s+me|that\s+works)\b",
        r"\b(please\s+confirm|go\s+ahead|proceed)\b",
        r"\b(einverstanden|bestätigen|passt)\b",  # German
    ]
    is_confirmation = any(re.search(p, message_text) for p in confirm_patterns)

    # Check for decline or change request
    decline_patterns = [
        r"\b(no|nope|nein|non)\b",
        r"\b(different|another|other)\s+(date|time|slot)\b",
        r"\b(change|reschedule|not\s+that)\b",
        r"\b(doesn'?t|won'?t|can'?t)\s+work\b",
        r"\b(actually|rather)\b",
    ]
    is_decline = any(re.search(p, message_text) for p in decline_patterns)

    if is_confirmation and not is_decline:
        # Client confirmed - schedule the visit
        if confirm_pending_site_visit(event_entry):
            return _confirm_site_visit(state, event_entry, pending_slot)
        # Fallback: manually set the date
        confirmed_date, confirmed_time = parse_slot_string(pending_slot)
        if confirmed_date:
            set_site_visit_date(event_entry, confirmed_date, confirmed_time)
            return _confirm_site_visit(state, event_entry, pending_slot)

    if is_decline:
        # Client wants different slot - restart date selection
        from workflows.common.site_visit_state import reset_site_visit_state
        reset_site_visit_state(event_entry)
        start_site_visit_flow(event_entry, event_entry.get("current_step", 3))
        return _offer_date_slots(state, event_entry)

    # Ambiguous response - ask for clarification
    body = (
        f"I'm not sure if you'd like to confirm **{pending_slot}** for your site visit. "
        f"Just say 'yes' to confirm, or let me know if you'd prefer a different time."
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_confirm_clarification",
        next_step="Confirm or choose different slot",
        requires_approval=False,
    )


def _confirm_site_visit(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    selected_slot: str,
) -> GroupResult:
    """Confirm the scheduled site visit."""
    current_step = event_entry.get("current_step", 3)
    append_audit_entry(event_entry, current_step, current_step, "site_visit_confirmed")

    # Check if client hasn't progressed to booking yet
    # (no room locked, no offer accepted, still in early steps)
    has_locked_room = event_entry.get("locked_room_id") is not None
    has_offer_accepted = event_entry.get("offer_accepted", False)
    in_booking_flow = has_locked_room or has_offer_accepted or current_step >= 5

    body = (
        f"Your site visit is confirmed for **{selected_slot}**. "
        f"We look forward to welcoming you and showing you our venue!"
    )

    # Add dynamic workflow reminder based on which step client left from
    if not in_booking_flow:
        sv_state = get_site_visit_state(event_entry)
        initiated_step = sv_state.get("initiated_at_step") or current_step

        # Map step number to client-friendly continuation prompt
        step_prompts = {
            2: "confirming your event date",
            3: "selecting a room",
            4: "reviewing your offer",
            5: "finalizing the negotiation",
            6: "completing the transition",
        }
        step_prompt = step_prompts.get(initiated_step, "booking your event")

        body += (
            f"\n\nWhenever you're ready to continue with {step_prompt}, "
            "just let me know!"
        )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_confirmed",
        next_step="Site visit scheduled",
        requires_approval=False,
    )


def _site_visit_already_scheduled(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> GroupResult:
    """Handle when site visit is already scheduled."""
    sv_state = get_site_visit_state(event_entry)
    date = sv_state.get("date_iso") or sv_state.get("confirmed_date")
    time_slot = sv_state.get("time_slot") or sv_state.get("confirmed_time")

    date_display = f"{date} at {time_slot}" if date and time_slot else date
    body = (
        f"You already have a site visit scheduled for **{date_display}**. "
        f"Would you like to reschedule?"
    )

    return _send_draft_response(
        state, event_entry, body,
        action="site_visit_already_scheduled",
        next_step="Confirm or reschedule",
        requires_approval=True,
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


def _get_booked_site_visit_slots(
    event_entry: Dict[str, Any],
    db: Optional[Dict[str, Any]] = None,
) -> Set[tuple[str, str]]:
    """Get already-booked site visit slots (per-slot availability).

    Returns a set of (date_iso, time_slot) tuples that are already booked
    OR pending confirmation. This prevents double-booking when another
    client is in the process of confirming a slot.

    Includes slots with status: "scheduled" OR "confirm_pending"

    Args:
        event_entry: Current event being processed
        db: Optional database dict (if None, loads from file)

    Returns:
        Set of (date_iso, time_slot) tuples that are booked or pending
    """
    booked_slots: Set[tuple[str, str]] = set()

    # Load database if not provided
    if db is None:
        db = _load_database()

    current_event_id = event_entry.get("event_id")

    # Query all events with scheduled OR pending site visits
    events = db.get("events", [])
    for event in events:
        # Skip current event
        if event.get("event_id") == current_event_id:
            continue

        # Check site visit state
        sv_state = event.get("site_visit_state", {})
        status = sv_state.get("status")

        # Include both scheduled and confirm_pending slots
        if status == "scheduled":
            date_iso = sv_state.get("date_iso") or sv_state.get("confirmed_date")
            time_slot = sv_state.get("time_slot") or sv_state.get("confirmed_time")

            if date_iso and time_slot:
                booked_slots.add((date_iso, time_slot))
            elif date_iso:
                # If no time slot, consider the default time slot booked
                booked_slots.add((date_iso, "10:00"))

        elif status == "confirm_pending":
            # Also block slots that are pending confirmation
            pending_slot = sv_state.get("pending_slot")
            if pending_slot:
                from workflows.common.site_visit_state import parse_slot_string
                date_iso, time_slot = parse_slot_string(pending_slot)
                if date_iso and time_slot:
                    booked_slots.add((date_iso, time_slot))

    return booked_slots


def _is_slot_available(
    date_iso: str,
    time_slot: str,
    blocked_dates: Set[str],
    booked_slots: Set[tuple[str, str]],
) -> bool:
    """Check if a specific date+time slot is available for site visit.

    Args:
        date_iso: Date in ISO format (YYYY-MM-DD)
        time_slot: Time slot (e.g., "10:00", "14:00")
        blocked_dates: Set of dates blocked for site visits (event days)
        booked_slots: Set of (date, time) tuples already booked

    Returns:
        True if the slot is available, False otherwise
    """
    # First check if the date is blocked entirely (event day)
    if date_iso in blocked_dates:
        return False

    # Then check if this specific slot is already booked
    if (date_iso, time_slot) in booked_slots:
        return False

    return True


def _has_any_room_available_for_slot(date_iso: str, time_slot: str) -> bool:
    """Check if any room is available (not Option/Confirmed) for a given time slot.

    Site visits are venue-wide, so we need at least one room to be "Available"
    (not booked, not with Option status) for the tour to make sense.

    Args:
        date_iso: Date in ISO format (YYYY-MM-DD)
        time_slot: Time slot (e.g., "10:00")

    Returns:
        True if at least one room is available, False if all rooms are busy/Option
    """
    from services.room_eval import evaluate_rooms

    # Create a minimal event entry to evaluate rooms for this date+time
    # Assume 2-hour site visit window
    hour = int(time_slot.split(":")[0])
    start_time = f"{hour:02d}:00"
    end_time = f"{(hour + 2) % 24:02d}:00"

    # Use timezone-aware ISO format with Zurich timezone offset (+01:00 or +02:00)
    # Using +00:00 (UTC) for simplicity since calendar uses UTC comparison
    fake_event = {
        "requirements": {},
        "requested_window": {
            "date_iso": date_iso,
            "start": f"{date_iso}T{start_time}:00+00:00",
            "end": f"{date_iso}T{end_time}:00+00:00",
        },
    }

    evaluations = evaluate_rooms(fake_event)
    # Check if at least one room is "Available"
    return any(e.status == "Available" for e in evaluations)


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_visit_slots(
    event_entry: Dict[str, Any],
    blocked_dates: Set[str],
    booked_slots: Optional[Set[tuple[str, str]]] = None,
) -> List[str]:
    """Generate available site visit slots.

    Slots are generated based on the event date:
    - If event date exists: base = event_date - 7 days (visit before event)
    - If no event date: base = today + 7 days

    Excludes blocked dates (event days) and already-booked site visit slots.
    """
    # Get booked slots if not provided
    if booked_slots is None:
        booked_slots = _get_booked_site_visit_slots(event_entry)

    # Get event date
    event_date_str = event_entry.get("chosen_date") or event_entry.get(
        "user_info", {}
    ).get("date")

    # Determine the base date for slot generation
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        if event_date_str:
            # Event date exists - base is event_date - 7 days
            if "." in event_date_str:
                day, month, year = map(int, event_date_str.split("."))
                event_date = datetime(year, month, day)
            else:
                event_date = datetime.fromisoformat(event_date_str.replace("Z", ""))
            base_date = event_date - timedelta(days=7)
        else:
            # No event date - base is today + 7 days
            base_date = today + timedelta(days=7)
            event_date = None  # No upper bound
    except (ValueError, IndexError):
        base_date = today + timedelta(days=7)
        event_date = None

    slots: List[str] = []

    # Load time slots from config (morning, early afternoon, late afternoon)
    times = get_site_visit_slots()

    # Load weekday preference and min days ahead from config
    weekdays_only = get_site_visit_weekdays_only()
    min_days_ahead = get_site_visit_min_days_ahead()

    # Search around the base date
    candidate = base_date

    for _ in range(60):  # Search up to 60 days
        # Ensure candidate is at least min_days_ahead from today
        if candidate < today + timedelta(days=min_days_ahead):
            candidate += timedelta(days=1)
            continue

        # If event date exists, ensure candidate is before it
        if event_date and candidate >= event_date:
            # Try going backwards from event_date - 1
            candidate = event_date - timedelta(days=1)
            if candidate < today + timedelta(days=min_days_ahead):
                break  # No valid dates before event
            continue

        # Check if date is blocked entirely (event day)
        candidate_iso = candidate.date().isoformat()
        if candidate_iso in blocked_dates:
            candidate += timedelta(days=1)
            continue

        # Check weekday requirement (configurable)
        if weekdays_only and candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            continue

        # Check each time slot for availability
        for hour in times:
            time_slot = f"{hour:02d}:00"
            # Check if this specific slot is booked
            if (candidate_iso, time_slot) in booked_slots:
                continue  # This slot is booked, try next time

            slot_dt = candidate.replace(hour=hour, minute=0)
            slots.append(slot_dt.strftime("%d.%m.%Y at %H:%M"))
            if len(slots) >= 3:
                break

        if len(slots) >= 3:
            break

        candidate += timedelta(days=1)

    return slots


def _generate_date_time_slots(
    event_entry: Dict[str, Any],
    blocked_dates: Set[str],
    max_dates: int = 3,
) -> Dict[str, List[str]]:
    """Generate available dates WITH their time slots for site visit.

    Returns a dict of date_iso -> [available_times] for display in one message.
    This is a UX improvement to avoid requiring two separate selections.

    Args:
        event_entry: Current event being processed
        blocked_dates: Set of dates blocked for site visits
        max_dates: Maximum number of dates to return (default 3)

    Returns:
        Dict mapping ISO dates to lists of available time slots
        Example: {"2026-08-04": ["10:00", "14:00", "16:00"], "2026-08-05": ["10:00"]}
    """
    booked_slots = _get_booked_site_visit_slots(event_entry)

    # Get event date
    event_date_str = event_entry.get("chosen_date") or event_entry.get(
        "user_info", {}
    ).get("date")

    # Determine the base date
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        if event_date_str:
            if "." in event_date_str:
                day, month, year = map(int, event_date_str.split("."))
                event_date = datetime(year, month, day)
            else:
                event_date = datetime.fromisoformat(event_date_str.replace("Z", ""))
            base_date = event_date - timedelta(days=7)
        else:
            base_date = today + timedelta(days=7)
            event_date = None
    except (ValueError, IndexError):
        base_date = today + timedelta(days=7)
        event_date = None

    result: Dict[str, List[str]] = {}
    times = get_site_visit_slots()
    weekdays_only = get_site_visit_weekdays_only()
    min_days_ahead = get_site_visit_min_days_ahead()

    candidate = base_date

    for _ in range(60):
        if candidate < today + timedelta(days=min_days_ahead):
            candidate += timedelta(days=1)
            continue

        if event_date and candidate >= event_date:
            candidate = event_date - timedelta(days=1)
            if candidate < today + timedelta(days=min_days_ahead):
                break
            continue

        candidate_iso = candidate.date().isoformat()

        if candidate_iso in blocked_dates:
            candidate += timedelta(days=1)
            continue

        if weekdays_only and candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            continue

        # Collect available time slots for this date
        # A slot is available if: (1) not already booked, (2) at least one room is free
        available_times: List[str] = []
        for hour in times:
            time_slot = f"{hour:02d}:00"
            if (candidate_iso, time_slot) in booked_slots:
                continue
            # Check if any room is available at this time
            if not _has_any_room_available_for_slot(candidate_iso, time_slot):
                continue
            available_times.append(time_slot)

        if available_times:
            result[candidate_iso] = available_times
            if len(result) >= max_dates:
                break

        candidate += timedelta(days=1)

    return result


def _generate_available_dates(
    event_entry: Dict[str, Any],
    blocked_dates: Set[str],
) -> List[str]:
    """Generate available DATES for site visit (without times).

    Returns a list of ISO date strings (YYYY-MM-DD).
    Used for step 1 of 2-step selection (date → time → confirm).
    """
    booked_slots = _get_booked_site_visit_slots(event_entry)

    # Get event date
    event_date_str = event_entry.get("chosen_date") or event_entry.get(
        "user_info", {}
    ).get("date")

    # Determine the base date
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        if event_date_str:
            if "." in event_date_str:
                day, month, year = map(int, event_date_str.split("."))
                event_date = datetime(year, month, day)
            else:
                event_date = datetime.fromisoformat(event_date_str.replace("Z", ""))
            base_date = event_date - timedelta(days=7)
        else:
            base_date = today + timedelta(days=7)
            event_date = None
    except (ValueError, IndexError):
        base_date = today + timedelta(days=7)
        event_date = None

    dates: List[str] = []
    times = get_site_visit_slots()
    weekdays_only = get_site_visit_weekdays_only()
    min_days_ahead = get_site_visit_min_days_ahead()

    candidate = base_date

    for _ in range(60):
        if candidate < today + timedelta(days=min_days_ahead):
            candidate += timedelta(days=1)
            continue

        if event_date and candidate >= event_date:
            candidate = event_date - timedelta(days=1)
            if candidate < today + timedelta(days=min_days_ahead):
                break
            continue

        candidate_iso = candidate.date().isoformat()

        if candidate_iso in blocked_dates:
            candidate += timedelta(days=1)
            continue

        if weekdays_only and candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            continue

        # Check if at least one time slot is available on this date
        has_available_slot = False
        for hour in times:
            time_slot = f"{hour:02d}:00"
            if (candidate_iso, time_slot) not in booked_slots:
                has_available_slot = True
                break

        if has_available_slot:
            dates.append(candidate_iso)
            if len(dates) >= 3:
                break

        candidate += timedelta(days=1)

    return dates


def _generate_time_slots_for_date(
    event_entry: Dict[str, Any],
    date_iso: str,
) -> List[str]:
    """Generate available time slots for a specific date.

    Returns list of time strings like ["10:00", "14:00", "16:00"].
    Used for step 2 of 2-step selection.

    A slot is available if:
    1. It's not already booked as a site visit
    2. At least one room is available (not Option/Confirmed) at that time
    """
    booked_slots = _get_booked_site_visit_slots(event_entry)
    times = get_site_visit_slots()

    available_times: List[str] = []
    for hour in times:
        time_slot = f"{hour:02d}:00"
        if (date_iso, time_slot) in booked_slots:
            continue
        # Check if any room is available at this time
        if not _has_any_room_available_for_slot(date_iso, time_slot):
            continue
        available_times.append(time_slot)

    return available_times


def _extract_date_from_message(message_text: str) -> Optional[str]:
    """Extract a date from message text using regex patterns.

    This is a fallback when detection doesn't extract the date.
    Returns format like "15.02.2026 at 10:00" or just "15.02.2026".
    """
    # Try DD.MM.YYYY format
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", message_text)
    if match:
        day, month, year = match.groups()
        date_str = f"{int(day):02d}.{int(month):02d}.{year}"

        # Check for optional time
        time_match = re.search(r"at\s+(\d{1,2}[:.]\d{2})", message_text, re.IGNORECASE)
        if time_match:
            time_str = time_match.group(1).replace(".", ":")
            return f"{date_str} at {time_str}"
        return date_str

    # Try ISO format (YYYY-MM-DD)
    match = re.search(r"\d{4}-\d{2}-\d{2}", message_text)
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


def _base_payload(state: WorkflowState, event_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Build base payload for GroupResult."""
    return {
        "event_id": event_entry.get("id") or state.event_id,
        "current_step": event_entry.get("current_step"),
        "thread_state": state.thread_state,
        "site_visit_state": event_entry.get("site_visit_state", {}),
    }


def is_site_visit_intent(detection: Optional[UnifiedDetectionResult]) -> bool:
    """Check if detection result indicates a site visit booking intent.

    Only `site_visit_request` triggers the booking flow.
    `site_visit_overview` (info questions like "do you offer tours?") should be
    handled as Q&A, not scheduling.
    """
    if not detection:
        return False

    # Only site_visit_request triggers booking (not site_visit_overview)
    if "site_visit_request" in detection.qna_types:
        return True

    # Step anchor "Site Visit" also indicates booking intent
    if detection.step_anchor == "Site Visit":
        return True

    return False


__all__ = [
    "handle_site_visit_request",
    "is_site_visit_intent",
    "set_db_loader",
    "_get_blocked_dates",  # Exported for testing
]
