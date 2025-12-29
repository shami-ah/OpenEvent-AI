from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timedelta, time, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[assignment]

from backend.domain import EventStatus, TaskStatus, TaskType
from backend.workflows.io.database import last_event_for_email
from backend.workflows.io.tasks import enqueue_task as _enqueue_task
# MIGRATED: from backend.workflows.common.conflict -> backend.detection.special.room_conflict
from backend.detection.special.room_conflict import (
    ConflictType,
    detect_conflict_type,
    handle_hard_conflict,
)

from .. import OpenEventAction

__workflow_role__ = "db_pers"

__all__ = [
    "attach_post_offer_classification",
    "enqueue_post_offer_routing_task",
    "enqueue_site_visit_followup",
    "enqueue_site_visit_hil_review",
    "HandlePostOfferRoute",
    "HandleSiteVisitRoute",
]

LOCAL_TZ = ZoneInfo("Europe/Zurich")
VISIT_DURATION_MIN = 45
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=4)
def _load_rooms(rooms_path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = Path(rooms_path) if rooms_path else _backend_root() / "data" / "rooms.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms") or []
    if not isinstance(rooms, list):
        return []
    return rooms


def _default_calendar_dir() -> Path:
    return _backend_root() / "calendar_data"


def _calendar_file(calendar_dir: Path, calendar_id: str) -> Path:
    calendar_dir.mkdir(parents=True, exist_ok=True)
    return calendar_dir / f"{calendar_id}.json"


def _load_calendar(calendar_dir: Path, calendar_id: str) -> Dict[str, Any]:
    candidate = _calendar_file(calendar_dir, calendar_id)
    if not candidate.exists():
        return {"busy": []}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return {"busy": []}
    if "busy" not in data or not isinstance(data["busy"], list):
        data["busy"] = []
    return data


def _save_calendar(calendar_dir: Path, calendar_id: str, payload: Dict[str, Any]) -> None:
    candidate = _calendar_file(calendar_dir, calendar_id)
    with candidate.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _parse_client_dt(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _format_slot(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%A, %d.%m.%Y at %H:%M")


def _iso_with_tz(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).replace(second=0, microsecond=0).isoformat()


def _slot_bounds(start: datetime, duration_min: int, room: Dict[str, Any]) -> Tuple[datetime, datetime, datetime, datetime]:
    end = start + timedelta(minutes=duration_min)
    before = int(room.get("buffer_before_min") or 0)
    after = int(room.get("buffer_after_min") or 0)
    window_start = start - timedelta(minutes=before)
    window_end = end + timedelta(minutes=after)
    return start, end, window_start, window_end


def _busy_to_windows(entries: Iterable[Dict[str, Any]]) -> List[Tuple[datetime, datetime, Dict[str, Any]]]:
    windows: List[Tuple[datetime, datetime, Dict[str, Any]]] = []
    for item in entries:
        start_raw = item.get("start")
        end_raw = item.get("end")
        if not start_raw or not end_raw:
            continue
        try:
            start = datetime.fromisoformat(start_raw)
            end = datetime.fromisoformat(end_raw)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=LOCAL_TZ)
        if end.tzinfo is None:
            end = end.replace(tzinfo=LOCAL_TZ)
        windows.append((start, end, item))
    return windows


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _candidate_conflicts(
    start: datetime,
    duration_min: int,
    room: Dict[str, Any],
    busy_entries: Iterable[Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]]]:
    _, end, window_start, window_end = _slot_bounds(start, duration_min, room)
    conflicts: List[Dict[str, Any]] = []
    for busy_start, busy_end, payload in _busy_to_windows(busy_entries):
        if _overlaps(window_start, window_end, busy_start, busy_end):
            conflicts.append(
                {
                    "start": _iso_with_tz(busy_start),
                    "end": _iso_with_tz(busy_end),
                    "description": payload.get("description"),
                    "status": payload.get("status"),
                }
            )
    available = not conflicts
    max_parallel = int(room.get("max_parallel_events") or 1)
    if max_parallel > 1:
        # Allow up to (max_parallel - 1) overlaps
        available = len(conflicts) < max_parallel
    return available, conflicts


def _select_room(rooms: List[Dict[str, Any]], preferred_label: Optional[str]) -> Optional[Dict[str, Any]]:
    if preferred_label:
        for room in rooms:
            if room.get("name") == preferred_label:
                return room
    return rooms[0] if rooms else None


def _build_hold_id(event_id: Optional[str], start_iso: str) -> str:
    base = event_id or "unknown-event"
    return f"{base}:{start_iso}"


def _existing_site_visits(
    entries: Iterable[Dict[str, Any]],
    event_id: Optional[str],
    client_email: str,
) -> List[Dict[str, Any]]:
    holds: List[Dict[str, Any]] = []
    for entry in entries:
        if entry.get("category") != "site_visit":
            continue
        if event_id and entry.get("event_id") != event_id:
            continue
        if entry.get("client_id") != client_email:
            continue
        holds.append(entry)
    return holds


def _find_hold_by_id(entries: Iterable[Dict[str, Any]], hold_id: str) -> Optional[Dict[str, Any]]:
    for entry in entries:
        if entry.get("hold_id") == hold_id:
            return entry
    return None


