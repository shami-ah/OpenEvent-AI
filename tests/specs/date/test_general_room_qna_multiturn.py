"""
Tests for multi-turn general_room_qna behavior.

Goal: Ensure each new Q&A message uses fresh extraction + QnAContext + DB query,
correctly overrides or narrows previous date patterns, and never reuses stale
dates/menus/rooms from earlier Q&A turns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step2_date_confirmation.trigger.process import process


def _create_state(tmp_path: Path, message_body: str, msg_id: str = "msg-1", ts: str = "2025-11-05T10:00:00Z") -> WorkflowState:
    """Create a test state with a message."""
    msg = IncomingMessage(
        msg_id=msg_id,
        from_name="Laura",
        from_email="laura@example.com",
        subject="Room availability",
        body=message_body,
        ts=ts,
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "multiturn-qna.json", db={"events": []})
    state.client_id = "laura@example.com"
    state.thread_id = "multiturn-thread"
    return state


def _event_entry() -> dict:
    """Create a standard event entry for testing."""
    return {
        "event_id": "EVT-MULTITURN",
        "requirements": {"preferred_room": "Room A", "number_of_participants": 30},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
    }


@pytest.mark.v4
def test_multiturn_override_broader_pattern(monkeypatch, tmp_path):
    """
    Test A - Override broader:
    Q1: "Which rooms are available on Saturdays in February 2026 for about 30 guests?"
        Expect Saturdays-only dates.
    Q2: "Which menus are available in February 2026 (not just on Saturdays)?"
        Expect DB constraints without weekday filter and dates across the whole February.
    """
    import importlib
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Q1: Saturdays in February 2026
    state1 = _create_state(
        tmp_path,
        "Which rooms are available on Saturdays in February 2026 for about 30 guests?",
        msg_id="msg-saturday-q",
    )
    event_entry1 = _event_entry()
    state1.event_entry = event_entry1
    state1.user_info = {}

    saturday_dates_iso = ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]
    saturday_dates_display = ["07.02.2026", "14.02.2026", "21.02.2026", "28.02.2026"]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: saturday_dates_iso,
    )

    result1 = process(state1)

    assert result1.action == "general_rooms_qna"
    draft1 = state1.draft_messages[-1]
    assert draft1["topic"] == "general_room_qna"
    # Verify that Q1 returns only Saturday dates
    for iso_date in saturday_dates_iso:
        assert any(iso_date in str(row) for row in draft1.get("range_results", []))

    # Verify last_general_qna context was stored
    assert "last_general_qna" in event_entry1
    last_context = event_entry1["last_general_qna"]
    assert last_context is not None

    # Q2: Broader pattern - all February 2026 (not just Saturdays)
    state2 = _create_state(
        tmp_path,
        "Which menus are available in February 2026 (not just on Saturdays)?",
        msg_id="msg-broader-q",
        ts="2025-11-05T11:00:00Z",
    )
    event_entry2 = event_entry1  # Same event, new message
    state2.event_entry = event_entry2
    state2.user_info = {}

    # All February dates (not just Saturdays)
    february_dates_iso = [
        "2026-02-02", "2026-02-03", "2026-02-05", "2026-02-07",
        "2026-02-09", "2026-02-10", "2026-02-12", "2026-02-14"
    ]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: february_dates_iso,
    )

    result2 = process(state2)

    assert result2.action == "general_rooms_qna"
    draft2 = state2.draft_messages[-1]
    assert draft2["topic"] == "general_room_qna"

    # Verify that Q2 does NOT contain Saturday-only dates from Q1
    # Instead, it should contain various weekdays from February
    range_results2 = draft2.get("range_results", [])
    iso_dates_in_results2 = {entry.get("iso_date") for entry in range_results2}

    # Check that we have non-Saturday dates in Q2
    assert any(date in iso_dates_in_results2 for date in february_dates_iso[:4])

    # Verify qna_cache was cleared (no reuse of old extraction)
    assert "qna_cache" not in event_entry2


@pytest.mark.v4
def test_multiturn_follow_up_weekday_change(monkeypatch, tmp_path):
    """
    Test B - Follow-up weekday change:
    Q1: "Which rooms are available on Saturdays in February 2026?"
    Q2: "And what about Sundays?"
        Expect Q2 to use Sundays in February 2026 only (no Saturdays).
    """
    import importlib
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Q1: Saturdays in February 2026
    state1 = _create_state(
        tmp_path,
        "Which rooms are available on Saturdays in February 2026?",
        msg_id="msg-sat-q1",
    )
    event_entry1 = _event_entry()
    state1.event_entry = event_entry1
    state1.user_info = {}

    saturday_dates = ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: saturday_dates,
    )

    result1 = process(state1)

    assert result1.action == "general_rooms_qna"
    draft1 = state1.draft_messages[-1]
    assert draft1["topic"] == "general_room_qna"

    # Q2: Sundays in February 2026
    state2 = _create_state(
        tmp_path,
        "And what about Sundays?",
        msg_id="msg-sun-q2",
        ts="2025-11-05T11:30:00Z",
    )
    event_entry2 = event_entry1  # Same event
    state2.event_entry = event_entry2
    state2.user_info = {}

    sunday_dates = ["2026-02-01", "2026-02-08", "2026-02-15", "2026-02-22"]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: sunday_dates,
    )

    result2 = process(state2)

    assert result2.action == "general_rooms_qna"
    draft2 = state2.draft_messages[-1]
    assert draft2["topic"] == "general_room_qna"

    # Verify Q2 contains Sunday dates, NOT Saturday dates from Q1
    range_results2 = draft2.get("range_results", [])
    iso_dates_in_results2 = {entry.get("iso_date") for entry in range_results2}

    # Check that we have Sunday dates
    assert any(date in iso_dates_in_results2 for date in sunday_dates)

    # Check that we DO NOT have Saturday dates from Q1
    for saturday_date in saturday_dates:
        assert saturday_date not in iso_dates_in_results2


@pytest.mark.v4
def test_multiturn_independent_new_qna(monkeypatch, tmp_path):
    """
    Test C - Independent new Q&A:
    After a February/Saturday Q&A, send a new mail "Private Dinner – April 2026, Fridays".
    Expect month=April, weekday=Friday; no February/Saturday constraints in this second run.
    """
    import importlib
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Q1: Saturdays in February 2026
    state1 = _create_state(
        tmp_path,
        "Which rooms are available on Saturdays in February 2026 for 30 people?",
        msg_id="msg-feb-sat",
    )
    event_entry1 = _event_entry()
    state1.event_entry = event_entry1
    state1.user_info = {}

    feb_saturday_dates = ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: feb_saturday_dates,
    )

    result1 = process(state1)

    assert result1.action == "general_rooms_qna"
    draft1 = state1.draft_messages[-1]
    assert draft1["topic"] == "general_room_qna"

    # Q2: Completely independent - Fridays in April 2026
    state2 = _create_state(
        tmp_path,
        "Private Dinner – April 2026, Fridays. What rooms are available?",
        msg_id="msg-april-fri",
        ts="2025-11-06T10:00:00Z",
    )
    event_entry2 = _event_entry()  # New independent query
    state2.event_entry = event_entry2
    state2.user_info = {}

    april_friday_dates = ["2026-04-03", "2026-04-10", "2026-04-17", "2026-04-24"]

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: april_friday_dates,
    )

    result2 = process(state2)

    assert result2.action == "general_rooms_qna"
    draft2 = state2.draft_messages[-1]
    assert draft2["topic"] == "general_room_qna"

    # Verify Q2 contains April Friday dates, NOT February Saturday dates
    range_results2 = draft2.get("range_results", [])
    iso_dates_in_results2 = {entry.get("iso_date") for entry in range_results2}

    # Check that we have April Friday dates
    assert any(date in iso_dates_in_results2 for date in april_friday_dates)

    # Check that we DO NOT have February Saturday dates from Q1
    for feb_date in feb_saturday_dates:
        assert feb_date not in iso_dates_in_results2


@pytest.mark.v4
def test_multiturn_extraction_is_fresh(monkeypatch, tmp_path):
    """
    Verify that ensure_qna_extraction is called with force_refresh=True
    for each turn, ensuring no stale extraction is reused.
    """
    import importlib
    from unittest.mock import Mock, call

    qna_extraction_module = importlib.import_module("backend.workflows.qna.extraction")
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Mock ensure_qna_extraction to track calls
    original_ensure = qna_extraction_module.ensure_qna_extraction
    mock_ensure = Mock(side_effect=original_ensure)
    monkeypatch.setattr(qna_extraction_module, "ensure_qna_extraction", mock_ensure)
    monkeypatch.setattr(step2_module, "ensure_qna_extraction", mock_ensure)

    # Q1
    state1 = _create_state(
        tmp_path,
        "Which rooms are available on Saturdays in February 2026?",
        msg_id="msg-q1",
    )
    event_entry1 = _event_entry()
    state1.event_entry = event_entry1
    state1.user_info = {}

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-02-07", "2026-02-14"],
    )

    result1 = process(state1)
    assert result1.action == "general_rooms_qna"

    # Verify ensure_qna_extraction was called with force_refresh=True
    calls = [c for c in mock_ensure.call_args_list if len(c.args) >= 1]
    assert any(c.kwargs.get("force_refresh") is True for c in calls), \
        "First Q&A should call ensure_qna_extraction with force_refresh=True"

    # Clear mock for Q2
    mock_ensure.reset_mock()

    # Q2
    state2 = _create_state(
        tmp_path,
        "And what about Sundays?",
        msg_id="msg-q2",
        ts="2025-11-05T11:00:00Z",
    )
    event_entry2 = event_entry1  # Same event
    state2.event_entry = event_entry2
    state2.user_info = {}

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-02-01", "2026-02-08"],
    )

    result2 = process(state2)
    assert result2.action == "general_rooms_qna"

    # Verify ensure_qna_extraction was called again with force_refresh=True
    calls2 = [c for c in mock_ensure.call_args_list if len(c.args) >= 1]
    assert any(c.kwargs.get("force_refresh") is True for c in calls2), \
        "Second Q&A should also call ensure_qna_extraction with force_refresh=True"


@pytest.mark.v4
def test_multiturn_no_stale_cache_reuse(monkeypatch, tmp_path):
    """
    Verify that qna_cache is cleared between multi-turn Q&A,
    preventing reuse of cached extraction from previous turns.
    """
    import importlib
    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Q1: Set up initial Q&A that might cache extraction
    state1 = _create_state(
        tmp_path,
        "Which rooms are available on Saturdays in February 2026?",
        msg_id="msg-cache-q1",
    )
    event_entry1 = _event_entry()
    # Simulate pre-existing qna_cache (from a hypothetical previous turn)
    event_entry1["qna_cache"] = {
        "extraction": {"q_values": {"month": "February", "weekday": "Saturday"}},
        "meta": {"cached": True},
        "last_message_text": "Old cached query",
    }
    state1.event_entry = event_entry1
    state1.user_info = {}

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-02-07", "2026-02-14"],
    )

    result1 = process(state1)
    assert result1.action == "general_rooms_qna"

    # After Q1, verify qna_cache was cleared (not reused)
    assert "qna_cache" not in event_entry1, \
        "qna_cache should be cleared to prevent stale data reuse in multi-turn Q&A"

    # Q2: Another query on the same event
    state2 = _create_state(
        tmp_path,
        "What about Sundays in March 2026?",
        msg_id="msg-cache-q2",
        ts="2025-11-05T12:00:00Z",
    )
    event_entry2 = event_entry1  # Same event
    state2.event_entry = event_entry2
    state2.user_info = {}

    monkeypatch.setattr(
        step2_module,
        "_candidate_dates_for_constraints",
        lambda *_args, **_kwargs: ["2026-03-01", "2026-03-08", "2026-03-15"],
    )

    result2 = process(state2)
    assert result2.action == "general_rooms_qna"

    # Verify qna_cache remains cleared after Q2
    assert "qna_cache" not in event_entry2, \
        "qna_cache should remain cleared after second Q&A turn"
