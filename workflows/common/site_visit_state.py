"""Site Visit State Management.

Centralized state helpers for site visit booking flow.
Site visits can be initiated at ANY workflow step (2-7).

IMPORTANT: Site visits are VENUE-WIDE (not room-specific).
- Client visits the whole venue/selection
- No room_id needed in site visit state
- Manager configures available slots via site_visit_config

Conflict Rules:
- Site visits CANNOT be booked on event days (hard block)
- Events CAN be booked on site visit days (triggers manager notification)

State Structure:
    event_entry["site_visit_state"] = {
        "status": "idle" | "date_pending" | "scheduled" | "completed" | "cancelled",
        "date_iso": str | None,
        "time_slot": str | None,
        "proposed_slots": list[str],
        "initiated_at_step": int | None,
        "has_event_conflict": bool,
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


SiteVisitStatus = Literal[
    "idle",
    "date_pending",     # Awaiting client to select a DATE from proposed options
    "time_pending",     # Date selected, awaiting client to select a TIME slot
    "confirm_pending",  # Date+time validated, awaiting explicit client confirmation
    "scheduled",
    "completed",
    "cancelled",
]


class SiteVisitState(TypedDict, total=False):
    """TypedDict for site visit state structure (venue-wide, no room)."""

    status: SiteVisitStatus
    date_iso: Optional[str]           # Scheduled date (ISO format)
    time_slot: Optional[str]          # "10:00", "14:00", etc.
    proposed_slots: List[str]         # Offered time slots (legacy, now used for times)
    proposed_dates: List[str]         # Offered dates (ISO format) for date selection
    selected_date: Optional[str]      # Date selected by client (ISO), before time selection
    initiated_at_step: Optional[int]  # Which workflow step (2-7) triggered
    has_event_conflict: bool          # Event was booked on this date after
    # Confirmation gate fields
    pending_slot: Optional[str]       # Slot awaiting confirmation (e.g., "2026-01-20 at 10:00")
    # Legacy fields for backward compatibility
    confirmed_date: Optional[str]
    confirmed_time: Optional[str]
    scheduled_slot: Optional[str]
    # Deprecated room fields (kept for migration, always None)
    room_id: Optional[str]
    room_pending_decision: bool
    inherited_from_event: bool


def get_site_visit_state(event_entry: Dict[str, Any]) -> SiteVisitState:
    """Get or initialize site visit state from event entry."""
    default: SiteVisitState = {
        "status": "idle",
        "date_iso": None,
        "time_slot": None,
        "proposed_slots": [],
        "proposed_dates": [],
        "selected_date": None,
        "initiated_at_step": None,
        "has_event_conflict": False,
        "pending_slot": None,
        # Deprecated fields
        "room_id": None,
        "room_pending_decision": False,
        "inherited_from_event": False,
    }
    state = event_entry.setdefault("site_visit_state", default)
    # Ensure all keys exist (migration from old format)
    for key, val in default.items():
        state.setdefault(key, val)
    return state


def set_site_visit_status(event_entry: Dict[str, Any], status: SiteVisitStatus) -> None:
    """Update site visit status."""
    state = get_site_visit_state(event_entry)
    state["status"] = status


def is_site_visit_active(event_entry: Dict[str, Any]) -> bool:
    """Check if a site visit flow is currently active (awaiting date, time, or confirmation)."""
    state = event_entry.get("site_visit_state", {})
    status = state.get("status", "idle")
    # Note: "room_pending" kept for backward compat but should not occur
    return status in ("date_pending", "time_pending", "confirm_pending", "room_pending")


def is_site_visit_scheduled(event_entry: Dict[str, Any]) -> bool:
    """Check if site visit is already scheduled."""
    state = event_entry.get("site_visit_state", {})
    return state.get("status") == "scheduled"


def is_site_visit_change_request(message_text: str) -> bool:
    """Check if message is explicitly requesting to change a site visit.

    This is a RESTRICTIVE check to avoid interference with other detection.
    Only returns True when message EXPLICITLY mentions "site visit" + change intent.

    Examples that return True:
    - "change the site visit to next Monday"
    - "can we reschedule our site visit?"
    - "move the tour to 14:00"

    Examples that return False:
    - "change the date to March 15"  (no site visit mention)
    - "I'd like to visit on Monday"  (no change intent, just "visit")
    - "confirm the visit"  (no change intent)
    """
    text_lower = message_text.lower()

    # STRICT site visit keywords - must be explicit
    site_visit_explicit = [
        "site visit", "venue tour", "tour of", "venue visit",
        "walkthrough", "viewing", "besichtigung"
    ]
    # "visit" alone is too ambiguous - only count if with "the" before
    has_explicit_sv = any(kw in text_lower for kw in site_visit_explicit)
    has_the_visit = "the visit" in text_lower or "the tour" in text_lower

    if not (has_explicit_sv or has_the_visit):
        return False

    # STRICT change intent - must indicate rescheduling
    change_verbs = [
        "change", "reschedule", "move", "switch", "postpone",
        "different", "another time", "different time", "new time"
    ]
    has_change_intent = any(verb in text_lower for verb in change_verbs)

    return has_change_intent


def is_site_visit_pending_confirmation(event_entry: Dict[str, Any]) -> bool:
    """Check if site visit is awaiting explicit client confirmation."""
    state = event_entry.get("site_visit_state", {})
    return state.get("status") == "confirm_pending"


def is_site_visit_pending_time(event_entry: Dict[str, Any]) -> bool:
    """Check if site visit is awaiting time slot selection (date already selected)."""
    state = event_entry.get("site_visit_state", {})
    return state.get("status") == "time_pending"


def set_time_pending(
    event_entry: Dict[str, Any],
    selected_date: str,
    proposed_time_slots: List[str],
) -> None:
    """Set site visit to time_pending state after client selects a date.

    Called when the client has selected a date but still needs to pick a time slot.
    """
    state = get_site_visit_state(event_entry)
    state["status"] = "time_pending"
    state["selected_date"] = selected_date
    state["proposed_slots"] = proposed_time_slots


def set_pending_confirmation(
    event_entry: Dict[str, Any],
    pending_slot: str,
) -> None:
    """Set site visit to pending confirmation state.

    Called when a date/time has been validated but needs explicit client confirmation.
    The pending_slot is stored until the client confirms.
    """
    state = get_site_visit_state(event_entry)
    state["status"] = "confirm_pending"
    state["pending_slot"] = pending_slot


def confirm_pending_site_visit(event_entry: Dict[str, Any]) -> bool:
    """Confirm the pending site visit slot.

    Returns True if confirmation succeeded (was in confirm_pending state).
    Returns False if not in confirm_pending state or no pending slot.
    """
    state = get_site_visit_state(event_entry)
    if state.get("status") != "confirm_pending":
        return False

    pending_slot = state.get("pending_slot")
    if not pending_slot:
        return False

    # Parse pending_slot to extract date and time
    date_iso, time_slot = parse_slot_string(pending_slot)

    if not date_iso:
        return False

    state["date_iso"] = date_iso
    state["time_slot"] = time_slot
    state["status"] = "scheduled"
    state["pending_slot"] = None
    # Legacy compatibility
    state["confirmed_date"] = date_iso
    state["confirmed_time"] = time_slot
    return True


def parse_slot_string(slot_str: str) -> tuple[Optional[str], Optional[str]]:
    """Parse slot string to (date_iso, time_slot).

    Handles formats:
    - "2026-01-20 at 10:00" -> ("2026-01-20", "10:00")
    - "20.01.2026 at 10:00" -> ("2026-01-20", "10:00")
    - "2026-01-20" -> ("2026-01-20", None)
    - "20.01.2026" -> ("2026-01-20", None)

    This is the canonical date/time parser for site visit slots.
    Used by both state management and handler modules.
    """
    time_slot = None
    date_part = slot_str

    # Extract time if present
    if " at " in slot_str:
        date_part, time_part = slot_str.split(" at ", 1)
        time_slot = time_part.strip()

    date_part = date_part.strip()

    # Try DD.MM.YYYY format first (more common in user input)
    if "." in date_part:
        try:
            day, month, year = map(int, date_part.split("."))
            return f"{year:04d}-{month:02d}-{day:02d}", time_slot
        except (ValueError, IndexError):
            pass

    # Try ISO format (YYYY-MM-DD)
    if "-" in date_part and len(date_part) >= 10:
        return date_part[:10], time_slot

    return None, time_slot


def set_site_visit_date(
    event_entry: Dict[str, Any],
    date_iso: str,
    time_slot: Optional[str] = None,
) -> None:
    """Set the date for site visit and mark as scheduled."""
    state = get_site_visit_state(event_entry)
    state["date_iso"] = date_iso
    if time_slot:
        state["time_slot"] = time_slot
    state["status"] = "scheduled"
    # Legacy fields for backward compat
    state["confirmed_date"] = date_iso
    state["confirmed_time"] = time_slot

    # Log site visit activity for manager visibility
    from activity.persistence import log_workflow_activity
    display_date = f"{date_iso} {time_slot}" if time_slot else date_iso
    log_workflow_activity(event_entry, "site_visit_booked", date=display_date)


def start_site_visit_flow(
    event_entry: Dict[str, Any],
    initiated_at_step: Optional[int] = None,
) -> SiteVisitState:
    """Start a new site visit flow.

    Since site visits are venue-wide, we go directly to date selection.
    No room selection needed.
    """
    state = get_site_visit_state(event_entry)
    state["status"] = "date_pending"
    state["date_iso"] = None
    state["time_slot"] = None
    state["proposed_slots"] = []
    state["proposed_dates"] = []
    state["selected_date"] = None
    state["initiated_at_step"] = initiated_at_step
    state["has_event_conflict"] = False
    return state


def mark_site_visit_conflict(event_entry: Dict[str, Any]) -> None:
    """Mark that an event was booked on the site visit date (conflict)."""
    state = get_site_visit_state(event_entry)
    state["has_event_conflict"] = True


def complete_site_visit(event_entry: Dict[str, Any]) -> None:
    """Mark site visit as completed (actually happened)."""
    state = get_site_visit_state(event_entry)
    state["status"] = "completed"


def cancel_site_visit(event_entry: Dict[str, Any]) -> None:
    """Cancel the site visit."""
    state = get_site_visit_state(event_entry)
    state["status"] = "cancelled"


def reset_site_visit_state(event_entry: Dict[str, Any]) -> None:
    """Reset site visit state to idle."""
    state = get_site_visit_state(event_entry)
    state["status"] = "idle"
    state["date_iso"] = None
    state["time_slot"] = None
    state["proposed_slots"] = []
    state["initiated_at_step"] = None
    state["has_event_conflict"] = False
    state["pending_slot"] = None
    # Clear deprecated fields
    state["room_id"] = None
    state["room_pending_decision"] = False
    state["inherited_from_event"] = False


# =============================================================================
# Deprecated functions - kept for backward compatibility
# =============================================================================

def get_site_visit_room(event_entry: Dict[str, Any]) -> Optional[str]:
    """DEPRECATED: Site visits are venue-wide, no room needed.

    Kept for backward compatibility. Always returns None.
    """
    return None


def set_site_visit_room(
    event_entry: Dict[str, Any],
    room_id: str,
    inherited: bool = False,
) -> None:
    """DEPRECATED: Site visits are venue-wide, no room needed.

    Kept for backward compatibility. Does nothing.
    """
    pass


def get_default_room_for_site_visit(event_entry: Dict[str, Any]) -> Optional[str]:
    """DEPRECATED: Site visits are venue-wide, no room needed.

    Kept for backward compatibility. Always returns None.
    """
    return None


__all__ = [
    "SiteVisitState",
    "SiteVisitStatus",
    "get_site_visit_state",
    "set_site_visit_status",
    "is_site_visit_active",
    "is_site_visit_scheduled",
    "is_site_visit_pending_confirmation",
    "is_site_visit_pending_time",
    "set_time_pending",
    "set_pending_confirmation",
    "confirm_pending_site_visit",
    "parse_slot_string",
    "set_site_visit_date",
    "start_site_visit_flow",
    "mark_site_visit_conflict",
    "complete_site_visit",
    "cancel_site_visit",
    "reset_site_visit_state",
    # Deprecated (kept for backward compat)
    "get_site_visit_room",
    "set_site_visit_room",
    "get_default_room_for_site_visit",
]
