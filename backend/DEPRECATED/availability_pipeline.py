"""Compatibility shims for the legacy availability pipeline entrypoints."""

# DEPRECATED: Legacy wrapper. All Intake/Date/Availability logic lives under
# backend/workflows/groups/* and is orchestrated by backend.workflow_email.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.workflow_email import process_msg as wf_process_msg
from backend.workflows.steps.step3_room_availability import run_availability_workflow as advanced_run


def process_email(
    subject: str,
    body: str,
    from_email: str,
    from_name: str = "Not specified",
    ts: Optional[str] = None,
    msg_id: Optional[str] = None,
) -> Dict[str, Any]:
    """[Trigger] Build a workflow message payload and delegate to the orchestrator."""

    payload = {
        "msg_id": msg_id or "availability-shim",
        "from_name": from_name,
        "from_email": from_email,
        "subject": subject,
        "ts": ts or "1970-01-01T00:00:00Z",
        "body": body,
    }
    return wf_process_msg(payload)


def legacy_run_availability_workflow(
    event_id: str,
    calendar_adapter: Any,
    client_gui_adapter: Any,
    rooms_path: Optional[Path] = None,
) -> None:
    """[Trigger] Delegate the advanced availability workflow to its preserved module."""

    advanced_run(event_id, calendar_adapter, client_gui_adapter, rooms_path)


__all__ = ["process_email", "legacy_run_availability_workflow"]
