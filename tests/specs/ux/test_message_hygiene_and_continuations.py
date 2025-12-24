from __future__ import annotations

import importlib
from pathlib import Path

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step2_date_confirmation.trigger.process import (
    _present_candidate_dates,
    _finalize_confirmation,
)
from backend.workflows.steps.step4_offer.trigger.process import process as offer_process

from ...utils.timezone import freeze_time

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.process")
from backend.workflows.steps.step3_room_availability.trigger.process import process as room_process
from backend.workflows.common.types import GroupResult


def _mk_state(tmp_path: Path, step: int, thread_state: str = "Awaiting Client") -> WorkflowState:
    msg = IncomingMessage(msg_id=f"msg-step-{step}", from_name="Client", from_email="client@example.com", subject=None, body=None, ts=None)
    state = WorkflowState(message=msg, db_path=tmp_path / f"state-step-{step}.json", db={"events": []})
    state.current_step = step
    state.set_thread_state(thread_state)
    return state


def test_hygiene_across_steps(tmp_path, monkeypatch):
    drafts = []

    # Step 1 — simulated intake clarification (single CTA + footer)
    step1_state = _mk_state(tmp_path, step=1)
    step1_state.add_draft_message(
        {
            "body_markdown": "Could you share the best email address so we can confirm details?",
            "step": 1,
            "next_step": "Share email",
            "thread_state": "Awaiting Client",
            "actions": [
                {
                    "type": "provide_email",
                    "label": "Send email",
                }
            ],
        }
    )
    drafts.append(step1_state.draft_messages[-1])

    # Step 2 — present deterministic candidate dates
    step2_state = _mk_state(tmp_path, step=2)
    event_entry = {
        "event_id": "EVT-UX",
        "requirements": {},
        "thread_state": "Awaiting Client",
        "current_step": 2,
    }
    step2_state.event_entry = event_entry
    monkeypatch.setattr(
        "backend.workflows.groups.intake.condition.checks.suggest_dates",
        lambda *_args, **_kwargs: ["12.11.2025", "13.11.2025"],
    )
    with freeze_time("2025-11-01 09:00:00"):
        _present_candidate_dates(step2_state, event_entry)
    drafts.append(step2_state.draft_messages[-1])

    # Q&A detour while Awaiting Client (no CTA required)
    step2_state.add_draft_message(
        {
            "body_markdown": "Happy to help — feel free to share any questions about the venue layout.",
            "step": 0,
            "next_step": "Provide details",
            "thread_state": "Awaiting Client",
            "actions": [],
        }
    )
    drafts.append(step2_state.draft_messages[-1])

    # Confirm date and move forward
    _finalize_confirmation(step2_state, event_entry, "12.11.2025")

    # Step 3 — room availability without redundant prompts
    step3_state = _mk_state(tmp_path, step=3)
    requirements = {"number_of_participants": 60, "seating_layout": "theatre"}
    req_hash = requirements_hash(requirements)
    step3_state.event_entry = {
        "event_id": "EVT-UX",
        "chosen_date": "12.11.2025",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
    }
    step3_state.user_info = {"shortcut_capacity_ok": True}

    monkeypatch.setattr(room_module, "evaluate_room_statuses", lambda *_: [{"Room A": "Available"}])
    monkeypatch.setattr(room_module, "_needs_better_room_alternatives", lambda *_: False)

    room_process(step3_state)
    drafts.append(step3_state.draft_messages[-1])

    # Step 4 — offer draft (single CTA)
    step4_state = _mk_state(tmp_path, step=4, thread_state="Awaiting Client")
    step4_state.event_entry = {
        "event_id": "EVT-UX",
        "chosen_date": "12.11.2025",
        "locked_room_id": "Room A",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": req_hash,
        "products_state": {"line_items": [], "skip_products": True},
        "products": [],
        "selected_products": [],
        "thread_state": "Awaiting Client",
        "current_step": 4,
        "date_confirmed": True,
    }
    step4_state.user_info = {}
    offer_process(step4_state)
    drafts.append(step4_state.draft_messages[-1])

    # Hygiene assertions
    for draft in drafts:
        footer = draft.get("footer", "")
        assert footer.startswith("Step:"), f"missing footer in draft: {draft}"
        assert "Next:" in footer and "State:" in footer
        actions = draft.get("actions") or []
        step = draft.get("step")
        if step == 2:
            assert all(action.get("type") == "select_date" for action in actions)
        elif step == 3:
            assert actions, "Room step should surface selectable options"
            assert all(action.get("type") == "select_room" for action in actions)
        else:
            assert len(actions) <= 1, f"multiple primary CTAs detected: {actions}"
        if actions:
            assert actions[0].get("label"), "CTA should include a human-readable label"
        assert len((draft.get("body_markdown") or "").splitlines()) <= 20


def test_finalize_confirmation_always_autoruns_room_step(tmp_path, monkeypatch):
    step2_state = _mk_state(tmp_path, step=2)
    requirements = {"number_of_participants": 80}
    event_entry = {
        "event_id": "EVT-DET",
        "requirements": requirements,
        "requested_window": {"hash": "old"},
        "thread_state": "Awaiting Client",
        "current_step": 5,
        "caller_step": 5,
    }
    step2_state.event_entry = event_entry
    step2_state.user_info = {
        "participants": 80,
    }

    stub_called = {"value": False}

    def _room_stub(state):
        stub_called["value"] = True
        return GroupResult(action="room_stub", payload={"stub": True}, halt=False)

    monkeypatch.setattr(room_module, "process", _room_stub)

    _finalize_confirmation(step2_state, event_entry, "20.11.2026")

    # Step 2 must always hand off to Step 3 after confirming the date,
    # regardless of any existing caller_step; Step 3 is responsible for
    # deciding whether to skip evaluation and route back.
    assert stub_called["value"], "Step 3 should autorun after date confirmation"
    assert event_entry.get("current_step") == 3
