from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.adapters.agent_adapter import AgentAdapter, StubAgentAdapter, get_agent_adapter, reset_agent_adapter
from backend.domain import IntentLabel
from backend.llm.provider_registry import get_provider, reset_provider_for_tests
from backend.workflows.common.fallback_reason import create_fallback_reason

from backend.prefs.semantics import normalize_catering, normalize_products
from backend.services.products import list_product_records, normalise_product_payload
from backend.workflows.common.room_rules import (
    USER_INFO_KEYS,
    clean_text,
    normalize_language,
    normalize_phone,
    normalize_room,
    sanitize_participants,
)
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.datetime_parse import (
    parse_first_date,
    parse_time_range,
    month_name_to_number,
    weekday_name_to_number,
)
from backend.utils.dates import MONTH_INDEX_TO_NAME, from_hints

adapter: AgentAdapter = get_agent_adapter()
_LAST_CALL_METADATA: Dict[str, Any] = {}
_ANALYSIS_CACHE: Dict[str, Dict[str, Any]] = {}

logger = logging.getLogger(__name__)

_FALLBACK_ADAPTER = StubAgentAdapter()
_MAX_RETRIES = 2

_MONTHS = {name.lower(): idx for idx, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    start=1,
)}
_DAY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+of\s+([A-Za-z]+)\b", re.IGNORECASE)

_LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "u shape": "U-shape",
    "u-shaped": "U-shape",
    "boardroom": "Boardroom",
    "standing": "Standing reception",
    "cocktail": "Standing reception",
}

_FEATURE_KEYWORDS = {
    "projector": ["projector", "screen", "beamer"],
    "sound system": ["sound system", "speakers", "audio", "music"],
    "coffee service": ["coffee service", "coffee bar", "coffee", "barista", "espresso", "tea service"],
}

_TIME_OF_DAY_ALIASES = {
    "morning": "morning",
    "breakfast": "morning",
    "afternoon": "afternoon",
    "lunchtime": "afternoon",
    "evening": "evening",
    "dinner": "evening",
    "night": "evening",
}

_VAGUE_WEEKDAY_TOKENS = [
    "monday",
    "mon",
    "tuesday",
    "tue",
    "tues",
    "wednesday",
    "wed",
    "thursday",
    "thu",
    "thur",
    "thurs",
    "friday",
    "fri",
    "saturday",
    "sat",
    "sunday",
    "sun",
]

_ORDINAL_MAP = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}

_WEEK_INDEX_PATTERNS = [
    re.compile(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\s+week\b", re.IGNORECASE),
    re.compile(r"\bweek\s*(?:number\s*)?(?P<index>\d)\b", re.IGNORECASE),
]

_DAY_PAIR_PATTERNS = [
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:/|or)\s*(\d{1,2})(?:st|nd|rd|th)?\b"),
    re.compile(r"\(([^)]+)\)"),
]

