"""
HIL (Human-in-the-Loop) task management APIs.

Extracted from workflow_email.py as part of W2 refactoring.

Public API:
- approve_task_and_send: Approve a pending HIL task and emit send_reply payload
- reject_task_and_send: Reject a pending HIL task and emit response payload
- cleanup_tasks: Remove resolved or stale HIL tasks
- list_pending_tasks: List pending HIL tasks (re-export from task_io)
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from domain import TaskStatus, TaskType

if TYPE_CHECKING:
    from workflows.common.types import WorkflowState
from workflows.io import database as db_io
from workflows.io import tasks as task_io
from workflows.io.database import update_event_metadata
from workflow.state import WorkflowStep, write_stage
from debug.trace import set_hil_open

# Re-export from task_io for backwards compatibility
list_pending_tasks = task_io.list_pending_tasks
update_task_status = task_io.update_task_status
enqueue_task = task_io.enqueue_task


def _get_default_db_path() -> Path:
    """Get the default database path, respecting tenant context.

    Uses tenant-aware resolution when X-Team-Id header or OE_TEAM_ID env is set.
    """
    base_path = Path(__file__).parent.parent.parent / "events_database.json"

    # Resolve tenant-aware path
    try:
        from workflows.io.integration.config import get_team_id

        team_id = get_team_id()
        if team_id:
            return base_path.parent / f"events_{team_id}.json"
    except ImportError:
        pass  # Config not available

    return base_path


def _get_default_lock_path() -> Path:
    """Get the default lock path, respecting tenant context."""
    db_path = _get_default_db_path()
    return db_io.lock_path_for(db_path)


def _resolve_lock_path(path: Path) -> Path:
    """Determine the lockfile used for a database path."""
    return db_io.lock_path_for(path)


def _build_hil_context(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build enriched context for HIL task review.

    Provides managers with decision history, client preferences, and event summary
    so they don't need to switch tabs to understand the conversation context.
    """
    context: Dict[str, Any] = {}

    # Previous HIL decisions (last 3)
    hil_history = event_entry.get("hil_history") or []
    if hil_history:
        context["previous_decisions"] = [
            {
                "step": d.get("step"),
                "decision": d.get("decision"),
                "notes": d.get("notes"),
                "timestamp": d.get("approved_at") or d.get("rejected_at"),
            }
            for d in hil_history[-3:]
        ]

    # Client preferences from captured data
    requirements = event_entry.get("requirements") or {}
    preferences = event_entry.get("preferences") or {}
    captured = event_entry.get("captured") or {}

    client_prefs: Dict[str, Any] = {}
    if requirements.get("number_of_participants"):
        client_prefs["participants"] = requirements["number_of_participants"]
    if captured.get("catering"):
        client_prefs["catering"] = captured["catering"]
    if captured.get("products"):
        client_prefs["special_requests"] = captured["products"]
    if preferences.get("room_preference"):
        client_prefs["preferred_room"] = preferences["room_preference"]

    if client_prefs:
        context["client_preferences"] = client_prefs

    # Current event summary
    event_data = event_entry.get("event_data") or {}
    context["event_summary"] = {
        "client_name": event_data.get("Name"),
        "company": event_data.get("Company"),
        "event_date": event_entry.get("chosen_date"),
        "room": event_entry.get("locked_room_id"),
        "step": event_entry.get("current_step"),
    }

    return context


def _compose_hil_decision_reply(decision: str, manager_notes: Optional[str] = None) -> str:
    """Compose a client-facing reply for HIL approval/rejection decisions."""
    normalized = (decision or "").lower()
    approved = normalized == "approve"
    note_text = (manager_notes or "").strip()

    if approved:
        # Warm, conversational approval
        intro = "Great news! Everything looks good on our end."
        next_line = "Let's continue with site visit bookings. Do you have any preferred dates or times?"
    else:
        # Soft rejection with forward momentum
        intro = "Thank you for your patience."
        next_line = "I'll revise the proposal based on some feedback and share an updated version shortly."

    sections = [intro]
    if note_text:
        # Integrate notes naturally without "Manager note:" label
        sections.append(note_text)
    sections.append(next_line)
    return "\n\n".join(section for section in sections if section)


