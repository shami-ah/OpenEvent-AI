from pathlib import Path

import pytest

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step2_date_confirmation.trigger.process import (
    _present_candidate_dates,
    _finalize_confirmation,
)
from backend.workflows.steps.step3_room_availability.trigger.process import process as room_process
from backend.workflows.steps.step4_offer.trigger.process import process as offer_process
import importlib

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.process")


def _build_state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-e2e",
        from_name="Client",
        from_email="client@example.com",
        subject="Event request",
        body="Hello!",
        ts="2025-10-01T09:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_id = "EVT-E2E"
    state.client_id = "client@example.com"
    state.current_step = 2
    state.set_thread_state("Awaiting Client")
    return state


@pytest.mark.parametrize("room_status", [["Available"], ["Unavailable"]])
def test_stubbed_flow_progression(tmp_path, monkeypatch, room_status):
    state = _build_state(tmp_path)
    event_entry = {
        "event_id": state.event_id,
        "requirements": {"number_of_participants": 60, "seating_layout": "theatre"},
        "requirements_hash": None,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
        "preferences": {
            "wish_products": ["Three-course dinner", "Wine pairing"],
            "keywords": ["wine"],
        },
    }
    state.event_entry = event_entry

    monkeypatch.setattr(
        "backend.workflows.groups.intake.condition.checks.suggest_dates",
        lambda *_args, **_kwargs: ["10.11.2025", "12.11.2025"],
    )

    # Step 2: present candidates
    _present_candidate_dates(state, event_entry)
    draft_step2 = state.draft_messages[-1]
    assert draft_step2["table_blocks"], "Date options should be presented in a table"
    assert draft_step2["actions"], "Date selection must provide CTA actions"

    # Confirm selected date
    state.user_info = {"event_date": draft_step2["actions"][0]["date"]}
    state.draft_messages.clear()
    confirmation_result = _finalize_confirmation(state, event_entry, draft_step2["actions"][0]["date"])
    assert confirmation_result.action in {"date_confirmed", "room_avail_result"}
    assert event_entry["date_confirmed"] is True

    # Step 3: room availability
    chosen_date = event_entry["chosen_date"]
    requirements = {
        "number_of_participants": 60,
        "seating_layout": "theatre",
    }
    req_hash = requirements_hash(requirements)

    if confirmation_result.action == "room_avail_result":
        room_result = confirmation_result
        draft_step3 = state.draft_messages[-1] if state.draft_messages else {}
    else:
        event_entry.update(
            {
                "requirements": requirements,
                "requirements_hash": req_hash,
                "room_eval_hash": None,
                "locked_room_id": None,
                "chosen_date": chosen_date,
                "current_step": 3,
                "date_confirmed": True,
                "preferences": {
                    "wish_products": ["Three-course dinner", "Wine pairing"],
                    "keywords": ["wine"],
                },
            }
        )
        state.current_step = 3
        state.draft_messages.clear()

        def fake_evaluate(_db, _date):
            if room_status[0] == "Available":
                return [{"Room A": "Available"}, {"Room B": "Option"}]
            return [{"Room A": "Unavailable"}, {"Room B": "Unavailable"}]

        monkeypatch.setattr(room_module, "evaluate_room_statuses", fake_evaluate)
        monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

        room_result = room_process(state)
        draft_step3 = state.draft_messages[-1] if state.draft_messages else {}

    if room_status[0] == "Available":
        assert room_result.action == "room_avail_result"
        assert draft_step3["table_blocks"][0]["type"] == "room_menu"
        assert draft_step3["actions"] and draft_step3["actions"][0]["type"] == "select_room"
        assert draft_step3["actions"][0]["hint"].lower().startswith("three-course")
        assert draft_step3["table_blocks"][0]["rows"][0]["hint"].lower().startswith("three-course")

        # HIL approval path
        state.user_info = {"hil_approve_step": 3, "hil_decision": "approve"}
        approve_result = room_process(state)
        assert approve_result.action == "room_hil_approved"
        event_entry["locked_room_id"] = approve_result.payload.get("selected_room")
    else:
        assert "table_blocks" in draft_step3
        assert draft_step3["thread_state"] == "Awaiting Client"
        return  # Stop flow for unavailable variant

    # Step 4: compose offer
    state.current_step = 4
    state.draft_messages.clear()
    event_entry.update(
        {
            "date_confirmed": True,
            "requirements_hash": req_hash,
            "room_eval_hash": req_hash,
            "products_state": {"line_items": []},
            "products": [],
            "selected_products": [],
        }
    )
    state.user_info = {}
    offer_result = offer_process(state)
    draft_messages = state.draft_messages or offer_result.payload.get("draft_messages", [])
    assert offer_result.action in {"offer_draft_prepared", "offer_detour"}

    if offer_result.action == "offer_draft_prepared":
        if draft_messages:
            draft_step4 = draft_messages[-1]
            assert draft_step4["table_blocks"]
            actions = draft_step4.get("actions") or offer_result.payload.get("actions", [])
        else:
            draft_meta = offer_result.payload.get("res", {}).get("assistant_draft", {})
            body = draft_meta.get("body", "")
            assert "Offer draft" in body
            actions = offer_result.payload.get("actions", [])
        assert any(action["type"] == "send_offer" for action in actions)
    else:
        assert offer_result.payload.get("missing") == ["P2"]
