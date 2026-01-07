"""
Sequential Workflow Detection Tests (DET_SEQ_*)

Tests the sequential workflow detection logic that distinguishes between:
- Natural workflow continuation (confirm step N + ask about step N+1)
- General Q&A (asking about a step without being at the prerequisite step)

This prevents messages like "Confirm May 8 and show rooms" from being
classified as general Q&A when they're simply following the natural
workflow order.

References:
- TEAM_GUIDE.md: Sequential workflow vs general Q&A distinction
"""

from __future__ import annotations

import pytest

from workflows.nlu import detect_sequential_workflow_request

pytestmark = pytest.mark.v4


# ==============================================================================
# STEP 2 → STEP 3 (Date Confirmation → Room Availability)
# ==============================================================================


class TestStep2ToStep3Sequential:
    """Test detection of date confirmation + room inquiry as sequential workflow."""

    @pytest.mark.parametrize(
        "message,expected_sequential",
        [
            # Clear sequential patterns (should be detected as sequential)
            ("Please confirm May 8 and show me available rooms", True),
            ("Confirm the 8th and recommend a suitable room", True),
            ("Yes, let's book May 8. What rooms do you have?", True),
            ("That date works. Show me room options", True),
            ("Let's proceed with May 8, 2026. Which rooms are available?", True),
            ("We'll take the 8th. What space do you have?", True),
            ("Book for May 8 and show available venues", True),
            ("Go ahead with May 8. Room availability please", True),

            # Pure date confirmation (no room inquiry - NOT sequential)
            ("Please confirm May 8", False),
            ("Yes, let's book that date", False),
            ("Proceed with May 8, 2026", False),
            ("That date works for us", False),

            # Pure room inquiry (no date action - NOT sequential)
            ("What rooms do you have?", False),
            ("Show me available spaces", False),
            ("Which room would you recommend?", False),
            ("Room availability please", False),

            # Unrelated messages
            ("Thank you for your help", False),
            ("Can you send me the menu?", False),
        ],
    )
    def test_step2_sequential_detection(self, message: str, expected_sequential: bool):
        """Test that step 2 → step 3 sequential patterns are detected correctly."""
        result = detect_sequential_workflow_request(message, current_step=2)

        assert result["is_sequential"] == expected_sequential, (
            f"Expected is_sequential={expected_sequential} for: '{message}'\n"
            f"Got: {result}"
        )

        if expected_sequential:
            assert result["asks_next_step"] == 3, (
                f"Expected asks_next_step=3 for: '{message}'\n"
                f"Got: {result}"
            )
            assert result["has_current_step_action"] is True


# ==============================================================================
# STEP 3 → STEP 4 (Room Availability → Offer)
# ==============================================================================


class TestStep3ToStep4Sequential:
    """Test detection of room selection + catering/offer inquiry as sequential workflow."""

    @pytest.mark.parametrize(
        "message,expected_sequential",
        [
            # Clear sequential patterns (should be detected as sequential)
            ("Room A looks good, what catering options do you have?", True),
            ("We'll take Room B. Show me the menu please", True),
            ("Go with Room A. What are the prices?", True),
            ("Choose Room C. How much would that cost?", True),
            ("Proceed with Room A. Can you send the offer?", True),
            ("Room A is fine. What packages do you offer?", True),
            ("Select Room B, and show catering choices", True),

            # Pure room selection (no catering inquiry - NOT sequential)
            ("Room A looks good", False),
            ("We'll take Room B", False),
            ("Proceed with Room A", False),
            ("Choose Room C please", False),

            # Pure catering inquiry (no room action - NOT sequential)
            ("What catering options do you have?", False),
            ("Show me the menu please", False),
            ("What are the prices?", False),
            ("How much would that cost?", False),

            # Unrelated messages
            ("Can we change the date?", False),
            ("Thank you for the information", False),
        ],
    )
    def test_step3_sequential_detection(self, message: str, expected_sequential: bool):
        """Test that step 3 → step 4 sequential patterns are detected correctly."""
        result = detect_sequential_workflow_request(message, current_step=3)

        assert result["is_sequential"] == expected_sequential, (
            f"Expected is_sequential={expected_sequential} for: '{message}'\n"
            f"Got: {result}"
        )

        if expected_sequential:
            assert result["asks_next_step"] == 4, (
                f"Expected asks_next_step=4 for: '{message}'\n"
                f"Got: {result}"
            )
            assert result["has_current_step_action"] is True


# ==============================================================================
# STEP 4 → STEP 5/7 (Offer → Negotiation/Confirmation)
# ==============================================================================