def approve_task_and_send(
    task_id: str,
    db_path: Optional[Path] = None,
    *,
    manager_notes: Optional[str] = None,
    edited_message: Optional[str] = None,
) -> Dict[str, Any]:
    """[OpenEvent Action] Approve a pending HIL task and emit the send_reply payload used in tests.

    Args:
        task_id: The HIL task ID to approve
        db_path: Path to the database file (defaults to events_database.json)
        manager_notes: Optional notes from the manager (appended to message)
        edited_message: Optional edited message text (replaces original draft when provided)
    """
    path = Path(db_path) if db_path else _get_default_db_path()
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

        # Append manager notes naturally (no label prefix)
        note_text = (manager_notes or "").strip()
        if note_text and body_text:
            body_text = f"{body_text.rstrip()}\n\n{note_text}"

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

            # Log activity for manager audit trail
            from activity.persistence import log_workflow_activity
            task_type = "edited reply" if edited_message else "AI reply"
            log_workflow_activity(target_event, "hil_approved", step=step_id or "?", task_type=task_type)

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

    # Handle SOURCE_MISSING_PRODUCT task approval (manager found the product)
    # NOTE: We do NOT send a standalone message here. Instead, we store the
    # sourcing prefix and let Step 4 generate a HYBRID message (sourcing confirmation + offer).
    if task_record and task_record.get("type") == TaskType.SOURCE_MISSING_PRODUCT.value:
        payload = task_record.get("payload") or {}
        event_id = payload.get("event_id")
        thread_id = payload.get("thread_id")
        products = payload.get("products", [])
        room = payload.get("room")

        # Find the event
        target_event = None
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                target_event = event
                break

        if target_event:
            # Clear sourcing_pending state
            if "sourcing_pending" in target_event:
                del target_event["sourcing_pending"]

            # Format product list and price for the sourcing prefix message
            if len(products) == 1:
                product_text = products[0]
            else:
                product_text = ", ".join(products[:-1]) + f" and {products[-1]}"

            price_note = ""
            if manager_notes:
                price_note = f" {manager_notes}"

            sourcing_prefix = (
                f"Great news! We can arrange the {product_text} for your event.{price_note}\n\n"
            )

            # Store sourced products with prefix for hybrid offer message
            target_event["sourced_products"] = {
                "products": products,
                "room": room,
                "manager_notes": manager_notes,
                "sourced_at": datetime.utcnow().isoformat() + "Z",
                "sourcing_prefix": sourcing_prefix,  # Step 4 will prepend this to offer
            }

            # Update HIL history
            target_event.setdefault("hil_history", []).append(
                {
                    "task_id": task_id,
                    "approved_at": datetime.utcnow().isoformat() + "Z",
                    "notes": manager_notes,
                    "step": 3,
                    "decision": "approved",
                    "task_type": "source_missing_product",
                    "products": products,
                }
            )

            # Log activity for manager audit trail
            from activity.persistence import log_workflow_activity
            products_text = ", ".join(products) if products else "product"
            log_workflow_activity(target_event, "product_sourced", products=products_text)

            # Update state for direct advance to Step 4
            # IMPORTANT: Clear caller_step to ensure Step 4 is called (not some other step)
            update_event_metadata(
                target_event,
                current_step=4,
                caller_step=None,  # Clear to prevent routing issues
                thread_state="Processing",
            )
            set_hil_open(thread_id, False)

        db_io.save_db(db, path, lock_path=lock_path)

        # Return WITHOUT a draft message - Step 4 will generate the hybrid offer
        return {
            "action": "advance_to_offer",
            "event_id": event_id,
            "thread_state": "Processing",
            "res": {},  # No draft message - hybrid will be generated by Step 4
            "actions": [],  # No immediate actions
            "thread_id": thread_id,
            "advance_to_step": 4,  # Frontend triggers continuation to Step 4
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

    # Log activity for manager audit trail
    from activity.persistence import log_workflow_activity
    request_step = target_request.get("step") or "?"
    log_workflow_activity(target_event, "hil_approved", step=request_step, task_type="workflow task")

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
            from workflows.common.types import IncomingMessage, WorkflowState
            from workflows.steps import step5_negotiation as negotiation_group
            from workflows.steps.step6_transition import process as process_transition

            logger.info("[HIL] Step 4 offer approved with deposit paid, continuing to site visit")

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

            # Don't force site_visit_state here - let Step 7 handle it naturally
            # The workflow will set "proposed" when it's ready for site visit

            if hil_state.extras.get("persist"):
                db_io.save_db(db, path, lock_path=lock_path)

    # If this approval is for a negotiation (Step 5), apply the decision so the workflow progresses.
    # BUG FIX (2026-01-13): After Step 5 HIL approval, we must continue to Step 7 to generate
    # the site visit message instead of returning the original HIL draft (which was manager-facing).
    if step_num == 5:
        pending_decision = target_event.get("negotiation_pending_decision")
        if pending_decision:
            from workflows.common.types import IncomingMessage, WorkflowState
            from workflows.steps import step5_negotiation as negotiation_group
            from workflows.steps.step6_transition import process as process_transition

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

            # BUG FIX (2026-01-13): After Step 5 HIL approval, check confirmation gate
            # and either prompt for deposit or generate site visit message.
            current_step = target_event.get("current_step")
            if current_step in (6, 7) and not decision_result.halt:
                from workflows.common.confirmation_gate import check_confirmation_gate, get_next_prompt

                # Check if all prerequisites are met (billing + deposit)
                gate_status = check_confirmation_gate(target_event)

                if not gate_status.ready_for_hil:
                    # Not ready - need deposit or billing first
                    next_prompt = get_next_prompt(gate_status, step=5)
                    if next_prompt:
                        update_event_metadata(target_event, current_step=5, thread_state="Awaiting Client")
                        db_io.save_db(db, path, lock_path=lock_path)

                        body_text = next_prompt.get("body_markdown") or next_prompt.get("body") or ""
                        assistant_draft = {"headers": [], "body": body_text, "body_markdown": body_text}
                        return {
                            "action": "awaiting_prerequisites",
                            "event_id": target_event.get("event_id"),
                            "thread_state": "Awaiting Client",
                            "draft": {"body": body_text, "body_markdown": body_text, "headers": []},
                            "res": {
                                "assistant_draft": assistant_draft,
                                "assistant_draft_text": body_text,
                            },
                            "actions": [{"type": "send_reply"}],
                            "thread_id": thread_id,
                            "pending_deposit": gate_status.deposit_required and not gate_status.deposit_paid,
                        }

                # All prerequisites met - proceed to Step 7 for site visit
                update_event_metadata(target_event, current_step=7, thread_state="Processing")

                # Generate site visit message by calling Step 7 handler
                from workflows.steps.step7_confirmation.trigger.process import process as process_step7

                # Create a fresh state for Step 7 processing
                step7_message = IncomingMessage.from_dict({
                    "msg_id": f"hil-continue-{task_id}",
                    "from_email": target_event.get("event_data", {}).get("Email"),
                    "subject": "Continue to confirmation",
                    "body": "",  # Empty body - just continuing the workflow
                    "ts": datetime.utcnow().isoformat() + "Z",
                })
                step7_state = WorkflowState(message=step7_message, db_path=path, db=db)
                step7_state.client_id = (target_event.get("event_data", {}).get("Email") or "").lower()
                step7_state.event_entry = target_event
                step7_state.current_step = 7
                step7_state.thread_state = "Processing"

                # Call Step 7 to generate the site visit message
                _step7_result = process_step7(step7_state)  # Result stored in state.draft_messages

                # Get the generated message from state
                draft_messages = step7_state.draft_messages or []
                if draft_messages:
                    draft = draft_messages[0]
                    # Use body (client message) first, not body_markdown (manager display)
                    body_text = draft.get("body") or draft.get("body_markdown") or ""
                else:
                    # Fallback message if Step 7 didn't generate one
                    body_text = "Thank you for accepting the offer. We will be in touch shortly to finalize the details."

                if step7_state.extras.get("persist"):
                    db_io.save_db(db, path, lock_path=lock_path)
                else:
                    db_io.save_db(db, path, lock_path=lock_path)

                assistant_draft = {"headers": [], "body": body_text, "body_markdown": body_text}
                return {
                    "action": "send_reply",
                    "event_id": target_event.get("event_id"),
                    "thread_state": step7_state.thread_state,
                    "draft": {"body": body_text, "body_markdown": body_text, "headers": []},
                    "res": {
                        "assistant_draft": assistant_draft,
                        "assistant_draft_text": body_text,
                    },
                    "actions": [{"type": "send_reply"}],
                    "thread_id": thread_id,
                }

            if hil_state.extras.get("persist"):
                db_io.save_db(db, path, lock_path=lock_path)

    db_io.save_db(db, path, lock_path=lock_path)

    draft = target_request.get("draft") or {}
    headers = draft.get("headers") or []

    # CRITICAL: body = client-facing message, body_markdown = manager-only display
    # When they differ, ALWAYS use body for the client message.
    # This is a common bug source - add defensive logging and assertions.
    raw_body = draft.get("body") or ""
    raw_body_markdown = draft.get("body_markdown") or ""

    if raw_body and raw_body_markdown and raw_body != raw_body_markdown:
        # They differ - use body (client message), log the difference
        logger.warning(
            "[HIL_APPROVAL] body differs from body_markdown (step=%s). "
            "Using body for client. body[:80]=%r, body_markdown[:80]=%r",
            target_request.get('step'),
            raw_body[:80],
            raw_body_markdown[:80],
        )
        body_text = raw_body
    else:
        # Same or one is empty - use whichever is available
        body_text = raw_body or raw_body_markdown

    # ALWAYS sync draft body and body_markdown to prevent frontend from showing wrong content
    # (frontend prioritizes body_markdown, so we must set it to the client message)
    draft = dict(draft)
    draft["body"] = body_text
    draft["body_markdown"] = body_text

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
    # For non-Step-5 approvals, append manager notes naturally (no label prefix)
    if note_text:
        appended = f"{body_text.rstrip()}\n\n{note_text}" if body_text.strip() else note_text
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
    db_path: Optional[Path] = None,
    *,
    manager_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """[OpenEvent Action] Reject a pending HIL task and emit a client-facing payload."""
    path = Path(db_path) if db_path else _get_default_db_path()
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

            # Log activity for manager audit trail
            from activity.persistence import log_workflow_activity
            reason = manager_notes or "no reason given"
            log_workflow_activity(target_event, "hil_rejected", step=step_id or "?", reason=reason)

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

    # Handle SOURCE_MISSING_PRODUCT task rejection (manager couldn't find the product)
    if task_record and task_record.get("type") == TaskType.SOURCE_MISSING_PRODUCT.value:
        payload = task_record.get("payload") or {}
        event_id = payload.get("event_id")
        thread_id = payload.get("thread_id")
        products = payload.get("products", [])
        room = payload.get("room")

        # Find the event
        target_event = None
        for event in db.get("events", []):
            if event.get("event_id") == event_id:
                target_event = event
                break

        if target_event:
            # Clear sourcing_pending state
            if "sourcing_pending" in target_event:
                del target_event["sourcing_pending"]

            # Set sourcing_declined so step3 handler knows to ask client to continue
            target_event["sourcing_declined"] = {
                "products": products,
                "room": room,
                "manager_notes": manager_notes,
                "declined_at": datetime.utcnow().isoformat() + "Z",
            }

            # Update HIL history
            target_event.setdefault("hil_history", []).append(
                {
                    "task_id": task_id,
                    "rejected_at": datetime.utcnow().isoformat() + "Z",
                    "notes": manager_notes,
                    "step": 3,
                    "decision": "rejected",
                    "task_type": "source_missing_product",
                    "products": products,
                }
            )

            # Log activity for manager audit trail
            from activity.persistence import log_workflow_activity
            products_text = ", ".join(products) if products else "product"
            reason = f"Could not source: {products_text}"
            if manager_notes:
                reason += f" ({manager_notes})"
            log_workflow_activity(target_event, "hil_rejected", step=3, reason=reason)

            # Update thread state - waiting for client to decide
            update_event_metadata(target_event, thread_state="Awaiting Client")
            set_hil_open(thread_id, False)

        db_io.save_db(db, path, lock_path=lock_path)

        # Format product list for message
        if len(products) == 1:
            product_text = products[0]
        else:
            product_text = ", ".join(products[:-1]) + f" and {products[-1]}"

        # Build message asking client to continue
        reason_note = ""
        if manager_notes:
            reason_note = f" ({manager_notes})"

        body_text = (
            f"Unfortunately, we weren't able to arrange the {product_text} for your event{reason_note}. "
            f"Would you like to continue with your booking without it, or would you prefer to cancel?"
        )

        draft = {
            "body": body_text,
            "body_markdown": body_text,
            "headers": [],
            "topic": "sourcing_failed",
            "step": 3,
        }

        return {
            "action": "send_reply",
            "event_id": event_id,
            "thread_state": "Awaiting Client",
            "draft": draft,
            "res": {
                "assistant_draft": draft,
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
            from workflows.common.types import IncomingMessage, WorkflowState
            from workflows.steps import step5_negotiation as negotiation_group

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
    # Use body (client message) first, not body_markdown (manager display)
    body_text = draft.get("body") or draft.get("body_markdown") or ""
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
        # Append manager notes naturally (no label prefix)
        appended = f"{body_text.rstrip()}\n\n{note_text}" if body_text.strip() else note_text
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


# ============================================================================
# HIL Task Creation (W2 extraction from workflow_email.py)
# ============================================================================


def _thread_identifier(state: "WorkflowState") -> str:
    """Get a stable thread identifier from state."""
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _hil_signature(draft: Dict[str, Any], event_entry: Dict[str, Any]) -> str:
    """Generate a signature to prevent duplicate HIL tasks."""
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


def _hil_action_type_for_step(step_id: Optional[int]) -> Optional[str]:
    """Map workflow step to action type string."""
    if step_id == 2:
        return "ask_for_date_enqueued"
    if step_id == 3:
        return "room_options_enqueued"
    if step_id == 4:
        return "offer_enqueued"
    if step_id == 5:
        return "negotiation_enqueued"
    if step_id == 6:
        return "transition_enqueued"
    if step_id == 7:
        return "confirmation_enqueued"
    return None


def enqueue_hil_tasks(state: "WorkflowState", event_entry: Dict[str, Any]) -> None:
    """[OpenEvent Action] Create HIL task records from draft messages.

    This function processes draft messages in the state, creates HIL tasks for those
    requiring approval, and updates the pending_hil_requests list on the event.

    Extracted from workflow_email.py as part of W2 refactoring.
    """
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
        if step_num not in {2, 3, 4, 5, 6, 7}:
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
        elif step_num == 6:
            task_type = TaskType.TRANSITION_MESSAGE
        elif step_num == 7:
            task_type = TaskType.CONFIRMATION_MESSAGE
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
            "hil_context": _build_hil_context(event_entry),  # Enriched context for managers
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
        task_record = {
            "task_id": task_id,
            "signature": signature,
            "step": step_num,
            "draft": dict(draft),
            "thread_id": thread_id,
            "type": task_type.value if hasattr(task_type, 'value') else str(task_type),
            "client_id": client_id,
            "event_id": event_entry.get("event_id"),
            "payload": task_payload,
        }
        pending_records.append(task_record)
        seen_signatures.add(signature)
        state.extras["persist"] = True

        # Send email notification if enabled (async, non-blocking)
        _notify_hil_email(task_record, event_entry)

    set_hil_open(thread_id, bool(pending_records))


def _notify_hil_email(task: Dict[str, Any], event_entry: Dict[str, Any]) -> None:
    """Send HIL email notification if enabled (non-blocking).

    This is called when a HIL task is created to ALSO send an email
    notification to the Event Manager (in addition to frontend panel).
    """
    try:
        from services.hil_email_notification import (
            is_hil_email_enabled,
            notify_hil_task_created,
        )

        if not is_hil_email_enabled():
            return

        result = notify_hil_task_created(task, event_entry)
        if result:
            if result.get("success"):
                logger.info("[HIL_EMAIL] Notification sent for task %s", task.get('task_id'))
            else:
                logger.warning("[HIL_EMAIL] Failed to send: %s", result.get('error'))

    except ImportError:
        # Email service not available - silently skip
        pass
    except Exception as e:
        # Log but don't fail the HIL task creation
        logger.error("[HIL_EMAIL] Error sending notification: %s", e)
