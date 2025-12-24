from __future__ import annotations

from pathlib import Path

from backend.debug.trace import BUS
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step2_date_confirmation.trigger.process import process


def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-general",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Room availability",
        body="Which rooms are free on Saturday evenings in February for ~30 people?",
        ts="2025-01-05T09:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "general-room.json", db={"events": []})
    state.client_id = "laura@example.com"
    state.thread_id = "room-thread"
    return state


def test_general_room_qna_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    BUS._buf.clear()  # type: ignore[attr-defined]

    state = _state(tmp_path)
    event_entry = {
        "event_id": "EVT-GENERAL",
        "requirements": {"preferred_room": "Room A", "number_of_participants": 30},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
    }
    state.event_entry = event_entry
    state.user_info = {}

    free_dates = ["01.02.2026", "08.02.2026", "15.02.2026"]
    import importlib

    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setattr(step2_module, "list_free_dates", lambda count, db, preferred_room: free_dates[:count])
    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-02-01", "2026-02-08", "2026-02-15"],
    )

    result = process(state)

    assert result.action == "general_rooms_qna"
    draft = state.draft_messages[-1]
    assert draft["topic"] == "general_room_qna"
    assert draft["candidate_dates"] == free_dates
    assert draft["range_results"], "Hybrid queries should include concrete availability rows"
    body = draft["body"]
    assert "Availability overview" in body
    assert "All options below fit 30 guests." in body
    assert "available on Sun 01 Feb 2026, Sun 08 Feb 2026 and Sun 15 Feb 2026" in body
    assert "| Room | Dates | Notes |" in body
    assert "Status: Available" in body
    assert "- Room A" not in body
    assert "- Room B" not in body
    assert draft["footer"].endswith("State: Awaiting Client")

    table_block = draft["table_blocks"][0]
    assert table_block["column_order"] == ["room", "dates", "notes"]
    assert table_block["rows"][0]["room"] == "Room A"
    assert "Status: Available" in table_block["rows"][0]["notes"]

    events = BUS.get(state.thread_id)  # type: ignore[attr-defined]
    assert any(
        event.get("io", {}).get("op") == "db.rooms.search_range"
        for event in events
        if event.get("kind") == "DB_READ"
    )
    assert any(event.get("subject") == "QNA_CLASSIFY" for event in events)


def test_general_room_qna_captures_shortcuts(monkeypatch, tmp_path):
    state = _state(tmp_path)
    event_entry = {
        "event_id": "EVT-GENERAL",
        "requirements": {"preferred_room": "Room B"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
    }
    state.event_entry = event_entry
    state.user_info = {
        "company": "ACME AG",
        "billing_address": "Bahnhofstrasse 1",
        "vague_month": "February",
        "vague_weekday": "Saturday",
    }

    import importlib

    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-02-07", "2026-02-14"],
    )
    monkeypatch.setattr(step2_module, "list_free_dates", lambda *_a, **_k: ["07.02.2026", "14.02.2026"])

    process(state)

    captured = event_entry.get("captured") or {}
    billing = captured.get("billing") or {}
    assert billing.get("company") == "ACME AG"
    assert billing.get("address") == "Bahnhofstrasse 1"


def test_general_room_qna_respects_window_without_fallback(monkeypatch, tmp_path):
    state = _state(tmp_path)
    event_entry = {
        "event_id": "EVT-GENERAL",
        "requirements": {"preferred_room": "Room C"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
    }
    state.event_entry = event_entry
    state.user_info = {
        "vague_month": "February",
        "vague_weekday": "Saturday",
    }

    import importlib

    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setattr(step2_module, "_search_range_availability", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(step2_module, "_candidate_dates_for_constraints", lambda *_args, **_kwargs: [])
    fallback_called = {"flag": False}

    def _fake_list_free(*_args, **_kwargs):
        fallback_called["flag"] = True
        return ["12.11.2025", "13.11.2025"]

    monkeypatch.setattr(step2_module, "list_free_dates", _fake_list_free)

    result = process(state)
    draft = state.draft_messages[-1]

    assert result.action == "general_rooms_qna"
    assert not fallback_called["flag"], "Off-window fallback should not run when constraints are present."
    assert draft["candidate_dates"] == []
    assert "need a specific date" in draft["body"].lower()
