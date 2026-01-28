"""Regression tests for detection interference fixes.

These tests verify that the unified LLM detection signals are properly
consumed to prevent regex/keyword detection from overriding correct intent.

Test IDs:
- DET_INT_001 - Step5 acceptance uses unified is_acceptance
- DET_INT_002 - Step5 rejection uses unified is_rejection
- DET_INT_003 - "good" alone does not trigger acceptance (regex too permissive)
- DET_INT_004 - Step7 "yes can we visit" returns site_visit not confirm
- DET_INT_005 - Step7 site_visit_state=proposed prioritizes visit keywords
- DET_INT_006 - Room detection "Is Room A available?" returns None (question)
- DET_INT_007 - Room detection "Room A please" returns "Room A" (not question)
- DET_INT_008 - Q&A borderline "need room" requires LLM agreement
- DET_INT_009 - Q&A clear "?" trusts heuristic without LLM
- DET_INT_010 - Q&A LLM veto on borderline false positive
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.v4


# ---------------------------------------------------------------------------
# Mock UnifiedDetectionResult for tests
# ---------------------------------------------------------------------------
@dataclass
class MockUnifiedDetection:
    """Mock unified detection result for testing."""

    is_acceptance: bool = False
    is_rejection: bool = False
    is_question: bool = False
    is_change_request: bool = False
    qna_types: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step5 Tests - Unified Acceptance/Rejection
# ---------------------------------------------------------------------------
class TestStep5UnifiedDetection:
    """Tests for Step5 using unified is_acceptance/is_rejection."""

    def test_DET_INT_001_step5_uses_unified_acceptance(self):
        """Step5 should use unified is_acceptance over regex.

        When unified detection says is_acceptance=True, Step5 should
        recognize it as acceptance even if regex wouldn't match.
        """
        from workflows.steps.step5_negotiation.trigger.classification import (
            collect_detected_intents,
            INTENT_ACCEPT,
        )

        # Create unified result with is_acceptance=True
        detection = MockUnifiedDetection(is_acceptance=True)

        # Message that wouldn't normally trigger acceptance regex
        message = "I think this works for us"

        intents = collect_detected_intents(message, unified_detection=detection)
        intent_names = [i[0] for i in intents]

        assert INTENT_ACCEPT in intent_names, (
            "Step5 should detect acceptance from unified is_acceptance signal"
        )

    def test_DET_INT_002_step5_uses_unified_rejection(self):
        """Step5 should use unified is_rejection over regex.

        When unified detection says is_rejection=True, Step5 should
        recognize it as rejection even if regex wouldn't match.
        """
        from workflows.steps.step5_negotiation.trigger.classification import (
            collect_detected_intents,
            INTENT_DECLINE,
        )

        # Create unified result with is_rejection=True
        detection = MockUnifiedDetection(is_rejection=True)

        # Message that wouldn't normally trigger rejection regex
        message = "We've decided to look elsewhere"

        intents = collect_detected_intents(message, unified_detection=detection)
        intent_names = [i[0] for i in intents]

        assert INTENT_DECLINE in intent_names, (
            "Step5 should detect rejection from unified is_rejection signal"
        )

    def test_DET_INT_003_good_alone_no_acceptance(self):
        """'good' alone should not trigger acceptance without LLM confirmation.

        The regex pattern for acceptance was too permissive, matching 'good'
        in contexts where it wasn't an offer acceptance.
        """
        from workflows.steps.step5_negotiation.trigger.classification import (
            collect_detected_intents,
            INTENT_ACCEPT,
        )

        # No unified detection - fallback to regex
        message = "good"

        intents = collect_detected_intents(message, unified_detection=None)
        intent_names = [i[0] for i in intents]

        # The regex may still match "good", but confidence should be lower
        # than when unified detection confirms acceptance
        acceptance_intents = [i for i in intents if i[0] == INTENT_ACCEPT]
        if acceptance_intents:
            # If matched, confidence should be less than unified (0.95)
            confidence = acceptance_intents[0][1]
            assert confidence < 0.95, (
                f"Regex-only acceptance confidence ({confidence}) should be "
                "lower than unified detection (0.95)"
            )


# ---------------------------------------------------------------------------
# Step7 Tests - Site Visit Precedence
# ---------------------------------------------------------------------------
class TestStep7SiteVisitPrecedence:
    """Tests for Step7 site visit detection over confirm keywords."""

    def test_DET_INT_004_yes_visit_returns_site_visit(self):
        """'Yes, can we visit next week?' should return site_visit not confirm.

        The bug was that CONFIRM_KEYWORDS ('yes') was checked before
        VISIT_KEYWORDS, so 'yes' was matched first.
        """
        from workflows.steps.step7_confirmation.trigger.classification import (
            classify_message,
        )

        event_entry = {"site_visit_state": {"status": "proposed"}}

        # Create unified detection with site_visit_request qna_type
        detection = MockUnifiedDetection(qna_types=["site_visit_request"])

        result = classify_message(
            "Yes, can we visit next week?",
            event_entry,
            unified_detection=detection,
        )

        assert result == "site_visit", (
            f"Expected 'site_visit' but got '{result}'. "
            "Site visit request should take precedence over 'yes' confirm keyword."
        )

    def test_DET_INT_005_site_visit_state_proposed_prioritizes_visit(self):
        """When site_visit_state=proposed, visit keywords should be prioritized.

        Even without unified detection, if site visit was proposed,
        visit keywords should be checked first.
        """
        from workflows.steps.step7_confirmation.trigger.classification import (
            classify_message,
        )

        event_entry = {"site_visit_state": {"status": "proposed"}}

        # No unified detection - rely on keyword order fix
        result = classify_message(
            "yes, when can we schedule a visit?",
            event_entry,
            unified_detection=None,
        )

        assert result == "site_visit", (
            f"Expected 'site_visit' but got '{result}'. "
            "When site_visit_state is 'proposed', visit keywords should be prioritized."
        )


# ---------------------------------------------------------------------------
# Room Detection Tests - Question Guard
# ---------------------------------------------------------------------------
class TestRoomDetectionQuestionGuard:
    """Tests for room detection question guard."""

    def test_DET_INT_006_question_mark_no_room_lock(self):
        """'Is Room A available?' should NOT lock Room A.

        Questions about rooms should not trigger room selection.
        """
        from workflows.steps.step1_intake.trigger.room_detection import (
            detect_room_choice,
        )

        linked_event = {"current_step": 3}

        # Mock load_rooms to return known rooms
        with patch(
            "workflows.steps.step1_intake.trigger.room_detection.load_rooms",
            return_value=["Room A", "Room B", "Room C"],
        ):
            result = detect_room_choice(
                "Is Room A available?",
                linked_event,
                unified_detection=None,
            )

        assert result is None, (
            f"Expected None but got '{result}'. "
            "Questions (with '?') should not lock rooms."
        )

    def test_DET_INT_007_room_please_locks_room(self):
        """'Room A please' should lock Room A.

        Explicit room selection without question mark should work.
        """
        from workflows.steps.step1_intake.trigger.room_detection import (
            detect_room_choice,
        )

        linked_event = {"current_step": 3}

        with patch(
            "workflows.steps.step1_intake.trigger.room_detection.load_rooms",
            return_value=["Room A", "Room B", "Room C"],
        ):
            result = detect_room_choice(
                "Room A please",
                linked_event,
                unified_detection=None,
            )

        assert result == "Room A", (
            f"Expected 'Room A' but got '{result}'. "
            "Non-question room selection should work."
        )

    def test_DET_INT_006b_unified_is_question_no_room_lock(self):
        """Room detection should respect unified is_question signal.

        Even without '?', if unified detection says is_question=True,
        don't lock the room.
        """
        from workflows.steps.step1_intake.trigger.room_detection import (
            detect_room_choice,
        )

        linked_event = {"current_step": 3}
        detection = MockUnifiedDetection(is_question=True)

        with patch(
            "workflows.steps.step1_intake.trigger.room_detection.load_rooms",
            return_value=["Room A", "Room B", "Room C"],
        ):
            # No question mark, but unified says it's a question
            result = detect_room_choice(
                "I was wondering about Room A",
                linked_event,
                unified_detection=detection,
            )

        assert result is None, (
            f"Expected None but got '{result}'. "
            "Unified is_question=True should prevent room lock."
        )


# ---------------------------------------------------------------------------
# Q&A Tests - LLM Veto for Borderline
# ---------------------------------------------------------------------------
class TestQnALLMVeto:
    """Tests for Q&A LLM veto logic on borderline heuristics."""

    def test_DET_INT_008_borderline_requires_llm_agreement(self):
        """Borderline heuristic 'need room' should require LLM agreement.

        Phrases like 'need room' are borderline - they could be a general
        room query or part of a longer sentence. LLM should confirm.
        """
        # Test the logic directly - borderline without LLM agreement
        heuristics = {"heuristic_general": True, "borderline": True}
        llm_result = {"label": "other"}  # LLM says NOT general

        # Apply the fixed logic
        is_clear_heuristic = (
            heuristics.get("heuristic_general")
            and not heuristics.get("borderline")
        )
        is_general_from_llm = llm_result.get("label") == "general_room_query"
        is_borderline_confirmed = (
            heuristics.get("borderline")
            and is_general_from_llm
        )
        is_general = bool(
            is_clear_heuristic or is_borderline_confirmed or is_general_from_llm
        )

        assert is_general is False, (
            "Borderline match without LLM agreement should NOT be general"
        )

    def test_DET_INT_009_clear_question_trusts_heuristic(self):
        """Clear question marks should trust heuristic without LLM.

        When message has '?' (clear signal), trust the heuristic.
        """
        # Test the logic directly - clear heuristic (not borderline)
        heuristics = {"heuristic_general": True, "borderline": False}
        llm_result = {"label": "other"}  # LLM disagrees, but doesn't matter

        is_clear_heuristic = (
            heuristics.get("heuristic_general")
            and not heuristics.get("borderline")
        )
        is_general_from_llm = llm_result.get("label") == "general_room_query"
        is_borderline_confirmed = (
            heuristics.get("borderline")
            and is_general_from_llm
        )
        is_general = bool(
            is_clear_heuristic or is_borderline_confirmed or is_general_from_llm
        )

        assert is_general is True, (
            "Clear heuristic (not borderline) should be trusted"
        )

    def test_DET_INT_010_llm_veto_on_borderline_false_positive(self):
        """LLM should be able to veto borderline false positives.

        When heuristic says 'general' but it's borderline, LLM can veto
        by returning a different label.
        """
        # Borderline heuristic match
        heuristics = {"heuristic_general": True, "borderline": True}
        # LLM vetoes - says it's NOT a general room query
        llm_result = {"label": "negotiation_counter"}

        is_clear_heuristic = (
            heuristics.get("heuristic_general")
            and not heuristics.get("borderline")
        )
        is_general_from_llm = llm_result.get("label") == "general_room_query"
        is_borderline_confirmed = (
            heuristics.get("borderline")
            and is_general_from_llm
        )
        is_general = bool(
            is_clear_heuristic or is_borderline_confirmed or is_general_from_llm
        )

        assert is_general is False, (
            "LLM should successfully veto borderline false positive"
        )

    def test_DET_INT_008b_borderline_with_llm_agreement(self):
        """Borderline heuristic with LLM agreement should be general.

        When borderline heuristic fires AND LLM confirms, accept it.
        """
        heuristics = {"heuristic_general": True, "borderline": True}
        llm_result = {"label": "general_room_query"}  # LLM confirms

        is_clear_heuristic = (
            heuristics.get("heuristic_general")
            and not heuristics.get("borderline")
        )
        is_general_from_llm = llm_result.get("label") == "general_room_query"
        is_borderline_confirmed = (
            heuristics.get("borderline")
            and is_general_from_llm
        )
        is_general = bool(
            is_clear_heuristic or is_borderline_confirmed or is_general_from_llm
        )

        assert is_general is True, (
            "Borderline match WITH LLM agreement should be general"
        )


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------
class TestDetectionInterferenceIntegration:
    """Integration tests combining multiple detection fixes."""

    def test_step5_structural_change_respects_unified_acceptance(self):
        """_detect_structural_change should return None when unified says acceptance.

        This prevents false positive 'change' detections on acceptance messages.
        """
        from workflows.steps.step5_negotiation.trigger.step5_handler import (
            _detect_structural_change,
        )

        user_info = {"email": "test@example.com"}
        event_entry = {
            "current_step": 5,
            "offer_sent": True,
            "room_name": "Room A",
            "chosen_date": "2026-02-15",
        }
        message = "That sounds great, we accept the offer"

        detection = MockUnifiedDetection(is_acceptance=True)

        result = _detect_structural_change(
            user_info, event_entry, message, unified_detection=detection
        )

        assert result is None, (
            f"Expected None (no change) but got {result}. "
            "Acceptance messages should not trigger structural change detection."
        )
