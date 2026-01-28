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

from domain import EventStatus, TaskStatus
from utils import json_io
from utils.calendar_events import create_calendar_event

__workflow_role__ = "Database"


LOCK_TIMEOUT = 60.0  # Allow up to 60s for message processing
LOCK_SLEEP = 0.1
STALE_LOCK_AGE_SECONDS = 300  # Consider lock stale if file is older than 5 minutes

logger = logging.getLogger(__name__)


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)  # Signal 0 = check if process exists
        return True
    except OSError:
        return False


def _cleanup_stale_lock(lock_path: Path) -> bool:
    """
    Remove stale lock file if the owning process is dead.

    Returns True if a stale lock was removed, False otherwise.
    """
    if not lock_path.exists():
        return False

    try:
        # Read the PID from the lock file
        with open(lock_path, "r") as f:
            content = f.read().strip()

        if not content:
            # Empty lock file - might be in process of being written (race condition)
            # Check file age before removing - new files (<1s) might still be getting PID
            try:
                file_age = time.time() - lock_path.stat().st_mtime
                if file_age < 1.0:
                    # Lock file is very new - don't remove, might be getting written
                    return False
            except OSError:
                pass  # File might have been removed already
            lock_path.unlink()
            logger.warning("Removed empty/corrupted lock file: %s", lock_path)
            return True

        try:
            pid = int(content)
        except ValueError:
            # Invalid PID content - remove the lock
            lock_path.unlink()
            logger.warning("Removed lock file with invalid PID content: %s", lock_path)
            return True

        # Check if the process is still running
        if not _is_process_running(pid):
            lock_path.unlink()
            logger.warning("Removed stale lock file (PID %d is dead): %s", pid, lock_path)
            return True

        # Process is still running - also check file age as a fallback
        # (in case PID was recycled to a different process)
        file_age = time.time() - lock_path.stat().st_mtime
        if file_age > STALE_LOCK_AGE_SECONDS:
            lock_path.unlink()
            logger.warning(
                "Removed stale lock file (age %.0fs > %ds): %s",
                file_age, STALE_LOCK_AGE_SECONDS, lock_path
            )
            return True

    except (OSError, IOError) as e:
        logger.debug("Could not check/cleanup stale lock %s: %s", lock_path, e)

    return False


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
        stale_check_done = False

        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("utf-8"))
                return
            except FileExistsError:
                # First time we hit a lock, check if it's stale
                if not stale_check_done:
                    if _cleanup_stale_lock(self.path):
                        # Stale lock removed - retry immediately
                        stale_check_done = True
                        continue
                    stale_check_done = True

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


def load_db(path: Path, lock_path: Optional[Path] = None, *, _lock_held: bool = False) -> Dict[str, Any]:
    """[OpenEvent Database] Load and validate the events database from disk.

    Args:
        path: Path to the database JSON file
        lock_path: Optional explicit lock path
        _lock_held: If True, skip lock acquisition (caller already holds lock)
    """

    path = Path(path)
    if not path.exists():
        return get_default_db()

    def _do_load():
        with path.open("r", encoding="utf-8") as fh:
            return json_io.load(fh)

    if _lock_held:
        db = _do_load()
    else:
        lock_candidate = lock_path_for(path, lock_path)
        with FileLock(lock_candidate):
            db = _do_load()
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


