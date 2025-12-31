"""
Step 2 Window Helpers - Shared functions for date constraint handling.

Extracted from step2_handler.py as part of D5 refactoring (Dec 2025).

These functions are used by both step2_handler.py and general_qna.py,
extracted here to avoid circular dependencies.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.types import WorkflowState
from backend.workflows.io.dates import next5
from backend.workflows.io.config_store import get_timezone

from .types import WindowHints
from .date_parsing import (
    normalize_month_token as _normalize_month_token,
    normalize_weekday_tokens as _normalize_weekday_tokens,
)


def _reference_date_from_state(state: WorkflowState) -> date:
    """Get the reference date from state message timestamp or today."""
    ts = state.message.ts if state.message else None
    if ts:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return date.today()


def _resolve_window_hints(constraints: Dict[str, Any], state: WorkflowState) -> WindowHints:
    """Extract month/weekday/time hints from constraints and state."""
    user_info = state.user_info or {}
    event_entry = state.event_entry or {}
    month_hint = constraints.get("vague_month") or user_info.get("vague_month") or event_entry.get("vague_month")
    weekday_hint = constraints.get("weekday") or user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    time_of_day = (
        constraints.get("time_of_day")
        or user_info.get("vague_time_of_day")
        or event_entry.get("vague_time_of_day")
    )
    return month_hint, weekday_hint, time_of_day


def _has_window_constraints(window_hints: WindowHints) -> bool:
    """Check if the window hints contain any constraints."""
    month_hint, weekday_hint, _ = window_hints
    if month_hint:
        return True
    if isinstance(weekday_hint, (list, tuple, set)):
        return any(bool(item) for item in weekday_hint)
    return bool(weekday_hint)


def _window_filters(window_hints: WindowHints) -> Tuple[Optional[int], List[int]]:
    """Convert window hints to month index and weekday indices."""
    month_hint, weekday_hint, _ = window_hints
    return _normalize_month_token(month_hint), _normalize_weekday_tokens(weekday_hint)


def _extract_participants_from_state(state: WorkflowState) -> Optional[int]:
    """Extract participant count from state, user_info, or event requirements."""
    candidates: List[Any] = []
    user_info = state.user_info or {}
    candidates.append(user_info.get("participants"))
    candidates.append(user_info.get("number_of_participants"))
    event_entry = state.event_entry or {}
    requirements = event_entry.get("requirements") or {}
    candidates.append(requirements.get("number_of_participants"))
    for raw in candidates:
        if raw in (None, "", "Not specified", "none"):
            continue
        try:
            return int(str(raw).strip().strip("~+"))
        except (TypeError, ValueError):
            continue
    return None


def _candidate_dates_for_constraints(
    state: WorkflowState,
    constraints: Dict[str, Any],
    limit: int = 5,
    *,
    window_hints: Optional[WindowHints] = None,
    strict: bool = False,
) -> List[str]:
    """
    Generate candidate dates matching the given constraints.

    Returns list of ISO date strings (YYYY-MM-DD).
    """
    hints = window_hints or _resolve_window_hints(constraints, state)
    month_hint, weekday_hint, _ = hints
    reference_day = _reference_date_from_state(state)
    rules: Dict[str, Any] = {"timezone": get_timezone()}
    if month_hint:
        rules["month"] = month_hint
    weekday_tokens: List[Any] = []
    if isinstance(weekday_hint, (list, tuple, set)):
        seen_tokens: set[str] = set()
        for token in weekday_hint:
            text = str(token).strip().lower()
            if not text or text in seen_tokens:
                continue
            seen_tokens.add(text)
            weekday_tokens.append(token)
    elif weekday_hint not in (None, ""):
        weekday_tokens.append(weekday_hint)

    candidate_dates: List[date] = []
    if weekday_tokens:
        for token in weekday_tokens:
            scoped_rules = dict(rules)
            scoped_rules["weekday"] = token
            candidate_dates.extend(next5(state.message.ts if state.message else None, scoped_rules))
    else:
        candidate_dates = next5(state.message.ts if state.message else None, rules)
    dates = sorted(candidate_dates)
    match_only = strict and _has_window_constraints(hints)
    iso_values: List[str] = []
    seen: set[str] = set()
    month_index, weekday_indices = _window_filters(hints)
    clamp_year: Optional[int] = None
    if month_index:
        clamp_year = reference_day.year
        days_in_month = monthrange(clamp_year, month_index)[1]
        if reference_day.month > month_index or (
            reference_day.month == month_index and reference_day.day > days_in_month
        ):
            clamp_year += 1

    for value in dates:
        if clamp_year:
            if value.year < clamp_year:
                continue
            if value.year > clamp_year:
                break
        iso_value = value.strftime("%Y-%m-%d")
        if iso_value in seen:
            continue
        if match_only:
            if month_index and value.month != month_index:
                continue
            if weekday_indices and value.weekday() not in weekday_indices:
                continue
        iso_values.append(iso_value)
        seen.add(iso_value)
        if len(iso_values) >= limit:
            break

    if not iso_values and not match_only:
        for value in dates:
            iso_value = value.strftime("%Y-%m-%d")
            if iso_value in seen:
                continue
            iso_values.append(iso_value)
            seen.add(iso_value)
            if len(iso_values) >= limit:
                break

    return iso_values[:limit]


__all__ = [
    "_reference_date_from_state",
    "_resolve_window_hints",
    "_has_window_constraints",
    "_window_filters",
    "_extract_participants_from_state",
    "_candidate_dates_for_constraints",
]
