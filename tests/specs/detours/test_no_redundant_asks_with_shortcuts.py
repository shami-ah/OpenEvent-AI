from __future__ import annotations

import importlib
from pathlib import Path

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.process")
from backend.workflows.steps.step3_room_availability.trigger.process import process as room_process


def _room_state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(msg_id="shortcut-room", from_name="Client", from_email="client@example.com", subject=None, body=None, ts=None)
    state = WorkflowState(message=msg, db_path=tmp_path / "shortcut-room.json", db={"events": []})
    state.event_id = "EVT-SHORTCUT"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    return state


def test_no_redundant_capacity_prompt_with_shortcut(tmp_path, monkeypatch):
    state = _room_state(tmp_path)
    requirements = {"number_of_participants": 80, "seating_layout": "theatre"}
    req_hash = requirements_hash(requirements)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "20.11.2025",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
    }
    state.user_info = {"shortcut_capacity_ok": True}

    monkeypatch.setattr(room_module, "evaluate_room_statuses", lambda *_: [{"Room A": "Available"}])
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

    room_process(state)
    draft = state.draft_messages[-1]
    assert "fits" not in (draft.get("body_markdown") or ""), "Capacity prompt should be omitted when shortcut present"


def test_hash_changes_trigger_dependent_steps_only(tmp_path, monkeypatch):
    state = _room_state(tmp_path)
    requirements = {"number_of_participants": 40, "seating_layout": "u-shape"}
    initial_hash = requirements_hash(requirements)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "05.12.2025",
        "requirements": requirements,
        "requirements_hash": initial_hash,
        "room_eval_hash": initial_hash,
        "locked_room_id": "Room A",
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
    }

    call_count = {"value": 0}

    def track_evaluate(*_args, **_kwargs):
        call_count["value"] += 1
        return [{"Room A": "Available"}]

    monkeypatch.setattr(room_module, "evaluate_room_statuses", track_evaluate)

    # No change -> should skip evaluation
    result = room_process(state)
    assert result.action == "room_eval_skipped"
    assert call_count["value"] == 0

    # Update requirements (e.g., more participants) -> re-run exactly once
    updated_requirements = {"number_of_participants": 120, "seating_layout": "u-shape"}
    new_hash = requirements_hash(updated_requirements)
    state.event_entry.update(
        {
            "requirements": updated_requirements,
            "requirements_hash": new_hash,
            "room_eval_hash": initial_hash,
            "locked_room_id": None,
            "date_confirmed": True,
        }
    )
    state.user_info = {}
    result = room_process(state)
    assert result.action == "room_avail_result"
    assert call_count["value"] == 1
    pending = state.event_entry.get("room_pending_decision") or {}
    assert pending.get("requirements_hash") == new_hash