"""
MODULE: activity/progress.py
PURPOSE: Convert current_step to progress bar representation.

Maps the 7-step workflow to 5 user-friendly stages:
  date → room → offer → deposit → confirmed
"""

from typing import Any, Dict, List, Optional

from .types import Progress, ProgressStage


# Stage definitions with icons
STAGE_DEFINITIONS = [
    {"id": "date", "label": "Date", "icon": "📅"},
    {"id": "room", "label": "Room", "icon": "🏢"},
    {"id": "offer", "label": "Offer", "icon": "📄"},
    {"id": "deposit", "label": "Deposit", "icon": "💳"},
    {"id": "confirmed", "label": "Confirmed", "icon": "✅"},
]


# Map current_step (1-7) to stage ID and percentage
STEP_TO_STAGE: Dict[int, Dict[str, Any]] = {
    1: {"stage": "date", "percentage": 0},
    2: {"stage": "date", "percentage": 20},
    3: {"stage": "room", "percentage": 40},
    4: {"stage": "offer", "percentage": 60},
    5: {"stage": "deposit", "percentage": 70},
    6: {"stage": "deposit", "percentage": 80},
    7: {"stage": "confirmed", "percentage": 100},
}


def get_progress(event_entry: Optional[Dict[str, Any]]) -> Progress:
    """
    Get progress state from an event database entry.

    Args:
        event_entry: Event dict from workflow database, or None

    Returns:
        Progress object with current stage and percentage

    Example:
        >>> entry = {"current_step": 3}
        >>> progress = get_progress(entry)
        >>> progress.current_stage
        'room'
        >>> progress.percentage
        40
    """
    if not event_entry:
        return _build_progress("date", 0)

    current_step = event_entry.get("current_step", 1)

    # Clamp step to valid range
    if current_step < 1:
        current_step = 1
    elif current_step > 7:
        current_step = 7

    step_info = STEP_TO_STAGE.get(current_step, {"stage": "date", "percentage": 0})

    return _build_progress(step_info["stage"], step_info["percentage"])


def _build_progress(current_stage_id: str, percentage: int) -> Progress:
    """Build Progress object with all stages marked appropriately."""
    stages: List[ProgressStage] = []
    found_current = False

    for stage_def in STAGE_DEFINITIONS:
        stage_id = stage_def["id"]

        if stage_id == current_stage_id:
            status = "active"
            found_current = True
        elif found_current:
            status = "pending"
        else:
            status = "completed"

        stages.append(ProgressStage(
            id=stage_id,
            label=stage_def["label"],
            status=status,
            icon=stage_def["icon"],
        ))

    return Progress(
        current_stage=current_stage_id,
        stages=stages,
        percentage=percentage,
    )


def get_progress_summary(event_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get a minimal progress summary for API responses.

    Returns dict suitable for embedding in send-message response:
        {"current_stage": "room", "percentage": 40}
    """
    progress = get_progress(event_entry)
    return {
        "current_stage": progress.current_stage,
        "percentage": progress.percentage,
    }
