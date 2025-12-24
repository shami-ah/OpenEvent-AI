from pathlib import Path

from backend import workflow_email as wf
from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps import step5_negotiation as negotiation_close


def _build_state(tmp_path: Path) -> WorkflowState:
    """Construct a minimal workflow state positioned at Step 5 for acceptance."""

    msg = IncomingMessage.from_dict(
        {
            "msg_id": "msg-accept",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Offer reply",
            "body": "We confirm the offer.",
            "ts": "2025-11-01T09:00:00Z",
        }
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.intent = IntentLabel.EVENT_REQUEST
    state.client_id = "client@example.com"

    event_entry = {
        "event_id": "evt-accept",
        "current_step": 5,
        "thread_state": "Awaiting Client",
        "flags": {"manager_requested": True},
        "offers": [{"offer_id": "offer-1"}],
        "current_offer_id": "offer-1",
        "negotiation_state": {"counter_count": 0, "manual_review_task_id": None},
        "requirements": {"number_of_participants": 10},
        "locked_room_id": "Room A",
        "offer_status": "Draft",
        "billing_details": {
            "name_or_company": "Test Client",
            "street": "Mainstrasse 1",
            "postal_code": "8000",
            "city": "Zurich",
            "country": "Switzerland",
        },
        "event_data": {
            "Billing Address": "Test Client, Mainstrasse 1, 8000 Zurich, Switzerland",
            "Email": "client@example.com",
        },
    }
    state.event_entry = event_entry
    state.current_step = 5
    state.db["events"].append(event_entry)
    return state


def test_negotiation_accept_enqueues_hil_and_keeps_progression(tmp_path: Path) -> None:
    state = _build_state(tmp_path)

    result = negotiation_close.process(state)
    payload = wf._finalize_output(result, state)  # type: ignore[attr-defined]

    assert any(action.get("type") == "negotiation_enqueued" for action in payload.get("actions", []))

    pending = state.event_entry.get("pending_hil_requests") or []
    assert pending and pending[0].get("step") == 5

    # Stay on Step 5 while waiting for the manager to approve.
    assert state.event_entry.get("current_step") == 5
    assert state.event_entry.get("thread_state") == "Waiting on HIL"

    wf.save_db(state.db, path=state.db_path)
    wf.approve_task_and_send(pending[0]["task_id"], db_path=state.db_path)

    db = wf.load_db(state.db_path)
    persisted_event = db.get("events", [])[0]
    assert persisted_event.get("offer_status") == "Accepted"
    assert persisted_event.get("current_step") >= 6


def test_hil_approval_moves_to_transition(tmp_path: Path) -> None:
    state = _build_state(tmp_path)
    result = negotiation_close.process(state)
    wf._finalize_output(result, state)  # type: ignore[attr-defined]

    pending = state.event_entry.get("pending_hil_requests") or []
    assert pending, "HIL request should exist before approval"
    task_id = pending[0]["task_id"]

    wf.save_db(state.db, path=state.db_path)
    wf.approve_task_and_send(task_id, db_path=state.db_path)

    db = wf.load_db(state.db_path)
    persisted_event = db.get("events", [])[0]
    assert persisted_event.get("offer_status") == "Accepted"
    # Transition checkpoint should mark readiness for confirmation.
    assert persisted_event.get("current_step") in {6, 7}
