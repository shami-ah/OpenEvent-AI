"""
MODULE: backend/api/routes/tasks.py
PURPOSE: HIL (Human-in-the-Loop) task management endpoints.

ENDPOINTS:
    GET  /api/tasks/pending      - List pending tasks for manager approval
    POST /api/tasks/{id}/approve - Approve a task
    POST /api/tasks/{id}/reject  - Reject a task
    POST /api/tasks/cleanup      - Remove resolved tasks

DEPENDS ON:
    - backend/workflow_email.py  # Task listing, approval, rejection
    - backend/workflows/common/pricing.py  # Rate calculations for task summaries
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
    list_pending_tasks as wf_list_pending_tasks,
    approve_task_and_send as wf_approve_task_and_send,
    reject_task_and_send as wf_reject_task_and_send,
    cleanup_tasks as wf_cleanup_tasks,
)
from backend.workflows.common.pricing import derive_room_rate, normalise_rate


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# --- Request Models ---

class TaskDecisionRequest(BaseModel):
    notes: Optional[str] = None
    edited_message: Optional[str] = None  # For AI Reply Approval: manager can edit draft before sending


class TaskCleanupRequest(BaseModel):
    keep_thread_id: Optional[str] = None


# --- Helper Functions ---

def _build_line_items(entry: Dict[str, Any]) -> list[str]:
    """Build line items summary for task display."""
    items: list[str] = []
    pricing_inputs = entry.get("pricing_inputs") or {}
    room_label = entry.get("locked_room_id") or (entry.get("room_pending_decision") or {}).get("selected_room")
    base_rate = normalise_rate(pricing_inputs.get("base_rate"))
    if base_rate is None:
        base_rate = derive_room_rate(entry)
    if base_rate is not None:
        items.append(f"{room_label or 'Room'} · CHF {base_rate:,.2f}")

    for product in entry.get("products") or []:
        name = product.get("name") or "Unnamed item"
        try:
            qty = float(product.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            unit_price = float(product.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            unit_price = 0.0
        unit = product.get("unit")
        total = qty * unit_price if qty and unit_price else unit_price
        label = f"{qty:g}× {name}" if qty else name
        price_text = f"CHF {total:,.2f}"
        if unit == "per_person" and qty:
            price_text += f" (CHF {unit_price:,.2f} per person)"
        elif unit == "per_event":
            price_text += " (per event)"
        items.append(f"{label} · {price_text}")
    return items


def _build_event_summary(event_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build event summary for task display."""
    if not event_entry:
        return None

    event_data = event_entry.get("event_data") or {}
    event_summary = {
        "client_name": event_data.get("Name"),
        "company": event_data.get("Company"),
        "billing_address": event_data.get("Billing Address"),
        "email": event_data.get("Email"),
        "chosen_date": event_entry.get("chosen_date"),
        "locked_room": event_entry.get("locked_room_id"),
        "line_items": _build_line_items(event_entry),
        "current_step": event_entry.get("current_step", 1),
    }

    # Calculate offer total
    try:
        from backend.workflows.steps.step5_negotiation.trigger.step5_handler import _determine_offer_total
        total_amount = _determine_offer_total(event_entry)
    except Exception:
        total_amount = None
    if total_amount not in (None, 0):
        event_summary["offer_total"] = total_amount

    # Include deposit info for client-side payment button
    deposit_info = event_entry.get("deposit_info")
    if deposit_info:
        event_summary["deposit_info"] = {
            "deposit_required": deposit_info.get("deposit_required", False),
            "deposit_amount": deposit_info.get("deposit_amount"),
            "deposit_vat_included": deposit_info.get("deposit_vat_included"),
            "deposit_due_date": deposit_info.get("deposit_due_date"),
            "deposit_paid": deposit_info.get("deposit_paid", False),
            "deposit_paid_at": deposit_info.get("deposit_paid_at"),
        }

    return event_summary


# --- Route Handlers ---

