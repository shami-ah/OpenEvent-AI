"""
MODULE: backend/detection/response/matchers.py
PURPOSE: Semantic pattern matching for client response classification.

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # Keyword patterns for EN/DE
    - backend/services/rooms.py              # Room catalog for dynamic patterns

USED BY:
    - backend/workflows/groups/negotiation_close.py  # Response classification
    - backend/workflows/groups/offer/trigger/process.py  # Acceptance detection
    - backend/tests/detection/test_semantic_matchers.py
    - backend/tests/detection/test_detour_detection.py

EXPORTS:
    - matches_acceptance_pattern(text) -> (bool, float, str)
    - matches_decline_pattern(text) -> (bool, float, str)
    - matches_counter_pattern(text) -> (bool, float, str)
    - matches_change_pattern(text) -> (bool, float, str)
    - matches_change_pattern_enhanced(text, event_state) -> (bool, float, str, ChangeIntentResult)
    - is_pure_qa_message(text) -> bool
    - looks_hypothetical(text) -> bool
    - is_room_selection(text) -> bool
    - ACCEPTANCE_PATTERNS, DECLINE_PATTERNS, COUNTER_PATTERNS, CHANGE_PATTERNS

RELATED TESTS:
    - backend/tests/detection/test_semantic_matchers.py
    - backend/tests/detection/test_detour_detection.py

---

Semantic pattern matching for client responses.
Uses regex patterns + fuzzy matching instead of exact keyword lists.

Enhanced with comprehensive EN/DE keyword buckets for detour detection.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from backend.services.rooms import load_room_catalog

# Import comprehensive keyword buckets for enhanced detection
from backend.detection.keywords.buckets import (
    CHANGE_VERBS_EN,
    CHANGE_VERBS_DE,
    REVISION_MARKERS_EN,
    REVISION_MARKERS_DE,
    PURE_QA_SIGNALS_EN,
    PURE_QA_SIGNALS_DE,
    CONFIRMATION_SIGNALS_EN,
    CONFIRMATION_SIGNALS_DE,
    DECLINE_SIGNALS_EN,
    DECLINE_SIGNALS_DE,
    TARGET_PATTERNS,
    detect_language,
    has_revision_signal,
    has_bound_target,
    is_pure_qa,
    compute_change_intent_score,
    ChangeIntentResult,
    DetourMode,
    MessageIntent,
)

# ============================================================================
# ACCEPTANCE / DECLINE / COUNTER PATTERNS
# ============================================================================

# Explicit agreement patterns and informal approvals
ACCEPTANCE_PATTERNS = [
    r"\b(accept|agree|approved?|confirm)\w*\b",
    r"\b(looks?|sounds?|all|good\s+to)\s+(good|great|fine|okay|ok)\b",
    r"\b(yes|ok|okay|sure|yep|ja|oui)[\s,]*(please|send|go|proceed|do\s+it)?\b",
    r"\b(?:that'?s?|i'?m?|all)?\s*fine\b",  # "fine", "that's fine", "all fine"
    r"\ball\s+good\b",  # "all good" standalone
    r"\b(send\s+it|go\s+ahead|proceed|let'?s?\s+(do|go|proceed))\b",
    r"\b(works?\s+for|happy\s+with|satisfied)\b",
    r"\b(d'?accord|einverstanden|va\s+bene)\b",
    r"\b(gerne|sehr\s+gut|perfekt|perfetto|perfecto|vale|claro|muy\s+bien)\b",
    r"\b(good|great)\b",  # standalone "good", "great"
    r"\bgut\b",  # German standalone "gut"
]

# Negation words that invalidate acceptance signals
NEGATION_PATTERN = re.compile(
    r"\b(not|no|n't|don't|doesn't|didn't|isn't|wasn't|aren't|weren't|won't|"
    r"wouldn't|couldn't|shouldn't|never|neither|ohne|nicht|kein|non|pas|jamais)\b",
    re.IGNORECASE
)

DECLINE_PATTERNS = [
    r"\b(no|nope|nah)\b",
    r"\b(not\s+interested|not\s+moving\s+forward|no\s+longer\s+interested)\b",
    r"\b(cancel(?:led|ing)?|cancellation)\b",
    r"\b(pass|skip)\b",
    r"\b(decline|rejected?|turn\s+down)\b",
    r"\b(do\s+not|don't)\s+(want|proceed|move\s+forward)\b",
]

COUNTER_PATTERNS = [
    r"\b(discount|better\s+price|reduce|lower|cheaper)\b",
    r"\b(can\s+you\s+do|could\s+you\s+do|would\s+you\s+do)\s+\d",
    r"\b(counter(?:\s*offer)?)\b",
    r"\b(budget\s+is|max\s+we\s+can\s+do|meet\s+us\s+at)\b",
    r"\b(could\s+you\s+do)\b",
]

# Legacy CHANGE_PATTERNS for backward compatibility
# For enhanced detection, use matches_change_pattern_enhanced() instead
CHANGE_PATTERNS = [
    r"\b(change|modify|update|adjust|switch|move|shift|reschedule)\b",
    r"\b(instead\s+of|rather\s+than|replace\s+with|swap\s+(out|for))\b",
    r"\b(actually|correction|i\s+meant|sorry)\b",
    r"\b(can|could|would)\s+(we|i|you)\s+(please\s+)?(change|modify|update|adjust)\b",
]

# Enhanced change patterns combining all keyword buckets (EN + DE)
CHANGE_PATTERNS_ENHANCED = []
for group in CHANGE_VERBS_EN.values():
    CHANGE_PATTERNS_ENHANCED.extend(group)
for group in CHANGE_VERBS_DE.values():
    CHANGE_PATTERNS_ENHANCED.extend(group)
CHANGE_PATTERNS_ENHANCED.extend(REVISION_MARKERS_EN)
CHANGE_PATTERNS_ENHANCED.extend(REVISION_MARKERS_DE)

QUESTION_PREFIXES = (
    "do you",
    "can you",
    "could you",
    "would you",
    "what",
    "which",
    "when",
    "where",
    "how",
)

ROOM_PATTERNS = [
    r"\broom\s+[a-z]\b",  # "room a", "room b"
    r"\bpunkt\.?\s*null\b",
    r"\b(sky\s*loft|garden|terrace)\b",
]

ROOM_SELECTION_SIGNALS = [
    "looks good",
    "sounds good",
    "prefer",
    "choose",
    "go with",
    "take",
    "like",
    "works",
]

HYPOTHETICAL_MARKERS = [
    r"\bwhat\s+if\b",
    r"\bhypothetically\b",
    r"\bin\s+theory\b",
    r"\bwould\s+it\s+be\s+possible\b",
    r"\bcould\s+we\s+potentially\b",
    r"\bjust\s+(curious|wondering|asking)\b",
    r"\bthinking\s+about\b",
    r"\bconsidering\b",
]


def _score_match(text: str, match: re.Match[str], *, multiplier: float = 0.02) -> float:
    """
    Score a regex match based on length, position, and exactness.
    """
    match_length = len(match.group(0))
    start = match.start()
    exact = match.group(0).strip() == text.strip()

    score = 0.65 + (match_length * multiplier)
    if start < 10:
        score += 0.1
    if exact:
        score += 0.1
    return min(0.95, score)


def _match_patterns(text: str, patterns: Sequence[str]) -> Tuple[bool, float, str]:
    text_lower = (text or "").lower().strip()
    best: Tuple[bool, float, str] = (False, 0.0, "")
    for pattern in patterns:
        for match in re.finditer(pattern, text_lower):
            score = _score_match(text_lower, match)
            if score > best[1]:
                best = (True, score, match.group(0))
    return best


def _is_question(text: str) -> bool:
    text_lower = (text or "").strip().lower()
    if "?" in text_lower:
        return True
    return any(text_lower.startswith(prefix) for prefix in QUESTION_PREFIXES)


def matches_acceptance_pattern(text: str) -> Tuple[bool, float, str]:
    """
    Check if text matches acceptance patterns.

    Returns:
        (is_match, confidence, matched_pattern)
    """
    if _is_question(text) or is_room_selection(text):
        return False, 0.0, ""
    # Reject if text contains negation words (e.g., "not good", "doesn't look good")
    if NEGATION_PATTERN.search(text or ""):
        return False, 0.0, ""
    return _match_patterns(text, ACCEPTANCE_PATTERNS)


def matches_decline_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches decline/rejection patterns."""
    return _match_patterns(text, DECLINE_PATTERNS)


