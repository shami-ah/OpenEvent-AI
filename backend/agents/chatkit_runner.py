from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, Iterable, List, Optional, Set

from pydantic import ValidationError

from backend.agents.guardrails import safe_envelope
from backend.agents.openevent_agent import OpenEventAgent
from backend.workflows.io.config_store import get_venue_name
from backend.utils.openai_key import SECRET_NAME, load_openai_api_key
from backend.agents.tools.dates import (
    SuggestDatesInput,
    ParseDateIntentInput,
    tool_suggest_dates,
    tool_parse_date_intent,
    TOOL_SCHEMA as DATES_TOOL_SCHEMA,
)
from backend.agents.tools.rooms import (
    EvaluateRoomsInput,
    RoomStatusInput,
    CapacityCheckInput,
    tool_evaluate_rooms,
    tool_room_status_on_date,
    tool_capacity_check,
    TOOL_SCHEMA as ROOMS_TOOL_SCHEMA,
)
from backend.agents.tools.offer import (
    ComposeOfferInput,
    PersistOfferInput,
    ModifyProductInput,
    FollowUpSuggestInput,
    ListCateringInput,
    ListProductsInput,
    SendOfferInput,
    tool_build_offer_draft,
    tool_persist_offer,
    tool_add_product_to_offer,
    tool_remove_product_from_offer,
    tool_follow_up_suggest,
    tool_list_catering,
    tool_list_products,
    tool_send_offer,
    TOOL_SCHEMA as OFFER_TOOL_SCHEMA,
)
from backend.agents.tools.negotiation import NegotiationInput, tool_negotiate_offer, TOOL_SCHEMA as NEGOTIATION_TOOL_SCHEMA
from backend.agents.tools.transition import TransitionInput, tool_transition_sync, TOOL_SCHEMA as TRANSITION_TOOL_SCHEMA
from backend.agents.tools.confirmation import ConfirmationInput, tool_classify_confirmation, TOOL_SCHEMA as CONFIRM_TOOL_SCHEMA

logger = logging.getLogger(__name__)

ENGINE_TOOL_ALLOWLIST: Dict[str, Set[str]] = {
    "2": {
        "tool_suggest_dates",
        "tool_parse_date_intent",
    },
    "3": {
        "tool_room_status_on_date",
        "tool_capacity_check",
        "tool_evaluate_rooms",
    },
    "4": {
        "tool_build_offer_draft",
        "tool_persist_offer",
        "tool_list_products",
        "tool_list_catering",
        "tool_add_product_to_offer",
        "tool_remove_product_from_offer",
        "tool_send_offer",
    },
    "5": {
        "tool_negotiate_offer",
        "tool_transition_sync",
    },
    "7": {
        "tool_follow_up_suggest",
        "tool_classify_confirmation",
    },
}

CLIENT_STOP_AT_TOOLS: Set[str] = {
    "client_confirm_offer",
    "client_change_offer",
    "client_discard_offer",
    "client_see_catering",
    "client_see_products",
}

