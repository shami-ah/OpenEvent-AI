"""
Regression tests for the Corrective Sandwich validation system.

These tests ensure that:
1. The corrective sandwich correctly identifies and fixes LLM output issues
2. Missing facts are inserted
3. Hallucinated facts are removed
4. Term protection works correctly
"""

from __future__ import annotations

import pytest

from backend.ux.verbalizer_payloads import RoomFact, MenuFact, RoomOfferFacts
from backend.ux.verbalizer_safety import (
    correct_output,
    verify_output,
    protect_terms,
    restore_terms,
    verify_term_preservation,
    build_facts_from_qna_payload,
    build_facts_from_workflow_state,
    ProtectedTerms,
)


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_facts() -> RoomOfferFacts:
    """Sample facts for testing."""
    return RoomOfferFacts(
        event_date="14.02.2026",
        event_date_iso="2026-02-14",
        participants_count=60,
        rooms=[
            RoomFact(
                name="Room A",
                status="available",
                capacity_max=80,
                features=["projector", "parking", "stage"],
            ),
            RoomFact(
                name="Room B",
                status="option",
                capacity_max=40,
                features=["whiteboard", "screen"],
            ),
        ],
        recommended_room="Room A",
        menus=[
            MenuFact(name="Apéro Package", price="CHF 45"),
            MenuFact(name="Business Lunch", price="CHF 65"),
        ],
        total_amount="CHF 500",
    )


@pytest.fixture
def sample_qna_payload() -> dict:
    """Sample QnA payload for testing."""
    return {
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "effective": {
            "D": {"value": "2026-02-14", "source": "Q", "meta": {}},
            "N": {"value": 60, "source": "Q", "meta": {}},
            "R": {"value": None, "source": "none", "meta": {}},
            "P": {"value": [], "source": "none", "meta": {}},
        },
        "db_results": {
            "rooms": [
                {
                    "room_id": "room_a",
                    "room_name": "Room A",
                    "capacity_max": 80,
                    "status": "available",
                    "features": ["projector", "parking"],
                },
            ],
            "dates": [],
            "products": [],
            "notes": [],
        },
    }


# -----------------------------------------------------------------------------
# Corrective Sandwich Tests
# -----------------------------------------------------------------------------


class TestCorrectiveInsertsMissingFacts:
    """Test that the corrective sandwich inserts missing facts."""

    def test_inserts_missing_date(self, sample_facts: RoomOfferFacts):
        """Missing date should be inserted."""
        llm_text = "Room A is available for your event."
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        assert was_corrected is True
        assert "14.02.2026" in corrected

    def test_inserts_missing_participant_count(self, sample_facts: RoomOfferFacts):
        """Missing participant count should be inserted."""
        llm_text = "Room A is available on 14.02.2026 for your guests."
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        # Should insert the count somewhere
        assert was_corrected is True
        assert "60" in corrected

    def test_no_correction_when_key_facts_present(self):
        """No correction needed when key facts are present."""
        # Use minimal facts - just date and one room
        simple_facts = RoomOfferFacts(
            event_date="14.02.2026",
            participants_count=60,
            rooms=[
                RoomFact(name="Room A", status="available", capacity_max=80, features=[]),
            ],
            recommended_room="Room A",
        )
        llm_text = "Great news! Room A is available on 14.02.2026 for your 60 guests."
        corrected, was_corrected = correct_output(simple_facts, llm_text)

        # The text already has all required facts
        assert was_corrected is False
        assert corrected == llm_text


class TestCorrectiveRemovesHallucinatedFacts:
    """Test that the corrective sandwich removes hallucinated facts."""

    def test_removes_invented_date(self, sample_facts: RoomOfferFacts):
        """Invented dates should be removed."""
        llm_text = "Room A is available on 21.12.2025 for your 60 guests."
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        assert was_corrected is True
        assert "21.12.2025" not in corrected
        # The correct date should be inserted
        assert "14.02.2026" in corrected

    def test_removes_invented_amount(self, sample_facts: RoomOfferFacts):
        """Invented currency amounts should be removed."""
        llm_text = "Room A is available on 14.02.2026 for 60 guests. Total: CHF 999."
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        assert was_corrected is True
        # CHF 999 should be removed/replaced
        assert "CHF 999" not in corrected or "[AMOUNT]" in corrected


class TestCorrectiveHandlesEmptyOutput:
    """Test that the corrective sandwich handles empty output."""

    def test_generates_minimal_response_for_empty(self, sample_facts: RoomOfferFacts):
        """Empty LLM output should generate minimal factual response."""
        llm_text = ""
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        assert was_corrected is True
        assert "14.02.2026" in corrected
        assert "60" in corrected or "guests" in corrected.lower()

    def test_generates_minimal_response_for_whitespace(self, sample_facts: RoomOfferFacts):
        """Whitespace-only output should generate minimal factual response."""
        llm_text = "   \n\t  "
        corrected, was_corrected = correct_output(sample_facts, llm_text)

        assert was_corrected is True
        assert len(corrected) > 10  # Should have real content


# -----------------------------------------------------------------------------
# Term Protection Tests
# -----------------------------------------------------------------------------


