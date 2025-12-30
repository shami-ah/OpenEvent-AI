from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache

from backend.domain import EventStatus, TaskStatus
from backend.utils import json_io
from backend.utils.calendar_events import create_calendar_event

__workflow_role__ = "Database"


LOCK_TIMEOUT = 5.0
LOCK_SLEEP = 0.1

logger = logging.getLogger(__name__)


class FileLock:
    """[OpenEvent Database] Coarse-grained filesystem lock to guard JSON persistence."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT, sleep: float = LOCK_SLEEP) -> None:
        self.path = path
        self.timeout = timeout
        self.sleep = sleep
        self.fd: Optional[int] = None

    def acquire(self) -> None:
        """[OpenEvent Database] Block until a lock file can be created or raise on timeout."""

        deadline = time.time() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                return
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Could not acquire lock {self.path}")
                time.sleep(self.sleep)

    def release(self) -> None:
        """[OpenEvent Database] Drop the lock file once a critical section completes."""

        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.path.exists():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "FileLock":
        """[OpenEvent Database] Enter a context manager that owns the lock."""

        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """[OpenEvent Database] Release the lock when leaving the context manager."""

        self.release()


def get_default_db() -> Dict[str, Any]:
    """[OpenEvent Database] Provide the baseline JSON schema for a clean database."""

    return {"events": [], "clients": {}, "tasks": []}


def lock_path_for(path: Path, default_lock: Optional[Path] = None) -> Path:
    """[OpenEvent Database] Derive a sibling lockfile path for a JSON resource."""

    path = Path(path)
    if default_lock is not None:
        return default_lock
    return path.with_name(f".{path.name}.lock")


def load_db(path: Path, lock_path: Optional[Path] = None) -> Dict[str, Any]:
    """[OpenEvent Database] Load and validate the events database from disk."""

    path = Path(path)
    if not path.exists():
        return get_default_db()
    lock_candidate = lock_path_for(path, lock_path)
    with FileLock(lock_candidate):
        with path.open("r", encoding="utf-8") as fh:
            db = json_io.load(fh)
    if "events" not in db or not isinstance(db["events"], list):
        db["events"] = []
    if "clients" not in db or not isinstance(db["clients"], dict):
        db["clients"] = {}
    if "tasks" not in db or not isinstance(db["tasks"], list):
        db["tasks"] = []
    events = db.get("events", [])
    for event in events:
        ensure_event_defaults(event)
    return db


def save_db(db: Dict[str, Any], path: Path, lock_path: Optional[Path] = None) -> None:
    """[OpenEvent Database] Persist the database atomically with crash-safe semantics."""

    path = Path(path)
    lock_candidate = lock_path_for(path, lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_db = {
        "events": db.get("events", []),
        "clients": db.get("clients", {}),
        "tasks": db.get("tasks", []),
        "config": db.get("config", {}),
    }
    with FileLock(lock_candidate):
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json_io.dump(out_db, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def upsert_client(db: Dict[str, Any], email: str, name: Optional[str] = None) -> Dict[str, Any]:
    """[OpenEvent Database] Create or return a client profile keyed by email."""

    client_id = (email or "").lower()
    clients = db.setdefault("clients", {})
    client = clients.setdefault(
        client_id,
        {
            "profile": {"name": None, "org": None, "phone": None},
            "history": [],
            "event_ids": [],
        },
    )
    if name:
        client["profile"]["name"] = client["profile"]["name"] or name
    return client


def append_history(client: Dict[str, Any], msg: Dict[str, Any], intent: str, conf: float, user_info: Dict[str, Any]) -> None:
    """[OpenEvent Database] Record a message snapshot under the client's communication history."""

    history = client.setdefault("history", [])
    body_preview = (msg.get("body") or "")[:160]
    history.append(
        {
            "msg_id": msg.get("msg_id"),
            "ts": msg.get("ts"),
            "subject": msg.get("subject"),
            "body_preview": body_preview,
            "intent": intent,
            "confidence": float(conf),
            "user_info": dict(user_info),
        }
    )


def link_event_to_client(client: Dict[str, Any], event_id: str) -> None:
    """[OpenEvent Database] Associate an event identifier with a client record."""

    event_ids = client.setdefault("event_ids", [])
    if event_id not in event_ids:
        event_ids.append(event_id)


