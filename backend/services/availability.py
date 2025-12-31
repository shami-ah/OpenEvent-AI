from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.adapters.calendar_adapter import get_calendar_adapter
from backend.services.rooms import get_room
from backend.workflows.io.config_store import get_timezone, get_operating_hours

# Dynamic venue configuration (fetched from database)
def _get_default_timezone() -> str:
    return get_timezone()

def _get_operating_hours() -> Tuple[int, int]:
    return get_operating_hours()

# Legacy constants for backward compatibility (use functions for dynamic values)
DEFAULT_TIMEZONE = "Europe/Zurich"  # Use _get_default_timezone() instead
OPERATING_START_HOUR = 8  # Use _get_operating_hours() instead
OPERATING_END_HOUR = 23


def parse_time_label(label: Optional[str]) -> Optional[time]:
    if not label:
        return None
    text = str(label).strip().replace(".", ":")
    if not text:
        return None
    if ":" not in text:
        if text.isdigit():
            text = f"{int(text) % 24:02d}:00"
        else:
            return None
    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def validate_window(
    date_iso: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    *,
    tz: Optional[str] = None,
    reference: Optional[date] = None,
) -> Tuple[bool, Optional[str]]:
    if not date_iso:
        return False, "Could you share a specific date and time you have in mind?"
    try:
        event_date = datetime.fromisoformat(date_iso).date()
    except ValueError:
        return False, "That date format looks unfamiliar—could you confirm the date?"
    today = reference or date.today()
    if event_date < today:
        return False, "That date is already in the past. Let me suggest a few upcoming options instead."

    start = parse_time_label(start_time)
    end = parse_time_label(end_time)
    if start and end:
        if start >= end:
            return False, "The end time needs to be after the start time. Happy to adjust the window."
        # Use dynamic operating hours from config
        op_start, op_end = _get_operating_hours()
        if start.hour < op_start or (end.hour >= op_end and end.minute > 0):
            return False, f"We host events between {op_start:02d}:00 and {op_end:02d}:00. Let me share some evening slots that work well."
    return True, None


def is_past(date_iso: Optional[str]) -> bool:
    if not date_iso:
        return True
    try:
        return datetime.fromisoformat(date_iso).date() < date.today()
    except ValueError:
        return True


def next_five_venue_dates(
    anchor: Optional[datetime] = None,
    *,
    tz: str = DEFAULT_TIMEZONE,
    count: int = 5,
    skip_dates: Optional[Iterable[date]] = None,
) -> List[str]:
    """
    Generate the next `count` venue dates (YYYY-MM-DD) starting from today or the anchor.
    Ensures no date returned is in the past.
    """

    excluded = {dt for dt in (skip_dates or [])}
    today = date.today()
    base_date = anchor.date() if anchor else today
    if base_date < today:
        base_date = today

    results: List[str] = []
    cursor = base_date
    while len(results) < count:
        if cursor not in excluded:
            results.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return results


def calendar_free(room_identifier: str, window: Dict[str, Any]) -> bool:
    record = get_room(room_identifier)
    if record is None:
        return True
    start_iso = window.get("start")
    end_iso = window.get("end")
    if not (start_iso and end_iso):
        return True
    calendar_id = record.calendar_id
    if not calendar_id:
        return True
    adapter = get_calendar_adapter()
    busy = adapter.get_busy(calendar_id, start_iso, end_iso)
    return not _has_overlap(start_iso, end_iso, busy)


def _has_overlap(start_iso: str, end_iso: str, busy_list: List[Dict[str, str]]) -> bool:
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    for slot in busy_list:
        raw_start = slot.get("start")
        raw_end = slot.get("end")
        if not raw_start or not raw_end:
            continue
        try:
            slot_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            slot_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
        except ValueError:
            continue
        if slot_end <= start_dt or end_dt <= slot_start:
            continue
        return True
    return False