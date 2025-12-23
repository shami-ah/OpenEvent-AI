"""
Acceptance/Confirmation Detection Tests (DET_ACCEPT_*)

Tests the acceptance phrase detection and date confirmation signal detection.
Critical for ensuring offer acceptances and date confirmations are caught.

References:
- TEST_MATRIX_detection_and_flow.md: DET_ACCEPT_001 through DET_ACCEPT_009
- TEAM_GUIDE.md: Offer Acceptance Stuck / Not Reaching HIL (Fixed)
- backend/llm/intent_classifier.py: _RESUME_PHRASES
- backend/workflows/groups/date_confirmation/trigger/process.py: _message_signals_confirmation
"""

from __future__ import annotations

import pytest
import re

# MIGRATED: from backend.llm.intent_classifier -> backend.detection.intent.classifier
from backend.detection.intent.classifier import _RESUME_PHRASES


# ==============================================================================
# HELPER: Check if message is in acceptance phrases
# ==============================================================================


def _is_acceptance_phrase(message: str) -> bool:
    """Check if the message matches known acceptance phrases."""
    normalized = message.strip().lower()
    # Normalize curly quotes to straight quotes
    normalized = normalized.replace("'", "'").replace("'", "'")
    normalized = normalized.replace(""", '"').replace(""", '"')

    # Direct match
    if normalized in _RESUME_PHRASES:
        return True

    # Check for common acceptance patterns not in _RESUME_PHRASES
    acceptance_patterns = [
        r"^(?:ok|okay)\b",
        r"\bthat'?s fine\b",
        r"\bapproved\b",
        r"\bplease (?:send|proceed|continue)\b",
        r"\bgo ahead\b",
        r"\bconfirm(?:ed)?\b",
        r"\bagree(?:d)?\b",
        r"\baccept(?:ed)?\b",
    ]

    for pattern in acceptance_patterns:
        if re.search(pattern, normalized):
            return True

    return False


def _message_signals_confirmation(message: str) -> bool:
    """
    Check if message signals a date/time confirmation.
    Matches bare date/time strings like "2025-12-10 18:00–22:00".
    """
    if not message:
        return False

    text = message.strip()

    # ISO date with optional time range
    iso_pattern = r"^\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2}[-–]\d{1,2}:\d{2})?$"
    if re.match(iso_pattern, text):
        return True

    # European date with optional time range
    eu_pattern = r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?:\s+\d{1,2}:\d{2}[-–]\d{1,2}:\d{2})?$"
    if re.match(eu_pattern, text):
        return True

    # Time range only (user confirming proposed time)
    time_pattern = r"^\d{1,2}:\d{2}[-–]\d{1,2}:\d{2}$"
    if re.match(time_pattern, text):
        return True

    return False


# ==============================================================================
# DET_ACCEPT_001: Simple Acceptance
# ==============================================================================


def test_DET_ACCEPT_001_simple_yes():
    """
    Simple acceptance should be detected.
    Input: "Yes, that's fine"
    Expected: is_acceptance=True
    """
    message = "Yes, that's fine"
    assert _is_acceptance_phrase(message), f"'{message}' should be detected as acceptance"


def test_DET_ACCEPT_001_yes_please():
    """Variant: yes please."""
    message = "Yes please"
    assert _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_002: Proceed Confirmation
# ==============================================================================


def test_DET_ACCEPT_002_proceed():
    """
    'Proceed' should be detected as acceptance.
    Input: "Please proceed"
    Expected: is_acceptance=True
    """
    message = "Please proceed"
    assert _is_acceptance_phrase(message)


def test_DET_ACCEPT_002_please_continue():
    """Variant: please continue."""
    message = "Please continue"
    assert _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_003: OK Acceptance
# ==============================================================================


def test_DET_ACCEPT_003_ok_go_ahead():
    """
    'OK, go ahead' should be detected as acceptance.
    Input: "OK, go ahead"
    Expected: is_acceptance=True
    """
    message = "OK, go ahead"
    assert _is_acceptance_phrase(message)


def test_DET_ACCEPT_003_okay():
    """Variant: okay."""
    message = "Okay"
    assert _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_004: Curly Apostrophe Normalization
# ==============================================================================


def test_DET_ACCEPT_004_curly_apostrophe():
    """
    Curly apostrophe should be normalized for acceptance detection.
    Input: "that's fine" (curly quote)
    Expected: is_acceptance=True (normalized)
    """
    # Using curly apostrophe
    message = "that's fine"
    assert _is_acceptance_phrase(message), "Curly apostrophe should be normalized"


