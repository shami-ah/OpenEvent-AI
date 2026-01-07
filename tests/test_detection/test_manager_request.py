"""
Manager Request Detection Tests (DET_MGR_*)

Tests the special manager/escalation request detection logic.
These requests should trigger manual review routing.

References:
- TEST_MATRIX_detection_and_flow.md: DET_MGR_001 through DET_MGR_006
- backend/llm/intent_classifier.py: _looks_like_manager_request
"""

from __future__ import annotations

import pytest

# MIGRATED: from llm.intent_classifier -> backend.detection.intent.classifier
from detection.intent.classifier import _looks_like_manager_request


# ==============================================================================
# DET_MGR_001: Explicit Escalation Request
# ==============================================================================


def test_DET_MGR_001_speak_with_manager():
    """
    Explicit manager request should be detected.
    Input: "I need to speak with a manager"
    Expected: _looks_like_manager_request=True
    """
    message = "I need to speak with a manager"
    assert _looks_like_manager_request(message.lower()) is True


def test_DET_MGR_001_talk_to_manager():
    """Variant: talk to manager."""
    message = "Can I talk to a manager please?"
    assert _looks_like_manager_request(message.lower()) is True


# ==============================================================================
# DET_MGR_002: Human Request
# ==============================================================================


def test_DET_MGR_002_human_request():
    """
    Request to speak with a human should be detected.
    Input: "Can I talk to a human?"
    Expected: _looks_like_manager_request=True
    """
    message = "Can I talk to a human?"
    assert _looks_like_manager_request(message.lower()) is True


def test_DET_MGR_002_real_person():
    """Variant: real person request."""
    message = "I'd like to speak with a real person"
    assert _looks_like_manager_request(message.lower()) is True


# ==============================================================================
# DET_MGR_003: Connect Request
# ==============================================================================


def test_DET_MGR_003_connect_someone():
    """
    Connect request should be detected.
    Input: "Please connect me with someone"
    Expected: _looks_like_manager_request=True
    """
    message = "Please connect me with someone"
    assert _looks_like_manager_request(message.lower()) is True


# ==============================================================================
# DET_MGR_004: Escalation Keyword
# ==============================================================================


def test_DET_MGR_004_escalate():
    """
    Escalation keyword should be detected.
    Input: "I want to escalate this"
    Expected: _looks_like_manager_request=True
    """
    message = "I want to escalate this"
    assert _looks_like_manager_request(message.lower()) is True


def test_DET_MGR_004_escalation_needed():
    """Variant: escalation needed."""
    message = "This needs escalation"
    assert _looks_like_manager_request(message.lower()) is True


# ==============================================================================
# DET_MGR_005: NOT Manager Request (Manager in Different Context)
# ==============================================================================


def test_DET_MGR_005_manager_approved():
    """
    'Manager' in a different context should NOT trigger detection.
    Input: "The manager approved the budget"
    Expected: _looks_like_manager_request=False
    """
    message = "The manager approved the budget"
    assert _looks_like_manager_request(message.lower()) is False


def test_DET_MGR_005_manager_will_attend():
    """Variant: manager attending event."""
    message = "Our manager will attend the event"
    assert _looks_like_manager_request(message.lower()) is False


# ==============================================================================
# DET_MGR_006: NOT Manager Request (Send to Manager)
# ==============================================================================


def test_DET_MGR_006_send_to_manager():
    """
    'Send to manager' is about document routing, not escalation.
    Input: "Please send the offer to my manager"
    Expected: _looks_like_manager_request=False
    """
    message = "Please send the offer to my manager"
    assert _looks_like_manager_request(message.lower()) is False


def test_DET_MGR_006_cc_manager():
    """Variant: CC manager."""
    message = "Can you CC my manager on the confirmation?"
    assert _looks_like_manager_request(message.lower()) is False


# ==============================================================================
# EDGE CASES
# ==============================================================================


def test_empty_message_no_manager():
    """Empty message should not be a manager request."""
    assert _looks_like_manager_request("") is False


def test_none_message_no_manager():
    """None-like message should not crash."""
    # The function expects a string; test with empty
    assert _looks_like_manager_request("") is False


def test_greeting_no_manager():
    """Simple greeting should not be a manager request."""
    message = "Hello, good morning!"
    assert _looks_like_manager_request(message.lower()) is False


def test_date_confirmation_no_manager():
    """Date confirmation should not be a manager request."""
    message = "December 15 works for us"
    assert _looks_like_manager_request(message.lower()) is False
