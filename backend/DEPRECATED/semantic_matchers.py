"""
DEPRECATED: This module has been migrated to backend/detection/response/matchers.py

Please update your imports:
    OLD: from backend.workflows.nlu.semantic_matchers import ...
    NEW: from backend.detection.response.matchers import ...

This file will be removed in a future release.
"""

from __future__ import annotations

# Re-export everything from the new canonical location
from backend.detection.response.matchers import (
    # Pattern matching functions
    matches_acceptance_pattern,
    matches_decline_pattern,
    matches_counter_pattern,
    matches_change_pattern,
    matches_change_pattern_enhanced,
    is_pure_qa_message,
    looks_hypothetical,
    is_room_selection,
    # Pattern lists
    ACCEPTANCE_PATTERNS,
    DECLINE_PATTERNS,
    COUNTER_PATTERNS,
    CHANGE_PATTERNS,
    CHANGE_PATTERNS_ENHANCED,
    NEGATION_PATTERN,
    # Re-exports from keyword_buckets
    ChangeIntentResult,
    DetourMode,
    MessageIntent,
    compute_change_intent_score,
    # Internal helpers exposed for testing
    _room_patterns_from_catalog,
)

__all__ = [
    # Pattern matching functions
    "matches_acceptance_pattern",
    "matches_decline_pattern",
    "matches_counter_pattern",
    "matches_change_pattern",
    "matches_change_pattern_enhanced",
    "is_pure_qa_message",
    "looks_hypothetical",
    "is_room_selection",
    # Pattern lists
    "ACCEPTANCE_PATTERNS",
    "DECLINE_PATTERNS",
    "COUNTER_PATTERNS",
    "CHANGE_PATTERNS",
    "CHANGE_PATTERNS_ENHANCED",
    "NEGATION_PATTERN",
    # Re-exports from keyword_buckets
    "ChangeIntentResult",
    "DetourMode",
    "MessageIntent",
    "compute_change_intent_score",
    # Internal helpers exposed for testing
    "_room_patterns_from_catalog",
]
