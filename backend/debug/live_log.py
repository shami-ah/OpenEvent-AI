"""
Live Human-Readable Debug Log

Writes a simple, tailable log file for each active thread that shows
what's happening in real-time. Designed for LLM coding agents to quickly
understand workflow activity.

Usage:
    tail -f tmp-debug/live/{thread_id}.log

The log file is deleted when the thread is closed.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .settings import is_trace_enabled


def _root_dir() -> Path:
    custom = os.getenv("DEBUG_LIVE_LOG_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "tmp-debug" / "live"


ROOT = _root_dir()

# Track which threads have been initialized
_INITIALIZED: set[str] = set()


def _ensure_dir() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)


def _sanitise(thread_id: str) -> str:
    cleaned = thread_id.replace(os.sep, "_").replace("..", "_")
    return cleaned or "unknown-thread"


def _log_path(thread_id: str) -> Path:
    return ROOT / f"{_sanitise(thread_id)}.log"


def _format_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _format_event(event: Dict[str, Any]) -> str:
    """Format a trace event into a human-readable log line."""
    ts = _format_timestamp()
    kind = event.get("kind", "?")
    step = event.get("step") or event.get("owner_step") or "-"

    # Build the main line based on event type
    if kind == "STEP_ENTER":
        subject = event.get("subject") or step
        return f"[{ts}] >> ENTER {subject}"

    if kind == "STEP_EXIT":
        subject = event.get("subject") or step
        return f"[{ts}] << EXIT {subject}"

    if kind == "GATE_PASS":
        gate = event.get("gate") or {}
        label = gate.get("label") or event.get("subject") or "gate"
        met = gate.get("met", "?")
        required = gate.get("required", "?")
        return f"[{ts}] {step} | GATE PASS: {label} ({met}/{required})"

    if kind == "GATE_FAIL":
        gate = event.get("gate") or {}
        label = gate.get("label") or event.get("subject") or "gate"
        met = gate.get("met", "?")
        required = gate.get("required", "?")
        missing = gate.get("missing") or []
        missing_str = f" missing=[{', '.join(missing)}]" if missing else ""
        return f"[{ts}] {step} | GATE FAIL: {label} ({met}/{required}){missing_str}"

    if kind == "DB_READ":
        db = event.get("db") or event.get("io") or {}
        op = db.get("op") or event.get("subject") or "read"
        result = db.get("result") or ""
        return f"[{ts}] {step} | DB READ: {op}" + (f" -> {result}" if result else "")

    if kind == "DB_WRITE":
        db = event.get("db") or event.get("io") or {}
        op = db.get("op") or event.get("subject") or "write"
        return f"[{ts}] {step} | DB WRITE: {op}"

    if kind == "ENTITY_CAPTURE":
        entity = event.get("entity_context") or {}
        key = entity.get("key") or event.get("subject") or "entity"
        value = entity.get("value")
        value_str = f"={value}" if value is not None else ""
        return f"[{ts}] {step} | CAPTURED: {key}{value_str}"

    if kind == "ENTITY_SUPERSEDED":
        entity = event.get("entity_context") or {}
        key = entity.get("key") or event.get("subject") or "entity"
        return f"[{ts}] {step} | SUPERSEDED: {key}"

    if kind == "DETOUR":
        detour = event.get("detour") or {}
        from_step = detour.get("from_step") or step
        to_step = detour.get("to_step") or "?"
        reason = detour.get("reason") or ""
        return f"[{ts}] {step} | DETOUR: {from_step} -> {to_step} ({reason})"

    if kind in ("QA_ENTER", "GENERAL_QA"):
        detail = event.get("details") or event.get("detail") or ""
        if isinstance(detail, dict):
            detail = detail.get("label") or detail.get("fn") or ""
        return f"[{ts}] {step} | Q&A: {detail}"

    if kind == "QA_EXIT":
        return f"[{ts}] {step} | Q&A EXIT"

    if kind == "DRAFT_SEND":
        draft = event.get("draft") or {}
        footer = draft.get("footer") or {}
        next_step = footer.get("next") or ""
        state = footer.get("state") or ""
        parts = [f"DRAFT from {step}"]
        if next_step:
            parts.append(f"-> {next_step}")
        if state:
            parts.append(f"[{state}]")
        return f"[{ts}] {' '.join(parts)}"

    if kind == "AGENT_PROMPT_IN":
        subject = event.get("subject") or "prompt"
        preview = event.get("prompt_preview") or ""
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return f"[{ts}] {step} | LLM IN ({subject}): {preview}"

    if kind == "AGENT_PROMPT_OUT":
        subject = event.get("subject") or "response"
        preview = event.get("prompt_preview") or ""
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return f"[{ts}] {step} | LLM OUT ({subject}): {preview}"

    if kind == "STATE_SNAPSHOT":
        data = event.get("data") or {}
        # Extract key state values
        parts = []
        if data.get("chosen_date"):
            parts.append(f"date={data['chosen_date']}")
        if data.get("date_confirmed"):
            parts.append("date_confirmed=True")
        if data.get("locked_room_id"):
            parts.append(f"room={data['locked_room_id']}")
        if data.get("thread_state"):
            parts.append(f"state={data['thread_state']}")
        if data.get("hil_open"):
            parts.append("hil_open=True")
        summary = ", ".join(parts) if parts else "initial state"
        return f"[{ts}] {step} | STATE: {summary}"

    # Fallback for unknown kinds
    summary = event.get("summary") or event.get("subject") or kind
    return f"[{ts}] {step} | {kind}: {summary}"


def append_log(thread_id: str, event: Dict[str, Any]) -> None:
    """Append a formatted log line for this event."""
    if not is_trace_enabled():
        return

    # Only log "logic" granularity events by default
    granularity = event.get("granularity", "verbose")
    if granularity != "logic":
        return

    _ensure_dir()

    # Auto-initialize on first event for this thread
    if thread_id not in _INITIALIZED:
        write_header(thread_id)
        _INITIALIZED.add(thread_id)

    line = _format_event(event)
    path = _log_path(thread_id)

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass  # Don't fail the workflow if logging fails


def write_header(thread_id: str) -> None:
    """Write a header to the log file when a thread starts."""
    if not is_trace_enabled():
        return

    _ensure_dir()
    path = _log_path(thread_id)
    now = datetime.now(timezone.utc).isoformat()

    header = f"""================================================================================