def save_db(db: Dict[str, Any], path: Path, lock_path: Optional[Path] = None, *, _lock_held: bool = False) -> None:
    """[OpenEvent Database] Persist the database atomically with crash-safe semantics.

    Args:
        db: The database dict to persist
        path: Path to the database JSON file
        lock_path: Optional explicit lock path
        _lock_held: If True, skip lock acquisition (caller already holds lock)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_db = {
        "events": db.get("events", []),
        "clients": db.get("clients", {}),
        "tasks": db.get("tasks", []),
        "config": db.get("config", {}),
    }

    def _do_save():
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

    if _lock_held:
        _do_save()
    else:
        lock_candidate = lock_path_for(path, lock_path)
        with FileLock(lock_candidate):
            _do_save()


def upsert_client(db: Dict[str, Any], email: str, name: Optional[str] = None, event_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """[OpenEvent Database] Create or return a client profile keyed by email."""

    client_id = (email or "").lower()
    clients = db.setdefault("clients", {})
    is_new_client = client_id not in clients
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

    # Log client creation activity for manager visibility (only for new clients)
    if is_new_client and event_entry:
        from activity.persistence import log_workflow_activity
        client_name = name or email
        log_workflow_activity(event_entry, "client_saved", client_name=client_name)

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

    # Import here to avoid circular dependency
    from workflows.io.integration.config import get_team_id

    event_id = str(uuid.uuid4())
    entry = {
        "event_id": event_id,
        "team_id": get_team_id(),  # Multi-tenancy: store owning team
        "created_at": datetime.utcnow().isoformat(),
        "status": EventStatus.LEAD.value,
        "current_step": 1,
        "caller_step": None,
        "thread_state": "In Progress",
        "chosen_date": None,
        "end_date": None,           # DD.MM.YYYY for multi-day events
        "end_date_iso": None,       # YYYY-MM-DD for multi-day events
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

    # Log event creation activity for manager visibility
    from activity.persistence import log_workflow_activity
    log_workflow_activity(entry, "event_created", status=EventStatus.LEAD.value)

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

    event.setdefault("team_id", None)  # Multi-tenancy: None for legacy records
    event.setdefault("status", EventStatus.LEAD.value)
    event.setdefault("current_step", 1)
    event.setdefault("current_step_stage", "step_1")
    event.setdefault("caller_step", None)
    event.setdefault("caller_step_stage", None)
    event.setdefault("subflow_group", "intake")
    event.setdefault("thread_state", "In Progress")
    event.setdefault("chosen_date", None)
    event.setdefault("end_date", None)       # DD.MM.YYYY for multi-day events
    event.setdefault("end_date_iso", None)   # YYYY-MM-DD for multi-day events
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
    """[OpenEvent Database] Apply metadata updates on workflow-specific fields.

    When 'status' is set to a booking status (Lead/Option/Confirmed),
    also syncs to event_data["Status"] for backward compatibility.

    Also logs manager-visible activities for key workflow transitions.
    """
    from activity.persistence import log_workflow_activity

    ensure_event_defaults(event)

    # Track step changes for activity logging
    old_step = event.get("current_step")

    for key, value in fields.items():
        event[key] = value

    # Sync booking status to event_data["Status"] for backward compatibility
    # Only sync recognized booking statuses, not workflow stages
    if "status" in fields:
        booking_status = fields["status"]
        if booking_status in ("Lead", "Option", "Confirmed"):
            event.setdefault("event_data", {})["Status"] = booking_status
            # Log room status change (coarse - always visible)
            status_key = f"status_{booking_status.lower()}"
            log_workflow_activity(event, status_key)
        elif booking_status == "Cancelled":
            reason = fields.get("cancellation_reason", "")
            log_workflow_activity(event, "status_cancelled", reason=reason)

    # Log activity for step transitions (manager-visible)
    if "current_step" in fields:
        new_step = fields["current_step"]
        if new_step != old_step and new_step in (1, 2, 3, 4, 5, 6, 7):
            activity_key = f"step_{new_step}_entered"
            log_workflow_activity(event, activity_key)


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
    query_start_time: Optional[str] = None,
    query_end_time: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """[OpenEvent Database] Get site visits that overlap with a time window.

    Used when booking an event - if there's a site visit overlapping with the
    requested time, we allow the event but create a manager notification.

    Time-aware overlap detection:
    - If query times are provided, checks for actual time overlap
    - Site visits without time_slot are assumed to be all-day
    - Falls back to date-only comparison if no time info available

    Args:
        db: The database dict
        date_iso: Date to check (YYYY-MM-DD format)
        query_start_time: Optional start time (HH:MM) for time-aware overlap
        query_end_time: Optional end time (HH:MM) for time-aware overlap

    Returns:
        List of event entries that have site visits overlapping with the query
    """
    from workflows.common.time_window import TimeWindow

    visits: List[Dict[str, Any]] = []

    # Build query window if times provided
    query_window: Optional[TimeWindow] = None
    if query_start_time and query_end_time:
        query_window = TimeWindow.from_date_and_times(
            date_iso, query_start_time, query_end_time
        )

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

        # Time-aware overlap check
        if query_window is not None:
            # Get site visit time slot (default to 1-hour if specified)
            sv_time = sv_state.get("time_slot") or sv_state.get("confirmed_time")
            if sv_time:
                # Site visits typically last 1 hour
                try:
                    parts = sv_time.split(":")
                    sv_start_hour = int(parts[0])
                    sv_start_min = int(parts[1]) if len(parts) > 1 else 0
                    sv_end_hour = sv_start_hour + 1  # 1-hour default duration
                    sv_end_time = f"{sv_end_hour:02d}:{sv_start_min:02d}"
                    sv_window = TimeWindow.from_date_and_times(
                        sv_date_iso, sv_time, sv_end_time
                    )
                except (ValueError, IndexError):
                    sv_window = TimeWindow.all_day(sv_date_iso)
            else:
                # No time specified - treat as all-day
                sv_window = TimeWindow.all_day(sv_date_iso)

            # Check overlap
            if sv_window and not query_window.overlaps(sv_window):
                continue  # No time overlap = no conflict

            visits.append(event)
        else:
            # Date-only comparison (backward compatibility)
            if sv_date_iso == date_iso:
                visits.append(event)

    return visits