# OpenAI tool schema for chat-completions fallback (matches ENGINE_TOOL_ALLOWLIST keys)
OPENAI_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {"type": "function", "function": {"name": "tool_suggest_dates", "parameters": DATES_TOOL_SCHEMA["tool_suggest_dates"]}},
    {"type": "function", "function": {"name": "tool_parse_date_intent", "parameters": DATES_TOOL_SCHEMA["tool_parse_date_intent"]}},
    {"type": "function", "function": {"name": "tool_room_status_on_date", "parameters": ROOMS_TOOL_SCHEMA["tool_room_status_on_date"]}},
    {"type": "function", "function": {"name": "tool_capacity_check", "parameters": ROOMS_TOOL_SCHEMA["tool_capacity_check"]}},
    {"type": "function", "function": {"name": "tool_evaluate_rooms", "parameters": ROOMS_TOOL_SCHEMA["tool_evaluate_rooms"]}},
    {"type": "function", "function": {"name": "tool_list_products", "parameters": OFFER_TOOL_SCHEMA["tool_list_products"]}},
    {"type": "function", "function": {"name": "tool_list_catering", "parameters": OFFER_TOOL_SCHEMA["tool_list_catering"]}},
    {"type": "function", "function": {"name": "tool_build_offer_draft", "parameters": OFFER_TOOL_SCHEMA["tool_build_offer_draft"]}},
    {"type": "function", "function": {"name": "tool_persist_offer", "parameters": OFFER_TOOL_SCHEMA["tool_persist_offer"]}},
    {"type": "function", "function": {"name": "tool_add_product_to_offer", "parameters": OFFER_TOOL_SCHEMA["tool_add_product_to_offer"]}},
    {"type": "function", "function": {"name": "tool_remove_product_from_offer", "parameters": OFFER_TOOL_SCHEMA["tool_remove_product_from_offer"]}},
    {"type": "function", "function": {"name": "tool_send_offer", "parameters": OFFER_TOOL_SCHEMA["tool_send_offer"]}},
    {"type": "function", "function": {"name": "tool_negotiate_offer", "parameters": NEGOTIATION_TOOL_SCHEMA["tool_negotiate_offer"]}},
    {"type": "function", "function": {"name": "tool_transition_sync", "parameters": TRANSITION_TOOL_SCHEMA["tool_transition_sync"]}},
    {"type": "function", "function": {"name": "tool_follow_up_suggest", "parameters": OFFER_TOOL_SCHEMA["tool_follow_up_suggest"]}},
    {"type": "function", "function": {"name": "tool_classify_confirmation", "parameters": CONFIRM_TOOL_SCHEMA["tool_classify_confirmation"]}},
]


TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "tool_suggest_dates": {
        "type": "object",
        "properties": {
            "event_id": {"type": ["string", "null"]},
            "preferred_room": {"type": ["string", "null"]},
            "start_from_iso": {"type": ["string", "null"]},
            "days_ahead": {"type": "integer", "minimum": 1, "maximum": 120},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "additionalProperties": False,
    },
    "tool_room_status_on_date": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": r"^\d{2}\.\d{2}\.\d{4}$"},
            "room": {"type": "string"},
        },
        "required": ["date", "room"],
        "additionalProperties": False,
    },
    "tool_evaluate_rooms": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": r"^\d{2}\.\d{2}\.\d{4}$"},
        },
        "required": ["date"],
        "additionalProperties": False,
    },
    "tool_list_products": {
        "type": "object",
        "properties": {
            "room_id": {"type": ["string", "null"]},
            "categories": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    },
    "tool_list_catering": {
        "type": "object",
        "properties": {
            "room_id": {"type": ["string", "null"]},
            "date_token": {"type": ["string", "null"]},
            "categories": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    },
    "tool_send_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "offer_id": {"type": "string"},
            "to_email": {"type": "string"},
            "cc": {"type": ["string", "null"]},
        },
        "required": ["event_entry", "offer_id", "to_email"],
        "additionalProperties": False,
    },
    "tool_parse_date_intent": {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    "tool_capacity_check": {
        "type": "object",
        "properties": {
            "room": {"type": "string"},
            "attendees": {"type": ["integer", "null"], "minimum": 1},
            "layout": {"type": ["string", "null"]},
        },
        "required": ["room"],
        "additionalProperties": False,
    },
    "tool_build_offer_draft": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "user_info": {"type": ["object", "null"]},
        },
        "required": ["event_entry"],
        "additionalProperties": False,
    },
    "tool_persist_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "pricing_inputs": {"type": "object"},
            "user_info": {"type": ["object", "null"]},
        },
        "required": ["event_entry", "pricing_inputs"],
        "additionalProperties": False,
    },
    "tool_add_product_to_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "product": {"type": "object"},
        },
        "required": ["event_entry", "product"],
        "additionalProperties": False,
    },
    "tool_remove_product_from_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "product": {"type": "object"},
        },
        "required": ["event_entry", "product"],
        "additionalProperties": False,
    },
    "tool_follow_up_suggest": {
        "type": "object",
        "properties": {
            "status": {"type": ["string", "null"]},
            "pending_actions": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    },
    "tool_negotiate_offer": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "client_email": {"type": "string"},
            "message": {"type": "string"},
            "msg_id": {"type": ["string", "null"]},
        },
        "required": ["event_id", "client_email", "message"],
        "additionalProperties": False,
    },
    "tool_transition_sync": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "client_email": {"type": "string"},
            "message": {"type": "string"},
            "msg_id": {"type": ["string", "null"]},
        },
        "required": ["event_id", "client_email", "message"],
        "additionalProperties": False,
    },
    "tool_classify_confirmation": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "client_email": {"type": "string"},
            "message": {"type": "string"},
            "msg_id": {"type": ["string", "null"]},
        },
        "required": ["event_id", "client_email", "message"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ToolDefinition:
    handler: Callable[..., Any]
    input_model: Any
    requires_db: bool = False
    schema: Dict[str, Any] = field(default_factory=dict)
    use_event_entry: bool = False


TOOL_DEFINITIONS: Dict[str, ToolDefinition] = {
    "tool_suggest_dates": ToolDefinition(
        handler=tool_suggest_dates,
        input_model=SuggestDatesInput,
        requires_db=True,
        schema=TOOL_SCHEMAS["tool_suggest_dates"],
    ),
    "tool_room_status_on_date": ToolDefinition(
        handler=tool_room_status_on_date,
        input_model=RoomStatusInput,
        requires_db=True,
        schema=TOOL_SCHEMAS["tool_room_status_on_date"],
    ),
    "tool_evaluate_rooms": ToolDefinition(
        handler=tool_evaluate_rooms,
        input_model=EvaluateRoomsInput,
        requires_db=True,
        schema=TOOL_SCHEMAS["tool_evaluate_rooms"],
    ),
    "tool_list_products": ToolDefinition(
        handler=tool_list_products,
        input_model=ListProductsInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_list_products"],
    ),
    "tool_list_catering": ToolDefinition(
        handler=tool_list_catering,
        input_model=ListCateringInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_list_catering"],
    ),
    "tool_send_offer": ToolDefinition(
        handler=tool_send_offer,
        input_model=SendOfferInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_send_offer"],
    ),
    "tool_parse_date_intent": ToolDefinition(
        handler=tool_parse_date_intent,
        input_model=ParseDateIntentInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_parse_date_intent"],
    ),
    "tool_capacity_check": ToolDefinition(
        handler=tool_capacity_check,
        input_model=CapacityCheckInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_capacity_check"],
    ),
    "tool_build_offer_draft": ToolDefinition(
        handler=tool_build_offer_draft,
        input_model=ComposeOfferInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_build_offer_draft"],
        use_event_entry=True,
    ),
    "tool_persist_offer": ToolDefinition(
        handler=tool_persist_offer,
        input_model=PersistOfferInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_persist_offer"],
        use_event_entry=True,
    ),
    "tool_add_product_to_offer": ToolDefinition(
        handler=tool_add_product_to_offer,
        input_model=ModifyProductInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_add_product_to_offer"],
    ),
    "tool_remove_product_from_offer": ToolDefinition(
        handler=tool_remove_product_from_offer,
        input_model=ModifyProductInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_remove_product_from_offer"],
    ),
    "tool_follow_up_suggest": ToolDefinition(
        handler=tool_follow_up_suggest,
        input_model=FollowUpSuggestInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_follow_up_suggest"],
    ),
    "tool_negotiate_offer": ToolDefinition(
        handler=tool_negotiate_offer,
        input_model=NegotiationInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_negotiate_offer"],
    ),
    "tool_transition_sync": ToolDefinition(
        handler=tool_transition_sync,
        input_model=TransitionInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_transition_sync"],
    ),
    "tool_classify_confirmation": ToolDefinition(
        handler=tool_classify_confirmation,
        input_model=ConfirmationInput,
        requires_db=False,
        schema=TOOL_SCHEMAS["tool_classify_confirmation"],
    ),
}


class ToolExecutionError(RuntimeError):
    """Raised when a tool invocation violates the step-aware allowlist or schema."""

    def __init__(
        self,
        tool_name: str,
        step: Optional[int],
        *,
        reason: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.step = step
        allowed = StepToolPolicy.allowed_tools_for(step)
        detail = {
            "tool": tool_name,
            "step": step,
            "allowed_tools": sorted(allowed),
        }
        if reason:
            detail["reason"] = reason
        if extra:
            detail.update(extra)
        super().__init__(json.dumps(detail))
        self.detail = detail


@dataclass
class StepToolPolicy:
    current_step: Optional[int]
    allowed_tools: Set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.allowed_tools = self.allowed_tools_for(self.current_step)

    @staticmethod
    def allowed_tools_for(step: Optional[int]) -> Set[str]:
        if step is None:
            return set().union(*ENGINE_TOOL_ALLOWLIST.values()) if ENGINE_TOOL_ALLOWLIST else set()
        return set(ENGINE_TOOL_ALLOWLIST.get(str(step), set()))

    def ensure_allowed(self, tool_name: str) -> None:
        if tool_name in CLIENT_STOP_AT_TOOLS:
            # Client tools are surfaced via StopAtTools; they are not executed automatically.
            return
        if tool_name not in self.allowed_tools:
            raise ToolExecutionError(tool_name, self.current_step)


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return True


def _validate_json_schema(schema: Dict[str, Any], value: Any, path: str = "root") -> List[str]:
    errors: List[str] = []
    expected_type = schema.get("type")

    def _validate(value: Any, schema: Dict[str, Any], current_path: str) -> None:
        expected = schema.get("type")
        if isinstance(expected, list):
            if value is None and "null" in expected:
                return
            if not any(_type_matches(value, candidate) for candidate in expected if candidate != "null"):
                errors.append(f"{current_path}: expected one of {expected}, received {type(value).__name__}")
                return
            # Determine dominant type for recursive validation
            for candidate in expected:
                if candidate == "null":
                    continue
                if _type_matches(value, candidate):
                    candidate_schema = dict(schema)
                    candidate_schema["type"] = candidate
                    _validate(value, candidate_schema, current_path)
                    return
            return

        if expected == "object":
            if not isinstance(value, dict):
                errors.append(f"{current_path}: expected object, received {type(value).__name__}")
                return
            required = schema.get("required", [])
            for field in required:
                if field not in value:
                    errors.append(f"{current_path}.{field}: missing required property")
            properties = schema.get("properties", {})
            for key, val in value.items():
                next_path = f"{current_path}.{key}"
                if key in properties:
                    _validate(val, properties[key], next_path)
                elif schema.get("additionalProperties", True) is False:
                    errors.append(f"{next_path}: additional property not allowed")
            return

        if expected == "array":
            if not isinstance(value, list):
                errors.append(f"{current_path}: expected array, received {type(value).__name__}")
                return
            item_schema = schema.get("items")
            if item_schema:
                for idx, item in enumerate(value):
                    _validate(item, item_schema, f"{current_path}[{idx}]")
            return

        if expected == "integer":
            if not _type_matches(value, "integer"):
                errors.append(f"{current_path}: expected integer, received {type(value).__name__}")
                return
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"{current_path}: value {value} < minimum {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"{current_path}: value {value} > maximum {maximum}")
            return

        if expected == "number":
            if not _type_matches(value, "number"):
                errors.append(f"{current_path}: expected number, received {type(value).__name__}")
                return
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"{current_path}: value {value} < minimum {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"{current_path}: value {value} > maximum {maximum}")
            return

        if expected == "string":
            if not isinstance(value, str):
                errors.append(f"{current_path}: expected string, received {type(value).__name__}")
                return
            enum = schema.get("enum")
            if enum and value not in enum:
                errors.append(f"{current_path}: expected one of {enum}, received {value!r}")
            pattern = schema.get("pattern")
            if pattern:
                import re

                if re.fullmatch(pattern, value) is None:
                    errors.append(f"{current_path}: value {value!r} does not match pattern {pattern!r}")
            return

        if expected == "boolean":
            if not isinstance(value, bool):
                errors.append(f"{current_path}: expected boolean, received {type(value).__name__}")
            return

        if expected == "null":
            if value is not None:
                errors.append(f"{current_path}: expected null, received {type(value).__name__}")
            return

        # Unknown type is treated as pass-through

    _validate(value, schema, path)
    return errors


def _validate_tool_schema(tool_name: str, payload: Optional[Dict[str, Any]], step: Optional[int]) -> None:
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return
    arguments = payload or {}
    if not isinstance(arguments, dict):
        raise ToolExecutionError(
            tool_name,
            step,
            reason="schema_validation_failed",
            extra={"errors": ["root: expected object arguments"]},
        )
    errors = _validate_json_schema(schema, arguments)
    if errors:
        raise ToolExecutionError(
            tool_name,
            step,
            reason="schema_validation_failed",
            extra={"errors": errors},
        )


@dataclass
class StepAwareAgent:
    thread_id: str
    state: Dict[str, Any]
    policy: StepToolPolicy


def build_agent(state: Dict[str, Any]) -> StepAwareAgent:
    current_step = state.get("current_step")
    policy = StepToolPolicy(current_step)
    return StepAwareAgent(
        thread_id=state.get("thread_id") or "unknown-thread",
        state=state,
        policy=policy,
    )


def execute_tool_call(
    tool_name: str,
    tool_call_id: str,
    arguments: Optional[Dict[str, Any]],
    state: Dict[str, Any],
    db: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validate and execute a server-side tool call in a deterministic manner.

    The call enforces the per-step allowlist, validates arguments against the
    declared JSON schema, hydrates the corresponding Pydantic input model, and
    finally invokes the underlying tool implementation. Results are wrapped in a
    structure compatible with Agents SDK expectations, echoing tool_call_id.
    """

    policy = StepToolPolicy(state.get("current_step"))
    policy.ensure_allowed(tool_name)
    _validate_tool_schema(tool_name, arguments, policy.current_step)

    definition = TOOL_DEFINITIONS.get(tool_name)
    if not definition:
        raise ToolExecutionError(
            tool_name,
            policy.current_step,
            reason="tool_not_supported",
        )

    payload = arguments or {}
    try:
        params = definition.input_model(**payload) if payload or definition.input_model is not None else None
    except ValidationError as exc:
        raise ToolExecutionError(
            tool_name,
            policy.current_step,
            reason="schema_validation_failed",
            extra={"errors": exc.errors()},
        )

    result: Any
    if definition.requires_db:
        if db is None:
            raise ToolExecutionError(
                tool_name,
                policy.current_step,
                reason="db_required",
            )
        if definition.use_event_entry:
            event_entry_data = getattr(params, "event_entry", None)
            if event_entry_data is None:
                raise ToolExecutionError(
                    tool_name,
                    policy.current_step,
                    reason="schema_validation_failed",
                    extra={"errors": ["event_entry missing"]},
                )
            result = definition.handler(db, event_entry_data, params)
        else:
            result = definition.handler(db, params)
    else:
        if definition.use_event_entry:
            event_entry_data = getattr(params, "event_entry", None)
            if event_entry_data is None:
                raise ToolExecutionError(
                    tool_name,
                    policy.current_step,
                    reason="schema_validation_failed",
                    extra={"errors": ["event_entry missing"]},
                )
            result = definition.handler(event_entry_data, params)
        else:
            result = definition.handler(params)

    if hasattr(result, "dict"):
        content = result.dict()
    elif isinstance(result, dict):
        content = result
    else:
        content = {"value": result}

    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "content": content,
    }


def load_default_db_for_tools() -> Dict[str, Any]:
    """
    Helper to load the workflow DB for agent tool execution. Tools are
    deterministic and should share the same backing store as the workflow.

    Returns:
        Database dict. If loading fails, returns a dict with an error flag
        so tools can report the issue instead of pretending there's no data.
    """
    from backend.workflow_email import get_default_db  # pylint: disable=import-outside-toplevel

    try:
        return get_default_db()
    except Exception as exc:
        # Return a db with error flag so tools can surface the issue
        from backend.utils.fallback import create_fallback_context
        ctx = create_fallback_context(
            source="agents.chatkit_runner.load_db",
            trigger="db_load_failed",
            error=exc,
        )
        print(f"[FALLBACK] {ctx.source} | {ctx.trigger} | {exc}")
        return {
            "events": [],
            "tasks": [],
            "_db_error": "Cannot reach the booking database. Please retry or contact support.",
        }


async def _fallback_stream(
    thread_id: str,
    message: Dict[str, Any],
    state: Dict[str, Any],
    *,
    fallback_reason: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Deterministic fallback path when the Agents SDK is unavailable.

    We reuse the existing OpenEventAgent facade so behaviour mirrors the
    traditional workflow-backed path. The output is wrapped in SSE format.

    Args:
        thread_id: The conversation thread ID
        message: The user message
        state: Current conversation state
        fallback_reason: If set, emit a diagnostic message before the response
    """
    # Emit diagnostic message if we're falling back due to an error
    if fallback_reason:
        diagnostic = {
            "type": "system_notice",
            "message": f"[Streaming mode unavailable: {fallback_reason}] Switching to workflow mode.",
        }
        yield f"data: {json.dumps(diagnostic)}\n\n"
        from backend.utils.fallback import create_fallback_context
        ctx = create_fallback_context(
            source="agents.chatkit_runner.stream",
            trigger="sdk_unavailable",
            thread_id=thread_id,
            error=Exception(fallback_reason),
        )
        print(f"[FALLBACK] {ctx.source} | {ctx.trigger} | {fallback_reason}")

    agent = OpenEventAgent()
    session = agent.create_session(thread_id)
    envelope = agent.run(session, message)
    payload = safe_envelope(envelope)
    yield f"data: {json.dumps(payload)}\n\n"


async def run_streamed(thread_id: str, message: Dict[str, Any], state: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    Stream the assistant response for ChatKit.

    When the Agents SDK or network access is not available the function falls
    back to the deterministic workflow pipeline so tests can run offline.
    """

    policy = StepToolPolicy(state.get("current_step"))
    agent_mode = os.getenv("AGENT_MODE", "workflow").lower()

    if agent_mode != "openai":
        async for chunk in _fallback_stream(thread_id, message, state):
            yield chunk
        return

    try:  # pragma: no cover - SDK path exercised only in integration runs
        from openai import OpenAI  # type: ignore

        api_key = load_openai_api_key(required=False)
        if not api_key:
            raise RuntimeError(f"Environment variable '{SECRET_NAME}' is required for streamed agent mode.")

        client = OpenAI(api_key=api_key)
        allowed_tools = [{"type": "function", "function": {"name": tool}} for tool in policy.allowed_tools]
        stop_tools = [{"type": "function", "function": {"name": tool}} for tool in CLIENT_STOP_AT_TOOLS]
        venue_name = get_venue_name()
        system_instructions = (
            f"You are OpenEvent's professional event manager for {venue_name}. Follow Workflow v3 strictly.\n"
            f"Current step: {state.get('current_step') or 'unknown'}; "
            f"Status: {state.get('status') or 'Lead'}.\n"
            "Communicate concisely and professionally. No marketing fluff.\n"
            "Only invoke engine tools that appear in the provided allowlist. "
            "Client tools (confirm/change/discard offer, see catering/products) must use StopAtTools."
        )

        response = client.responses.stream.create(  # type: ignore[attr-defined]
            model=os.getenv("OPENAI_AGENT_MODEL", "gpt-4.1-mini"),
            input=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": message["body"]},
            ],
            tools=allowed_tools + stop_tools,
            tool_choice={"type": "required"},
        )

        async for event in response:
            if event.type == "response.error":
                raise RuntimeError(event.error)  # type: ignore[attr-defined]
            if event.type != "response.output_text.delta":  # type: ignore[attr-defined]
                continue
            text = event.delta  # type: ignore[attr-defined]
            yield f"data: {json.dumps({'delta': text})}\n\n"

        final = response.get_final_response()
        yield f"data: {json.dumps({'assistant_text': final.output_text})}\n\n"
    except Exception as exc:
        logger.warning("Agents SDK unavailable or failed (%s); using fallback workflow path.", exc)
        # Pass fallback reason so UI knows streaming failed
        fallback_reason = str(exc)[:100]  # Truncate long errors
        async for chunk in _fallback_stream(thread_id, message, state, fallback_reason=fallback_reason):
            yield chunk


def validate_tool_call(tool_name: str, state: Dict[str, Any], arguments: Optional[Dict[str, Any]] = None) -> None:
    """
    Helper exposed for tests so we can assert allowlist enforcement without
    needing to exercise the Agents SDK.
    """

    policy = StepToolPolicy(state.get("current_step"))
    policy.ensure_allowed(tool_name)
    _validate_tool_schema(tool_name, arguments, policy.current_step)
