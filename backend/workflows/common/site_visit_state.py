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


SiteVisitStatus = Literal["idle", "date_pending", "scheduled", "completed", "cancelled"]


class SiteVisitState(TypedDict, total=False):
    """TypedDict for site visit state structure (venue-wide, no room)."""

    status: SiteVisitStatus
    date_iso: Optional[str]           # Scheduled date (ISO format)
    time_slot: Optional[str]          # "10:00", "14:00", etc.
    proposed_slots: List[str]         # Offered time slots
    initiated_at_step: Optional[int]  # Which workflow step (2-7) triggered
    has_event_conflict: bool          # Event was booked on this date after
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
        "initiated_at_step": None,
        "has_event_conflict": False,
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
    """Check if a site visit flow is currently active (awaiting date selection)."""
    state = event_entry.get("site_visit_state", {})
    status = state.get("status", "idle")
    # Note: "room_pending" kept for backward compat but should not occur
    return status in ("date_pending", "room_pending")


def is_site_visit_scheduled(event_entry: Dict[str, Any]) -> bool:
    """Check if site visit is already scheduled."""
    state = event_entry.get("site_visit_state", {})
    return state.get("status") == "scheduled"


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
