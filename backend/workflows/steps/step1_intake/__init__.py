"""
Step 1: Intake - Initial client contact and information gathering.

This step handles:
- Email intake and initial classification
- Entity extraction (date, participants, room preferences, etc.)
- Task creation for HIL review if needed

CANONICAL LOCATION: backend/workflows/steps/step1_intake/
MIGRATED FROM: backend/workflows/groups/intake/

Submodules:
    trigger/    - Main entry point (process function)
    condition/  - Gate checks (has_event_date, suggest_dates)
    llm/        - LLM-based analysis (classify_intent, extract_user_information)
    db_pers/    - Database persistence (enqueue_task, update_task_status)
"""

from .trigger.process import process
from .condition.checks import has_event_date, room_status_on_date, suggest_dates, blackout_days
from .llm.analysis import classify_intent, extract_user_information, sanitize_user_info
from .db_pers.tasks import enqueue_task, update_task_status

__all__ = [
    "process",
    "classify_intent",
    "extract_user_information",
    "sanitize_user_info",
    "has_event_date",
    "room_status_on_date",
    "suggest_dates",
    "blackout_days",
    "enqueue_task",
    "update_task_status",
]
