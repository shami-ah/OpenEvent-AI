from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime
import logging

from backend.domain import TaskStatus, TaskType

from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.common.types import GroupResult
from backend.workflows.groups import intake, date_confirmation, room_availability
from backend.workflows.groups.offer.trigger import process as process_offer
from backend.workflows.groups.negotiation_close import process as process_negotiation
from backend.workflows.groups.transition_checkpoint import process as process_transition
from backend.workflows.groups.event_confirmation.trigger import process as process_confirmation
from backend.workflows.io import database as db_io
from backend.workflows.io.database import update_event_metadata
from backend.workflows.io import tasks as task_io
from backend.workflows.io.integration.config import is_hil_all_replies_enabled
from backend.workflows.llm import adapter as llm_adapter
from backend.workflows.planner import maybe_run_smart_shortcuts
from backend.workflows.nlu import (
    detect_general_room_query,
    empty_general_qna_detection,
    quick_general_qna_scan,
)
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.utils.profiler import profile_step
from backend.workflow.state import stage_payload, WorkflowStep, write_stage
from backend.debug.lifecycle import close_if_ended
from backend.debug.settings import is_trace_enabled
from backend.debug.trace import set_hil_open
from backend.workflow.guards import evaluate as evaluate_guards
from backend.debug.state_store import STATE_STORE

logger = logging.getLogger(__name__)
WF_DEBUG = os.getenv("WF_DEBUG_STATE") == "1"

_ENTITY_LABELS = {
    "client": "Client",
    "assistant": "Agent",
    "agent": "Agent",
    "trigger": "Trigger",
    "system": "System",
    "qa": "Q&A",
    "q&a": "Q&A",
}


def _debug_state(stage: str, state: WorkflowState, extra: Optional[Dict[str, Any]] = None) -> None:
    debug_trace_enabled = is_trace_enabled()
    if not WF_DEBUG and not debug_trace_enabled:
        return

    event_entry = state.event_entry or {}
    requirements = event_entry.get("requirements") or {}
    shortcuts = event_entry.get("shortcuts") or {}
    info = {
        "stage": stage,
        "step": event_entry.get("current_step"),
        "caller": event_entry.get("caller_step"),
        "thread": event_entry.get("thread_state"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "chosen_date": event_entry.get("chosen_date"),
        "participants": requirements.get("number_of_participants") or requirements.get("participants"),
        "capacity_shortcut": shortcuts.get("capacity_ok"),
        "vague_month": event_entry.get("vague_month"),
        "vague_weekday": event_entry.get("vague_weekday"),
        "vague_time": event_entry.get("vague_time_of_day"),
    }
    general_flag = state.extras.get("general_qna_detected")
    if general_flag is not None:
        info["general_qna"] = bool(general_flag)
    if extra and "entity" in extra:
        entity_raw = extra["entity"]
        if isinstance(entity_raw, str):
            info.setdefault("entity", _ENTITY_LABELS.get(entity_raw.lower(), entity_raw))
        else:
            info.setdefault("entity", entity_raw)
    elif stage == "init":
        info.setdefault("entity", "Client")
    if extra:
        info.update(extra)
    if WF_DEBUG:
        serialized = " ".join(f"{key}={value}" for key, value in info.items())
        print(f"[WF DEBUG][state] {serialized}")

    if not debug_trace_enabled:
        return

    thread_id = _thread_identifier(state)
    snapshot = dict(info)
    snapshot.update(
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "offer_id": event_entry.get("offer_id"),
            "locked_room_id": event_entry.get("locked_room_id"),
             "locked_room_status": event_entry.get("selected_status") or (event_entry.get("room_pending_decision") or {}).get("selected_status"),
            "wish_products": event_entry.get("wish_products"),
            "thread_state": state.thread_state,
            "caller_step": event_entry.get("caller_step"),
            "offer_status": event_entry.get("offer_status"),
            "event_data": event_entry.get("event_data"),
            "billing_details": event_entry.get("billing_details"),
        }
    )
    subloop = state.extras.pop("subloop", None)
    if subloop:
        snapshot["subloop"] = subloop
    from backend.debug.hooks import trace_state, set_subloop, clear_subloop  # pylint: disable=import-outside-toplevel
    from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

    pending_hil = (event_entry or {}).get("pending_hil_requests") or []
    snapshot["hil_open"] = bool(pending_hil)
    if subloop:
        set_subloop(thread_id, subloop)
    trace_state(thread_id, _snapshot_step_name(event_entry), snapshot)
    if subloop:
        clear_subloop(thread_id)
    existing_state = STATE_STORE.get(thread_id)
    merged_state = dict(existing_state)
    merged_state.update(snapshot)
    if "flags" in existing_state:
        merged_state.setdefault("flags", existing_state.get("flags", {}))
    STATE_STORE.update(thread_id, merged_state)
    close_if_ended(thread_id, snapshot)


_TRACE_STEP_NAMES = {
    1: "Step1_Intake",
    2: "Step2_Date",
    3: "Step3_Room",
    4: "Step4_Offer",
    5: "Step5_Negotiation",
    6: "Step6_Transition",
    7: "Step7_Confirmation",
}


def _snapshot_step_name(event_entry: Optional[Dict[str, Any]]) -> str:
    if not event_entry:
        return "intake"
    raw = event_entry.get("current_step")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return "intake"
    return _TRACE_STEP_NAMES.get(value, "intake")