def _last_event_for_email(db: Dict[str, Any], email_lc: str) -> Optional[Dict[str, Any]]:
    """[OpenEvent Database] Locate the newest event entry for a given email."""

    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for idx, event in enumerate(db.get("events", [])):
        data = event.get("event_data", {})
        if (data.get("Email") or "").lower() == email_lc:
            created = event.get("created_at") or ""
            candidates.append((created, idx, event))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _snapshot_hash(payload: Dict[str, Any]) -> str:
    normalized = json_io.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def context_snapshot(db: Dict[str, Any], client: Dict[str, Any], email_lc: str) -> Dict[str, Any]:
    """[OpenEvent Database] Assemble a short context payload for downstream steps."""

    history_tail = client.get("history", [])[-5:]
    snapshot = {
        "profile": dict(client.get("profile", {})),
        "history_tail": history_tail,
        "last_event": _last_event_for_email(db, email_lc),
    }
    snapshot_hash = _snapshot_hash(snapshot)
    snapshot["context_hash"] = snapshot_hash
    return snapshot


def last_event_for_email(db: Dict[str, Any], email_lc: str) -> Optional[Dict[str, Any]]:
    """[OpenEvent Database] Fetch the newest event associated with a client email."""

    return _last_event_for_email(db, email_lc)


def find_event_idx(db: Dict[str, Any], client_email: str, event_date_ddmmyyyy: str) -> Optional[int]:
    """[OpenEvent Database] Locate an existing event entry by email and event date."""

    candidates: List[Tuple[int, str]] = []
    for idx, event in enumerate(db.get("events", [])):
        data = event.get("event_data", {})
        if (data.get("Email") or "").lower() == (client_email or "").lower() and data.get("Event Date") == event_date_ddmmyyyy:
            created = event.get("created_at", "")
            candidates.append((idx, created))
    if not candidates:
        return None
    candidates.sort(key=lambda item: ((item[1] or ""), item[0]), reverse=True)
    return candidates[0][0]


def find_event_idx_by_id(db: Dict[str, Any], event_id: str) -> Optional[int]:
    """[OpenEvent Database] Locate an event entry by its identifier."""

    for idx, event in enumerate(db.get("events", [])):
        if event.get("event_id") == event_id:
            return idx
    return None


def create_event_entry(db: Dict[str, Any], event_data: Dict[str, Any]) -> str:
    """[OpenEvent Database] Insert a new event entry and return its identifier."""

    event_id = str(uuid.uuid4())
    entry = {
        "event_id": event_id,
        "created_at": datetime.utcnow().isoformat(),
        "status": EventStatus.LEAD.value,
        "current_step": 1,
        "caller_step": None,
        "thread_state": "In Progress",
        "chosen_date": None,
        "date_confirmed": False,
        "locked_room_id": None,
        "requirements": {},
        "requirements_hash": None,
        "room_eval_hash": None,
        "offer_id": None,
        "audit": [],
        "review_state": {
            "state": "none",
            "reviewed_at": None,
            "message": None,
        },
        "event_data": event_data,
        "msgs": [],
        "captured": {},
        "verified": {},
        "captured_sources": [],
        "deferred_intents": [],
    }
    db.setdefault("events", []).append(entry)
    try:
        calendar_event = create_calendar_event(entry, "lead")
        entry["calendar_event_id"] = calendar_event.get("id")
        logger.info("Created calendar event for new booking: %s", event_id)
    except Exception as exc:  # pragma: no cover - best-effort calendar logging
        logger.warning("Failed to create calendar event: %s", exc)
        # Don't fail the booking if calendar creation fails
    return event_id


def update_event_entry(db: Dict[str, Any], idx: int, new_data: Dict[str, Any]) -> List[str]:
    """[OpenEvent Database] Apply partial updates to an existing event entry."""

    event = db["events"][idx]
    event_data = event.setdefault("event_data", {})
    updated: List[str] = []
    for key, value in new_data.items():
        if value in (None, "Not specified"):
            continue
        current = event_data.get(key)
        if (
            key == "Additional Info"
            and current
            and current != "Not specified"
            and current != value
            and isinstance(current, str)
            and isinstance(value, str)
        ):
            if value not in current:
                combined = f"{current} | {value}"
            else:
                combined = current
            if combined != current:
                event_data[key] = combined
                updated.append(key)
            continue
        if current != value:
            event_data[key] = value
            updated.append(key)
    return updated


