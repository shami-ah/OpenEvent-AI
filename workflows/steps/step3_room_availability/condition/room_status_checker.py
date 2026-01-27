from __future__ import annotations

from typing import Any, Dict, Optional

__workflow_role__ = "condition"


def room_status_on_date(
    db: Dict[str, Any],
    date_ddmmyyyy: str | None,
    room_name: str,
    *,
    exclude_event_id: Optional[str] = None,
) -> str:
    """[Condition] Derive the availability for a specific room on a given date.

    Checks booking status from the canonical event["status"] field.
    Falls back to event_data["Status"] for backward compatibility with legacy data.

    Args:
        db: Database dict with "events" list
        date_ddmmyyyy: Target date in DD.MM.YYYY format
        room_name: Room to check
        exclude_event_id: Event ID to exclude from conflict check (the current client's event).
                          This prevents a client's own booking from blocking themselves.

    Returns:
        "Available", "Option", or "Confirmed" based on other clients' bookings
    """

    if not date_ddmmyyyy:
        return "Unavailable"
    room_lc = room_name.lower()
    status_found = "Available"
    for event in db.get("events", []):
        # Skip the current client's event - they shouldn't conflict with themselves
        if exclude_event_id and event.get("event_id") == exclude_event_id:
            continue
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room") or event.get("locked_room_id")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        # Use canonical event["status"], fall back to event_data["Status"] for legacy
        # IMPORTANT: Only Option and Confirmed block rooms. Leads do NOT block.
        normalized = (event.get("status") or data.get("Status") or "").lower()
        if normalized == "confirmed":
            return "Confirmed"
        if normalized == "option":
            status_found = "Option"
    return status_found
