"""Natural-language understanding helpers for workflow routing."""

# MIGRATED: from .general_qna_classifier -> backend.detection.qna.general_qna
from backend.detection.qna.general_qna import (
    detect_general_room_query,
    empty_general_qna_detection,
    quick_general_qna_scan,
    reset_general_qna_cache,
)
from .parse_billing import parse_billing_address
from .preferences import extract_preferences
# MIGRATED: from .sequential_workflow -> backend.detection.qna.sequential_workflow
from backend.detection.qna.sequential_workflow import detect_sequential_workflow_request

# Shared detection patterns (consolidated from multiple modules)
# MIGRATED: from .keyword_buckets -> backend.detection.keywords.buckets
from backend.detection.keywords.buckets import (
    RoomSearchIntent,
    ACTION_REQUEST_PATTERNS,
    AVAILABILITY_TOKENS,
    RESUME_PHRASES,
    OPTION_KEYWORDS,
    CAPACITY_KEYWORDS,
    ALTERNATIVE_KEYWORDS,
    ENHANCED_CONFIRMATION_KEYWORDS,
    AVAILABILITY_KEYWORDS,
)

__all__ = [
    "detect_general_room_query",
    "empty_general_qna_detection",
    "quick_general_qna_scan",
    "reset_general_qna_cache",
    "parse_billing_address",
    "extract_preferences",
    "detect_sequential_workflow_request",
    # Shared detection patterns
    "RoomSearchIntent",
    "ACTION_REQUEST_PATTERNS",
    "AVAILABILITY_TOKENS",
    "RESUME_PHRASES",
    "OPTION_KEYWORDS",
    "CAPACITY_KEYWORDS",
    "ALTERNATIVE_KEYWORDS",
    "ENHANCED_CONFIRMATION_KEYWORDS",
    "AVAILABILITY_KEYWORDS",
]
