from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from backend.workflows.steps.step3_room_availability.condition.decide import room_status_on_date
from backend.workflows.steps.step3_room_availability.trigger.process import (
    evaluate_room_statuses,
    _flatten_statuses,  # type: ignore
    ROOM_OUTCOME_AVAILABLE,
    ROOM_OUTCOME_OPTION,
)
from backend.workflows.common.capacity import fits_capacity

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_room_status_on_date": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": r"^\\d{2}\\.\\d{2}\\.\\d{4}$"},
            "room": {"type": "string"},
        },
        "required": ["date", "room"],
        "additionalProperties": False,
    },
    "tool_capacity_check": {
        "type": "object",
        "properties": {
            "room": {"type": "string"},
            "attendees": {"type": ["integer", "null"], "minimum": 1},
            "layout": {"type": ["string", "null"]},
        },
        "required": ["room"],
        "additionalProperties": False,
    },
    "tool_evaluate_rooms": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": r"^\\d{2}\\.\\d{2}\\.\\d{4}$"},
        },
        "required": ["date"],
        "additionalProperties": False,
    },
}


class RoomStatusInput(BaseModel):
    date: str = Field(..., description="Requested date in DD.MM.YYYY format.")
    room: Optional[str] = Field(None, description="Specific room to evaluate.")

    @validator("date")
    def _validate_date(cls, value: str) -> str:
        if len(value) != 10 or value[2] != "." or value[5] != ".":
            raise ValueError("date must be DD.MM.YYYY")
        return value


class RoomStatusOutput(BaseModel):
    status: str


def tool_room_status_on_date(db: Dict[str, Any], params: RoomStatusInput) -> RoomStatusOutput:
    """Return the availability status for a specific room/date combination."""

    if not params.room:
        raise ValueError("room must be provided to evaluate availability")
    status = room_status_on_date(db, params.date, params.room)
    return RoomStatusOutput(status=status)


class EvaluateRoomsInput(BaseModel):
    date: str

    @validator("date")
    def _validate_date(cls, value: str) -> str:
        if len(value) != 10 or value[2] != "." or value[5] != ".":
            raise ValueError("date must be DD.MM.YYYY")
        return value


class EvaluateRoomsOutput(BaseModel):
    status_map: Dict[str, str]
    recommended_room: Optional[str]
    summary_lines: List[str]


def tool_evaluate_rooms(db: Dict[str, Any], params: EvaluateRoomsInput) -> EvaluateRoomsOutput:
    """
    Evaluate all rooms for the given date using existing workflow logic.

    The deterministic workflow multiplies this information into the conversation
    turn; the agent layer simply packages it for LLM consumption.
    """

    room_statuses = evaluate_room_statuses(db, params.date)
    status_map = _flatten_statuses(room_statuses)
    available = [room for room, status in status_map.items() if status == ROOM_OUTCOME_AVAILABLE]
    options = [room for room, status in status_map.items() if status == ROOM_OUTCOME_OPTION]
    recommended = (available or options or [None])[0]

    summary = [f"{room}: {status}" for room, status in status_map.items()]
    return EvaluateRoomsOutput(
        status_map=status_map,
        recommended_room=recommended,
        summary_lines=summary,
    )


class CapacityCheckInput(BaseModel):
    room: str = Field(..., description="Room identifier.")
    attendees: Optional[int]
    layout: Optional[str]


class CapacityCheckOutput(BaseModel):
    fits: bool
    message: str


def tool_capacity_check(params: CapacityCheckInput) -> CapacityCheckOutput:
    """
    Thin wrapper around fits_capacity ensuring deterministic phrasing for the agent.
    """

    fits = fits_capacity(params.room, params.attendees, params.layout)
    if fits:
        msg = "Configuration fits within the room limits."
    else:
        descriptor = f"{params.attendees} guests" if params.attendees else "the requested headcount"
        if params.layout:
            descriptor = f"{descriptor} in {params.layout}"
        msg = f"{params.room} cannot host {descriptor}."
    return CapacityCheckOutput(fits=fits, message=msg)


# Backwards compatibility with legacy agent scaffolding.
tool_room_status = tool_room_status_on_date
