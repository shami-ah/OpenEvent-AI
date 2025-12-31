# backend/workflows/groups/intake/condition/checks.py
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from zoneinfo import ZoneInfo

from backend.workflows.io.config_store import get_timezone
from backend.workflows.conditions.checks import has_event_date as _has_event_date
from backend.workflows.conditions.checks import is_event_request as _is_event_request
from backend.workflows.steps.step3_room_availability.condition.decide import (
    room_status_on_date as _room_status_on_date,
)

__workflow_role__ = "condition"


def _get_venue_tz() -> ZoneInfo:
    """Return venue timezone as ZoneInfo from config."""
    return ZoneInfo(get_timezone())


@lru_cache(maxsize=1)
def _load_blackout_config() -> Dict[str, Any]:
    default = {"blackouts": [], "buffers": []}
    candidates = [
        Path(__file__).resolve().parents[4] / "data" / "blackout_buffer_windows.json",
        Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "blackout_buffer_windows.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return {
                "blackouts": payload.get("blackouts", []),
                "buffers": payload.get("buffers", []),
            }
    return default


def _expand_blackouts(config: Dict[str, Any]) -> set[date]:
    blocked: set[date] = set()
    buffers = config.get("buffers") or []
    for raw in config.get("blackouts") or []:
        try:
            base = date.fromisoformat(str(raw))
        except ValueError:
            continue
        blocked.add(base)
        for window in buffers:
            before = int(window.get("days_before", 0) or 0)
            after = int(window.get("days_after", 0) or 0)
            for offset in range(1, before + 1):
                blocked.add(base - timedelta(days=offset))
            for offset in range(1, after + 1):
                blocked.add(base + timedelta(days=offset))
    return blocked


def is_event_request(intent: Any) -> bool:
    """[Condition] Determine whether the classified intent corresponds to an event."""

    return _is_event_request(intent)


has_event_date = _has_event_date
has_event_date.__doc__ = """[Condition] Detect if user-provided information includes a valid event date."""


def suggest_dates(
    db: Dict[str, Any],
    preferred_room: str,
    start_from_iso: Any,
    days_ahead: int = 30,
    max_results: int = 5,
) -> List[str]:
    """[Condition] Offer candidate dates for a preferred room when missing."""

    tz = _get_venue_tz()
    today = datetime.now(tz).date()
    start_date = today
    if start_from_iso:
        try:
            start_dt = datetime.fromisoformat(str(start_from_iso).replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tz)
            else:
                start_dt = start_dt.astimezone(tz)
            start_date = start_dt.date()
        except ValueError:
            start_date = today
    if start_date < today:
        start_date = today

    config = _load_blackout_config()
    blocked = _expand_blackouts(config)
    suggestions: List[str] = []
    preferred = preferred_room or "Not specified"
    search_window = days_ahead + len(blocked) + 7

    for offset in range(max(search_window, days_ahead)):
        if len(suggestions) >= max_results:
            break
        day = start_date + timedelta(days=offset)
        if day in blocked:
            continue
        day_ddmmyyyy = day.strftime("%d.%m.%Y")
        status = room_status_on_date(db, day_ddmmyyyy, preferred)
        if status == "Available":
            suggestions.append(day_ddmmyyyy)

    return suggestions


def blackout_days() -> set[date]:
    """Expose expanded blackout+buffer dates for reuse in downstream steps."""

    config = _load_blackout_config()
    return _expand_blackouts(config)


room_status_on_date = _room_status_on_date
room_status_on_date.__doc__ = """[Condition] Check existing events on a given date for the same room."""
