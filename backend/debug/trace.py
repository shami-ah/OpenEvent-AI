from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from .settings import is_trace_enabled

TraceKind = Literal[
    "STEP_ENTER",
    "STEP_EXIT",
    "GATE_PASS",
    "GATE_FAIL",
    "DB_READ",
    "DB_WRITE",
    "ENTITY_CAPTURE",
    "ENTITY_SUPERSEDED",
    "DETOUR",
    "QA_ENTER",
    "QA_EXIT",
    "GENERAL_QA",
    "DRAFT_SEND",
    "STATE_SNAPSHOT",
    "AGENT_PROMPT_IN",
    "AGENT_PROMPT_OUT",
]

Lane = Literal["step", "gate", "db", "entity", "detour", "qa", "draft", "prompt"]

LANE_BY_KIND: Dict[TraceKind, Lane] = {
    "STEP_ENTER": "step",
    "STEP_EXIT": "step",
    "DRAFT_SEND": "draft",
    "STATE_SNAPSHOT": "step",
    "GATE_PASS": "gate",
    "GATE_FAIL": "gate",
    "DB_READ": "db",
    "DB_WRITE": "db",
    "ENTITY_CAPTURE": "entity",
    "ENTITY_SUPERSEDED": "entity",
    "DETOUR": "detour",
    "QA_ENTER": "qa",
    "QA_EXIT": "qa",
    "GENERAL_QA": "qa",
    "AGENT_PROMPT_IN": "prompt",
    "AGENT_PROMPT_OUT": "prompt",
}

_SEQ_COUNTER: Dict[str, int] = {}
_STEP_MINOR_STATE: Dict[str, Tuple[Optional[int], int]] = {}
_TRACE_SUMMARY: Dict[str, Dict[str, Any]] = {}
_SUMMARY_LOCK = threading.Lock()
_HIL_LOCK = threading.Lock()
_LAST_ENTITY_LABEL: Dict[str, Optional[str]] = {}
_HIL_OPEN: Dict[str, bool] = {}
_SUBLOOP_CONTEXT: Dict[str, Optional[str]] = {}
REQUIREMENTS_MATCH_HELP = "Deterministic digest of date, pax, and constraints. 'Match' means inputs didn’t change since the last evaluation."


@dataclass
class TraceEvent:
    thread_id: str
    ts: float
    seq: int
    row_id: str
    kind: TraceKind
    lane: Lane
    step: Optional[str] = None
    owner_step: Optional[str] = None
    entity: Optional[str] = None
    actor: Optional[str] = None
    step_major: Optional[int] = None
    step_minor: Optional[int] = None
    event: Optional[str] = None
    details: Optional[str] = None
    detail: Optional[Any] = None
    subject: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    captured_additions: List[str] = field(default_factory=list)
    confirmed_now: List[str] = field(default_factory=list)
    loop: bool = False
    detour_to_step: Optional[int] = None
    wait_state: Optional[str] = None
    granularity: str = "verbose"
    gate: Optional[Dict[str, Any]] = None
    io: Optional[Dict[str, Any]] = None
    prompt_preview: Optional[str] = None
    hash_status: Optional[str] = None
    hash_help: Optional[str] = None
    entity_context: Optional[Dict[str, Any]] = None
    db: Optional[Dict[str, Any]] = None
    detour: Optional[Dict[str, Any]] = None
    draft: Optional[Dict[str, Any]] = None
    subloop: Optional[str] = None


def _next_sequence(thread_id: str) -> int:
    seq = _SEQ_COUNTER.get(thread_id, 0) + 1
    _SEQ_COUNTER[thread_id] = seq
    return seq


