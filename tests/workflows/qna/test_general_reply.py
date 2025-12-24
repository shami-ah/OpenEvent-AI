from __future__ import annotations

from pathlib import Path

import pytest

import importlib

from backend.workflows.common.types import GroupResult, IncomingMessage, WorkflowState
from backend.workflows.common import general_qna
from backend.workflows.common.general_qna import enrich_general_qna_step2, render_general_qna_reply
from backend.workflows.steps.step2_date_confirmation.trigger.process import _present_general_room_qna

date_process_module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.process")


@pytest.fixture
def state():
    message = IncomingMessage(
        msg_id="msg-structured",
        from_name="Client",
        from_email="client@example.com",
        subject="",
        body="",
        ts=None,
    )
    wf_state = WorkflowState(
        message=message,
        db_path=Path("."),
        db={},
    )
    wf_state.event_entry = {"current_step": 3}
    wf_state.extras["_general_qna_classification"] = {"is_general": True}
    return wf_state


def test_render_general_qna_reply_uses_structured_context(monkeypatch, state):
    extraction_payload = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {
            "date_pattern": "second week of December 2026 around December 10 or 11",
            "n_exact": 22,
            "products": ["Projector & Screen"],
        },
    }
    state.extras["qna_extraction"] = extraction_payload

    result = render_general_qna_reply(state, {"is_general": True})
    assert isinstance(result, GroupResult)
    payload = result.payload
    assert payload["structured_qna"] is True
    effective_d = payload["structured_qna_debug"]["effective"]["D"]
    assert effective_d["source"] == "Q"
    assert effective_d["meta"].get("month_index") == 12
    rooms = payload["qna_select_result"]["db_summary"]["rooms"]
    assert any(row["date"] == "2026-12-10" for row in rooms)
    assert payload["qna_extraction"] == extraction_payload


def test_render_general_qna_reply_handles_unhandled_context(monkeypatch, state):
    extraction_payload = {
        "msg_type": "event",
        "qna_intent": "update_candidate",
        "qna_subtype": "update_candidate",
        "q_values": {"room": "Room B"},
    }
    state.extras["qna_extraction"] = extraction_payload

    result = render_general_qna_reply(state, {"is_general": True})
    assert isinstance(result, GroupResult)
    payload = result.payload
    assert payload["structured_qna"] is False
    assert payload["qna_select_result"]["handled"] is False
    assert payload["structured_qna_debug"]["unresolved"] == ["update_flow"]


def test_present_general_room_qna_generates_february_dates(monkeypatch, state):
    monkeypatch.setattr(date_process_module, "update_event_metadata", lambda *args, **kwargs: None)
    state.event_entry = {
        "event_id": "evt-123",
        "current_step": 2,
        "requirements": {"number_of_participants": 30},
        "qna_cache": {},
    }
    state.message = IncomingMessage(
        msg_id="msg-structured",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Private dinner",
        body="",
        ts=None,
    )
    classification = {"is_general": True}
    extraction_payload = {
        "msg_type": "event",
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "q_values": {
            "date_pattern": "Saturdays in February 2026",
            "n_exact": 30,
            "products": [],
        },
    }
    state.event_entry["qna_cache"] = {
        "extraction": extraction_payload,
        "meta": {"model": "test"},
        "last_message_text": "Private dinner\nWe are thinking Saturdays in February 2026.",
    }

    result = _present_general_room_qna(state, state.event_entry, classification, thread_id=None)
    payload = result.payload
    assert payload["structured_qna"] is True
    assert not payload.get("structured_qna_fallback")
    candidate_dates = payload["candidate_dates"]
    assert candidate_dates
    assert any(date.endswith(".02.2026") for date in candidate_dates)
    actions = payload["actions"]
    assert actions and actions[0]["iso_date"].startswith("2026-02")
    rooms = payload["qna_select_result"]["db_summary"]["rooms"]
    assert any(row["date"] == "2026-02-07" for row in rooms)


def test_present_general_room_qna_uses_cache_when_message_blank(monkeypatch, state):
    monkeypatch.setattr(date_process_module, "update_event_metadata", lambda *args, **kwargs: None)
    state.event_entry = {
        "event_id": "evt-789",
        "current_step": 2,
        "requirements": {"number_of_participants": 30},
        "qna_cache": {
            "extraction": {
                "msg_type": "event",
                "qna_intent": "select_dependent",
                "qna_subtype": "room_list_for_us",
                "q_values": {"date_pattern": "Saturdays in February 2026", "n_exact": 30},
            },
            "meta": {"model": "test"},
            "last_message_text": "We’d like Saturdays in February 2026.",
        },
    }
    state.message = IncomingMessage(
        msg_id="msg-blank",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Private dinner",
        body="",
        ts=None,
    )

    result = _present_general_room_qna(state, state.event_entry, {"is_general": True}, thread_id=None)
    payload = result.payload
    assert payload["structured_qna"] is True
    assert not payload.get("structured_qna_fallback")


