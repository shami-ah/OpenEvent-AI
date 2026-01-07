"""
Q&A Detection Tests (DET_QNA_*)

Tests the Q&A classification logic in intent_classifier.py and general_qna_classifier.py.
Ensures that Q&A questions are detected correctly and do not trigger legacy fallback messages.

References:
- TEST_MATRIX_detection_and_flow.md: DET_QNA_001 through DET_QNA_006, DET_QNA_FALLBACK_*
- TEAM_GUIDE.md: Regression trap: quoted confirmations triggering General Q&A
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from typing import List

# MIGRATED: from llm.intent_classifier -> backend.detection.intent.classifier
from detection.intent.classifier import classify_intent, _detect_qna_types
# MIGRATED: from workflows.nlu.general_qna_classifier -> backend.detection.qna.general_qna
from detection.qna.general_qna import (
    detect_general_room_query,
    reset_general_qna_cache,
)

# ==============================================================================
# ANTI-FALLBACK ASSERTIONS
# ==============================================================================

FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
]


def assert_no_fallback(response_body: str, context: str = ""):
    """Assert that response does not contain legacy fallback messages."""
    if not response_body:
        return
    lowered = response_body.lower()
    for pattern in FALLBACK_PATTERNS:
        assert pattern not in lowered, (
            f"Fallback detected: '{pattern}' in response. {context}\n"
            f"Response: {response_body[:200]}..."
        )


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture(autouse=True)
def reset_qna_cache():
    """Reset Q&A cache before each test for isolation."""
    reset_general_qna_cache()
    yield
    reset_general_qna_cache()


def _state() -> SimpleNamespace:
    """Create a minimal workflow state for testing."""
    return SimpleNamespace(user_info={}, locale="en")


# ==============================================================================
# DET_QNA_001: Room Features Question
# ==============================================================================


def test_DET_QNA_001_room_features_question():
    """
    Room features question should be detected as Q&A.
    Input: "Do your rooms have HDMI?"
    Expected: secondary contains 'rooms_by_feature'
    """
    message = "Do your rooms have HDMI?"

    # Test Q&A type detection
    qna_types = _detect_qna_types(message.lower())
    assert "rooms_by_feature" in qna_types, f"Expected 'rooms_by_feature' in {qna_types}"


def test_DET_QNA_001_projector_question():
    """Room equipment question variant."""
    message = "Which rooms have a projector?"
    qna_types = _detect_qna_types(message.lower())
    assert "rooms_by_feature" in qna_types


# ==============================================================================
# DET_QNA_002: Availability Question (General Query)
# ==============================================================================


def test_DET_QNA_002_availability_question():
    """
    Availability question with vague date should be detected as general Q&A.
    Input: "Which rooms are free on Saturdays in February for 30 people?"
    Expected: is_general=True, vague_month=february
    """
    message = "Which rooms are free on Saturdays in February for 30 people?"
    state = _state()

    result = detect_general_room_query(message, state)

    assert result["is_general"] is True, f"Expected is_general=True, got {result}"
    assert result["constraints"]["vague_month"] == "february", (
        f"Expected vague_month='february', got {result['constraints']}"
    )
    assert result["constraints"]["pax"] == 30, (
        f"Expected pax=30, got {result['constraints']}"
    )


def test_DET_QNA_002_saturday_evening_variant():
    """Variant with time of day."""
    message = "Are there rooms available Saturday evenings in March?"
    state = _state()

    result = detect_general_room_query(message, state)

    assert result["is_general"] is True
    assert result["constraints"]["vague_month"] == "march"
    assert result["constraints"]["time_of_day"] == "evening"


# ==============================================================================
# DET_QNA_003: Catering Question
# ==============================================================================


def test_DET_QNA_003_catering_question():
    """
    Catering question should be detected as Q&A.
    Input: "What menus do you offer?"
    Expected: secondary contains 'catering_for'
    """
    message = "What menus do you offer?"
    qna_types = _detect_qna_types(message.lower())
    assert "catering_for" in qna_types


def test_DET_QNA_003_coffee_break_question():
    """Coffee break variant."""
    message = "Do you provide coffee breaks?"
    qna_types = _detect_qna_types(message.lower())
    assert "catering_for" in qna_types


# ==============================================================================
# DET_QNA_004: Mixed Step + Q&A
# ==============================================================================


def test_DET_QNA_004_mixed_step_and_qna():
    """
    Mixed message with date + Q&A should prioritize step but detect Q&A.
    Input: "December 10-11 for 22 ppl. Do rooms have HDMI?"
    Expected: primary=date_confirmation, secondary contains 'rooms_by_feature'
    """
    message = "December 10-11 for 22 ppl. Do rooms have HDMI?"

    # Classify intent - step 2 context
    classification = classify_intent(message, current_step=2)

    # Primary should be step-related
    assert classification["primary"] in ["date_confirmation", "event_request"], (
        f"Expected step-related primary, got {classification['primary']}"
    )

    # Secondary should include Q&A
    assert "rooms_by_feature" in classification.get("secondary", []), (
        f"Expected 'rooms_by_feature' in secondary, got {classification}"
    )


# ==============================================================================
# DET_QNA_005: Site Visit Question
# ==============================================================================


def test_DET_QNA_005_site_visit_question():
    """
    Site visit question should be detected as Q&A.
    Input: "Can we arrange a tour of the venue?"
    """
    message = "Can we arrange a tour of the venue?"
    qna_types = _detect_qna_types(message.lower())
    assert "site_visit_overview" in qna_types


def test_DET_QNA_005_walkthrough_variant():
    """Walkthrough variant."""
    message = "Would it be possible to do a walkthrough before booking?"
    qna_types = _detect_qna_types(message.lower())
    assert "site_visit_overview" in qna_types


# ==============================================================================
# DET_QNA_006: Parking Policy Question
# ==============================================================================


def test_DET_QNA_006_parking_question():
    """
    Parking question should be detected as Q&A.
    Input: "Where can guests park?"
    """
    message = "Where can guests park?"
    qna_types = _detect_qna_types(message.lower())
    assert "parking_policy" in qna_types


# ==============================================================================
# DET_QNA_FALLBACK_001: General Q&A Must Not Return Stub
# ==============================================================================


def test_DET_QNA_FALLBACK_001_no_stub_for_general_qna():
    """
    General Q&A detection result should never contain fallback language.
    The 'no specific information available' stub is a bug indicator.
    """
    message = "Which rooms are available for 40 people on weekends in April?"
    state = _state()

    result = detect_general_room_query(message, state)

    # The detection result itself shouldn't have fallback
    assert result["is_general"] is True, "Should be detected as general Q&A"

    # If there's a response body, check for fallback
    response_body = result.get("response", "") or ""
    if response_body:
        assert_no_fallback(response_body, context="General Q&A response")


# ==============================================================================
# DET_QNA_FALLBACK_002: Non-General Message Should Not Trigger Q&A Path
# ==============================================================================


def test_DET_QNA_FALLBACK_002_non_general_no_qna():
    """
    Non-general messages (e.g., product requests) should not trigger Q&A path.
    Input: "Please send menu options and pricing."
    Expected: is_general=False
    """
    message = "Please send menu options and pricing."
    state = _state()

    result = detect_general_room_query(message, state)

    assert result["is_general"] is False, (
        f"Product request should not be general Q&A: {result}"
    )


# ==============================================================================
# DET_QNA_FALLBACK_003: Room Features Query Must Return Data
# ==============================================================================


def test_DET_QNA_FALLBACK_003_features_returns_data():
    """
    Room features query should be detectable without returning stub.
    The actual room data comes from the workflow, but detection should work.
    """
    message = "Which of your rooms have AV equipment?"
    qna_types = _detect_qna_types(message.lower())

    # Should detect as rooms_by_feature
    assert "rooms_by_feature" in qna_types, f"Expected rooms_by_feature detection"


# ==============================================================================
# EDGE CASES AND VARIANTS
# ==============================================================================


def test_qna_cache_works():
    """Test that Q&A cache prevents duplicate processing."""
    reset_general_qna_cache()
    message = "Which rooms are free on Saturdays in February for 30 people?"
    state = _state()

    # First call - not cached
    result1 = detect_general_room_query(message, state)
    assert result1.get("cached") is not True

    # Second call - should be cached
    result2 = detect_general_room_query(message, state)
    assert result2.get("cached") is True


def test_empty_message_not_general():
    """Empty message should not be detected as general Q&A."""
    state = _state()
    result = detect_general_room_query("", state)
    assert result["is_general"] is False


def test_short_greeting_not_general():
    """Short greeting should not be detected as general Q&A."""
    state = _state()
    result = detect_general_room_query("Hello", state)
    assert result["is_general"] is False


def test_pure_date_not_general():
    """Pure date message should not be general Q&A (it's a confirmation)."""
    state = _state()
    result = detect_general_room_query("2025-12-10 18:00-22:00", state)
    assert result["is_general"] is False


def test_action_request_not_treated_as_qna():
    """Action requests like 'send me the menu' should bypass Q&A routing."""
    state = _state()
    message = "Can you send me the menu?"
    qna_types = _detect_qna_types(message.lower())
    assert qna_types == []

    result = detect_general_room_query(message, state)
    assert result["is_general"] is False
    assert result["heuristics"].get("action_request") is True