def ensure_event_defaults(event: Dict[str, Any]) -> None:
    """[OpenEvent Database] Backfill workflow fields on legacy event records."""

    event.setdefault("status", EventStatus.LEAD.value)
    event.setdefault("current_step", 1)
    event.setdefault("current_step_stage", "step_1")
    event.setdefault("caller_step", None)
    event.setdefault("caller_step_stage", None)
    event.setdefault("subflow_group", "intake")
    event.setdefault("thread_state", "In Progress")
    event.setdefault("chosen_date", None)
    event.setdefault("date_confirmed", False)
    event.setdefault("locked_room_id", None)
    event.setdefault("requested_window", {})
    event.setdefault("requirements", {})
    event.setdefault("requirements_hash", None)
    event.setdefault("room_eval_hash", None)
    event.setdefault("offer_id", None)
    event.setdefault("offer_hash", None)
    event.setdefault("audit", [])
    event.setdefault(
        "review_state",
        {"state": "none", "reviewed_at": None, "message": None},
    )
    event.setdefault("offers", [])
    event.setdefault("current_offer_id", None)
    event.setdefault("offer_sequence", 0)
    event.setdefault("products", [])
    event.setdefault("selected_products", [])
    event.setdefault("requested_products", [])
    event.setdefault("selected_catering", [])
    event.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    event.setdefault("transition_ready", False)
    event.setdefault("captured", {})
    event.setdefault("verified", {})
    event.setdefault("captured_sources", [])
    event.setdefault("deferred_intents", [])
    if not isinstance(event["captured"], dict):
        event["captured"] = {}
    if not isinstance(event["verified"], dict):
        event["verified"] = {}
    if not isinstance(event["captured_sources"], list):
        event["captured_sources"] = []
    if not isinstance(event["deferred_intents"], list):
        event["deferred_intents"] = []
    event.setdefault("calendar_blocks", [])
    event.setdefault(
        "deposit_state",
        {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0},
    )
    event.setdefault(
        "site_visit_state",
        {"status": "idle", "proposed_slots": [], "scheduled_slot": None},
    )
    event.setdefault("confirmation_state", {"last_response_type": None})
    products_state = event.setdefault(
        "products_state",
        {
            "available_items": [],
            "manager_added_items": [],
            "line_items": [],
            "pending_hil_requests": [],
            "budgets": {},
            "presented_interest": {},
            "preask_pending": {},
        },
    )
    products_state.setdefault("available_items", [])
    products_state.setdefault("manager_added_items", [])
    products_state.setdefault("line_items", [])
    products_state.setdefault("pending_hil_requests", [])
    products_state.setdefault("budgets", {})
    products_state.setdefault("presented_interest", {})
    products_state.setdefault("preask_pending", {})
    event.setdefault("pending_intents", [])
    event.setdefault("edit_trace", [])
    event.setdefault("choice_context", None)
    gatekeeper = event.setdefault(
        "gatekeeper_passed",
        {"step2": False, "step3": False, "step4": False, "step7": False},
    )
    for key in ("step2", "step3", "step4", "step7"):
        gatekeeper.setdefault(key, False)
    event.setdefault("decision", "pending")


def append_audit_entry(
    event: Dict[str, Any],
    from_step: int,
    to_step: int,
    reason: str,
    actor: str = "system",
) -> None:
    """[OpenEvent Database] Append an audit log entry for workflow transitions."""

    ensure_event_defaults(event)
    audit = event.setdefault("audit", [])
    audit.append(
        {
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "actor": actor,
            "from_step": from_step,
            "to_step": to_step,
            "reason": reason,
        }
    )


def update_event_metadata(event: Dict[str, Any], **fields: Any) -> None:
    """[OpenEvent Database] Apply metadata updates on workflow-specific fields."""

    ensure_event_defaults(event)
    for key, value in fields.items():
        event[key] = value


