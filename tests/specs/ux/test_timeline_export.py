from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.domain import IntentLabel
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps import step1_intake as intake
from backend.workflows.steps.step2_date_confirmation.trigger import process as date_process
from backend.workflows.steps.step4_offer.trigger.process import process as offer_process
from backend.workflows.steps.step3_room_availability.trigger import process as room_process
from backend.debug.lifecycle import close_if_ended


def test_debug_trace_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    monkeypatch.setenv("DEBUG_TRACE_DIR", str(tmp_path / "sessions"))

    timeline_module = importlib.import_module("backend.debug.timeline")
    importlib.reload(timeline_module)
    intake_trigger_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")
    monkeypatch.setattr(intake_trigger_module, "classify_intent", lambda _payload: (IntentLabel.EVENT_REQUEST, 0.99))
    monkeypatch.setattr(intake_trigger_module, "extract_user_information", lambda _payload: {"participants": 30, "event_date": None, "vague_month": "February", "vague_weekday": "Saturday", "vague_time_of_day": "evening"})

    # Reload main to ensure debug route is registered with the env toggle.
    main = importlib.import_module("backend.main")
    importlib.reload(main)

    thread_id = "trace-contract-thread"

    db = {"events": [], "clients": {}, "tasks": []}
    message = IncomingMessage(
        msg_id="msg-trace-1",
        from_name="Laura Meier",
        from_email="laura.meier@example.com",
        subject="Private Dinner Event",
        body=(
            "Hello,\n"
            "We’d like to organize a private dinner for around 30 guests.\n"
            "Preferably a Saturday in February with a three-course dinner and wine.\n"
        ),
        ts="2025-01-05T09:00:00Z",
    )
    state = WorkflowState(message=message, db_path=Path(tmp_path) / "events.json", db=db)
    state.thread_id = thread_id

    intake.process(state)

    # Step 2: present candidate dates (no confirmation yet).
    event_entry = state.event_entry or {}
    event_entry['chosen_date'] = None
    event_entry['date_confirmed'] = False
    event_entry['current_step'] = 2

    state.user_info = {}
    state.current_step = 2
    monkeypatch.setattr(
        "backend.workflows.groups.intake.condition.checks.suggest_dates",
        lambda *_args, **_kwargs: ["10.11.2025", "12.11.2025"],
    )
    date_process(state)

    # Simulate confirming a date and preparing requirements for Step 3.
    event_entry = state.event_entry or {}
    requirements = {"number_of_participants": 30, "seating_layout": "banquet"}
    event_entry["requirements"] = requirements
    event_entry["requirements_hash"] = requirements_hash(requirements)
    event_entry["chosen_date"] = "12.11.2025"
    event_entry["date_confirmed"] = True
    event_entry["current_step"] = 3
    state.user_info = {"shortcut_capacity_ok": True}
    state.current_step = 3

    room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")
    monkeypatch.setattr(room_module, "evaluate_room_statuses", lambda *_: [{"Room A": "Available"}])
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

    room_process(state)

    # Prepare Step 4 inputs and run.
    event_entry["locked_room_id"] = "Room A"
    event_entry["room_eval_hash"] = event_entry.get("requirements_hash")
    event_entry["products_state"] = {"line_items": [], "skip_products": True}
    event_entry["products"] = []
    event_entry["selected_products"] = []
    state.user_info = {}
    state.current_step = 4
    offer_process(state)

    client = TestClient(main.app)
    response = client.get(f"/api/debug/threads/{thread_id}")
    assert response.status_code == 200
    payload = response.json()

    assert payload["thread_id"] == thread_id
    assert payload["state"], "Expected state snapshot to be present"
    assert payload["timeline"], "Expected timeline entries in debug trace payload"

    lanes = {event["lane"] for event in payload["trace"]}
    for lane in ("step", "gate", "db", "entity"):
        assert lane in lanes, f"Expected events in lane '{lane}'"

    step_events = [event for event in payload["trace"] if event["lane"] == "step"]
    assert any(event["kind"] == "STEP_ENTER" and event.get("step") == "Step1_Intake" for event in step_events)
    draft_events = [event for event in payload["trace"] if event["kind"] == "DRAFT_SEND"]
    assert draft_events, "Expected at least one draft event"
    for event in draft_events:
        footer = event.get("data", {}).get("footer", {})
        assert footer.get("step")
        assert footer.get("next") is not None
        assert footer.get("wait_state") is not None

    gate_events = [event for event in payload["trace"] if event["lane"] == "gate"]
    assert any(
        isinstance(event.get("detail"), dict) and event["detail"].get("fn") == "P1 date_confirmed"
        for event in gate_events
    )
    assert any(event.get("owner_step") == "Step4_Offer" for event in gate_events)

    db_events = [event for event in payload["trace"] if event["lane"] == "db"]
    assert any(event["kind"] == "DB_WRITE" for event in db_events)

    entity_events = [event for event in payload["trace"] if event["lane"] == "entity"]
    assert any(event["kind"] == "ENTITY_CAPTURE" for event in entity_events)

    timeline_path = timeline_module.resolve_path(thread_id)
    assert timeline_path is not None and Path(timeline_path).exists()

    with Path(timeline_path).open("r", encoding="utf-8") as handle:
        timeline_events = [json.loads(line) for line in handle if line.strip()]

    assert timeline_events, "Timeline should contain events"
    timestamps = [event["ts"] for event in timeline_events]
    assert timestamps == sorted(timestamps), "Timeline timestamps should be non-decreasing"

    kinds = {event["kind"] for event in timeline_events}
    for expected_kind in {"STEP_ENTER", "GATE_PASS", "DB_READ", "DB_WRITE", "ENTITY_CAPTURE", "DRAFT_SEND"}:
        assert expected_kind in kinds, f"Expected timeline to capture '{expected_kind}'"

    draft_entries = [event for event in timeline_events if event["kind"] == "DRAFT_SEND"]
    assert draft_entries, "Timeline should include draft events"
    for entry in draft_entries:
        footer = entry.get("data", {}).get("footer", {})
        assert footer.get("step")
        assert footer.get("next") is not None
        assert footer.get("wait_state") is not None

    timeline_response = client.get(f"/api/debug/threads/{thread_id}/timeline")
    assert timeline_response.status_code == 200
    timeline_payload = timeline_response.json()
    assert timeline_payload["timeline"], "Timeline endpoint should return events"

    download_response = client.get(f"/api/debug/threads/{thread_id}/timeline/download")
    assert download_response.status_code == 200

    # Simulate closing the thread and ensure the file is archived.
    close_if_ended(thread_id, {"thread_state": "Closed"})
    archived_path = timeline_module.resolve_path(thread_id)
    assert archived_path is not None
    assert Path(archived_path).exists()
    assert "archive" in Path(archived_path).parts