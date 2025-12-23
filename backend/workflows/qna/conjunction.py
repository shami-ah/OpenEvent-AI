"""
Q&A Conjunction Analysis

Analyzes conjuncted Q&A questions to determine the relationship between parts:
- Case A (independent): Different selects → separate answer sections
- Case B (and_combined): Same select, compatible conditions → single combined answer
- Case C (or_union): Same select, conflicting conditions → ranked results (both first)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# MIGRATED: from backend.llm.intent_classifier -> backend.detection.intent.classifier
from backend.detection.intent.classifier import QNA_TYPE_TO_STEP


# Mapping Q&A types to their select target (what entity they query)
QNA_TYPE_TO_SELECT = {
    "free_dates": "dates",
    "check_availability": "dates",
    "rooms_by_feature": "rooms",
    "room_features": "rooms",
    "check_capacity": "rooms",
    "check_alternatives": "rooms",
    "catering_for": "menus",
    "products_for": "products",
    "request_option": "products",
    "site_visit_overview": "site_visit",
    "parking_policy": "policy",
    "confirm_booking": "booking",
}


@dataclass
class QnAPart:
    """Represents a single Q&A query part."""

    select: str  # "rooms", "menus", "dates", "packages", etc.
    qna_type: str  # Original Q&A type from classifier
    conditions: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""  # Original text segment if extractable


@dataclass
class ConjunctionAnalysis:
    """Result of analyzing conjuncted Q&A parts."""

    parts: List[QnAPart]
    relationship: str  # "independent" | "and_combined" | "or_union" | "single"

    @property
    def is_multi_part(self) -> bool:
        """True if there are multiple Q&A parts."""
        return len(self.parts) > 1

    @property
    def is_independent(self) -> bool:
        """True if parts query different entities (separate answers needed)."""
        return self.relationship == "independent"

    @property
    def is_combined(self) -> bool:
        """True if parts should be combined with AND logic."""
        return self.relationship == "and_combined"

    @property
    def is_union(self) -> bool:
        """True if parts should be combined with OR logic (ranked results)."""
        return self.relationship == "or_union"


# Month patterns for condition extraction
_MONTH_PATTERN = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)

# Feature patterns for condition extraction
_FEATURE_PATTERNS = {
    "projector": re.compile(r"\b(projector|beamer|screen)\b", re.IGNORECASE),
    "music": re.compile(r"\b(music|background\s*music|sound\s*system|speakers)\b", re.IGNORECASE),
    "kitchen": re.compile(r"\b(kitchen|cooking|culinary)\b", re.IGNORECASE),
    "vegetarian": re.compile(r"\b(vegetarian|vegan|plant[- ]?based)\b", re.IGNORECASE),
    "whiteboard": re.compile(r"\b(whiteboard|flipchart)\b", re.IGNORECASE),
    "parking": re.compile(r"\b(parking|car\s*park)\b", re.IGNORECASE),
    "wifi": re.compile(r"\b(wifi|wi-fi|internet)\b", re.IGNORECASE),
}

# Capacity pattern
_CAPACITY_PATTERN = re.compile(r"\b(\d+)\s*(people|persons|guests|attendees|visitors|pax)\b", re.IGNORECASE)


def analyze_conjunction(secondary: List[str], text: str) -> ConjunctionAnalysis:
    """
    Analyze conjuncted Q&A to determine relationship between parts.

    Args:
        secondary: List of Q&A types detected by intent classifier
        text: Original message text for condition extraction

    Returns:
        ConjunctionAnalysis with parts and their relationship
    """
    if not secondary:
        return ConjunctionAnalysis(parts=[], relationship="single")

    # Extract parts from Q&A types
    parts = _extract_qna_parts(secondary, text)

    if len(parts) <= 1:
        return ConjunctionAnalysis(parts=parts, relationship="single")

    # Classify the relationship between parts
    relationship = _classify_relationship(parts)

    return ConjunctionAnalysis(parts=parts, relationship=relationship)


def _extract_qna_parts(secondary: List[str], text: str) -> List[QnAPart]:
    """
    Extract Q&A parts from secondary types and enrich with conditions.

    Splits text into segments and extracts conditions per-segment to handle
    cases like "What menus in January and what rooms in February?"
    """
    parts: List[QnAPart] = []

    # Split text into segments for per-part condition extraction
    segments = _split_into_segments(text)

    # Track used segments to avoid duplicate assignment when same type appears twice
    used_segment_indices: Set[int] = set()

    # Match each Q&A type to its most relevant segment
    for qna_type in secondary:
        select = QNA_TYPE_TO_SELECT.get(qna_type, "general")

        # Find the segment that best matches this Q&A type (excluding already used)
        matching_segment, segment_idx = _find_matching_segment(
            select, qna_type, segments, used_segment_indices
        )
        segment_text = matching_segment if matching_segment else text

        if segment_idx is not None:
            used_segment_indices.add(segment_idx)

        # Extract conditions from the matched segment
        segment_conditions = _extract_conditions(segment_text)

        # Create part with segment-specific conditions
        part = QnAPart(
            select=select,
            qna_type=qna_type,
            conditions=segment_conditions,
            raw_text=segment_text,
        )

        # Add type-specific conditions
        if qna_type in ("catering_for", "products_for"):
            # Check for dietary conditions
            for feature in ("vegetarian",):
                if feature in segment_conditions.get("features", []):
                    part.conditions.setdefault("dietary", []).append(feature)

        parts.append(part)

    return parts


# Keywords that indicate which select target a segment is about
_SELECT_KEYWORDS = {
    "rooms": ["room", "rooms", "space", "spaces", "venue", "hall", "capacity", "fit", "seat"],
    "menus": ["menu", "menus", "catering", "food", "lunch", "dinner", "breakfast", "meal", "buffet", "package"],
    "dates": ["date", "dates", "availability", "available", "free", "when", "day", "days"],
    "products": ["product", "products", "add-on", "addon", "option", "options", "extra", "extras"],
    "site_visit": ["site visit", "visit", "tour", "viewing"],
    "policy": ["policy", "parking", "cancellation", "terms"],
}


def _split_into_segments(text: str) -> List[str]:
    """
    Split text into segments based on conjunctions and sentence boundaries.

    Handles patterns like:
    - "X and Y" → ["X", "Y"]
    - "X? Y?" → ["X?", "Y?"]
    - "X. Y" → ["X.", "Y"]
    """
    # First split on question marks (each question is likely a separate part)
    # But keep the question mark with its segment
    segments: List[str] = []

    # Split on " and " when it separates different questions/topics
    # Pattern: look for "and what", "and which", "and are there", etc.
    and_split_pattern = re.compile(
        r"\s+and\s+(?=what|which|are there|do you|can you|is there|how|where)",
        re.IGNORECASE,
    )
    preliminary = and_split_pattern.split(text)

    for segment in preliminary:
        # Further split on sentence boundaries if segment contains multiple questions
        question_parts = re.split(r"(?<=[?.])\s+", segment)
        for part in question_parts:
            part = part.strip()
            if part:
                segments.append(part)

    # If no splits occurred, return the whole text as one segment
    if not segments:
        segments = [text]

    return segments


def _find_matching_segment(
    select: str,
    qna_type: str,
    segments: List[str],
    used_indices: Set[int],
) -> Tuple[Optional[str], Optional[int]]:
    """
    Find the segment that best matches a given select target.

    Uses keyword matching to identify which segment discusses the entity.
    Excludes segments at indices in used_indices to handle duplicate Q&A types.

    Returns:
        Tuple of (segment_text, segment_index) or (None, None) if no match.
    """
    if not segments:
        return None, None

    if len(segments) == 1:
        if 0 not in used_indices:
            return segments[0], 0
        return None, None

    keywords = _SELECT_KEYWORDS.get(select, [])

    # Score each segment by keyword matches (excluding already used)
    best_segment: Optional[str] = None
    best_idx: Optional[int] = None
    best_score = 0

    for idx, segment in enumerate(segments):
        if idx in used_indices:
            continue
        segment_lower = segment.lower()
        score = sum(1 for kw in keywords if kw in segment_lower)
        # Give a small bonus for having any match at all
        if score > best_score:
            best_score = score
            best_segment = segment
            best_idx = idx

    # If no keyword match found, assign first unused segment in order
    if best_segment is None:
        for idx, segment in enumerate(segments):
            if idx not in used_indices:
                return segment, idx
        return None, None

    return best_segment, best_idx


def _extract_conditions(text: str) -> Dict[str, Any]:
    """
    Extract conditions (filters) from Q&A text.

    Extracts:
    - month/date references
    - capacity requirements
    - feature requirements
    """
    conditions: Dict[str, Any] = {}

    # Extract month
    month_match = _MONTH_PATTERN.search(text)
    if month_match:
        month = month_match.group(1).lower()
        # Normalize short forms
        month_map = {
            "jan": "january", "feb": "february", "mar": "march", "apr": "april",
            "jun": "june", "jul": "july", "aug": "august", "sep": "september",
            "sept": "september", "oct": "october", "nov": "november", "dec": "december",
        }
        conditions["month"] = month_map.get(month, month)

    # Extract capacity
    capacity_match = _CAPACITY_PATTERN.search(text)
    if capacity_match:
        try:
            conditions["capacity"] = int(capacity_match.group(1))
        except ValueError:
            pass

    # Extract features
    features: List[str] = []
    for feature_name, pattern in _FEATURE_PATTERNS.items():
        if pattern.search(text):
            features.append(feature_name)
    if features:
        conditions["features"] = features

    return conditions


def _classify_relationship(parts: List[QnAPart]) -> str:
    """
    Classify the relationship between Q&A parts.

    Returns:
        - "independent": Different selects → separate answers
        - "and_combined": Same select, compatible conditions → combine
        - "or_union": Same select, conflicting conditions → ranked results
    """
    selects = {p.select for p in parts}

    # Case A: Different selects → independent answers
    if len(selects) > 1:
        return "independent"

    # Same select - check if conditions are compatible or conflicting
    all_conditions = [p.conditions for p in parts]

    if _conditions_conflict(all_conditions):
        # Case C: Conflicting conditions → OR with ranking
        return "or_union"

    # Case B: Compatible conditions → AND combined
    return "and_combined"


def _conditions_conflict(conditions_list: List[Dict[str, Any]]) -> bool:
    """
    Check if conditions conflict with each other.

    Conflicts occur when:
    - Same key has different values (e.g., month=January vs month=December)
    """
    # Check month conflicts
    months = [c.get("month") for c in conditions_list if c.get("month")]
    if len(set(months)) > 1:
        return True

    # Check capacity conflicts (different specific values)
    capacities = [c.get("capacity") for c in conditions_list if c.get("capacity")]
    if len(set(capacities)) > 1:
        return True

    return False


def get_combined_conditions(parts: List[QnAPart]) -> Dict[str, Any]:
    """
    Merge conditions from all parts (for and_combined relationship).
    """
    combined: Dict[str, Any] = {}

    for part in parts:
        for key, value in part.conditions.items():
            if key not in combined:
                combined[key] = value
            elif isinstance(value, list):
                # Merge lists (e.g., features)
                existing = combined[key] if isinstance(combined[key], list) else [combined[key]]
                combined[key] = list(set(existing + value))

    return combined


def get_union_conditions(parts: List[QnAPart]) -> List[Dict[str, Any]]:
    """
    Return separate conditions for OR union (for ranking).
    """
    return [part.conditions for part in parts]


__all__ = [
    "QnAPart",
    "ConjunctionAnalysis",
    "analyze_conjunction",
    "get_combined_conditions",
    "get_union_conditions",
]