@router.get("/pending")
async def get_pending_tasks():
    """OpenEvent Action (light-blue): expose pending manual tasks for GUI approvals."""
    try:
        db = wf_load_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load tasks: {exc}") from exc

    tasks = wf_list_pending_tasks(db)
    events_by_id = {event.get("event_id"): event for event in db.get("events") or [] if event.get("event_id")}
    payload = []
    offer_tasks_indices: Dict[tuple[str, str], int] = {}

    for task in tasks:
        payload_data = task.get("payload") or {}
        event_entry = events_by_id.get(task.get("event_id"))
        event_data = (event_entry or {}).get("event_data") or {}
        draft_body = payload_data.get("draft_body") or payload_data.get("draft_msg")

        if not draft_body and event_entry:
            for request in event_entry.get("pending_hil_requests") or []:
                if request.get("task_id") == task.get("task_id"):
                    draft_body = (request.get("draft") or {}).get("body") or draft_body
                    break

        event_summary = _build_event_summary(event_entry)

        record = {
            "task_id": task.get("task_id"),
            "type": task.get("type"),
            "client_id": task.get("client_id"),
            "event_id": task.get("event_id"),
            "created_at": task.get("created_at"),
            "notes": task.get("notes"),
            "payload": {
                "snippet": payload_data.get("snippet"),
                "draft_body": draft_body,
                "suggested_dates": payload_data.get("suggested_dates"),
                "thread_id": payload_data.get("thread_id"),
                "step_id": payload_data.get("step_id") or payload_data.get("step"),
                "event_summary": event_summary,
            },
        }
        payload.append(record)
        if task.get("type") == "offer_message" and payload_data.get("thread_id"):
            key = (task.get("event_id"), payload_data.get("thread_id"))
            offer_tasks_indices[key] = len(payload) - 1

    # Deduplicate per (event, thread) by priority so only one task shows in the manager panel.
    priority = {
        "offer_message": 0,
        "room_availability_message": 1,
        "date_confirmation_message": 2,
        "ask_for_date": 3,
        "manual_review": 4,
    }
    dedup: Dict[tuple[str, str], Dict[str, Any]] = {}
    for record in payload:
        thread_id = (record.get("payload") or {}).get("thread_id")
        event_id = record.get("event_id")
        key = (event_id, thread_id)
        rank = priority.get(record.get("type"), 99)
        current = dedup.get(key)
        if current is None or priority.get(current.get("type"), 99) > rank:
            dedup[key] = record
    payload = list(dedup.values())

    return {"tasks": payload}


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as approved from the GUI.

    For AI Reply Approval tasks, the manager can optionally edit the draft message
    before sending by providing `edited_message` in the request body.
    """
    try:
        result = wf_approve_task_and_send(
            task_id,
            manager_notes=request.notes,
            edited_message=request.edited_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to approve task: {exc}") from exc
    print(f"[WF] task approved id={task_id}")
    assistant_text = result.get("res", {}).get("assistant_draft_text")
    return {
        "task_id": task_id,
        "task_status": "approved",
        "assistant_reply": assistant_text,
        "thread_id": result.get("thread_id"),
        "event_id": result.get("event_id"),
        "review_state": "approved",
    }


@router.post("/{task_id}/reject")
async def reject_task(task_id: str, request: TaskDecisionRequest):
    """OpenEvent Action (light-blue): mark a task as rejected from the GUI."""
    try:
        result = wf_reject_task_and_send(task_id, manager_notes=request.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reject task: {exc}") from exc
    print(f"[WF] task rejected id={task_id}")
    assistant_text = result.get("res", {}).get("assistant_draft_text")
    return {
        "task_id": task_id,
        "task_status": "rejected",
        "assistant_reply": assistant_text,
        "thread_id": result.get("thread_id"),
        "event_id": result.get("event_id"),
        "review_state": "rejected",
    }


@router.post("/cleanup")
async def cleanup_tasks(request: TaskCleanupRequest):
    """Remove resolved HIL tasks to declutter the task list."""
    try:
        db = wf_load_db()
        removed = wf_cleanup_tasks(db, keep_thread_id=request.keep_thread_id)
        wf_save_db(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup tasks: {exc}") from exc
    print(f"[WF] tasks cleanup removed={removed}")
    return {"removed": removed}