# --------------------------------------------------------------------------- #
# Shared persistence helpers
# --------------------------------------------------------------------------- #


def attach_post_offer_classification(
    db: Dict[str, Any],
    client_email: str,
    message_id: str,
    classification: Dict[str, Any],
) -> None:
    """Store the post-offer classification on the matching client history item."""

    email_key = (client_email or "").lower()
    clients = db.get("clients") or {}
    client = clients.get(email_key)
    if not client:
        raise KeyError(f"Client '{email_key}' not found in database.")

    history = client.get("history") or []
    for entry in history:
        if entry.get("msg_id") == message_id:
            entry["post_offer_classification"] = copy.deepcopy(classification)
            return

    raise KeyError(f"Message '{message_id}' not found in history for client '{email_key}'.")


def enqueue_post_offer_routing_task(
    db: Dict[str, Any],
    client_email: str,
    event_id: Optional[str],
    message_id: str,
    routing_hint: str,
) -> str:
    """Queue a route_post_offer task if one does not already exist for this message."""

    email_key = (client_email or "").lower()
    tasks = db.setdefault("tasks", [])
    for task in tasks:
        if (
            task.get("type") == TaskType.ROUTE_POST_OFFER.value
            and task.get("status") == TaskStatus.PENDING.value
            and (task.get("payload") or {}).get("message_msg_id") == message_id
        ):
            task.setdefault("payload", {})["routing_hint"] = routing_hint
            return task["task_id"]

    payload = {
        "routing_hint": routing_hint,
        "message_msg_id": message_id,
    }
    return _enqueue_task(
        db,
        TaskType.ROUTE_POST_OFFER,
        email_key,
        event_id,
        payload,
    )


def enqueue_site_visit_followup(
    db: Dict[str, Any],
    client_email: str,
    event_id: Optional[str],
    message_id: str,
) -> str:
    """Queue a follow-up pointer for the site-visit slice if missing."""

    email_key = (client_email or "").lower()
    tasks = db.setdefault("tasks", [])
    for task in tasks:
        if (
            task.get("type") == TaskType.ROUTE_SITE_VISIT.value
            and task.get("status") == TaskStatus.PENDING.value
            and (task.get("payload") or {}).get("message_msg_id") == message_id
        ):
            return task["task_id"]

    payload = {
        "routing_hint": "site_visit",
        "message_msg_id": message_id,
    }
    return _enqueue_task(
        db,
        TaskType.ROUTE_SITE_VISIT,
        email_key,
        event_id,
        payload,
    )


def enqueue_site_visit_hil_review(
    db: Dict[str, Any],
    client_email: str,
    event_id: Optional[str],
    hold_id: str,
    start_iso: str,
    end_iso: str,
    calendar_id: str,
    room_name: str,
) -> str:
    """Queue a manager review task for a site visit hold."""

    email_key = (client_email or "").lower()
    tasks = db.setdefault("tasks", [])
    for task in tasks:
        if (
            task.get("type") == TaskType.SITE_VISIT_HIL_REVIEW.value
            and (task.get("payload") or {}).get("hold_id") == hold_id
            and task.get("status") == TaskStatus.PENDING.value
        ):
            return task["task_id"]

    payload = {
        "hold_id": hold_id,
        "client_id": email_key,
        "event_id": event_id,
        "start": start_iso,
        "end": end_iso,
        "calendar_id": calendar_id,
        "room_name": room_name,
    }
    return _enqueue_task(
        db,
        TaskType.SITE_VISIT_HIL_REVIEW,
        email_key,
        event_id,
        payload,
    )


# --------------------------------------------------------------------------- #
# Post-offer routing handler
# --------------------------------------------------------------------------- #


_ACK_PATTERN = re.compile(r"\b(thanks|thank you|ok(?:ay)?|sounds good|great)\b", re.IGNORECASE)


