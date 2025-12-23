"""
MODULE: backend/detection/intent/classifier.py
PURPOSE: Main intent classification for incoming messages.

DEPENDS ON:
    - backend/domain/vocabulary.py           # IntentLabel enum
    - backend/workflows/llm/adapter.py       # LLM-based classify_intent
    - backend/detection/intent/confidence.py # has_workflow_signal, is_gibberish
    - backend/detection/keywords/buckets.py  # ACTION_REQUEST_PATTERNS, etc.

USED BY:
    - backend/workflows/groups/*/trigger/process.py  # All step handlers
    - backend/workflows/qna/router.py                # spans_multiple_steps
    - backend/workflows/qna/conjunction.py           # QNA_TYPE_TO_STEP
    - backend/detection/qna/general_qna.py           # _detect_qna_types

EXPORTS:
    - classify_intent(message, current_step, expect_resume) -> Dict
    - spans_multiple_steps(qna_types) -> bool
    - get_qna_steps(qna_types) -> List[int]
    - is_action_request(text) -> bool
    - QNA_TYPE_TO_STEP dict
    - _detect_qna_types(text) -> List[str]  (for internal use)
    - _looks_like_manager_request(text) -> bool  (for internal use)
    - _RESUME_PHRASES  (backward compat alias)

RELATED TESTS:
    - backend/tests/detection/test_qna_detection.py
    - backend/tests/detection/test_manager_request.py
    - backend/tests/detection/test_room_search_intents.py
    - backend/tests/detection/test_acceptance.py
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.domain.vocabulary import IntentLabel
from backend.workflows.llm.adapter import classify_intent as agent_classify_intent
from backend.detection.intent.confidence import has_workflow_signal, is_gibberish

# Import consolidated patterns from keyword_buckets (single source of truth)
from backend.detection.keywords.buckets import (
    ACTION_REQUEST_PATTERNS,
    AVAILABILITY_TOKENS,
    RESUME_PHRASES,
    # Regex-based patterns for flexible matching
    OPTION_KEYWORDS,
    CAPACITY_KEYWORDS,
    ALTERNATIVE_KEYWORDS,
    ENHANCED_CONFIRMATION_KEYWORDS,
    AVAILABILITY_KEYWORDS,
)

# Use imports with local aliases for backward compatibility
_RESUME_PHRASES = RESUME_PHRASES

_ROOM_NAMES = ("room a", "room b", "room c", "punkt.null", "punkt null")

_DATE_PATTERNS = (
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
)

_MONTH_TOKENS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

# Use imported AVAILABILITY_TOKENS from keyword_buckets
_AVAILABILITY_TOKENS = AVAILABILITY_TOKENS

_OFFER_ACTION_TOKENS = (
    "confirm the offer",
    "confirm offer",
    "approve the offer",
    "approve the quote",
    "go ahead with the offer",
    "move forward with the offer",
    "finalize the offer",
    "finalise the offer",
    "lock the offer",
    "ready for the offer",
    "send the contract",
    "sign the contract",
)

_QNA_KEYWORDS: Dict[str, Sequence[str]] = {
    "rooms_by_feature": (
        "hdmi",
        "projector",
        "screen",
        "sound system",
        "audio",
        "video",
        "features",
        "equipment",
        "what rooms",
        "which rooms",
        "any rooms",
        "room options",
        "room choices",
        "can you recommend a room",
        "do rooms have",
    ),
    "room_features": (
        "room a have",
        "room b have",
        "room c have",
        "punkt.null have",
        "punkt null have",
        "room a include",
        "room b include",
        "room c include",
        "punkt null include",
        "punkt.null include",
        "features of room",
        "equipment in room",
    ),
    "catering_for": (
        "catering",
        "menu",
        "menus",
        "package",
        "packages",
        "package options",
        "coffee break",
        "coffee",
        "snacks",
        "lunch",
        "dinner",
        "drinks",
        "beverage",
        "beverages",
        "apero",
        "aperitif",
    ),
    "products_for": (
        "products",
        "add-ons",
        "addons",
        "equipment",
        "lighting",
        "microphone",
        "av setup",
        "av equipment",
        "tech package",
        "hybrid kit",
    ),
    "free_dates": (
        "available dates",
        "free dates",
        "dates available",
        "which days are free",
        "open dates",
        "date options",
        "next available date",
        "what dates",
    ),
    "site_visit_overview": (
        "site visit",
        "tour",
        "walkthrough",
        "visit the venue",
        "come by",
        "venue tour",
    ),
    "parking_policy": (
        "parking",
        "car park",
        "where to park",
        " park",  # "can guests park" - note leading space to avoid matching "park" in other contexts
        "park?",  # "where can guests park?"
        "loading dock",
        "access",
    ),
    # =========================================================================
    # NEW: Room Search Intents (from industry best practices)
    # =========================================================================
    "check_availability": (
        "is it available",
        "are you available",
        "is it free",
        "is it booked",
        "can we book",
        "open for booking",
        "status of",
    ),
    "request_option": (
        "can i hold",
        "can we hold",
        "can we option",
        "tentative booking",
        "provisional booking",
        "soft hold",
        "first option",
        "put on hold",
        "put it on hold",
        "hold the space",
    ),
    "check_capacity": (
        "capacity",
        "how many people",
        "how many guests",
        "does it fit",
        "will it fit",
        "enough space",
        "standing capacity",
        "seated capacity",
        "theater style",
        "theatre style",
        "max capacity",
        "maximum capacity",
    ),
    "check_alternatives": (
        "waitlist",
        "waiting list",
        "other dates",
        "alternative dates",
        "different dates",
        "next available",
        "nearest available",
        "backup option",
        "next opening",
        "what else",
        "any other rooms",
        "if not available",
    ),
    "confirm_booking": (
        "green light",
        "lock it in",
        "secure the date",
        "binding booking",
        "firm commitment",
        "ready to book",
        "ready to sign",
        "sign us up",
        "sign me up",
        "that's a deal",
        "it's a deal",
    ),
}

_QUESTION_PREFIXES = (
    "do you",
    "can you",
    "could you",
    "would you",
    "what",
    "which",
    "any chance",
    "is there",
    "are there",
    "when",
    "where",
    "how",
)

# Use imported ACTION_REQUEST_PATTERNS from keyword_buckets
_ACTION_PATTERNS = ACTION_REQUEST_PATTERNS


def _normalise_text(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _matches_any(text: str, tokens: Iterable[str]) -> bool:
    return any(token in text for token in tokens)


def _matches_any_regex(text: str, patterns: List[str]) -> bool:
    """Match text against regex patterns (more flexible than substring matching)."""
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _detect_room_mentions(text: str) -> bool:
    return any(room in text for room in _ROOM_NAMES)


# Mapping of Q&A types to regex patterns (for flexible matching)
_QNA_REGEX_PATTERNS: Dict[str, List[str]] = {
    "request_option": OPTION_KEYWORDS.get("en", []),
    "check_capacity": CAPACITY_KEYWORDS.get("en", []),
    "check_alternatives": ALTERNATIVE_KEYWORDS.get("en", []),
    "confirm_booking": ENHANCED_CONFIRMATION_KEYWORDS.get("en", []),
    "check_availability": AVAILABILITY_KEYWORDS.get("en", []),
}


def _detect_qna_types(text: str) -> List[str]:
    if is_action_request(text):
        return []
    matches: List[str] = []

    # First check regex patterns (more flexible, handles variations)
    for qna_type, patterns in _QNA_REGEX_PATTERNS.items():
        if patterns and _matches_any_regex(text, patterns):
            matches.append(qna_type)

    # Then check simple substring keywords (for existing types)
    for qna_type, keywords in _QNA_KEYWORDS.items():
        # Skip types already checked via regex
        if qna_type in _QNA_REGEX_PATTERNS:
            continue
        if _matches_any(text, keywords):
            matches.append(qna_type)

    return matches


# Mapping Q&A types to their primary workflow step
QNA_TYPE_TO_STEP = {
    "free_dates": 2,
    "check_availability": 2,
    "rooms_by_feature": 3,
    "room_features": 3,
    "check_capacity": 3,
    "check_alternatives": 3,
    "catering_for": 4,
    "products_for": 4,
    "request_option": 4,
    "site_visit_overview": 7,
    "parking_policy": 0,  # General info, no specific step
    "confirm_booking": 7,
}


def spans_multiple_steps(qna_types: List[str]) -> bool:
    """
    Check if Q&A types in secondary span different workflow steps.

    Used to detect multi-variable Q&A that needs special handling
    (e.g., asking about dates AND packages in one message).
    """
    steps = {QNA_TYPE_TO_STEP.get(t, 0) for t in qna_types}
    # Remove step 0 (general info) and check if multiple steps remain
    meaningful_steps = steps - {0}
    return len(meaningful_steps) > 1


def get_qna_steps(qna_types: List[str]) -> List[int]:
    """Return sorted list of workflow steps covered by the Q&A types."""
    steps = {QNA_TYPE_TO_STEP.get(t, 0) for t in qna_types}
    return sorted(steps - {0})


def _has_date_anchor(text: str) -> bool:
    if any(re.search(pattern, text) for pattern in _DATE_PATTERNS):
        return True
    if _matches_any(text, _MONTH_TOKENS):
        return True
    if re.search(r"\b(?:next|following)\s+(?:week|month)\b", text):
        return True
    if re.search(r"\bweek\s+of\b", text):
        return True
    if re.search(r"\b(?:on|for)\s+\d{1,2}(?:st|nd|rd|th)?\b", text):
        return True
    if re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text):
        return True
    if re.search(r"\b\d{1,2}\s*(?:am|pm|:)\b", text):
        return True
    return False


def _has_availability_ask(text: str) -> bool:
    return _matches_any(text, _AVAILABILITY_TOKENS)


def _has_offer_action(text: str) -> bool:
    return _matches_any(text, _OFFER_ACTION_TOKENS)


_MANAGER_PATTERNS = (
    r"\b(escalate|escalation)\b",
    r"\b(speak|talk|chat)\s+(to|with)\s+(a|the)\s+(manager|human|person)\b",
    r"\b(speak|talk|chat)\s+(to|with)\s+(a\s+)?real\s+person\b",
    r"\bneed\s+(a|the)\s+(manager|human)\b",
    r"\bconnect\s+me\s+with\s+(someone|a person)\b",
)


def _looks_like_manager_request(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _MANAGER_PATTERNS)


def is_action_request(text: str) -> bool:
    """Check if message is requesting an action vs asking a question."""
    return any(re.search(pattern, text) for pattern in _ACTION_PATTERNS)


_EVENT_INTENTS = {
    IntentLabel.EVENT_REQUEST,
    IntentLabel.CONFIRM_DATE,
    IntentLabel.CONFIRM_DATE_PARTIAL,
    IntentLabel.EDIT_DATE,
    IntentLabel.EDIT_ROOM,
    IntentLabel.EDIT_REQUIREMENTS,
}


def _agent_route(message: str) -> Tuple[IntentLabel, float]:
    payload = {"subject": "", "body": message}
    try:
        label, confidence = agent_classify_intent(payload)
    except Exception:
        label, confidence = IntentLabel.NON_EVENT, 0.0
    return label, confidence


def _step_name_for_anchor(step: Optional[str]) -> Optional[str]:
    if not step:
        return None
    mapping = {
        "date_confirmation": "Date Confirmation",
        "room_availability": "Room Availability",
        "offer_review": "Offer Review",
        "site_visit": "Site Visit",
        "follow_up": "Follow-Up",
    }
    return mapping.get(step, step.replace("_", " ").title())


def _step_anchor_from_qna(qna_types: Sequence[str]) -> Optional[str]:
    if not qna_types:
        return None
    for qna_type in qna_types:
        # NEW: Room search intents route to Room Availability
        if qna_type in {"check_availability", "check_capacity", "check_alternatives"}:
            return "Room Availability"
        # NEW: Option/confirmation route to Offer Review (stronger signal)
        if qna_type in {"request_option", "confirm_booking"}:
            return "Offer Review"
        # Existing mappings (unchanged)
        if qna_type in {"free_dates"}:
            return "Date Confirmation"
        if qna_type in {"rooms_by_feature", "room_features"}:
            return "Room Availability"
        if qna_type in {"catering_for", "products_for"}:
            return "Offer Review"
        if qna_type in {"site_visit_overview"}:
            return "Site Visit"
    return None


def classify_intent(
    message: str,
    *,
    current_step: Optional[int] = None,
    expect_resume: bool = False,
) -> Dict[str, Any]:
    """
    Deterministic classifier producing workflow + Q&A routing hints.

    Early gate: If message has no workflow signal and is gibberish,
    return "nonsense" immediately to save LLM cost.
    """

    normalized = _normalise_text(message)
    current_step = current_step or 2

    # -------------------------------------------------------------------------
    # EARLY GATE: Catch gibberish BEFORE any LLM calls to save cost
    # -------------------------------------------------------------------------
    _has_workflow_signal = has_workflow_signal(message)
    needs_confidence_gate = False

    if not _has_workflow_signal:
        if is_gibberish(message):
            # Pure gibberish (keyboard mash, repeated chars) - ignore immediately
            return {
                "primary": "nonsense",
                "secondary": [],
                "step_anchor": None,
                "wants_resume": False,
                "agent_intent": "nonsense",
                "agent_confidence": 0.0,
                "needs_confidence_gate": False,
            }
        else:
            # No workflow signal but not obvious gibberish (could be off-topic)
            # Flag for post-step-handler confidence check
            needs_confidence_gate = True
    # -------------------------------------------------------------------------

    classification: Dict[str, Any] = {
        "primary": "general_qna",
        "secondary": [],
        "step_anchor": None,
        "wants_resume": False,
        "needs_confidence_gate": needs_confidence_gate,
    }

    if expect_resume:
        if normalized in _RESUME_PHRASES:
            classification["primary"] = "resume"
            classification["wants_resume"] = True
            return classification
        if re.match(r"^(yes|yep|ok|okay|sure)\b", normalized):
            classification["primary"] = "resume"
            classification["wants_resume"] = True
            return classification
        if "proceed" in normalized or "continue" in normalized or "go ahead" in normalized:
            classification["primary"] = "resume"
            classification["wants_resume"] = True
            return classification

    agent_label, agent_confidence = _agent_route(message)
    classification["agent_intent"] = agent_label.value
    classification["agent_confidence"] = agent_confidence

    if agent_label == IntentLabel.MESSAGE_MANAGER:
        classification["primary"] = "message_manager"
        classification["step_anchor"] = None
        return classification

    qna_types = _detect_qna_types(normalized)
    has_qna_keywords = bool(qna_types)

    if not normalized:
        classification["primary"] = "general_qna"
        classification["secondary"] = []
        classification["step_anchor"] = _step_name_for_anchor(None)
        return classification

    has_date_anchor = _has_date_anchor(normalized)
    has_availability_ask = _has_availability_ask(normalized)
    has_room_nomination = _detect_room_mentions(normalized)
    has_offer_action = _has_offer_action(normalized)

    is_event = agent_label in _EVENT_INTENTS

    # Precedence for primary intent
    if (not is_event) and (has_date_anchor or has_availability_ask or has_room_nomination or has_offer_action):
        is_event = True

    if is_event and (has_date_anchor or has_availability_ask):
        classification["primary"] = "date_confirmation"
    elif is_event and current_step == 3 and has_room_nomination:
        classification["primary"] = "room_availability"
    elif is_event and current_step == 4 and has_offer_action:
        classification["primary"] = "offer_review"
    elif is_event:
        classification["primary"] = "date_confirmation"
    elif has_qna_keywords:
        classification["primary"] = "general_qna"
    elif _looks_like_manager_request(normalized):
        classification["primary"] = "message_manager"
    else:
        # fallback: treat question-like messages as general Q&A
        if normalized.endswith("?") or any(normalized.startswith(prefix) for prefix in _QUESTION_PREFIXES):
            classification["primary"] = "general_qna"
        else:
            classification["primary"] = "general_qna"

    if has_qna_keywords:
        classification["secondary"] = list(dict.fromkeys(qna_types))

    qna_anchor = _step_anchor_from_qna(classification["secondary"])
    if classification["primary"] in {"date_confirmation", "room_availability", "offer_review"}:
        classification["step_anchor"] = qna_anchor or _step_name_for_anchor(classification["primary"])
    else:
        classification["step_anchor"] = qna_anchor

    # If no explicit anchor resolved, fall back to current step
    if not classification["step_anchor"]:
        fallback_map = {
            2: "Date Confirmation",
            3: "Room Availability",
            4: "Offer Review",
            5: "Site Visit",
            7: "Follow-Up",
        }
        classification["step_anchor"] = fallback_map.get(current_step)

    return classification


__all__ = [
    "classify_intent",
    "spans_multiple_steps",
    "get_qna_steps",
    "is_action_request",
    "QNA_TYPE_TO_STEP",
    # Internal helpers exposed for tests and related modules
    "_detect_qna_types",
    "_looks_like_manager_request",
    "_RESUME_PHRASES",
]
