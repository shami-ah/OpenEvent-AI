from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

from backend.debug.trace import BUS
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step2_date_confirmation.trigger.process import _present_candidate_dates



def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-vague",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Saturday in February",
        body="We'd like a Saturday evening in February for about 30 guests.",
        ts="2024-12-10T09:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "vague-dates.json", db={"events": []})
    state.client_id = "laura@example.com"
    return state


def test_vague_month_weekday_enumeration(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    BUS._buf.clear()  # type: ignore[attr-defined]

    deterministic = [
        date(2026, 2, 7),
        date(2026, 2, 14),
        date(2026, 2, 21),
        date(2026, 2, 28),
        date(2026, 3, 7),
    ]

    def _fake_next5(*_args, **_kwargs):
        return list(deterministic)

    monkeypatch.setattr("backend.workflows.io.dates.next5", _fake_next5)
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setattr(
        step2_module,
        "suggest_dates",
        lambda *_args, **_kwargs: ["07.02.2026", "14.02.2026", "21.02.2026", "28.02.2026", "07.03.2026"],
    )
    monkeypatch.setattr(step2_module, "next_five_venue_dates", lambda *_a, **_k: [])

    state = _state(tmp_path)
    state.thread_id = "vague-thread"
    event_entry = {
        "event_id": "EVT-VAGUE",
        "requirements": {"preferred_room": "Room A"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "vague_month": "February",
        "vague_weekday": "Saturday",
        "vague_time_of_day": "evening",
    }
    state.event_entry = event_entry
    state.user_info = {
        "vague_month": "February",
        "vague_weekday": "Saturday",
        "vague_time_of_day": "evening",
    }

    _present_candidate_dates(state, event_entry)

    draft = state.draft_messages[-1]
    block = draft["table_blocks"][0]
    rows = block["rows"]
    actions = draft["actions"]

    assert block["type"] == "dates"
    assert "Saturdays in February" in block.get("label", "")
    assert len(rows) == len(actions) == 5
    assert all(action["type"] == "select_date" for action in actions)

    expected_iso = [value.isoformat() for value in deterministic]
    produced_iso = [row["iso_date"] for row in rows]
    assert produced_iso == expected_iso

    assert all(row.get("time_of_day") == "Evening" for row in rows)
    assert all("Evening" in action["label"] for action in actions)

    stored_candidates = event_entry.get("candidate_dates") or []
    assert stored_candidates == [action["date"] for action in actions]

    footer = draft.get("footer", "")
    assert footer == "Step: 2 Date Confirmation · Next: Room Availability · State: Awaiting Client"
    assert "- Room " not in draft.get("body_markdown", "")

    trace_events = BUS.get(state.thread_id)  # type: ignore[attr-defined]
    db_events = [event for event in trace_events if event.get("kind") == "DB_READ"]
    assert any(event.get("io", {}).get("op") == "db.dates.next5" for event in db_events)


def test_vague_range_forces_candidates(monkeypatch, tmp_path):
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setenv("DEBUG_TRACE", "1")

    state = _state(tmp_path)
    state.thread_id = "thread-range"
    state.client_id = "laura@example.com"
    event_entry = {
        "event_id": "EVT-VAGUE",
        "requirements": {"preferred_room": "Room B"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "range_query_detected": True,
        "vague_month": "February",
        "vague_weekday": "Saturday",
        "date_confirmed": False,
    }
    state.event_entry = event_entry
    state.user_info = {
        "range_query_detected": True,
        "vague_month": "February",
        "vague_weekday": "Saturday",
    }

    monkeypatch.setattr(
        step2_module,
        "suggest_dates",
        lambda *_args, **_kwargs: ["01.02.2026", "08.02.2026", "15.02.2026"],
    )
    monkeypatch.setattr(step2_module, "next_five_venue_dates", lambda *_a, **_k: [])

    result = step2_module.process(state)
    assert result.action == "date_options_proposed"
    draft = state.draft_messages[-1]
    assert draft["topic"] == "date_candidates"
    assert draft["candidate_dates"] == ["01.02.2026", "08.02.2026", "15.02.2026"]
    assert event_entry.get("date_confirmed") is False
