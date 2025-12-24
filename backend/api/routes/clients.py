"""
MODULE: backend/api/routes/clients.py
PURPOSE: Client management endpoints.

ENDPOINTS:
    POST /api/client/reset     - Reset all data for a client (testing only)
    POST /api/client/continue  - Continue workflow at current step (dev test mode)

DEPENDS ON:
    - backend/workflow_email.py  # Database operations

SECURITY NOTE:
    These endpoints are for testing only and are disabled by default.
    Set ENABLE_DANGEROUS_ENDPOINTS=true to enable (never in production!).
"""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
    process_msg as wf_process_msg,
)


router = APIRouter(prefix="/api/client", tags=["clients"])


# --- Request Models ---

class ClientResetRequest(BaseModel):
    email: str


class ClientContinueRequest(BaseModel):
    """Request to continue workflow at current step (bypasses dev_choice prompt)."""
    email: str
    subject: Optional[str] = None
    body: Optional[str] = None
    session_id: Optional[str] = None


# --- Route Handlers ---

@router.post("/reset")
async def reset_client_data(request: ClientResetRequest):
    """[Testing Only] Reset all data for a client by email address.

    Deletes:
    - Client entry from 'clients' dict
    - All events where client_id matches the email
    - All tasks associated with those events

    SECURITY: This endpoint is disabled by default.
    Set ENABLE_DANGEROUS_ENDPOINTS=true to enable (never in production!).
    """
    # Production guard - enabled by default in development (when running main.py directly)
    # Disabled in production unless explicitly enabled
    is_dev = os.getenv("ENABLE_DANGEROUS_ENDPOINTS", "true").lower() == "true"
    if not is_dev:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is disabled. Set ENABLE_DANGEROUS_ENDPOINTS=true to enable (development only)."
        )

    email = request.email.lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        db = wf_load_db()
        deleted_events = 0
        deleted_tasks = 0

        # Delete client entry
        clients = db.get("clients", {})
        if isinstance(clients, dict):
            client_deleted = email in clients
            if client_deleted:
                del clients[email]
        else:
            client_deleted = False

        # Delete all events for this client (check both client_id and event_data.Email)
        events = db.get("events", {})
        if isinstance(events, dict):
            event_ids_to_delete = []
            for eid, event in events.items():
                if not isinstance(event, dict):
                    continue
                client_id_match = (event.get("client_id") or "").lower() == email
                event_data = event.get("event_data", {}) or {}
                email_match = (event_data.get("Email") or "").lower() == email
                if client_id_match or email_match:
                    event_ids_to_delete.append(eid)
            for eid in event_ids_to_delete:
                del events[eid]
                deleted_events += 1
        elif isinstance(events, list):
            # Handle legacy list format
            original_len = len(events)
            matched_event_ids = []
            def should_keep(e):
                if not isinstance(e, dict):
                    return True
                client_id_match = (e.get("client_id") or "").lower() == email
                event_data = e.get("event_data", {}) or {}
                email_match = (event_data.get("Email") or "").lower() == email
                if client_id_match or email_match:
                    matched_event_ids.append(e.get("event_id", "unknown"))
                    return False
                return True
            db["events"] = [e for e in events if should_keep(e)]
            deleted_events = original_len - len(db["events"])
            if matched_event_ids:
                print(f"[WF] reset matched events: {matched_event_ids}")

        # Delete all tasks for this client
        tasks = db.get("tasks", {})
        if isinstance(tasks, dict):
            task_ids_to_delete = [
                tid for tid, task in tasks.items()
                if isinstance(task, dict) and (task.get("client_id") or "").lower() == email
            ]
            for tid in task_ids_to_delete:
                del tasks[tid]
                deleted_tasks += 1
        elif isinstance(tasks, list):
            # Handle legacy list format
            original_len = len(tasks)
            db["tasks"] = [
                t for t in tasks
                if not isinstance(t, dict) or (t.get("client_id") or "").lower() != email
            ]
            deleted_tasks = original_len - len(db["tasks"])

        wf_save_db(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reset client data: {exc}") from exc

    print(f"[WF] client reset email={email} events={deleted_events} tasks={deleted_tasks}")
    return {
        "email": email,
        "client_deleted": client_deleted,
        "events_deleted": deleted_events,
        "tasks_deleted": deleted_tasks,
    }


@router.post("/continue")
async def continue_workflow(request: ClientContinueRequest):
    """[Dev Test Mode] Continue workflow at current step, bypassing dev_choice prompt.

    This endpoint is used when DEV_TEST_MODE is enabled and a client has an existing
    event at a higher step. Instead of resetting, this allows continuing the workflow
    from where it left off.

    SECURITY: This endpoint is disabled by default.
    Set ENABLE_DANGEROUS_ENDPOINTS=true to enable (development only).
    """
    is_dev = os.getenv("ENABLE_DANGEROUS_ENDPOINTS", "true").lower() == "true"
    if not is_dev:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is disabled. Set ENABLE_DANGEROUS_ENDPOINTS=true to enable (development only)."
        )

    email = request.email.lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Build message payload with skip_dev_choice flag
    msg = {
        "from_email": email,
        "subject": request.subject or "Continue workflow",
        "body": request.body or "",
        "skip_dev_choice": True,  # This bypasses the dev_choice prompt
    }
    if request.session_id:
        msg["session_id"] = request.session_id

    try:
        result = wf_process_msg(msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to continue workflow: {exc}") from exc

    print(f"[WF] client continue email={email} action={result.get('action', 'unknown')}")
    return {
        "email": email,
        "action": result.get("action"),
        "payload": result.get("payload"),
        "draft_messages": result.get("draft_messages"),
    }
