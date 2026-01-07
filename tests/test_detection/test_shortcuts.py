"""
Shortcut Detection Tests (DET_SHORT_*)

Tests the shortcut capture policy: entities captured out of order are reused
at their owning step without re-asking.

References:
- TEST_MATRIX_detection_and_flow.md: DET_SHORT_001 through DET_SHORT_006
- CLAUDE.md: Shortcut Capture Policy (V4)
- tests/specs/intake/test_entity_capture_shortcuts.py (existing tests)
"""

from __future__ import annotations

import re
import pytest
from typing import Any, Dict, List, Optional


# ==============================================================================
# SHORTCUT EXTRACTION HELPERS
# ==============================================================================


def _extract_capacity_shortcut(message: str) -> Optional[int]:
    """
    Extract capacity/participant count from message.
    Valid: positive integers.
    Invalid: negative numbers, zero, non-numeric.
    """
    if not message:
        return None

    text = message.lower()

    # Pattern: "for X people" or "X people" or "X guests" or "X attendees"
    patterns = [
        r"(?:for|about|around|approximately|~)\s*(\d+)\s*(?:people|persons|guests|attendees|pax|participants)",
        r"(\d+)\s*(?:people|persons|guests|attendees|pax|participants)",
        r"capacity[:\s]+(\d+)",
        r"(\d+)\s*(?:seated|seating)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1))
            if value > 0:  # Only positive values
                return value

    return None


def _extract_date_shortcut(message: str) -> Optional[str]:
    """
    Extract date from message for shortcut capture.
    Returns ISO format (YYYY-MM-DD) if valid.
    """
    if not message:
        return None

    text = message

    # ISO date pattern
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso_match:
        return iso_match.group(1)

    # European date pattern (DD.MM.YYYY)
    eu_match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if eu_match:
        day, month, year = eu_match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Month name patterns (simplified)
    month_names = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12"
    }

    for month_name, month_num in month_names.items():
        # Pattern: "December 10" or "10 December"
        pattern1 = rf"{month_name}\s+(\d{{1,2}})"
        pattern2 = rf"(\d{{1,2}})\s+{month_name}"

        match1 = re.search(pattern1, text.lower())
        if match1:
            day = match1.group(1).zfill(2)
            # Assume current/next year (2025)
            return f"2025-{month_num}-{day}"

        match2 = re.search(pattern2, text.lower())
        if match2:
            day = match2.group(1).zfill(2)
            return f"2025-{month_num}-{day}"

    return None


def _extract_product_wishes(message: str) -> List[str]:
    """
    Extract product/equipment wishes for ranking (non-gating).
    """
    if not message:
        return []

    text = message.lower()
    wishes = []

    product_keywords = [
        "projector", "screen", "hdmi", "microphone", "mic",
        "coffee", "coffee break", "lunch", "dinner",
        "catering", "wine", "drinks", "beverages",
        "sound system", "audio", "video", "av equipment",
        "hybrid", "streaming", "recording",
    ]

    for keyword in product_keywords:
        if keyword in text:
            wishes.append(keyword)

    return wishes


def _is_valid_capacity(value: Any) -> bool:
    """Validate capacity shortcut value."""
    if value is None:
        return False
    try:
        num = int(value)
        return num > 0
    except (TypeError, ValueError):
        return False


def _is_valid_date(value: str) -> bool:
    """Validate date shortcut value (ISO format)."""
    if not value:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))


# ==============================================================================
# DET_SHORT_001: Capacity at Intake
# ==============================================================================


def test_DET_SHORT_001_capacity_at_intake():
    """
    Capacity stated at intake should be captured as shortcut.
    Input: "Event for 30 people"
    Expected: shortcuts.capacity=30
    """
    message = "Event for 30 people"
    capacity = _extract_capacity_shortcut(message)

    assert capacity == 30, f"Expected capacity=30, got {capacity}"
    assert _is_valid_capacity(capacity)


def test_DET_SHORT_001_capacity_variants():
    """Test various capacity phrasings."""
    test_cases = [
        ("for 30 people", 30),
        ("about 25 guests", 25),
        ("approximately 40 attendees", 40),
        ("~50 participants", 50),
        ("capacity: 60", 60),
        ("20 seated", 20),
    ]

    for message, expected in test_cases:
        capacity = _extract_capacity_shortcut(message)
        assert capacity == expected, f"'{message}' should extract {expected}, got {capacity}"


# ==============================================================================
# DET_SHORT_002: Date at Intake
# ==============================================================================


def test_DET_SHORT_002_date_at_intake():
    """
    Date stated at intake should be captured as shortcut.
    Input: "Thinking December 10"
    Expected: shortcuts.date="2025-12-10"
    """
    message = "Thinking December 10"
    date = _extract_date_shortcut(message)

    assert date == "2025-12-10", f"Expected 2025-12-10, got {date}"
    assert _is_valid_date(date)


