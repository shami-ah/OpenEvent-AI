from __future__ import annotations

from typing import Any, Dict, Optional

from backend.domain import TaskStatus, TaskType
from backend.workflows.io.tasks import enqueue_task as _enqueue_task
from backend.workflows.io.tasks import update_task_status as _update_task_status

__workflow_role__ = "db_pers"


def enqueue_task(
    db: Dict[str, Any],
    task_type: TaskType,
    client_id: str,
    linked_event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Generic helper to queue workflow tasks."""

    return _enqueue_task(db, task_type, client_id, linked_event_id, payload)


def enqueue_manual_review_task(
    db: Dict[str, Any],
    client_id: str,
    linked_event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Queue a manual review task for non-event inquiries."""

    return _enqueue_task(db, TaskType.MANUAL_REVIEW, client_id, linked_event_id, payload)


def enqueue_missing_event_date_task(
    db: Dict[str, Any],
    client_id: str,
    linked_event_id: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """[OpenEvent Action] Queue a task requesting the client to confirm an event date."""

    return _enqueue_task(
        db,
        TaskType.REQUEST_MISSING_EVENT_DATE,
        client_id,
        linked_event_id,
        payload,
    )


def update_task_status(
    db: Dict[str, Any], task_id: str, status: str | TaskStatus, notes: Optional[str] = None
) -> None:
    """[OpenEvent Action] Update workflow tasks with human decisions."""

    _update_task_status(db, task_id, status, notes)