def matches_counter_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches counter/negotiation patterns."""
    return _match_patterns(text, COUNTER_PATTERNS)


def matches_change_pattern(text: str) -> Tuple[bool, float, str]:
    """Check if text matches change intent patterns, avoiding hypotheticals."""
    if looks_hypothetical(text):
        return False, 0.0, ""
    return _match_patterns(text, CHANGE_PATTERNS)


def matches_change_pattern_enhanced(
    text: str,
    event_state: Optional[Dict] = None,
) -> Tuple[bool, float, str, Optional[ChangeIntentResult]]:
    """
    Enhanced change detection using dual-condition logic.

    A message is only a change when BOTH conditions are met:
    1. Has revision signal (change verb OR revision marker)
    2. Has bound target (explicit value OR anaphoric reference)

    This prevents false positives on pure Q&A questions like:
    - "What rooms are free in December?" -> NOT a change
    - "Do you have parking?" -> NOT a change

    Args:
        text: Client message text
        event_state: Optional event state for checking confirmed values

    Returns:
        (is_match, confidence, matched_pattern, full_result)
        - full_result contains detailed ChangeIntentResult if change detected
    """
    if looks_hypothetical(text):
        return False, 0.0, "", None

    # Use comprehensive dual-condition detection
    result = compute_change_intent_score(text, event_state)

    if result.has_change_intent:
        # Return first matched pattern for compatibility
        matched = result.revision_signals[0] if result.revision_signals else ""
        return True, result.score, matched, result

    return False, result.score, "", result


def is_pure_qa_message(text: str) -> bool:
    """
    Check if message is a pure Q&A question without change intent.

    Use this to filter out messages that should go to Q&A handler
    instead of triggering a detour.

    Examples that return True:
    - "What rooms are free in December?"
    - "Do you have parking?"
    - "Was kostet das?"

    Examples that return False:
    - "Can we change the date?"
    - "Sorry, I meant February 28th"
    """
    language = detect_language(text)
    return is_pure_qa(text, language)


def looks_hypothetical(text: str) -> bool:
    """Check if message is a hypothetical question vs actual request."""
    text_lower = (text or "").lower()
    if not text_lower:
        return False
    has_marker = any(re.search(marker, text_lower) for marker in HYPOTHETICAL_MARKERS)
    return has_marker and ("?" in text_lower or _is_question(text_lower))


def is_room_selection(text: str) -> bool:
    """Detect if a message is selecting a room rather than accepting an offer."""
    text_lower = (text or "").lower()
    room_patterns = ROOM_PATTERNS + _room_patterns_from_catalog()
    mentions_room = any(re.search(pattern, text_lower) for pattern in room_patterns)
    if not mentions_room:
        return False
    return any(signal in text_lower for signal in ROOM_SELECTION_SIGNALS)


@lru_cache(maxsize=1)
def _room_patterns_from_catalog() -> List[str]:
    """
    Build room regex patterns from the room catalog to avoid stale hardcoding.
    """
    patterns: List[str] = []
    try:
        for record in load_room_catalog():
            name = record.name.strip().lower()
            room_id = record.room_id.strip().lower()
            if name:
                patterns.append(rf"\b{re.escape(name)}\b")
            if room_id and room_id != name:
                patterns.append(rf"\b{re.escape(room_id)}\b")
    except Exception:
        # Defensive: fall back to empty if catalog unavailable
        return []
    return patterns


__all__ = [
    # Pattern matching functions
    "matches_acceptance_pattern",
    "matches_decline_pattern",
    "matches_counter_pattern",
    "matches_change_pattern",
    "matches_change_pattern_enhanced",  # New: dual-condition detection
    "is_pure_qa_message",               # New: Q&A filter
    "looks_hypothetical",
    "is_room_selection",
    # Pattern lists
    "ACCEPTANCE_PATTERNS",
    "DECLINE_PATTERNS",
    "COUNTER_PATTERNS",
    "CHANGE_PATTERNS",
    "CHANGE_PATTERNS_ENHANCED",         # New: comprehensive EN/DE patterns
    # Re-exports from keyword_buckets for convenience
    "ChangeIntentResult",
    "DetourMode",
    "MessageIntent",
    "compute_change_intent_score",
    # Internal helpers exposed for testing
    "_room_patterns_from_catalog",
]
