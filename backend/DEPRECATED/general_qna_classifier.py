"""
DEPRECATED: This module has been migrated to backend/detection/qna/general_qna.py

Please update your imports:
    OLD: from backend.workflows.nlu.general_qna_classifier import ...
    NEW: from backend.detection.qna.general_qna import ...

This file will be removed in a future release.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
from typing import Any, Dict, Optional

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - OpenAI optional in local/dev runs
    OpenAI = None  # type: ignore[assignment]

from backend.workflows.common.types import WorkflowState
from backend.utils.openai_key import load_openai_api_key

# Import consolidated pattern from keyword_buckets (single source of truth)
# MIGRATED: from backend.workflows.nlu.keyword_buckets -> backend.detection.keywords.buckets
from backend.detection.keywords.buckets import ACTION_REQUEST_PATTERNS

# Note: _detect_qna_types is imported lazily inside detect_general_room_query()
# to avoid circular import with backend.llm.intent_classifier

_QUESTION_WORDS = (
    "which",
    "what",
    "when",
    "can",
    "could",
    "would",
    "do you have",
    "does",
    "is there",
    "are there",
    "any chance",
    "could you",
    "would you",
)

# Use imported patterns (removes duplicate definition)
_ACTION_PATTERNS = ACTION_REQUEST_PATTERNS

_PATTERNS = (
    "available",
    "availability",
    "free dates",
    "which dates",
    "what dates",
    "rooms free",
    "room options",
    "show dates",
    "saturdays in",
    "need rooms",
    "looking for rooms",
    "open dates",
    "open rooms",
)

_IMPERATIVE_HINTS = (
    "please let me know which dates",
    "please share which rooms",
    "let me know which rooms",
    "let me know which dates",
)

_BORDERLINE_HINTS = (
    "need rooms",
    "looking for rooms",
    "require room",
    "need a room",
    "need venue",
    "looking for venue",
    "room availability",
)

_MONTHS = {
    "january": "january",
    "february": "february",
    "march": "march",
    "april": "april",
    "may": "may",
    "june": "june",
    "july": "july",
    "august": "august",
    "september": "september",
    "october": "october",
    "november": "november",
    "december": "december",
}

_WEEKDAYS = {
    "monday": "monday",
    "tuesday": "tuesday",
    "wednesday": "wednesday",
    "thursday": "thursday",
    "friday": "friday",
    "saturday": "saturday",
    "sunday": "sunday",
}

_WEEKDAY_ALIASES = {
    "mon": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "weekend": ["saturday", "sunday"],
    "weekends": ["saturday", "sunday"],
}

_TIME_OF_DAY = {
    "morning": "morning",
    "afternoon": "afternoon",
    "evening": "evening",
    "night": "night",
    "all day": "all-day",
    "full day": "all-day",
}

_PAX_PATTERN = re.compile(r"(?:~|about|around)?\s*(\d{1,3})(?:\s*(?:guests|people|pax|attendees|ppl))", re.IGNORECASE)

_CACHE_TTL = 24 * 60 * 60  # 24 hours
_CACHE_MAX = 256
_CACHE: Dict[str, Dict[str, Any]] = {}

_LLM_MODEL = os.getenv("OPENAI_GENERAL_QNA_MODEL", "gpt-4o-mini")
_LLM_ENABLED = bool(load_openai_api_key(required=False))


def reset_general_qna_cache() -> None:
    _CACHE.clear()


def _is_action_request(msg_text: str) -> bool:
    lowered = (msg_text or "").lower()
    return any(re.search(pattern, lowered) for pattern in _ACTION_PATTERNS)


def heuristic_flags(msg_text: str) -> Dict[str, Any]:
    text = (msg_text or "").strip()
    lowered = text.lower()
    has_qmark = "?" in text
    starts_interrogative = bool(re.match(rf"^\s*({'|'.join(_QUESTION_WORDS)})\b", lowered))
    matched_patterns = [pattern for pattern in _PATTERNS if pattern in lowered]
    imperative_hint = any(phrase in lowered for phrase in _IMPERATIVE_HINTS)
    borderline = any(term in lowered for term in _BORDERLINE_HINTS)
    action_request = _is_action_request(lowered)
    heuristic_general = (
        has_qmark or starts_interrogative or bool(matched_patterns) or imperative_hint or borderline
    ) and not action_request
    return {
        "has_qmark": has_qmark,
        "starts_interrogative": starts_interrogative,
        "matched_patterns": matched_patterns,
        "imperative_hint": imperative_hint,
        "borderline": borderline,
        "action_request": action_request,
        "heuristic_general": heuristic_general,
    }


def parse_constraints(msg_text: str) -> Dict[str, Any]:
    lowered = (msg_text or "").lower()
    vague_month: Optional[str] = None
    weekday_tokens: Optional[Any] = None
    time_of_day = None
    pax: Optional[int] = None

    for name in _MONTHS:
        if name in lowered:
            vague_month = _MONTHS[name]
            break

    weekdays = []
    for name in _WEEKDAYS:
        if name in lowered:
            weekdays.append(_WEEKDAYS[name])
    for alias, target in _WEEKDAY_ALIASES.items():
        if alias in lowered:
            if isinstance(target, list):
                weekdays.extend(target)
            else:
                weekdays.append(target)
    if weekdays:
        weekday_tokens = sorted({token for token in weekdays})
        if len(weekday_tokens) == 1:
            weekday_tokens = weekday_tokens[0]

    for token, label in _TIME_OF_DAY.items():
        if token in lowered:
            time_of_day = label
            break

    pax_match = _PAX_PATTERN.search(lowered)
    if pax_match:
        try:
            pax = int(pax_match.group(1))
        except (TypeError, ValueError):
            pax = None

    return {
        "vague_month": vague_month,
        "weekday": weekday_tokens,
        "time_of_day": time_of_day,
        "pax": pax,
    }


def quick_general_qna_scan(msg_text: str) -> Dict[str, Any]:
    """
    Lightweight detector that flags potential general Q&A without LLM calls.

    We keep this stage inexpensive by relying on regex/token checks (question marks,
    interrogative starters, and availability keywords). The result steers whether the
    expensive classifier should run downstream.
    """

    text = (msg_text or "").strip()
    heuristics = heuristic_flags(text)
    parsed = parse_constraints(text)
    likely_general = bool(
        heuristics.get("has_qmark")
        or heuristics.get("starts_interrogative")
        or heuristics.get("matched_patterns")
        or heuristics.get("imperative_hint")
    )
    return {
        "likely_general": likely_general,
        "heuristics": heuristics,
        "parsed": parsed,
    }


def should_call_llm(heuristics: Dict[str, Any], parsed: Dict[str, Any], message_text: str, state: WorkflowState) -> bool:
    if len(message_text or "") > 2000:
        return False
    if not heuristics.get("heuristic_general") and not heuristics.get("borderline"):
        return False
    if heuristics.get("heuristic_general"):
        if _parsed_complete(parsed, state):
            return False
        return True
    return heuristics.get("borderline", False)


def llm_classify(msg_text: str) -> Dict[str, Any]:
    if not _LLM_ENABLED or OpenAI is None:
        return {"label": "not_general", "uncertain": True, "constraints": {}}

    system_prompt = (
        "You are a strict router for event-mail. Classify if the message is a general rooms availability question "
        "(asks about rooms/dates availability in a vague range). Output strict JSON."
    )
    schema = {
        "type": "object",
        "properties": {
            "label": {"enum": ["general_room_query", "not_general"]},
            "uncertain": {"type": "boolean"},
            "constraints": {
                "type": "object",
                "properties": {
                    "vague_month": {"type": ["string", "null"]},
                    "weekday": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "null"},
                        ]
                    },
                    "time_of_day": {"type": ["string", "null"]},
                    "pax": {"type": ["number", "null"]},
                },
                "required": ["vague_month", "weekday", "time_of_day", "pax"],
                "additionalProperties": False,
            },
        },
        "required": ["label", "uncertain", "constraints"],
        "additionalProperties": False,
    }

    few_shots = [
        {
            "role": "user",
            "content": "Which rooms are free on Saturdays in February for ~30 people?",
        },
        {
            "role": "assistant",
            "content": (
                '{"label":"general_room_query","uncertain":false,"constraints":{"vague_month":"february","weekday":["saturday"],'
                '"time_of_day":null,"pax":30}}'
            ),
        },
        {
            "role": "user",
            "content": "Can you send a menu?",
        },
        {
            "role": "assistant",
            "content": '{"label":"not_general","uncertain":false,"constraints":{"vague_month":null,"weekday":null,"time_of_day":null,"pax":null}}',
        },
        {
            "role": "user",
            "content": "Evenings in March, 40–50 pax, what’s available?",
        },
        {
            "role": "assistant",
            "content": (
                '{"label":"general_room_query","uncertain":false,"constraints":{"vague_month":"march","weekday":null,"time_of_day":"evening","pax":45}}'
            ),
        },
        {
            "role": "user",
            "content": "We’re thinking 15 March.",
        },
        {
            "role": "assistant",
            "content": '{"label":"not_general","uncertain":false,"constraints":{"vague_month":null,"weekday":null,"time_of_day":null,"pax":null}}',
        },
        {
            "role": "user",
            "content": "Do you have any availability end of spring?",
        },
        {
            "role": "assistant",
            "content": (
                '{"label":"general_room_query","uncertain":true,"constraints":{"vague_month":null,"weekday":null,"time_of_day":null,"pax":null}}'
            ),
        },
    ]

    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=_LLM_MODEL,
        temperature=0,
        top_p=0,
        max_tokens=120,
        response_format={"type": "json_schema", "json_schema": {"name": "general_room_classifier", "schema": schema}},
        messages=[
            {"role": "system", "content": system_prompt},
            *few_shots,
            {"role": "user", "content": msg_text},
        ],
    )
    content = response.choices[0].message.content if response.choices else "{}"
    try:
        payload = json.loads(content or "{}")  # type: ignore[name-defined]
    except Exception:  # pragma: no cover - defensive
        payload = {}
    label = payload.get("label") if payload.get("label") in {"general_room_query", "not_general"} else "not_general"
    constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    return {
        "label": label,
        "uncertain": bool(payload.get("uncertain")),
        "constraints": constraints,
    }


def detect_general_room_query(msg_text: str, state: WorkflowState) -> Dict[str, Any]:
    text = (msg_text or "").strip()
    if not text:
        return _empty_detection()

    cache_key = _cache_key(text, state)
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached["ts"] < _CACHE_TTL:
        result = dict(cached["result"])
        result["cached"] = True
        return result

    heuristics = heuristic_flags(text)
    parsed = parse_constraints(text)

    if heuristics.get("action_request"):
        detection = {
            "is_general": False,
            "heuristics": heuristics,
            "parsed": parsed,
            "constraints": parsed,
            "llm_called": False,
            "llm_result": {"label": "not_general", "uncertain": True, "constraints": {}},
            "cached": False,
        }
        if len(_CACHE) >= _CACHE_MAX:
            _evict_cache_entry()
        _CACHE[cache_key] = {"ts": now, "result": detection}
        return detection

    call_llm = should_call_llm(heuristics, parsed, text, state)

    llm_called = False
    llm_result = {"label": "not_general", "uncertain": True, "constraints": {}}
    if call_llm:
        llm_called = True
        llm_result = llm_classify(text)

    is_general = bool(
        heuristics.get("heuristic_general") or llm_result.get("label") == "general_room_query"
    )

    combined_constraints = _merge_constraints(parsed, llm_result.get("constraints") or {})

    # Detect secondary Q&A types (catering_for, products_for, etc.)
    # Lazy import to avoid circular import with backend.llm.intent_classifier
    from backend.llm.intent_classifier import _detect_qna_types  # pylint: disable=import-outside-toplevel
    secondary_types = _detect_qna_types(text)

    detection = {
        "is_general": is_general,
        "heuristics": heuristics,
        "parsed": parsed,
        "constraints": combined_constraints,
        "llm_called": llm_called,
        "llm_result": llm_result,
        "cached": False,
        "secondary": secondary_types if secondary_types else None,
    }
    if len(_CACHE) >= _CACHE_MAX:
        _evict_cache_entry()
    _CACHE[cache_key] = {"ts": now, "result": detection}
    return detection


def _merge_constraints(parsed: Dict[str, Any], llm_constraints: Dict[str, Any]) -> Dict[str, Any]:
    weekday = parsed.get("weekday") or llm_constraints.get("weekday")
    if isinstance(weekday, str):
        weekday_value = weekday
    elif isinstance(weekday, list):
        weekday_value = sorted({str(item) for item in weekday})
    else:
        weekday_value = weekday

    return {
        "vague_month": parsed.get("vague_month") or llm_constraints.get("vague_month"),
        "weekday": weekday_value,
        "time_of_day": parsed.get("time_of_day") or llm_constraints.get("time_of_day"),
        "pax": parsed.get("pax") or llm_constraints.get("pax"),
    }


def _parsed_complete(parsed: Dict[str, Any], state: WorkflowState) -> bool:
    has_month = bool(parsed.get("vague_month") or state.user_info.get("vague_month"))
    has_weekday = bool(parsed.get("weekday") or state.user_info.get("vague_weekday"))
    has_time = bool(parsed.get("time_of_day") or state.user_info.get("vague_time_of_day"))
    has_pax = parsed.get("pax") is not None or state.user_info.get("participants") is not None
    return has_month and (has_weekday or has_time) and has_pax


def _cache_key(message: str, state: WorkflowState) -> str:
    locale = getattr(state, "locale", None) or state.user_info.get("language") or "en"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return f"{locale}:{digest}"


def _evict_cache_entry() -> None:
    if not _CACHE:
        return
    oldest_key = min(_CACHE.keys(), key=lambda key: _CACHE[key]["ts"])
    _CACHE.pop(oldest_key, None)


def _empty_detection() -> Dict[str, Any]:
    return {
        "is_general": False,
        "heuristics": heuristic_flags(""),
        "parsed": parse_constraints(""),
        "constraints": {"vague_month": None, "weekday": None, "time_of_day": None, "pax": None},
        "llm_called": False,
        "llm_result": {"label": "not_general", "uncertain": True, "constraints": {}},
        "cached": False,
    }


def empty_general_qna_detection() -> Dict[str, Any]:
    """Public wrapper so callers can reuse the canonical empty payload."""

    return dict(_empty_detection())


__all__ = [
    "detect_general_room_query",
    "empty_general_qna_detection",
    "heuristic_flags",
    "parse_constraints",
    "quick_general_qna_scan",
    "should_call_llm",
    "reset_general_qna_cache",
]
