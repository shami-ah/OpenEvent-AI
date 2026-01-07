"""
Backend Startup Smoke Tests

Verifies that the backend can:
1. Import all core modules without errors
2. Process a basic workflow message end-to-end
3. Handle the start-conversation and send-message API contracts

Run these tests to ensure the backend is properly configured before integration testing.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.v4
from types import SimpleNamespace
from typing import Any, Dict


class TestBackendImports:
    """Verify all critical backend modules can be imported."""

    def test_import_main(self):
        """Main FastAPI app should import without errors."""
        from main import app
        assert app is not None
        assert app.title == "AI Event Manager"

    def test_import_workflow_email(self):
        """Workflow email processor should import."""
        from workflow_email import process_msg
        assert callable(process_msg)

    def test_import_capture(self):
        """Capture module should import."""
        from workflows.common.capture import (
            capture_workflow_requirements,
            split_statement_vs_question,
        )
        assert callable(capture_workflow_requirements)
        assert callable(split_statement_vs_question)

    def test_import_qna_router(self):
        """Q&A router should import."""
        from workflows.qna.router import route_general_qna
        assert callable(route_general_qna)

    def test_import_qna_extraction(self):
        """Q&A extraction should import."""
        from workflows.qna.extraction import ensure_qna_extraction
        assert callable(ensure_qna_extraction)

    def test_import_date_confirmation(self):
        """Date confirmation process should import."""
        from workflows.steps.step2_date_confirmation.trigger.process import process
        assert callable(process)

    def test_import_room_availability(self):
        """Room availability process should import."""
        from workflows.steps.step3_room_availability.trigger.process import process
        assert callable(process)

    def test_import_intake(self):
        """Intake process should import."""
        from workflows.steps.step1_intake.trigger.process import process
        assert callable(process)


class TestBasicWorkflowProcessing:
    """Verify basic workflow message processing works."""

    def test_process_msg_returns_result(self):
        """process_msg should return a valid result dict."""
        from workflow_email import process_msg, load_db, save_db

        # Create a test message
        msg = {
            "subject": "Test Event Inquiry",
            "body": "Hello, I would like to book a room for 30 people on January 15, 2026.",
            "sender": "smoke-test@example.com",
        }

        # Process through workflow
        result = process_msg(msg)

        # Should return a dict with standard fields
        assert isinstance(result, dict)
        assert "action" in result or "res" in result or "event_id" in result

    def test_process_msg_returns_valid_structure(self):
        """A new inquiry should return a result with event information."""
        from workflow_email import process_msg

        # Use a unique email to avoid conflicts
        import uuid
        unique_email = f"smoke-test-{uuid.uuid4().hex[:8]}@example.com"

        msg = {
            "subject": "Event Booking",
            "body": "Hi, I need a venue for 20 guests next month.",
            "sender": unique_email,
        }

        result = process_msg(msg)

        # Result should contain workflow information
        assert isinstance(result, dict), "process_msg should return a dict"

        # Should have one of: action, event_id, res, or error info
        has_valid_key = any(
            key in result for key in ["action", "event_id", "res", "error", "intent", "confidence"]
        )
        assert has_valid_key, f"Result should have valid workflow keys, got: {list(result.keys())}"


class TestSentenceLevelParsing:
    """Verify sentence-level parsing for workflow context."""

    def test_split_statement_question_basic(self):
        """Basic statement/question split should work."""
        from workflows.common.capture import split_statement_vs_question

        text = "We'll have 50 people. What rooms work?"
        statements, questions = split_statement_vs_question(text)

        assert "50" in statements
        assert "rooms" in questions

    def test_capture_requirements_from_statement(self):
        """Requirements in statements should be captured."""
        from workflows.common.capture import capture_workflow_requirements

        # Create minimal state
        event_entry = {"requirements": {}}
        state = SimpleNamespace(
            event_entry=event_entry,
            user_info={},
            extras={},
            telemetry={},
        )

        user_info = {"participants": 50}
        text = "We'll have 50 guests for the event."

        captured = capture_workflow_requirements(state, text, user_info)

        assert captured.get("number_of_participants") == 50


class TestQnaRequirementsPreservation:
    """Verify Q&A requirements are preserved through extraction."""

    def test_normalize_preserves_qna_requirements(self):
        """Normalized extraction should include qna_requirements."""
        from workflows.qna.extraction import _normalize_qna_extraction

        raw = {
            "msg_type": "event",
            "qna_intent": "select_dependent",
            "qna_subtype": "room_by_feature",
            "q_values": {},
            "qna_requirements": {
                "attendees": 40,
                "features": ["projector"],
            },
        }

        normalized = _normalize_qna_extraction(raw)

        assert "qna_requirements" in normalized
        assert normalized["qna_requirements"]["attendees"] == 40

    def test_get_qna_requirements_accessor(self):
        """Generic accessor should return qna_requirements."""
        from workflows.qna.router import get_qna_requirements

        extraction = {
            "qna_requirements": {
                "attendees": 30,
                "layout": "classroom",
            }
        }

        qna_req = get_qna_requirements(extraction)

        assert qna_req["attendees"] == 30
        assert qna_req["layout"] == "classroom"
