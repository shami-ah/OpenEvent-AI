"""
Q&A Requirements and Capture Tests

Tests for:
1. qna_requirements preservation in extraction (Fix 2)
2. Sentence-level parsing for workflow vs Q&A context (Fix 3)
3. capture_workflow_requirements integration (Fix 3b)

Key rule:
- Statement sentences → PERSIST to event_entry["requirements"]
- Question sentences → DON'T persist (use qna_requirements for Q&A only)
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from typing import Any, Dict

from workflows.common.capture import (
    split_statement_vs_question,
    capture_workflow_requirements,
)
from workflows.qna.extraction import _normalize_qna_extraction
from workflows.qna.router import get_qna_requirements


# ==============================================================================
# Fix 2: qna_requirements Preservation Tests
# ==============================================================================


class TestQnaRequirementsPreservation:
    """Tests that qna_requirements extracted by LLM are preserved, not dropped."""

    def test_qna_requirements_preserved_in_normalized_extraction(self):
        """qna_requirements should be included in normalized output."""
        raw = {
            "msg_type": "event",
            "qna_intent": "select_dependent",
            "qna_subtype": "room_by_feature",
            "q_values": {"room": "Room A"},
            "qna_requirements": {
                "attendees": 40,
                "dietary": ["vegetarian"],
                "features": ["projector"],
                "layout": "u-shape",
            },
        }

        normalized = _normalize_qna_extraction(raw)

        assert "qna_requirements" in normalized
        assert normalized["qna_requirements"]["attendees"] == 40
        assert normalized["qna_requirements"]["dietary"] == ["vegetarian"]
        assert normalized["qna_requirements"]["features"] == ["projector"]
        assert normalized["qna_requirements"]["layout"] == "u-shape"

    def test_qna_requirements_none_when_not_present(self):
        """qna_requirements should be None if not in raw extraction."""
        raw = {
            "msg_type": "event",
            "qna_intent": "select_static",
            "qna_subtype": "general",
            "q_values": {},
        }

        normalized = _normalize_qna_extraction(raw)

        assert "qna_requirements" in normalized
        assert normalized["qna_requirements"] is None

    def test_get_qna_requirements_accessor(self):
        """Generic accessor should return qna_requirements dict."""
        extraction = {
            "qna_requirements": {
                "attendees": 50,
                "layout": "classroom",
            }
        }

        qna_req = get_qna_requirements(extraction)

        assert qna_req["attendees"] == 50
        assert qna_req["layout"] == "classroom"

    def test_get_qna_requirements_empty_when_none(self):
        """Generic accessor should return empty dict when qna_requirements is None."""
        extraction = {"qna_requirements": None}

        qna_req = get_qna_requirements(extraction)

        assert qna_req == {}

    def test_get_qna_requirements_handles_missing_extraction(self):
        """Generic accessor should handle None extraction gracefully."""
        qna_req = get_qna_requirements(None)
        assert qna_req == {}


# ==============================================================================
# Fix 3: Sentence-Level Parsing Tests
# ==============================================================================


class TestSentenceLevelParsing:
    """Tests for split_statement_vs_question function."""

    def test_pure_statement(self):
        """Pure statement should go to statements part."""
        text = "We'll have 50 people."
        statements, questions = split_statement_vs_question(text)

        assert "50 people" in statements
        assert questions == ""

    def test_pure_question(self):
        """Pure question should go to questions part."""
        text = "What rooms would work for 40 guests?"
        statements, questions = split_statement_vs_question(text)

        assert statements == ""
        assert "rooms" in questions

    def test_statement_plus_question(self):
        """Mixed text should be split correctly."""
        text = "We'll have 50 people. What rooms would work?"
        statements, questions = split_statement_vs_question(text)

        assert "50 people" in statements
        assert "rooms" in questions

    def test_but_what_about_pattern(self):
        """'but what about' should split at 'but'."""
        text = "We have 50 people but what about 70?"
        statements, questions = split_statement_vs_question(text)

        assert "50 people" in statements
        assert "70" in questions or "what about 70" in questions

    def test_question_word_starters(self):
        """Sentences starting with question words are questions."""
        test_cases = [
            ("What time?", "", "What time?"),
            ("Which room?", "", "Which room?"),
            ("How many?", "", "How many?"),
            ("Would that work?", "", "Would that work?"),
            ("Could you check?", "", "Could you check?"),
            ("Can we book?", "", "Can we book?"),
            ("Is it available?", "", "Is it available?"),
            ("Are there options?", "", "Are there options?"),
            ("Do you have?", "", "Do you have?"),
            ("Does it include?", "", "Does it include?"),
            ("Will it fit?", "", "Will it fit?"),
        ]
        for text, expected_statements, expected_in_questions in test_cases:
            statements, questions = split_statement_vs_question(text)
            assert expected_in_questions in questions, f"Failed for: {text}"

    def test_multiple_sentences(self):
        """Multiple sentences should be categorized correctly."""
        text = "We need seating for 30. The event is next Friday. What options are there? Is catering available?"
        statements, questions = split_statement_vs_question(text)

        assert "30" in statements
        assert "Friday" in statements
        assert "options" in questions
        assert "catering" in questions

    def test_empty_text(self):
        """Empty text should return empty strings."""
        statements, questions = split_statement_vs_question("")
        assert statements == ""
        assert questions == ""

    def test_whitespace_only(self):
        """Whitespace-only text should return empty strings."""
        statements, questions = split_statement_vs_question("   ")
        assert statements == ""
        assert questions == ""


# ==============================================================================
# Fix 3b: capture_workflow_requirements Integration Tests
# ==============================================================================


class TestCaptureWorkflowRequirements:
    """Tests for capture_workflow_requirements function."""

    def _make_state(self, event_entry: Dict[str, Any]) -> SimpleNamespace:
        """Create a minimal state for testing."""
        return SimpleNamespace(
            event_entry=event_entry,
            user_info={},
            extras={},
            telemetry=SimpleNamespace(),
        )

    def test_capture_participants_from_statement(self):
        """Participants mentioned in statement should be captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"participants": 50}

        # Text with number in statement part
        text = "We'll have 50 people."

        captured = capture_workflow_requirements(state, text, user_info)

        assert captured.get("number_of_participants") == 50
        assert event_entry["requirements"]["number_of_participants"] == 50

    def test_no_capture_participants_from_question(self):
        """Participants mentioned only in question should NOT be captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"participants": 70}

        # Text with number only in question part
        text = "What about 70 people?"

        captured = capture_workflow_requirements(state, text, user_info)

        # 70 appears in question, not statement, so should NOT be captured
        assert captured.get("number_of_participants") is None
        assert "number_of_participants" not in event_entry["requirements"]

    def test_capture_layout_from_statement(self):
        """Layout mentioned in statement should be captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"layout": "U-shape"}

        text = "We need U-shape seating."

        captured = capture_workflow_requirements(state, text, user_info)

        assert captured.get("seating_layout") == "U-shape"
        assert event_entry["requirements"]["seating_layout"] == "U-shape"

    def test_mixed_statement_question_captures_only_statement(self):
        """Only values from statement part should be captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"participants": 50}  # 50 is in statement

        text = "We have 50 people. Would rooms work for 70?"

        captured = capture_workflow_requirements(state, text, user_info)

        # 50 is in statement → captured
        assert captured.get("number_of_participants") == 50
        # 70 is only in question → not captured (user_info doesn't have 70)

    def test_empty_statement_no_capture(self):
        """Pure question should not capture anything."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"participants": 40}

        text = "What rooms work for 40 people?"

        captured = capture_workflow_requirements(state, text, user_info)

        # No statement part → nothing captured
        assert captured == {}

    def test_persist_flag_set_when_captured(self):
        """persist flag should be set when requirements are captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {"participants": 30}

        text = "We'll have 30 guests."

        capture_workflow_requirements(state, text, user_info)

        assert state.extras.get("persist") is True

    def test_no_persist_flag_when_nothing_captured(self):
        """persist flag should not be set when nothing captured."""
        event_entry = {"requirements": {}}
        state = self._make_state(event_entry)
        state.telemetry = {}
        user_info = {}

        text = "Just checking availability."

        capture_workflow_requirements(state, text, user_info)

        assert state.extras.get("persist") is not True

    def test_no_event_entry_returns_empty(self):
        """Should return empty dict if no event_entry."""
        state = self._make_state(None)
        state.telemetry = {}
        user_info = {"participants": 50}

        captured = capture_workflow_requirements(state, "We have 50 people.", user_info)

        assert captured == {}


# ==============================================================================
# Integration Tests
# ==============================================================================


class TestQnaVsWorkflowContextIntegration:
    """Integration tests ensuring Q&A vs workflow context rule works correctly."""

    def test_scenario_statement_then_question(self):
        """
        'We'll have 50 people. What rooms work?'
        - 50 persisted from statement
        - Q&A uses stored 50
        """
        text = "We'll have 50 people. What rooms work?"
        statements, questions = split_statement_vs_question(text)

        # Statement part has the 50
        assert "50" in statements
        # Question part has the question
        assert "rooms" in questions

    def test_scenario_mixed_with_different_numbers(self):
        """
        'We have 50 people but what about 70?'
        - 50 persisted from statement
        - 70 used for Q&A only (not persisted)
        """
        text = "We have 50 people but what about 70?"
        statements, questions = split_statement_vs_question(text)

        # 50 should be in statement
        assert "50" in statements
        # 70 should be in question
        assert "70" in questions

    def test_scenario_pure_qna_no_persist(self):
        """
        'Would rooms work for 40?'
        - Nothing persisted (Q&A only)
        """
        text = "Would rooms work for 40?"
        statements, questions = split_statement_vs_question(text)

        # No statements
        assert statements == ""
        # Question has everything
        assert "40" in questions