class TestTermProtection:
    """Test the term protection marker system."""

    def test_protect_and_restore_features(self, sample_facts: RoomOfferFacts):
        """Features should be protected and restored correctly."""
        text = "Room A has projector and parking available."
        protected_text, protected_terms = protect_terms(text, sample_facts)

        # Features should be replaced with markers
        assert "{{TERM_FEAT_" in protected_text
        assert "projector" not in protected_text
        assert "parking" not in protected_text

        # Restore should bring them back
        restored = restore_terms(protected_text, protected_terms)
        assert "projector" in restored
        assert "parking" in restored

    def test_protect_menu_names(self, sample_facts: RoomOfferFacts):
        """Menu names should be protected."""
        text = "We offer the Apéro Package and Business Lunch."
        protected_text, protected_terms = protect_terms(text, sample_facts)

        # Menu names should be replaced with markers
        assert "{{TERM_MENU_" in protected_text
        assert "Apéro Package" not in protected_text

        # Restore
        restored = restore_terms(protected_text, protected_terms)
        assert "Apéro Package" in restored
        assert "Business Lunch" in restored

    def test_protect_room_names(self, sample_facts: RoomOfferFacts):
        """Room names should be protected."""
        text = "Room A and Room B are both excellent choices."
        protected_text, protected_terms = protect_terms(text, sample_facts)

        # Room names should be replaced with markers
        assert "{{TERM_ROOM_" in protected_text

        # Restore
        restored = restore_terms(protected_text, protected_terms)
        assert "Room A" in restored
        assert "Room B" in restored

    def test_verify_term_preservation(self):
        """Verify term preservation should detect missing terms."""
        protected = ProtectedTerms()
        protected.reverse_map = {
            "projector": "{{TERM_FEAT_0}}",
            "parking": "{{TERM_FEAT_1}}",
        }

        # All terms present
        text_complete = "Room A has projector and parking."
        missing = verify_term_preservation(text_complete, protected)
        assert len(missing) == 0

        # Missing term
        text_missing = "Room A has projector."
        missing = verify_term_preservation(text_missing, protected)
        assert "parking" in missing


# -----------------------------------------------------------------------------
# Facts Extraction Tests
# -----------------------------------------------------------------------------


class TestBuildFactsFromQnAPayload:
    """Test building facts from QnA payloads."""

    def test_extracts_rooms(self, sample_qna_payload: dict):
        """Rooms should be extracted from QnA payload."""
        facts = build_facts_from_qna_payload(sample_qna_payload)

        assert len(facts.rooms) == 1
        assert facts.rooms[0].name == "Room A"
        assert facts.rooms[0].capacity_max == 80

    def test_extracts_date(self, sample_qna_payload: dict):
        """Date should be extracted from effective values."""
        facts = build_facts_from_qna_payload(sample_qna_payload)

        assert facts.event_date_iso == "2026-02-14"
        assert facts.event_date == "14.02.2026"

    def test_extracts_participants(self, sample_qna_payload: dict):
        """Participant count should be extracted."""
        facts = build_facts_from_qna_payload(sample_qna_payload)

        assert facts.participants_count == 60

    def test_handles_empty_payload(self):
        """Empty payload should return empty facts."""
        facts = build_facts_from_qna_payload({})

        assert facts.event_date == ""
        assert facts.participants_count is None
        assert len(facts.rooms) == 0


class TestBuildFactsFromWorkflowState:
    """Test building facts from workflow state."""

    def test_extracts_from_event_entry(self):
        """Facts should be extracted from event entry."""
        event_entry = {
            "chosen_date": "14.02.2026",
            "locked_room_id": "Room A",
            "requirements": {
                "number_of_participants": 60,
            },
        }
        facts = build_facts_from_workflow_state(event_entry)

        assert facts.event_date == "14.02.2026"
        assert facts.participants_count == 60
        assert len(facts.rooms) == 1
        assert facts.rooms[0].name == "Room A"

    def test_converts_iso_date(self):
        """ISO dates should be converted to DD.MM.YYYY."""
        event_entry = {
            "chosen_date": "2026-02-14",
            "requirements": {},
        }
        facts = build_facts_from_workflow_state(event_entry)

        assert facts.event_date == "14.02.2026"
        assert facts.event_date_iso == "2026-02-14"

    def test_handles_none_event_entry(self):
        """None event entry should return empty facts."""
        facts = build_facts_from_workflow_state(None)

        assert facts.event_date == ""


# -----------------------------------------------------------------------------
# Verification Tests
# -----------------------------------------------------------------------------


class TestVerifyOutput:
    """Test the output verification function."""

    def test_passes_when_facts_present(self):
        """Verification should pass when all facts are present."""
        # Use minimal facts to test basic verification
        simple_facts = RoomOfferFacts(
            event_date="14.02.2026",
            participants_count=60,
            rooms=[
                RoomFact(name="Room A", status="available", capacity_max=80, features=[]),
            ],
            recommended_room="Room A",
            total_amount="CHF 500",
        )
        llm_text = (
            "Great news! Room A is available on 14.02.2026 for your 60 guests. "
            "The total comes to CHF 500."
        )
        result = verify_output(simple_facts, llm_text)

        assert result.ok is True
        assert len(result.missing_facts) == 0
        assert len(result.invented_facts) == 0

    def test_fails_on_missing_date(self, sample_facts: RoomOfferFacts):
        """Verification should fail when date is missing."""
        llm_text = "Room A is available for your 60 guests."
        result = verify_output(sample_facts, llm_text)

        assert result.ok is False
        assert "dates" in result.missing_facts

    def test_detects_invented_date(self, sample_facts: RoomOfferFacts):
        """Verification should detect invented dates."""
        llm_text = "Room A is available on 21.12.2025 for 60 guests."
        result = verify_output(sample_facts, llm_text)

        assert result.ok is False
        assert "dates" in result.invented_facts
        assert "21.12.2025" in result.invented_facts["dates"]

    def test_fails_on_empty_output(self, sample_facts: RoomOfferFacts):
        """Verification should fail on empty output."""
        result = verify_output(sample_facts, "")

        assert result.ok is False
        assert result.reason == "empty_output"
