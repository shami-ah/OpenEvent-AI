from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency resolved at runtime
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - library may be unavailable in tests
    OpenAI = None  # type: ignore

from backend.workflows.common.types import WorkflowState
# MIGRATED: from backend.workflows.nlu.general_qna_classifier -> backend.detection.qna.general_qna
from backend.detection.qna.general_qna import quick_general_qna_scan
from backend.utils.openai_key import load_openai_api_key
from backend.workflows.common.fallback_reason import (
    create_fallback_reason,
    llm_disabled_reason,
    llm_exception_reason,
)

QNA_EXTRACTION_MODEL = os.getenv("OPEN_EVENT_QNA_EXTRACTION_MODEL", "o3-mini")
_LLM_ENABLED = bool(load_openai_api_key(required=False) and OpenAI is not None)

Q_VALUE_KEYS = (
    "date",
    "date_range",
    "date_pattern",
    "n_exact",
    "n_range",
    "room",
    "exclude_rooms",
    "products",
    "product_attributes",
    "notes",
)

QNA_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["msg_type", "qna_intent", "qna_subtype", "q_values"],
    "additionalProperties": False,
    "properties": {
        "msg_type": {"enum": ["event", "non_event"]},
        "qna_intent": {"enum": ["select_dependent", "select_static", "non_event", "update_candidate"]},
        "qna_subtype": {"type": "string"},
        "q_values": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "date": {"type": ["string", "null"]},
                "date_range": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                },
                "date_pattern": {"type": ["string", "null"]},
                "n_exact": {"type": ["integer", "null"]},
                "n_range": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "min": {"type": "integer"},
                        "max": {"type": "integer"},
                    },
                },
                "room": {"type": ["string", "null"]},
                "exclude_rooms": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "products": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "product_attributes": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "notes": {"type": ["string", "null"]},
            },
        },
        # Temporary requirements for THIS Q&A only (NOT persisted to event record)
        "qna_requirements": {
            "type": ["object", "null"],
            "description": "Requirements mentioned IN THIS Q&A ONLY - used to answer this question, not stored permanently",
            "additionalProperties": False,
            "properties": {
                "attendees": {
                    "type": ["integer", "null"],
                    "description": "Number of attendees/visitors/guests/people mentioned in Q&A",
                },
                "dietary": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Dietary requirements like vegetarian, vegan, halal, kosher",
                },
                "features": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Room/venue features like projector, kitchen, music",
                },
                "layout": {
                    "type": ["string", "null"],
                    "description": "Seating arrangement like u-shape, classroom, boardroom",
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You extract structured Q&A intents for OpenEvent. "
    "Classify the message into read-only Q&A intents. "
    "Always emit JSON matching the provided schema. "
    "If the Q&A message mentions specific requirements (number of attendees/visitors/guests/people, "
    "dietary needs like vegetarian/vegan, or room features like projector/kitchen/music), "
    "extract them into qna_requirements. Use semantic understanding - 'visitors', 'guests', "
    "'attendees', 'people' all refer to attendee count. "
    "These requirements are used ONLY for answering this question, not stored permanently."
)


