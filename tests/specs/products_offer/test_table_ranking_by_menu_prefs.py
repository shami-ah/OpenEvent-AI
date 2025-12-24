from __future__ import annotations

import importlib
from pathlib import Path

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.process")
from backend.workflows.steps.step3_room_availability.trigger.process import process as room_process


def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(msg_id="menu-pref", from_name="Client", from_email="client@example.com", subject=None, body=None, ts=None)
    state = WorkflowState(message=msg, db_path=tmp_path / "menu-pref.json", db={"events": []})
    state.event_id = "EVT-MENU"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    return state


def test_room_table_ranks_by_menu_preferences(tmp_path, monkeypatch):
    state = _state(tmp_path)
    requirements = {"number_of_participants": 30, "seating_layout": "banquet"}
    req_hash = requirements_hash(requirements)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "22.03.2025",
        "date_confirmed": True,
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
        "preferences": {
            "wish_products": ["Wine pairing"],
            "keywords": ["stage"],
        },
    }

    def fake_eval(_db, _date):
        return [{"Room B": "Option"}, {"Room A": "Available"}, {"Room C": "Unavailable"}]

    monkeypatch.setattr(room_module, "evaluate_room_statuses", fake_eval)
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

    result = room_process(state)
    draft = state.draft_messages[-1]
    table_rows = draft["table_blocks"][0]["rows"]
    actions = draft["actions"]

    assert result.action == "room_avail_result"
    assert table_rows[0]["room"] == "Room A"
    assert table_rows[0]["hint"].lower().startswith("wine")
    assert table_rows[0]["requirements_score"] >= table_rows[1]["requirements_score"]

    assert all(action["type"] == "select_room" for action in actions)
    assert all("hint" in action and "date" in action for action in actions)
    assert actions[0]["room"] == "Room A"
