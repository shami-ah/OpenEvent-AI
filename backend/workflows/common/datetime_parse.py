"""Utility helpers for parsing human-friendly dates and time ranges."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple

from backend.workflows.common.relative_dates import resolve_relative_date
from backend.workflows.io.config_store import get_timezone

from zoneinfo import ZoneInfo


def _get_venue_tz() -> ZoneInfo:
    """Return venue timezone as ZoneInfo from config."""
    return ZoneInfo(get_timezone())

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_WEEKDAY_ALIASES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_DATE_NUMERIC = re.compile(
    r"\b(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{2,4})\b"
)
_DATE_ISO = re.compile(
    r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"
)
_DATE_TEXTUAL_DMY = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]{3,9})(?:\s*,?\s*(?P<year>\d{2,4}))?\b"
)
_DATE_TEXTUAL_MDY = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<year>\d{2,4}))?\b"
)
# Date range pattern: "June 11–12, 2026" or "11–12 June 2026"
_DATE_RANGE_MDY = re.compile(
    r"\b(?P<month>[A-Za-z]{3,9})\s+(?P<day1>\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–—]\s*(?P<day2>\d{1,2})(?:st|nd|rd|th)?)?\s*,?\s*(?P<year>\d{4})\b"
)
_DATE_RANGE_DMY = re.compile(
    r"\b(?P<day1>\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–—]\s*(?P<day2>\d{1,2})(?:st|nd|rd|th)?)?\s+(?P<month>[A-Za-z]{3,9})\s*,?\s*(?P<year>\d{4})\b"
)

_TIME_RANGE = re.compile(
    r"(?P<s_hour>\d{1,2})(?::(?P<s_min>\d{2}))?\s*(?P<s_suffix>am|pm|a\.m\.|p\.m\.|uhr|h)?"
    r"\s*(?:-|–|—|to|till|until|bis)\s*"
    r"(?P<e_hour>\d{1,2})(?::(?P<e_min>\d{2}))?\s*(?P<e_suffix>am|pm|a\.m\.|p\.m\.|uhr|h)?",
    re.IGNORECASE,
)

_TIME_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def parse_all_dates(
    text: str,
    *,
    fallback_year: Optional[int] = None,
    limit: Optional[int] = None,
    reference: Optional[date] = None,
    allow_relative: bool = True,
) -> List[date]:
    """Return all recognizable dates within ``text`` ordered by appearance."""

    if not text:
        return []

    matches: List[Tuple[int, date]] = []
    seen: set[str] = set()

    def _record(match_index: int, candidate: Optional[date]) -> None:
        if not candidate:
            return
        iso = candidate.isoformat()
        if iso in seen:
            return
        seen.add(iso)
        matches.append((match_index, candidate))

    def _parse_numeric(parts: dict[str, str]) -> Optional[date]:
        year = int(parts["year"])
        if year < 100:
            year += 2000
        month = int(parts["month"])
        day = int(parts["day"])
        try:
            return date(year, month, day)
        except ValueError:
            return None

    for pattern in (_DATE_NUMERIC, _DATE_ISO):
        for match in pattern.finditer(text):
            candidate = _parse_numeric(match.groupdict())
            _record(match.start(), candidate)

    # Date range patterns first (e.g., "June 11–12, 2026") - these have explicit year
    for pattern in (_DATE_RANGE_MDY, _DATE_RANGE_DMY):
        for match in pattern.finditer(text):
            parts = match.groupdict()
            month_token = parts["month"].lower()
            month = _MONTHS.get(month_token)
            if not month:
                continue
            try:
                year = int(parts["year"])
                day1 = int(parts["day1"])
                candidate1 = date(year, month, day1)
                _record(match.start(), candidate1)
                # Also capture second day if present (e.g., 12 in "June 11–12")
                day2_str = parts.get("day2")
                if day2_str:
                    day2 = int(day2_str)
                    candidate2 = date(year, month, day2)
                    _record(match.start() + 1, candidate2)  # offset slightly for ordering
            except ValueError:
                continue

    for pattern in (_DATE_TEXTUAL_DMY, _DATE_TEXTUAL_MDY):
        for match in pattern.finditer(text):
            parts = match.groupdict()
            month_token = parts["month"].lower()
            month = _MONTHS.get(month_token)
            if not month:
                continue
            try:
                year_str = parts.get("year")
                if year_str:
                    year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)
                elif fallback_year is not None:
                    year = fallback_year
                else:
                    year = datetime.utcnow().year
                day = int(parts["day"])
                candidate = date(year, month, day)
            except ValueError:
                continue
            _record(match.start(), candidate)

    matches.sort(key=lambda item: item[0])
    ordered = [item[1] for item in matches]
    if not ordered and allow_relative:
        reference_day = reference or date.today()
        relative_candidate = resolve_relative_date(text, reference_day)
        if relative_candidate:
            ordered.append(relative_candidate)

    if limit is not None:
        return ordered[:limit]
    return ordered


def parse_first_date(
    text: str,
    *,
    fallback_year: Optional[int] = None,
    reference: Optional[date] = None,
    allow_relative: bool = True,
) -> Optional[date]:
    """Parse the first recognizable date within ``text``."""

    results = parse_all_dates(
        text,
        fallback_year=fallback_year,
        limit=1,
        reference=reference,
        allow_relative=allow_relative,
    )
    return results[0] if results else None


def to_ddmmyyyy(value: date | str) -> Optional[str]:
    """Format supported date inputs into DD.MM.YYYY."""

    if isinstance(value, str):
        parsed = parse_first_date(value)
        if not parsed:
            return None
        return parsed.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return None


def to_iso_date(ddmmyyyy: str) -> Optional[str]:
    """Convert ``DD.MM.YYYY`` into ISO ``YYYY-MM-DD``."""

    try:
        parsed = datetime.strptime(ddmmyyyy, "%d.%m.%Y").date()
    except ValueError:
        return None
    return parsed.isoformat()


def parse_time_range(text: str) -> Tuple[Optional[time], Optional[time], bool]:
    """
    Extract a time range from ``text``.

    Returns a tuple of (start_time, end_time, matched), where ``matched`` signals
    whether any span was identified (even if parsing failed).
    """

    text_norm = text or ""
    for match in _TIME_RANGE.finditer(text_norm):
        start = _build_time(
            match.group("s_hour"),
            match.group("s_min"),
            match.group("s_suffix"),
            fallback_suffix=match.group("e_suffix"),
        )
        end = _build_time(
            match.group("e_hour"),
            match.group("e_min"),
            match.group("e_suffix"),
            fallback_suffix=match.group("s_suffix"),
        )
        if start and end:
            end = _adjust_end_if_needed(start, end)
            return start, end, True
        if start or end:
            return start, end, True

    times = _TIME_24H.findall(text_norm)
    if len(times) >= 2:
        start_hour, start_min = map(int, times[0])
        end_hour, end_min = map(int, times[1])
        start = time(start_hour, start_min)
        end = time(end_hour, end_min)
        end = _adjust_end_if_needed(start, end)
        return start, end, True
    return None, None, False


def build_window_iso(iso_date: str, start: time, end: time) -> Tuple[str, str]:
    """Compose timezone-aware ISO start/end from date and time components."""

    day = datetime.fromisoformat(iso_date)
    tz = _get_venue_tz()
    start_dt = datetime.combine(day.date(), start, tzinfo=tz)
    end_dt = datetime.combine(day.date(), end, tzinfo=tz)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt.isoformat(), end_dt.isoformat()


def _build_time(hour_str: Optional[str], minute_str: Optional[str], suffix: Optional[str], fallback_suffix: Optional[str]) -> Optional[time]:
    if hour_str is None:
        return None
    try:
        hour = int(hour_str)
    except ValueError:
        return None
    if not 0 <= hour <= 23:
        if suffix and suffix.lower().startswith(("a", "p")):
            hour %= 12
        else:
            return None
    minute = 0
    if minute_str:
        try:
            minute = int(minute_str)
        except ValueError:
            return None
    suffix_norm = (suffix or "").lower().rstrip(".")
    if suffix_norm in {"pm", "p", "p m"}:
        if hour < 12:
            hour += 12
    elif suffix_norm in {"am", "a", "a m"}:
        if hour == 12:
            hour = 0
    elif suffix_norm in {"uhr", "h"}:
        pass
    elif not suffix_norm and fallback_suffix:
        fallback_norm = fallback_suffix.lower().rstrip(".")
        if fallback_norm in {"pm", "p", "p m"} and hour < 12:
            hour += 12
        elif fallback_norm in {"am", "a", "a m"} and hour == 12:
            hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _adjust_end_if_needed(start: time, end: time) -> time:
    if end > start:
        return end
    tz = _get_venue_tz()
    start_dt = datetime.combine(date.today(), start, tzinfo=tz)
    end_dt = datetime.combine(date.today(), end, tzinfo=tz)
    if end_dt <= start_dt:
        end_dt += timedelta(hours=12)
    return end_dt.time()


def month_name_to_number(token: str) -> Optional[int]:
    """Normalize textual month tokens into month numbers."""

    if not token:
        return None
    lowered = token.strip().lower()
    return _MONTHS.get(lowered)


def weekday_name_to_number(token: str) -> Optional[int]:
    """Normalize textual weekday tokens into weekday numbers (Monday=0)."""

    if not token:
        return None
    lowered = token.strip().lower()
    return _WEEKDAY_ALIASES.get(lowered)


def enumerate_month_weekday(year: int, month: int, weekday: int) -> List[date]:
    """
    Enumerate every occurrence of ``weekday`` within the specified month.

    Weekday uses Python's convention (Monday = 0). Results are naive ``date`` objects.
    """

    try:
        pivot = date(year, month, 1)
    except ValueError:
        return []
    offset = (weekday - pivot.weekday()) % 7
    current = pivot + timedelta(days=offset)
    results: List[date] = []
    while current.month == month:
        results.append(current)
        current += timedelta(days=7)
    return results


__all__ = [
    "parse_first_date",
    "to_ddmmyyyy",
    "to_iso_date",
    "parse_time_range",
    "build_window_iso",
    "month_name_to_number",
    "weekday_name_to_number",
    "enumerate_month_weekday",
]
