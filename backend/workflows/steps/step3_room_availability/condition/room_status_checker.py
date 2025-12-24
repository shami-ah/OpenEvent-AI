from __future__ import annotations

from typing import Any, Dict

__workflow_role__ = "condition"


def room_status_on_date(db: Dict[str, Any], date_ddmmyyyy: str | None, room_name: str) -> str:
    """[Condition] Derive the availability for a specific room on a given date."""

    if not date_ddmmyyyy:
        return "Unavailable"
    room_lc = room_name.lower()
    status_found = "Available"
    for event in db.get("events", []):
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        normalized = (data.get("Status") or "").lower()
        if normalized == "confirmed":
            return "Confirmed"
        if normalized in {"option", "lead"}:
            status_found = "Option"
    return status_found
