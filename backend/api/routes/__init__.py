"""
MODULE: backend/api/routes/__init__.py
PURPOSE: FastAPI route handlers organized by domain.

CONTAINS:
    - tasks.py       HIL task management (/api/tasks/*)
    - events.py      Event operations (/api/event/*, /api/events/*)
    - config.py      Configuration (/api/config/*)
    - clients.py     Client operations (/api/client/*)
    - debug.py       Debug and tracing (/api/debug/*)
    - snapshots.py   Snapshot storage (/api/snapshots/*)
    - test_data.py   Test data and Q&A (/api/test-data/*, /api/qna)
    - workflow.py    Workflow status (/api/workflow/*)
    - messages.py    Message and conversation handling (/api/send-message, /api/conversation/*)

MIGRATION STATUS:
    Phase C of refactoring - complete.
    main.py reduced from 2188 → ~600 lines.
"""

from .tasks import router as tasks_router
from .events import router as events_router
from .config import router as config_router
from .clients import router as clients_router
from .debug import router as debug_router
from .snapshots import router as snapshots_router
from .test_data import router as test_data_router
from .workflow import router as workflow_router
from .messages import router as messages_router

__all__ = [
    "tasks_router",
    "events_router",
    "config_router",
    "clients_router",
    "debug_router",
    "snapshots_router",
    "test_data_router",
    "workflow_router",
    "messages_router",
]