def _thread_identifier(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


DB_PATH = Path(__file__).with_name("events_database.json")
LOCK_PATH = Path(__file__).with_name(".events_db.lock")

enqueue_task = task_io.enqueue_task
update_task_status = task_io.update_task_status
list_pending_tasks = task_io.list_pending_tasks
get_default_db = db_io.get_default_db


def _same_default(path: Path) -> bool:
    """[Condition] Detect whether a path resolves to the default workflow database."""

    try:
        return path.resolve() == DB_PATH.resolve()
    except FileNotFoundError:
        return path == DB_PATH


def _resolve_lock_path(path: Path) -> Path:
    """[OpenEvent Database] Determine the lockfile used for a database path."""

    if _same_default(path):
        return LOCK_PATH
    return db_io.lock_path_for(path)


def _ensure_general_qna_classification(state: WorkflowState, message_text: str) -> Dict[str, Any]:
    """Ensure the general Q&A classification is available on the workflow state."""

    scan = state.extras.get("general_qna_scan")
    if not scan:
        scan = quick_general_qna_scan(message_text)
        state.extras["general_qna_scan"] = scan

    ensure_qna_extraction(state, message_text, scan)
    extraction_payload = state.extras.get("qna_extraction")
    if extraction_payload:
        event_entry = state.event_entry or {}
        cache = event_entry.setdefault("qna_cache", {})
        cache["extraction"] = extraction_payload
        cache["meta"] = state.extras.get("qna_extraction_meta")
        cache["last_message_text"] = message_text
        state.event_entry = event_entry
        state.extras["persist"] = True

    classification = state.extras.get("_general_qna_classification")
    if classification:
        state.extras["general_qna_detected"] = bool(classification.get("is_general"))
        return classification

    needs_detailed = bool(
        scan.get("likely_general")
        or (scan.get("heuristics") or {}).get("borderline")
    )
    if needs_detailed:
        classification = detect_general_room_query(message_text, state)
    else:
        classification = empty_general_qna_detection()
        classification["heuristics"] = scan.get("heuristics", classification["heuristics"])
        classification["parsed"] = scan.get("parsed", classification["parsed"])
        classification["constraints"] = {
            "vague_month": classification["parsed"].get("vague_month"),
            "weekday": classification["parsed"].get("weekday"),
            "time_of_day": classification["parsed"].get("time_of_day"),
            "pax": classification["parsed"].get("pax"),
        }
        classification["llm_called"] = False
        classification["cached"] = False

    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    return classification


def load_db(path: Path = DB_PATH) -> Dict[str, Any]:
    """[OpenEvent Database] Load the workflow database with locking safeguards."""

    path = Path(path)
    lock_path = _resolve_lock_path(path)
    return db_io.load_db(path, lock_path=lock_path)


def save_db(db: Dict[str, Any], path: Path = DB_PATH) -> None:
    """[OpenEvent Database] Persist the workflow database atomically."""

    path = Path(path)
    lock_path = _resolve_lock_path(path)
    db_io.save_db(db, path, lock_path=lock_path)


def _persist_if_needed(state: WorkflowState, path: Path, lock_path: Path) -> None:
    """[OpenEvent Database] Flag persistence requests so we can coalesce writes."""

    if state.extras.pop("persist", False):
        state.extras["_pending_save"] = True


def _flush_pending_save(state: WorkflowState, path: Path, lock_path: Path) -> None:
    """[OpenEvent Database] Flush debounced writes at the end of the turn."""

    if state.extras.pop("_pending_save", False):
        db_io.save_db(state.db, path, lock_path=lock_path)


def _flush_and_finalize(result: GroupResult, state: WorkflowState, path: Path, lock_path: Path) -> Dict[str, Any]:
    """Persist pending state and normalise the outgoing payload."""

    output = _finalize_output(result, state)
    _flush_pending_save(state, path, lock_path)
    return output


def _hil_signature(draft: Dict[str, Any], event_entry: Dict[str, Any]) -> str:
    base = {
        "step": draft.get("step"),
        "topic": draft.get("topic"),
        "caller": event_entry.get("caller_step"),
        "requirements_hash": event_entry.get("requirements_hash"),
        "room_eval_hash": event_entry.get("room_eval_hash"),
        "body": draft.get("body"),
    }
    payload = json.dumps(base, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _enqueue_hil_tasks(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    pending_records = event_entry.setdefault("pending_hil_requests", [])
    seen_signatures = {entry.get("signature") for entry in pending_records if entry.get("signature")}
    thread_id = _thread_identifier(state)

    for draft in state.draft_messages:
        if draft.get("requires_approval") is False:
            continue
        signature = _hil_signature(draft, event_entry)
        if signature in seen_signatures:
            continue

        step_id = draft.get("step")
        try:
            step_num = int(step_id)
        except (TypeError, ValueError):
            continue
        if step_num not in {2, 3, 4, 5}:
            continue
        # Drop older pending requests for the same step to avoid duplicate reviews.
        stale_requests = [entry for entry in pending_records if entry.get("step") == step_num]
        if stale_requests:
            for stale in stale_requests:
                task_id = stale.get("task_id")
                if task_id:
                    try:
                        update_task_status(state.db, task_id, TaskStatus.DONE)
                    except Exception:
                        pass
                try:
                    pending_records.remove(stale)
                except ValueError:
                    pass
            state.extras["persist"] = True
        if step_num == 5:
            earlier_steps = [entry for entry in pending_records if (entry.get("step") or 0) < 5]
            for stale in earlier_steps:
                task_id = stale.get("task_id")
                if task_id:
                    try:
                        update_task_status(state.db, task_id, TaskStatus.DONE)
                    except Exception:
                        pass
                try:
                    pending_records.remove(stale)
                except ValueError:
                    pass
            if earlier_steps:
                state.extras["persist"] = True
        if step_num == 4:
            task_type = TaskType.OFFER_MESSAGE
        elif step_num == 5:
            task_type = TaskType.OFFER_MESSAGE
        elif step_num == 3:
            task_type = TaskType.ROOM_AVAILABILITY_MESSAGE
        elif step_num == 2:
            task_type = TaskType.DATE_CONFIRMATION_MESSAGE
        else:
            task_type = TaskType.MANUAL_REVIEW

        task_payload = {
            "step_id": step_num,
            "intent": state.intent.value if state.intent else None,
            "event_id": event_entry.get("event_id"),
            "draft_msg": draft.get("body"),
            "language": (state.user_info or {}).get("language"),
            "caller_step": event_entry.get("caller_step"),
            "requirements_hash": event_entry.get("requirements_hash"),
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "thread_id": thread_id,
        }
        hil_reason = draft.get("hil_reason")
        if hil_reason:
            task_payload["reason"] = hil_reason

        client_id = state.client_id or (state.message.from_email or "unknown@example.com").lower()
        task_id = enqueue_task(
            state.db,
            task_type,
            client_id,
            event_entry.get("event_id"),
            task_payload,
        )
        pending_records.append(
            {
                "task_id": task_id,
                "signature": signature,
                "step": step_num,
                "draft": dict(draft),
                "thread_id": thread_id,
            }
        )
        seen_signatures.add(signature)
        state.extras["persist"] = True

    set_hil_open(thread_id, bool(pending_records))


def _hil_action_type_for_step(step_id: Optional[int]) -> Optional[str]:
    if step_id == 2:
        return "ask_for_date_enqueued"
    if step_id == 3:
        return "room_options_enqueued"
    if step_id == 4:
        return "offer_enqueued"
    if step_id == 5:
        return "negotiation_enqueued"
    return None


def _compose_hil_decision_reply(decision: str, manager_notes: Optional[str] = None) -> str:
    normalized = (decision or "").lower()
    approved = normalized == "approve"
    decision_line = "Manager decision: Approved" if approved else "Manager decision: Declined"
    note_text = (manager_notes or "").strip()
    next_line = (
        "Next step: Let's continue with site visit bookings. Do you have any preferred dates or times?"
        if approved
        else "Next step: I'll revise the offer with this feedback and share an updated proposal."
    )
    sections = [decision_line]
    if note_text:
        sections.append(f"Manager note: {note_text}")
    sections.append(next_line)
    return "\n\n".join(section for section in sections if section)


def approve_task_and_send(
    task_id: str,
    db_path: Path = DB_PATH,
    *,
    manager_notes: Optional[str] = None,
    edited_message: Optional[str] = None,
) -> Dict[str, Any]:
    """[OpenEvent Action] Approve a pending HIL task and emit the send_reply payload used in tests.

    Args:
        task_id: The HIL task ID to approve
        db_path: Path to the database file
        manager_notes: Optional notes from the manager (appended to message)
        edited_message: Optional edited message text (replaces original draft when provided)
    """

    path = Path(db_path)
    lock_path = _resolve_lock_path(path)
    db = db_io.load_db(path, lock_path=lock_path)
    update_task_status(db, task_id, TaskStatus.APPROVED)

    # First, check if this is an AI Reply Approval task (these are NOT in pending_hil_requests)
    task_record = None
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            task_record = task
            break

    # Handle AI Reply Approval tasks separately
    if task_record and task_record.get("type") == TaskType.AI_REPLY_APPROVAL.value:
        payload = task_record.get("payload") or {}
        event_id = payload.get("event_id")
        thread_id = payload.get("thread_id")
        draft_body = payload.get("draft_body", "")
        step_id = payload.get("step_id")

        # Use edited message if provided, otherwise use original draft
        body_text = edited_message.strip() if edited_message else draft_body

        # Append manager notes if provided
        note_text = (manager_notes or "").strip()
        if note_text and body_text:
            body_text = f"{body_text.rstrip()}\n\nManager note:\n{note_text}"

        # Find the event for context (optional)
        target_event = None
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                target_event = event
                break

        # Update hil_history on the event if found
        if target_event:
            target_event.setdefault("hil_history", []).append(
                {
                    "task_id": task_id,
                    "approved_at": datetime.utcnow().isoformat() + "Z",
                    "notes": manager_notes,
                    "step": step_id,
                    "decision": "approved",
                    "task_type": "ai_reply_approval",
                    "edited": bool(edited_message),
                }
            )
            set_hil_open(thread_id, False)

        db_io.save_db(db, path, lock_path=lock_path)

        draft = {
            "body": body_text,
            "body_markdown": body_text,
            "headers": [],
            "edited_by_manager": bool(edited_message),
        }
        assistant_draft = {"headers": [], "body": body_text, "body_markdown": body_text}

        return {
            "action": "send_reply",
            "event_id": event_id,
            "thread_state": target_event.get("thread_state") if target_event else None,
            "draft": draft,
            "res": {
                "assistant_draft": assistant_draft,
                "assistant_draft_text": body_text,
            },
            "actions": [{"type": "send_reply"}],
            "thread_id": thread_id,
        }

    # Original logic for step-specific HIL tasks (stored in pending_hil_requests)
    target_event = None
    target_request: Optional[Dict[str, Any]] = None
    for event in db.get("events", []):
        pending = event.get("pending_hil_requests") or []
        for request in pending:
            if request.get("task_id") == task_id:
                target_event = event
                target_request = request
                pending.remove(request)
                break
        if target_event:
            break

    if not target_event or not target_request:
        raise ValueError(f"Task {task_id} not found in pending approvals.")

    thread_id = target_request.get("thread_id") or target_event.get("thread_id")

    # Stamp HIL history for auditing.
    target_event.setdefault("hil_history", []).append(
        {
            "task_id": task_id,
            "approved_at": datetime.utcnow().isoformat() + "Z",
            "notes": manager_notes,
            "step": target_request.get("step"),
            "decision": "approved",
        }
    )
    set_hil_open(thread_id, bool(target_event.get("pending_hil_requests") or []))

    step_num = target_request.get("step")
    if isinstance(step_num, int):
        try:
            current_step_raw = target_event.get("current_step")
            try:
                current_step_int = int(current_step_raw) if current_step_raw is not None else None
            except (TypeError, ValueError):
                current_step_int = None
            effective_step = max(step_num, current_step_int) if current_step_int else step_num
            workflow_step = WorkflowStep(f"step_{effective_step}")
            write_stage(target_event, current_step=workflow_step)
            update_event_metadata(target_event, current_step=effective_step)
        except ValueError:
            pass

    # If this approval is for a Step 4 offer with deposit already paid, continue to site visit
    if step_num == 4:
        deposit_info = target_event.get("deposit_info") or {}
        offer_accepted = target_event.get("offer_accepted", False)
        deposit_required = deposit_info.get("deposit_required", False)
        deposit_paid = deposit_info.get("deposit_paid", False)

        # If offer was accepted and deposit is paid (or not required), continue workflow
        if offer_accepted and (not deposit_required or deposit_paid):
            from backend.workflows.common.types import IncomingMessage, WorkflowState
            from backend.workflows.groups import negotiation_close as negotiation_group
            from backend.workflows.groups.transition_checkpoint import process as process_transition

            print(f"[HIL] Step 4 offer approved with deposit paid, continuing to site visit")

            hil_message = IncomingMessage.from_dict(
                {
                    "msg_id": f"hil-approve-{task_id}",
                    "from_email": target_event.get("event_data", {}).get("Email"),
                    "subject": "HIL approval",
                    "body": manager_notes or "Approved",
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
            )
            hil_state = WorkflowState(message=hil_message, db_path=path, db=db)
            hil_state.client_id = (target_event.get("event_data", {}).get("Email") or "").lower()
            hil_state.event_entry = target_event
            hil_state.current_step = 5
            hil_state.user_info = {"hil_approve_step": 5, "hil_decision": "approve"}
            hil_state.thread_state = target_event.get("thread_state")

            # Set pending decision so negotiation handler can process it
            if not target_event.get("negotiation_pending_decision"):
                target_event["negotiation_pending_decision"] = {
                    "type": "accept",
                    "offer_id": target_event.get("current_offer_id"),
                    "created_at": datetime.utcnow().isoformat() + "Z",
                }

            decision_result = negotiation_group._apply_hil_negotiation_decision(hil_state, target_event, "approve")  # type: ignore[attr-defined]
            if not decision_result.halt and (target_event.get("current_step") == 6):
                process_transition(hil_state)

            # Set site_visit_state to "proposed" so client's date preference is handled correctly
            target_event.setdefault("site_visit_state", {
                "status": "idle",
                "proposed_slots": [],
                "confirmed_date": None,
                "confirmed_time": None,
            })["status"] = "proposed"

            if hil_state.extras.get("persist"):
                db_io.save_db(db, path, lock_path=lock_path)

    # If this approval is for a negotiation (Step 5), apply the decision so the workflow progresses.
    if step_num == 5:
        pending_decision = target_event.get("negotiation_pending_decision")
        if pending_decision:
            from backend.workflows.common.types import IncomingMessage, WorkflowState
            from backend.workflows.groups import negotiation_close as negotiation_group
            from backend.workflows.groups.transition_checkpoint import process as process_transition

            hil_message = IncomingMessage.from_dict(
                {
                    "msg_id": f"hil-approve-{task_id}",
                    "from_email": target_event.get("event_data", {}).get("Email"),
                    "subject": "HIL approval",
                    "body": manager_notes or "Approved",
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
            )
            hil_state = WorkflowState(message=hil_message, db_path=path, db=db)
            hil_state.client_id = (target_event.get("event_data", {}).get("Email") or "").lower()
            hil_state.event_entry = target_event
            hil_state.current_step = 5
            hil_state.user_info = {"hil_approve_step": 5, "hil_decision": "approve"}
            hil_state.thread_state = target_event.get("thread_state")

            decision_result = negotiation_group._apply_hil_negotiation_decision(hil_state, target_event, "approve")  # type: ignore[attr-defined]
            if not decision_result.halt and (target_event.get("current_step") == 6):
                process_transition(hil_state)

            # Set site_visit_state to "proposed" so client's date preference is handled correctly
            # (mirrors the Step 4 approval logic above)
            target_event.setdefault("site_visit_state", {
                "status": "idle",
                "proposed_slots": [],
                "confirmed_date": None,
                "confirmed_time": None,
            })["status"] = "proposed"

            if hil_state.extras.get("persist"):
                db_io.save_db(db, path, lock_path=lock_path)

    db_io.save_db(db, path, lock_path=lock_path)

    draft = target_request.get("draft") or {}
    body_text = draft.get("body_markdown") or draft.get("body") or ""
    headers = draft.get("headers") or []

    # If manager provided an edited message, use it instead of the original draft
    # This is used for AI Reply Approval when manager edits the AI-generated text
    if edited_message is not None:
        body_text = edited_message.strip()
        draft = dict(draft)
        draft["body_markdown"] = body_text
        draft["body"] = body_text
        draft["edited_by_manager"] = True

    assistant_draft = {"headers": headers, "body": body_text, "body_markdown": body_text}

    note_text = (manager_notes or "").strip()
    if step_num == 5:
        new_body = _compose_hil_decision_reply("approve", note_text)
        assistant_draft["body"] = new_body
        assistant_draft["body_markdown"] = new_body
        draft = dict(draft)
        draft["body_markdown"] = new_body
        draft["body"] = new_body
        body_text = new_body
        # Set site_visit_state to "proposed" so client's date preference is handled correctly
        target_event.setdefault("site_visit_state", {
            "status": "idle",
            "proposed_slots": [],
            "confirmed_date": None,
            "confirmed_time": None,
        })["status"] = "proposed"
        db_io.save_db(db, path, lock_path=lock_path)
    elif note_text:
        appended = f"{body_text.rstrip()}\n\nManager note:\n{note_text}" if body_text.strip() else f"Manager note:\n{note_text}"
        body_text = appended
        assistant_draft["body"] = appended
        assistant_draft["body_markdown"] = appended
        draft = dict(draft)
        draft["body_markdown"] = appended
        draft["body"] = appended

    return {
        "action": "send_reply",
        "event_id": target_event.get("event_id"),
        "thread_state": target_event.get("thread_state"),
        "draft": draft,
        "res": {
            "assistant_draft": assistant_draft,
            "assistant_draft_text": body_text,
        },
        "actions": [{"type": "send_reply"}],
        "thread_id": thread_id,
    }


def reject_task_and_send(
    task_id: str,
    db_path: Path = DB_PATH,
    *,
    manager_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """[OpenEvent Action] Reject a pending HIL task and emit a client-facing payload."""

    path = Path(db_path)
    lock_path = _resolve_lock_path(path)
    db = db_io.load_db(path, lock_path=lock_path)
    update_task_status(db, task_id, TaskStatus.REJECTED, manager_notes)

    # First, check if this is an AI Reply Approval task (these are NOT in pending_hil_requests)
    task_record = None
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            task_record = task
            break

    # Handle AI Reply Approval rejections separately
    if task_record and task_record.get("type") == TaskType.AI_REPLY_APPROVAL.value:
        payload = task_record.get("payload") or {}
        event_id = payload.get("event_id")
        thread_id = payload.get("thread_id")
        step_id = payload.get("step_id")

        # Find the event for context (optional)
        target_event = None
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                target_event = event
                break

        # Update hil_history on the event if found
        if target_event:
            target_event.setdefault("hil_history", []).append(
                {
                    "task_id": task_id,
                    "rejected_at": datetime.utcnow().isoformat() + "Z",
                    "notes": manager_notes,
                    "step": step_id,
                    "decision": "rejected",
                    "task_type": "ai_reply_approval",
                }
            )
            set_hil_open(thread_id, False)

        db_io.save_db(db, path, lock_path=lock_path)

        # Rejected AI reply = no message sent to client
        return {
            "action": "discarded",
            "event_id": event_id,
            "thread_state": target_event.get("thread_state") if target_event else None,
            "draft": None,
            "res": {
                "assistant_draft": None,
                "assistant_draft_text": "",
            },
            "actions": [],
            "thread_id": thread_id,
            "manager_notes": manager_notes,
        }

    # Original logic for step-specific HIL tasks (stored in pending_hil_requests)
    target_event = None
    target_request: Optional[Dict[str, Any]] = None
    for event in db.get("events", []):
        pending = event.get("pending_hil_requests") or []
        for request in pending:
            if request.get("task_id") == task_id:
                target_event = event
                target_request = request
                pending.remove(request)
                break
        if target_event:
            break

    if not target_event or not target_request:
        raise ValueError(f"Task {task_id} not found in pending approvals.")

    thread_id = target_request.get("thread_id") or target_event.get("thread_id")

    target_event.setdefault("hil_history", []).append(
        {
            "task_id": task_id,
            "rejected_at": datetime.utcnow().isoformat() + "Z",
            "notes": manager_notes,
            "step": target_request.get("step"),
            "decision": "rejected",
        }
    )
    set_hil_open(thread_id, bool(target_event.get("pending_hil_requests") or []))

    step_num = target_request.get("step")
    if isinstance(step_num, int):
        try:
            current_step_raw = target_event.get("current_step")
            try:
                current_step_int = int(current_step_raw) if current_step_raw is not None else None
            except (TypeError, ValueError):
                current_step_int = None
            effective_step = max(step_num, current_step_int) if current_step_int else step_num
            workflow_step = WorkflowStep(f"step_{effective_step}")
            write_stage(target_event, current_step=workflow_step)
            update_event_metadata(target_event, current_step=effective_step)
        except ValueError:
            pass

    if step_num == 5:
        pending_decision = target_event.get("negotiation_pending_decision")
        if pending_decision:
            from backend.workflows.common.types import IncomingMessage, WorkflowState
            from backend.workflows.groups import negotiation_close as negotiation_group

            hil_message = IncomingMessage.from_dict(
                {
                    "msg_id": f"hil-reject-{task_id}",
                    "from_email": target_event.get("event_data", {}).get("Email"),
                    "subject": "HIL rejection",
                    "body": manager_notes or "Declined",
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
            )
            hil_state = WorkflowState(message=hil_message, db_path=path, db=db)
            hil_state.client_id = (target_event.get("event_data", {}).get("Email") or "").lower()
            hil_state.event_entry = target_event
            hil_state.current_step = 5
            hil_state.user_info = {"hil_approve_step": 5, "hil_decision": "reject"}
            hil_state.thread_state = target_event.get("thread_state")

            negotiation_group._apply_hil_negotiation_decision(hil_state, target_event, "reject")  # type: ignore[attr-defined]
            if hil_state.extras.get("persist"):
                db_io.save_db(db, path, lock_path=lock_path)

    db_io.save_db(db, path, lock_path=lock_path)

    draft = target_request.get("draft") or {}
    body_text = draft.get("body_markdown") or draft.get("body") or ""
    headers = draft.get("headers") or []
    assistant_draft = {"headers": headers, "body": body_text, "body_markdown": body_text}

    note_text = (manager_notes or "").strip()
    if step_num == 5:
        new_body = _compose_hil_decision_reply("reject", note_text)
        assistant_draft["body"] = new_body
        assistant_draft["body_markdown"] = new_body
        draft = dict(draft)
        draft["body_markdown"] = new_body
        draft["body"] = new_body
        body_text = new_body
    elif note_text:
        appended = f"{body_text.rstrip()}\n\nManager note:\n{note_text}" if body_text.strip() else f"Manager note:\n{note_text}"
        body_text = appended
        assistant_draft["body"] = appended
        assistant_draft["body_markdown"] = appended
        draft = dict(draft)
        draft["body_markdown"] = appended
        draft["body"] = appended

    return {
        "action": "send_reply",
        "event_id": target_event.get("event_id"),
        "thread_state": target_event.get("thread_state"),
        "draft": draft,
        "res": {
            "assistant_draft": assistant_draft,
            "assistant_draft_text": body_text,
        },
        "actions": [{"type": "send_reply"}],
        "thread_id": thread_id,
    }


def cleanup_tasks(
    db: Dict[str, Any],
    *,
    keep_thread_id: Optional[str] = None,
) -> int:
    """Remove resolved or stale HIL tasks, optionally keeping those tied to a specific thread."""

    tasks = db.get("tasks") or []
    if not tasks:
        return 0

    remaining: List[Dict[str, Any]] = []
    removed_ids: set[str] = set()
    keep_specified = keep_thread_id is not None

    if not tasks:
        return 0

    if not keep_specified:
        removed_ids = {task.get("task_id") for task in tasks if task.get("task_id")}
        db["tasks"] = []
    else:
        removed_ids = set()
        for task in tasks:
            payload = task.get("payload") or {}
            thread_id = payload.get("thread_id")
            task_id = task.get("task_id")
            if thread_id == keep_thread_id:
                remaining.append(task)
            else:
                removed_ids.add(task_id)
        db["tasks"] = remaining

    if not removed_ids:
        return 0

    for event in db.get("events", []):
        pending = event.get("pending_hil_requests") or []
        if not pending:
            continue
        event["pending_hil_requests"] = [
            entry for entry in pending if entry.get("task_id") not in removed_ids
        ]

    return len(removed_ids)


@profile_step("workflow.router.process_msg")
def process_msg(msg: Dict[str, Any], db_path: Path = DB_PATH) -> Dict[str, Any]:
    """[Trigger] Process an inbound message through workflow groups A–C."""

    path = Path(db_path)
    lock_path = _resolve_lock_path(path)
    db = db_io.load_db(path, lock_path=lock_path)

    message = IncomingMessage.from_dict(msg)
    state = WorkflowState(message=message, db_path=path, db=db)
    raw_thread_id = (
        msg.get("thread_id")
        or msg.get("thread")
        or msg.get("session_id")
        or msg.get("msg_id")
        or msg.get("from_email")
        or "unknown-thread"
    )
    state.thread_id = str(raw_thread_id)
    STATE_STORE.clear(state.thread_id)
    combined_text = "\n".join(
        part for part in ((message.subject or "").strip(), (message.body or "").strip()) if part
    )
    state.extras["general_qna_scan"] = quick_general_qna_scan(combined_text)
    # [DEV TEST MODE] Pass through skip_dev_choice flag for testing convenience
    if msg.get("skip_dev_choice"):
        state.extras["skip_dev_choice"] = True
    classification = _ensure_general_qna_classification(state, combined_text)
    _debug_state("init", state, extra={"entity": "client"})
    last_result = intake.process(state)
    _debug_state("post_intake", state, extra={"intent": state.intent.value if state.intent else None})

    # [DUPLICATE MESSAGE DETECTION] Check if client sent the exact same message twice in a row
    # This prevents confusing duplicate responses when client accidentally resends
    if state.event_entry:
        last_client_msg = state.event_entry.get("last_client_message", "")
        normalized_current = combined_text.strip().lower()
        normalized_last = (last_client_msg or "").strip().lower()

        # Only check for duplicates if we have a previous message and messages are identical
        if normalized_last and normalized_current == normalized_last:
            # Don't flag as duplicate if this is a detour return or offer update flow
            is_detour = state.event_entry.get("caller_step") is not None
            current_step = state.event_entry.get("current_step", 1)
            # Don't flag as duplicate during billing flow - client may resend billing info
            in_billing_flow = (
                state.event_entry.get("offer_accepted")
                and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
            )

            if not is_detour and not in_billing_flow and current_step >= 2:
                # Return friendly "same message" response instead of processing
                duplicate_response = GroupResult(
                    action="duplicate_message",
                    halt=True,
                    payload={
                        "draft": {
                            "body_markdown": (
                                "I notice this is the same message as before. "
                                "Is there something specific you'd like to add or clarify? "
                                "I'm happy to help with any questions or changes."
                            ),
                            "hil_required": False,
                        },
                    },
                )
                from backend.debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel
                trace_marker(
                    state.thread_id,
                    "DUPLICATE_MESSAGE_DETECTED",
                    detail="Client sent identical message twice in a row",
                    owner_step=f"Step{current_step}",
                )
                return _flush_and_finalize(duplicate_response, state, path, lock_path)

        # Store current message for next comparison (only if not a duplicate)
        state.event_entry["last_client_message"] = combined_text.strip()
        state.extras["persist"] = True

    _persist_if_needed(state, path, lock_path)
    if last_result.halt:
        _debug_state("halt_post_intake", state)
        return _flush_and_finalize(last_result, state, path, lock_path)

    guard_snapshot = evaluate_guards(state)
    if guard_snapshot.step2_required and guard_snapshot.candidate_dates:
        state.extras["guard_candidate_dates"] = list(guard_snapshot.candidate_dates)

    shortcut_result = maybe_run_smart_shortcuts(state)
    if shortcut_result is not None:
        _debug_state(
            "smart_shortcut",
            state,
            extra={"shortcut_action": shortcut_result.action},
        )
        _persist_if_needed(state, path, lock_path)
        return _flush_and_finalize(shortcut_result, state, path, lock_path)

    # [BILLING FLOW CORRECTION] Force step=5 when in billing flow
    # This handles cases where step was incorrectly set before billing flow started
    if state.event_entry:
        in_billing_flow = (
            state.event_entry.get("offer_accepted")
            and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        )
        stored_step = state.event_entry.get("current_step")
        if in_billing_flow and stored_step != 5:
            print(f"[WF][BILLING_FIX] Correcting step from {stored_step} to 5 for billing flow")
            state.event_entry["current_step"] = 5
            state.extras["persist"] = True

    for _ in range(6):
        event_entry = state.event_entry
        if not event_entry:
            break
        step = event_entry.get("current_step")
        if step == 2:
            last_result = date_confirmation.process(state)
            _debug_state("post_step2", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step2", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 3:
            last_result = room_availability.process(state)
            _debug_state("post_step3", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step3", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 4:
            last_result = process_offer(state)
            _debug_state("post_step4", state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step4", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 5:
            last_result = process_negotiation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step5", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 6:
            last_result = process_transition(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step6", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        if step == 7:
            last_result = process_confirmation(state)
            _persist_if_needed(state, path, lock_path)
            if last_result.halt:
                _debug_state("halt_step7", state)
                return _flush_and_finalize(last_result, state, path, lock_path)
            continue
        break

    _debug_state("final", state)
    return _flush_and_finalize(last_result, state, path, lock_path)


def run_samples() -> list[Any]:
    """[Trigger] Execute a deterministic sample flow for manual testing."""

    os.environ["AGENT_MODE"] = "stub"
    llm_adapter.reset_llm_adapter()
    if DB_PATH.exists():
        DB_PATH.unlink()

    samples = [
        {
            "msg_id": "sample-1",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Event inquiry for our workshop",
            "ts": "2025-10-13T09:00:00Z",
            "body": (
                "Hello,\n"
                "We would like to reserve Room A for approx 15 ppl next month for a workshop.\n"
                "Could you share available dates? Language: en.\n"
                "Phone: 042754980\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
        {
            "msg_id": "sample-2",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Event Request: 15.03.2025 Room A",
            "ts": "2025-10-14T10:31:00Z",
            "body": (
                "Hello,\n"
                "We confirm the workshop should be on 15.03.2025 in Room A.\n"
                "We expect 15 participants and would like catering preference: Standard Buffet.\n"
                "Start at 14:00 and end by 16:00.\n"
                "Company: TechCorp\n"
                "Language: English\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
        {
            "msg_id": "sample-3",
            "from_name": "Sarah Thompson",
            "from_email": "sarah.thompson@techcorp.com",
            "subject": "Parking question",
            "ts": "2025-10-16T08:05:00Z",
            "body": (
                "Hello,\n"
                "Is there parking available nearby? Just checking for next week.\n"
                "Thanks,\n"
                "Sarah\n"
            ),
        },
    ]

    outputs: list[Any] = []
    for msg in samples:
        res = process_msg(msg)
        print(res)
        outputs.append(res)

    if sys.stdin.isatty():
        task_cli_loop()
    return outputs


def task_cli_loop(db_path: Path = DB_PATH) -> None:
    """[OpenEvent Action] Provide a simple CLI to inspect and update tasks."""

    while True:
        print("\nOpenEvent Action Queue")
        print("1) List pending tasks")
        print("2) Approve a task")
        print("3) Reject a task")
        print("4) Mark task done")
        print("5) Exit")
        choice = input("Select option: ").strip()




        if choice == "1":
            db = load_db(db_path)
            pending = list_pending_tasks(db)
            if not pending:
                print("No pending tasks.")
            else:
                for task in pending:
                    payload_preview = task.get("payload") or {}
                    print(
                        f"- {task.get('task_id')} | {task.get('type')} | "
                        f"{payload_preview.get('reason') or payload_preview.get('preferred_room')}"
                    )
        elif choice in {"2", "3", "4"}:
            task_id = input("Task ID: ").strip()
            notes = input("Notes (optional): ").strip() or None
            status_map = {"2": TaskStatus.APPROVED, "3": TaskStatus.REJECTED, "4": TaskStatus.COMPLETED}
            db = load_db(db_path)
            update_task_status(db, task_id, status_map[choice], notes)
            save_db(db, db_path)
            print(f"Task {task_id} updated to {status_map[choice].value}.")
        elif choice == "5":
            return
        else:
            print("Invalid choice.")


def _finalize_output(result: GroupResult, state: WorkflowState) -> Dict[str, Any]:
    """[Trigger] Normalise final payload with workflow metadata."""

    payload = result.merged()
    if state.user_info:
        payload.setdefault("user_info", dict(state.user_info))
    if state.intent_detail:
        payload["intent_detail"] = state.intent_detail
    event_entry = state.event_entry
    if event_entry:
        payload.setdefault("event_id", event_entry.get("event_id"))
        payload["current_step"] = event_entry.get("current_step")
        payload["caller_step"] = event_entry.get("caller_step")
        payload["thread_state"] = event_entry.get("thread_state")
        payload.setdefault("stage", stage_payload(event_entry))
    elif state.thread_state:
        payload["thread_state"] = state.thread_state
    res_meta = payload.setdefault("res", {})
    actions_out = payload.setdefault("actions", [])
    requires_approval_flags: List[bool] = []
    # Check FIRST if HIL approval is required for ALL LLM replies (toggle)
    # This must be checked BEFORE _enqueue_hil_tasks to avoid creating duplicate tasks
    hil_all_replies_on = is_hil_all_replies_enabled()
    if state.draft_messages:
        payload["draft_messages"] = state.draft_messages
        # ALWAYS create step-specific HIL tasks (offer confirmation, special requests, etc.)
        # These are the original workflow HIL tasks - they work regardless of the AI reply toggle
        if event_entry:
            _enqueue_hil_tasks(state, event_entry)
        requires_approval_flags = [draft.get("requires_approval", True) for draft in state.draft_messages]
    else:
        payload.setdefault("draft_messages", [])

    if state.draft_messages:
        latest_draft = next(
            (draft for draft in reversed(state.draft_messages) if draft.get("requires_approval")),
            state.draft_messages[-1],
        )
        draft_body = latest_draft.get("body_markdown") or latest_draft.get("body") or ""
        draft_headers = list(latest_draft.get("headers") or [])

        # When HIL toggle is ON: DON'T include message in response (it goes to approval queue only)
        # When HIL toggle is OFF: Include message in response for immediate display
        if hil_all_replies_on:
            # Message pending approval - don't send to client chat yet
            res_meta["assistant_draft"] = None
            res_meta["assistant_draft_text"] = ""
            res_meta["pending_hil_approval"] = True  # Flag for frontend
        else:
            res_meta["assistant_draft"] = {"headers": draft_headers, "body": draft_body}
            res_meta["assistant_draft_text"] = draft_body
    else:
        res_meta.setdefault("assistant_draft", None)
        res_meta.setdefault("assistant_draft_text", "")
    general_qa_payload = state.turn_notes.get("general_qa")
    if general_qa_payload:
        res_meta["general_qa"] = general_qa_payload
    trace_payload = payload.setdefault("trace", {})
    trace_payload["subloops"] = list(state.subloops_trace)
    if state.draft_messages:
        # Check if HIL approval is required for ALL LLM replies (toggle)
        if hil_all_replies_on:
            # When toggle ON: ALL AI-generated replies go to separate "AI Reply Approval" queue
            # This allows managers to review/edit EVERY outbound message before it reaches clients
            latest_draft = state.draft_messages[-1]
            draft_body = latest_draft.get("body_markdown") or latest_draft.get("body") or ""
            draft_step = latest_draft.get("step", state.current_step)
            thread_id = _thread_identifier(state)

            # Check if there's already a PENDING ai_reply_approval task for this thread
            # This prevents duplicate tasks from being created
            existing_pending_task = None
            for task in state.db.get("tasks", []):
                if (task.get("type") == TaskType.AI_REPLY_APPROVAL.value
                    and task.get("status") == TaskStatus.PENDING.value
                    and task.get("payload", {}).get("thread_id") == thread_id):
                    existing_pending_task = task
                    break

            if existing_pending_task:
                # Update existing task with new draft instead of creating duplicate
                existing_pending_task["payload"]["draft_body"] = draft_body
                existing_pending_task["payload"]["step_id"] = draft_step
                task_id = existing_pending_task.get("task_id")
            else:
                # Create task for AI reply approval
                client_id = state.client_id or (state.message.from_email or "unknown@example.com").lower()
                task_payload = {
                    "step_id": draft_step,
                    "draft_body": draft_body,
                    "thread_id": thread_id,
                    "event_id": event_entry.get("event_id") if event_entry else None,
                    "editable": True,  # Manager can edit before approving
                    "event_summary": {
                        "client_name": event_entry.get("client_name", "Client") if event_entry else "Client",
                        "email": event_entry.get("client_id") if event_entry else None,
                        "company": (event_entry.get("event_data") or {}).get("Organization") if event_entry else None,
                        "chosen_date": event_entry.get("chosen_date") if event_entry else None,
                        "locked_room": event_entry.get("locked_room") if event_entry else None,
                    },
                }
                task_id = enqueue_task(
                    state.db,
                    TaskType.AI_REPLY_APPROVAL,
                    client_id,
                    event_entry.get("event_id") if event_entry else None,
                    task_payload,
                )

            hil_ai_payload = {
                "task_id": task_id,
                "event_id": event_entry.get("event_id") if event_entry else None,
                "client_name": event_entry.get("client_name", "Client") if event_entry else "Client",
                "client_email": event_entry.get("client_id") if event_entry else None,
                "draft_message": draft_body,
                "workflow_step": draft_step,
                "editable": True,  # Manager can edit before approving
            }
            actions_out.append({"type": "hil_ai_reply_approval", "payload": hil_ai_payload})
        elif any(not flag for flag in requires_approval_flags):
            # Toggle OFF + no approval needed: send directly (current behavior)
            actions_out.append({"type": "send_reply"})
        elif event_entry:
            # Toggle OFF + approval needed: route to step-specific HIL (current behavior)
            hil_type = _hil_action_type_for_step(state.draft_messages[-1].get("step"))
            if hil_type:
                hil_payload = {
                    "event_id": event_entry.get("event_id"),
                }
                if event_entry.get("candidate_dates"):
                    hil_payload["suggested_dates"] = list(event_entry.get("candidate_dates"))
                actions_out.append({"type": hil_type, "payload": hil_payload})
    if state.telemetry:
        payload["telemetry"] = state.telemetry.to_payload()
    return payload