def _derive_step_major(step_label: Optional[str]) -> Optional[int]:
    if not step_label:
        return None
    for token in str(step_label).split("_"):
        if token.isdigit():
            return int(token)
    if isinstance(step_label, str) and step_label.startswith("Step"):
        digits = "".join(ch for ch in step_label if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def _next_step_minor(thread_id: str, major: Optional[int]) -> Optional[int]:
    if not major:
        return None
    current_major, counter = _STEP_MINOR_STATE.get(thread_id, (None, 0))
    if current_major != major:
        counter = 0
    counter += 1
    _STEP_MINOR_STATE[thread_id] = (major, counter)
    return counter


def _record_summary(
    thread_id: str,
    *,
    step_major: Optional[int],
    wait_state: Optional[str],
    hash_status: Optional[str],
) -> None:
    with _SUMMARY_LOCK:
        summary = _TRACE_SUMMARY.setdefault(thread_id, {})
        if step_major:
            summary["current_step_major"] = step_major
        if wait_state is not None:
            summary["wait_state"] = wait_state
        summary.setdefault("hash_help", REQUIREMENTS_MATCH_HELP)
        if hash_status is not None:
            summary["hash_status"] = hash_status
        summary["hil_open"] = has_open_hil(thread_id)


def get_trace_summary(thread_id: str) -> Dict[str, Any]:
    with _SUMMARY_LOCK:
        summary = _TRACE_SUMMARY.get(thread_id, {})
        result = dict(summary)
        result.setdefault("hil_open", has_open_hil(thread_id))
        return result


def set_hil_open(thread_id: str, is_open: bool) -> None:
    with _HIL_LOCK:
        if is_open:
            _HIL_OPEN[thread_id] = True
        else:
            _HIL_OPEN.pop(thread_id, None)
    if not is_trace_enabled():
        return
    try:  # pragma: no cover - defensive guard to avoid circular failures
        from backend.debug.state_store import STATE_STORE  # pylint: disable=import-outside-toplevel

        snapshot = STATE_STORE.get(thread_id) or {}
        if snapshot.get("hil_open") == is_open:
            return
        snapshot = dict(snapshot)
        snapshot["hil_open"] = is_open
        STATE_STORE.update(thread_id, snapshot)
    except Exception:
        pass


def has_open_hil(thread_id: str) -> bool:
    with _HIL_LOCK:
        return _HIL_OPEN.get(thread_id, False)


def set_subloop_context(thread_id: str, subloop: Optional[str]) -> None:
    if subloop:
        _SUBLOOP_CONTEXT[thread_id] = subloop
    else:
        _SUBLOOP_CONTEXT.pop(thread_id, None)


def clear_subloop_context(thread_id: str) -> None:
    _SUBLOOP_CONTEXT.pop(thread_id, None)


def get_subloop_context(thread_id: str) -> Optional[str]:
    return _SUBLOOP_CONTEXT.get(thread_id)


class TraceBus:
    def __init__(self, max_events: int = 2000) -> None:
        self._buf: Dict[str, List[TraceEvent]] = {}
        self._lock = threading.Lock()
        self._max = max_events

    def emit(self, ev: TraceEvent) -> None:
        with self._lock:
            buf = self._buf.setdefault(ev.thread_id, [])
            buf.append(ev)
            if len(buf) > self._max:
                del buf[: len(buf) - self._max]

    def get(self, thread_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(ev) for ev in self._buf.get(thread_id, [])]

    def list_threads(self) -> List[str]:
        with self._lock:
            return list(self._buf.keys())


BUS = TraceBus()


def emit(
    thread_id: str,
    kind: TraceKind,
    *,
    step: Optional[str] = None,
    detail: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
    subject: Optional[str] = None,
    status: Optional[str] = None,
    summary: Optional[str] = None,
    lane: Optional[Lane] = None,
    loop: bool = False,
    detour_to_step: Optional[int] = None,
    wait_state: Optional[str] = None,
    owner_step: Optional[str] = None,
    granularity: str = "verbose",
    gate: Optional[Dict[str, Any]] = None,
    entity: Optional[Dict[str, Any]] = None,
    entity_label: Optional[str] = None,
    actor: Optional[str] = None,
    event_name: Optional[str] = None,
    details_label: Optional[str] = None,
    captured_additions: Optional[List[str]] = None,
    confirmed_now: Optional[List[str]] = None,
    io: Optional[Dict[str, Any]] = None,
    db: Optional[Dict[str, Any]] = None,
    detour: Optional[Dict[str, Any]] = None,
    draft: Optional[Dict[str, Any]] = None,
    prompt_preview: Optional[str] = None,
    hash_status: Optional[str] = None,
    hash_help: Optional[str] = None,
) -> None:
    if not is_trace_enabled():
        return
    lane_value = lane or LANE_BY_KIND[kind]
    payload = dict(data or {})
    effective_io = io or db
    summary_text = summary or _derive_summary(
        kind,
        step,
        detail,
        subject,
        status,
        payload,
        gate=gate,
        entity=entity,
        db=effective_io,
        detour=detour,
        draft=draft,
    )
    ts = time.time()
    seq = _next_sequence(thread_id)
    row_id = f"{int(ts * 1000)}.{seq:04d}"
    owner = owner_step or step
    step_major = _derive_step_major(owner)
    step_minor = _next_step_minor(thread_id, step_major)
    details_text = details_label
    detail_payload: Optional[Dict[str, Any]]
    if isinstance(detail, dict):
        detail_payload = dict(detail)
        details_text = details_text or detail_payload.get("fn") or detail_payload.get("label")
    elif detail is not None:
        details_text = details_text or str(detail)
        detail_payload = {"label": str(detail)}
    else:
        detail_payload = None
    if detail_payload is None and details_text:
        detail_payload = {"fn": details_text}
    elif detail_payload is not None and details_text:
        detail_payload.setdefault("fn", details_text)
    if not details_text:
        details_text = subject or (payload.get("op") if isinstance(payload, dict) else None)
    if effective_io and not details_text:
        details_text = effective_io.get("op")
    effective_entity = entity_label
    if kind == "STATE_SNAPSHOT":
        if wait_state:
            effective_entity = entity_label or "Waiting"
        else:
            effective_entity = entity_label or _LAST_ENTITY_LABEL.get(thread_id)
    elif effective_entity is None:
        effective_entity = _LAST_ENTITY_LABEL.get(thread_id)

    current_subloop = get_subloop_context(thread_id)
    if current_subloop and isinstance(payload, dict):
        payload.setdefault("subloop", current_subloop)

    event = TraceEvent(
        thread_id=thread_id,
        ts=ts,
        seq=seq,
        row_id=row_id,
        kind=kind,
        lane=lane_value,
        step=step,
        owner_step=owner,
        entity=effective_entity,
        actor=actor,
        step_major=step_major,
        step_minor=step_minor,
        event=event_name,
        details=details_text,
        detail=detail_payload,
        subject=subject,
        status=status,
        summary=summary_text,
        payload=payload,
        data=payload,
        captured_additions=list(captured_additions or []),
        confirmed_now=list(confirmed_now or []),
        loop=loop,
        detour_to_step=detour_to_step,
        wait_state=wait_state,
        granularity=granularity,
        gate=gate,
        io=effective_io,
        prompt_preview=prompt_preview,
        hash_status=hash_status,
        hash_help=hash_help or (REQUIREMENTS_MATCH_HELP if hash_status else None),
        entity_context=entity,
        db=effective_io,
        detour=detour,
        draft=draft,
        subloop=current_subloop,
    )
    if event.entity and event.entity != "Waiting":
        _LAST_ENTITY_LABEL[thread_id] = event.entity
    BUS.emit(event)
    _record_summary(
        thread_id,
        step_major=event.step_major if (event.step_major and (event.entity or "") != "Waiting") else None,
        wait_state=wait_state,
        hash_status=event.hash_status,
    )
    try:
        from . import timeline  # pylint: disable=import-outside-toplevel

        timeline.append(thread_id, asdict(event))
    except Exception:
        pass

    # Also write to human-readable live log
    try:
        from . import live_log  # pylint: disable=import-outside-toplevel

        live_log.append_log(thread_id, asdict(event))
    except Exception:
        pass


def _derive_summary(
    kind: TraceKind,
    step: Optional[str],
    detail: Optional[Any],
    subject: Optional[str],
    status: Optional[str],
    payload: Dict[str, Any],
    *,
    gate: Optional[Dict[str, Any]] = None,
    entity: Optional[Dict[str, Any]] = None,
    db: Optional[Dict[str, Any]] = None,
    detour: Optional[Dict[str, Any]] = None,
    draft: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Generate a compact summary line for the timeline table."""

    detail_label: Optional[str]
    if isinstance(detail, dict):
        detail_label = detail.get("label") or detail.get("fn")
    else:
        detail_label = detail

    if gate:
        label = gate.get("label") or detail_label or subject or step or "gate"
        result = gate.get("result") or status or ("PASS" if kind == "GATE_PASS" else "FAIL")
        inputs = gate.get("inputs") or payload
        input_preview = ""
        if inputs:
            formatted = ", ".join(f"{k}={_stringify(v)}" for k, v in list(inputs.items())[:3])
            input_preview = f" ({formatted})"
        return f"{label}: {result}{input_preview}"

    if entity:
        lifecycle = entity.get("lifecycle") or status or "captured"
        key = entity.get("key") or subject or detail_label or "entity"
        value = entity.get("value")
        return f"{lifecycle} {key}={_stringify(value)}"

    if db:
        op = db.get("op") or detail_label or subject or step or "db"
        mode = db.get("mode") or ("READ" if kind == "DB_READ" else "WRITE")
        duration = db.get("duration_ms")
        suffix = f" ({duration}ms)" if duration is not None else ""
        return f"{mode} {op}{suffix}"

    if detour:
        from_step = detour.get("from_step") or step or subject or "detour"
        to_step = detour.get("to_step")
        reason = detour.get("reason") or detail or ""
        arrow = f" → {to_step}" if to_step else ""
        return f"{from_step}{arrow} {reason}".strip()

    if draft:
        footer = draft.get("footer") or {}
        step_label = footer.get("step") or step or "Draft"
        next_step = footer.get("next")
        wait_state = footer.get("state")
        pieces = [step_label]
        if next_step:
            pieces.append(f"→ {next_step}")
        if wait_state:
            pieces.append(wait_state)
        return " · ".join(pieces)

    if subject:
        value = payload.get("value")
        if value is None and "summary" in payload:
            value = payload.get("summary")
        if value is not None:
            return f"{subject}={_stringify(value)}"

    if kind in {"DB_READ", "DB_WRITE"}:
        target = detail_label or step or payload.get("resource") or "db"
        action = "READ" if kind == "DB_READ" else "WRITE"
        return f"{action} {target}"

    if kind in {"GATE_PASS", "GATE_FAIL"}:
        label = detail_label or step or subject or "gate"
        verdict = status or ("pass" if kind == "GATE_PASS" else "fail")
        return f"{label}: {verdict}"

    if kind == "DETOUR":
        if detail_label:
            return detail_label
        return payload.get("reason") or "detour"

    if kind == "DRAFT_SEND":
        footer = payload.get("footer") or {}
        step_label = footer.get("step") or step or "Draft"
        next_step = footer.get("next")
        state = footer.get("wait_state")
        pieces = [step_label]
        if next_step:
            pieces.append(f"→ {next_step}")
        if state:
            pieces.append(state)
        return " · ".join(pieces)

    if payload.get("summary"):
        return str(payload["summary"])

    if detail_label:
        return detail_label
    if step:
        return step
    return None


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        text = str(value)
    else:
        text = str(value)
    if len(text) > 80:
        return f"{text[:77]}…"
    return text


__all__ = [
    "TraceEvent",
    "TraceBus",
    "TraceKind",
    "Lane",
    "LANE_BY_KIND",
    "BUS",
    "emit",
    "get_trace_summary",
    "set_hil_open",
    "has_open_hil",
    "set_subloop_context",
    "clear_subloop_context",
    "get_subloop_context",
    "REQUIREMENTS_MATCH_HELP",
]
