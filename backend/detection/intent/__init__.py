"""
MODULE: backend/detection/intent/__init__.py
PURPOSE: Intent classification and confidence scoring.

CONTAINS:
    - classifier.py     Main classify_intent() function (from llm/intent_classifier.py)
    - confidence.py     Confidence scoring and thresholds (from common/confidence.py)
    - gibberish.py      Gibberish detection heuristics (extracted from confidence.py)

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # Keyword patterns for all intents

USED BY:
    - backend/workflows/steps/step1_intake/        # Initial message classification
    - backend/workflows/steps/step2-7/             # All workflow steps for reclassification

EXPORTS:
    - classify_intent(message, current_step, expect_resume) -> Tuple[str, float]
    - check_confidence(confidence, message) -> str  # "proceed" | "ignore" | "hil"
    - is_gibberish(text) -> bool
    - has_workflow_signal(text) -> bool
"""

# Confidence scoring (migrated from workflows/common/confidence.py)
from .confidence import (
    # Thresholds
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_NONSENSE,
    NONSENSE_IGNORE_THRESHOLD,
    NONSENSE_HIL_THRESHOLD,
    # Functions
    confidence_level,
    should_defer_to_human,
    should_seek_clarification,
    should_ignore_message,
    classify_response_action,
    check_nonsense_gate,
    has_workflow_signal,
    is_gibberish,
)

# Intent classification (migrated from llm/intent_classifier.py)
from .classifier import (
    classify_intent,
    spans_multiple_steps,
    get_qna_steps,
    is_action_request,
    QNA_TYPE_TO_STEP,
    # Internal helpers exposed for tests
    _detect_qna_types,
    _looks_like_manager_request,
    _RESUME_PHRASES,
)

__all__ = [
    # Confidence
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CONFIDENCE_LOW",
    "CONFIDENCE_NONSENSE",
    "NONSENSE_IGNORE_THRESHOLD",
    "NONSENSE_HIL_THRESHOLD",
    "confidence_level",
    "should_defer_to_human",
    "should_seek_clarification",
    "should_ignore_message",
    "classify_response_action",
    "check_nonsense_gate",
    "has_workflow_signal",
    "is_gibberish",
    # Classifier
    "classify_intent",
    "spans_multiple_steps",
    "get_qna_steps",
    "is_action_request",
    "QNA_TYPE_TO_STEP",
    "_detect_qna_types",
    "_looks_like_manager_request",
    "_RESUME_PHRASES",
]
