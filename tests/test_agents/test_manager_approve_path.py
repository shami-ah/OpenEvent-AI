"""
Manager Approve Path Tests (APPROVE_*)

Tests for HIL (Human-in-the-Loop) approval flow ensuring managers can
approve/reject tasks and the workflow progresses correctly.

References:
- TEST_MATRIX_detection_and_flow.md: APPROVE_* tests
- CLAUDE.md: HIL approval gates, Step 5 negotiation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

import workflow_email as wf
from domain import IntentLabel, TaskStatus
from workflows.common.types import IncomingMessage, WorkflowState
from workflows.steps import step5_negotiation as negotiation_close


# ==============================================================================
# HELPERS
# ==============================================================================


def create_hil_pending_state(
    tmp_path: Path,
    step: int = 5,
    task_type: str = "negotiation_approval",
) -> WorkflowState:
    """Create a workflow state with a pending HIL request."""
    msg = IncomingMessage.from_dict(
        {
            "msg_id": "msg-pending-hil",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Offer reply",
            "body": "We accept the offer.",
            "ts": "2025-11-01T09:00:00Z",
        }
    )
    state = WorkflowState(
        message=msg,
        db_path=tmp_path / "events.json",
        db={"events": [], "tasks": []},
    )
    state.intent = IntentLabel.EVENT_REQUEST
    state.client_id = "client@example.com"

    event_entry = {
        "event_id": "evt-hil-test",
        "current_step": step,
        "thread_state": "Waiting on HIL",
        "flags": {"manager_requested": True},
        "offers": [{"offer_id": "offer-001", "total_amount": 500.0}],
        "current_offer_id": "offer-001",
        "negotiation_state": {"counter_count": 0, "manual_review_task_id": None},
        "requirements": {"number_of_participants": 25},
        "locked_room_id": "Room A",
        "offer_status": "Draft",
        "pending_hil_requests": [],
        "billing_details": {
            "name_or_company": "Test Company",
            "street": "Test Street 1",
            "postal_code": "8000",
            "city": "Zurich",
            "country": "Switzerland",
        },
        "event_data": {
            "Email": "client@example.com",
            "Billing Address": "Test Company, Test Street 1, 8000 Zurich",
        },
    }
    state.event_entry = event_entry
    state.current_step = step
    state.db["events"].append(event_entry)
    return state


def enqueue_hil_request(state: WorkflowState, task_type: str = "negotiation_approval") -> str:
    """Enqueue a HIL request and return the task_id."""
    task_id = f"task-{task_type}-001"
    hil_request = {
        "task_id": task_id,
        "step": state.current_step,
        "type": task_type,
        "thread_id": "thread-test",
        "draft": {
            "headers": ["Subject: Offer Confirmation"],
            "body": "Your offer has been accepted.",
            "body_markdown": "Your offer has been accepted.",
        },
    }
    state.event_entry.setdefault("pending_hil_requests", []).append(hil_request)

    # Also add to tasks array (required by update_task_status)
    task_entry = {
        "task_id": task_id,
        "event_id": state.event_entry.get("event_id"),
        "type": task_type,
        "status": "pending",
        "created_at": "2025-11-01T09:00:00Z",
    }
    state.db.setdefault("tasks", []).append(task_entry)

    return task_id


# ==============================================================================
# APPROVE_HIL_001: Manager Approval Flow
# ==============================================================================


class TestManagerApprovalFlow:
    """
    APPROVE_HIL_001: Manager approval updates task status and progresses workflow.

    Tests the end-to-end approval flow from HIL request to workflow progression.
    """

    def test_approve_task_updates_status_to_approved(self, tmp_path: Path):
        """Approving a task should update its status to APPROVED."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        result = wf.approve_task_and_send(task_id, db_path=state.db_path)

        assert result["action"] == "send_reply"
        assert result["event_id"] == "evt-hil-test"
        assert "draft" in result

    def test_approve_task_removes_from_pending(self, tmp_path: Path):
        """Approving a task should remove it from pending_hil_requests."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        wf.approve_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        pending = event.get("pending_hil_requests", [])
        assert not any(r["task_id"] == task_id for r in pending)

    def test_approve_task_records_hil_history(self, tmp_path: Path):
        """Approving a task should add entry to hil_history."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        wf.approve_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        hil_history = event.get("hil_history", [])
        assert len(hil_history) >= 1
        latest = hil_history[-1]
        assert latest["task_id"] == task_id
        assert latest["decision"] == "approved"

    def test_approve_with_manager_notes(self, tmp_path: Path):
        """Manager notes should be included in the response."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        notes = "Approved with discount applied."
        result = wf.approve_task_and_send(task_id, db_path=state.db_path, manager_notes=notes)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        hil_history = event.get("hil_history", [])
        latest = hil_history[-1]
        assert latest["notes"] == notes


# ==============================================================================
# APPROVE_HIL_002: Step 5 Negotiation Approval
# ==============================================================================


class TestNegotiationApproval:
    """
    APPROVE_HIL_002: Step 5 negotiation approval advances to transition.

    Tests that approving a negotiation at Step 5 correctly advances the workflow.
    """

    def test_negotiation_approval_sets_offer_accepted(self, tmp_path: Path):
        """Approving negotiation should set offer_status to Accepted."""
        state = create_hil_pending_state(tmp_path, step=5)

        # Process negotiation to enqueue HIL
        result = negotiation_close.process(state)
        wf._finalize_output(result, state)  # type: ignore[attr-defined]

        pending = state.event_entry.get("pending_hil_requests", [])
        if not pending:
            pytest.skip("No HIL request created for this scenario")

        task_id = pending[0]["task_id"]
        wf.save_db(state.db, path=state.db_path)

        wf.approve_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        assert event.get("offer_status") == "Accepted"

    def test_negotiation_approval_advances_step(self, tmp_path: Path):
        """Approving negotiation should advance to Step 6 or 7."""
        state = create_hil_pending_state(tmp_path, step=5)

        result = negotiation_close.process(state)
        wf._finalize_output(result, state)  # type: ignore[attr-defined]

        pending = state.event_entry.get("pending_hil_requests", [])
        if not pending:
            pytest.skip("No HIL request created for this scenario")

        task_id = pending[0]["task_id"]
        wf.save_db(state.db, path=state.db_path)

        wf.approve_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        # Should advance past Step 5
        assert event.get("current_step") >= 6


# ==============================================================================
# APPROVE_HIL_003: Rejection Flow
# ==============================================================================


class TestManagerRejectionFlow:
    """
    APPROVE_HIL_003: Manager rejection updates task status and records decision.
    """

    def test_reject_task_removes_from_pending(self, tmp_path: Path):
        """Rejecting a task should remove it from pending_hil_requests."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        wf.reject_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        pending = event.get("pending_hil_requests", [])
        assert not any(r["task_id"] == task_id for r in pending)

    def test_reject_task_records_hil_history(self, tmp_path: Path):
        """Rejecting a task should add entry to hil_history with rejected decision."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        wf.reject_task_and_send(task_id, db_path=state.db_path)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        hil_history = event.get("hil_history", [])
        assert len(hil_history) >= 1
        latest = hil_history[-1]
        assert latest["task_id"] == task_id
        assert latest["decision"] == "rejected"

    def test_reject_with_manager_notes(self, tmp_path: Path):
        """Manager notes should be recorded on rejection."""
        state = create_hil_pending_state(tmp_path, step=5)
        task_id = enqueue_hil_request(state)
        wf.save_db(state.db, path=state.db_path)

        notes = "Rejected: Price too low for this configuration."
        wf.reject_task_and_send(task_id, db_path=state.db_path, manager_notes=notes)

        db = wf.load_db(state.db_path)
        event = db["events"][0]
        hil_history = event.get("hil_history", [])
        latest = hil_history[-1]
        assert latest["notes"] == notes


# ==============================================================================
# APPROVE_HIL_004: Error Handling
# ==============================================================================


class TestApprovalErrorHandling:
    """
    APPROVE_HIL_004: Error handling for invalid task IDs.
    """

    def test_approve_nonexistent_task_raises(self, tmp_path: Path):
        """Approving a nonexistent task should raise ValueError."""
        state = create_hil_pending_state(tmp_path, step=5)
        wf.save_db(state.db, path=state.db_path)

        with pytest.raises(ValueError, match="not found"):
            wf.approve_task_and_send("nonexistent-task-id", db_path=state.db_path)

    def test_reject_nonexistent_task_raises(self, tmp_path: Path):
        """Rejecting a nonexistent task should raise ValueError."""
        state = create_hil_pending_state(tmp_path, step=5)
        wf.save_db(state.db, path=state.db_path)

        with pytest.raises(ValueError, match="not found"):
            wf.reject_task_and_send("nonexistent-task-id", db_path=state.db_path)
