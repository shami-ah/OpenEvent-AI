"""
Step 2 Pure Utilities - Stateless helper functions for date confirmation.

Extracted from step2_handler.py as part of Step 2 refactoring (Dec 2025).

These are pure functions that don't depend on WorkflowState and can be
tested in isolation. They handle:
- Text extraction (names, signatures)
- String formatting (time labels, day lists)
- Simple classification (affirmative replies, confirmation signals)
- Data conversion (ConfirmationWindow <-> dict)
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, time
from typing import Any, Counter as CounterType, Dict, List, Optional, Sequence, Tuple

from backend.debug.hooks import trace_gate  # D13d

from .constants import (
    AFFIRMATIVE_TOKENS,
    CONFIRMATION_KEYWORDS,
    PLACEHOLDER_NAMES,
    SIGNATURE_MARKERS,
    WEEKDAY_LABELS,
)
from .types import ConfirmationWindow
from .date_parsing import clean_weekdays_hint as _clean_weekdays_hint
from backend.workflows.common.datetime_parse import parse_first_date


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

def _extract_first_name(raw: Optional[str]) -> Optional[str]:
    """Extract the first name from a raw name string."""
    if not raw:
        return None
    candidate = str(raw).strip()
    if not candidate:
        return None
    token = candidate.split()[0].strip(",. ")
    lowered = token.lower()
    if lowered in PLACEHOLDER_NAMES:
        return None
    return token or None


def _extract_signature_name(text: Optional[str]) -> Optional[str]:
    """Extract a name from an email signature block."""
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in SIGNATURE_MARKERS):
            if idx + 1 < len(lines):
                candidate = lines[idx + 1].strip(", ")
                if candidate and len(candidate.split()) <= 4:
                    return candidate
    if lines:
        tail = lines[-1]
        if 1 <= len(tail.split()) <= 4:
            return tail
    return None


def compose_greeting(
    raw_name: Optional[str],
    message_body: Optional[str] = None,
    from_name: Optional[str] = None,
) -> str:
    """Compose a greeting from available name sources.

    Extracted from step2_handler.py as part of D13 refactoring.

    Args:
        raw_name: Pre-extracted name from user_info or client profile
        message_body: Message body to search for signature name
        from_name: Fallback from_name from message

    Returns:
        Greeting string like "Hello Sarah," or "Hello,"
    """
    # Try sources in priority order
    name = raw_name
    if not name and message_body:
        name = _extract_signature_name(message_body)
    if not name:
        name = from_name

    first = _extract_first_name(name)
    if not first:
        return "Hello,"
    return f"Hello {first},"


def with_greeting(greeting: str, body: str) -> str:
    """Prepend a greeting to a message body if not already present.

    Extracted from step2_handler.py as part of D13 refactoring.

    Args:
        greeting: The greeting to prepend (e.g., "Hello Sarah,")
        body: The message body

    Returns:
        Body with greeting prepended, or just greeting if body is empty
    """
    if not body:
        return greeting
    if body.startswith(greeting):
        return body
    return f"{greeting}\n\n{body}"


def _extract_candidate_tokens(text: str) -> str:
    """Extract the most relevant tokens from message text for date parsing."""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    # Strip greetings or closings when the message is short.
    parts = cleaned.splitlines()
    if len(parts) == 1:
        token = parts[0].strip()
        return token
    # Prefer the longest non-empty line (often the date).
    longest = max((line.strip() for line in parts), key=len, default="")
    return longest or cleaned


def _strip_system_subject(subject: str) -> str:
    """Strip system-generated metadata from subject lines.

    The API adds "Client follow-up (YYYY-MM-DD HH:MM)" to follow-up messages.
    This timestamp should NOT be used for date extraction as it represents
    when the message was sent, not the requested event date.
    """
    # Pattern: "Client follow-up (YYYY-MM-DD HH:MM)" or similar system-generated prefixes
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()


# =============================================================================
# DATA CLEANUP
# =============================================================================

def _clear_invalid_weekdays_hint(event_entry: Dict[str, Any]) -> None:
    """Strip invalid weekday hints that can be polluted by participant counts."""
    weekdays_hint = event_entry.get("weekdays_hint")
    cleaned = _clean_weekdays_hint(weekdays_hint)
    if cleaned != weekdays_hint:
        if cleaned:
            event_entry["weekdays_hint"] = cleaned
        else:
            event_entry.pop("weekdays_hint", None)


# =============================================================================
# STRING FORMATTING
# =============================================================================

def _preface_with_apology(text: Optional[str]) -> Optional[str]:
    """Prepend 'Sorry, ' to a message if not already apologetic."""
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    lowered = stripped.lower()
    if lowered.startswith(("sorry", "unfortunately", "apologies")):
        return stripped
    first = stripped[0]
    softened = stripped
    if first.isalpha() and first.isupper():
        softened = first.lower() + stripped[1:]
    return f"Sorry, {softened}"


def _format_label_text(label: Optional[Any]) -> str:
    """Format a label string with proper capitalization."""
    if label is None:
        return ""
    text = str(label).strip()
    if not text:
        return ""
    if text.lower() == text:
        return text.capitalize()
    return text


def _date_header_label(month_hint: Optional[str], week_label: Optional[str] = None) -> str:
    """Generate a header label for date options."""
    if week_label:
        return f"Date options for {_format_label_text(week_label)}"
    if month_hint:
        return f"Date options for {_format_label_text(month_hint)}"
    return "Date options"


def _format_time_label(raw: Optional[str]) -> Optional[str]:
    """Format a time of day label (e.g., 'morning' -> 'Morning')."""
    if not raw:
        return None
    lowered = raw.strip().lower()
    if not lowered:
        return None
    return lowered.capitalize()


def _format_day_list(iso_dates: Sequence[str]) -> Tuple[str, Optional[int]]:
    """Format a list of ISO dates into a comma-separated day list with year."""
    if not iso_dates:
        return "", None
    day_labels: List[str] = []
    year_value: Optional[int] = None
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        day_labels.append(parsed.strftime("%d"))
        year_value = year_value or parsed.year
    return ", ".join(day_labels), year_value


def _weekday_label_from_dates(
    iso_dates: Sequence[str],
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Determine the most common weekday from a list of ISO dates."""
    counts: CounterType[int] = Counter()
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        counts.update([parsed.weekday()])
    if counts:
        weekday_index, _ = counts.most_common(1)[0]
        base = WEEKDAY_LABELS[weekday_index]
        return f"{base}s"
    return fallback


