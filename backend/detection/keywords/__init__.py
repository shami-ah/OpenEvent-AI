"""
MODULE: backend/detection/keywords/__init__.py
PURPOSE: Single source of truth for ALL keyword patterns used in detection.

This is THE authoritative location for all keyword patterns. All detection
modules import from here. DO NOT define keyword patterns elsewhere.

CONTAINS:
    - buckets.py  All keyword buckets, patterns, and enums

KEYWORD CATEGORIES:

    Change Detection (EN/DE):
        CHANGE_VERBS_EN, CHANGE_VERBS_DE       # "change", "modify", "update"
        REVISION_MARKERS_EN, REVISION_MARKERS_DE # "actually", "instead", "on second thought"
        TARGET_PATTERNS                         # Room names, date patterns

    Response Detection (EN/DE):
        CONFIRMATION_SIGNALS_EN, CONFIRMATION_SIGNALS_DE  # "yes", "ok", "sounds good"
        DECLINE_SIGNALS_EN, DECLINE_SIGNALS_DE            # "no", "cancel"
        ACCEPTANCE_PATTERNS, DECLINE_PATTERNS, COUNTER_PATTERNS

    Q&A Detection:
        PURE_QA_SIGNALS_EN, PURE_QA_SIGNALS_DE  # Question-only signals
        ACTION_REQUEST_PATTERNS                 # Action vs question
        OPTION_KEYWORDS                         # Soft holds
        CAPACITY_KEYWORDS                       # Capacity questions
        ALTERNATIVE_KEYWORDS                    # Alternatives/waitlist
        AVAILABILITY_KEYWORDS                   # Availability checks

    Intent Classification:
        WORKFLOW_SIGNALS                        # EN/DE patterns for workflow content

ENUMS:
    - MessageIntent      # DETOUR_DATE, DETOUR_ROOM, CONFIRMATION, GENERAL_QA, etc.
    - DetourMode         # LONG, FAST, EXPLICIT
    - RoomSearchIntent   # CHECK_AVAILABILITY, REQUEST_OPTION, etc.

HELPER FUNCTIONS:
    - has_revision_signal(text) -> bool
    - has_bound_target(text) -> bool
    - is_pure_qa(text) -> bool
    - is_confirmation(text) -> bool
    - compute_change_intent_score(text) -> ChangeIntentScore
    - detect_language(text) -> str  # "en" | "de"

USED BY:
    - backend/detection/intent/classifier.py
    - backend/detection/response/*.py
    - backend/detection/change/*.py
    - backend/detection/qna/*.py
    - backend/detection/special/*.py

MIGRATION SOURCE:
    - backend/workflows/nlu/keyword_buckets.py (moved here)

RELATED TESTS:
    - backend/tests/detection/test_semantic_matchers.py
    - backend/tests/detection/test_detour_detection.py
"""

# Will export all patterns from buckets.py when migrated
# from backend.detection.keywords.buckets import (
#     CHANGE_VERBS_EN, CHANGE_VERBS_DE,
#     CONFIRMATION_SIGNALS_EN, CONFIRMATION_SIGNALS_DE,
#     # ... etc
# )
