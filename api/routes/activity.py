"""
MODULE: api/routes/activity.py
PURPOSE: AI Activity Logger API endpoints.

ENDPOINTS:
    GET  /api/events/{event_id}/progress   - Get workflow progress bar state
    GET  /api/events/{event_id}/activity   - Get activity log with granularity filter

These endpoints provide real-time visibility into:
- Where the booking is in the workflow (progress)
- What the AI has done (activity)

DESIGN:
- "high" granularity: Uses persisted activities from database (survives restarts)
- "detailed" granularity: Uses real-time TraceBus (for debugging, lost on restart)
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from activity import get_progress
from activity.persistence import get_persisted_activities
from workflow_email import load_db as wf_load_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["activity"])


@router.get("/api/events/{event_id}/progress")
async def get_event_progress(event_id: str):
    """
    Get workflow progress for an event.

    Returns a progress bar representation showing:
    - Current workflow stage (date/room/offer/deposit/confirmed)
    - Status of each stage (completed/active/pending)
    - Overall percentage completion

    Example response:
    {
        "current_stage": "room",
        "stages": [
            {"id": "date", "label": "Date", "status": "completed", "icon": "📅"},
            {"id": "room", "label": "Room", "status": "active", "icon": "🏢"},
            ...
        ],
        "percentage": 40
    }
    """
    try:
        db = wf_load_db()
        events = db.get("events") or []

        event_entry = None
        for event in events:
            if event.get("event_id") == event_id:
                event_entry = event
                break

        if not event_entry:
            raise HTTPException(status_code=404, detail="Event not found")

        progress = get_progress(event_entry)
        return progress.to_dict()

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get progress for event %s: %s", event_id, exc)
        raise HTTPException(status_code=500, detail="Failed to get progress")


@router.get("/api/events/{event_id}/activity")
async def get_event_activity(
    event_id: str,
    granularity: Literal["high", "detailed"] = Query(
        default="high",
        description="Activity detail level: 'high' for manager-friendly (persisted), 'detailed' for debugging (real-time)"
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of activities to return"
    ),
):
    """
    Get activity log for an event.

    Returns a list of AI actions taken for this event, filtered by granularity:
    - "high": Manager-friendly events from database (persists across restarts)
    - "detailed": All events from real-time trace (for debugging, lost on restart)

    Example response:
    {
        "activities": [
            {
                "id": "act_123",
                "timestamp": "2025-01-28T10:30:00",
                "icon": "📅",
                "title": "Date Confirmed",
                "detail": "March 15, 2025"
            }
        ],
        "has_more": false
    }
    """
    try:
        db = wf_load_db()
        events = db.get("events") or []

        event_entry = None
        for event in events:
            if event.get("event_id") == event_id:
                event_entry = event
                break

        if not event_entry:
            raise HTTPException(status_code=404, detail="Event not found")

        # Both granularities use persisted activities from database
        # "high" = coarse (main milestones), "detailed" = fine (all steps)
        activities = get_persisted_activities(
            event_entry,
            limit=limit + 1,
            granularity=granularity,
        )
        has_more = len(activities) > limit
        if has_more:
            activities = activities[:limit]

        return {
            "activities": activities,  # Already dicts
            "has_more": has_more,
            "event_id": event_id,
            "granularity": granularity,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get activity for event %s: %s", event_id, exc)
        raise HTTPException(status_code=500, detail="Failed to get activity")