def _month_label_from_dates(
    iso_dates: Sequence[str],
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Get the month name from the first valid ISO date."""
    for iso_value in iso_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        return parsed.strftime("%B")
    return fallback


def _pluralize_weekday_hint(weekday_hint: Any) -> Optional[str]:
    """Pluralize a weekday name (e.g., 'Friday' -> 'Fridays')."""
    if isinstance(weekday_hint, str):
        token = weekday_hint.strip()
        if token:
            label = token.capitalize()
            return f"{label}s" if not label.endswith("s") else label
    return None


def _describe_constraints(
    month_hint: Optional[str],
    weekday_hint: Optional[Any],
    time_of_day: Optional[str],
) -> str:
    """Generate a human-readable description of date constraints."""
    parts: List[str] = []
    if weekday_hint:
        if isinstance(weekday_hint, (list, tuple, set)):
            tokens = [str(word).capitalize() for word in weekday_hint if str(word).strip()]
            if tokens:
                parts.append(", ".join(tokens))
        else:
            parts.append(str(weekday_hint).capitalize())
    if month_hint:
        parts.append(f"in {str(month_hint).capitalize()}")
    descriptor = " ".join(parts) if parts else "for your requested window"
    if time_of_day:
        descriptor += f" ({str(time_of_day).lower()})"
    return descriptor


def _format_window(window: ConfirmationWindow) -> str:
    """Format a ConfirmationWindow as a display string."""
    if window.start_time and window.end_time:
        return f"{window.display_date} {window.start_time}–{window.end_time}"
    return window.display_date


# =============================================================================
# TIME UTILITIES
# =============================================================================

def _normalize_time_value(value: Optional[str]) -> Optional[str]:
    """Normalize a time value to HH:MM format."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", ":")
    if ":" not in text:
        if text.isdigit():
            text = f"{int(text) % 24:02d}:00"
        else:
            return None
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _to_time(value: str) -> time:
    """Parse a HH:MM string into a time object."""
    return datetime.strptime(value, "%H:%M").time()


def _window_hash(date_iso: str, start_iso: Optional[str], end_iso: Optional[str]) -> str:
    """Generate a SHA256 hash for a window (date + time range)."""
    payload = f"{date_iso}|{start_iso or ''}|{end_iso or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# =============================================================================
# CLASSIFICATION
# =============================================================================