_SINGLE_DAY_CONTEXT = re.compile(
    r"\b(?:around|on|between|for)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _extract_requirement_hints(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    layout = None
    for token, label in _LAYOUT_KEYWORDS.items():
        if token in lowered:
            layout = label
            break

    features: List[str] = []
    for label, keywords in _FEATURE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            features.append(label)

    catering = None
    if "coffee" in lowered or "barista" in lowered or "espresso" in lowered:
        catering = "Coffee service"

    return {"layout": layout, "features": features, "catering": catering}


def _match_catalog_products(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    catalog_names = [record.name for record in list_product_records()]
    agent_instance = _agent()
    if not hasattr(agent_instance, "match_catalog_items"):
        return []
    raw_matches = agent_instance.match_catalog_items(text, catalog_names)
    matches: List[Dict[str, Any]] = []
    if not raw_matches:
        return matches

    for entry in raw_matches:
        name: Optional[str]
        score: float
        if isinstance(entry, tuple) and entry:
            name = str(entry[0]) if entry[0] is not None else None
            try:
                score = float(entry[1]) if len(entry) > 1 else 0.0
            except (TypeError, ValueError):
                score = 0.0
        elif isinstance(entry, dict):
            name = entry.get("name")
            raw_score = entry.get("confidence")
            try:
                score = float(raw_score) if raw_score is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
        else:
            name = str(entry) if entry else None
            score = 0.65
        if not name:
            continue
        matches.append({"name": name, "confidence": max(0.0, min(1.0, score))})
    return matches


def _infer_date_from_body(body: str) -> Optional[str]:
    match = _DAY_RE.search(body or "")
    if not match:
        return None
    try:
        day = int(match.group(1))
    except ValueError:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if not month:
        return None
    clamped_day = max(1, min(day, 28))
    today = dt.date.today()
    try:
        candidate = dt.date(today.year, month, clamped_day)
    except ValueError:
        return None
    if candidate < today:
        candidate = dt.date(today.year + 1, month, clamped_day)
    return candidate.strftime("%Y-%m-%d")


def _agent() -> AgentAdapter:
    global adapter
    adapter = get_agent_adapter()
    return adapter

def _record_last_call(agent: AgentAdapter, phase: str) -> None:
    """Store metadata about the most recent adapter invocation for telemetry."""

    global _LAST_CALL_METADATA
    info: Dict[str, Any] = {}
    if hasattr(agent, "last_call_info"):
        try:
            raw = agent.last_call_info()  # type: ignore[attr-defined]
            if isinstance(raw, dict):
                info = dict(raw)
        except Exception:
            info = {}
    if not info and hasattr(agent, "describe"):
        try:
            raw_desc = agent.describe()
            if isinstance(raw_desc, dict):
                info = dict(raw_desc)
        except Exception:
            info = {}
    info.setdefault("phase", phase)
    if "model" not in info:
        phase_key = "intent_model" if phase == "intent" else "entity_model"
        if phase_key in info and info[phase_key]:
            info["model"] = info[phase_key]
    _LAST_CALL_METADATA = info

def last_call_metadata() -> Dict[str, Any]:
    """Expose metadata for the most recent adapter call."""

    return dict(_LAST_CALL_METADATA)


def _prepare_payload(message: Dict[str, Optional[str]]) -> Dict[str, str]:
    """[LLM] Ensure the adapter payload always provides subject/body strings."""

    payload = dict(message)
    payload["subject"] = payload.get("subject") or ""
    payload["body"] = payload.get("body") or ""
    return payload


def _analysis_cache_key(payload: Dict[str, str]) -> str:
    msg_id = payload.get("msg_id") or ""
    subject = payload.get("subject") or ""
    body = payload.get("body") or ""
    fingerprint = f"{msg_id}::{subject}::{body}"
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _validated_analysis(result: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    intent = result.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return None
    fields = result.get("fields") if isinstance(result.get("fields"), dict) else {}
    confidence_raw = result.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "intent": intent,
        "confidence": confidence,
        "fields": dict(fields),
    }


def _invoke_provider_with_retry(payload: Dict[str, str], phase: str) -> Optional[Dict[str, Any]]:
    provider = get_provider()
    text = json.dumps(payload, ensure_ascii=False)
    last_error: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            result = provider.classify_extract(text)
            validated = _validated_analysis(result)
            if validated is not None:
                try:
                    _record_last_call(_agent(), phase=phase)
                except Exception:  # pragma: no cover - defensive guard
                    pass
                return validated
            logger.warning("Provider returned invalid analysis payload on attempt %s", attempt + 1)
        except NotImplementedError as exc:
            last_error = exc
            break
        except Exception as exc:  # pragma: no cover - defensive guard
            last_error = exc
            logger.warning("Provider analysis failed (attempt %s): %s", attempt + 1, exc)
    if last_error:
        logger.info("Falling back to heuristics after provider failure: %s", last_error)
    return None


def _fallback_analysis(
    payload: Dict[str, str],
    original_error: Optional[str] = None,
) -> Dict[str, Any]:
    global _LAST_CALL_METADATA
    fallback_reason: Optional[str] = None
    fallback_error: Optional[str] = None

    try:
        result = _FALLBACK_ADAPTER.analyze_message(payload)
        validated = _validated_analysis(result)
        if validated is not None:
            _LAST_CALL_METADATA = {"phase": "analysis", "adapter": "stub"}
            return validated
        fallback_reason = "stub_returned_invalid"
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.debug("Stub fallback failed: %s", exc)
        fallback_reason = "stub_exception"
        fallback_error = str(exc)

    # If we had an original error from the provider, use that
    if original_error:
        fallback_reason = "provider_failed"
        fallback_error = original_error

    _LAST_CALL_METADATA = {
        "phase": "analysis",
        "adapter": "fallback",
        "fallback_reason": fallback_reason,
        "fallback_error": fallback_error,
    }

    # Create structured fallback reason for diagnostics
    reason = create_fallback_reason(
        source="intent_adapter",
        trigger=fallback_reason or "unknown",
        failed_conditions=["provider_unavailable", "stub_failed"],
        context={"message_preview": str(payload.get("body", ""))[:100]},
        original_error=fallback_error,
    )

    return {
        "intent": IntentLabel.NON_EVENT.value,
        "confidence": 0.0,
        "fields": {},
        "_fallback": True,
        "_fallback_reason": reason.to_dict(),
    }


def _analyze_payload(payload: Dict[str, str]) -> Dict[str, Any]:
    cache_key = _analysis_cache_key(payload)
    cached = _ANALYSIS_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    analysis = _invoke_provider_with_retry(payload, phase="analysis")
    if analysis is None:
        analysis = _fallback_analysis(payload)
    _ANALYSIS_CACHE[cache_key] = analysis
    return dict(analysis)


def classify_intent(message: Dict[str, Optional[str]]) -> Tuple[IntentLabel, float]:
    """[LLM] Delegate intent classification to the agent adapter and normalize output."""

    payload = _prepare_payload(message)
    if os.getenv("INTENT_FORCE_EVENT_REQUEST") == "1":
        print("[DEV] intent override -> event_request")
        return IntentLabel.EVENT_REQUEST, 0.99
    analysis = _analyze_payload(payload)
    normalized = IntentLabel.normalize(analysis.get("intent"))
    confidence = float(analysis.get("confidence", 0.0))
    override = _heuristic_intent_override(payload, normalized)
    if override is not None:
        normalized = override
        confidence = max(confidence, 0.93)
    return normalized, float(confidence)


def extract_user_information(message: Dict[str, Optional[str]]) -> Dict[str, Optional[Any]]:
    """[LLM] Extract structured event details from free-form text."""

    payload = _prepare_payload(message)
    analysis = _analyze_payload(payload)
    raw_fields = analysis.get("fields") if isinstance(analysis.get("fields"), dict) else {}
    sanitized = sanitize_user_info(raw_fields)
    if not sanitized.get("date") and (
        os.getenv("AGENT_MODE", "").lower() == "stub" or os.getenv("INTENT_FORCE_EVENT_REQUEST") == "1"
    ):
        inferred = _infer_date_from_body(payload.get("body") or "")
        if inferred:
            sanitized["date"] = inferred
            if not sanitized.get("event_date"):
                sanitized["event_date"] = dt.datetime.strptime(inferred, "%Y-%m-%d").strftime("%d.%m.%Y")

    body_text = payload.get("body") or ""
    hints = _extract_requirement_hints(body_text)
    if hints.get("layout") and not sanitized.get("layout"):
        sanitized["layout"] = hints["layout"]
    if hints.get("catering") and not sanitized.get("catering"):
        sanitized["catering"] = hints["catering"]

    note_tokens: List[str] = []
    if sanitized.get("notes"):
        note_tokens.extend([token.strip() for token in str(sanitized["notes"]).split(",") if token.strip()])
    for token in hints.get("features", []):
        if token not in note_tokens:
            note_tokens.append(token)
    if note_tokens:
        sanitized["notes"] = ", ".join(note_tokens)

    full_day_tokens = ("full-day", "full day", "all-day", "all day")
    if not sanitized.get("start_time") and any(token in body_text.lower() for token in full_day_tokens):
        sanitized["start_time"] = "09:00"
    if not sanitized.get("end_time") and any(token in body_text.lower() for token in full_day_tokens):
        sanitized["end_time"] = "17:00"

    matched_products = _match_catalog_products(body_text)
    if matched_products:
        high_confidence: List[str] = []
        for item in matched_products:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            try:
                score = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if score >= 0.6:
                high_confidence.append(str(name))
        if high_confidence:
            participant_count = sanitized.get("participants")
            participant_value = participant_count if isinstance(participant_count, int) else None
            normalised = normalise_product_payload(
                high_confidence,
                participant_count=participant_value,
            )
            if normalised:
                existing = normalise_product_payload(
                    sanitized.get("products_add"),
                    participant_count=participant_value,
                )
                combined_names = {item["name"] for item in existing}
                for item in normalised:
                    if item["name"] not in combined_names:
                        existing.append(item)
                sanitized["products_add"] = existing

    vague_components = _extract_vague_date_components(body_text)
    for key, value in vague_components.items():
        if value and not sanitized.get(key):
            sanitized[key] = value
    month_hint = sanitized.get("vague_month") or vague_components.get("vague_month")
    week_window = _extract_week_window(body_text, month_hint)
    if week_window:
        if week_window.get("month") and not sanitized.get("vague_month"):
            sanitized["vague_month"] = week_window["month"]
        if week_window.get("week_index") is not None:
            sanitized["week_index"] = week_window.get("week_index")
        if week_window.get("weekdays_hint"):
            sanitized["weekdays_hint"] = list(week_window["weekdays_hint"])
        window_payload = {
            key: week_window[key]
            for key in ("month", "week_index", "weekdays_hint")
            if week_window.get(key)
        }
        if window_payload:
            sanitized["window"] = window_payload

    lowered_body = body_text.lower()
    if "zurich" in lowered_body:
        city_candidate = "Zürich" if "zürich" in body_text else "Zurich"
        existing_city = sanitized.get("city")
        if not existing_city or existing_city.strip().lower() in _MONTHS:
            sanitized["city"] = city_candidate

    products_add = sanitized.get("products_add")
    if isinstance(products_add, list) and products_add:
        sanitized["wish_products"] = [
            item.get("name")
            for item in products_add
            if isinstance(item, dict) and item.get("name")
        ]

    return sanitized


def _extract_vague_date_components(text: str) -> Dict[str, Optional[str]]:
    lowered = (text or "").lower()
    result: Dict[str, Optional[str]] = {
        "vague_month": None,
        "vague_weekday": None,
        "vague_time_of_day": None,
    }

    # Detect month token
    detected_month: Optional[str] = None
    for token in sorted(_MONTHS.keys(), key=len, reverse=True):
        pattern = rf"\b{re.escape(token)}\b"
        if re.search(pattern, lowered):
            normalized = month_name_to_number(token)
            if normalized:
                detected_month = token
                break
    if detected_month:
        result["vague_month"] = detected_month

    # Detect weekday token
    detected_weekday: Optional[str] = None
    for token in sorted(_VAGUE_WEEKDAY_TOKENS, key=len, reverse=True):
        pattern = rf"\b{re.escape(token)}\b"
        if re.search(pattern, lowered):
            if weekday_name_to_number(token) is not None:
                detected_weekday = token
                break
    if detected_weekday:
        result["vague_weekday"] = detected_weekday

    # Detect time of day
    for token, label in _TIME_OF_DAY_ALIASES.items():
        if token in lowered:
            result["vague_time_of_day"] = label
            break

    return result


def _extract_week_index(text: str) -> Optional[int]:
    lowered = text.lower()
    for pattern in _WEEK_INDEX_PATTERNS:
        match = pattern.search(lowered)
        if not match:
            continue
        if "index" in match.groupdict():
            try:
                value = int(match.group("index"))
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 6:
                return value
            continue
        ordinal = match.group(1).lower()
        value = _ORDINAL_MAP.get(ordinal)
        if value:
            return value
    return None


def _safe_day(value: str | None) -> Optional[int]:
    if value is None:
        return None
    try:
        number = int(re.sub(r"[^\d]", "", value))
    except ValueError:
        return None
    return number if 1 <= number <= 31 else None


def _extract_day_hints(text: str) -> List[int]:
    hints: Set[int] = set()
    for match in _DAY_PAIR_PATTERNS[0].finditer(text):
        for group in match.groups():
            day = _safe_day(group)
            if day is not None:
                hints.add(day)
    for match in _DAY_PAIR_PATTERNS[1].finditer(text):
        inside = match.group(1)
        for inner in _DAY_PAIR_PATTERNS[0].finditer(inside):
            for group in inner.groups():
                day = _safe_day(group)
                if day is not None:
                    hints.add(day)
        for token in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", inside):
            day = _safe_day(token)
            if day is not None:
                hints.add(day)
    for match in _SINGLE_DAY_CONTEXT.finditer(text):
        day = _safe_day(match.group(1))
        if day is not None:
            hints.add(day)
    return sorted(hints)


def _extract_week_window(text: str, month_hint: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    week_index = _extract_week_index(text)
    day_hints = _extract_day_hints(text)
    if week_index is None and not day_hints:
        return None
    resolved_month = month_hint
    if not resolved_month and day_hints:
        resolved_month = None
    window: Dict[str, Any] = {
        "week_index": week_index,
        "weekdays_hint": day_hints,
    }
    if resolved_month:
        index = month_name_to_number(resolved_month)
        label = MONTH_INDEX_TO_NAME.get(index, str(resolved_month).strip().capitalize())
        window["month"] = label
        window["month_index"] = index
    return window


def _sanitize_weekdays_hint(value: Any) -> Optional[List[int]]:
    if value is None:
        return None
    result: List[int] = []
    if isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = re.findall(r"\d{1,2}", str(value))
    for candidate in candidates:
        try:
            day = int(candidate)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 31:
            if day not in result:
                result.append(day)
    return result or None


def sanitize_user_info(raw: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """[LLM] Coerce adapter outputs into the workflow schema."""

    sanitized: Dict[str, Optional[Any]] = {}
    for key in USER_INFO_KEYS:
        value = raw.get(key) if raw else None
        if key == "participants":
            sanitized[key] = sanitize_participants(value)
        elif key == "language":
            sanitized[key] = normalize_language(value)
        elif key == "room":
            sanitized[key] = normalize_room(value)
        elif key == "phone":
            sanitized[key] = normalize_phone(value)
        elif key in {"catering", "company", "notes", "billing_address"}:
            sanitized[key] = clean_text(value, trailing=" .;")
        elif key == "type":
            sanitized[key] = clean_text(value)
        elif key == "layout":
            sanitized[key] = clean_text(value)
        elif key in {"name", "email"}:
            sanitized[key] = clean_text(value)
        elif key == "city":
            city_text = clean_text(value)
            if city_text and city_text.lower() not in {"english", "german", "french", "italian", "spanish"} and "room" not in city_text.lower():
                sanitized[key] = city_text
            else:
                sanitized[key] = None
        elif key == "week_index":
            try:
                candidate = int(value) if value is not None else None
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and 1 <= candidate <= 6:
                sanitized[key] = candidate
            else:
                sanitized[key] = None
        elif key == "weekdays_hint":
            sanitized[key] = _sanitize_weekdays_hint(value)
        elif key == "window":
            sanitized[key] = value if isinstance(value, dict) else None
        elif key in {"date", "start_time", "end_time"}:
            sanitized[key] = clean_text(value)
        else:
            sanitized[key] = value
    sanitized["event_date"] = format_iso_date_to_ddmmyyyy(sanitized.get("date"))
    return sanitized


def reset_llm_adapter() -> None:
    """Reset the cached agent adapter (intended for tests)."""

    global adapter
    global _LAST_CALL_METADATA
    global _ANALYSIS_CACHE
    reset_agent_adapter()
    adapter = get_agent_adapter()
    _LAST_CALL_METADATA = {}
    _ANALYSIS_CACHE = {}
    reset_provider_for_tests()


_CONFIRM_TOKENS = (
    "confirm",
    "confirmed",
    "please confirm",
    "we'll take",
    "we will take",
    "take that date",
    "lock it in",
    "proceed",
    "go ahead",
    "works for us",
    "that date works",
    "book it",
)
_AFFIRMATIVE_PREFIXES = ("yes", "yep", "ja", "oui", "si", "sounds good", "let's do")
_EDIT_TOKENS = ("change", "update", "adjust", "move", "shift", "switch", "different", "another", "reschedule")
_ROOM_TOKENS = ("room", "space", "hall")
_REQUIREMENT_TOKENS = (
    "people",
    "guests",
    "attendees",
    "participants",
    "headcount",
    "projector",
    "screen",
    "catering",
    "requirements",
    "layout",
    "package",
    "menu",
    "equipment",
)


def _heuristic_intent_override(
    payload: Dict[str, str],
    base_intent: IntentLabel,
) -> Optional[IntentLabel]:
    raw_subject = (payload.get("subject") or "")
    raw_body = (payload.get("body") or "")
    subject = raw_subject.strip()
    body = raw_body.strip()
    body_lower = body.lower()
    subject_lower = subject.lower()
    text = f"{subject_lower}\n{body_lower}"

    detected_date = parse_first_date(body) or parse_first_date(subject)
    start_time, end_time, _ = parse_time_range(body)
    has_time_range = bool(start_time and end_time)

    if detected_date:
        if any(token in text for token in _CONFIRM_TOKENS) or body_lower.startswith(_AFFIRMATIVE_PREFIXES):
            return IntentLabel.CONFIRM_DATE if has_time_range else IntentLabel.CONFIRM_DATE_PARTIAL

        if any(token in text for token in _EDIT_TOKENS):
            # "move to 17.04" → edit date
            if any(keyword in text for keyword in ("date", "day", "daytime", "calendar")) or not any(
                room_token in text for room_token in _ROOM_TOKENS
            ):
                return IntentLabel.EDIT_DATE

    if any(room_token in text for room_token in _ROOM_TOKENS) and any(token in text for token in _EDIT_TOKENS):
        return IntentLabel.EDIT_ROOM

    if any(req_token in text for req_token in _REQUIREMENT_TOKENS) and any(token in text for token in _EDIT_TOKENS):
        return IntentLabel.EDIT_REQUIREMENTS

    # Escalate direct affirmative + date replies even without keywords.
    if detected_date and body_lower.startswith(_AFFIRMATIVE_PREFIXES):
        return IntentLabel.CONFIRM_DATE if has_time_range else IntentLabel.CONFIRM_DATE_PARTIAL

    if detected_date and "works" in body_lower:
        return IntentLabel.CONFIRM_DATE if has_time_range else IntentLabel.CONFIRM_DATE_PARTIAL

    if base_intent != IntentLabel.EVENT_REQUEST:
        if any(token in text for token in ("workshop", "conference", "meeting", "event")) and any(
            pax_token in text for pax_token in ("people", "guests", "participants", "pax")
        ):
            return IntentLabel.EVENT_REQUEST

    return None
