from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain import IntentLabel, TaskType
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps import step5_negotiation as negotiation_close


def _make_state(body: str, *, event_overrides: dict | None = None, user_info: dict | None = None) -> WorkflowState:
    event_entry = {
        "event_id": "evt-123",
        "locked_room_id": "Room A",
        "chosen_date": "02.11.2025",
        "date_confirmed": True,
        "offers": [
            {
                "offer_id": "offer-1",
                "total_amount": 750.0,
            }
        ],
        "current_offer_id": "offer-1",
        "negotiation_state": {"counter_count": 0, "manual_review_task_id": None},
        "requirements": {"number_of_participants": 15},
    }
    if event_overrides:
        event_entry.update(event_overrides)
    db = {"events": [event_entry], "tasks": []}
    state = WorkflowState(
        message=IncomingMessage.from_dict(
            {
                "msg_id": "msg-1",
                "from_name": "Client",
                "from_email": "client@example.com",
                "subject": "Offer reply",
                "body": body,
                "ts": "2025-11-01T09:00:00Z",
            }
        ),
        db_path=Path("test-db.json"),
        db=db,
    )
    state.client_id = "client@example.com"
    state.intent = IntentLabel.EVENT_REQUEST
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = 5
    state.user_info = user_info or {}
    return state


def test_accept_direct_en_creates_task_and_reply() -> None:
    state = _make_state("Great, we confirm the offer.")
    result = negotiation_close.process(state)
    assert result.action == "negotiation_accept"
    draft = state.draft_messages[-1]["body"]
    assert "NEXT STEP:" in draft
    assert "We’ll prepare the final offer for approval and sending." in draft
    tasks = state.db.get("tasks", [])
    assert any(task.get("type") == TaskType.ROUTE_POST_OFFER.value for task in tasks)
    assert state.telemetry.final_action == "accepted"


def test_accept_direct_de() -> None:
    state = _make_state("Das passt, wir bestätigen.")
    result = negotiation_close.process(state)
    assert result.action == "negotiation_accept"


def test_not_accept_request() -> None:
    state = _make_state("Can you confirm the offer?")
    result = negotiation_close.process(state)
    assert result.action == "negotiation_clarification"


def test_not_accept_conditional() -> None:
    state = _make_state("If you approve, we can proceed.")
    result = negotiation_close.process(state)
    assert result.action == "negotiation_clarification"


def test_counter_overrides_accept() -> None:
    state = _make_state(
        "We confirm, but make it 30 people.",
        user_info={"participants": 30},
        event_overrides={"requirements": {"number_of_participants": 15}},
    )
    result = negotiation_close.process(state)
    assert result.action in {"negotiation_counter", "negotiation_detour"}


def test_accept_requires_invariants_missing_room() -> None:
    state = _make_state(
        "We confirm the offer.",
        event_overrides={
            "locked_room_id": None,
        },
    )
    result = negotiation_close.process(state)
    assert result.action == "transition_blocked"
    draft = state.draft_messages[-1]["body"]
    assert draft.startswith("INFO:")
    assert "room" in draft.lower()
    assert "NEXT STEP:" in draft
    tasks = state.db.get("tasks", [])
    assert not tasks