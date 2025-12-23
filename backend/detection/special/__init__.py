"""
MODULE: backend/detection/special/__init__.py
PURPOSE: Special case detection (manager requests, room conflicts, nonsense filtering).

CONTAINS:
    - manager_request.py  looks_like_manager_request() - escalation to human
    - room_conflict.py    detect_room_conflict() - booking conflicts
    - nonsense.py         check_nonsense_gate() - gibberish/off-topic filtering

MANAGER REQUEST DETECTION:
    Patterns: "speak to a manager", "talk to a real person", "escalate", etc.
    Result: Route to message_manager intent, not automated response

ROOM CONFLICT DETECTION:
    - SOFT conflict: Two clients have Option status on same room/date
    - HARD conflict: Client tries to confirm when another has Option
    Result: HIL task for manager resolution

NONSENSE GATE:
    Two-layer system:
    1. Regex gate (FREE) - catches pure gibberish like "asdfghjkl"
    2. Confidence check - low confidence + no workflow signal -> ignore

    Decision matrix:
    | Confidence | Workflow Signal | Action |
    |------------|-----------------|--------|
    | Any        | YES             | Proceed |
    | < 0.15     | NO              | IGNORE (silent) |
    | 0.15-0.25  | NO              | Defer to HIL |
    | >= 0.25    | NO              | Proceed |

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # Manager request patterns
    - backend/workflows/io/database.py       # For conflict checking

USED BY:
    - backend/workflows/steps/step1_intake/            # Manager request detection
    - backend/workflows/steps/step3_room_availability/ # Conflict detection
    - backend/workflows/steps/step7_confirmation/      # Conflict resolution
    - All steps: Nonsense gate

EXPORTS:
    - looks_like_manager_request(text) -> bool
    - detect_room_conflict(event_id, room_id, date) -> ConflictResult
    - check_nonsense_gate(confidence, message) -> str  # "proceed" | "ignore" | "hil"

RELATED TESTS:
    - backend/tests/detection/test_manager_request.py
    - backend/tests/flow/test_room_conflict.py
    - backend/tests/detection/test_low_confidence_handling.py
"""

# Room conflict detection (migrated from workflows/common/conflict.py)
from .room_conflict import (
    # Enums
    ConflictType,
    # Core detection
    detect_room_conflict,
    detect_conflict_type,
    get_available_rooms_on_date,
    # Conflict handling
    handle_soft_conflict,
    handle_hard_conflict,
    handle_loser_event,
    resolve_conflict,
    notify_conflict_resolution,
    # Message composition
    compose_conflict_warning_message,
    compose_soft_conflict_warning,
    compose_hard_conflict_block,
    compose_winner_message,
    compose_conflict_hil_task,
)

__all__ = [
    # Room conflict
    "ConflictType",
    "detect_room_conflict",
    "detect_conflict_type",
    "get_available_rooms_on_date",
    "handle_soft_conflict",
    "handle_hard_conflict",
    "handle_loser_event",
    "resolve_conflict",
    "notify_conflict_resolution",
    "compose_conflict_warning_message",
    "compose_soft_conflict_warning",
    "compose_hard_conflict_block",
    "compose_winner_message",
    "compose_conflict_hil_task",
]
