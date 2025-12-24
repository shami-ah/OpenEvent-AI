"""
Step 3: Room Availability - Check room availability and manage room selection.

This step handles:
- Checking room availability for confirmed dates
- Evaluating room capacity against participant counts
- Managing room selection and conflicts
- Generating availability summaries

CANONICAL LOCATION: backend/workflows/steps/step3_room_availability/
MIGRATED FROM: backend/workflows/groups/room_availability/

Submodules:
    trigger/    - Main entry point (process function)
    condition/  - Gate checks (room_status_on_date)
    llm/        - LLM-based analysis (summarize_room_statuses)
    db_pers/    - Database persistence and room configuration
"""

from .trigger.process import handle_select_room_action, evaluate_room_statuses, process
from .condition.decide import room_status_on_date
from .llm.analysis import summarize_room_statuses
from .db_pers.advanced import (
    RequestedWindow,
    append_log,
    build_candidate_rooms,
    build_options_for_reply,
    build_requested_windows,
    choose_decision,
    collect_conflicts,
    compose_reply,
    derive_room_label,
    ensure_comms,
    ensure_logs,
    evaluate_candidate_rooms,
    evaluate_room,
    format_date_label,
    human_review,
    load_rooms_config,
    near_miss_suggestions,
    now_iso,
    outcome_from_decision,
    overlaps,
    parse_date,
    parse_iso_datetime,
    parse_participants,
    parse_time,
    room_capacity_ok,
    run_availability_workflow,
    select_best_fit,
    to_display_date,
    to_display_time,
    to_utc,
)

__all__ = [
    "process",
    "room_status_on_date",
    "summarize_room_statuses",
    "RequestedWindow",
    "now_iso",
    "parse_date",
    "parse_time",
    "parse_iso_datetime",
    "to_utc",
    "overlaps",
    "to_display_time",
    "to_display_date",
    "format_date_label",
    "load_rooms_config",
    "ensure_logs",
    "append_log",
    "build_requested_windows",
    "parse_participants",
    "build_candidate_rooms",
    "room_capacity_ok",
    "collect_conflicts",
    "near_miss_suggestions",
    "evaluate_room",
    "evaluate_candidate_rooms",
    "choose_decision",
    "select_best_fit",
    "outcome_from_decision",
    "build_options_for_reply",
    "derive_room_label",
    "ensure_comms",
    "human_review",
    "compose_reply",
    "run_availability_workflow",
    "evaluate_room_statuses",
    "handle_select_room_action",
]
