"""Regression test: Step preservation during billing flow.

Bug: After offer acceptance and billing address capture, current_step was
incorrectly set to 3 instead of 5, causing deposit payment to fail.

Root cause: evaluate_pre_route_guards() was forcing step without checking
for billing flow state.

Fix: Added billing flow bypass in pre_route.py (Dec 2025).
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflows.common.types import WorkflowState, IncomingMessage
from workflows.runtime.pre_route import evaluate_pre_route_guards


def _make_state(thread_id: str, msg: str) -> WorkflowState:
    """Create a minimal WorkflowState for testing."""
    message = IncomingMessage(
        msg_id=None,
        from_name="Test",
        from_email="test@example.com",
        subject="Re: Booking",
        body=msg,
        ts=None,
    )
    return WorkflowState(
        message=message,
        db_path=Path("/tmp/test.json"),
        db={},
        thread_id=thread_id,
    )


class TestBillingStepPreservation:
    """Verify step remains at 5 during billing flow."""

    def test_billing_flow_bypasses_guard_forcing(self):
        """When in billing flow, guards should NOT force step to 3."""
        # Setup: Event is in billing flow (offer accepted, awaiting billing)
        state = _make_state(
            "test-billing-step",
            "Billing: Test Corp, 123 Main St, 8000 Zurich",
        )
        state.event_entry = {
            "event_id": "evt_test_billing",
            "current_step": 5,  # Correctly at step 5
            "offer_accepted": True,
            "billing_requirements": {
                "awaiting_billing_for_accept": True,
            },
            "requirements_hash": "hash123",
        }
        state.extras = {}

        # Mock the guard evaluation to return a forced_step of 3
        # (this simulates what was happening before the fix)
        mock_guard_snapshot = MagicMock()
        mock_guard_snapshot.deposit_bypass = False
        mock_guard_snapshot.forced_step = 3  # Guard wants to force step 3
        mock_guard_snapshot.requirements_hash_changed = False
        mock_guard_snapshot.step2_required = False
        mock_guard_snapshot.candidate_dates = []

        with patch(
            "workflows.runtime.pre_route.evaluate_guards",
            return_value=mock_guard_snapshot,
        ):
            # Act: Evaluate guards
            evaluate_pre_route_guards(state)

        # Assert: Step should still be 5 (billing flow bypass should have prevented forcing)
        assert state.event_entry["current_step"] == 5, (
            "Step should remain at 5 during billing flow, "
            "but guard forced it to a different value"
        )

    def test_normal_flow_allows_guard_forcing(self):
        """When NOT in billing flow, guards CAN force step changes."""
        # Setup: Event is NOT in billing flow
        state = _make_state(
            "test-normal-step",
            "Can we change the date?",
        )
        state.event_entry = {
            "event_id": "evt_test_normal",
            "current_step": 4,
            "offer_accepted": False,  # Not accepted yet
            "requirements_hash": "hash123",
        }
        state.extras = {}

        # Mock the guard evaluation to return a forced_step of 3
        mock_guard_snapshot = MagicMock()
        mock_guard_snapshot.deposit_bypass = False
        mock_guard_snapshot.forced_step = 3  # Guard wants to force step 3
        mock_guard_snapshot.requirements_hash_changed = False
        mock_guard_snapshot.step2_required = False
        mock_guard_snapshot.candidate_dates = []

        with patch(
            "workflows.runtime.pre_route.evaluate_guards",
            return_value=mock_guard_snapshot,
        ):
            # Act: Evaluate guards
            evaluate_pre_route_guards(state)

        # Assert: Step should be forced to 3 (normal flow allows guard forcing)
        assert state.event_entry["current_step"] == 3, (
            "Step should be forced to 3 in normal flow"
        )

    def test_billing_flow_without_awaiting_flag_allows_forcing(self):
        """When offer accepted but awaiting_billing_for_accept is False, allow forcing."""
        # Setup: Offer accepted but billing already captured
        state = _make_state(
            "test-billing-done",
            "Can we change the date?",
        )
        state.event_entry = {
            "event_id": "evt_test_billing_done",
            "current_step": 5,
            "offer_accepted": True,
            "billing_requirements": {
                "awaiting_billing_for_accept": False,  # Billing already captured
            },
            "requirements_hash": "hash123",
        }
        state.extras = {}

        # Mock the guard evaluation to return a forced_step of 3
        mock_guard_snapshot = MagicMock()
        mock_guard_snapshot.deposit_bypass = False
        mock_guard_snapshot.forced_step = 3
        mock_guard_snapshot.requirements_hash_changed = False
        mock_guard_snapshot.step2_required = False
        mock_guard_snapshot.candidate_dates = []

        with patch(
            "workflows.runtime.pre_route.evaluate_guards",
            return_value=mock_guard_snapshot,
        ):
            # Act: Evaluate guards
            evaluate_pre_route_guards(state)

        # Assert: Step can be forced since billing flow is complete
        assert state.event_entry["current_step"] == 3, (
            "Step should be forceable when billing flow is complete"
        )