def tag_message(event_entry: Dict[str, Any], msg_id: Optional[str]) -> None:
    """[OpenEvent Database] Link a processed message to the event entry for audit."""

    if not msg_id:
        return
    msgs_list = event_entry.setdefault("msgs", [])
    if msg_id not in msgs_list:
        msgs_list.append(msg_id)


def update_event_date(
    db: Dict[str, Any],
    event_id: str,
    date_iso: str,
) -> Dict[str, Any]:
    """[OpenEvent Database] Persist the confirmed event date for an event."""

    idx = find_event_idx_by_id(db, event_id)
    if idx is None:
        raise ValueError(f"Event {event_id} not found.")
    event_entry = db["events"][idx]
    ensure_event_defaults(event_entry)

    display_date: Optional[str]
    try:
        display_date = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        display_date = None

    event_data = event_entry.setdefault("event_data", {})
    if display_date:
        event_data["Event Date"] = display_date
    else:
        event_data["Event Date"] = date_iso

    update_event_metadata(
        event_entry,
        chosen_date=display_date or date_iso,
        date_confirmed=True,
        last_confirmed_iso=date_iso,
    )
    return event_entry


def update_event_billing(
    db: Dict[str, Any],
    event_id: str,
    billing_details: Dict[str, Any],
) -> Dict[str, Any]:
    """[OpenEvent Database] Persist structured billing details for an event."""

    idx = find_event_idx_by_id(db, event_id)
    if idx is None:
        raise ValueError(f"Event {event_id} not found.")
    event_entry = db["events"][idx]
    ensure_event_defaults(event_entry)

    event_data = event_entry.setdefault("event_data", {})
    raw_address = billing_details.get("raw")
    if raw_address:
        event_data["Billing Address"] = raw_address

    current = event_entry.get("billing_details") or {}
    merged = dict(current)
    for key, value in billing_details.items():
        if value:
            merged[key] = value
    event_entry["billing_details"] = merged
    return event_entry


def update_event_room(
    db: Dict[str, Any],
    event_id: str,
    *,
    selected_room: str,
    status: str,
) -> Dict[str, Any]:
    """[OpenEvent Database] Persist the room selection captured via select_room."""

    idx = find_event_idx_by_id(db, event_id)
    if idx is None:
        raise ValueError(f"Event {event_id} not found.")

    event_entry = db["events"][idx]
    ensure_event_defaults(event_entry)

    update_event_metadata(
        event_entry,
        selected_room=selected_room,
        selected_room_status=status,
    )
    flags = event_entry.setdefault("flags", {})
    flags["room_selected"] = True

    pending = event_entry.setdefault("room_pending_decision", {})
    pending["selected_room"] = selected_room
    pending["selected_status"] = status

    return event_entry


def record_room_search_start(
    db: Dict[str, Any],
    event_id: str,
    *,
    date_iso: str,
    participants: Optional[int],
) -> Dict[str, Any]:
    """[OpenEvent Database] Register the start of a room availability evaluation."""

    idx = find_event_idx_by_id(db, event_id)
    if idx is None:
        raise ValueError(f"Event {event_id} not found.")
    event_entry = db["events"][idx]
    ensure_event_defaults(event_entry)
    logs = event_entry.setdefault("logs", [])
    logs.append(
        {
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "actor": "workflow",
            "action": "room_search_started",
            "details": {
                "date_iso": date_iso,
                "participants": participants,
            },
        }
    )
    return event_entry


def default_event_record(user_info: Dict[str, Any], msg: Dict[str, Any], received_date: str) -> Dict[str, Any]:
    """[OpenEvent Database] Translate sanitized user info into the event DB schema."""

    participant_count: Optional[str]
    if user_info.get("participants") is None:
        participant_count = "Not specified"
    else:
        participant_count = str(user_info["participants"])
    return {
        "Date Email Received": received_date,
        "Status": EventStatus.LEAD.value,
        "Event Date": user_info.get("event_date") or "Not specified",
        "Name": msg.get("from_name") or "Not specified",
        "Email": msg.get("from_email"),
        "Phone": user_info.get("phone") or "Not specified",
        "Company": user_info.get("company") or "Not specified",
        "Billing Address": "Not specified",
        "Start Time": user_info.get("start_time") or "Not specified",
        "End Time": user_info.get("end_time") or "Not specified",
        "Preferred Room": user_info.get("room") or "Not specified",
        "Number of Participants": participant_count,
        "Type of Event": user_info.get("type") or "Not specified",
        "Catering Preference": user_info.get("catering") or "Not specified",
        "Billing Amount": "none",
        "Deposit": "none",
        "Language": user_info.get("language") or "Not specified",
        "Additional Info": user_info.get("notes") or "Not specified",
    }


