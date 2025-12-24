from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain import IntentLabel
from backend.workflows.common.prompts import compose_footer, FOOTER_SEPARATOR


@dataclass
class IncomingMessage:
    """[Trigger] Normalized representation of an inbound workflow message."""

    msg_id: Optional[str]
    from_name: Optional[str]
    from_email: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    ts: Optional[str]
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IncomingMessage":
        """[Trigger] Build an IncomingMessage from a raw dict payload."""

        # Extract known fields
        known_keys = {"msg_id", "from_name", "from_email", "subject", "body", "ts"}
        extras = {k: v for k, v in payload.items() if k not in known_keys}

        return cls(
            msg_id=payload.get("msg_id"),
            from_name=payload.get("from_name"),
            from_email=payload.get("from_email"),
            subject=payload.get("subject"),
            body=payload.get("body"),
            ts=payload.get("ts"),
            extras=extras,
        )

    def to_payload(self) -> Dict[str, Optional[str]]:
        """[Trigger] Expose message details in adapter-friendly format."""

        return {
            "msg_id": self.msg_id,
            "from_name": self.from_name,
            "from_email": self.from_email,
            "subject": self.subject,
            "body": self.body,
            "ts": self.ts,
        }


@dataclass
class TurnTelemetry:
    """[Telemetry] Per-turn instrumentation payload for downstream logging."""

    buttons_rendered: bool = False
    buttons_enabled: bool = False
    missing_fields: List[str] = field(default_factory=list)
    clicked_button: str = "none"
    final_action: str = "none"
    detour_started: bool = False
    detour_completed: bool = False
    no_op_detour: bool = False
    caller_step: Optional[int] = None
    gatekeeper_passed: Dict[str, bool] = field(
        default_factory=lambda: {"step2": False, "step3": False, "step4": False, "step7": False}
    )
    gatekeeper_explain: Dict[str, Any] = field(default_factory=dict)
    answered_question_first: bool = False
    delta_availability_used: bool = False
    menus_included: str = "false"
    menus_phase: str = "none"
    preask_candidates: List[str] = field(default_factory=list)
    preask_shown: List[str] = field(default_factory=list)
    preask_response: Dict[str, str] = field(default_factory=dict)
    preview_class_shown: str = "none"
    preview_items_count: int = 0
    choice_context_active: bool = False
    selection_method: str = "none"
    re_prompt_reason: str = "none"
    llm: Dict[str, Any] = field(default_factory=dict)
    captured_fields: List[str] = field(default_factory=list)
    promoted_fields: List[str] = field(default_factory=list)
    deferred_intents: List[str] = field(default_factory=list)
    dag_blocked: str = "none"
    atomic_default: bool = False
    # Ad-hoc diagnostic events appended by steps for deep debugging
    log_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        """Serialise telemetry into a JSON-friendly payload."""

        return {
            "buttons_rendered": self.buttons_rendered,
            "buttons_enabled": self.buttons_enabled,
            "missing_fields": list(self.missing_fields),
            "clicked_button": self.clicked_button,
            "final_action": self.final_action,
            "detour_started": self.detour_started,
            "detour_completed": self.detour_completed,
            "no_op_detour": self.no_op_detour,
            "caller_step": self.caller_step,
            "gatekeeper_passed": dict(self.gatekeeper_passed),
            "gatekeeper_explain": dict(self.gatekeeper_explain),
            "answered_question_first": self.answered_question_first,
            "delta_availability_used": self.delta_availability_used,
            "menus_included": self.menus_included,
            "menus_phase": self.menus_phase,
            "preask_candidates": list(self.preask_candidates),
            "preask_shown": list(self.preask_shown),
            "preask_response": dict(self.preask_response),
            "preview_class_shown": self.preview_class_shown,
            "preview_items_count": self.preview_items_count,
            "choice_context_active": self.choice_context_active,
            "selection_method": self.selection_method,
            "re_prompt_reason": self.re_prompt_reason,
            "llm": dict(self.llm),
            "captured_fields": list(self.captured_fields),
            "promoted_fields": list(self.promoted_fields),
            "deferred_intents": list(self.deferred_intents),
            "dag_blocked": self.dag_blocked,
            "atomic_default": self.atomic_default,
            "log_events": list(self.log_events),
        }

    # ------------------------------------------------------------------ #
    # Mapping helpers for dynamic telemetry fields
    # ------------------------------------------------------------------ #

    def setdefault(self, key: str, default: Any) -> Any:
        """Mimic dict.setdefault for known telemetry attributes."""

        if hasattr(self, key):
            value = getattr(self, key)
            if key == "llm" and not value:
                assigned = dict(default) if isinstance(default, dict) else default
                setattr(self, key, assigned)
                return getattr(self, key)
            if isinstance(value, list) and not value:
                assigned_list = list(default) if isinstance(default, list) else default
                setattr(self, key, assigned_list)
                return getattr(self, key)
            if value is None:
                setattr(self, key, default)
                return getattr(self, key)
            return value
        setattr(self, key, default)
        return getattr(self, key)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
            return
        raise KeyError(key)


