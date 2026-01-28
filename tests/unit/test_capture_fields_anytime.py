"""Unit tests for capture_fields_anytime global capture functionality."""

import pytest
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
from unittest.mock import MagicMock


# Mock UnifiedDetectionResult for testing without full import chain
@dataclass
class MockUnifiedDetectionResult:
    """Minimal mock of UnifiedDetectionResult for testing."""

    date: Optional[str] = None
    date_text: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room_preference: Optional[str] = None
    site_visit_date: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


@dataclass
class MockTelemetry:
    """Mock telemetry object."""

    captured_fields: List[str] = None
    deferred_intents: List[str] = None

    def __post_init__(self):
        if self.captured_fields is None:
            self.captured_fields = []
        if self.deferred_intents is None:
            self.deferred_intents = []

    def setdefault(self, key: str, default):
        if getattr(self, key, None) is None:
            setattr(self, key, default)
        return getattr(self, key)


class MockWorkflowState:
    """Minimal mock of WorkflowState for testing."""

    def __init__(self, event_entry: Optional[Dict[str, Any]] = None):
        self.event_entry = event_entry or {}
        self.extras: Dict[str, Any] = {}
        self.turn_notes: Dict[str, Any] = {}
        self.telemetry = MockTelemetry()


# Import the function after defining mocks
from workflows.common.capture import (
    capture_fields_anytime,
    FieldCaptureResult,
    _set_nested,
)


class TestCaptureFieldsAnytime:
    """Test capture_fields_anytime function."""

    def test_no_unified_result_returns_no_detection(self):
        """When unified_result is None, returns 'no_detection' source."""
        state = MockWorkflowState({"current_step": 5})
        result = capture_fields_anytime(state, None, current_step=5)

        assert result.captured is False
        assert result.source == "no_detection"

    def test_no_event_entry_returns_no_event(self):
        """When event_entry is None, returns 'no_event' source."""
        state = MockWorkflowState()
        state.event_entry = None
        unified = MockUnifiedDetectionResult(date="2026-05-15")

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is False
        assert result.source == "no_event"

    def test_captures_date_at_step_5(self):
        """Date should be captured at step 5 (outside normal step 2)."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult(date="2026-05-15")

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is True
        assert "date" in result.fields
        assert state.event_entry["captured"]["date"] == "2026-05-15"
        assert state.extras.get("persist") is True

    def test_captures_room_at_step_6(self):
        """Room preference should be captured at step 6."""
        state = MockWorkflowState({"current_step": 6})
        unified = MockUnifiedDetectionResult(room_preference="Saal A")

        result = capture_fields_anytime(state, unified, current_step=6)

        assert result.captured is True
        assert "preferred_room" in result.fields
        assert state.event_entry["captured"]["preferred_room"] == "Saal A"

    def test_captures_contact_at_step_7(self):
        """Contact info should be captured at step 7 (site visit confirmation)."""
        state = MockWorkflowState({"current_step": 7})
        unified = MockUnifiedDetectionResult(
            contact_name="Jane Doe",
            contact_email="jane@acme.com",
            contact_phone="555-1234",
        )

        result = capture_fields_anytime(state, unified, current_step=7)

        assert result.captured is True
        assert "contact.name" in result.fields
        assert "contact.email" in result.fields
        assert "contact.phone" in result.fields
        assert state.event_entry["captured"]["contact"]["name"] == "Jane Doe"
        assert state.event_entry["captured"]["contact"]["email"] == "jane@acme.com"
        assert state.event_entry["captured"]["contact"]["phone"] == "555-1234"

    def test_captures_time_fields(self):
        """Start and end time should be captured."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult(
            start_time="14:00",
            end_time="18:00",
        )

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is True
        assert "start_time" in result.fields
        assert "end_time" in result.fields
        assert state.event_entry["captured"]["start_time"] == "14:00"
        assert state.event_entry["captured"]["end_time"] == "18:00"

    def test_no_duplicate_capture_same_turn(self):
        """Should not capture twice in same turn."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult(date="2026-05-15")

        # First capture
        result1 = capture_fields_anytime(state, unified, current_step=5)
        assert result1.captured is True

        # Second capture same turn
        result2 = capture_fields_anytime(state, unified, current_step=5)
        assert result2.captured is False
        assert result2.source == "already_captured"

    def test_site_visit_date_not_captured_as_event_date(self):
        """Site visit date should NOT overwrite event date."""
        state = MockWorkflowState({"current_step": 7})
        unified = MockUnifiedDetectionResult(
            site_visit_date="2026-05-10",  # Site visit date
            date=None,  # No event date
        )

        result = capture_fields_anytime(state, unified, current_step=7)

        # Should not capture because date is None and site_visit_date is set
        assert "date" not in result.fields

    def test_deferred_intent_tracking_before_step(self):
        """Should add deferred intent when captured before relevant step."""
        state = MockWorkflowState({"current_step": 1})
        unified = MockUnifiedDetectionResult(
            contact_name="John Smith",
        )

        result = capture_fields_anytime(state, unified, current_step=1)

        assert result.captured is True
        # Contact is step 4, so at step 1 it should be deferred
        assert "contact_update" in state.event_entry["deferred_intents"]

    def test_no_deferred_intent_at_correct_step(self):
        """Should NOT add deferred intent when captured at or after relevant step."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult(
            contact_name="John Smith",
        )

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is True
        # Contact is step 4, at step 5 no deferred intent needed
        assert "contact_update" not in state.event_entry.get("deferred_intents", [])

    def test_empty_fields_returns_no_fields(self):
        """When unified result has no extractable fields, return no_fields."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult()  # All None

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is False
        assert result.source == "no_fields"

    def test_captures_multiple_fields_together(self):
        """Should capture multiple fields in one call."""
        state = MockWorkflowState({"current_step": 5})
        unified = MockUnifiedDetectionResult(
            date="2026-05-15",
            start_time="14:00",
            room_preference="Saal B",
            contact_email="test@example.com",
        )

        result = capture_fields_anytime(state, unified, current_step=5)

        assert result.captured is True
        assert len(result.fields) == 4
        assert "date" in result.fields
        assert "start_time" in result.fields
        assert "preferred_room" in result.fields
        assert "contact.email" in result.fields


class TestSetNested:
    """Test the _set_nested helper function."""

    def test_single_level(self):
        container = {}
        _set_nested(container, ("key",), "value")
        assert container == {"key": "value"}

    def test_nested_two_levels(self):
        container = {}
        _set_nested(container, ("a", "b"), "value")
        assert container == {"a": {"b": "value"}}

    def test_nested_three_levels(self):
        container = {}
        _set_nested(container, ("a", "b", "c"), "value")
        assert container == {"a": {"b": {"c": "value"}}}

    def test_preserves_existing(self):
        container = {"a": {"x": 1}}
        _set_nested(container, ("a", "y"), 2)
        assert container == {"a": {"x": 1, "y": 2}}