def test_enrich_general_qna_step2_room_dates_column(monkeypatch, state):
    monkeypatch.setattr(date_process_module, "update_event_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(date_process_module, "_search_range_availability", lambda *args, **kwargs: [
        {"iso_date": "2026-02-07", "room": "Room A", "status": "Available"},
        {"iso_date": "2026-02-14", "room": "Room B", "status": "Available"},
    ])
    monkeypatch.setattr(date_process_module, "_candidate_dates_for_constraints", lambda *_a, **_k: [
        "2026-02-07",
        "2026-02-14",
    ])

    state.event_entry = {
        "event_id": "evt-room",
        "current_step": 2,
        "thread_state": "Awaiting Client",
    }
    classification = {"is_general": True}
    date_process_module._present_general_room_qna(state, state.event_entry, classification, thread_id="THREAD-ROOM")
    enrich_general_qna_step2(state, classification)
    draft = state.draft_messages[-1]
    body = draft["body_markdown"]
    assert "| Room | Dates | Notes |" in body
    assert draft["table_blocks"][0]["column_order"] == ["room", "dates", "notes"]


def test_enrich_general_qna_step2_menu_table(monkeypatch, state):
    monkeypatch.setattr(
        general_qna,
        "_load_structured_action_payload_for_general_qna",
        lambda _state: {
            "qna_subtype": "product_catalog",
            "extraction": {"q_values": {}},
            "effective": {
                "D": {"value": None, "source": "Q", "meta": {}},
                "N": {"value": 30, "source": "Q", "meta": {}},
                "P": {"value": ["Menu A", "Menu B"], "source": "Q", "meta": {}},
                "R": {"value": None, "source": "UNUSED", "meta": {}},
            },
            "db_summary": {
                "rooms": [],
                "products": [
                    {"product": "Menu A", "rooms": ["Room A"], "available_today": True},
                    {"product": "Menu B", "rooms": [], "available_today": False},
                ],
            },
        },
    )
    state.event_entry = {"event_id": "evt-menu", "current_step": 2}
    state.draft_messages.append({
        "body": "",
        "body_markdown": "",
        "candidate_dates": ["01.02.2026"],
        "range_results": [],
        "subloop": "general_q_a",
        "topic": "general_room_qna",
        "step": 2,
    })
    classification = {"is_general": True}
    enrich_general_qna_step2(state, classification)
    draft = state.draft_messages[-1]
    assert "| Menu | Dates | Notes |" in draft["body_markdown"]
    assert draft["table_blocks"][0]["column_order"] == ["menu", "dates", "notes"]
    assert "01.02.2026" in draft["table_blocks"][0]["rows"][0]["dates"]


def test_enrich_general_qna_step2_room_menu_columns(monkeypatch, state):
    monkeypatch.setattr(
        general_qna,
        "_load_structured_action_payload_for_general_qna",
        lambda _state: {
            "qna_subtype": "room_catalog_with_products",
            "extraction": {"q_values": {}},
            "effective": {
                "D": {"value": None, "source": "Q", "meta": {}},
                "N": {"value": 40, "source": "Q", "meta": {}},
                "P": {"value": ["Menu A"], "source": "Q", "meta": {}},
                "R": {"value": None, "source": "UNUSED", "meta": {}},
            },
            "db_summary": {
                "rooms": [
                    {
                        "room_name": "Room A",
                        "capacity_max": 40,
                        "status": "Available",
                        "products": ["Menu A"],
                    }
                ],
                "products": [],
            },
        },
    )
    state.event_entry = {"event_id": "evt-room-menu", "current_step": 2}
    state.draft_messages.append({
        "body": "",
        "body_markdown": "",
        "candidate_dates": ["01.02.2026"],
        "range_results": [],
        "subloop": "general_q_a",
        "topic": "general_room_qna",
        "step": 2,
    })
    classification = {"is_general": True}
    enrich_general_qna_step2(state, classification)
    draft = state.draft_messages[-1]
    assert "| Room | Menus | Dates | Notes |" in draft["body_markdown"]
    assert draft["table_blocks"][0]["column_order"] == ["room", "menu", "dates", "notes"]