@lru_cache(maxsize=4)
def _load_rooms_cached(resolved_path: str) -> List[str]:
    rooms_path = Path(resolved_path)
    if not rooms_path.exists():
        return ["Punkt.Null", "Room A", "Room B", "Room C"]
    with rooms_path.open("r", encoding="utf-8") as handle:
        payload = json_io.load(handle)
    rooms = payload.get("rooms") or []
    return [room.get("name") for room in rooms if room.get("name")]


def load_rooms(path: Optional[Path] = None) -> List[str]:
    """[OpenEvent Database] Load room names from the canonical configuration file."""

    rooms_path = path or Path(__file__).resolve().parents[2] / "data" / "rooms.json"
    resolved = str(rooms_path.resolve())
    return list(_load_rooms_cached(resolved))


def clear_cached_rooms() -> None:
    """Clear the memoized room list (used by tests to reset state)."""

    _load_rooms_cached.cache_clear()


def get_event_dates(
    db: Dict[str, Any],
    *,
    exclude_event_id: Optional[str] = None,
    exclude_cancelled: bool = True,
) -> List[str]:
    """[OpenEvent Database] Get all event dates from the database.

    Returns dates in ISO format (YYYY-MM-DD) for all events.
    Used for site visit conflict detection - site visits cannot be
    booked on days when events are scheduled.

    Args:
        db: The database dict (from load_db)
        exclude_event_id: Optionally exclude a specific event (e.g., current event)
        exclude_cancelled: If True, exclude events with status 'Cancelled'

    Returns:
        List of ISO date strings (YYYY-MM-DD)
    """
    dates: List[str] = []

    for event in db.get("events", []):
        # Skip excluded event
        if exclude_event_id and event.get("event_id") == exclude_event_id:
            continue

        # Skip cancelled events if requested
        if exclude_cancelled:
            status = event.get("status", "")
            if status.lower() == "cancelled":
                continue

        # Get date from chosen_date (confirmed) or event_data
        date_str = event.get("chosen_date")
        if not date_str:
            event_data = event.get("event_data", {})
            date_str = event_data.get("Event Date")

        if not date_str or date_str == "Not specified":
            continue

        # Normalize to ISO format
        try:
            if "." in date_str:
                # dd.mm.yyyy format
                day, month, year = map(int, date_str.split("."))
                dates.append(f"{year:04d}-{month:02d}-{day:02d}")
            elif "-" in date_str:
                # Already ISO format
                dates.append(date_str[:10])
        except (ValueError, IndexError):
            # Skip malformed dates
            continue

    return dates


def get_site_visits_on_date(
    db: Dict[str, Any],
    date_iso: str,
) -> List[Dict[str, Any]]:
    """[OpenEvent Database] Get site visits scheduled on a specific date.

    Used when booking an event - if there's a site visit on that day,
    we allow the event but create a manager notification.

    Args:
        db: The database dict
        date_iso: Date to check (YYYY-MM-DD format)

    Returns:
        List of event entries that have site visits on that date
    """
    visits: List[Dict[str, Any]] = []

    for event in db.get("events", []):
        sv_state = event.get("site_visit_state", {})
        if sv_state.get("status") != "scheduled":
            continue

        # Get site visit date
        sv_date = sv_state.get("date_iso") or sv_state.get("confirmed_date")
        if not sv_date:
            continue

        # Normalize for comparison
        try:
            if "." in sv_date:
                day, month, year = map(int, sv_date.split("."))
                sv_date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            else:
                sv_date_iso = sv_date[:10]
        except (ValueError, IndexError):
            continue

        if sv_date_iso == date_iso:
            visits.append(event)

    return visits
