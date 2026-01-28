"""
MODULE: activity/__init__.py
PURPOSE: AI Activity Logger - Progress tracking and activity transformation.

Provides:
- Progress bar showing workflow stages (date → room → offer → deposit → confirmed)
- Activity window with two granularity levels (high-level vs detailed)
- Per-message logging of AI actions
- Persistence of manager-relevant activities to event database

DESIGN DECISIONS:
- High-level activities persisted to event_entry["activity_log"] for manager tracing
- Real-time activities from TraceBus (in-memory, for debugging)
- Granularity filter: "high" = manager-visible, "detailed" = dev-only
- Timestamps in local timezone for manager convenience
"""

from .types import Activity, ProgressStage, Progress, Granularity
from .progress import get_progress, STEP_TO_STAGE
from .transformer import transform_trace_to_activity, get_activities_for_event
from .persistence import (
    log_activity,
    log_workflow_activity,
    get_persisted_activities,
    WORKFLOW_ACTIVITIES,
)

__all__ = [
    # Types
    "Activity",
    "ProgressStage",
    "Progress",
    "Granularity",
    # Progress
    "get_progress",
    "STEP_TO_STAGE",
    # Transform (real-time from TraceBus)
    "transform_trace_to_activity",
    "get_activities_for_event",
    # Persistence (to database)
    "log_activity",
    "log_workflow_activity",
    "get_persisted_activities",
    "WORKFLOW_ACTIVITIES",
]
