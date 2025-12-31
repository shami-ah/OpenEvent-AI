from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

try:  # Python >= 3.9
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc,assignment]

from backend.workflows.steps.step1_intake.condition.checks import blackout_days
from backend.workflows.io.config_store import get_timezone


def _get_default_timezone() -> str:
    """Return venue timezone from config."""
    return get_timezone()
_MAX_LOOKAHEAD_DAYS = 730


def next5(
    base_or_today: Optional[Any],
    rules: Optional[Dict[str, Any]] = None,
) -> List[date]:
    """
    Compute the next five feasible event dates applying static venue rules.

    The helper favours dates that match supplied month/weekday constraints and
    gracefully falls back to the next available calendar days when the window
    is too restrictive. Returned dates are guaranteed to be unique and sorted.
    """

    start_date = _resolve_start_date(base_or_today, rules)
    blocked = set(blackout_days())
    weekday_hint = _normalize_weekday(rules.get("weekday") if rules else None)
    month_hint = _normalize_month(rules.get("month") if rules else None)
    days_ahead = int(rules.get("days_ahead") or _MAX_LOOKAHEAD_DAYS) if rules else _MAX_LOOKAHEAD_DAYS
    days_ahead = max(30, min(days_ahead, _MAX_LOOKAHEAD_DAYS))

    preferred: List[date] = []
    fallback: List[date] = []

    for offset in range(days_ahead):
        if len(preferred) >= 5 and len(preferred) + len(fallback) >= 5:
            break
        candidate = start_date + timedelta(days=offset)
        if candidate in blocked:
            continue
        matches_weekday = weekday_hint is None or candidate.weekday() == weekday_hint
        matches_month = month_hint is None or candidate.month == month_hint

        if matches_weekday and matches_month:
            _append_unique(preferred, candidate)
        else:
            _append_unique(fallback, candidate)

    ordered: List[date] = []
    ordered.extend(preferred[:5])

    if len(ordered) < 5:
        for candidate in fallback:
            if candidate not in ordered:
                ordered.append(candidate)
            if len(ordered) == 5:
                break

    if len(ordered) < 5:
        # Pad with additional days beyond the requested window if necessary.
        last_seen = ordered[-1] if ordered else start_date
        while len(ordered) < 5:
            last_seen += timedelta(days=1)
            if last_seen in blocked:
                continue
            _append_unique(ordered, last_seen)
    ordered = sorted(ordered)
    return ordered[:5]


def dates_in_month_weekday(
    month_hint: Optional[Any],
    weekday_hint: Optional[Any],
    *,
    limit: int = 5,
    timezone: Optional[str] = None,
) -> List[str]:
    """Return up to `limit` future ISO dates matching the given month/weekday."""

    rules: Dict[str, Any] = {"timezone": timezone or _get_default_timezone()}
    if month_hint:
        rules["month"] = month_hint
    if weekday_hint:
        rules["weekday"] = weekday_hint
    candidates = next5(None, rules)
    return [value.strftime("%Y-%m-%d") for value in candidates[:limit]]


def closest_alternatives(
    anchor_iso: str,
    weekday_hint: Optional[Any],
    month_hint: Optional[Any],
    *,
    limit: int = 3,
) -> List[str]:
    """
    Return the closest ISO dates to the anchor, favouring the same weekday/month hints.
    The list prioritises future dates while still surfacing near past dates when helpful.
    """

    if not anchor_iso:
        return []
    anchor_dt = _parse_to_datetime(anchor_iso)
    if anchor_dt is None:
        return []
    anchor_date = anchor_dt.date()

    weekday_normalized = _normalize_weekday(weekday_hint)
    month_normalized = _normalize_month(month_hint)

    blocked = set(blackout_days())
    results: List[str] = []
    seen = set()

    def _consider(candidate: date) -> None:
        if len(results) >= limit:
            return
        if candidate in blocked:
            return
        if weekday_normalized is not None and candidate.weekday() != weekday_normalized:
            return
        if month_normalized is not None and candidate.month != month_normalized:
            return
        iso_value = candidate.strftime("%Y-%m-%d")
        if iso_value in seen or iso_value == anchor_iso:
            return
        seen.add(iso_value)
        results.append(iso_value)

    offset = 1
    max_search_days = 90
    while len(results) < limit and offset <= max_search_days:
        _consider(anchor_date + timedelta(days=offset))
        _consider(anchor_date - timedelta(days=offset))
        offset += 1

    return results[:limit]


def _resolve_start_date(base_or_today: Optional[Any], rules: Optional[Dict[str, Any]]) -> date:
    tz_name = (rules or {}).get("timezone") or _get_default_timezone()
    tz = ZoneInfo(tz_name) if ZoneInfo else None
    today = datetime.now(tz).date() if tz else datetime.utcnow().date()

    if base_or_today is None:
        return today

    if isinstance(base_or_today, datetime):
        base_dt = base_or_today
    elif isinstance(base_or_today, date):
        base_dt = datetime.combine(base_or_today, datetime.min.time())
    else:
        base_dt = _parse_to_datetime(str(base_or_today))

    if base_dt is None:
        return today

    if tz and base_dt.tzinfo is not None:
        base_dt = base_dt.astimezone(tz)
    elif tz:
        base_dt = base_dt.replace(tzinfo=tz)

    candidate = base_dt.date()
    return candidate if candidate >= today else today


def _parse_to_datetime(raw: str) -> Optional[datetime]:
    cleaned = raw.strip()
    if not cleaned:
        return None

    for parser in (_parse_iso, _parse_date_only, _parse_ddmmyyyy):
        result = parser(cleaned)
        if result is not None:
            return result
    return None


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date_only(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed


def _parse_ddmmyyyy(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        return None
    return parsed


def _normalize_weekday(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 6 else None
    text = str(value).strip().lower()
    if not text:
        return None
    lookup = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }
    if text in lookup:
        return lookup[text]
    try:
        numeric = int(text)
        return numeric if 0 <= numeric <= 6 else None
    except ValueError:
        return None


def _normalize_month(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 12 else None
    text = str(value).strip()
    if not text:
        return None
    month_lookup = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }
    lowered = text.lower()
    if lowered in month_lookup:
        return month_lookup[lowered]
    if text.isdigit():
        numeric = int(text)
        return numeric if 1 <= numeric <= 12 else None
    return None


def _append_unique(container: List[date], value: date) -> None:
    if value not in container:
        container.append(value)