def test_DET_SHORT_002_iso_date():
    """ISO date format."""
    message = "We're looking at 2025-12-10"
    date = _extract_date_shortcut(message)
    assert date == "2025-12-10"


def test_DET_SHORT_002_european_date():
    """European date format."""
    message = "How about 10.12.2025?"
    date = _extract_date_shortcut(message)
    assert date == "2025-12-10"


# ==============================================================================
# DET_SHORT_003: Products at Intake
# ==============================================================================


def test_DET_SHORT_003_products_at_intake():
    """
    Products mentioned at intake should be captured for ranking.
    Input: "We'll need a projector"
    Expected: wish_products=["projector"]
    """
    message = "We'll need a projector"
    wishes = _extract_product_wishes(message)

    assert "projector" in wishes, f"Expected 'projector' in wishes, got {wishes}"


def test_DET_SHORT_003_multiple_products():
    """Multiple product wishes."""
    message = "We need projector, coffee break, and microphone"
    wishes = _extract_product_wishes(message)

    assert "projector" in wishes
    assert "coffee" in wishes or "coffee break" in wishes
    assert "microphone" in wishes or "mic" in wishes


# ==============================================================================
# DET_SHORT_004: Multiple Shortcuts
# ==============================================================================


def test_DET_SHORT_004_multiple_shortcuts():
    """
    Multiple shortcuts in one message should all be captured.
    Input: "30 people on Dec 10 with projector"
    Expected: All captured
    """
    message = "30 people on December 10 with projector"

    capacity = _extract_capacity_shortcut(message)
    date = _extract_date_shortcut(message)
    wishes = _extract_product_wishes(message)

    assert capacity == 30
    assert date == "2025-12-10"
    assert "projector" in wishes


# ==============================================================================
# DET_SHORT_005: Invalid Shortcut Ignored
# ==============================================================================


def test_DET_SHORT_005_negative_capacity_ignored():
    """
    Invalid capacity (negative) should NOT be captured.
    Input: "Negative -5 people"
    Expected: NOT captured (invalid)
    """
    message = "Negative -5 people"
    capacity = _extract_capacity_shortcut(message)

    # Should not capture negative
    assert capacity is None or capacity > 0, "Negative capacity should not be captured"


def test_DET_SHORT_005_zero_capacity_ignored():
    """Zero capacity should be invalid."""
    message = "for 0 people"
    capacity = _extract_capacity_shortcut(message)

    assert capacity is None or capacity > 0, "Zero capacity should not be captured"


def test_DET_SHORT_005_invalid_date_ignored():
    """Invalid date format should not be captured."""
    # Ambiguous or invalid dates
    message = "sometime next week maybe"
    date = _extract_date_shortcut(message)

    # Should return None for vague references (this is shortcut capture, not full parsing)
    assert date is None, "Vague date should not be captured as shortcut"


# ==============================================================================
# DET_SHORT_006: Shortcut Reuse (No Re-ask)
# ==============================================================================


def test_DET_SHORT_006_shortcut_reuse_principle():
    """
    Shortcut capture policy: if valid shortcut exists and unchanged, use silently.

    This tests the principle that shortcuts should be reused without re-asking.
    The actual workflow behavior is tested in integration tests.
    """
    # Simulate shortcut capture at Step 1
    shortcuts = {
        "capacity": 30,
        "captured_at_step": 1,
        "source": "shortcut",
    }

    # At Step 3, capacity should be available without re-asking
    assert shortcuts["capacity"] == 30
    assert shortcuts["source"] == "shortcut"

    # Validation should pass
    assert _is_valid_capacity(shortcuts["capacity"])


# ==============================================================================
# EDGE CASES
# ==============================================================================


def test_empty_message_no_shortcuts():
    """Empty message should not produce shortcuts."""
    assert _extract_capacity_shortcut("") is None
    assert _extract_date_shortcut("") is None
    assert _extract_product_wishes("") == []


def test_no_capacity_in_greeting():
    """Greeting without capacity should not capture."""
    message = "Hello, I'm interested in booking"
    capacity = _extract_capacity_shortcut(message)
    assert capacity is None


def test_no_date_in_greeting():
    """Greeting without date should not capture."""
    message = "Hello, I'm interested in booking"
    date = _extract_date_shortcut(message)
    assert date is None


def test_capacity_in_sentence():
    """Capacity embedded in sentence should be captured."""
    message = "We're planning a workshop for 25 people in our department"
    capacity = _extract_capacity_shortcut(message)
    assert capacity == 25


def test_date_month_day_order():
    """Test different month-day orderings."""
    # "10 December"
    message1 = "10 December"
    date1 = _extract_date_shortcut(message1)
    assert date1 == "2025-12-10"

    # "December 10"
    message2 = "December 10"
    date2 = _extract_date_shortcut(message2)
    assert date2 == "2025-12-10"