OpenEvent Live Debug Log
Thread: {thread_id}
Started: {now}
================================================================================
Watch with: tail -f {path}
API endpoint: /api/debug/threads/{thread_id}/llm-diagnosis
================================================================================

"""
    try:
        with path.open("w", encoding="utf-8") as f:
            f.write(header)
            f.flush()
    except Exception:
        pass


def close_log(thread_id: str, reason: str = "closed") -> Optional[Path]:
    """Close and delete the live log file for this thread."""
    # Remove from initialized set
    _INITIALIZED.discard(thread_id)

    path = _log_path(thread_id)
    if not path.exists():
        return None

    try:
        # Write closing message
        ts = _format_timestamp()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n[{ts}] === THREAD CLOSED: {reason} ===\n")
            f.flush()

        # Delete the file
        path.unlink()
        return path
    except Exception:
        return None


def get_log_path(thread_id: str) -> Optional[Path]:
    """Get the path to the live log file if it exists."""
    path = _log_path(thread_id)
    return path if path.exists() else None


def list_active_logs() -> list[str]:
    """List all active thread IDs with live logs."""
    if not ROOT.exists():
        return []
    return [p.stem for p in ROOT.glob("*.log")]


__all__ = [
    "append_log",
    "write_header",
    "close_log",
    "get_log_path",
    "list_active_logs",
]
