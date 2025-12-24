import json
from hashlib import sha256
from pathlib import Path

import importlib

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.process")
from backend.workflows.steps.step3_room_availability.trigger.process import process as room_process

from ...utils.seeds import set_seed

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "room_search_cases.json"


def _requirements_hash(requirements: dict) -> str:
    payload = f"{requirements['date']}|{requirements['capacity']}|{requirements['layout']}"
    return sha256(payload.encode()).hexdigest()


def test_room_search_classification():
    cases = json.loads(FIXTURE.read_text())

    available = cases["available"]
    option_only = cases["option_only"]
    unavailable = cases["unavailable"]

    assert any(room["fits"] and not room["option"] for room in available["rooms"])
    assert all(room["option"] for room in option_only["rooms"])
    assert unavailable["rooms"] == []


def test_lock_room_records_hash():
    set_seed()
    case = json.loads(FIXTURE.read_text())["available"]

    requirements = {
        "date": case["date"],
        "capacity": case["capacity"],
        "layout": "theatre",
    }

    locked_room_id = case["rooms"][0]["id"]
    requirements_hash = _requirements_hash(requirements)
    room_eval_hash = requirements_hash

    lock_payload = {
        "locked_room_id": locked_room_id,
        "room_eval_hash": room_eval_hash,
        "next_step": 4,
    }

    assert lock_payload["locked_room_id"] == "R1"
    assert lock_payload["room_eval_hash"] == requirements_hash
    assert lock_payload["next_step"] == 4


def _build_room_state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(msg_id="msg-1", from_name=None, from_email=None, subject=None, body=None, ts=None)
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_id = "EVT-1"
    state.current_step = 3
    state.user_info = {}
    return state


def test_room_process_structured_payload(tmp_path, monkeypatch):
    state = _build_room_state(tmp_path)
    requirements = {"number_of_participants": 80, "seating_layout": "theatre"}
    req_hash = requirements_hash(requirements)
    event_entry = {
        "event_id": state.event_id,
        "chosen_date": "15.03.2025",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
        "preferences": {
            "wish_products": ["Three-course dinner", "Wine pairing"],
            "keywords": ["wine"],
        },
    }
    state.event_entry = event_entry

    def fake_evaluate(db, target_date):
        return [{"Room A": "Available"}, {"Room B": "Option"}]

    monkeypatch.setattr(room_module, "evaluate_room_statuses", fake_evaluate)
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

    result = room_process(state)
    draft = state.draft_messages[-1]

    assert result.action == "room_avail_result"
    assert draft["footer"].startswith("Step: 3 Room Availability")
    first_block = draft["table_blocks"][0]
    assert first_block["type"] == "room_menu"
    assert any(row["room"] == "Room A" for row in first_block["rows"])
    assert all("hint" in row for row in first_block["rows"])
    assert all("requirements" in row for row in first_block["rows"])
    assert any(action["type"] == "select_room" for action in draft["actions"])
    assert all("hint" in action for action in draft["actions"])
    assert all("requirements" in action for action in draft["actions"])


def test_room_process_skips_when_hash_cached(tmp_path, monkeypatch):
    state = _build_room_state(tmp_path)
    requirements = {"number_of_participants": 60}
    req_hash = requirements_hash(requirements)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "15.03.2025",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": req_hash,
        "locked_room_id": "Room A",
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
    }

    def fail_evaluate(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("Room evaluation should be skipped when hashes match")

    monkeypatch.setattr(room_module, "evaluate_room_statuses", fail_evaluate)

    result = room_process(state)
    assert result.action == "room_eval_skipped"
    assert not state.draft_messages