def _is_affirmative_reply(text: str) -> bool:
    """Check if text is an affirmative reply (yes, ok, etc.)."""
    normalized = text.strip().lower()
    if not normalized:
        return False
    if normalized in AFFIRMATIVE_TOKENS:
        return True
    negative_prefixes = ("can you", "could you", "would you", "please", "may you")
    for token in AFFIRMATIVE_TOKENS:
        if token in normalized:
            if any(prefix in normalized for prefix in negative_prefixes) and "?" in normalized:
                continue
            return True
    return False


def _message_signals_confirmation(text: str) -> bool:
    """Check if a message signals date confirmation intent."""
    normalized = text.strip().lower()
    if not normalized:
        return False
    if _is_affirmative_reply(normalized):
        return True
    for keyword in CONFIRMATION_KEYWORDS:
        if keyword in normalized:
            if "?" in normalized and any(prefix in normalized for prefix in ("can you", "could you")):
                continue
            return True
    # Treat bare mentions of supported dates/times as confirmations.
    # BUT: Skip this when the message is clearly a Q&A query (question words + "?").
    # Vague date mentions like "Saturday in February" should not count as confirmations.
    # Check for question words anywhere in the message (with word boundaries).
    question_words = ("which", "what", "when", "where", "how", "can", "could", "would", "do you", "is there", "are there")
    is_question = "?" in normalized and any(
        re.search(rf"\b{re.escape(word)}\b", normalized) for word in question_words
    )
    if not is_question:
        tokens = _extract_candidate_tokens(text or "")
        if tokens:
            parsed = parse_first_date(tokens, allow_relative=True)
            if parsed:
                return True
    return False


def _message_mentions_new_date(text: str) -> bool:
    """Check if a message mentions a new date."""
    if not text.strip():
        return False
    detected = parse_first_date(text, fallback_year=datetime.utcnow().year)
    return detected is not None


def _is_weekend_token(token: Optional[Any]) -> bool:
    """Check if a token represents a weekend day."""
    if token is None:
        return False
    if isinstance(token, (list, tuple, set)):
        return any(_is_weekend_token(item) for item in token)
    normalized = str(token).strip().lower()
    if not normalized:
        return False
    return normalized.startswith("sat") or normalized.startswith("sun") or "weekend" in normalized


# =============================================================================
# DATA CONVERSION
# =============================================================================

def _window_payload(window: ConfirmationWindow) -> Dict[str, Any]:
    """Convert a ConfirmationWindow to a dictionary payload."""
    return {
        "display_date": window.display_date,
        "iso_date": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start_iso": window.start_iso,
        "end_iso": window.end_iso,
        "inherited_times": window.inherited_times,
        "partial": window.partial,
        "source_message_id": window.source_message_id,
    }


def _window_from_payload(payload: Dict[str, Any]) -> Optional[ConfirmationWindow]:
    """Convert a dictionary payload to a ConfirmationWindow."""
    if not isinstance(payload, dict):
        return None
    try:
        return ConfirmationWindow(
            display_date=payload.get("display_date"),
            iso_date=payload.get("iso_date"),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            start_iso=payload.get("start_iso"),
            end_iso=payload.get("end_iso"),
            inherited_times=bool(payload.get("inherited_times")),
            partial=bool(payload.get("partial")),
            source_message_id=payload.get("source_message_id"),
        )
    except TypeError:
        return None


__all__ = [
    # Text extraction
    "_extract_first_name",
    "_extract_signature_name",
    "_extract_candidate_tokens",
    "_strip_system_subject",
    # D13: Greeting helpers
    "compose_greeting",
    "with_greeting",
    # String formatting
    "_preface_with_apology",
    "_format_label_text",
    "_date_header_label",
    "_format_time_label",
    "_format_day_list",
    "_weekday_label_from_dates",
    "_month_label_from_dates",
    "_pluralize_weekday_hint",
    "_describe_constraints",
    "_format_window",
    # Time utilities
    "_normalize_time_value",
    "_to_time",
    "_window_hash",
    # Classification
    "_is_affirmative_reply",
    "_message_signals_confirmation",
    "_message_mentions_new_date",
    "_is_weekend_token",
    # Data conversion
    "_window_payload",
    "_window_from_payload",
    # D9: Additional utilities
    "has_range_tokens",
    "range_query_pending",
    "get_message_text",
    "build_select_date_action",
    "format_room_availability",
    "compact_products_summary",
    "user_requested_products",
    # D13d: Tracing
    "trace_candidate_gate",
]