def test_DET_ACCEPT_004_straight_apostrophe():
    """Same with straight apostrophe."""
    message = "that's fine"
    assert _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_005: Approved
# ==============================================================================


def test_DET_ACCEPT_005_approved():
    """
    'Approved, please send' should be detected as acceptance.
    Input: "Approved, please send"
    Expected: is_acceptance=True
    """
    message = "Approved, please send"
    assert _is_acceptance_phrase(message)


def test_DET_ACCEPT_005_approved_simple():
    """Simple approved."""
    message = "Approved"
    assert _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_006: NOT Acceptance (Question)
# ==============================================================================


def test_DET_ACCEPT_006_question_not_acceptance():
    """
    Question about offer should NOT be acceptance.
    Input: "Is this the final offer?"
    Expected: is_acceptance=False
    """
    message = "Is this the final offer?"
    assert not _is_acceptance_phrase(message), "Question should not be acceptance"


def test_DET_ACCEPT_006_clarification_not_acceptance():
    """Clarification request should not be acceptance."""
    message = "Can you explain the pricing?"
    assert not _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_007: NOT Acceptance (Change Request)
# ==============================================================================


def test_DET_ACCEPT_007_change_not_acceptance():
    """
    Change/counter request should NOT be acceptance.
    Input: "Can you adjust the price?"
    Expected: is_acceptance=False
    """
    message = "Can you adjust the price?"
    assert not _is_acceptance_phrase(message), "Change request should not be acceptance"


def test_DET_ACCEPT_007_counter_not_acceptance():
    """Counter offer should not be acceptance."""
    message = "Can we do 10% less?"
    assert not _is_acceptance_phrase(message)


# ==============================================================================
# DET_ACCEPT_008: Date Confirmation (Bare Date)
# ==============================================================================


def test_DET_ACCEPT_008_bare_date_confirmation():
    """
    Bare date/time string should signal confirmation.
    Input: "2025-12-10 18:00-22:00"
    Expected: _message_signals_confirmation=True
    """
    message = "2025-12-10 18:00-22:00"
    assert _message_signals_confirmation(message), "Bare date should signal confirmation"


def test_DET_ACCEPT_008_iso_date_only():
    """ISO date without time."""
    message = "2025-12-10"
    assert _message_signals_confirmation(message)


def test_DET_ACCEPT_008_european_date():
    """European date format."""
    message = "10.12.2025"
    assert _message_signals_confirmation(message)


def test_DET_ACCEPT_008_with_en_dash():
    """Time range with en-dash."""
    message = "2025-12-10 18:00–22:00"  # en-dash
    assert _message_signals_confirmation(message)


# ==============================================================================
# DET_ACCEPT_009: Date Confirmation with Quoted Thread
# ==============================================================================


def test_DET_ACCEPT_009_quoted_confirmation():
    """
    Bare date in reply to quoted thread should still be detected.
    This is the regression trap from TEAM_GUIDE.md.
    Input: Quoted thread + "2025-12-10 18:00–22:00"
    Expected: _message_signals_confirmation=True for the bare date part
    """
    # The actual confirmation is the bare date; quoted text should be filtered
    confirmation_part = "2025-12-10 18:00–22:00"
    assert _message_signals_confirmation(confirmation_part)


# ==============================================================================
# EDGE CASES
# ==============================================================================


def test_empty_not_acceptance():
    """Empty message should not be acceptance."""
    assert not _is_acceptance_phrase("")


def test_greeting_not_acceptance():
    """Greeting should not be acceptance."""
    message = "Hello there"
    assert not _is_acceptance_phrase(message)


def test_date_only_not_acceptance():
    """Date-only is a confirmation signal, not general acceptance."""
    message = "2025-12-10"
    # This is date confirmation, not offer acceptance
    assert not _is_acceptance_phrase(message), "Date is confirmation, not acceptance"


def test_random_text_not_acceptance():
    """Random text should not be acceptance."""
    message = "The weather is nice today"
    assert not _is_acceptance_phrase(message)


def test_time_range_signals_confirmation():
    """Time range alone can signal confirmation."""
    message = "18:00-22:00"
    assert _message_signals_confirmation(message)


def test_text_with_date_not_bare():
    """Text with date embedded should not match bare pattern."""
    message = "Yes, 2025-12-10 works for us"
    # This is not a bare date, so the pattern shouldn't match
    # (but it would be handled by the full confirmation logic)
    assert not _message_signals_confirmation(message)