def _find_task(db: Dict[str, Any], task_id: str) -> Optional[Dict[str, Any]]:
    for task in db.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def _find_event_by_id(db: Dict[str, Any], event_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not event_id:
        return None
    for event in db.get("events", []):
        if event.get("event_id") == event_id:
            return event
    return None


def _find_history_entry(client: Dict[str, Any], msg_id: str) -> Dict[str, Any]:
    for entry in client.get("history") or []:
        if entry.get("msg_id") == msg_id:
            return entry
    raise KeyError(f"History entry '{msg_id}' not found.")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _append_assistant_history(
    client: Dict[str, Any],
    message: str,
    note: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    msg_id = f"assistant-post-offer-{uuid.uuid4()}"
    entry = {
        "msg_id": msg_id,
        "ts": _utc_now_iso(),
        "subject": "Post-offer follow-up",
        "body_preview": message[:160],
        "message": message,
        "role": "assistant",
        "note": note,
    }
    if metadata:
        entry["metadata"] = copy.deepcopy(metadata)
    client.setdefault("history", []).append(entry)
    return entry


def _is_acknowledgement(text: Optional[str]) -> bool:
    if not text:
        return False
    return bool(_ACK_PATTERN.search(text))


_CONFIRM_PHRASES = (
    "let's go with",
    "let us take",
    "that works",
    "works for us",
    "works for me",
    "works fine",
    "we'll take",
    "we will take",
    "please book",
    "book us",
    "confirm",
    "lock it",
    "schedule",
    "reserve",
)


def _message_confirms_time(text: Optional[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in _CONFIRM_PHRASES)


def _history_has_metadata(client: Dict[str, Any], note: str, key: str, value: str) -> bool:
    for entry in client.get("history") or []:
        if entry.get("note") != note:
            continue
        metadata = entry.get("metadata") or {}
        if metadata.get(key) == value:
            return True
    return False


def _slot_selected_in_text(text: Optional[str], slot: datetime) -> bool:
    if not text:
        return False
    probes = {
        slot.strftime("%Y-%m-%d %H:%M"),
        slot.strftime("%d.%m.%Y %H:%M"),
        slot.strftime("%d.%m.%Y at %H:%M"),
        slot.strftime("%d.%m.%Y"),
        slot.strftime("%H:%M"),
    }
    lowered = text.lower()
    return any(probe.lower() in lowered for probe in probes)


def _slots_for_day(day: datetime) -> List[datetime]:
    slots: List[datetime] = []
    base = day.astimezone(LOCAL_TZ)
    available_hours = (9, 11, 14, 16)
    for hour in available_hours:
        candidate = base.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate.hour < BUSINESS_START_HOUR or candidate.hour >= BUSINESS_END_HOUR:
            continue
        slots.append(candidate)
    return slots


def _generate_suggestions_for_room(
    room: Dict[str, Any],
    busy_entries: Iterable[Dict[str, Any]],
    now: datetime,
    limit: int,
) -> List[datetime]:
    suggestions: List[datetime] = []
    days_checked = 0
    current = now + timedelta(hours=1)
    # Round to start of day in local tz
    day_cursor = datetime.combine(current.date(), time(hour=BUSINESS_START_HOUR), tzinfo=LOCAL_TZ)
    while len(suggestions) < limit and days_checked < 21:
        for slot in _slots_for_day(day_cursor):
            if slot <= now:
                continue
            available, _ = _candidate_conflicts(slot, VISIT_DURATION_MIN, room, busy_entries)
            if available:
                suggestions.append(slot)
                if len(suggestions) >= limit:
                    break
        day_cursor += timedelta(days=1)
        days_checked += 1
    return suggestions


def _generate_alternative_slots(
    room: Dict[str, Any],
    busy_entries: Iterable[Dict[str, Any]],
    preferred: List[datetime],
    now: datetime,
    limit: int,
) -> List[datetime]:
    candidates: List[datetime] = []
    if not preferred:
        return candidates
    # Search window ±7 days around preferred
    for base in preferred:
        for delta_days in range(-7, 8):
            day = base + timedelta(days=delta_days)
            for slot in _slots_for_day(day):
                if slot <= now:
                    continue
                candidates.append(slot)
    unique: Dict[str, datetime] = {}
    for slot in candidates:
        iso = _iso_with_tz(slot)
        unique.setdefault(iso, slot)
    slots = list(unique.values())

    def sort_key(dt: datetime) -> Tuple[int, int, datetime]:
        if preferred:
            distances = [abs((dt.date() - base.date()).days) for base in preferred]
            distance = min(distances)
        else:
            distance = 0
        future_flag = 0 if dt >= now else 1
        return (distance, future_flag, dt)

    slots.sort(key=sort_key)

    alternatives: List[datetime] = []
    for slot in slots:
        available, _ = _candidate_conflicts(slot, VISIT_DURATION_MIN, room, busy_entries)
        if available:
            alternatives.append(slot)
            if len(alternatives) >= limit:
                break
    return alternatives


def _format_conflicts(conflicts: Iterable[Dict[str, Any]]) -> List[str]:
    formatted: List[str] = []
    for conflict in conflicts:
        start = conflict.get("start")
        try:
            start_dt = datetime.fromisoformat(start) if start else None
        except ValueError:
            start_dt = None
        if start_dt:
            text = _format_slot(start_dt)
        else:
            text = start or "busy"
        formatted.append(text)
    return formatted


def _generate_event_date_suggestions(
    room: Dict[str, Any],
    busy_entries: Iterable[Dict[str, Any]],
    now: datetime,
    limit: int,
) -> List[str]:
    slots = _generate_suggestions_for_room(room, busy_entries, now, limit * 2)
    seen: set[str] = set()
    dates: List[str] = []
    for slot in slots:
        label = slot.date().isoformat()
        if label in seen:
            continue
        seen.add(label)
        dates.append(label)
        if len(dates) >= limit:
            break
    return dates


def _ensure_status(event_data: Dict[str, Any], target: EventStatus) -> bool:
    current_raw = event_data.get("Status") or EventStatus.LEAD.value
    try:
        current = EventStatus(current_raw)  # type: ignore[arg-type]
    except Exception:
        current = EventStatus.LEAD
    if current == target:
        return False
    if current == EventStatus.LEAD and target == EventStatus.OPTION:
        event_data["Status"] = EventStatus.OPTION.value
        return True
    if current == EventStatus.OPTION and target == EventStatus.CONFIRMED:
        event_data["Status"] = EventStatus.CONFIRMED.value
        return True
    if current == EventStatus.LEAD and target == EventStatus.CONFIRMED:
        # Respect progression: go through OPTION first.
        event_data["Status"] = EventStatus.OPTION.value
        return True
    return False


def _summarize_change_patch(patch: Dict[str, Any]) -> List[str]:
    summary: List[str] = []
    if patch.get("new_event_date"):
        summary.append(f"date → {patch['new_event_date']}")
    if patch.get("new_start_time"):
        summary.append(f"start time → {patch['new_start_time']}")
    if patch.get("new_end_time"):
        summary.append(f"end time → {patch['new_end_time']}")
    if patch.get("new_room_label"):
        summary.append(f"room → {patch['new_room_label']}")
    if patch.get("new_guest_count") is not None:
        summary.append(f"guests → {patch['new_guest_count']}")
    if patch.get("new_catering_notes"):
        summary.append("catering → updated notes")
    return summary


def _current_status_label(event_data: Optional[Dict[str, Any]]) -> str:
    if not event_data:
        return EventStatus.LEAD.value
    return event_data.get("Status") or EventStatus.LEAD.value


def _deposit_required(event_data: Optional[Dict[str, Any]]) -> bool:
    if not event_data:
        return False
    raw = str(event_data.get("Deposit") or "").strip().lower()
    if not raw or raw in {"none", "not required", "not specified"}:
        return False
    return True


def _deposit_paid(event_data: Optional[Dict[str, Any]]) -> bool:
    if not event_data:
        return False
    return str(event_data.get("Deposit Status") or "").strip().lower() == "paid"


def _set_manager_status(event_data: Dict[str, Any], status: str) -> None:
    event_data["Manager Approval"] = status


def _manager_status(event_data: Optional[Dict[str, Any]]) -> str:
    if not event_data:
        return "not_requested"
    return str(event_data.get("Manager Approval") or "not_requested").lower()


class HandlePostOfferRoute(OpenEventAction):
    """Consume a route_post_offer pointer and advance the post-offer branch."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db = payload["db"]
        task_id = payload["task_id"]

        task = _find_task(db, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")
        if task.get("type") != TaskType.ROUTE_POST_OFFER.value:
            raise ValueError(f"Task '{task_id}' is not a route_post_offer task.")
        if task.get("status") != TaskStatus.PENDING.value:
            return {"task_id": task_id, "skipped": True, "task_status": task.get("status")}

        client_id = task.get("client_id")
        if not client_id:
            raise ValueError("Task is missing client_id.")
        client = (db.get("clients") or {}).get(client_id)
        if not client:
            raise ValueError(f"Client '{client_id}' not found.")

        payload_info = task.get("payload") or {}
        message_id = payload_info.get("message_msg_id")
        if not message_id:
            raise ValueError("Routing task missing message_msg_id pointer.")

        history_entry = _find_history_entry(client, message_id)
        classification = history_entry.get("post_offer_classification")
        if not classification:
            raise ValueError(f"No post_offer_classification stored on message '{message_id}'.")

        event_entry = _find_event_by_id(db, task.get("event_id")) or last_event_for_email(db, client_id)
        event_data = event_entry.get("event_data") if event_entry else {}

        response_type = classification.get("response_type")
        handler_map = {
            "confirm_booking": self._handle_confirm,
            "reserve_date": self._handle_reserve,
            "change_request": self._handle_change,
            "site_visit": self._handle_site_visit,
            "general_question": self._handle_question,
            "not_interested": self._handle_not_interested,
        }
        handler = handler_map.get(response_type)
        if handler is None:
            raise ValueError(f"Unsupported response_type '{response_type}'.")

        branch_result = handler(
            db=db,
            task=task,
            client=client,
            event_entry=event_entry,
            event_data=event_data,
            classification=classification,
            message_id=message_id,
            client_id=client_id,
        )

        note = branch_result["note"]
        _append_assistant_history(client, branch_result["message"], note)

        task["status"] = TaskStatus.DONE.value
        task["notes"] = note

        return {
            "task_id": task_id,
            "task_status": TaskStatus.DONE.value,
            "note": note,
            "message": branch_result["message"],
            "created_tasks": branch_result.get("created_tasks", []),
            "event_status": event_data.get("Status") if event_data else None,
        }

    # ------------------------------------------------------------------ #
    # Branch handlers
    # ------------------------------------------------------------------ #

    def _handle_confirm(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        # [HARD CONFLICT CHECK] Detect if another client has Option/Confirmed on same room/date
        event_id = event_entry.get("event_id") if event_entry else None
        room_id = event_data.get("Preferred Room") or event_data.get("locked_room_id")
        event_date = event_data.get("Event Date") or event_data.get("chosen_date")

        if event_id and room_id and event_date:
            conflict_type, conflict_info = detect_conflict_type(
                db=db,
                event_id=event_id,
                room_id=room_id,
                event_date=event_date,
                action="confirm",  # Client is trying to confirm
            )

            if conflict_type == ConflictType.HARD and conflict_info:
                # Check if client already provided a reason (from previous message or classification)
                client_reason = classification.get("extracted_fields", {}).get("conflict_reason")

                result = handle_hard_conflict(
                    db=db,
                    event_id=event_id,
                    conflict_info=conflict_info,
                    client_reason=client_reason,
                )

                if result["action"] == "ask_for_reason":
                    # Block confirmation, ask for reason
                    _ensure_status(event_data, EventStatus.OPTION)
                    message = result["message"]
                    note = "confirm: conflict-blocked"
                    return {"message": message, "note": note}

                elif result["action"] == "hil_task_created":
                    # HIL task created, wait for resolution
                    _ensure_status(event_data, EventStatus.OPTION)
                    message = result["message"]
                    note = "confirm: conflict-hil-pending"
                    return {"message": message, "note": note}

        deposit_req = _deposit_required(event_data)
        deposit_paid = _deposit_paid(event_data)
        manager_status = _manager_status(event_data)

        if deposit_req and not deposit_paid:
            _ensure_status(event_data, EventStatus.OPTION)
            if classification.get("extracted_fields", {}).get("wants_to_pay_deposit_now"):
                event_data.setdefault("Deposit Status", "pending payment")
            status_label = _current_status_label(event_data)
            message = (
                "Thanks for confirming the event! "
                f"Status: {status_label}. Once the deposit arrives I'll lock everything in. "
                "Feel free to share any questions or tweaks in the meantime."
            )
            note = "confirm: awaiting-deposit"
            return {"message": message, "note": note}

        if manager_status != "approved":
            _ensure_status(event_data, EventStatus.OPTION)
            _set_manager_status(event_data, "pending")
            status_label = _current_status_label(event_data)
            message = (
                "Great, I've marked the event as a provisional Option and passed it to our manager for a quick review. "
                f"Status: {status_label}. I'll update you as soon as we have the green light."
            )
            note = "confirm: pending-hil"
            return {"message": message, "note": note}

        # Deposit satisfied and manager already approved → confirm event.
        updated = _ensure_status(event_data, EventStatus.CONFIRMED)
        status_label = _current_status_label(event_data)
        date_label = event_data.get("Event Date") or "your event date"
        time_label = f"{event_data.get('Start Time') or 'start'}–{event_data.get('End Time') or 'end'}"
        room_label = event_data.get("Preferred Room") or "the room we discussed"
        message = (
            "Great news: everything is confirmed!"
            f"\nDate: {date_label} | Time: {time_label} | Room: {room_label}."
            f"\nStatus: {status_label}. If anything changes, just let me know."
        )
        note = "confirm: confirmed"
        return {"message": message, "note": note}

    def _handle_reserve(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        _ensure_status(event_data, EventStatus.OPTION)
        status_label = _current_status_label(event_data)
        message = (
            "I’ve placed a provisional Option hold for your event. "
            f"Status: {status_label}. It isn’t fully confirmed yet, so just let me know when you’re ready to confirm or adjust anything."
        )
        note = "reserve: option"
        return {"message": message, "note": note}

    def _handle_change(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        _ensure_status(event_data, EventStatus.OPTION)
        patch = classification.get("extracted_fields", {}).get("change_request_patch") or {}
        summary = _summarize_change_patch(patch)
        summary_text = ", ".join(summary) if summary else "updates noted"
        status_label = _current_status_label(event_data)
        message = (
            f"I’ve noted the requested updates ({summary_text}). "
            f"Status stays {status_label}. Just confirm if you’d like me to apply them, or let me know what to adjust instead."
        )
        note = "change: awaiting-decision"
        return {"message": message, "note": note}

    def _handle_site_visit(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        extracted = classification.get("extracted_fields", {})
        visit_slots = extracted.get("proposed_visit_datetimes") or []
        if visit_slots:
            availability_line = (
                "Thanks for the suggested times. I'll check availability and circle back shortly."
            )
        else:
            availability_line = "I'll pull a few visit times that fit our schedule and get back to you."
        status_label = _current_status_label(event_data)
        message = (
            f"{availability_line} Status: {status_label}. "
            "You can keep planning the event in parallel."
        )
        note = "visit: intake"
        task_id = enqueue_site_visit_followup(db, client_id, task.get("event_id"), message_id)
        return {"message": message, "note": note, "created_tasks": [task_id]}

    def _handle_question(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        question_text = classification.get("extracted_fields", {}).get("user_question_text") or "your question"
        status_label = _current_status_label(event_data)
        message = (
            f"Thanks for the note. I'll dig into "{question_text}" and circle back shortly. "
            f"Status remains {status_label} while I gather the info."
        )
        note = "question: acknowledgement"
        return {"message": message, "note": note}

    def _handle_not_interested(
        self,
        *,
        db: Dict[str, Any],
        task: Dict[str, Any],
        client: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        classification: Dict[str, Any],
        message_id: str,
        client_id: str,
    ) -> Dict[str, Any]:
        status_label = _current_status_label(event_data)
        message = (
            "Thanks for letting us know. I’m sorry we won’t host your event this time."
            f"\nStatus stays {status_label}. If you change your mind, simply reply and I’ll reopen everything for you."
        )
        note = "not-interested: closed"
        return {"message": message, "note": note}


class HandleSiteVisitRoute(OpenEventAction):
    """Consume a route_site_visit pointer and manage site visit scheduling."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db = payload["db"]
        calendar_dir = Path(payload.get("calendar_dir") or _default_calendar_dir())
        rooms_path = payload.get("rooms_path")
        rooms = _load_rooms(rooms_path)

        hil_updates = self._process_hil_reviews(db, calendar_dir, rooms)

        task_id = payload["task_id"]
        task = _find_task(db, task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")
        if task.get("type") != TaskType.ROUTE_SITE_VISIT.value:
            raise ValueError(f"Task '{task_id}' is not a route_site_visit task.")
        if task.get("status") != TaskStatus.PENDING.value:
            return {
                "task_id": task_id,
                "skipped": True,
                "task_status": task.get("status"),
                "hil_updates": hil_updates,
            }

        client_id = task.get("client_id")
        if not client_id:
            raise ValueError("Site visit task missing client_id.")
        client = (db.get("clients") or {}).get(client_id)
        if not client:
            raise ValueError(f"Client '{client_id}' not found.")

        event_entry = _find_event_by_id(db, task.get("event_id")) or last_event_for_email(db, client_id)
        event_data = event_entry.get("event_data") if event_entry else {}

        room_label = event_data.get("Preferred Room") if event_data else None
        room = _select_room(rooms, room_label)
        if room is None:
            message = (
                "I couldn't find a matching room to schedule the viewing. "
                "Please let me know which space you'd like to visit."
            )
            _append_assistant_history(client, message, "visit: missing-room")
            task["status"] = TaskStatus.DONE.value
            task["notes"] = "visit: missing-room"
            return {
                "task_id": task_id,
                "task_status": TaskStatus.DONE.value,
                "message": message,
                "hil_updates": hil_updates,
            }

        calendar_id = room.get("calendar_id") or ""
        calendar_payload = _load_calendar(calendar_dir, calendar_id)
        busy_entries = calendar_payload.get("busy", [])

        now = datetime.now(tz=LOCAL_TZ)
        self._maybe_send_post_visit_followup(
            client=client,
            client_id=client_id,
            event_id=event_entry.get("event_id") if event_entry else None,
            room=room,
            busy_entries=busy_entries,
            now=now,
        )

        payload_info = task.get("payload") or {}
        message_id = payload_info.get("message_msg_id")
        if not message_id:
            raise ValueError("Site visit task missing message pointer.")

        history_entry = _find_history_entry(client, message_id)
        classification = history_entry.get("post_offer_classification")
        if not classification:
            raise ValueError("Site visit message lacks classification.")

        message_text = history_entry.get("message") or history_entry.get("body_preview") or ""
        proposals_raw = (classification.get("extracted_fields") or {}).get("proposed_visit_datetimes") or []
        proposal_slots = [dt for dt in (_parse_client_dt(slot) for slot in proposals_raw) if dt is not None]

        if proposal_slots:
            result = self._handle_with_proposals(
                db=db,
                client=client,
                client_id=client_id,
                task=task,
                event_entry=event_entry,
                event_data=event_data,
                room=room,
                calendar_dir=calendar_dir,
                calendar_payload=calendar_payload,
                calendar_id=calendar_id,
                busy_entries=busy_entries,
                proposal_slots=proposal_slots,
                history_entry=history_entry,
                message_text=message_text,
                now=now,
            )
        else:
            result = self._handle_without_proposals(
                db=db,
                client=client,
                client_id=client_id,
                task=task,
                event_entry=event_entry,
                event_data=event_data,
                room=room,
                calendar_dir=calendar_dir,
                calendar_payload=calendar_payload,
                calendar_id=calendar_id,
                busy_entries=busy_entries,
                history_entry=history_entry,
                message_text=message_text,
                now=now,
            )

        result.setdefault("hil_updates", hil_updates)
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _process_hil_reviews(
        self,
        db: Dict[str, Any],
        calendar_dir: Path,
        rooms: List[Dict[str, Any]],
    ) -> List[str]:
        updates: List[str] = []
        for task in db.get("tasks", []):
            if task.get("type") != TaskType.SITE_VISIT_HIL_REVIEW.value:
                continue
            if task.get("status") == TaskStatus.PENDING.value:
                continue
            if task.get("notes") == "processed":
                continue
            payload = task.get("payload") or {}
            hold_id = payload.get("hold_id")
            if not hold_id:
                task["notes"] = "processed"
                continue
            client_id = payload.get("client_id")
            client = (db.get("clients") or {}).get(client_id)
            if not client:
                task["notes"] = "processed"
                continue
            calendar_id = payload.get("calendar_id") or ""
            calendar_payload = _load_calendar(calendar_dir, calendar_id)
            busy_entries = calendar_payload.get("busy", [])
            hold = _find_hold_by_id(busy_entries, hold_id)
            room_name = payload.get("room_name")
            room = _select_room(rooms, room_name)
            if room is None and rooms:
                room = rooms[0]
            status_label = task.get("status")
            if status_label == TaskStatus.APPROVED.value and hold:
                hold["status"] = "confirmed"
                _save_calendar(calendar_dir, calendar_id, calendar_payload)
                start_iso = hold.get("start")
                start_dt = _parse_client_dt(start_iso) if start_iso else None
                when_label = _format_slot(start_dt) if start_dt else start_iso
                message = (
                    f"Your site visit has been confirmed for {when_label} in {room_name or room.get('name') if room else 'the venue'}."
                    "\n"
                    "Once you're ready we can move ahead with reserving or confirming the event."
                )
                metadata = {"hold_id": hold_id}
                _append_assistant_history(client, message, "visit: confirmed", metadata)
                task["status"] = TaskStatus.DONE.value
                task["notes"] = "processed"
                updates.append(f"visit_confirmed:{hold_id}")
            elif status_label == TaskStatus.REJECTED.value and hold:
                busy_entries.remove(hold)
                _save_calendar(calendar_dir, calendar_id, calendar_payload)
                message = (
                    "Our manager wasn't able to approve that site-visit slot. "
                    "Could you propose another time that would work for you?"
                )
                metadata = {"hold_id": hold_id}
                _append_assistant_history(client, message, "visit: hil-declined", metadata)
                task["status"] = TaskStatus.DONE.value
                task["notes"] = "processed"
                updates.append(f"visit_declined:{hold_id}")
            else:
                task["status"] = TaskStatus.DONE.value
                task["notes"] = "processed"
        return updates

    def _handle_with_proposals(
        self,
        *,
        db: Dict[str, Any],
        client: Dict[str, Any],
        client_id: str,
        task: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        room: Dict[str, Any],
        calendar_dir: Path,
        calendar_payload: Dict[str, Any],
        calendar_id: str,
        busy_entries: List[Dict[str, Any]],
        proposal_slots: List[datetime],
        history_entry: Dict[str, Any],
        message_text: str,
        now: datetime,
    ) -> Dict[str, Any]:
        available_slots: List[datetime] = []
        conflicts_detail: List[Dict[str, Any]] = []
        for slot in proposal_slots:
            available, conflicts = _candidate_conflicts(slot, VISIT_DURATION_MIN, room, busy_entries)
            if available:
                available_slots.append(slot)
            else:
                conflicts_detail.extend(conflicts)

        if available_slots:
            # Direct confirmation if the message clearly selects one slot and there is a single option.
            if (
                len(available_slots) == 1
                and (_message_confirms_time(message_text) or len(proposal_slots) == 1)
            ):
                slot = available_slots[0]
                result = self._book_visit(
                    db=db,
                    client=client,
                    client_id=client_id,
                    task=task,
                    event_entry=event_entry,
                    event_data=event_data,
                    room=room,
                    calendar_dir=calendar_dir,
                    calendar_payload=calendar_payload,
                    calendar_id=calendar_id,
                    busy_entries=busy_entries,
                    slot=slot,
                )
                return result

            if _message_confirms_time(message_text):
                for slot in available_slots:
                    if _slot_selected_in_text(message_text, slot):
                        return self._book_visit(
                            db=db,
                            client=client,
                            client_id=client_id,
                            task=task,
                            event_entry=event_entry,
                            event_data=event_data,
                            room=room,
                            calendar_dir=calendar_dir,
                            calendar_payload=calendar_payload,
                            calendar_id=calendar_id,
                            busy_entries=busy_entries,
                            slot=slot,
                        )

            options = "\n".join(f"- { _format_slot(slot) }" for slot in available_slots)
            message = (
                "Here are the visit times that are currently free:\n"
                f"{options}\n"
                "Let me know which one you'd like, or feel free to propose another time."
            )
            _append_assistant_history(client, message, "visit: propose")
            task["status"] = TaskStatus.DONE.value
            task["notes"] = "visit: propose"
            return {
                "task_id": task["task_id"],
                "task_status": TaskStatus.DONE.value,
                "message": message,
            }

        alternatives = _generate_alternative_slots(room, busy_entries, proposal_slots, now, limit=5)
        alt_lines = "\n".join(f"- { _format_slot(slot) }" for slot in alternatives)
        conflict_lines = "\n".join(f"- {line}" for line in _format_conflicts(conflicts_detail))
        if not alternatives:
            fallback = "I can pull fresh options if you share a couple of new time windows."
        else:
            fallback = "Let me know if any of those work, or feel free to propose another time."
        parts = [
            "The times you suggested are already booked:",
            conflict_lines or "- All proposed slots overlap with existing events.",
        ]
        if alternatives:
            parts.append("Closest available alternatives:")
            parts.append(alt_lines)
        parts.append(fallback)
        message = "\n".join(parts)
        _append_assistant_history(client, message, "visit: alternatives")
        task["status"] = TaskStatus.DONE.value
        task["notes"] = "visit: alternatives"
        return {
            "task_id": task["task_id"],
            "task_status": TaskStatus.DONE.value,
            "message": message,
        }

    def _handle_without_proposals(
        self,
        *,
        db: Dict[str, Any],
        client: Dict[str, Any],
        client_id: str,
        task: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        room: Dict[str, Any],
        calendar_dir: Path,
        calendar_payload: Dict[str, Any],
        calendar_id: str,
        busy_entries: List[Dict[str, Any]],
        history_entry: Dict[str, Any],
        message_text: str,
        now: datetime,
    ) -> Dict[str, Any]:
        if _is_acknowledgement(message_text):
            task["status"] = TaskStatus.DONE.value
            task["notes"] = "visit: noop"
            _append_assistant_history(
                client,
                "Thanks for the update. Just let me know when you'd like to lock a visit slot.",
                "visit: noop",
            )
            return {
                "task_id": task["task_id"],
                "task_status": TaskStatus.DONE.value,
                "message": "noop",
            }

        suggestions = _generate_suggestions_for_room(room, busy_entries, now, limit=4)
        if suggestions:
            options = "\n".join(f"- { _format_slot(slot) }" for slot in suggestions)
            message = (
                "Here are a few visit times that fit our calendar:\n"
                f"{options}\n"
                "Pick one or feel free to propose another slot that suits you."
            )
            note = "visit: propose"
        else:
            message = (
                "It looks like the next couple of weeks are quite full. "
                "Could you share a few time windows that work for a tour? "
                "I'll match them against our calendar right away."
            )
            note = "visit: propose"
        _append_assistant_history(client, message, note)
        task["status"] = TaskStatus.DONE.value
        task["notes"] = note
        return {
            "task_id": task["task_id"],
            "task_status": TaskStatus.DONE.value,
            "message": message,
        }

    def _book_visit(
        self,
        *,
        db: Dict[str, Any],
        client: Dict[str, Any],
        client_id: str,
        task: Dict[str, Any],
        event_entry: Optional[Dict[str, Any]],
        event_data: Dict[str, Any],
        room: Dict[str, Any],
        calendar_dir: Path,
        calendar_payload: Dict[str, Any],
        calendar_id: str,
        busy_entries: List[Dict[str, Any]],
        slot: datetime,
    ) -> Dict[str, Any]:
        start, end, _, _ = _slot_bounds(slot, VISIT_DURATION_MIN, room)
        start_iso = _iso_with_tz(start)
        end_iso = _iso_with_tz(end)
        hold_id = _build_hold_id(event_entry.get("event_id") if event_entry else None, start_iso)
        existing = _find_hold_by_id(busy_entries, hold_id)
        client_name = (event_data or {}).get("Name") or client.get("profile", {}).get("name") or client_id
        description = f"Viewing visit for {client_name}"

        if not existing:
            entry = {
                "start": start_iso,
                "end": end_iso,
                "description": description,
                "status": "option",
                "category": "site_visit",
                "event_id": event_entry.get("event_id") if event_entry else None,
                "client_id": client_id,
                "hold_id": hold_id,
                "room_name": room.get("name"),
            }
            busy_entries.append(entry)
            _save_calendar(calendar_dir, calendar_id, calendar_payload)

        hil_task_id = enqueue_site_visit_hil_review(
            db=db,
            client_email=client_id,
            event_id=event_entry.get("event_id") if event_entry else None,
            hold_id=hold_id,
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_id=calendar_id,
            room_name=room.get("name"),
        )

        message = (
            f"Your site visit is provisionally reserved for {_format_slot(start)}. "
            "I've sent it to our manager for confirmation and will let you know as soon as it's approved.\n"
            "If you'd like, we can already move ahead with reserving or confirming the event details."
        )
        metadata = {"hold_id": hold_id}
        _append_assistant_history(client, message, "visit: option-pending-hil", metadata)
        task["status"] = TaskStatus.DONE.value
        task["notes"] = "visit: option-pending-hil"

        return {
            "task_id": task["task_id"],
            "task_status": TaskStatus.DONE.value,
            "message": message,
            "hil_task_id": hil_task_id,
            "hold_id": hold_id,
        }

    def _maybe_send_post_visit_followup(
        self,
        client: Dict[str, Any],
        client_id: str,
        event_id: Optional[str],
        room: Dict[str, Any],
        busy_entries: List[Dict[str, Any]],
        now: datetime,
    ) -> None:
        holds = _existing_site_visits(busy_entries, event_id, client_id)
        for hold in holds:
            start_iso = hold.get("start")
            hold_id = hold.get("hold_id")
            if not hold_id or not start_iso:
                continue
            if _history_has_metadata(client, "visit: post-visit-followup", "hold_id", hold_id):
                continue
            start_dt = _parse_client_dt(start_iso)
            if not start_dt or start_dt + timedelta(minutes=VISIT_DURATION_MIN) > now:
                continue
            room_name = hold.get("room_name") or room.get("name") or "the venue"
            start_label = _format_slot(start_dt)
            suggestions = _generate_event_date_suggestions(room, busy_entries, now, limit=3)
            if suggestions:
                suggestion_text = "\n".join(
                    f"- {datetime.strptime(date, '%Y-%m-%d').strftime('%A, %d.%m.%Y')}"
                    for date in suggestions
                )
                followup = (
                    f"Thanks again for visiting {room_name} on {start_label}. "
                    "If you'd like to move forward, here are a few event dates we can currently offer:\n"
                    f"{suggestion_text}\n"
                    "Just let me know which one you prefer, or share another date."
                )
            else:
                followup = (
                    f"Thanks again for visiting {room_name} on {start_label}. "
                    "When you're ready, share a preferred event date and I'll take it from there."
                )
            metadata = {"hold_id": hold_id}
            _append_assistant_history(client, followup, "visit: post-visit-followup", metadata)
