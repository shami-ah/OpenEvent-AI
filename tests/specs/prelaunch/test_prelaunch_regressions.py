from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import pytest

from detection.unified import run_unified_detection
from domain import IntentLabel
from llm.provider_config import validate_hybrid_mode
from workflows.common.gatekeeper import explain_step7_gate
from workflows.common.types import IncomingMessage, WorkflowState
from workflows.planner import maybe_run_smart_shortcuts
from workflows.runtime.pre_route import check_out_of_context
from workflows.steps.step1_intake.trigger import step1_handler as step1_intake
from workflows.steps.step5_negotiation.trigger.step5_handler import _detect_structural_change
from workflows.steps.step6_transition import process as step6_process
from workflows.steps.step7_confirmation.trigger.classification import classify_message
from workflows.steps.step7_confirmation.trigger.step7_handler import process as step7_process
from workflow_email import _finalize_output


def test_step7_yes_should_be_confirm() -> None:
    """Fixed: Added 'yes' to CONFIRM_KEYWORDS (Jan 2026)."""
    assert classify_message("Yes", {"deposit_state": {"status": "idle"}}) == "confirm"


def test_step7_deposit_request_should_emit_action() -> None:
    """Fixed: HIL routing extended to Step 7 with CONFIRMATION_MESSAGE task type (Jan 2026)."""
    os.environ.setdefault("AGENT_MODE", "stub")
    msg = IncomingMessage(
        msg_id="m",
        from_name="Client",
        from_email="client@example.com",
        subject="Re: booking",
        body="Confirm please",
        ts="2026-01-01T00:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=Path("dummy.json"), db={"events": [], "tasks": []})
    state.confidence = 0.99
    state.event_entry = {
        "event_id": "EVT-7",
        "current_step": 7,
        "thread_state": "In Progress",
        "chosen_date": "12.05.2026",
        "locked_room_id": "Room A",
        "date_confirmed": True,
        "event_data": {"Company": "ACME", "Billing Address": "X"},
        "offer_status": "Accepted",
        "offer_gate_ready": True,
        "deposit_state": {"required": True, "status": "requested", "due_amount": 100.0},
        "deposit_info": {"deposit_required": True, "deposit_paid": False, "deposit_amount": 100.0},
    }
    result = step7_process(state)
    out = _finalize_output(result, state)
    assert out.get("actions"), out


def test_step6_transition_blocked_should_emit_action() -> None:
    """Fixed: HIL routing extended to Step 6 with TRANSITION_MESSAGE task type (Jan 2026)."""
    os.environ.setdefault("AGENT_MODE", "stub")
    msg = IncomingMessage(
        msg_id="m",
        from_name="Client",
        from_email="client@example.com",
        subject="Re: booking",
        body="Ok",
        ts="2026-01-01T00:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=Path("dummy.json"), db={"events": [], "tasks": []})
    state.confidence = 0.99
    state.event_entry = {
        "event_id": "EVT-6",
        "current_step": 6,
        "thread_state": "Awaiting Client",
        "chosen_date": "12.05.2026",
        "locked_room_id": "Room A",
        "requirements_hash": "h",
        "room_eval_hash": "h",
        "offer_status": "Accepted",
        "deposit_state": {"required": True, "status": "requested", "due_amount": 100.0},
    }
    result = step6_process(state)
    out = _finalize_output(result, state)
    assert out.get("actions"), out


def test_unified_detection_should_fallback_when_gemini_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unified detection now handles missing GOOGLE_API_KEY gracefully."""
    monkeypatch.setenv("INTENT_PROVIDER", "gemini")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Expectation (desired): no exception, fallback to another provider.
    run_unified_detection("Hello, do you have parking?", current_step=2)


def test_out_of_context_should_not_drop_message_with_billing(tmp_path: Path) -> None:
    """Fixed: OOC bypassed when capturable data (billing) exists (Jan 2026)."""
    state = WorkflowState(
        message=IncomingMessage(
            msg_id="m",
            from_name="Client",
            from_email="client@example.com",
            subject="Re: booking",
            body="We confirm the date. Billing address: ACME, ...",
            ts="2026-01-01T00:00:00Z",
        ),
        db_path=tmp_path / "db.json",
        db={"events": []},
    )
    state.event_entry = {"event_id": "EVT", "current_step": 5}
    state.user_info = {"billing_address": "ACME, Bahnhofstrasse 1, 8001 Zurich"}

    class Unified:
        intent = "confirm_date"

    def finalize_fn(result, _state, _path, _lock_path):
        return result.merged()

    # Expectation (desired): should continue processing, not silently ignore.
    assert (
        check_out_of_context(
            state,
            Unified(),  # type: ignore[arg-type]
            tmp_path / "db.json",
            tmp_path / ".db.lock",
            finalize_fn,
        )
        is None
    )


def test_step5_quoted_history_date_should_not_trigger_change() -> None:
    """Fixed: _strip_quoted_lines now removes attribution headers like 'On ... wrote:' (Jan 2026)."""
    event_entry = {
        "chosen_date": "12.05.2026",
        "locked_room_id": "Room A",
        "requirements": {"number_of_participants": 30},
    }
    message_text = (
        "Thanks!\n\n"
        "On Tue, 14.02.2026 you wrote:\n"
        "> Event Date: 14.02.2026\n"
        "> Room A\n"
    )
    assert _detect_structural_change({}, event_entry, message_text) is None


def test_shortcuts_should_not_reconfirm_date_when_already_confirmed() -> None:
    """Fixed: Reconfirmation guard in date_handler.py prevents this (Jan 2026)."""
    os.environ.setdefault("AGENT_MODE", "stub")
    msg = IncomingMessage(
        msg_id="m",
        from_name="Client",
        from_email="client@example.com",
        subject="Re: booking",
        body="Just confirming again: 12.05.2026 14:00–16:00.",
        ts="2026-01-01T00:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=Path("dummy.json"), db={"events": [], "tasks": []})
    state.confidence = 0.99
    state.event_entry = {
        "event_id": "EVT-SHORTCUT",
        "current_step": 5,
        "thread_state": "In Progress",
        "chosen_date": "12.05.2026",
        "date_confirmed": True,
        "requested_window": {"start": "2026-05-12T14:00:00Z", "end": "2026-05-12T16:00:00Z", "tz": "Europe/Zurich"},
        "locked_room_id": "Room A",
        "requirements": {"number_of_participants": 30},
        "requirements_hash": "h",
        "room_eval_hash": "h",
    }
    state.user_info = {
        "date": "2026-05-12",
        "event_date": "12.05.2026",
        "start_time": "14:00",
        "end_time": "16:00",
    }

    _ = maybe_run_smart_shortcuts(state)
    assert state.event_entry.get("current_step") == 5, state.event_entry


def test_step7_deposit_paid_with_payment_date_should_not_detour_to_step2() -> None:
    """Fixed: _detect_structural_change skips date check for deposit payment context (Jan 2026)."""
    os.environ.setdefault("AGENT_MODE", "stub")
    msg = IncomingMessage(
        msg_id="m",
        from_name="Client",
        from_email="client@example.com",
        subject="Re: booking",
        body="We paid the deposit on 02.01.2026.",
        ts="2026-01-02T10:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=Path("dummy.json"), db={"events": [], "tasks": []})
    state.confidence = 0.99
    state.user_info = {"date": "2026-01-02", "event_date": "02.01.2026"}
    state.event_entry = {
        "event_id": "EVT-7-PAY",
        "current_step": 7,
        "thread_state": "Awaiting Client",
        "chosen_date": "12.05.2026",
        "locked_room_id": "Room A",
        "date_confirmed": True,
        "offer_status": "Accepted",
        "offer_gate_ready": True,
        "event_data": {"Company": "ACME", "Billing Address": "X"},
        "deposit_state": {"required": True, "status": "requested", "due_amount": 100.0},
        "deposit_info": {"deposit_required": True, "deposit_paid": False, "deposit_amount": 100.0},
    }

    result = step7_process(state)
    assert result.action != "structural_change_detour", result.merged()


def test_step1_confirm_date_should_not_trigger_offer_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed: looks_like_offer_acceptance now excludes date confirmations (Jan 2026)."""
    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setattr(step1_intake, "classify_intent", lambda _payload: (IntentLabel.EVENT_REQUEST, 0.99))
    monkeypatch.setattr(
        step1_intake,
        "extract_user_information",
        lambda _payload: {"event_date": "12.05.2026", "date": "2026-05-12"},
    )
    msg = IncomingMessage(
        msg_id="m",
        from_name="Client",
        from_email="client@example.com",
        subject="Re: booking",
        body="We confirm the date 12.05.2026.",
        ts="2026-01-01T00:00:00Z",
    )
    state = WorkflowState(
        message=msg,
        db_path=Path("dummy.json"),
        db={
            "events": [
                {
                    "event_id": "EVT-STEP2",
                    "event_data": {"Email": "client@example.com"},
                    "thread_state": "Awaiting Client",
                    "current_step": 2,
                    "chosen_date": None,
                    "date_confirmed": False,
                }
            ],
            "clients": {},
            "tasks": [],
        },
    )
    _ = step1_intake.process(state)
    assert state.user_info.get("hil_approve_step") is None, state.user_info


def test_validate_hybrid_mode_should_fail_when_required_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed: validate_hybrid_mode() now checks API key existence (Jan 2026)."""
    monkeypatch.setenv("INTENT_PROVIDER", "gemini")
    monkeypatch.setenv("ENTITY_PROVIDER", "gemini")
    monkeypatch.setenv("VERBALIZER_PROVIDER", "openai")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    is_valid, _msg, _settings = validate_hybrid_mode(raise_on_failure=False, is_production=False)
    assert is_valid is False


def test_out_of_context_should_still_persist_step1_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed: OOC handler now tags msg_id before returning (Jan 2026)."""
    from workflow_email import process_msg
    from workflows.io import database as db_io
    from detection.unified import UnifiedDetectionResult

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("DETECTION_MODE", "unified")

    # Force the unified detector to always return an out-of-context intent.
    def fake_unified(*_args, **_kwargs):
        return UnifiedDetectionResult(intent="confirm_date")

    monkeypatch.setattr("backend.workflows.runtime.pre_route.run_unified_detection", fake_unified)

    db_path = tmp_path / "db.json"
    db = db_io.get_default_db()
    db["events"].append(
        {
            "event_id": "EVT-OOC",
            "event_data": {"Email": "client@example.com"},
            "current_step": 5,
            "thread_state": "In Progress",
            "chosen_date": "12.05.2026",
            "date_confirmed": True,
            "locked_room_id": "Room A",
            "requirements": {"number_of_participants": 30},
        }
    )
    db_io.save_db(db, db_path, lock_path=db_io.lock_path_for(db_path))

    _ = process_msg(
        {
            "msg_id": "m-out-of-context",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Re: booking",
            "body": "I confirm the date.",
            "ts": "2026-01-01T00:00:00Z",
        },
        db_path=db_path,
    )

    persisted = db_io.load_db(db_path, lock_path=db_io.lock_path_for(db_path))
    event_entry = persisted["events"][0]
    assert "m-out-of-context" in (event_entry.get("msgs") or []), event_entry


def test_step7_gatekeeper_should_treat_captured_billing_as_ready() -> None:
    """Fixed: Gatekeeper now checks captured.billing as fallback for event_data (Jan 2026)."""
    event_entry = {
        "date_confirmed": True,
        "chosen_date": "12.05.2026",
        "locked_room_id": "Room A",
        "offer_status": "Accepted",
        "offer_gate_ready": True,
        "event_data": {},  # missing canonical fields
        "captured": {
            "billing": {
                "company": "ACME AG",
                "address": "ACME AG, Bahnhofstrasse 1, 8001 Zurich, Switzerland",
            }
        },
    }
    assert explain_step7_gate(event_entry)["ready"] is True


def test_concurrent_process_msg_should_not_lose_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed: process_msg now holds DB lock for entire read-modify-write cycle (Jan 2026).

    Previously, concurrent process_msg calls could lose updates because the lock was
    only held during individual load/save operations (last writer wins). Now the lock
    is held for the entire process_msg duration, serializing concurrent access.
    """
    from workflow_email import process_msg
    from workflows.io import database as db_io

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("DETECTION_MODE", "legacy")

    db_path = tmp_path / "db.json"
    db = db_io.get_default_db()
    db["events"].append(
        {
            "event_id": "EVT-RACE",
            "event_data": {"Email": "client@example.com"},
            "current_step": 2,
            "thread_state": "Awaiting Client",
        }
    )
    db_io.save_db(db, db_path, lock_path=db_io.lock_path_for(db_path))

    def worker(msg_id: str) -> None:
        # Use different body text to avoid duplicate message detection
        process_msg(
            {
                "msg_id": msg_id,
                "from_name": "Client",
                "from_email": "client@example.com",
                "subject": "Re: booking",
                "body": f"Just checking in for message {msg_id}.",  # Unique per message
                "ts": "2026-01-01T00:00:00Z",
            },
            db_path=db_path,
        )

    # Run two concurrent workers - with proper locking, both updates should persist
    t1 = threading.Thread(target=worker, args=("m1",))
    t2 = threading.Thread(target=worker, args=("m2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    persisted = db_io.load_db(db_path, lock_path=db_io.lock_path_for(db_path))
    msgs = persisted["events"][0].get("msgs") or []
    assert set(msgs) == {"m1", "m2"}, f"Expected both messages to be persisted, got: {msgs}"


def test_step1_can_overwrite_event_date_from_unanchored_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fixed: Guards and step handlers now skip date change detection for deposit payment context (Jan 2026)."""
    from workflow_email import process_msg
    from workflows.io import database as db_io
    from workflows.common.requirements import requirements_hash

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("DETECTION_MODE", "legacy")
    monkeypatch.setattr(step1_intake, "classify_intent", lambda _payload: (IntentLabel.EVENT_REQUEST, 0.99))
    monkeypatch.setattr(
        step1_intake,
        "extract_user_information",
        lambda _payload: {"event_date": "02.01.2026", "date": "2026-01-02"},
    )

    db_path = tmp_path / "db.json"
    db = db_io.get_default_db()
    req = {
        "number_of_participants": 30,
        "event_duration": {"start": "14:00", "end": "16:00"},
        "seating_layout": None,
        "special_requirements": None,
        "preferred_room": None,
    }
    h = requirements_hash(req)
    db["events"].append(
        {
            "event_id": "EVT-STEP7",
            "event_data": {"Email": "client@example.com", "Company": "ACME", "Billing Address": "X"},
            "current_step": 7,
            "thread_state": "Awaiting Client",
            "chosen_date": "12.05.2026",
            "date_confirmed": True,
            "locked_room_id": "Room A",
            "requirements": req,
            "requirements_hash": h,
            "room_eval_hash": h,
            "offer_status": "Accepted",
            "offer_gate_ready": True,
            "deposit_state": {"required": True, "status": "requested", "due_amount": 100.0},
        }
    )
    db_io.save_db(db, db_path, lock_path=db_io.lock_path_for(db_path))

    _ = process_msg(
        {
            "msg_id": "m-pay",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Re: deposit",
            "body": "We paid the deposit on 02.01.2026. Please confirm receipt.",
            "ts": "2026-01-02T10:00:00Z",
        },
        db_path=db_path,
    )

    persisted = db_io.load_db(db_path, lock_path=db_io.lock_path_for(db_path))
    evt = persisted["events"][0]
    assert evt.get("chosen_date") == "12.05.2026", evt


# =============================================================================
# Multilingual Confirmation Detection (Jan 2026)
# =============================================================================

@pytest.mark.parametrize("text,expected", [
    # English
    ("sounds good", True),
    ("looks good", True),
    ("all good", True),
    ("proceed", True),
    ("let's do it", True),
    ("confirm", True),
    # German
    ("einverstanden", True),
    ("perfekt", True),
    ("machen wir so", True),
    ("passt", True),
    # French
    ("d'accord", True),
    ("parfait", True),
    ("c'est bon", True),
    ("allons-y", True),
    # Italian
    ("va bene", True),
    ("perfetto", True),
    ("procediamo", True),
    ("d'accordo", True),
    # Spanish
    ("perfecto", True),
    ("de acuerdo", True),
    ("adelante", True),
    ("vale", True),
    # Should NOT match (questions)
    ("What date?", False),
    ("Do you have availability?", False),
    ("Can we change the room?", False),
    # Should NOT match (date confirmations - handled separately)
    ("We confirm the date", False),
    ("I confirm the day", False),
    ("Confirmed the time", False),
    # Should NOT match (too long)
    ("This is a very long message that goes on and on about many different topics and contains lots of words " * 3, False),
])
def test_multilingual_acceptance_detection(text: str, expected: bool) -> None:
    """Multilingual confirmation detection supports EN, DE, FR, IT, ES (Jan 2026)."""
    from workflows.steps.step1_intake.trigger.gate_confirmation import looks_like_offer_acceptance
    assert looks_like_offer_acceptance(text) == expected, f"Failed for: {text!r}"