def ensure_qna_extraction(
    state: WorkflowState,
    message_text: str,
    scan: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Populate `state.extras['qna_extraction']` with the structured payload when we
    believe the message belongs to the general Q&A surface.

    Args:
        state: Current workflow state
        message_text: Text to extract from
        scan: Optional pre-computed scan result
        force_refresh: If True, skip cache and always run fresh extraction (for multi-turn Q&A)
    """

    if not force_refresh and "qna_extraction" in state.extras:
        cached = state.extras["qna_extraction"]
        if cached:
            return cached
        return None

    text = (message_text or "").strip()
    if not text:
        state.extras["qna_extraction_skipped"] = True
        return None

    if scan is None:
        scan = quick_general_qna_scan(text)
        state.extras["general_qna_scan"] = scan

    heuristics = scan.get("heuristics") or {}
    borderline = bool(heuristics.get("borderline"))
    likely_general = bool(scan.get("likely_general"))
    heuristic_general = bool(heuristics.get("heuristic_general"))

    if not (likely_general or borderline or heuristic_general):
        state.extras["qna_extraction_skipped"] = True
        return None

    payload = {
        "message": {
            "subject": state.message.subject or "",
            "body": state.message.body or "",
            "text": text,
        },
        "event_state": state.event_entry or {},
        "scan": {
            "likely_general": likely_general,
            "borderline": borderline,
            "heuristics": heuristics,
        },
    }

    try:
        extraction = _run_qna_extraction(payload)
    except Exception as exc:  # pragma: no cover - defensive
        state.extras["qna_extraction_error"] = str(exc)
        extraction = _fallback_extraction(payload, reason="llm_exception", error=str(exc))

    normalized = _normalize_qna_extraction(extraction)
    meta = {
        "model": QNA_EXTRACTION_MODEL if _LLM_ENABLED else "fallback",
        "trigger": "borderline" if borderline and not likely_general else "general",
    }
    state.extras["qna_extraction"] = normalized
    state.extras["qna_extraction_meta"] = meta
    state.extras["qna_last_message_text"] = text

    # Only save to qna_cache if NOT doing a forced refresh (multi-turn Q&A)
    event_entry = state.event_entry
    if isinstance(event_entry, dict) and not force_refresh:
        cache = event_entry.setdefault("qna_cache", {})
        cache["extraction"] = normalized
        cache["meta"] = meta
        cache["last_message_text"] = text
        state.extras["persist"] = True

    return normalized


def _run_qna_extraction(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _LLM_ENABLED:
        return _fallback_extraction(payload, reason="llm_disabled")

    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=QNA_EXTRACTION_MODEL,
        temperature=0,
        top_p=0,
        max_tokens=600,
        response_format={"type": "json_schema", "json_schema": {"name": "qna_extraction", "schema": QNA_EXTRACTION_SCHEMA}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content if response.choices else "{}"
    try:
        return json.loads(content or "{}")
    except json.JSONDecodeError as exc:
        return _fallback_extraction(payload, reason="json_decode_error", error=str(exc))


def _fallback_extraction(
    payload: Dict[str, Any],
    reason: str = "llm_disabled",
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministic heuristic fallback used in offline/dev mode.

    Args:
        payload: The extraction payload
        reason: Why fallback was triggered (llm_disabled, llm_exception, json_decode_error)
        error: Optional error message for exceptions
    """
    return {
        "msg_type": "event",
        "qna_intent": "select_static",
        "qna_subtype": "non_event_info",
        "q_values": {key: None for key in Q_VALUE_KEYS},
        "qna_requirements": None,
        "_fallback": True,
        "_fallback_reason": reason,
        "_fallback_error": error,
    }


def _normalize_qna_extraction(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    q_values = raw.get("q_values") if isinstance(raw.get("q_values"), dict) else {}
    normalized_values: Dict[str, Any] = {key: q_values.get(key) for key in Q_VALUE_KEYS}

    # Preserve qna_requirements (temporary, NOT persisted to event record)
    # Used only for answering this specific Q&A
    qna_requirements = raw.get("qna_requirements") if isinstance(raw.get("qna_requirements"), dict) else None

    return {
        "msg_type": _safe_enum(raw.get("msg_type"), {"event", "non_event"}, default="event"),
        "qna_intent": _safe_enum(
            raw.get("qna_intent"),
            {"select_dependent", "select_static", "non_event", "update_candidate"},
            default="select_static",
        ),
        "qna_subtype": str(raw.get("qna_subtype") or "non_event_info"),
        "q_values": normalized_values,
        "qna_requirements": qna_requirements,
    }


def _safe_enum(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return default


__all__ = ["ensure_qna_extraction", "QNA_EXTRACTION_SCHEMA"]
