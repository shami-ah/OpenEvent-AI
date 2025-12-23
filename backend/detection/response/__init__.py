"""
MODULE: backend/detection/response/__init__.py
PURPOSE: Client response pattern detection (acceptance, decline, counter, confirmation).

CONTAINS:
    - acceptance.py     matches_acceptance_pattern() - "yes", "agree", "sounds good"
    - decline.py        matches_decline_pattern() - "no", "cancel", "not interested"
    - counter.py        matches_counter_pattern() - negotiation, price discussions
    - confirmation.py   is_confirmation() - strong confirmation signals

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # Pattern definitions (EN/DE)

USED BY:
    - backend/workflows/steps/step2_date_confirmation/  # Date acceptance
    - backend/workflows/steps/step3_room_availability/  # Room selection
    - backend/workflows/steps/step4_offer/              # Offer acceptance/decline
    - backend/workflows/steps/step5_negotiation/        # Negotiation handling
    - backend/workflows/steps/step7_confirmation/       # Final confirmation

EXPORTS:
    - matches_acceptance_pattern(text) -> bool
    - matches_decline_pattern(text) -> bool
    - matches_counter_pattern(text) -> bool
    - is_confirmation(text) -> bool
"""

# Semantic matchers (migrated from nlu/semantic_matchers.py)
from .matchers import (
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
    # Re-exports
    "ChangeIntentResult",
    "DetourMode",
    "MessageIntent",
    "compute_change_intent_score",
    # Internal helpers exposed for testing
    "_room_patterns_from_catalog",
]