# =============================================================================
# D9: ADDITIONAL UTILITIES (extracted from step2_handler.py)
# =============================================================================

def has_range_tokens(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> bool:
    """Check if user_info or event_entry contains range query tokens."""
    return any(
        (
            user_info.get("range_query_detected"),
            event_entry.get("range_query_detected"),
            user_info.get("vague_month"),
            event_entry.get("vague_month"),
            user_info.get("vague_weekday"),
            event_entry.get("vague_weekday"),
            user_info.get("vague_time_of_day"),
            event_entry.get("vague_time_of_day"),
        )
    )


def range_query_pending(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> bool:
    """Check if a range query is still pending (not yet resolved to a date)."""
    if not has_range_tokens(user_info, event_entry):
        return False
    if event_entry.get("date_confirmed"):
        return False
    if user_info.get("event_date") or user_info.get("date"):
        return False
    pending_window = event_entry.get("pending_date_confirmation") or {}
    if pending_window.get("iso_date"):
        return False
    return True


def get_message_text(subject: Optional[str], body: Optional[str]) -> str:
    """Combine subject and body into a single message text."""
    subject = subject or ""
    body = body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def build_select_date_action(
    date_value: "datetime.date",
    ddmmyyyy: str,
    time_label: Optional[str],
) -> Dict[str, Any]:
    """Build a select_date action dictionary for the frontend."""
    # Import here to avoid circular imports
    from datetime import date as dt_date
    label = date_value.strftime("%a %d %b %Y")
    if time_label:
        label = f"{label} · {time_label}"
    return {
        "type": "select_date",
        "label": f"Confirm {label}",
        "date": ddmmyyyy,
        "iso_date": date_value.isoformat(),
    }


def format_room_availability(entries: List[Dict[str, Any]]) -> List[str]:
    """Format room availability entries into display lines."""
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for entry in entries:
        room = str(entry.get("room") or "Room").strip() or "Room"
        date_label = entry.get("date_label") or entry.get("iso_date") or ""
        status = entry.get("status") or "Available"
        grouped.setdefault(room, []).append((date_label, status))

    lines: List[str] = []
    for room, values in grouped.items():
        seen: set[Tuple[str, str]] = set()
        formatted: List[str] = []
        for date_label, status in values:
            if not date_label:
                continue
            key = (date_label, status)
            if key in seen:
                continue
            seen.add(key)
            label = date_label
            if status and status.lower() not in {"available"}:
                label = f"{date_label} ({status})"
            formatted.append(label)
        if formatted:
            lines.append(f"{room}: Available on {', '.join(formatted)}")
    return lines


def compact_products_summary(preferences: Dict[str, Any]) -> List[str]:
    """Build a compact products/catering summary."""
    lines = ["Products & Catering (summary):"]
    wish_products = []
    raw_wishes = preferences.get("wish_products") if isinstance(preferences, dict) else None
    if isinstance(raw_wishes, (list, tuple)):
        wish_products = [str(item).strip() for item in raw_wishes if str(item).strip()]
    if wish_products:
        highlights = ", ".join(wish_products[:3])
        lines.append(f"- Highlights: {highlights}.")
    else:
        lines.append("- Seasonal menus with flexible wine pairings available.")
    return lines


def user_requested_products(message_text: str, classification: Dict[str, Any]) -> bool:
    """Check if the user requested products/catering in their message."""
    message_lower = (message_text or "").lower()
    if any(keyword in message_lower for keyword in ("menu", "cater", "product", "wine")):
        return True
    parsed = classification.get("parsed") or {}
    if isinstance(parsed, dict):
        if parsed.get("products") or parsed.get("catering"):
            return True
    return False


# =============================================================================
# D13d: TRACING UTILITIES (extracted from step2_handler.py)
# =============================================================================


def trace_candidate_gate(thread_id: str, candidates: List[str]) -> None:
    """Emit a gate trace for candidate count (feasible=0/1/many).

    Extracted from step2_handler.py as part of D13d refactoring.

    Args:
        thread_id: Thread identifier for tracing
        candidates: List of candidate ISO date strings
    """
    if not thread_id:
        return
    count = len([value for value in candidates if value])
    if count == 0:
        label = "feasible=0"
    elif count == 1:
        label = "feasible=1"
    else:
        label = "feasible=many"
    trace_gate(thread_id, "Step2_Date", label, True, {"count": count})