class TestStep4ToStep5Or7Sequential:
    """Test detection of offer acceptance + next steps inquiry as sequential workflow."""

    @pytest.mark.parametrize(
        "message,expected_sequential,expected_next_step",
        [
            # Accept + site visit (step 7)
            ("Accept the offer. When can we do a site visit?", True, 7),
            ("We approve the offer. Can we visit the venue?", True, 7),
            ("Go ahead with the offer. Schedule a tour please", True, 7),

            # Accept + deposit/contract (step 5)
            ("Accept the offer. What's the deposit?", True, 5),
            ("Approve the offer, send the contract", True, 5),
            ("Finalize the offer. What are the next steps?", True, 5),
            ("Offer looks good. What about payment?", True, 5),

            # Pure offer acceptance (no next step inquiry - NOT sequential)
            ("Accept the offer", False, None),
            ("We approve the quote", False, None),
            ("Go ahead with the offer", False, None),

            # Pure next step inquiry (no offer action - NOT sequential)
            ("When can we do a site visit?", False, None),
            ("What's the deposit amount?", False, None),
            # Note: "Send the contract" is a direct action request, not sequential workflow
            # It would be handled by the offer step directly, not as a sequential pattern

            # Unrelated messages
            ("Can we change the room?", False, None),
            ("Add more catering options", False, None),
        ],
    )
    def test_step4_sequential_detection(
        self, message: str, expected_sequential: bool, expected_next_step
    ):
        """Test that step 4 → step 5/7 sequential patterns are detected correctly."""
        result = detect_sequential_workflow_request(message, current_step=4)

        assert result["is_sequential"] == expected_sequential, (
            f"Expected is_sequential={expected_sequential} for: '{message}'\n"
            f"Got: {result}"
        )

        if expected_sequential:
            assert result["asks_next_step"] == expected_next_step, (
                f"Expected asks_next_step={expected_next_step} for: '{message}'\n"
                f"Got: {result}"
            )
            assert result["has_current_step_action"] is True


# ==============================================================================
# EDGE CASES
# ==============================================================================


class TestSequentialEdgeCases:
    """Test edge cases for sequential workflow detection."""

    def test_empty_message(self):
        """Empty message should not be detected as sequential."""
        result = detect_sequential_workflow_request("", current_step=2)
        assert result["is_sequential"] is False
        assert result["has_current_step_action"] is False
        assert result["asks_next_step"] is None

    def test_whitespace_only_message(self):
        """Whitespace-only message should not be detected as sequential."""
        result = detect_sequential_workflow_request("   \n\t  ", current_step=2)
        assert result["is_sequential"] is False

    def test_case_insensitivity(self):
        """Detection should be case-insensitive."""
        result = detect_sequential_workflow_request(
            "CONFIRM MAY 8 AND SHOW ROOMS", current_step=2
        )
        assert result["is_sequential"] is True

    def test_german_style_date(self):
        """Should handle German-style date formats."""
        result = detect_sequential_workflow_request(
            "Please confirm 08.05.2026 and show available rooms", current_step=2
        )
        assert result["has_current_step_action"] is True

    def test_conditional_lookahead(self):
        """Conditional lookahead should still be detected."""
        result = detect_sequential_workflow_request(
            "If May 8 works, please show available rooms", current_step=2
        )
        # This tests that we detect room mention even with conditional phrasing
        assert result["asks_next_step"] == 3

    def test_multiple_step_mentions(self):
        """Message mentioning multiple future steps should detect the immediate next."""
        # At step 2, asking about rooms AND catering - should detect room (step 3) first
        result = detect_sequential_workflow_request(
            "Confirm May 8. Show rooms and also catering options", current_step=2
        )
        # Should detect step 3 (rooms) as the immediate next step
        assert result["asks_next_step"] == 3

    def test_unsupported_step(self):
        """Steps without defined patterns should return no sequential."""
        result = detect_sequential_workflow_request(
            "Some message about anything", current_step=99
        )
        assert result["is_sequential"] is False
        assert result["has_current_step_action"] is False


# ==============================================================================
# NEGATIVE TESTS - Ensure Q&A is NOT suppressed incorrectly
# ==============================================================================


class TestNotSequentialPreservesQna:
    """Ensure that pure Q&A messages are NOT marked as sequential."""

    @pytest.mark.parametrize(
        "message,current_step",
        [
            # Pure questions at step 2 (should remain Q&A)
            ("What rooms do you have for 30 people?", 2),
            ("Can you tell me about your catering options?", 2),
            ("What are your prices?", 2),

            # Out-of-order questions (should remain Q&A)
            ("Can I see the site before confirming a date?", 2),  # Site visit at step 2
            ("What's the deposit policy?", 2),  # Deposit at step 2

            # Informational questions at any step
            ("Do you have parking?", 2),
            ("What time do you close?", 3),
            ("Is there a minimum booking?", 4),
        ],
    )
    def test_pure_qna_not_sequential(self, message: str, current_step: int):
        """Pure Q&A messages should NOT be detected as sequential workflow."""
        result = detect_sequential_workflow_request(message, current_step)

        # Pure questions without current step action should NOT be sequential
        # (even if they ask about the next step)
        assert result["is_sequential"] is False, (
            f"Pure Q&A should NOT be sequential: '{message}'\n"
            f"Got: {result}"
        )