@dataclass
class WorkflowState:
    """[OpenEvent Database] Mutable state shared between workflow groups."""

    message: IncomingMessage
    db_path: Path
    db: Dict[str, Any]
    client: Optional[Dict[str, Any]] = None
    client_id: Optional[str] = None
    thread_id: Optional[str] = None
    intent: Optional[IntentLabel] = None
    confidence: Optional[float] = None
    user_info: Dict[str, Any] = field(default_factory=dict)
    intent_detail: Optional[str] = None
    event_id: Optional[str] = None
    event_entry: Optional[Dict[str, Any]] = None
    updated_fields: list[str] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)
    current_step: Optional[int] = None
    caller_step: Optional[int] = None
    subflow_group: Optional[str] = None
    thread_state: Optional[str] = None
    draft_messages: List[Dict[str, Any]] = field(default_factory=list)
    turn_notes: Dict[str, Any] = field(default_factory=dict)
    subloops_trace: List[str] = field(default_factory=list)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)
    telemetry: TurnTelemetry = field(default_factory=TurnTelemetry)

    def record_context(self, context: Dict[str, Any]) -> None:
        """[OpenEvent Database] Store the latest context snapshot for the workflow."""

        self.context_snapshot = context

    def add_draft_message(self, message: Dict[str, Any]) -> None:
        """[HIL] Register a draft message awaiting approval before sending."""

        step_value = message.get("step") or self.current_step or 0
        next_step = message.get("next_step", step_value)
        thread_state = message.get("thread_state") or self.thread_state or "Awaiting Client"

        body_markdown = message.pop("body_markdown", None)
        raw_body = message.get("body")
        footer = message.get("footer")

        if body_markdown is None and isinstance(raw_body, str) and raw_body:
            if FOOTER_SEPARATOR in raw_body:
                before, _, after = raw_body.partition(FOOTER_SEPARATOR)
                body_markdown = before.strip()
                if not footer:
                    footer = after.strip()
            else:
                body_markdown = raw_body.strip()

        if body_markdown is None:
            body_markdown = ""

        if not footer:
            footer = compose_footer(step_value or 0, next_step, thread_state)

        message["body_markdown"] = body_markdown
        message["footer"] = footer
        message.setdefault("table_blocks", [])
        message.setdefault("actions", [])
        message["thread_state"] = thread_state
        message.setdefault("next_step", next_step)
        subloop = message.get("subloop") or self.extras.get("subloop")
        if subloop:
            message["subloop"] = subloop

        combined_body = f"{body_markdown}{FOOTER_SEPARATOR}{footer}" if body_markdown else footer
        message["body"] = combined_body

        message.setdefault("requires_approval", True)
        message.setdefault("created_at_step", step_value)
        self.draft_messages.append(message)

        try:
            from backend.debug.hooks import trace_draft  # pylint: disable=import-outside-toplevel
        except Exception:
            trace_draft = None  # type: ignore[assignment]

        if trace_draft:
            footer_payload = _decode_footer_payload(footer, next_step, thread_state)
            trace_draft(
                _thread_identifier(self),
                _step_name(step_value),
                footer_payload,
                message.get("actions") or [],
                message.get("body_markdown"),
                message.get("subloop"),
            )

    def record_subloop(self, label: Optional[str]) -> None:
        """Record a debugger subloop for trace outputs."""

        if not label:
            return
        if label not in self.subloops_trace:
            self.subloops_trace.append(label)

    def set_thread_state(self, value: str) -> None:
        """[OpenEvent Database] Track whether the thread awaits a client reply."""

        self.thread_state = value

    def add_audit_entry(self, from_step: int, to_step: int, reason: str, actor: str = "system") -> None:
        """[OpenEvent Database] Buffer audit entries for persistence."""

        self.audit_log.append(
            {
                "from_step": from_step,
                "to_step": to_step,
                "reason": reason,
                "actor": actor,
            }
        )





@dataclass
class GroupResult:
    """[Trigger] Encapsulates the outcome of a workflow group."""

    action: str
    payload: Dict[str, Any] = field(default_factory=dict)
    halt: bool = False

    def merged(self) -> Dict[str, Any]:
        """[Condition] Combine the action label with payload for orchestrator consumption."""

        data = dict(self.payload)
        data.setdefault("action", self.action)
        return data


_STEP_NAME_MAP = {
    1: "Step1_Intake",
    2: "Step2_Date",
    3: "Step3_Room",
    4: "Step4_Offer",
    5: "Step5_Negotiation",
    6: "Step6_Transition",
    7: "Step7_Confirmation",
}


def _step_name(value: Any) -> str:
    if isinstance(value, str):
        try:
            value_int = int(value)
        except ValueError:
            value_int = None
    else:
        value_int = value if isinstance(value, int) else None
    if value_int in _STEP_NAME_MAP:
        return _STEP_NAME_MAP[value_int]
    return "intake"


def _decode_footer_payload(footer: Optional[str], next_step: Any, thread_state: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "text": footer or "",
        "step": None,
        "next": None,
        "wait_state": None,
    }
    if footer:
        segments = [segment.strip() for segment in footer.split("·")]
        for segment in segments:
            lowered = segment.lower()
            if lowered.startswith("step:"):
                payload["step"] = segment.split(":", 1)[1].strip()
            elif lowered.startswith("next:"):
                payload["next"] = segment.split(":", 1)[1].strip()
            elif lowered.startswith("state:"):
                payload["wait_state"] = segment.split(":", 1)[1].strip()
    if payload["next"] is None and next_step is not None:
        payload["next"] = str(next_step)
    if payload["wait_state"] is None and thread_state is not None:
        payload["wait_state"] = str(thread_state)
    return payload


def _thread_identifier(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
