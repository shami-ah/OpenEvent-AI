from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from workflows.common.capacity import alternative_rooms, fits_capacity, layout_capacity
from workflows.common.catalog import (
    list_catering,
    list_common_room_features,
    list_free_dates,
    list_products,
    list_room_features,
    list_rooms_by_feature,
    _room_entries,  # For listing all rooms in Q&A
)
from workflows.common.conflict import get_available_rooms_on_date
from workflows.qna.templates import build_info_block, build_next_step_line
from debug.hooks import trace_qa_enter, trace_qa_exit

# Generic accessor for LLM-extracted Q&A requirements
def get_qna_requirements(extraction: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get ALL temporary requirements extracted by LLM for this Q&A.
    Generic accessor - works for any field (attendees, dietary, features, layout, etc.)

    These requirements are for answering THIS Q&A only, NOT persisted to event record.
    """
    if not extraction:
        return {}
    qna_req = extraction.get("qna_requirements")
    return qna_req if isinstance(qna_req, dict) else {}


def _get_cached_extraction(event_entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Get the cached Q&A extraction from event entry."""
    if not event_entry:
        return None
    qna_cache = event_entry.get("qna_cache")
    if isinstance(qna_cache, dict):
        return qna_cache.get("extraction")
    return None


_ROOM_NAMES = ("Room A", "Room B", "Room C", "Punkt.Null")


def _list_all_rooms_for_qna(
    min_capacity: Optional[int] = None,
    event_date: Optional[str] = None,
    db: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    List rooms for Q&A responses (e.g., "What rooms do you have available?").

    Returns (rooms, is_date_filtered) tuple:
    - rooms: List sorted by capacity with name, max_capacity, and key features
    - is_date_filtered: True if filtered by date availability

    When event_date and db are provided, only returns rooms available on that date.
    Optionally filters by minimum capacity.
    """
    # Get date-available rooms if date and db provided
    available_on_date: Optional[set] = None
    if event_date and db and event_id:
        try:
            available_rooms = get_available_rooms_on_date(db, event_id, event_date)
            available_on_date = {r.lower() for r in available_rooms}
        except (AttributeError, TypeError, KeyError):
            # Database structure might not support this check
            pass

    rooms = []
    for entry in _room_entries():
        name = entry.get("name")
        if not name:
            continue

        # Filter by date availability if we have that info
        if available_on_date is not None:
            if name.lower() not in available_on_date:
                continue

        # Get max capacity
        max_cap = entry.get("max_capacity")
        if max_cap is None:
            # Try to compute from layouts
            layouts = entry.get("capacity_by_layout") or {}
            if layouts:
                max_cap = max(layouts.values())

        # Filter by min capacity if specified
        if min_capacity is not None and max_cap is not None and max_cap < min_capacity:
            continue

        # Get features for display
        features = list(entry.get("features") or [])[:3]  # Top 3 features

        rooms.append({
            "name": name,
            "max_capacity": max_cap,
            "features": features,
        })

    # Sort by capacity descending (largest rooms first)
    rooms.sort(key=lambda r: (r["max_capacity"] or 0), reverse=True)
    return rooms, available_on_date is not None
# Auto-build feature keywords from room data at import time
def _build_feature_keywords() -> Dict[str, str]:
    """
    Auto-generate feature keywords from actual room data.
    This ensures we don't need to manually maintain a keyword list.
    """
    from workflows.common.catalog import list_room_features
    keywords: Dict[str, str] = {}

    # Collect all features from all rooms
    all_features: set[str] = set()
    for room in _ROOM_NAMES:
        features = list_room_features(room) or []
        all_features.update(features)

    # Build keyword mappings from actual features
    for feature in all_features:
        # Add the full feature as-is
        keywords[feature.lower()] = feature
        # Add individual words as keywords (for partial matching)
        for word in feature.lower().split():
            if len(word) > 2 and word not in {"and", "the", "for", "with"}:
                if word not in keywords:
                    keywords[word] = feature

    # Add common aliases
    aliases = {
        "wi-fi": "WiFi", "internet": "WiFi",
        "av": "projector", "beamer": "Projector",
        "mic": "Microphone", "microphone": "Microphone",
    }
    for alias, canonical in aliases.items():
        if alias not in keywords:
            # Find actual feature containing canonical
            for feat in all_features:
                if canonical.lower() in feat.lower():
                    keywords[alias] = feat
                    break

    return keywords

_FEATURE_KEYWORDS = _build_feature_keywords()
_LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "ushape": "U-shape",
    "u shape": "U-shape",
    "theater": "Theater",
    "theatre": "Theater",
    "classroom": "Classroom",
    "boardroom": "Boardroom",
    "banquet": "Banquet",
    "standing": "Standing reception",
}
_ATTENDEE_PATTERN = re.compile(r"(\d{1,3})\s*(?:guests|people|ppl|attendees)", re.IGNORECASE)
_ROOM_PATTERN = re.compile(r"\broom\s*([abc])\b", re.IGNORECASE)
_MONTHS = {
    # English
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    # German
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,  # ASCII alternative for März
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "oktober": 10,
    "dezember": 12,
}


def _with_preface(lines: List[str], preface: Optional[str]) -> List[str]:
    """Return a new list with an optional lead sentence ahead of the info lines."""

    cleaned = (preface or "").strip()
    if not cleaned:
        return lines
    if lines and lines[0].strip() == cleaned:
        return lines
    return [cleaned, *lines]


def _message_text(msg: Dict[str, Any]) -> str:
    subject = str(msg.get("subject") or "").strip()
    body = str(msg.get("body") or "").strip()
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _current_step(event_entry: Optional[Dict[str, Any]]) -> int:
    if event_entry and isinstance(event_entry.get("current_step"), int):
        return int(event_entry["current_step"])
    return 2


def _extract_attendees(
    text: str,
    fallback: Optional[Any],
    extraction: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """
    Extract attendee count. Priority:
    1. LLM-extracted qna_requirements.attendees (semantic understanding)
    2. Regex pattern match in text
    3. Fallback value
    """
    # Prefer LLM extraction (handles "visitors", "guests", "people" semantically)
    qna_req = get_qna_requirements(extraction)
    if qna_req.get("attendees") is not None:
        try:
            return int(qna_req["attendees"])
        except (TypeError, ValueError):
            pass

    # Fall back to regex
    match = _ATTENDEE_PATTERN.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    if fallback is None:
        return None
    try:
        return int(fallback)
    except (TypeError, ValueError):
        return None


def _extract_layout(
    text: str,
    fallback: Optional[str],
    extraction: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Extract layout. Priority:
    1. LLM-extracted qna_requirements.layout
    2. Keyword match in text
    3. Fallback value
    """
    # Prefer LLM extraction
    qna_req = get_qna_requirements(extraction)
    if qna_req.get("layout"):
        return str(qna_req["layout"])

    # Fall back to keyword matching
    lowered = text.lower()
    for token, layout in _LAYOUT_KEYWORDS.items():
        if token in lowered:
            return layout
    return fallback


def _extract_feature_tokens(
    text: str,
    extraction: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Extract feature tokens ONLY from the message text.
    We're strict here - only extract features that the user explicitly asks about.
    Uses word boundary matching to avoid false positives.
    """
    import re
    features: List[str] = []
    lowered = text.lower()
    # Extract words from the message for exact matching
    message_words = set(re.findall(r'\b\w+\b', lowered))

    # Get LLM-extracted features but only keep ones that appear in text
    qna_req = get_qna_requirements(extraction)
    llm_features = qna_req.get("features") or []
    if isinstance(llm_features, list):
        for f in llm_features:
            f_str = str(f).lower()
            # Only include if a key word from the feature appears as a word in text
            feature_words = set(re.findall(r'\b\w+\b', f_str))
            if feature_words & message_words:  # Any common word
                features.append(str(f))

    # Also do keyword matching for features in the actual message
    for token, canonical in _FEATURE_KEYWORDS.items():
        # Use word boundary matching - token must appear as whole word
        if token in message_words and canonical not in features:
            features.append(canonical)

    return features


def _extract_date_from_text(text: str) -> Optional[Tuple[str, str]]:
    """
    Extract a date mentioned in message text.

    Returns tuple of (iso_date, display_date) or None if no date found.
    Handles formats like "March 15th", "15th of March", "15.03", "March 15".
    """
    import calendar

    month_names = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    month_abbr = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}

    text_lower = text.lower()

    # Pattern: "March 15th" or "March 15"
    pattern1 = re.compile(r'\b(' + '|'.join(month_names.keys()) + r')\s+(\d{1,2})(?:st|nd|rd|th)?\b', re.IGNORECASE)
    match = pattern1.search(text_lower)
    if match:
        month_name, day_str = match.groups()
        month = month_names.get(month_name.lower())
        if month:
            day = int(day_str)
            year = datetime.now().year
            # If date is in the past, use next year
            try:
                target = datetime(year, month, day)
                if target < datetime.now():
                    year += 1
                iso_date = f"{year}-{month:02d}-{day:02d}"
                display_date = f"{day:02d}.{month:02d}.{year}"
                return iso_date, display_date
            except ValueError:
                pass

    # Pattern: "15th of March" or "15 March"
    pattern2 = re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(' + '|'.join(month_names.keys()) + r')\b', re.IGNORECASE)
    match = pattern2.search(text_lower)
    if match:
        day_str, month_name = match.groups()
        month = month_names.get(month_name.lower())
        if month:
            day = int(day_str)
            year = datetime.now().year
            try:
                target = datetime(year, month, day)
                if target < datetime.now():
                    year += 1
                iso_date = f"{year}-{month:02d}-{day:02d}"
                display_date = f"{day:02d}.{month:02d}.{year}"
                return iso_date, display_date
            except ValueError:
                pass

    # Pattern: "15.03" or "15/03" (European format)
    pattern3 = re.compile(r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b')
    match = pattern3.search(text)
    if match:
        day_str, month_str, year_str = match.groups()
        day = int(day_str)
        month = int(month_str)
        year = int(year_str) if year_str else datetime.now().year
        if year < 100:
            year += 2000
        if 1 <= day <= 31 and 1 <= month <= 12:
            try:
                target = datetime(year, month, day)
                if target < datetime.now() and not year_str:
                    year += 1
                iso_date = f"{year}-{month:02d}-{day:02d}"
                display_date = f"{day:02d}.{month:02d}.{year}"
                return iso_date, display_date
            except ValueError:
                pass

    return None


def _feature_matches_room(asked: str, room_features: List[str]) -> bool:
    """
    Check if an asked feature matches any room feature.
    Uses word-level matching to handle variations like:
    - "wifi" matches "WiFi included"
    - "projector" matches "Beamer/Projector"
    """
    asked_words = set(asked.lower().split())
    asked_lower = asked.lower()

    for rf in room_features:
        rf_lower = rf.lower()
        # Direct substring match
        if asked_lower in rf_lower or rf_lower in asked_lower:
            return True
        # Word-level match
        rf_words = set(rf_lower.replace("/", " ").replace("-", " ").split())
        if asked_words & rf_words:  # Any common word
            return True

    return False


def _find_matching_feature(asked: str, room_features: List[str]) -> Optional[str]:
    """Find the actual room feature that matches the asked feature."""
    asked_words = set(asked.lower().split())
    asked_lower = asked.lower()

    for rf in room_features:
        rf_lower = rf.lower()
        if asked_lower in rf_lower or rf_lower in asked_lower:
            return rf
        rf_words = set(rf_lower.replace("/", " ").replace("-", " ").split())
        if asked_words & rf_words:
            return rf
    return None


def _extract_requested_room(text: str) -> Optional[str]:
    lowered = text.lower()
    for name in _ROOM_NAMES:
        if name.lower() in lowered:
            return name
    alias = _ROOM_PATTERN.search(lowered)
    if alias:
        letter = alias.group(1).upper()
        return f"Room {letter}"
    if "punkt" in lowered:
        return "Punkt.Null"
    return None


def _extract_anchor(text: str) -> Tuple[Optional[int], Optional[int], bool]:
    """
    Extract month, day, and whether "next year" is explicitly mentioned.
    Returns (month, day, force_next_year).
    """
    lowered = text.lower()
    # Detect "next year" pattern (handles "next year", "nächstes Jahr" for German)
    force_next_year = bool(
        re.search(r"\bnext\s+year\b", lowered)
        or re.search(r"\bnächstes?\s+jahr\b", lowered)
    )
    for name, month in _MONTHS.items():
        if name in lowered:
            day_match = re.search(rf"(\d{{1,2}})\s+(?:of\s+)?{name}", lowered)
            if day_match:
                try:
                    return month, int(day_match.group(1)), force_next_year
                except ValueError:
                    return month, None, force_next_year
            return month, None, force_next_year
    return None, None, force_next_year


def _event_requirements(event_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not event_entry:
        return {}
    requirements = event_entry.get("requirements")
    if isinstance(requirements, dict):
        return requirements
    return {}


def _event_attendees(event_entry: Optional[Dict[str, Any]]) -> Optional[int]:
    requirements = _event_requirements(event_entry)
    value = requirements.get("number_of_participants")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_layout(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    requirements = _event_requirements(event_entry)
    layout = requirements.get("seating_layout")
    if isinstance(layout, str) and layout.strip():
        return layout
    return None


def _event_room(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not event_entry:
        return None
    locked = event_entry.get("locked_room_id")
    if locked:
        return locked
    requirements = _event_requirements(event_entry)
    preferred = requirements.get("preferred_room")
    if preferred:
        return preferred
    return None


def _event_date_iso(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    """Get event date in ISO format from various sources in event_entry."""
    if not event_entry:
        return None

    # Source 1: requested_window.date_iso (from time window capture)
    window = event_entry.get("requested_window") or {}
    iso_value = window.get("date_iso")
    if iso_value:
        return iso_value

    # Source 2: chosen_date (confirmed date)
    chosen = event_entry.get("chosen_date")
    if chosen:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(chosen, fmt)
                return parsed.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    # Source 3: captured.date (from global capture or step capture)
    captured = event_entry.get("captured") or {}
    captured_date = captured.get("date") or captured.get("event_date")
    if captured_date:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(captured_date, fmt)
                return parsed.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    # Source 4: Event Date field (legacy)
    event_date = event_entry.get("Event Date")
    if event_date:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(event_date, fmt)
                return parsed.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue

    return None


def _missing_fields(step: int, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    missing: List[str] = []
    if not event_entry:
        if step == 2:
            missing.extend(["date", "time"])
        return missing

    if step == 2:
        window = event_entry.get("requested_window") or {}
        if not window.get("date_iso"):
            missing.append("date")
        if not (window.get("start_time") and window.get("end_time")):
            missing.append("time")
    elif step == 3:
        if not event_entry.get("locked_room_id"):
            missing.append("room")
        requirements = _event_requirements(event_entry)
        if not requirements.get("number_of_participants"):
            missing.append("attendees")
        if not requirements.get("seating_layout"):
            missing.append("layout")
    elif step == 4:
        products = event_entry.get("products") or []
        selected = event_entry.get("selected_products") or []
        if not products and not selected:
            missing.append("products")
        event_data = event_entry.get("event_data") or {}
        catering_pref = str(event_data.get("Catering Preference") or "").strip()
        if not catering_pref or catering_pref.lower() == "not specified":
            missing.append("catering")
    return missing


def _rooms_by_feature_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
    attendees: Optional[int],
    layout: Optional[str],
    extraction: Optional[Dict[str, Any]] = None,
    db: Optional[Dict[str, Any]] = None,
) -> List[str]:
    requested_room = _extract_requested_room(text)
    feature_tokens = _extract_feature_tokens(text, extraction)
    # NO DEFAULT: Only check features if user explicitly asked about them
    # "Natural daylight" was a noise-causing default - removed
    features_to_check = feature_tokens

    # If asking about a SPECIFIC room's features (e.g., "Does Room A have a projector?"),
    # just answer directly - don't list alternatives. Let _room_features_response handle it.
    if requested_room and feature_tokens:
        room_features = [f.lower() for f in (list_room_features(requested_room) or [])]
        has_all = all(
            any(asked.lower() in rf for rf in room_features)
            for asked in feature_tokens
        )
        feature_list = ", ".join(feature_tokens)
        if has_all:
            return [f"Yes, {requested_room} has {feature_list}."]
        else:
            # Check which ones are available
            available = [f for f in feature_tokens if any(f.lower() in rf for rf in room_features)]
            missing = [f for f in feature_tokens if f not in available]
            if available and missing:
                return [f"{requested_room} has {', '.join(available)}, but {', '.join(missing)} is not included."]
            elif missing:
                return [f"{requested_room} doesn't have {', '.join(missing)} as standard equipment."]

    info_lines: List[str] = []

    if requested_room and attendees is not None and not fits_capacity(requested_room, attendees, layout):
        descriptor = f"{attendees} guests"
        if layout:
            descriptor = f"{attendees} guests in {layout}"
        info_lines.append(f"{requested_room} cannot comfortably host {descriptor}.")
        alternatives = alternative_rooms(_event_date_iso(event_entry), attendees, layout)
        if alternatives:
            for alt in alternatives[:3]:
                cap_text = ""
                if alt.get("layout_max"):
                    cap_text = f" ({layout or 'requested layout'} up to {alt['layout_max']})"
                elif alt.get("max"):
                    cap_text = f" (up to {alt['max']} guests)"
                info_lines.append(f"Consider {alt['name']}{cap_text}.")
        if not info_lines:
            info_lines.append("Let me know if you'd like me to suggest another room.")
        return _with_preface(info_lines, f"I checked {requested_room} for you:")

    # Only list alternative rooms if NOT asking about a specific room
    if not requested_room:
        for feature in features_to_check:
            rooms = list_rooms_by_feature(feature, min_capacity=attendees, layout=layout)
            if rooms:
                for room in rooms[:3]:
                    layout_cap = room.get("layout_capacity")
                    capacity_bits: List[str] = []
                    if layout_cap:
                        capacity_bits.append(f"{layout or 'layout'} up to {layout_cap}")
                    elif room.get("max_capacity"):
                        capacity_bits.append(f"up to {room['max_capacity']} guests")
                    feature_bits = room.get("features") or []
                    highlight = ", ".join(feature_bits[:2]) if feature_bits else feature
                    cap_text = f" ({'; '.join(capacity_bits)})" if capacity_bits else ""
                    suffix = f"; {highlight}" if highlight else ""
                    info_lines.append(f"{room['name']}{cap_text}{suffix}.")
                break

    if requested_room and not info_lines:
        feature_list = list_room_features(requested_room)
        if feature_list:
            primary = ", ".join(feature_list[:3])
            info_lines.append(f"{requested_room} includes {primary}.")

    # Fallback: List rooms when asking general availability question
    # (no specific room, no specific features)
    if not info_lines and not requested_room and not feature_tokens:
        # Get event date and ID for date-aware filtering
        event_date = _event_date_iso(event_entry)
        event_id = event_entry.get("event_id") if event_entry else None

        # Fallback: Try to extract date from message text if not in event_entry
        display_date = None
        if not event_date and text:
            extracted = _extract_date_from_text(text)
            if extracted:
                event_date = extracted[0]  # ISO format
                display_date = extracted[1]  # Display format

        # Format display date for user-friendly message
        if event_date and not display_date:
            try:
                parsed = datetime.strptime(event_date, "%Y-%m-%d")
                display_date = parsed.strftime("%d.%m.%Y")
            except ValueError:
                display_date = event_date

        # Get rooms, filtered by date availability if possible
        all_rooms, is_date_filtered = _list_all_rooms_for_qna(
            min_capacity=attendees,
            event_date=event_date,
            db=db,
            event_id=event_id,
        )

        if all_rooms:
            # Date-aware header when we have a date
            if display_date and is_date_filtered:
                info_lines.append(f"On {display_date}, we have the following rooms available:")
            elif display_date:
                info_lines.append(f"For {display_date}, we have the following rooms:")
            else:
                info_lines.append("We have the following rooms available:")

            for room in all_rooms:
                cap_str = f"up to {room['max_capacity']} guests" if room.get('max_capacity') else ""
                feat_str = ", ".join(room.get('features', [])[:2])
                if cap_str and feat_str:
                    info_lines.append(f"• {room['name']} ({cap_str}) - {feat_str}")
                elif cap_str:
                    info_lines.append(f"• {room['name']} ({cap_str})")
                else:
                    info_lines.append(f"• {room['name']}")
        elif display_date and is_date_filtered:
            # No rooms available on requested date - suggest alternatives
            info_lines.append(f"Unfortunately, all our rooms are fully booked on {display_date}.")
            # Get month from date for alternative suggestions
            try:
                parsed = datetime.strptime(event_date, "%Y-%m-%d")
                free_dates = list_free_dates(anchor_month=parsed.month, count=3, db=db)
                if free_dates:
                    dates_str = ", ".join(free_dates[:3])
                    info_lines.append(f"However, we have availability on: {dates_str}")
            except (ValueError, TypeError):
                pass  # Skip alternative suggestions if date parsing fails

    # Final fallback if still empty
    if not info_lines:
        info_lines.append("All rooms include Wi-Fi, daylight, and flexible seating.")

    # Only use preface for general queries, not specific room questions
    if feature_tokens and not requested_room:
        joined = ", ".join(feature_tokens)
        preface = f"Rooms with {joined}:"
        return _with_preface(info_lines, preface)

    return info_lines


def _room_features_response(text: str, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    requested_room = _extract_requested_room(text) or _event_room(event_entry)
    if not requested_room:
        return [
            "Happy to outline the equipment — just let me know which room you have in mind.",
        ]

    text_lower = text.lower()
    info: List[str] = []

    # Check for specific topic questions: accessibility or rate inclusions
    asks_accessibility = any(kw in text_lower for kw in [
        "wheelchair", "accessible", "accessibility", "disabled", "disability",
        "step-free", "elevator", "lift", "mobility"
    ])
    asks_rate_inclusions = any(kw in text_lower for kw in [
        "included in the rate", "included in the price", "what's included",
        "whats included", "comes with", "rate include", "price include",
        "included with"
    ])

    # Get full room data including accessibility and rate_inclusions
    from services.qna_readonly import load_room_static
    room_static = load_room_static(requested_room)

    if asks_accessibility:
        accessibility = room_static.get("accessibility") or {}
        if accessibility:
            acc_info = []
            if accessibility.get("wheelchair_accessible"):
                acc_info.append("wheelchair accessible")
            if accessibility.get("elevator_access"):
                acc_info.append("elevator access")
            if accessibility.get("step_free_entry"):
                acc_info.append("step-free entry")
            if accessibility.get("accessible_bathroom"):
                acc_info.append("accessible bathroom on-site")
            notes = accessibility.get("notes")
            if acc_info:
                info.append(f"Yes, {requested_room} is fully accessible: {', '.join(acc_info)}.")
            if notes:
                info.append(notes)
        else:
            info.append(f"{requested_room} offers standard accessibility. Contact us for specific requirements.")
        # Direct answer - no preface needed
        return info

    if asks_rate_inclusions:
        rate_inclusions = room_static.get("rate_inclusions") or []
        if rate_inclusions:
            inclusions_text = ", ".join(rate_inclusions)
            info.append(f"The room rate includes: {inclusions_text}.")
        else:
            info.append(f"The room rate includes standard amenities. Contact us for details.")
        # Direct answer - no preface needed
        return info

    # Check if asking about specific features (projector, screen, wifi, etc.)
    asked_features = _extract_feature_tokens(text)
    if asked_features:
        room_features = [f.lower() for f in (list_room_features(requested_room) or [])]
        has_all = all(
            any(asked.lower() in rf for rf in room_features)
            for asked in asked_features
        )
        feature_list = ", ".join(asked_features)
        if has_all:
            info.append(f"Yes, {requested_room} has {feature_list}.")
        else:
            # Check which ones are available
            available = [f for f in asked_features if any(f.lower() in rf for rf in room_features)]
            missing = [f for f in asked_features if f not in available]
            if available and missing:
                info.append(f"{requested_room} has {', '.join(available)}, but {', '.join(missing)} is not included.")
            elif missing:
                info.append(f"{requested_room} doesn't have {', '.join(missing)} as standard equipment.")
        # Direct answer - no preface needed
        return info

    # Generic room features question - keep it brief
    features = list_room_features(requested_room)
    if not features:
        return [f"{requested_room} offers Wi-Fi, daylight, and flexible seating as standard."]

    highlights = ", ".join(features[:5])
    return [f"{requested_room} includes {highlights}."]


def _accessibility_response(text: str, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    """Generate response for accessibility inquiries."""
    requested_room = _extract_requested_room(text) or _event_room(event_entry)
    if not requested_room:
        return [
            "Our venue is fully accessible with step-free entry, elevators, and accessible bathrooms. Which room would you like details about?",
        ]

    from services.qna_readonly import load_room_static
    room_static = load_room_static(requested_room)
    accessibility = room_static.get("accessibility") or {}

    if not accessibility:
        return [f"{requested_room} offers standard accessibility. Contact us for specific requirements."]

    info: List[str] = []
    acc_features = []
    if accessibility.get("wheelchair_accessible"):
        acc_features.append("wheelchair accessible")
    if accessibility.get("elevator_access"):
        acc_features.append("elevator access")
    if accessibility.get("step_free_entry"):
        acc_features.append("step-free entry")
    if accessibility.get("accessible_bathroom"):
        acc_features.append("accessible bathroom on-site")

    if acc_features:
        info.append(f"Yes, {requested_room} is fully accessible: {', '.join(acc_features)}.")

    notes = accessibility.get("notes")
    if notes:
        info.append(notes)

    if not info:
        info.append(f"{requested_room} offers standard accessibility features.")

    return info


def _rate_inclusions_response(text: str, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    """Generate response for rate inclusions inquiries."""
    requested_room = _extract_requested_room(text) or _event_room(event_entry)
    if not requested_room:
        return [
            "Room rates typically include WiFi, basic AV equipment, and standard furniture. Which room would you like details about?",
        ]

    from services.qna_readonly import load_room_static
    room_static = load_room_static(requested_room)
    rate_inclusions = room_static.get("rate_inclusions") or []

    if not rate_inclusions:
        return [f"The room rate for {requested_room} includes standard amenities. Contact us for details."]

    inclusions_text = ", ".join(rate_inclusions)
    return [f"The {requested_room} rate includes: {inclusions_text}."]


def _catering_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
) -> List[str]:
    """
    ═══════════════════════════════════════════════════════════════════════════════
    Q&A CATERING DETOUR CONTEXT RULE (Jan 12, 2026)
    ═══════════════════════════════════════════════════════════════════════════════

    When answering catering Q&A during a detour, use the DETOURED context:

    PRIORITY ORDER:
    1. If detoured with NEW room AND room is available:
       → Show catering for the NEW room

    2. If room is being re-evaluated (detour in progress) but date is confirmed:
       → Show ALL catering options from ALL rooms on that date

    3. If BOTH date and room are uncertain (double detour or no confirmation):
       → Show catering available in the CURRENT MONTH
       → If past the 20th: Also show NEXT month's options
       → Format: "In February: [list], In March: [list]"

    4. EXCLUSION RULE: If a room is unavailable for remaining days of month,
       exclude that room's UNIQUE catering options (options only that room has).
       Shared options from other rooms are still shown.

    The event_entry values are already UPDATED by the detour handler before
    Q&A is called, so we use event_entry directly (not cached/stale values).
    ═══════════════════════════════════════════════════════════════════════════════
    """
    # Get current context (already updated by detour if applicable)
    room = _event_room(event_entry)
    date_token = _event_date_iso(event_entry)
    date_confirmed = (event_entry or {}).get("date_confirmed", False)
    room_confirmed = bool((event_entry or {}).get("locked_room_id"))

    # Detect detour context
    caller_step = (event_entry or {}).get("caller_step")
    is_in_detour = caller_step is not None

    # Determine category filter from question text
    categories: Optional[List[str]] = None
    lowered = text.lower()
    if "drink" in lowered or "beverage" in lowered:
        categories = ["beverages"]
    elif "package" in lowered or "menu" in lowered or "catering" in lowered:
        categories = ["package"]

    # === PRIORITY 1: New room confirmed and available ===
    if room_confirmed and room:
        options = list_catering(room_id=room, date_token=date_token, categories=categories)
        preface = f"Here are catering options for {room}:"
        if date_token:
            preface = f"Here are catering options for {room} on {_format_date(date_token)}:"

    # === PRIORITY 2: Date confirmed but room being re-evaluated ===
    elif date_confirmed and date_token and not room_confirmed:
        # Show ALL catering from all rooms on this date
        options = list_catering(room_id=None, date_token=date_token, categories=categories)
        preface = f"Here are all catering options available on {_format_date(date_token)}:"

    # === PRIORITY 3: Both uncertain - show monthly availability ===
    elif not date_confirmed or not room_confirmed:
        options = list_catering(room_id=None, date_token=None, categories=categories)
        # Check if we're past the 20th of current month
        today = datetime.now()
        current_month = today.strftime("%B")
        if today.day > 20:
            next_month_date = today.replace(day=28)
            try:
                from datetime import timedelta
                next_month_date = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            except Exception:
                pass
            next_month = next_month_date.strftime("%B")
            preface = f"In {current_month} and {next_month}, we offer these catering options:"
        else:
            preface = f"In {current_month}, we offer these catering options:"

    # === DEFAULT: Use whatever context we have ===
    else:
        options = list_catering(room_id=room, date_token=date_token, categories=categories)
        if room and date_token:
            preface = f"Here are catering ideas that work well in {room} on your requested date:"
        elif room:
            preface = f"Here are catering ideas that work well in {room}:"
        else:
            preface = "Here are a few catering ideas we can arrange:"

    # Format response
    info: List[str] = []
    for entry in options[:4]:
        name = entry.get("name") or "Option"
        price = entry.get("price_per_person") or entry.get("price")
        descriptor = entry.get("description")
        price_text = f" — CHF {price}" if price else ""
        if categories == ["beverages"] and entry.get("options"):
            descriptor = ", ".join(entry["options"])
        if descriptor:
            info.append(f"{name}{price_text}: {descriptor}.")
        else:
            info.append(f"{name}{price_text}.")

    if not info:
        if is_in_detour:
            info.append("I'll confirm catering options once we finalize the room and date.")
        elif room:
            info.append(f"I'll pull the detailed catering menus for {room} once we confirm the room and date.")
        else:
            info.append("Catering menus are available once we confirm the room/date combination.")

    # Override preface for specific category questions ONLY if not in context-aware mode
    # (context-aware mode = already set a specific preface based on room/date context)
    context_aware = room_confirmed or (date_confirmed and date_token) or is_in_detour
    if not context_aware:
        if categories == ["beverages"]:
            preface = "Here are beverage pairings we can set up for you:"
        elif categories == ["package"]:
            preface = "Here are our catering packages:"

    return _with_preface(info, preface)


def _format_date(date_iso: str) -> str:
    """Format ISO date to readable format (e.g., '2026-02-25' -> 'February 25')."""
    try:
        dt = datetime.strptime(date_iso, "%Y-%m-%d")
        return dt.strftime("%B %d").replace(" 0", " ")
    except Exception:
        return date_iso


def _products_response(
    event_entry: Optional[Dict[str, Any]],
) -> List[str]:
    room = _event_room(event_entry)
    items = list_products(room_id=room)
    info: List[str] = []
    for item in items[:4]:
        name = item.get("name")
        category = item.get("category")
        if category:
            info.append(f"{name} — {category.upper()} add-on.")
        else:
            info.append(f"{name}.")
    if not info:
        info.append("Add-on equipment menus unlock after we lock a room.")
    if room:
        preface = f"Here are some add-ons that pair nicely with {room}:"
    else:
        preface = "Here are the add-ons most teams choose:"
    return _with_preface(info, preface)


def _dates_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]],
) -> List[str]:
    anchor_month, anchor_day, force_next_year = _extract_anchor(text)
    preferred_room = _event_room(event_entry) or "Room A"
    dates = list_free_dates(
        anchor_month, anchor_day, count=5, db=db,
        preferred_room=preferred_room, force_next_year=force_next_year
    )
    info: List[str] = []
    for value in dates[:5]:
        info.append(f"{value} — {preferred_room} currently shows as free.")
    if not info:
        info.append("I can suggest dates once I have a preferred month or room.")
    preface: Optional[str] = None
    if anchor_month:
        try:
            month_name = datetime(2000, anchor_month, 1).strftime("%B")
        except ValueError:
            month_name = None
        if month_name and anchor_day:
            preface = f"Around {anchor_day} {month_name}, these slots are open in {preferred_room}:"
        elif month_name:
            preface = f"Here are a few {month_name} dates when {preferred_room} is available:"
    if not preface:
        preface = f"Here are upcoming dates when {preferred_room} is available:"
    return _with_preface(info, preface)


def _site_visit_response() -> List[str]:
    info = [
        "Site visits run Tuesday–Thursday between 10:00 and 18:00.",
        "We need a confirmed event date and time window before booking the tour.",
    ]
    return _with_preface(info, "Here's how site visits work at our venue:")


def _general_response(event_entry: Optional[Dict[str, Any]]) -> List[str]:
    """Generate dynamic general response based on actual room features from database."""
    step = _current_step(event_entry)

    # Get common features from database
    common_features = list_common_room_features(max_features=4)

    if step == 2:
        # Informational only - CTA is always at the end of Step 2 handler's message
        if common_features:
            feature_text = ", ".join(common_features)
            return [f"Our rooms feature {feature_text}."]
        return ["Our rooms are fully equipped for meetings and events."]

    if step == 3:
        # Only room info here - CTA is always at the end of Step 3 handler's message
        if common_features:
            feature_text = ", ".join(common_features[:3])
            return [f"All rooms include {feature_text}."]
        return ["All rooms include standard meeting equipment."]

    # Informational only - CTAs are handled by step handlers
    return [
        "Feel free to ask about rooms, catering, equipment, or site visits.",
    ]


def _parking_response() -> List[str]:
    info = [
        "Underground parking at Europaallee is two minutes from the venue with direct lift access.",
        "We can arrange a short-term loading permit for equipment drop-off with 24 hours' notice.",
    ]
    return _with_preface(info, "Thanks for checking on parking — here's what we can arrange nearby:")


def _pricing_response() -> List[str]:
    """Return room rate card (no date/room confirmation required)."""
    from workflows.steps.step3_room_availability.db_pers import load_rooms_config

    rooms = load_rooms_config() or []
    info_lines: List[str] = []

    for room in rooms[:5]:  # Show top 5 rooms
        name = room.get("name")
        hourly = room.get("hourly_rate")
        half_day = room.get("half_day_rate")
        full_day = room.get("full_day_rate")

        parts = []
        if hourly:
            parts.append(f"CHF {hourly}/hr")
        if half_day:
            parts.append(f"CHF {half_day} half-day")
        if full_day:
            parts.append(f"CHF {full_day}/day")

        if parts:
            info_lines.append(f"- **{name}**: {', '.join(parts)}")

    if not info_lines:
        info_lines.append("Contact us for custom pricing based on your event details.")

    info_lines.append("")
    info_lines.append("Final pricing depends on your event date, duration, and any add-ons.")
    return _with_preface(info_lines, "Here's our room rate structure:")


def _step_index_from_anchor(anchor: Optional[str]) -> Optional[int]:
    if not anchor:
        return None
    lookup = {
        "date confirmation": 2,
        "room availability": 3,
        "offer review": 4,
        "site visit": 5,
        "follow-up": 7,
    }
    return lookup.get(anchor.strip().lower())


def _qna_target_step(qna_type: str) -> Optional[int]:
    mapping = {
        "free_dates": 2,
        "rooms_by_feature": 3,
        "room_features": 3,
        "catering_for": 4,
        "products_for": 4,
        "site_visit_overview": 5,
    }
    return mapping.get(qna_type)


def route_general_qna(
    msg: Dict[str, Any],
    event_entry_before: Optional[Dict[str, Any]],
    event_entry_after: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build deterministic INFO/NEXT STEP blocks for any general Q&A detected in the turn.
    """

    text = _message_text(msg)
    active_entry = event_entry_after or event_entry_before
    extraction = _get_cached_extraction(active_entry)
    requirements = _event_requirements(active_entry)
    fallback_attendees = requirements.get("number_of_participants")
    attendees = _extract_attendees(text, fallback_attendees, extraction)
    layout = _extract_layout(text, requirements.get("seating_layout"), extraction)

    current_step = _current_step(active_entry)
    anchor_name = classification.get("step_anchor")
    anchor_step = _step_index_from_anchor(anchor_name)
    resume_step_idx = anchor_step or current_step
    missing = _missing_fields(resume_step_idx, active_entry)

    qna_types: List[str] = list(classification.get("secondary") or [])
    if not qna_types and classification.get("primary") == "general_qna":
        qna_types = ["general"]

    blocks_pre: List[Dict[str, Any]] = []
    blocks_post: List[Dict[str, Any]] = []

    thread_id = _thread_id(msg, active_entry)
    if thread_id:
        trace_qa_enter(thread_id, ",".join(qna_types) if qna_types else "general")

    for qna_type in qna_types:
        if qna_type == "general":
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = resume_step_idx
        elif qna_type == "rooms_by_feature":
            info_lines = _rooms_by_feature_response(text, active_entry, attendees, layout, extraction, db=db)
            topic = "rooms_by_feature"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "room_features":
            info_lines = _room_features_response(text, active_entry)
            topic = "room_features"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "catering_for":
            info_lines = _catering_response(text, active_entry)
            topic = "catering_for"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "products_for":
            info_lines = _products_response(active_entry)
            topic = "products_for"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "free_dates":
            info_lines = _dates_response(text, active_entry, db)
            topic = "free_dates"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "site_visit_overview":
            info_lines = _site_visit_response()
            topic = "site_visit_overview"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "parking_policy":
            info_lines = _parking_response()
            topic = "parking_policy"
            target_step_idx = resume_step_idx
        elif qna_type == "accessibility_inquiry":
            info_lines = _accessibility_response(text, active_entry)
            topic = "accessibility_inquiry"
            target_step_idx = resume_step_idx
        elif qna_type == "pricing_inquiry":
            info_lines = _pricing_response()
            topic = "pricing_inquiry"
            target_step_idx = resume_step_idx
        else:
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = resume_step_idx

        if current_step <= 1 and qna_type not in {"free_dates", "site_visit_overview"}:
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = current_step

        info_block = build_info_block(info_lines)
        next_step_block = build_next_step_line(anchor_name or resume_step_idx, missing)
        body = "\n\n".join([info_block, next_step_block])

        block_payload = {
            "body": body,
            "topic": topic,
            "step": target_step_idx,
            "requires_approval": False,
        }

        target_anchor = _qna_target_step(qna_type)
        active_anchor = anchor_step or current_step
        destination = blocks_post
        if target_anchor is not None and target_anchor == active_anchor:
            destination = blocks_pre

        destination.append(block_payload)

    result = {
        "pre_step": blocks_pre,
        "post_step": blocks_post,
        "resume_step": anchor_name or resume_step_idx,
        "missing_fields": missing,
        "status": (active_entry or {}).get("status"),
        "thread_state": (active_entry or {}).get("thread_state"),
    }
    if thread_id:
        trace_qa_exit(thread_id, "general_qna")
    return result


def _thread_id(msg: Dict[str, Any], event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if msg.get("thread_id"):
        return str(msg["thread_id"])
    if event_entry and event_entry.get("event_id"):
        return str(event_entry["event_id"])
    if msg.get("msg_id"):
        return str(msg["msg_id"])
    return None


def route_multi_variable_qna(
    msg: Dict[str, Any],
    event_entry_before: Optional[Dict[str, Any]],
    event_entry_after: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]],
    classification: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Route multi-variable Q&A with conjunction analysis.

    Uses the conjunction analyzer to determine the relationship between Q&A parts:
    - independent: Different selects → separate answer sections
    - and_combined: Same select, compatible conditions → single combined answer
    - or_union: Same select, conflicting conditions → ranked results

    Returns None if no multi-variable Q&A detected, otherwise returns composed result.
    """
    # MIGRATED: from llm.intent_classifier -> backend.detection.intent.classifier
    from detection.intent.classifier import spans_multiple_steps
    from workflows.qna.conjunction import analyze_conjunction

    secondary: List[str] = list(classification.get("secondary") or [])

    # Only use multi-variable routing if there are multiple Q&A types
    if len(secondary) < 2:
        return None

    text = _message_text(msg)

    # Analyze the conjunction relationship
    conjunction = analyze_conjunction(secondary, text)

    # If independent (different selects), we can use the existing behavior
    # but mark it as multi-variable for debugging
    if conjunction.relationship == "independent":
        result = route_general_qna(msg, event_entry_before, event_entry_after, db, classification)
        result["multi_variable"] = True
        result["conjunction_relationship"] = "independent"
        result["qna_parts_count"] = len(conjunction.parts)
        return result

    # For and_combined or or_union, we need specialized handling
    active_entry = event_entry_after or event_entry_before
    requirements = _event_requirements(active_entry)

    if conjunction.relationship == "and_combined":
        # Combine conditions and query once
        combined_result = _route_combined_qna(
            conjunction, text, active_entry, requirements, db, classification
        )
        combined_result["multi_variable"] = True
        combined_result["conjunction_relationship"] = "and_combined"
        return combined_result

    elif conjunction.relationship == "or_union":
        # Query with ranking
        ranked_result = _route_ranked_union_qna(
            conjunction, text, active_entry, requirements, db, classification
        )
        ranked_result["multi_variable"] = True
        ranked_result["conjunction_relationship"] = "or_union"
        return ranked_result

    return None


def _route_combined_qna(
    conjunction: Any,
    text: str,
    active_entry: Optional[Dict[str, Any]],
    requirements: Dict[str, Any],
    db: Optional[Dict[str, Any]],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Route Q&A with combined AND conditions.
    """
    from workflows.qna.conjunction import get_combined_conditions

    parts = conjunction.parts
    if not parts:
        return {"pre_step": [], "post_step": [], "status": "error"}

    select_type = parts[0].select
    combined_conditions = get_combined_conditions(parts)
    extraction = _get_cached_extraction(active_entry)

    # Build info lines based on select type with combined conditions
    fallback_attendees = requirements.get("number_of_participants")
    attendees = combined_conditions.get("capacity") or _extract_attendees(text, fallback_attendees, extraction)
    layout = _extract_layout(text, requirements.get("seating_layout"), extraction)

    current_step = _current_step(active_entry)

    if select_type == "rooms":
        info_lines = _rooms_by_feature_response(text, active_entry, attendees, layout, extraction, db=db)
        topic = "rooms_combined"
    elif select_type == "menus":
        info_lines = _catering_response(text, active_entry)
        topic = "menus_combined"
    elif select_type == "dates":
        info_lines = _dates_response(text, active_entry, db)
        topic = "dates_combined"
    else:
        info_lines = _general_response(active_entry)
        topic = "general_combined"

    # Build header describing combined query
    header_parts = []
    if combined_conditions.get("month"):
        header_parts.append(f"in {combined_conditions['month'].title()}")
    if combined_conditions.get("features"):
        header_parts.append(f"with {', '.join(combined_conditions['features'])}")
    header_suffix = " ".join(header_parts) if header_parts else ""
    header = f"{select_type.title()} {header_suffix}".strip()

    info_block = build_info_block(info_lines)
    anchor_name = classification.get("step_anchor")
    missing = _missing_fields(current_step, active_entry)
    next_step_block = build_next_step_line(anchor_name or current_step, missing)
    body = "\n\n".join([f"**{header}:**", info_block, next_step_block])

    block_payload = {
        "body": body,
        "topic": topic,
        "step": current_step,
        "requires_approval": False,
        "combined_conditions": combined_conditions,
    }

    return {
        "pre_step": [],
        "post_step": [block_payload],
        "resume_step": anchor_name or current_step,
        "missing_fields": missing,
        "status": (active_entry or {}).get("status"),
        "thread_state": (active_entry or {}).get("thread_state"),
    }


def _route_ranked_union_qna(
    conjunction: Any,
    text: str,
    active_entry: Optional[Dict[str, Any]],
    requirements: Dict[str, Any],
    db: Optional[Dict[str, Any]],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Route Q&A with OR conditions (ranked union).
    Shows items matching ALL conditions first.
    """
    from workflows.qna.conjunction import get_union_conditions

    parts = conjunction.parts
    if not parts:
        return {"pre_step": [], "post_step": [], "status": "error"}

    select_type = parts[0].select
    union_conditions = get_union_conditions(parts)

    current_step = _current_step(active_entry)

    # Collect all features from all conditions
    all_features = set()
    for cond in union_conditions:
        all_features.update(cond.get("features", []))

    if select_type == "rooms":
        # Get rooms matching any of the features
        info_lines = _rooms_by_multiple_features_response(list(all_features), active_entry)
        topic = "rooms_ranked"
    else:
        info_lines = _general_response(active_entry)
        topic = "general_ranked"

    header = f"{select_type.title()} by Features"

    info_block = build_info_block(info_lines)
    anchor_name = classification.get("step_anchor")
    missing = _missing_fields(current_step, active_entry)
    next_step_block = build_next_step_line(anchor_name or current_step, missing)
    body = "\n\n".join([f"**{header}:**", info_block, "Items matching most features shown first.", next_step_block])

    block_payload = {
        "body": body,
        "topic": topic,
        "step": current_step,
        "requires_approval": False,
        "union_conditions": union_conditions,
    }

    return {
        "pre_step": [],
        "post_step": [block_payload],
        "resume_step": anchor_name or current_step,
        "missing_fields": missing,
        "status": (active_entry or {}).get("status"),
        "thread_state": (active_entry or {}).get("thread_state"),
    }


def _rooms_by_multiple_features_response(
    features: List[str],
    active_entry: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Get rooms matching multiple features with ranking.
    Rooms matching more features appear first.
    """
    if not features:
        return ["No specific features requested."]

    # Get all rooms with their features
    all_rooms = list_rooms_by_feature(None)  # Get all rooms

    # Score each room by how many requested features it has
    scored_rooms: List[Tuple[str, int, List[str]]] = []
    for room in all_rooms:
        room_features = set(f.lower() for f in (room.get("features") or []))
        matched = [f for f in features if f.lower() in room_features]
        if matched:
            scored_rooms.append((room.get("name", "Room"), len(matched), matched))

    if not scored_rooms:
        return [f"No rooms found with requested features: {', '.join(features)}"]

    # Sort by score descending
    scored_rooms.sort(key=lambda x: x[1], reverse=True)

    lines = []
    for name, score, matched in scored_rooms:
        if score == len(features):
            lines.append(f"• {name} - matches all ({', '.join(matched)})")
        else:
            lines.append(f"• {name} - matches {score}/{len(features)} ({', '.join(matched)})")

    return lines


def generate_hybrid_qna_response(
    qna_types: List[str],
    message_text: str,
    event_entry: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Generate Q&A response text for hybrid messages (booking + Q&A).

    Called from step handlers when unified detection finds qna_types alongside
    a booking intent. Returns markdown text to append to the booking response,
    or None if no Q&A types to process.

    Args:
        qna_types: List of Q&A types detected (e.g., ["catering_for", "free_dates"])
        message_text: Original message text for context extraction
        event_entry: Event record for context (attendees, room, etc.)
        db: Database for date availability checks

    Returns:
        Markdown string with Q&A answers, or None if no answers generated
    """
    if not qna_types:
        return None

    # Filter out types that are handled by the main workflow (not pure Q&A)
    pure_qna_types = [
        t for t in qna_types
        if t in {
            "catering_for", "products_for", "free_dates", "check_availability",
            "room_features", "rooms_by_feature", "parking_policy", "pricing_inquiry",
            "site_visit_overview", "general", "accessibility_inquiry", "rate_inclusions"
        }
    ]

    if not pure_qna_types:
        return None

    extraction = _get_cached_extraction(event_entry)
    requirements = _event_requirements(event_entry)
    fallback_attendees = requirements.get("number_of_participants")
    attendees = _extract_attendees(message_text, fallback_attendees, extraction)
    layout = _extract_layout(message_text, requirements.get("seating_layout"), extraction)

    # DEDUPLICATION: If asking about a specific room's features, only use ONE handler
    # "rooms_by_feature" and "room_features" both answer "Does Room A have X?"
    requested_room = _extract_requested_room(message_text)
    feature_tokens = _extract_feature_tokens(message_text, extraction)
    is_specific_room_feature_question = requested_room and feature_tokens

    if is_specific_room_feature_question and requested_room:
        # For "Does Room A have a projector?" - just answer directly, no multiple sections
        room_features = list_room_features(requested_room) or []

        # Use smarter matching that handles variations
        matched_features: List[str] = []
        missing_features: List[str] = []

        for asked in feature_tokens:
            actual = _find_matching_feature(asked, room_features)
            if actual:
                matched_features.append(actual)
            else:
                missing_features.append(asked)

        if matched_features and not missing_features:
            # All asked features found - format nicely
            feature_display = ", ".join(matched_features)
            return f"Yes, **{requested_room}** has {feature_display}."
        elif matched_features and missing_features:
            return f"**{requested_room}** has {', '.join(matched_features)}, but {', '.join(missing_features)} is not included."
        elif missing_features:
            return f"**{requested_room}** doesn't have {', '.join(missing_features)} as standard equipment."
        else:
            # Fallback - list what the room has
            return f"**{requested_room}** includes: {', '.join(room_features[:5])}."

    # For other Q&A types, generate responses without verbose headers
    response_parts: List[str] = []

    for qna_type in pure_qna_types:
        info_lines: List[str] = []

        if qna_type == "catering_for":
            info_lines = _catering_response(message_text, event_entry)
        elif qna_type == "products_for":
            info_lines = _products_response(event_entry)
        elif qna_type in ("free_dates", "check_availability"):
            info_lines = _dates_response(message_text, event_entry, db)
        elif qna_type == "room_features":
            info_lines = _room_features_response(message_text, event_entry)
        elif qna_type == "rooms_by_feature":
            info_lines = _rooms_by_feature_response(message_text, event_entry, attendees, layout, extraction, db=db)
        elif qna_type == "parking_policy":
            info_lines = _parking_response()
        elif qna_type == "pricing_inquiry":
            info_lines = _pricing_response()
        elif qna_type == "site_visit_overview":
            info_lines = _site_visit_response()
        elif qna_type == "general":
            info_lines = _general_response(event_entry)
        elif qna_type == "accessibility_inquiry":
            info_lines = _accessibility_response(message_text, event_entry)
        elif qna_type == "rate_inclusions":
            info_lines = _rate_inclusions_response(message_text, event_entry)
        else:
            continue

        if info_lines:
            # Direct response - no section headers for simple Q&A
            # Join lines with spacing for readability
            response_parts.append("\n\n".join(info_lines))

    if not response_parts:
        return None

    # For multiple Q&A topics, separate with blank line (not ---)
    return "\n\n".join(response_parts)


__all__ = ["route_general_qna", "route_multi_variable_qna", "generate_hybrid_qna_response"]
