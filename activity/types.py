"""
MODULE: activity/types.py
PURPOSE: Core data types for AI Activity Logger.

Contains:
- Activity: Individual action taken by the AI
- ProgressStage: One stage in the progress bar
- Progress: Complete progress state
- Granularity: Filter level for activities
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional


Granularity = Literal["high", "detailed"]


@dataclass
class Activity:
    """A single AI activity event for display in the activity window.

    Attributes:
        id: Unique identifier (e.g., "act_123")
        timestamp: ISO 8601 timestamp
        icon: Emoji icon for visual representation
        title: Short action title (e.g., "Date Confirmed")
        detail: Longer description with context
        granularity: "high" for manager-friendly, "detailed" for debugging
    """
    id: str
    timestamp: str
    icon: str
    title: str
    detail: str
    granularity: Granularity = "high"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "icon": self.icon,
            "title": self.title,
            "detail": self.detail,
            "granularity": self.granularity,
        }


@dataclass
class ProgressStage:
    """A single stage in the workflow progress bar.

    Attributes:
        id: Stage identifier (e.g., "date", "room")
        label: Display label (e.g., "Date", "Room")
        status: "completed", "active", or "pending"
        icon: Emoji icon for the stage
    """
    id: str
    label: str
    status: Literal["completed", "active", "pending"]
    icon: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "icon": self.icon,
        }


@dataclass
class Progress:
    """Complete workflow progress state.

    Attributes:
        current_stage: ID of the currently active stage
        stages: Ordered list of all stages
        percentage: Progress percentage (0-100)
    """
    current_stage: str
    stages: List[ProgressStage] = field(default_factory=list)
    percentage: int = 0

    def to_dict(self) -> dict:
        return {
            "current_stage": self.current_stage,
            "stages": [s.to_dict() for s in self.stages],
            "percentage": self.percentage,
        }
