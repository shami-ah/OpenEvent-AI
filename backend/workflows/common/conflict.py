"""
DEPRECATED: This module has been migrated to backend/detection/special/room_conflict.py

Please update your imports:
    OLD: from backend.workflows.common.conflict import ...
    NEW: from backend.detection.special.room_conflict import ...

This file will be removed in a future release.
---

Room conflict detection and resolution for the booking workflow.

Two conflict scenarios:

SCENARIO A: Option + Option (Soft Conflict)
- Client 2 selects room already Option for Client 1
- Both become Option
- Client 2 receives soft warning
- NO HIL task (yet)
- Manager sees both on calendar

SCENARIO B: Option + Confirm (Hard Conflict)
- Client 2 tries to CONFIRM when Client 1 has Option
- HIL task created automatically
- Manager must decide who gets the room
- Loser redirected to Step 2 or 3

Implements first-come-first-served with manager override.
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ConflictType(Enum):
    """Type of room conflict."""
    NONE = "none"
    SOFT = "soft"  # Option + Option
    HARD = "hard"  # Option + Confirm or Confirmed + anything


def detect_room_conflict(
    db: Dict[str, Any],
    event_id: str,
    room_id: str,
    event_date: str,
) -> Optional[Dict[str, Any]]:
    """
    Check if another event already has this room locked (Option/Confirmed) on this date.

    Args:
        db: The database dict
        event_id: Current event ID (to exclude from conflict check)
        room_id: Room being requested
        event_date: Date being requested (ISO format YYYY-MM-DD)

    Returns:
        Dict with conflict info if conflict exists, None otherwise.
        {
            "conflicting_event_id": str,
            "conflicting_client_email": str,
            "conflicting_client_name": str,
            "room_id": str,
            "event_date": str,
            "status": str  # "Option" or "Confirmed"
        }
    """
    events = db.get("events") or {}

    for other_event_id, other_event in events.items():
        # Skip self
        if other_event_id == event_id:
            continue

        # Check if same room
        other_locked_room = other_event.get("locked_room_id")
        if not other_locked_room:
            continue
        if str(other_locked_room).lower() != str(room_id).lower():
            continue

        # Check if same date
        other_date = other_event.get("chosen_date") or other_event.get("Event Date")
        if not other_date:
            continue
        if str(other_date) != str(event_date):
            continue

        # Check status - only conflict if Option or Confirmed
        other_status = other_event.get("status") or other_event.get("Status") or "Lead"
        if other_status.lower() not in ("option", "confirmed"):
            continue

        # Found a conflict!
        other_client_id = other_event.get("client_id")
        other_client = {}
        if other_client_id:
            clients = db.get("clients") or {}
            other_client = clients.get(other_client_id) or {}

        return {
            "conflicting_event_id": other_event_id,
            "conflicting_client_email": other_client.get("email") or other_event.get("client_email"),
            "conflicting_client_name": other_client.get("name") or other_event.get("client_name"),
            "room_id": room_id,
            "event_date": event_date,
            "status": other_status,
        }

    return None


def get_available_rooms_on_date(
    db: Dict[str, Any],
    event_id: str,
    event_date: str,
    exclude_statuses: Optional[List[str]] = None,
) -> List[str]:
    """
    Get rooms that are NOT locked (Option/Confirmed) by other events on this date.

    Args:
        db: The database dict
        event_id: Current event ID (to exclude from check)
        event_date: Date to check
        exclude_statuses: Statuses to exclude (default: ["option", "confirmed"])

    Returns:
        List of available room IDs
    """
    if exclude_statuses is None:
        exclude_statuses = ["option", "confirmed"]

    # Get all rooms
    rooms_data = db.get("rooms") or {}
    all_rooms = set(rooms_data.keys())

    # Find rooms locked by other events on this date
    events = db.get("events") or {}
    locked_rooms = set()

    for other_event_id, other_event in events.items():
        if other_event_id == event_id:
            continue

        other_date = other_event.get("chosen_date") or other_event.get("Event Date")
        if str(other_date) != str(event_date):
            continue

        other_status = (other_event.get("status") or other_event.get("Status") or "").lower()
        if other_status not in exclude_statuses:
            continue

        other_room = other_event.get("locked_room_id")
        if other_room:
            locked_rooms.add(str(other_room).lower())

    # Return rooms not locked
    available = [r for r in all_rooms if str(r).lower() not in locked_rooms]
    return available


def compose_conflict_warning_message(
    room_name: str,
    event_date: str,
) -> str:
    """
    Compose the automatic warning message when conflict is detected.
    """
    return (
        f"I should let you know that someone else already has a provisional reservation (Option) "
        f"for {room_name} on {event_date}. "
        f"\n\nI'd recommend choosing a different room or date to avoid any complications. "
        f"However, if you have a special reason why you really need this specific room on this date "
        f"(for example, it's a birthday or anniversary), I can send a request to our manager who will "
        f"review both bookings and get back to you as soon as possible."
        f"\n\nWhat would you like to do?"
        f"\n- Choose a different room"
        f"\n- Choose a different date"
        f"\n- Request manager review (please share your reason)"
    )


def compose_conflict_hil_task(
    db: Dict[str, Any],
    current_event: Dict[str, Any],
    conflict_info: Dict[str, Any],
    insist_reason: str,
) -> Dict[str, Any]:
    """
    Create a HIL task for conflict resolution.

    Returns a task dict ready to be inserted into the database.
    """
    current_client_id = current_event.get("client_id")
    current_client = {}
    if current_client_id:
        clients = db.get("clients") or {}
        current_client = clients.get(current_client_id) or {}

    room_id = conflict_info.get("room_id")
    event_date = conflict_info.get("event_date")

    task = {
        "type": "room_conflict_resolution",
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "event_id": current_event.get("event_id"),
        "data": {
            "room_id": room_id,
            "event_date": event_date,
            "client_1": {
                "event_id": conflict_info.get("conflicting_event_id"),
                "email": conflict_info.get("conflicting_client_email"),
                "name": conflict_info.get("conflicting_client_name"),
                "status": conflict_info.get("status"),
                "note": "First to reserve (current holder)",
            },
            "client_2": {
                "event_id": current_event.get("event_id"),
                "email": current_client.get("email") or current_event.get("client_email"),
                "name": current_client.get("name") or current_event.get("client_name"),
                "status": "Option (pending)",
                "insist_reason": insist_reason,
            },
        },
        "description": (
            f"Room Conflict: {room_id} on {event_date}\n\n"
            f"Client 1 (current holder): {conflict_info.get('conflicting_client_email')}\n"
            f"Client 2 (requesting): {current_client.get('email') or current_event.get('client_email')}\n\n"
            f"Client 2's reason for insisting:\n{insist_reason}\n\n"
            f"Please decide who should get the room."
        ),
    }
    return task


def resolve_conflict(
    db: Dict[str, Any],
    task_id: str,
    winner_event_id: str,
    notes: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Resolve a room conflict by selecting a winner.

    Args:
        db: The database dict
        task_id: The conflict task ID
        winner_event_id: Event ID of the winner
        notes: Optional manager notes

    Returns:
        Tuple of (winner_event_id, loser_event_id)
    """
    tasks = db.get("tasks") or {}
    task = tasks.get(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    task_data = task.get("data") or {}
    client_1_event_id = task_data.get("client_1", {}).get("event_id")
    client_2_event_id = task_data.get("client_2", {}).get("event_id")

    if winner_event_id == client_1_event_id:
        loser_event_id = client_2_event_id
    elif winner_event_id == client_2_event_id:
        loser_event_id = client_1_event_id
    else:
        raise ValueError(f"Winner event ID {winner_event_id} not in conflict")

    # Update task
    task["status"] = "resolved"
    task["resolved_at"] = datetime.now().isoformat()
    task["resolution"] = {
        "winner_event_id": winner_event_id,
        "loser_event_id": loser_event_id,
        "notes": notes,
    }

    return winner_event_id, loser_event_id


def handle_loser_event(
    db: Dict[str, Any],
    loser_event_id: str,
) -> Dict[str, Any]:
    """
    Handle the loser event after conflict resolution.

    Checks if other rooms are available on the same date:
    - If yes: Reset to Step 3 (room selection)
    - If no: Reset to Step 2 (date confirmation) and release room

    Returns dict with action to take and message to send.
    """
    events = db.get("events") or {}
    loser_event = events.get(loser_event_id)
    if not loser_event:
        return {"action": "error", "message": "Event not found"}

    event_date = loser_event.get("chosen_date") or loser_event.get("Event Date")

    # Check for other available rooms
    available_rooms = get_available_rooms_on_date(db, loser_event_id, event_date)

    if available_rooms:
        # Other rooms available - go to Step 3
        loser_event["locked_room_id"] = None
        loser_event["room_eval_hash"] = None
        loser_event["current_step"] = 3
        loser_event["thread_state"] = "Awaiting Client"
        loser_event["conflict_resolution"] = {
            "action": "choose_another_room",
            "available_rooms": available_rooms,
            "resolved_at": datetime.now().isoformat(),
        }

        return {
            "action": "choose_another_room",
            "step": 3,
            "available_rooms": available_rooms,
            "message": (
                f"I'm sorry, but after review, the room you wanted has been assigned to another client. "
                f"However, there are still {len(available_rooms)} other room(s) available on {event_date}. "
                f"Would you like me to show you the alternatives?"
            ),
        }
    else:
        # No rooms available - go to Step 2
        loser_event["locked_room_id"] = None
        loser_event["room_eval_hash"] = None
        loser_event["chosen_date"] = None
        loser_event["date_confirmed"] = False
        loser_event["current_step"] = 2
        loser_event["thread_state"] = "Awaiting Client"
        loser_event["conflict_resolution"] = {
            "action": "choose_another_date",
            "resolved_at": datetime.now().isoformat(),
        }

        return {
            "action": "choose_another_date",
            "step": 2,
            "message": (
                f"I'm sorry, but after review, the room you wanted has been assigned to another client, "
                f"and unfortunately there are no other rooms available on {event_date}. "
                f"Could you please let me know another date that would work for your event?"
            ),
        }


def compose_winner_message(room_name: str, event_date: str, had_conflict: bool = False) -> str:
    """
    Compose message for the winner (if they need to be notified).
    Only used if the winner was Client 2 (the one who insisted).
    Client 1 is not notified if they won (they don't know about conflict).
    """
    if not had_conflict:
        return ""

    return (
        f"Great news! Your request has been approved. "
        f"{room_name} on {event_date} is now reserved for you. "
        f"Let me prepare your offer."
    )


# =============================================================================
# SCENARIO-SPECIFIC FUNCTIONS
# =============================================================================


def detect_conflict_type(
    db: Dict[str, Any],
    event_id: str,
    room_id: str,
    event_date: str,
    action: str = "select",  # "select" for becoming Option, "confirm" for confirming
) -> Tuple[ConflictType, Optional[Dict[str, Any]]]:
    """
    Detect conflict type based on the action being taken.

    Args:
        db: The database dict
        event_id: Current event ID
        room_id: Room being requested
        event_date: Date being requested
        action: "select" (becoming Option) or "confirm" (confirming booking)

    Returns:
        Tuple of (ConflictType, conflict_info or None)
    """
    conflict_info = detect_room_conflict(db, event_id, room_id, event_date)

    if not conflict_info:
        return ConflictType.NONE, None

    other_status = conflict_info.get("status", "").lower()

    # Scenario B: Hard conflict - other is Confirmed OR we're trying to confirm
    if other_status == "confirmed" or action == "confirm":
        return ConflictType.HARD, conflict_info

    # Scenario A: Soft conflict - both are Option
    if other_status == "option" and action == "select":
        return ConflictType.SOFT, conflict_info

    # Default to soft
    return ConflictType.SOFT, conflict_info


def compose_soft_conflict_warning(room_name: str, event_date: str) -> str:
    """
    Compose a soft warning for Scenario A (Option + Option).
    Client still becomes Option, but receives a note.
    """
    return (
        f"Note: Another client also has a provisional hold (Option) on {room_name} for {event_date}. "
        f"You can still proceed, but if both of you try to confirm, the manager will need to decide. "
        f"If you'd prefer to avoid this situation, you could choose a different room or date."
    )


def compose_hard_conflict_block(room_name: str, event_date: str) -> str:
    """
    Compose message for Scenario B (Option + Confirm).
    Client cannot proceed until conflict is resolved.
    """
    return (
        f"I'm sorry, but {room_name} on {event_date} is currently held by another client. "
        f"Before I can confirm your booking, I need to check with our manager. "
        f"\n\nIf you have a special reason why you really need this room "
        f"(for example, it's a birthday or anniversary), please let me know and I'll include that "
        f"in my request to the manager. Otherwise, I'd recommend choosing a different room or date."
        f"\n\nWhat would you like to do?"
    )


def handle_soft_conflict(
    db: Dict[str, Any],
    event_id: str,
    conflict_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle Scenario A: Option + Option (soft conflict).

    - Client 2 STILL becomes Option
    - Soft warning is added to response
    - No HIL task created
    - Flag set on event for future reference

    Returns dict with action and warning message.
    """
    events = db.get("events") or {}
    event = events.get(event_id)

    if event:
        # Mark that there's a soft conflict (for visibility)
        event["has_conflict"] = True
        event["conflict_with"] = conflict_info.get("conflicting_event_id")
        event["conflict_type"] = "soft"

    room_name = conflict_info.get("room_id", "the room")
    event_date = conflict_info.get("event_date", "this date")

    return {
        "action": "proceed_with_warning",
        "conflict_type": "soft",
        "allow_proceed": True,
        "warning": compose_soft_conflict_warning(room_name, event_date),
    }


def handle_hard_conflict(
    db: Dict[str, Any],
    event_id: str,
    conflict_info: Dict[str, Any],
    client_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle Scenario B: Option + Confirm (hard conflict).

    If client_reason is provided:
    - Create HIL task for manager resolution
    - Block client until resolved

    If no client_reason:
    - Ask client for reason or to choose alternative

    Returns dict with action and message.
    """
    events = db.get("events") or {}
    event = events.get(event_id)

    room_name = conflict_info.get("room_id", "the room")
    event_date = conflict_info.get("event_date", "this date")

    if client_reason:
        # Client insists - create HIL task
        task = compose_conflict_hil_task(db, event, conflict_info, client_reason)

        # Add task to database
        tasks = db.setdefault("tasks", {})
        task_id = f"conflict_{event_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        tasks[task_id] = task

        # Mark event as waiting for conflict resolution
        if event:
            event["has_conflict"] = True
            event["conflict_with"] = conflict_info.get("conflicting_event_id")
            event["conflict_type"] = "hard"
            event["conflict_task_id"] = task_id
            event["thread_state"] = "Waiting on HIL"

        return {
            "action": "hil_task_created",
            "conflict_type": "hard",
            "allow_proceed": False,
            "task_id": task_id,
            "message": (
                f"Thank you for letting me know. I've sent a request to our manager to review your booking. "
                f"They will get back to you as soon as possible. "
                f"In the meantime, please wait for their decision."
            ),
        }
    else:
        # No reason yet - ask client
        if event:
            event["has_conflict"] = True
            event["conflict_with"] = conflict_info.get("conflicting_event_id")
            event["conflict_type"] = "hard_pending"

        return {
            "action": "ask_for_reason",
            "conflict_type": "hard",
            "allow_proceed": False,
            "message": compose_hard_conflict_block(room_name, event_date),
        }


def notify_conflict_resolution(
    db: Dict[str, Any],
    task_id: str,
    winner_event_id: str,
    manager_notes: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Resolve conflict and prepare notifications for both clients.

    Args:
        db: The database dict
        task_id: The conflict task ID
        winner_event_id: Event ID of the winner
        manager_notes: Optional notes from manager

    Returns:
        Tuple of (winner_result, loser_result) with messages for each client.
    """
    # Resolve the conflict
    winner_id, loser_id = resolve_conflict(db, task_id, winner_event_id, manager_notes)

    tasks = db.get("tasks") or {}
    task = tasks.get(task_id, {})
    task_data = task.get("data", {})
    room_name = task_data.get("room_id", "the room")
    event_date = task_data.get("event_date", "this date")

    # Handle loser
    loser_result = handle_loser_event(db, loser_id)

    # Prepare winner result
    events = db.get("events") or {}
    winner_event = events.get(winner_id, {})

    # Clear conflict flags on winner
    if winner_event:
        winner_event.pop("has_conflict", None)
        winner_event.pop("conflict_with", None)
        winner_event.pop("conflict_type", None)
        winner_event.pop("conflict_task_id", None)
        winner_event["thread_state"] = "Awaiting Client"

    # Check if winner was the one who insisted (Client 2)
    client_2_event_id = task_data.get("client_2", {}).get("event_id")
    winner_was_insister = winner_id == client_2_event_id

    if winner_was_insister:
        winner_message = compose_winner_message(room_name, event_date, had_conflict=True)
    else:
        # Winner was Client 1 - they don't need to know about the conflict
        winner_message = None

    winner_result = {
        "action": "winner_proceeds",
        "event_id": winner_id,
        "notify": winner_was_insister,
        "message": winner_message,
    }

    return winner_result, loser_result