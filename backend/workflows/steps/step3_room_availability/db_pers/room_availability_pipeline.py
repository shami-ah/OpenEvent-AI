"""Advanced room availability pipeline preserved for future workflow phases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.utils.async_tools import run_io_tasks

__workflow_role__ = "db_pers"

from zoneinfo import ZoneInfo

from backend.adapters.calendar_adapter import CalendarAdapter
from backend.adapters.client_gui_adapter import ClientGUIAdapter
from backend.workflows.io.database import load_db as _load_db, save_db as _save_db

TZ = ZoneInfo("Europe/Zurich")
TIME_SHIFTS = [
    (-30, "shift -30m"),
    (30, "shift +30m"),
    (-60, "shift -60m"),
    (60, "shift +60m"),
    (-90, "shift -90m"),
    (90, "shift +90m"),
]
DATE_FORMAT_FALLBACKS = ("%Y-%m-%d", "%d.%m.%Y")
WF_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "events_database.json"
WF_LOCK_PATH = WF_DB_PATH.with_name(".events_db.lock")
ROOMS_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "rooms.json"


@dataclass
class RequestedWindow:
    """[Condition] Requested availability window derived from event data."""

    date: str
    start: datetime
    end: datetime


def now_iso() -> str:
    """[Condition] Current UTC timestamp formatted for logs."""

    return (
        datetime.now(tz=TZ)
        .astimezone(ZoneInfo("UTC"))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def parse_date(value: str) -> datetime:
    """[Condition] Parse supported date formats into datetime objects."""

    for fmt in DATE_FORMAT_FALLBACKS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def parse_time(value: str) -> time:
    """[Condition] Parse a HH:MM string into a time object."""

    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Unsupported time format: {value}") from exc


def parse_iso_datetime(value: str) -> datetime:
    """[Condition] Parse ISO timestamps tolerating trailing Z."""

    payload = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(payload)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def to_utc(value: datetime) -> datetime:
    """[Condition] Convert aware datetimes to UTC."""

    return value.astimezone(ZoneInfo("UTC"))


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """[Condition] Determine if two time windows overlap."""

    return a_start < b_end and b_start < a_end


def to_display_date(value: str) -> str:
    """[LLM] Format stored date strings for human-friendly output."""

    try:
        parsed = parse_date(value)
    except ValueError:
        return value
    return parsed.strftime("%d.%m.%Y")


def format_date_label(dates: Sequence[str]) -> str:
    """[LLM] Build a concise label describing requested dates."""

    if not dates:
        return ""
    if len(dates) == 1:
        return to_display_date(dates[0])
    if len(dates) == 2:
        return f"{to_display_date(dates[0])} – {to_display_date(dates[1])}"
    return ", ".join(to_display_date(d) for d in dates)


def load_rooms_config(path: Path | None = None) -> List[Dict[str, Any]]:
    """[Condition] Load venue room definitions from JSON fixtures."""

    candidate = path or ROOMS_PATH
    with candidate.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms", [])
    return rooms


def ensure_logs(event: Dict[str, Any]) -> None:
    """[OpenEvent Database] Guarantee the event has a logs array."""

    event.setdefault("logs", [])


def append_log(event: Dict[str, Any], action: str, details: Dict[str, Any]) -> None:
    """[OpenEvent Database] Append a structured log entry to the event."""

    ensure_logs(event)
    event["logs"].append({"ts": now_iso(), "actor": "Platform", "action": action, "details": details})


def build_requested_windows(event_data: Dict[str, Any]) -> Tuple[List[RequestedWindow], Dict[str, str]]:
    """[Condition] Derive per-day windows from stored event fields."""

    date_raw = event_data.get("Event Date")
    start_raw = event_data.get("Start Time")
    end_raw = event_data.get("End Time")

    if not date_raw or date_raw in {"Not specified", "none"}:
        raise ValueError("Missing Event Date")
    if not start_raw or start_raw in {"Not specified", "none"}:
        raise ValueError("Missing Start Time")
    if not end_raw or end_raw in {"Not specified", "none"}:
        raise ValueError("Missing End Time")

    start_time = parse_time(str(start_raw))
    end_time = parse_time(str(end_raw))
    if datetime.combine(datetime.today(), end_time) <= datetime.combine(datetime.today(), start_time):
        raise ValueError("End time must be after start time")

    if isinstance(date_raw, list):
        dates = [str(d) for d in date_raw if d]
    else:
        dates = [str(date_raw)]

    requested: List[RequestedWindow] = []
    for value in dates:
        base = parse_date(value)
        start_dt = datetime.combine(base.date(), start_time, tzinfo=TZ)
        end_dt = datetime.combine(base.date(), end_time, tzinfo=TZ)
        requested.append(RequestedWindow(date=base.strftime("%Y-%m-%d"), start=start_dt, end=end_dt))

    overall = {"start": requested[0].start.isoformat(), "end": requested[-1].end.isoformat()}
    return requested, overall


def parse_participants(event_data: Dict[str, Any]) -> Tuple[Optional[int], bool]:
    """[Condition] Parse participant counts and track uncertainty."""

    raw = event_data.get("Number of Participants")
    if raw in (None, "", "Not specified", "none"):
        return None, True
    if isinstance(raw, int):
        return raw, False
    try:
        value = int(str(raw).strip())
        return value, False
    except ValueError:
        return None, True


def build_candidate_rooms(
    rooms: Sequence[Dict[str, Any]],
    preferred_room: Optional[str],
    participants: Optional[int],
) -> List[Dict[str, Any]]:
    """[Condition] Sort rooms prioritizing the preferred room and capacity fit."""

    ordered: List[Dict[str, Any]] = []
    preferred_lower = (preferred_room or "").lower()
    capacity_unknown = participants is None

    if preferred_room:
        for room in rooms:
            if room.get("name", "").lower() == preferred_lower:
                ordered.append(room)
                break

    for room in rooms:
        if room in ordered:
            continue
        capacity_min = room.get("capacity_min")
        capacity_max = room.get("capacity_max")
        if capacity_unknown:
            ordered.append(room)
            continue
        if capacity_min is None or capacity_max is None:
            ordered.append(room)
            continue
        if capacity_min <= participants <= capacity_max:
            ordered.append(room)
    return ordered


def room_capacity_ok(room: Dict[str, Any], participants: Optional[int]) -> bool:
    """[Condition] Check whether the room capacity fits the attendee count."""

    if participants is None:
        return True
    capacity_min = room.get("capacity_min")
    capacity_max = room.get("capacity_max")
    if capacity_min is None or capacity_max is None:
        return True
    return capacity_min <= participants <= capacity_max


def collect_conflicts(
    room: Dict[str, Any],
    window: RequestedWindow,
    calendar_adapter: CalendarAdapter,
) -> Tuple[bool, List[Dict[str, str]]]:
    """[Condition] Gather busy intervals overlapping the requested window."""

    def _buffer_minutes(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    # Respect per-room buffer settings; default to 30 if missing/invalid
    buffer_before = timedelta(minutes=_buffer_minutes(room.get("buffer_before_min"), 30))
    buffer_after = timedelta(minutes=_buffer_minutes(room.get("buffer_after_min"), 30))

    start = window.start
    end = window.end
    expanded_start = to_utc(start - buffer_before)
    expanded_end = to_utc(end + buffer_after)

    busy = calendar_adapter.get_busy(
        calendar_id=str(room.get("calendar_id") or ""),
        start_iso=(start - buffer_before).isoformat(),
        end_iso=(end + buffer_after).isoformat(),
    )

    conflicts: List[Dict[str, str]] = []
    for slot in busy:
        busy_start = to_utc(parse_iso_datetime(slot["start"]))
        busy_end = to_utc(parse_iso_datetime(slot["end"]))
        if overlaps(expanded_start, expanded_end, busy_start, busy_end):
            conflicts.append({"start": busy_start.isoformat(), "end": busy_end.isoformat()})

    return (len(conflicts) > 0, conflicts)



def near_miss_suggestions(
    room: Dict[str, Any],
    window: RequestedWindow,
    calendar_adapter: CalendarAdapter,
) -> List[Dict[str, str]]:
    """[LLM] Suggest nearby slots by shifting the requested time window."""

    suggestions: List[Dict[str, str]] = []
    for shift_minutes, label in TIME_SHIFTS:
        if len(suggestions) >= 3:
            break
        shifted_start = window.start + timedelta(minutes=shift_minutes)
        shifted_end = window.end + timedelta(minutes=shift_minutes)
        if shifted_start.date() != window.start.date():
            continue
        conflict, _ = collect_conflicts(
            room,
            RequestedWindow(date=window.date, start=shifted_start, end=shifted_end),
            calendar_adapter,
        )
        if conflict:
            continue
        suggestions.append(
            {
                "room": room.get("name"),
                "start": shifted_start.isoformat(),
                "end": shifted_end.isoformat(),
                "note": label,
            }
        )
    return suggestions[:3]


def evaluate_room(
    room: Dict[str, Any],
    windows: Sequence[RequestedWindow],
    calendar_adapter: CalendarAdapter,
) -> Dict[str, Any]:
    """[Condition] Evaluate room availability for each requested day."""

    per_day: List[Dict[str, Any]] = []
    conflict_intervals: List[Dict[str, str]] = []
    any_free = False
    all_free = True
    collected_suggestions: List[Dict[str, str]] = []

    for day_window in windows:
        conflict, conflicts = collect_conflicts(room, day_window, calendar_adapter)
        state = "conflict" if conflict else "free"
        per_day.append(
            {
                "date": day_window.date,
                "state": state,
                "start": day_window.start.isoformat(),
                "end": day_window.end.isoformat(),
            }
        )
        if conflict:
            all_free = False
            conflict_intervals.extend(conflicts)
        else:
            any_free = True

    availability = "conflict"
    if all_free:
        availability = "available"
    elif any_free:
        availability = "partial"

    if availability != "available":
        for window in windows:
            collected_suggestions.extend(near_miss_suggestions(room, window, calendar_adapter))
            if len(collected_suggestions) >= 3:
                break

    seen_keys = set()
    dedup_conflicts: List[Dict[str, str]] = []
    for interval in conflict_intervals:
        key = (interval["start"], interval["end"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        dedup_conflicts.append(interval)

    return {
        "room": room.get("name"),
        "availability": availability,
        "per_day": per_day,
        "conflict_intervals": dedup_conflicts,
        "near_miss_suggestions": collected_suggestions[:3],
        "_meta": room,
    }


def evaluate_candidate_rooms(
    candidates: Sequence[Dict[str, Any]],
    windows: Sequence[RequestedWindow],
    calendar_adapter: CalendarAdapter,
    participants: Optional[int],
) -> List[Dict[str, Any]]:
    """[Condition] Evaluate all candidate rooms for the requested dates."""

    if not candidates:
        return []

    def _task(room: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        evaluation = evaluate_room(room, windows, calendar_adapter)
        return room, evaluation

    tasks = [lambda room=room: _task(room) for room in candidates]
    evaluations = run_io_tasks(tasks)

    results: List[Dict[str, Any]] = []
    for room, evaluation in evaluations:
        evaluation["capacity_ok"] = room_capacity_ok(room, participants)
        results.append(evaluation)
    return results


def choose_decision(
    preferred_room: Optional[str],
    rooms_checked: Sequence[Dict[str, Any]],
    participants: Optional[int],
) -> Tuple[str, Optional[str], str]:
    """[Condition] Decide the best outcome given room availability checks."""

    preferred_lower = (preferred_room or "").lower()
    preferred_entry = None
    for room in rooms_checked:
        if room["room"] and room["room"].lower() == preferred_lower:
            preferred_entry = room
            break

    if preferred_entry and preferred_entry["availability"] == "available":
        reason = f"Preferred room {preferred_entry['room']} is free on all requested days."
        return "preferred_available", preferred_entry["room"], reason

    available_rooms = [
        room
        for room in rooms_checked
        if room["availability"] == "available" and room["room"].lower() != preferred_lower
    ]

    if available_rooms:
        chosen = select_best_fit(available_rooms, participants)
        reason = f"Room {chosen['room']} is available; preferred room had conflicts."
        return "alternative_available", chosen["room"], reason

    reason = "No rooms fully available for the requested window."
    return "no_full_availability", None, reason


def select_best_fit(rooms: Sequence[Dict[str, Any]], participants: Optional[int]) -> Dict[str, Any]:
    """[Condition] Select the best alternative room based on capacity and features."""

    def score(room: Dict[str, Any]) -> Tuple[int, int]:
        meta = room["_meta"]
        capacity_max = meta.get("capacity_max") or 0
        capacity_min = meta.get("capacity_min") or 0
        if participants is None:
            delta = capacity_max
        else:
            delta = max(capacity_max - participants, 0)
        features = len(meta.get("features", []))
        return (delta, -features, capacity_min)

    return sorted(rooms, key=score)[0]


def outcome_from_decision(decision_status: str, rooms_checked: Sequence[Dict[str, Any]]) -> str:
    """[Condition] Map decision variants to human-readable outcomes."""

    if decision_status in {"preferred_available", "alternative_available"}:
        return "Available"
    any_options = any(room.get("near_miss_suggestions") for room in rooms_checked)
    any_partial = any(room.get("availability") == "partial" for room in rooms_checked)
    if any_options or any_partial:
        return "Option"
    return "Unavailable"


def build_options_for_reply(rooms_checked: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """[LLM] Build near-miss options to include in the drafted reply."""

    options: List[Dict[str, str]] = []
    for room in rooms_checked:
        for suggested in room.get("near_miss_suggestions", []):
            options.append(
                {
                    "room": room["room"],
                    "start": suggested["start"],
                    "end": suggested["end"],
                    "note": suggested.get("note", ""),
                }
            )
            if len(options) >= 3:
                break
        if len(options) >= 3:
            break
    if len(options) < 3:
        for room in rooms_checked:
            if len(options) >= 3:
                break
            for per_day in room.get("per_day", []):
                if per_day.get("state") != "free":
                    continue
                options.append(
                    {
                        "room": room["room"],
                        "start": per_day["start"],
                        "end": per_day["end"],
                        "note": "available on selected day",
                    }
                )
                if len(options) >= 3:
                    break
    return options


def compose_reply(
    event_data: Dict[str, Any],
    outcome: str,
    variant: str,
    room_label: str,
    date_label: str,
    options: Sequence[Dict[str, str]],
) -> Dict[str, str]:
    """[LLM] Draft the availability reply shown to clients."""

    name = event_data.get("Name") or "there"
    participants = event_data.get("Number of Participants") or "your group"
    start_time = event_data.get("Start Time") or ""
    end_time = event_data.get("End Time") or ""

    if outcome == "Available":
        subject = "Your requested date is available"
        body = (
            f"Hi {name},\n\n"
            f"Good news — {room_label} is available on {date_label} from {start_time} to {end_time} "
            f"for {participants} people.\n\n"
            "Next steps:\n"
            "• I can send a detailed price offer.\n"
            "• If you like, we can also arrange a short in-person visit of the venue.\n\n"
            "Best,\nEvent Manager"
        )
    elif outcome == "Option":
        subject = "We have close options for your date"
        if options:
            bullet_lines = []
            for opt in options[:3]:
                start_local = to_display_time(opt["start"])
                end_local = to_display_time(opt["end"])
                note = f" {opt['note']}" if opt.get("note") else ""
                bullet_lines.append(f"• {opt['room']}: {start_local}–{end_local}{note}")
            bullets = "\n".join(bullet_lines)
        else:
            bullets = "• (alternative time slots available)"
        body = (
            f"Hi {name},\n\n"
            "The requested time isn’t fully free, but we can offer these options at the Atelier:\n\n"
            f"{bullets}\n\n"
            "Let me know which option you prefer, or share alternative dates and I’ll recheck immediately.\n\n"
            "Best,\nEvent Manager"
        )
    else:
        subject = "Requested date currently unavailable"
        body = (
            f"Hi {name},\n\n"
            "Thanks a lot for your request — you caught me at just the right moment!\n"
            "Unfortunately, the requested date/time is currently unavailable.\n\n"
            "If you have alternative dates in mind, tell me a couple of options and I’ll check right away.\n\n"
            "Best,\nEvent Manager"
        )
    return {"subject": subject, "body": body}


def to_display_time(value: str) -> str:
    """[LLM] Convert ISO timestamps into venue-local time strings."""

    dt = parse_iso_datetime(value).astimezone(TZ)
    return dt.strftime("%H:%M")


def derive_room_label(variant: str, preferred_room: Optional[str], chosen_room: Optional[str]) -> str:
    """[LLM] Describe which room the reply references."""

    if variant == "preferred_available" and preferred_room:
        return f"your preferred room ({preferred_room})"
    if variant == "alternative_available" and chosen_room:
        return chosen_room
    return preferred_room or "our venue"


def ensure_comms(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """[OpenEvent Database] Ensure the communications block exists on the event."""

    comms = event_data.get("Comms") or {}
    event_data["Comms"] = comms
    return comms


def human_review(reply: Dict[str, Any], options: Sequence[Dict[str, str]]) -> str:
    """[OpenEvent Action] Console UI for manual approval of drafted replies."""

    while True:
        print("----------------------------------------------------")
        print(f"Outcome: {reply['outcome']} (variant: {reply['variant']})")
        print(f"Subject: {reply['draft']['subject']}")
        if options:
            print("Options:")
            for opt in options[:3]:
                print(
                    f"  - {opt['room']}: {to_display_time(opt['start'])}–{to_display_time(opt['end'])}"
                    f"{' ' + opt['note'] if opt.get('note') else ''}"
                )
        print("----------------------------------------------------")
        print(reply["draft"]["body"])
        print("----------------------------------------------------")
        cmd = input("[E]dit / [A]pprove & Publish / [C]ancel ? ").strip().lower()
        if cmd == "a":
            return "approve"
        if cmd == "c":
            return "cancel"
        if cmd == "e":
            print("Enter new message body. Finish with a single line '---END---'")
            lines: List[str] = []
            while True:
                line = input()
                if line.strip() == "---END---":
                    break
                lines.append(line)
            reply["draft"]["body"] = "\n".join(lines)
            continue
        print("Unrecognized choice. Please try again.")


def _load_workflow_db() -> Dict[str, Any]:
    return _load_db(WF_DB_PATH, lock_path=WF_LOCK_PATH)


def _save_workflow_db(db: Dict[str, Any]) -> None:
    _save_db(db, WF_DB_PATH, lock_path=WF_LOCK_PATH)


def run_availability_workflow(
    event_id: str,
    calendar_adapter: CalendarAdapter,
    client_gui_adapter: ClientGUIAdapter,
    rooms_path: Path | None = None,
) -> None:
    """[Trigger] Execute the full advanced availability workflow."""

    db = _load_workflow_db()
    events = db.get("events", [])
    event = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if event is None:
        raise ValueError(f"Event {event_id} not found")

    event_data = event.get("event_data") or {}

    if event_data.get("Status") != "Date Confirmed":
        raise ValueError("Event status must be 'Date Confirmed' to run availability workflow.")

    try:
        windows, overall_window = build_requested_windows(event_data)
    except ValueError as exc:
        reason = str(exc)
        event_data["Status"] = "Needs Clarification"

        ensure_comms(event_data)
        event_data["Comms"]["availability_reply"] = {
            "status": "draft",
            "outcome": "Unavailable",
            "variant": "no_full_availability",
            "room_label": event_data.get("Preferred Room") or "our venue",
            "date_label": to_display_date(event_data.get("Event Date", "")),
            "options": [],
            "draft": {
                "subject": "One more detail to proceed",
                "body": (
                    "Hi there,\n\n"
                    "To check availability, could you please share the start and end time for your event?\n\n"
                    "Best,\nEvent Manager"
                ),
            },
        }
        append_log(
            event,
            "availability_reply_drafted",
            {"outcome": "Unavailable", "variant": "no_full_availability", "reason": reason},
        )
        _save_workflow_db(db)
        print("[i] Drafted clarification reply (missing time).")
        return

    rooms = load_rooms_config(rooms_path)
    preferred_room = event_data.get("Preferred Room")
    preferred_room = None if not preferred_room or preferred_room == "Not specified" else preferred_room

    participants, capacity_unknown = parse_participants(event_data)
    candidates = build_candidate_rooms(rooms, preferred_room, participants)

    rooms_checked = evaluate_candidate_rooms(candidates, windows, calendar_adapter, participants)
    decision_status, chosen_room, decision_reason = choose_decision(preferred_room, rooms_checked, participants)
    outcome = outcome_from_decision(decision_status, rooms_checked)
    options = build_options_for_reply(rooms_checked)

    room_availability_block = {
        "requested_days": [window.date for window in windows],
        "window": overall_window,
        "preferred_room": preferred_room,
        "capacity_unknown": capacity_unknown,
        "rooms_checked": [
            {
                "room": room["room"],
                "capacity_ok": room["capacity_ok"],
                "availability": room["availability"],
                "per_day": room["per_day"],
                "conflict_intervals": room["conflict_intervals"],
                "near_miss_suggestions": room["near_miss_suggestions"],
            }
            for room in rooms_checked
        ],
        "decision": {
            "status": decision_status,
            "chosen_room": chosen_room,
            "reason": decision_reason,
        },
    }

    event_data["Room Availability"] = room_availability_block

    if outcome == "Available":
        event_data["Status"] = "Availability Assessed"
    elif options:
        event_data["Status"] = "Availability Constraints"
    else:
        event_data["Status"] = "Availability Constraints"

    append_log(event, "room_availability_assessed", room_availability_block)

    room_label = derive_room_label(decision_status, preferred_room, chosen_room)
    date_label = format_date_label(room_availability_block["requested_days"])

    reply_payload = compose_reply(event_data, outcome, decision_status, room_label, date_label, options)

    comms = ensure_comms(event_data)
    availability_reply = {
        "status": "draft",
        "outcome": outcome,
        "variant": decision_status,
        "room_label": room_label,
        "date_label": date_label,
        "options": options,
        "draft": {
            "subject": reply_payload["subject"],
            "body": reply_payload["body"],
        },
    }
    comms["availability_reply"] = availability_reply

    append_log(event, "availability_reply_drafted", {"outcome": outcome, "variant": decision_status})

    decision = human_review(
        {
            "outcome": outcome,
            "variant": decision_status,
            "draft": availability_reply["draft"],
        },
        options,
    )

    if decision == "cancel":
        _save_workflow_db(db)
        print("Cancelled. Draft saved only.")
        return

    availability_reply["status"] = "approved"
    availability_reply["approved"] = {"ts": now_iso(), "by": "Event Manager"}

    idempotency_key = f"availability_reply::{event_id}::{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        client_gui_adapter.upsert_card(
            event_id=event_id,
            card_type="availability_reply",
            payload={
                "subject": availability_reply["draft"]["subject"],
                "body": availability_reply["draft"]["body"],
                "outcome": outcome,
                "date_label": date_label,
                "room_label": room_label,
                "options": options,
            },
            idempotency_key=idempotency_key,
        )
    except Exception as exc:  # pragma: no cover - manual flow
        print(f"[!] Failed to publish to Client GUI: {exc}")
        _save_workflow_db(db)
        return

    availability_reply["status"] = "published"
    availability_reply["published"] = {
        "ts": now_iso(),
        "channel": "client_gui",
        "idempotency_key": idempotency_key,
    }

    append_log(
        event,
        "availability_reply_published_client_gui",
        {"idempotency_key": idempotency_key, "outcome": outcome},
    )

    _save_workflow_db(db)
    print("✅ Published to Client GUI.")
