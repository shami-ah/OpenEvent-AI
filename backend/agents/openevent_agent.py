from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backend.workflow_email import process_msg as workflow_process_msg
from backend.agents.guardrails import safe_envelope
from backend.workflows.common.prompts import FOOTER_SEPARATOR
from backend.utils.openai_key import load_openai_api_key

logger = logging.getLogger(__name__)


class OpenEventAgent:
    """
    Facade that prefers the OpenAI Agents SDK when available, falling back to
    the deterministic workflow router when the SDK or network access is not
    present.  This keeps the codebase ready for agent orchestration without
    breaking the existing deterministic behaviour relied upon by tests.
    """

    _SYSTEM_PROMPT = (
        "You are OpenEvent's professional event manager for The Atelier. "
        "Follow Workflow v3 strictly: Step 2 (date) → Step 3 (room) → Step 4 "
        "(offer) → Step 5 (negotiation) → Step 6 (transition) → Step 7 "
        "(confirmation), honouring detours via caller_step and hash checks. "
        "Style: Be professional, concise, and direct. No fluff or over-enthusiasm. "
        "Always reply with JSON in the schema {assistant_text, requires_hil, "
        "action, payload}. Preserve provided facts verbatim (menus, dates, "
        "prices). Never mutate the database directly—call the provided tools."
    )

    def __init__(self) -> None:
        self._sdk_available = False
        self._chat_supported = False
        self._client = None
        self._agent_id: Optional[str] = None
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._tool_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._initialise_sdk()

    def _initialise_sdk(self) -> None:
        try:  # pragma: no cover - optional dependency probe
            from openai import OpenAI  # type: ignore

            api_key = load_openai_api_key(required=False)
            if not api_key:
                self._client = None
                self._sdk_available = False
                self._chat_supported = False
                logger.info("OpenAI API key missing; using workflow fallback.")
                return

            self._client = OpenAI(api_key=api_key)
            self._sdk_available = hasattr(self._client, "agents")
            self._chat_supported = hasattr(self._client, "chat")
            if self._sdk_available:
                logger.info("OpenAI Agents SDK detected. Agent orchestration enabled.")
            elif self._chat_supported:
                logger.info("OpenAI chat completions detected; using lightweight agent runner.")
            else:
                logger.info("OpenAI client present but no agents/chat support; using workflow fallback.")
        except Exception as exc:  # pragma: no cover - optional dependency probe
            self._client = None
            self._sdk_available = False
            self._chat_supported = False
            logger.info("Agents SDK unavailable (%s); using workflow fallback.", exc)

    def _ensure_agent(self) -> Optional[str]:
        if not self._sdk_available or not self._client:
            return None
        if self._agent_id:
            return self._agent_id
        try:
            response = self._client.agents.create(  # type: ignore[attr-defined]
                model="gpt-4.1-mini",
                instructions=self._SYSTEM_PROMPT,
                tools=[
                    {"type": "function", "function": {"name": "tool_suggest_dates"}},
                    {"type": "function", "function": {"name": "tool_persist_confirmed_date"}},
                    {"type": "function", "function": {"name": "tool_evaluate_rooms"}},
                    {"type": "function", "function": {"name": "tool_room_status"}},
                    {"type": "function", "function": {"name": "tool_compose_offer"}},
                    {"type": "function", "function": {"name": "tool_persist_offer"}},
                    {"type": "function", "function": {"name": "tool_send_offer"}},
                    {"type": "function", "function": {"name": "tool_negotiate_offer"}},
                    {"type": "function", "function": {"name": "tool_transition_sync"}},
                    {"type": "function", "function": {"name": "tool_classify_confirmation"}},
                ],
            )
            self._agent_id = response.id  # type: ignore[attr-defined]
            return self._agent_id
        except Exception as exc:  # pragma: no cover - network guarded
            logger.warning("Failed to create Agents SDK agent: %s", exc)
            self._agent_id = None
            self._sdk_available = False
            return None

    def _ensure_session(self, thread_id: str) -> Dict[str, Any]:
        session = self._sessions.get(thread_id)
        if session:
            return session
        session = {
            "thread_id": thread_id,
            "state": {
                "event_id": None,
                "current_step": None,
                "caller_step": None,
                "requirements_hash": None,
                "room_eval_hash": None,
                "offer_hash": None,
                "status": None,
            },
        }
        self._sessions[thread_id] = session
        return session

    def create_session(self, thread_id: str) -> Dict[str, Any]:
        """Public helper for API endpoints to initialise a session."""

        return self._ensure_session(thread_id)

    def execute_tool(
        self,
        session: Dict[str, Any],
        *,
        tool_name: str,
        tool_call_id: str,
        arguments: Optional[Dict[str, Any]] = None,
        db: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a tool deterministically with idempotent caching."""

        thread_id = session.get("thread_id") or "unknown-thread"
        cache = self._tool_cache.setdefault(thread_id, {})
        if tool_call_id in cache:
            cached = cache[tool_call_id]
            return dict(cached)

        # Import locally to avoid circular import during module initialisation.
        from backend.agents import chatkit_runner as _runner  # pylint: disable=import-outside-toplevel

        state_snapshot = session.get("state", {}) or {}
        result = _runner.execute_tool_call(tool_name, tool_call_id, arguments, state_snapshot, db)
        message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": json.dumps(result.get("content", {}), ensure_ascii=False),
        }
        cache[tool_call_id] = message
        self._persist_thread_delta(session, result.get("content"))
        return dict(message)

    def run(self, session: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a turn via the Agents SDK when possible, otherwise fall back to
        the deterministic workflow router.
        """

        if self._sdk_available and self._ensure_agent():
            try:
                return self._run_via_agent(session, message)
            except Exception as exc:  # pragma: no cover - network guarded
                logger.warning("Agents SDK execution failed (%s); falling back.", exc)
        elif self._chat_supported and self._client:
            try:
                return self._run_via_chat(session, message)
            except Exception as exc:
                logger.warning("Chat-based agent execution failed (%s); falling back.", exc)

        return self._run_fallback(message)

    def _run_via_agent(self, session: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
        assert self._client is not None  # for type checkers
        agent_id = self._ensure_agent()
        if not agent_id:
            raise RuntimeError("Agent ID unavailable after initialisation.")

        thread_id = session["thread_id"]
        try:
            run = self._client.agents.runs.create(  # type: ignore[attr-defined]
                agent_id=agent_id,
                thread_id=thread_id,
                input=message["body"],
                session_state=session.get("state", {}),
            )
            envelope = run.output[0].content  # type: ignore[attr-defined]
            validated = safe_envelope(envelope if isinstance(envelope, dict) else {})
            session["state"] = run.session_state  # type: ignore[attr-defined]
            return validated
        except Exception as exc:  # pragma: no cover - network guarded
            raise RuntimeError(f"Agents SDK run failed: {exc}") from exc

    def _run_via_chat(self, session: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lightweight agent runner using chat completions when the Agents SDK
        surface is unavailable in the installed OpenAI version.
        """
        assert self._client is not None

        # Always rehydrate from DB to ensure state is current for this turn.
        self._hydrate_session_from_db(session)
        state = session.get("state") or {}

        # If no event/workflow state exists after hydration, use the deterministic
        # workflow to seed the event and get a first-turn response.
        if not state.get("current_step"):
            seeded = self._run_fallback(message)
            self._hydrate_session_from_payload(session, seeded.get("payload", {}))
            return seeded

        from backend.agents import chatkit_runner as _runner  # pylint: disable=import-outside-toplevel

        history: List[Dict[str, Any]] = session.get("history", []) or []
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": message.get("body", "")},
        ]

        response = self._client.chat.completions.create(  # type: ignore[attr-defined]
            model="gpt-4.1-mini",
            messages=messages,
            temperature=0.2,
            tools=_runner.OPENAI_TOOLS_SCHEMA,
        )

        choice = response.choices[0].message  # type: ignore[index]
        tool_calls = choice.tool_calls or []

        # If the LLM requested tools, execute deterministically and return a safe envelope.
        if tool_calls:
            session_state = session.get("state", {}) or {}
            db = _runner.load_default_db_for_tools()
            tool_messages: List[Dict[str, Any]] = []
            for call in tool_calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except Exception:
                    arguments = {}
                try:
                    result = _runner.execute_tool_call(name, call.id, arguments, session_state, db)
                    # Refresh session state from db after a successful tool call.
                    self._hydrate_session_from_db(session)
                except Exception as exc:
                    # Surface a deterministic tool error envelope instead of crashing
                    payload = {
                        "assistant_text": "I hit an issue while running a tool; a manager will review.",
                        "requires_hil": True,
                        "action": "tool_error",
                        "payload": {"tool": name, "reason": str(exc)},
                    }
                    return safe_envelope(payload)
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": name,
                        "content": json.dumps(result.get("content", {}), ensure_ascii=False),
                    }
                )
                # Persist state delta if present
                self._persist_thread_delta(session, result.get("content"))

            # Mirror tool results back to the client in a deterministic envelope.
            payload = {
                "assistant_text": "Processed tool calls.",
                "requires_hil": True,
                "action": "tool_calls_executed",
                "payload": {"tool_messages": tool_messages},
            }
            # Persist minimal history for follow-up turns.
            session["history"] = [
                *history[-4:],
                {"role": "user", "content": message.get("body", "")},
            ]
            return safe_envelope(payload)

        # No tool calls: attempt JSON parse, else wrap raw text.
        content = choice.content
        if isinstance(content, list):
            content_text = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        else:
            content_text = str(content or "")

        try:
            parsed = json.loads(content_text)
        except Exception:
            parsed = {
                "assistant_text": content_text or "Thanks, I’ll check that now.",
                "requires_hil": True,
                "action": "agent_reply",
                "payload": {"raw_message": content_text},
            }

        session["history"] = [
            *history[-4:],  # cap memory growth
            {"role": "user", "content": message.get("body", "")},
            {"role": "assistant", "content": content_text},
        ]

        return safe_envelope(parsed if isinstance(parsed, dict) else {"assistant_text": content_text, "requires_hil": True, "action": "agent_reply", "payload": {}})

    def _hydrate_session_from_payload(self, session: Dict[str, Any], payload: Dict[str, Any]) -> None:
        state = session.setdefault("state", {})
        state.update(
            {
                "event_id": payload.get("event_id") or state.get("event_id"),
                "current_step": payload.get("current_step") or state.get("current_step"),
                "caller_step": payload.get("caller_step") or state.get("caller_step"),
                "requirements_hash": payload.get("requirements_hash") or state.get("requirements_hash"),
                "room_eval_hash": payload.get("room_eval_hash") or state.get("room_eval_hash"),
                "offer_hash": payload.get("offer_hash") or state.get("offer_hash"),
                "status": payload.get("status") or payload.get("thread_state") or state.get("status"),
            }
        )

    def _hydrate_session_from_db(self, session: Dict[str, Any]) -> None:
        try:
            from backend.workflow_email import get_default_db  # pylint: disable=import-outside-toplevel
        except Exception:
            return

        db = get_default_db()
        state = session.setdefault("state", {})
        event_id = state.get("event_id")
        candidate = None
        if event_id:
            for evt in db.get("events", []):
                if evt.get("event_id") == event_id:
                    candidate = evt
                    break
        if not candidate:
            return
        state.update(
            {
                "event_id": candidate.get("event_id"),
                "current_step": candidate.get("current_step"),
                "caller_step": candidate.get("caller_step"),
                "requirements_hash": candidate.get("requirements_hash"),
                "room_eval_hash": candidate.get("room_eval_hash"),
                "offer_hash": candidate.get("offer_hash"),
                "status": candidate.get("status") or candidate.get("thread_state"),
            }
        )

    def _run_fallback(self, message: Dict[str, Any]) -> Dict[str, Any]:
        wf_res = workflow_process_msg(message)
        assistant_text = self._compose_reply(wf_res)
        requires_hil = True
        action = wf_res.get("action") or "workflow_response"
        payload = {k: v for k, v in wf_res.items() if k not in {"draft_messages", "summary"}}
        payload.setdefault("draft_messages", wf_res.get("draft_messages") or [])
        envelope = {
            "assistant_text": assistant_text,
            "requires_hil": requires_hil,
            "action": action,
            "payload": payload,
        }
        return safe_envelope(envelope)

    @staticmethod
    def _compose_reply(workflow_result: Dict[str, Any]) -> str:
        drafts = workflow_result.get("draft_messages") or []
        bodies: List[str] = []
        for draft in drafts:
            chosen_field = (
                "body_markdown"
                if draft.get("body_markdown")
                else "body_md"
                if draft.get("body_md")
                else "body"
                if draft.get("body")
                else "prompt"
                if draft.get("prompt")
                else "" 
            )
            source_value = (
                draft.get("body_markdown")
                or draft.get("body_md")
                or draft.get("body")
                or draft.get("prompt")
                or ""
            )
            print(
                "[WF][DEBUG][EmailCompose] body_chosen=",
                chosen_field or "none",
                "| len=",
                len(source_value),
            )
            body_markdown = draft.get("body_markdown") or draft.get("body_md")
            footer = draft.get("footer") or ""
            body_text = None
            if body_markdown:
                body_text = body_markdown
                if footer:
                    body_text = f"{body_markdown}{FOOTER_SEPARATOR}{footer}".strip()
            if not body_text:
                body_text = draft.get("body") or draft.get("prompt")
                if body_text and footer and footer not in body_text:
                    body_text = f"{body_text}{FOOTER_SEPARATOR}{footer}".strip()
            if body_text:
                bodies.append(str(body_text))
        if bodies:
            return "\n\n".join(bodies)
        if workflow_result.get("summary"):
            return str(workflow_result["summary"])
        if workflow_result.get("reason"):
            return str(workflow_result["reason"])
        return "Thanks for the update — I'll keep you posted."

    def _persist_thread_delta(self, session: Dict[str, Any], content: Any) -> None:
        if not isinstance(content, dict):
            return
        state = session.setdefault("state", {})
        for key in ("caller_step", "requirements_hash", "room_eval_hash"):
            if key in content and content[key] is not None:
                state[key] = content[key]
