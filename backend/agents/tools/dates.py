from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflow_email import process_msg as workflow_process_msg

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_suggest_dates": {
        "type": "object",
        "properties": {
            "event_id": {"type": ["string", "null"]},
            "preferred_room": {"type": ["string", "null"]},
            "start_from_iso": {"type": ["string", "null"]},
            "days_ahead": {"type": "integer", "minimum": 1, "maximum": 120},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "additionalProperties": False,
    },
    "tool_parse_date_intent": {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
        "required": ["message"],
        "additionalProperties": False,
    },
}


class SuggestDatesInput(BaseModel):
    event_id: Optional[str]
    preferred_room: Optional[str] = Field(None, description="Room to evaluate availability for.")
    start_from_iso: Optional[str] = Field(None, description="ISO timestamp seed (defaults to now).")
    days_ahead: int = Field(45, ge=1, le=120)
    max_results: int = Field(5, ge=1, le=10)


class SuggestDatesOutput(BaseModel):
    candidate_dates: List[str] = Field(default_factory=list)

    @validator("candidate_dates", each_item=True)
    def _format(cls, value: str) -> str:
        if len(value) != 10 or value[2] != "." or value[5] != ".":
            raise ValueError("Dates must be formatted as DD.MM.YYYY")
        return value


def tool_suggest_dates(db: Dict[str, Any], params: SuggestDatesInput) -> SuggestDatesOutput:
    """Thin wrapper over suggest_dates to satisfy agent tool expectations."""

    start_iso = params.start_from_iso or datetime.utcnow().isoformat()
    preferred = params.preferred_room or "Room A"
    dates = suggest_dates(
        db,
        preferred_room=preferred,
        start_from_iso=start_iso,
        days_ahead=params.days_ahead,
        max_results=params.max_results,
    )
    return SuggestDatesOutput(candidate_dates=dates)


class PersistConfirmedDateInput(BaseModel):
    event_id: str
    chosen_date: str
    start_time: Optional[str]
    end_time: Optional[str]
    message_id: Optional[str]

    @validator("chosen_date")
    def _validate_date(cls, value: str) -> str:
        if len(value) != 10 or value[2] != "." or value[5] != ".":
            raise ValueError("chosen_date must be DD.MM.YYYY")
        return value


class PersistConfirmedDateOutput(BaseModel):
    chosen_date_iso: str


def tool_persist_confirmed_date(params: PersistConfirmedDateInput) -> PersistConfirmedDateOutput:
    """
    Persist the confirmed date by replaying the workflow router.

    The agent layer should ensure this tool is only invoked when the date is ready
    to be locked in. We reuse workflow_email.process_msg to avoid bypassing
    debounced persistence logic.
    """

    iso_date = to_iso_date(params.chosen_date)
    if not iso_date:
        raise ValueError("Unable to convert chosen_date to ISO format")

    synthetic_message = {
        "msg_id": params.message_id or f"agent-confirm-{datetime.utcnow().timestamp()}",
        "from_name": "Agent",
        "from_email": "agent@openevent.ai",
        "subject": f"Agent confirms {params.chosen_date}",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": f"The client confirms {params.chosen_date}.",
    }
    workflow_process_msg(synthetic_message)
    return PersistConfirmedDateOutput(chosen_date_iso=iso_date)


DATE_PATTERN = re.compile(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b")


class ParseDateIntentInput(BaseModel):
    message: str = Field(..., description="Raw client message text.")


class ParseDateIntentOutput(BaseModel):
    candidates: List[str] = Field(default_factory=list)


def tool_parse_date_intent(params: ParseDateIntentInput) -> ParseDateIntentOutput:
    """
    Lightweight date extractor used during Step 2 to seed deterministic checks.
    """

    matches = DATE_PATTERN.findall(params.message or "")
    normalised: List[str] = []
    for value in matches:
        cleaned = value.replace("/", ".")
        parts = cleaned.split(".")
        if len(parts) != 3:
            continue
        day, month, year = parts
        if len(day) == 1:
            day = f"0{day}"
        if len(month) == 1:
            month = f"0{month}"
        if len(year) == 2:
            year = f"20{year}"
        formatted = f"{day}.{month}.{year}"
        if formatted not in normalised:
            normalised.append(formatted)
    return ParseDateIntentOutput(candidates=normalised)
