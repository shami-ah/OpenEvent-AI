from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
import logging

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.datetime_parse import build_window_iso
import importlib
from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
from backend.config.flags import env_flag

date_process_module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.process")
ConfirmationWindow = getattr(date_process_module, "ConfirmationWindow")
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.services.products import normalise_product_payload

logger = logging.getLogger(__name__)

# Feature flags ----------------------------------------------------------------


def _env_flag(name: str, default: str = "false") -> str:
    return os.environ.get(name, default)


def _flag_enabled() -> bool:
    return env_flag("SMART_SHORTCUTS", False)


def _max_combined() -> int:
    value = _env_flag("SMART_SHORTCUTS_MAX_COMBINED", os.environ.get("MAX_COMBINED", "3"))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


def _legacy_shortcuts_allowed() -> bool:
    return env_flag("LEGACY_SHORTCUTS_ALLOWED", False)


def _needs_input_priority() -> List[str]:
    default = ["time", "availability", "site_visit", "offer_hil", "budget", "billing"]
    raw = os.environ.get("SMART_SHORTCUTS_NEEDS_INPUT")
    if not raw:
        return default
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or default


def _product_flow_enabled() -> bool:
    return env_flag("PRODUCT_FLOW_ENABLED", False)


def _capture_budget_on_hil() -> bool:
    return env_flag("CAPTURE_BUDGET_ON_HIL", False)


def _no_unsolicited_menus() -> bool:
    return env_flag("NO_UNSOLICITED_MENUS", False)


def _event_scoped_upsell_enabled() -> bool:
    return env_flag("EVENT_SCOPED_UPSELL", False)


def _budget_default_currency() -> str:
    return os.environ.get("BUDGET_DEFAULT_CURRENCY", "CHF")


def _budget_parse_strict() -> bool:
    return env_flag("BUDGET_PARSE_STRICT", False)


def _max_missing_items_per_hil() -> int:
    try:
        return max(1, int(os.environ.get("MAX_MISSING_ITEMS_PER_HIL", "10") or 10))
    except (TypeError, ValueError):
        return 10


_PREASK_CLASS_COPY = {
    "catering": "Would you like to see catering options we can provide on-site?",
    "av": "Would you like to see AV add-ons (e.g., extra mics, adapters)?",
    "furniture": "Would you like to see furniture layouts or add-ons?",
}

_CLASS_KEYWORDS = {
    "catering": {"catering", "food", "menu", "buffet", "lunch", "coffee"},
    "av": {"av", "audio", "visual", "video", "projector", "sound", "microphone"},
    "furniture": {"furniture", "chairs", "tables", "layout", "seating"},
}

_ORDINAL_WORDS_BY_LANG = {
    "en": {
        "first": 1,
        "1st": 1,
        "one": 1,
        "second": 2,
        "2nd": 2,
        "two": 2,
        "third": 3,
        "3rd": 3,
        "three": 3,
        "fourth": 4,
        "4th": 4,
        "four": 4,
        "fifth": 5,
        "5th": 5,
        "five": 5,
    },
    "de": {
        "erste": 1,
        "zuerst": 1,
        "zweite": 2,
        "zweiter": 2,
        "dritte": 3,
        "dritter": 3,
        "vierte": 4,
        "vierter": 4,
        "fuenfte": 5,
    },
}



# Intent structures ------------------------------------------------------------


@dataclass
class ParsedIntent:
    type: str
    data: Dict[str, Any]
    verifiable: bool
    reason: Optional[str] = None


@dataclass
class PlannerTelemetry:
    executed_intents: List[str] = field(default_factory=list)
    combined_confirmation: bool = False
    needs_input_next: Optional[str] = None
    deferred: List[Dict[str, Any]] = field(default_factory=list)
    artifact_match: Optional[str] = None
    added_items: List[Dict[str, Any]] = field(default_factory=list)
    missing_items: List[Dict[str, Any]] = field(default_factory=list)
    offered_hil: bool = False
    hil_request_created: bool = False
    budget_provided: bool = False
    upsell_shown: bool = False
    room_checked: bool = False
    menus_included: str = "false"
    menus_phase: str = "none"
    product_prices_included: bool = False
    product_price_missing: bool = False
    gatekeeper_passed: Optional[bool] = None
    answered_question_first: Optional[bool] = None
    delta_availability_used: Optional[bool] = None
    preask_candidates: List[str] = field(default_factory=list)
    preask_shown: List[str] = field(default_factory=list)
    preask_response: Dict[str, str] = field(default_factory=dict)
    preview_class_shown: str = "none"
    preview_items_count: int = 0
    choice_context_active: bool = False
    selection_method: str = "none"
    re_prompt_reason: str = "none"
    legacy_shortcut_invocations: int = 0
    shortcut_path_used: str = "none"

    def to_log(self, msg_id: Optional[str], event_id: Optional[str]) -> Dict[str, Any]:
        return {
            "executed_intents": list(self.executed_intents),
            "combined_confirmation": bool(self.combined_confirmation),
            "needs_input_next": self.needs_input_next,
            "deferred_count": len(self.deferred),
            "source_msg_id": msg_id,
            "event_id": event_id,
            "artifact_match": self.artifact_match,
            "added_items": self.added_items,
            "missing_items": self.missing_items,
            "offered_hil": self.offered_hil,
            "hil_request_created": self.hil_request_created,
            "budget_provided": self.budget_provided,
            "upsell_shown": self.upsell_shown,
            "room_checked": self.room_checked,
            "menus_included": self.menus_included,
            "menus_phase": self.menus_phase,
            "product_prices_included": self.product_prices_included,
            "product_price_missing": self.product_price_missing,
            "gatekeeper_passed": self.gatekeeper_passed,
            "answered_question_first": self.answered_question_first,
            "delta_availability_used": self.delta_availability_used,
            "legacy_shortcut_invocations": self.legacy_shortcut_invocations,
            "shortcut_path_used": self.shortcut_path_used,
        }


@dataclass
class AtomicDecision:
    execute: List[ParsedIntent]
    deferred: List[Tuple[ParsedIntent, str]]
    use_combo: bool = False
    shortcut_path_used: str = "none"


class AtomicTurnPolicy:
    def __init__(self) -> None:
        self.atomic_turns = env_flag("ATOMIC_TURNS", False)
        self.allow_date_room = env_flag("SHORTCUT_ALLOW_DATE_ROOM", True)

    def decide(self, planner: "_ShortcutPlanner") -> AtomicDecision:
        if not self.atomic_turns:
            return AtomicDecision(execute=list(planner.verifiable), deferred=[])

        verifiable = list(planner.verifiable)
        decision = AtomicDecision(execute=[], deferred=[], use_combo=False, shortcut_path_used="none")

        date_intent = next((intent for intent in verifiable if intent.type == "date_confirmation"), None)
        room_intent = next((intent for intent in verifiable if intent.type == "room_selection"), None)

        if (
            self.allow_date_room
            and date_intent
            and room_intent
            and planner._should_execute_date_room_combo()
        ):
            decision.execute = [date_intent, room_intent]
            decision.use_combo = True
            decision.shortcut_path_used = "date+room"
            for intent in verifiable:
                if intent not in decision.execute:
                    decision.deferred.append((intent, "combined_limit_reached"))
            return decision

        if verifiable:
            primary = verifiable[0]
            decision.execute = [primary]
            for intent in verifiable[1:]:
                decision.deferred.append((intent, "combined_limit_reached"))

        return decision


class PlannerResult(dict):
    """Dictionary-like payload returned by the shortcut planner with a stable accessor."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__(payload)

    def merged(self) -> Dict[str, Any]:
        """Return a shallow copy of the planner payload for external consumers."""

        payload = dict(self)
        payload.setdefault("message", "")
        payload.setdefault("telemetry", {})
        payload.setdefault("state_delta", {})
        return payload


# Planner execution ------------------------------------------------------------


def maybe_run_smart_shortcuts(state: WorkflowState) -> Optional[GroupResult]:
    policy = AtomicTurnPolicy()
    if policy.atomic_turns:
        state.telemetry.atomic_default = True
    if not _flag_enabled():
        return None
    event_entry = state.event_entry
    if not event_entry:
        return None
    if not _shortcuts_allowed(event_entry):
        _debug_shortcut_gate("blocked", event_entry, state.user_info)
        return None
    _debug_shortcut_gate("allowed", event_entry, state.user_info)

    planner = _ShortcutPlanner(state, policy)
    result = planner.handle_lightweight_turn()
    if result is None:
        result = planner.run()
    if not result:
        return None

    # Replace draft messages with the planner-composed reply.
    state.draft_messages.clear()
    state.draft_messages.append(
        {
            "body": result["message"],
            "step": event_entry.get("current_step") or state.current_step or 2,
            "topic": "smart_shortcut_combined_confirmation",
            "requires_approval": True,
        }
    )
    state.extras["persist"] = True
    state.extras["subloop"] = "shortcut"
    return GroupResult(action="smart_shortcut_processed", payload=result.merged())


def _shortcuts_allowed(event_entry: Dict[str, Any]) -> bool:
    """Gate smart shortcuts on confirmed date + capacity readiness."""

    current_step = event_entry.get("current_step") or 0
    if current_step and isinstance(current_step, str):
        try:
            current_step = int(current_step)
        except ValueError:
            current_step = 0
    if current_step < 3:
        return False

    # [BILLING FLOW BYPASS] Don't intercept messages during billing capture flow
    # When offer is accepted and we're awaiting billing, let step 5 handle the message
    if event_entry.get("offer_accepted"):
        billing_req = event_entry.get("billing_requirements") or {}
        if billing_req.get("awaiting_billing_for_accept"):
            return False

    if event_entry.get("date_confirmed") is not True:
        return False

    if _coerce_participants(event_entry) is not None:
        return True

    shortcuts = event_entry.get("shortcuts") or {}
    return bool(shortcuts.get("capacity_ok"))


def _coerce_participants(event_entry: Dict[str, Any]) -> Optional[int]:
    requirements = event_entry.get("requirements") or {}
    raw = requirements.get("number_of_participants")
    if raw in (None, "", "Not specified", "none"):
        raw = requirements.get("participants")
    if raw in (None, "", "Not specified", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None


def _debug_shortcut_gate(state: str, event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> None:
    if os.getenv("WF_DEBUG_STATE") != "1":
        return
    info = {
        "state": state,
        "step": event_entry.get("current_step"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "participants": (event_entry.get("requirements") or {}).get("number_of_participants"),
        "capacity_shortcut": (event_entry.get("shortcuts") or {}).get("capacity_ok"),
        "wish_products": (event_entry.get("wish_products") or []),
        "user_shortcut": (user_info or {}).get("shortcut_capacity_ok"),
    }
    formatted = " ".join(f"{key}={value}" for key, value in info.items())
    print(f"[WF DEBUG][shortcuts] {formatted}")


class _ShortcutPlanner:
    def __init__(self, state: WorkflowState, policy: Optional[AtomicTurnPolicy] = None):
        self.state = state
        self.event = state.event_entry or {}
        self.user_info = state.user_info or {}
        self.verifiable: List[ParsedIntent] = []
        self.needs_input: List[ParsedIntent] = []
        self.telemetry = PlannerTelemetry()
        self.summary_lines: List[str] = []
        self.pending_items: List[Dict[str, Any]] = []
        self.initial_snapshot = self._snapshot_event()
        self.policy = policy or AtomicTurnPolicy()
        self.legacy_allowed = _legacy_shortcuts_allowed()
        self.max_combined = _max_combined() if self.legacy_allowed else 1
        self.telemetry.shortcut_path_used = "none"
        self.telemetry.legacy_shortcut_invocations = 0
        if self.policy.atomic_turns:
            self.telemetry.atomic_default = True
        self.priority_order = _needs_input_priority()
        seen: set[str] = set()
        ordered: List[str] = []
        for item in self.priority_order + ["date_choice"]:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        self.priority_order = ordered
        if "budget" not in self.priority_order:
            self.priority_order.append("budget")
        if "offer_hil" not in self.priority_order:
            insert_pos = self.priority_order.index("budget") if "budget" in self.priority_order else len(self.priority_order)
            self.priority_order.insert(insert_pos, "offer_hil")
        if "product_followup" not in self.priority_order:
            self.priority_order.append("product_followup")
        self.pending_product_additions: List[Dict[str, Any]] = []
        self.pending_missing_products: List[Dict[str, Any]] = []
        self.menu_requested = self._explicit_menu_requested()
        self.room_checked_initial = bool(self.event.get("locked_room_id"))
        self.room_checked = self.room_checked_initial
        self.product_line_details: List[Dict[str, Any]] = []
        self.product_currency_totals: Dict[str, float] = {}
        self.product_price_missing = False
        self.budget_info = self._extract_budget_info()
        if self.budget_info:
            self.telemetry.budget_provided = True
        self.telemetry.menus_included = "false"
        self.telemetry.menus_phase = "none"
        self.telemetry.dag_blocked = "none"
        self.state.telemetry.dag_blocked = "none"
        self.telemetry.room_checked = self.room_checked
        self.products_state = self._products_state()
        self.preask_pending_state: Dict[str, bool] = dict(self.products_state.get("preask_pending") or {})
        self.presented_interest: Dict[str, str] = self.products_state.setdefault("presented_interest", {})
        self.manager_items_by_class = self._group_manager_items()
        self._sync_manager_catalog_signature()
        self.preview_requests: List[Tuple[str, int]] = []
        self.preask_clarifications: List[str] = []
        self.choice_context = self._load_choice_context()
        self.preview_lines: List[str] = []
        self.preview_class: Optional[str] = None
        self._choice_context_handled = False
        self._parsed = False
        self.preask_ack_lines: List[str] = []
        self._dag_block_reason: str = "none"

    def _greeting_line(self) -> str:
        profile = (self.state.client or {}).get("profile", {}) if self.state.client else {}
        raw_name = profile.get("name") or self.state.message.from_name
        if raw_name:
            token = str(raw_name).strip().split()
            if token:
                first = token[0].strip(",. ")
                if first:
                    return f"Hello {first},"
        return "Hello,"

    def _with_greeting(self, body: str) -> str:
        greeting = self._greeting_line()
        if not body:
            return greeting
        if body.startswith(greeting):
            return body
        return f"{greeting}\n\n{body}"

    def handle_lightweight_turn(self) -> Optional[PlannerResult]:
        choice_context_result = self._maybe_handle_choice_context_reply()
        if choice_context_result:
            return choice_context_result

        self._ensure_intents_prepared()

        if not self.verifiable and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                self.telemetry.answered_question_first = True
                return self._build_payload("\u200b")

        if self.preask_ack_lines and not self.verifiable and not self.needs_input:
            ack_message = "\n".join(self.preask_ack_lines).strip()
            self.preask_ack_lines.clear()
            self.telemetry.answered_question_first = True
            return self._build_payload(ack_message or "\u200b")

        date_answer = self._maybe_emit_date_options_answer()
        if date_answer:
            return date_answer

        if not self.verifiable and len(self.needs_input) == 1:
            follow_up = self._maybe_emit_single_followup()
            if follow_up:
                return follow_up

        return None

    def run(self) -> Optional[PlannerResult]:
        if not self._choice_context_handled:
            choice_context_result = self._maybe_handle_choice_context_reply()
            if choice_context_result:
                return choice_context_result

        self._ensure_intents_prepared()

        if not self.verifiable and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                return self._build_payload("\u200b")

        executed_count = 0
        combine_executed = False

        date_answer = self._maybe_emit_date_options_answer()
        if date_answer:
            return date_answer

        if self.policy.atomic_turns:
            decision = self.policy.decide(self)
            self.telemetry.shortcut_path_used = decision.shortcut_path_used
            if decision.use_combo:
                combine_executed = self._execute_date_room_combo()
                if combine_executed:
                    executed_count = 2
                else:
                    decision.use_combo = False
                    self.telemetry.shortcut_path_used = "none"
            if not decision.use_combo:
                for intent in decision.execute:
                    allowed, guard_reason = self._dag_guard(intent)
                    if not allowed:
                        self._set_dag_block(guard_reason)
                        self._ensure_prerequisite_prompt(guard_reason, intent)
                        self._defer_intent(intent, guard_reason or "dag_blocked")
                        continue
                    if self._execute_intent(intent):
                        executed_count += 1
                    else:
                        self._defer_intent(intent, "not_executable_now")
            for intent, reason in decision.deferred:
                allowed, guard_reason = self._dag_guard(intent)
                final_reason = guard_reason or reason or "not_executable_now"
                if guard_reason:
                    self._set_dag_block(guard_reason)
                    self._ensure_prerequisite_prompt(guard_reason, intent)
                self._defer_intent(intent, final_reason)
            self.telemetry.legacy_shortcut_invocations = 1 if decision.use_combo else 0
        else:
            if not self.legacy_allowed and self._should_execute_date_room_combo():
                combine_executed = self._execute_date_room_combo()
                if combine_executed:
                    executed_count = 2
                    remaining = [i for i in self.verifiable if i.type not in {"date_confirmation", "room_selection"}]
                    for intent in remaining:
                        self._defer_intent(intent, "combined_limit_reached")
                    self.verifiable = []
                    self.telemetry.shortcut_path_used = "date+room"
                    self.telemetry.legacy_shortcut_invocations = max(0, executed_count - 1)
            if not combine_executed and self.verifiable:
                combined_limit = max(1, min(self.max_combined, len(self.verifiable)))
                for intent in self.verifiable:
                    allowed, guard_reason = self._dag_guard(intent)
                    if not allowed:
                        self._set_dag_block(guard_reason)
                        self._ensure_prerequisite_prompt(guard_reason, intent)
                        self._defer_intent(intent, guard_reason or "dag_blocked")
                        continue
                    if executed_count >= combined_limit:
                        self._defer_intent(intent, "combined_limit_reached")
                        continue
                    handled = self._execute_intent(intent)
                    if handled:
                        executed_count += 1
                    else:
                        self._defer_intent(intent, "not_executable_now")
            if not combine_executed:
                if "date_confirmation" in self.telemetry.executed_intents and "room_selection" in self.telemetry.executed_intents:
                    self.telemetry.shortcut_path_used = "date+room"
                else:
                    self.telemetry.shortcut_path_used = "none"
                if self.legacy_allowed:
                    self.telemetry.legacy_shortcut_invocations = max(0, executed_count - 1)
                else:
                    self.telemetry.legacy_shortcut_invocations = 0

        if executed_count == 0 and len(self.needs_input) == 1:
            follow_up = self._maybe_emit_single_followup()
            if follow_up:
                return follow_up

        if executed_count == 0 and not self.needs_input:
            preask_only = self._maybe_emit_preask_prompt_only()
            if preask_only:
                return preask_only
            if not self.preview_lines and self.telemetry.preask_response:
                return self._build_payload("\u200b")
            if not self.preview_lines:
                return None

        if combine_executed:
            self.telemetry.combined_confirmation = True
        else:
            self.telemetry.combined_confirmation = bool(self.summary_lines or self.product_line_details)
            if not self.policy.atomic_turns and self.telemetry.shortcut_path_used != "date+room":
                self.telemetry.shortcut_path_used = "none"
        next_question = self._select_next_question()
        if next_question is None:
            if self.policy.atomic_turns:
                next_question = self._default_next_question()
            else:
                fallback = self._default_next_question()
                if fallback and fallback.get("intent") == "offer_prepare" and self._is_room_locked():
                    next_question = fallback
        self.telemetry.needs_input_next = next_question["intent"] if next_question else None
        message = self._compose_message(next_question)
        self.telemetry.room_checked = bool(self.event.get("locked_room_id")) or self.room_checked
        if not self.telemetry.menus_included:
            self.telemetry.menus_included = "false"
        self.telemetry.product_price_missing = bool(self.telemetry.product_price_missing)
        self.telemetry.answered_question_first = True
        self.telemetry.delta_availability_used = False
        if "date_confirmation" in self.telemetry.executed_intents and "room_selection" in self.telemetry.executed_intents:
            self.telemetry.gatekeeper_passed = True
        elif "date_confirmation" in self.telemetry.executed_intents and "room_selection" not in self.telemetry.executed_intents:
            self.telemetry.gatekeeper_passed = False
        if self._dag_block_reason == "none":
            self.telemetry.dag_blocked = "none"
            self.state.telemetry.dag_blocked = "none"

        self._finalize_preask_state()
        self._persist_pending_intents()
        return self._build_payload(message)

    def _ensure_intents_prepared(self) -> None:
        if self._parsed:
            return
        self._process_preask()
        self._parse_intents()
        self._parsed = True

    # --------------------------------------------------------------------- parse
    def _parse_intents(self) -> None:
        self._parse_date_intent()
        self._parse_room_intent()
        self._parse_participants_intent()
        self._parse_billing_intent()
        self._parse_product_intent()
        self._ensure_date_choice_intent()

    def _parse_date_intent(self) -> None:
        if not (self.user_info.get("date") or self.user_info.get("event_date")):
            return

        window = self._manual_window_from_user_info()
        if window is None:
            window = self._resolve_window_from_module(preview=False)
        if window is None:
            self._add_needs_input("time", {"reason": "missing_time"}, reason="missing_time")
            return
        if getattr(window, "partial", False):
            self._add_needs_input("time", {"reason": "missing_time"}, reason="missing_time")
            return
        intent = ParsedIntent("date_confirmation", {"window": self._window_to_payload(window)}, verifiable=True)
        self.verifiable.append(intent)

    def _parse_room_intent(self) -> None:
        room = self.user_info.get("room")
        if not room:
            return

        if self._can_lock_room(room):
            intent = ParsedIntent("room_selection", {"room": room}, verifiable=True)
            self.verifiable.append(intent)
        else:
            self._add_needs_input("availability", {"room": room, "reason": "room_requires_date"}, reason="room_requires_date")

    def _parse_participants_intent(self) -> None:
        participants = self.user_info.get("participants")
        if participants is None:
            return
        if isinstance(participants, (int, float)) or str(participants).isdigit():
            intent = ParsedIntent("participants_update", {"participants": int(participants)}, verifiable=True)
            self.verifiable.append(intent)
        else:
            self._add_needs_input("requirements", {"reason": "participants_unclear"}, reason="participants_unclear")

    def _parse_billing_intent(self) -> None:
        billing = self.user_info.get("billing_address")
        if billing:
            self._add_needs_input("billing", {"billing_address": billing, "reason": "billing_after_offer"}, reason="billing_after_offer")

    def _parse_product_intent(self) -> None:
        if not _product_flow_enabled():
            return
        raw_products = self._normalise_products(self.user_info.get("products_add"))
        if not raw_products:
            return

        available_map = self._product_lookup("available_items")
        manager_map = self._product_lookup("manager_added_items")

        matched: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []

        for item in raw_products:
            name_key = item["name"].lower()
            catalog_entry = available_map.get(name_key) or manager_map.get(name_key)
            if catalog_entry:
                merged = dict(catalog_entry)
                merged.setdefault("name", catalog_entry.get("name") or item["name"])
                merged["quantity"] = item.get("quantity") or merged.get("quantity") or self._infer_quantity(merged)
                matched.append(merged)
            else:
                missing.append(item)

        if matched:
            self.pending_product_additions.extend(matched)
            self.verifiable.append(ParsedIntent("product_add", {"items": matched}, verifiable=True))

        limited_missing = missing[: _max_missing_items_per_hil()]

        if missing:
            self.pending_missing_products.extend(limited_missing)
            payload = {
                "items": limited_missing,
                "ask_budget": _capture_budget_on_hil(),
            }
            if self.budget_info:
                payload["budget"] = self.budget_info
                self.telemetry.budget_provided = True
            self.telemetry.offered_hil = True
            self._add_needs_input("offer_hil", payload, reason="missing_products")
            self.product_price_missing = True

        if matched and not missing:
            if self.telemetry.artifact_match is None:
                self.telemetry.artifact_match = "all"
        elif matched and missing:
            self.telemetry.artifact_match = "partial"
        elif not matched and missing:
            if self.telemetry.artifact_match is None:
                self.telemetry.artifact_match = "none"

        if missing:
            self.telemetry.missing_items.extend({"name": item.get("name")} for item in limited_missing)

    def _ensure_date_choice_intent(self) -> None:
        current_step = self.event.get("current_step")
        if current_step not in (None, 1, 2):
            return
        if self.event.get("chosen_date"):
            return
        if any(intent.type == "date_confirmation" for intent in self.verifiable):
            return
        if any(intent.type in {"time", "date_choice"} for intent in self.needs_input):
            return
        self._add_needs_input("date_choice", {"reason": "date_missing"}, reason="date_missing")

    # ------------------------------------------------------------------ execute
    def _is_date_confirmed(self) -> bool:
        if self.event.get("date_confirmed") is True:
            return True
        requested = self.event.get("requested_window") or {}
        if requested.get("date_iso") or requested.get("display_date"):
            return True
        return False

    def _is_room_locked(self) -> bool:
        return bool(self.event.get("locked_room_id"))

    def _can_collect_billing(self) -> bool:
        current_step = self.event.get("current_step") or 1
        if current_step >= 6:
            return True
        status = str(self.event.get("offer_status") or "").lower()
        return status in {"sent", "accepted", "finalized", "finalised", "approved", "ready"}

    def _set_dag_block(self, reason: Optional[str]) -> None:
        if not reason:
            return
        order = {"room_requires_date": 0, "products_require_room": 1, "billing_after_offer": 2}
        current_rank = order.get(self._dag_block_reason, 99)
        next_rank = order.get(reason, 99)
        if next_rank < current_rank:
            self._dag_block_reason = reason
        if reason == self._dag_block_reason:
            self.telemetry.dag_blocked = self._dag_block_reason
            self.state.telemetry.dag_blocked = self._dag_block_reason

    def _ensure_prerequisite_prompt(self, reason: Optional[str], intent: Optional[ParsedIntent] = None) -> None:
        if not reason:
            return
        if reason == "room_requires_date":
            self._ensure_date_choice_intent()
            return
        if reason == "products_require_room":
            if any(item.type == "availability" for item in self.needs_input):
                return
            payload: Dict[str, Any] = {"reason": "room_requires_date"}
            pending = self.event.get("room_pending_decision") or {}
            room = pending.get("selected_room")
            if room:
                payload["room"] = room
            self._add_needs_input("availability", payload, reason="room_requires_date")
            return
        if reason == "billing_after_offer":
            if any(item.type == "offer_prepare" for item in self.needs_input):
                return
            self._add_needs_input("offer_prepare", {}, reason="billing_after_offer")

    def _dag_guard(self, intent: ParsedIntent) -> Tuple[bool, Optional[str]]:
        reason: Optional[str] = None
        if intent.type == "room_selection" and not self._is_date_confirmed():
            reason = "room_requires_date"
        elif intent.type == "product_add" and not self._is_room_locked():
            reason = "products_require_room"
        elif intent.type == "billing" and not self._can_collect_billing():
            reason = "billing_after_offer"
        allowed = reason is None
        return allowed, reason

    def _time_from_iso(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return f"{parsed.hour:02d}:{parsed.minute:02d}"
        except ValueError:
            pass
        if len(text) >= 16 and text[13] == ":":
            candidate = text[11:16]
            return self._normalize_time(candidate)
        return self._normalize_time(text)

    def _preferred_date_slot(self) -> str:
        start = self._normalize_time(self.user_info.get("start_time"))
        end = self._normalize_time(self.user_info.get("end_time"))

        requested = self.event.get("requested_window") or {}
        if not start:
            start = self._normalize_time(requested.get("start_time")) or self._time_from_iso(requested.get("start"))
        if not end:
            end = self._normalize_time(requested.get("end_time")) or self._time_from_iso(requested.get("end"))

        requirements = self.event.get("requirements") or {}
        duration = requirements.get("event_duration") or {}
        if not start:
            start = self._normalize_time(duration.get("start"))
        if not end:
            end = self._normalize_time(duration.get("end"))

        start = start or "18:00"
        end = end or "22:00"
        if start and end:
            return f"{start}–{end}"
        return start or end or "18:00–22:00"

    def _candidate_date_options(self) -> List[str]:
        requirements = self.event.get("requirements") or {}
        preferred_room = requirements.get("preferred_room") or ""
        raw_dates = suggest_dates(
            self.state.db,
            preferred_room=preferred_room,
            start_from_iso=self.state.message.ts,
            days_ahead=45,
            max_results=5,
        )
        return raw_dates[:5]

    def _maybe_emit_date_options_answer(self) -> Optional[PlannerResult]:
        if self.verifiable:
            return None
        date_needed = next((intent for intent in self.needs_input if intent.type == "date_choice"), None)
        if not date_needed:
            return None

        slot_label = self._preferred_date_slot()
        options = self._candidate_date_options()
        lines: List[str] = [f"AVAILABLE DATES ({slot_label}):"]
        if options:
            for idx, option in enumerate(options, start=1):
                lines.append(f"{idx}) {option}")
        else:
            lines.append("No availability in the next 45 days — share another window and I'll check.")
        lines.append("")
        option_count = len(options)
        if option_count == 0:
            lines.append("Tell me another date/time window and I'll check it right away.")
        elif option_count == 1:
            lines.append("Reply with 1, or tell me another date/time window.")
        else:
            lines.append(f"Reply with a number (1–{option_count}), or tell me another date/time window.")

        self.telemetry.needs_input_next = "date_choice"
        self.telemetry.answered_question_first = True
        self.telemetry.combined_confirmation = False
        self.telemetry.menus_included = "false"
        self.telemetry.menus_phase = "none"
        self.state.telemetry.answered_question_first = True
        self._set_dag_block("room_requires_date")
        return self._build_payload(self._with_greeting("\n".join(lines)))

    def _should_execute_date_room_combo(self) -> bool:
        date_intent = next((intent for intent in self.verifiable if intent.type == "date_confirmation"), None)
        room_intent = next((intent for intent in self.verifiable if intent.type == "room_selection"), None)
        if not date_intent or not room_intent:
            return False
        window = date_intent.data.get("window") or {}
        if window.get("partial"):
            return False
        requested_room = room_intent.data.get("room")
        if not requested_room or not self._can_lock_room(requested_room):
            return False
        return True

    def _execute_date_room_combo(self) -> bool:
        date_intent = next((intent for intent in self.verifiable if intent.type == "date_confirmation"), None)
        room_intent = next((intent for intent in self.verifiable if intent.type == "room_selection"), None)
        if not date_intent or not room_intent:
            return False

        window_payload = date_intent.data.get("window") or {}
        if not self._apply_date_confirmation(window_payload):
            return False

        requested_room = room_intent.data.get("room")
        if not self._apply_room_selection(requested_room):
            return False
        return True

    def _execute_intent(self, intent: ParsedIntent) -> bool:
        if intent.type == "date_confirmation":
            return self._apply_date_confirmation(intent.data["window"])
        if intent.type == "room_selection":
            return self._apply_room_selection(intent.data["room"])
        if intent.type == "participants_update":
            return self._apply_participants_update(intent.data["participants"])
        if intent.type == "product_add":
            return self._apply_product_add(intent.data.get("items") or [])
        return False

    def _apply_date_confirmation(self, window_payload: Dict[str, Any]) -> bool:
        # Reuse Step 2 helpers to finalise confirmation.
        finalize = getattr(date_process_module, "_finalize_confirmation", None)
        if not finalize:
            return False
        window_obj = self._window_from_payload(window_payload)
        result = finalize(self.state, self.event, window_obj)
        # Remove legacy draft message; planner will compose new reply.
        self.state.draft_messages.clear()
        self.state.extras["persist"] = True
        self.telemetry.executed_intents.append("date_confirmation")
        start = window_payload.get("start_time")
        end = window_payload.get("end_time")
        iso = window_payload.get("display_date")
        tz = window_payload.get("tz", "Europe/Zurich")
        if start and end:
            slot = f"{start}–{end}"
        elif start:
            slot = start
        else:
            slot = "time pending"
        self.summary_lines.append(f"• Date confirmed: {iso} {slot} ({tz})")
        return result is not None

    def _apply_room_selection(self, requested_room: str) -> bool:
        pending = self.event.get("room_pending_decision") or {}
        selected = pending.get("selected_room") or self.event.get("locked_room_id")
        if not selected or selected.lower() != str(requested_room).strip().lower():
            return False
        status = pending.get("selected_status") or "Available"
        requirements_hash_value = pending.get("requirements_hash") or self.event.get("requirements_hash")
        update_event_metadata(
            self.event,
            locked_room_id=selected,
            room_eval_hash=requirements_hash_value,
            current_step=4,
            thread_state="In Progress",
            status="Option",  # Room selected → calendar blocked as Option
        )
        self.event.pop("room_pending_decision", None)
        append_audit_entry(self.event, 3, 4, "room_locked_via_shortcut")
        self.state.current_step = 4
        self.state.extras["persist"] = True
        self.telemetry.executed_intents.append("room_selection")
        self.summary_lines.append(f"• Room locked: {selected} ({status}) → Status: Option")
        self.room_checked = True
        return True

    def _apply_participants_update(self, participants: int) -> bool:
        requirements = dict(self.event.get("requirements") or {})
        requirements["number_of_participants"] = participants
        req_hash = requirements_hash(requirements)
        update_event_metadata(self.event, requirements=requirements, requirements_hash=req_hash)
        self.state.extras["persist"] = True
        self.telemetry.executed_intents.append("participants_update")
        self.summary_lines.append(f"• Headcount updated: {participants} guests")
        return True

    def _apply_product_add(self, items: List[Dict[str, Any]]) -> bool:
        if not items:
            return False
        products_list = self.event.setdefault("products", [])
        line_items = self._products_state().setdefault("line_items", [])
        currency_default = _budget_default_currency()
        for item in items:
            name = item.get("name") or "Unnamed item"
            quantity = max(1, int(item.get("quantity") or self._infer_quantity(item)))
            unit_price_raw = item.get("unit_price")
            currency = item.get("currency") or currency_default
            unit_price_value: Optional[float] = None
            if unit_price_raw is not None:
                try:
                    unit_price_value = float(unit_price_raw)
                except (TypeError, ValueError):
                    unit_price_value = None
            subtotal: Optional[float] = None
            if unit_price_value is not None:
                subtotal = unit_price_value * quantity
            else:
                self.product_price_missing = True

            updated = False
            for existing in products_list:
                if existing.get("name", "").lower() == name.lower():
                    existing["quantity"] = quantity
                    if unit_price_value is not None:
                        existing["unit_price"] = unit_price_value
                    updated = True
                    break
            if not updated:
                entry = {"name": name, "quantity": quantity}
                if unit_price_value is not None:
                    entry["unit_price"] = unit_price_value
                products_list.append(entry)

            line_updated = False
            for existing_line in line_items:
                if existing_line.get("name", "").lower() == name.lower():
                    existing_line["quantity"] = quantity
                    if unit_price_value is not None:
                        existing_line["unit_price"] = unit_price_value
                    line_updated = True
                    break
            if not line_updated:
                entry = {"name": name, "quantity": quantity}
                if unit_price_value is not None:
                    entry["unit_price"] = unit_price_value
                line_items.append(entry)

            self.telemetry.added_items.append({"name": name, "quantity": quantity})
            if subtotal is not None:
                self.product_currency_totals[currency] = self.product_currency_totals.get(currency, 0.0) + subtotal
            else:
                self.product_price_missing = True
            self.product_line_details.append(
                {
                    "name": name,
                    "quantity": quantity,
                    "currency": currency,
                    "unit_price": unit_price_value,
                    "subtotal": subtotal,
                    "price_missing": unit_price_value is None,
                }
            )

        if items:
            self.telemetry.executed_intents.append("product_add")
        self.state.extras["persist"] = True
        return True

    # ------------------------------------------------------------ utilities
    def _snapshot_event(self) -> Dict[str, Any]:
        event = self.event
        return {
            "date": event.get("chosen_date"),
            "locked_room_id": event.get("locked_room_id"),
            "requirements": dict(event.get("requirements") or {}),
            "pending_intents": list(event.get("pending_intents") or []),
        }

    def _resolve_window_from_module(self, preview: bool = False):
        resolver = getattr(date_process_module, "_resolve_confirmation_window", None)
        if not resolver:
            return None
        window = resolver(self.state, self.event)
        if not window:
            manual = self._manual_window_from_user_info()
            return manual
        if preview and window.partial and not window.start_time:
            return None
        return window

    def _manual_window_from_user_info(self) -> Optional[ConfirmationWindow]:
        date_iso = self.user_info.get("date")
        display = self.user_info.get("event_date") or format_iso_date_to_ddmmyyyy(date_iso)
        start_raw = self.user_info.get("start_time")
        end_raw = self.user_info.get("end_time")
        if not (start_raw and end_raw):
            inferred_start, inferred_end = self._infer_times_for_date(date_iso)
            start_raw = start_raw or inferred_start
            end_raw = end_raw or inferred_end
        if not (date_iso and display and start_raw and end_raw):
            return None
        start_norm = self._normalize_time(start_raw)
        end_norm = self._normalize_time(end_raw)
        if not (start_norm and end_norm):
            return None
        start_time_obj = datetime.strptime(start_norm, "%H:%M").time()
        end_time_obj = datetime.strptime(end_norm, "%H:%M").time()
        start_iso, end_iso = build_window_iso(date_iso, start_time_obj, end_time_obj)
        return ConfirmationWindow(
            display_date=display,
            iso_date=date_iso,
            start_time=start_norm,
            end_time=end_norm,
            start_iso=start_iso,
            end_iso=end_iso,
            inherited_times=False,
            partial=False,
            source_message_id=self.state.message.msg_id,
        )

    def _can_lock_room(self, requested_room: str) -> bool:
        pending = self.event.get("room_pending_decision") or {}
        selected = pending.get("selected_room")
        status = pending.get("selected_status")
        if not selected:
            return False
        return selected.lower() == str(requested_room).strip().lower() and status in {"Available", "Option"}

    def _add_needs_input(self, intent_type: str, data: Dict[str, Any], reason: str = "needs_input") -> None:
        self.needs_input.append(ParsedIntent(intent_type, data, verifiable=False, reason=reason))
        payload = {
            "type": intent_type,
            "entities": data,
            "confidence": 0.75,
            "reason_deferred": reason,
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        self.telemetry.deferred.append(payload)
        self.pending_items.append(payload)

    def _select_next_question(self) -> Optional[Dict[str, Any]]:
        if not self.needs_input:
            return None
        priority_map = {intent.type: intent for intent in self.needs_input}
        for candidate in self.priority_order:
            intent = priority_map.get(candidate)
            if intent:
                return {"intent": intent.type, "data": intent.data}
        # Fall back to first deferred.
        intent = self.needs_input[0]
        return {"intent": intent.type, "data": intent.data}

    def _build_product_confirmation_lines(self) -> List[str]:
        if not self.product_line_details:
            self.telemetry.product_prices_included = False
            self.telemetry.product_price_missing = self.product_price_missing
            return []
        lines: List[str] = ["Products added:"]
        any_missing = False
        for detail in self.product_line_details:
            line = self._format_product_line(detail)
            if detail.get("price_missing"):
                any_missing = True
            lines.append(line)
        subtotal_lines = self._product_subtotal_lines()
        lines.extend(subtotal_lines)
        any_priced = any(not detail.get("price_missing") for detail in self.product_line_details)
        all_priced = all(not detail.get("price_missing") for detail in self.product_line_details)
        self.telemetry.product_prices_included = all_priced and any_priced
        self.product_price_missing = self.product_price_missing or any_missing
        self.telemetry.product_price_missing = self.product_price_missing or any_missing
        return lines

    def _format_product_line(self, detail: Dict[str, Any]) -> str:
        name = detail.get("name") or "Unnamed item"
        quantity = detail.get("quantity") or 1
        unit_price = detail.get("unit_price")
        currency = detail.get("currency") or _budget_default_currency()
        if unit_price is None:
            return f"• {name} — {quantity} × TBD (price pending)"
        subtotal = detail.get("subtotal")
        unit_str = self._format_money(unit_price, currency)
        subtotal_str = self._format_money(subtotal or 0.0, currency)
        return f"• {name} — {quantity} × {unit_str} = {subtotal_str}"

    def _product_subtotal_lines(self) -> List[str]:
        if not self.product_currency_totals:
            return []
        if len(self.product_currency_totals) == 1:
            currency, amount = next(iter(self.product_currency_totals.items()))
            return [f"Products subtotal: {self._format_money(amount, currency)}"]
        lines: List[str] = []
        for currency in sorted(self.product_currency_totals.keys()):
            amount = self.product_currency_totals[currency]
            lines.append(f"Products subtotal ({currency}): {self._format_money(amount, currency)}")
        return lines

    @staticmethod
    def _format_money(amount: float, currency: str) -> str:
        if amount is None:
            return "TBD"
        rounded = round(amount, 2)
        if abs(rounded - round(rounded)) < 1e-6:
            value = str(int(round(rounded)))
        else:
            value = f"{rounded:.2f}".rstrip("0").rstrip(".")
        return f"{currency} {value}"

    def _compose_addons_section(self) -> Tuple[Optional[str], List[str]]:
        if self.preview_lines:
            phase = "post_room" if self.room_checked else "explicit_request"
            self.telemetry.menus_phase = phase
            self.telemetry.menus_included = "preview"
            if self.preview_class:
                self.telemetry.preview_class_shown = self.preview_class
                if not self.telemetry.preview_items_count:
                    item_count = sum(
                        1 for line in self.preview_lines if line.strip() and line.strip()[0].isdigit()
                    )
                    self.telemetry.preview_items_count = item_count
            return "preview", list(self.preview_lines)
        if not self.room_checked:
            if self.menu_requested:
                self.telemetry.menus_phase = "explicit_request"
            return None, []
        if self.menu_requested:
            preview_lines = self._menu_preview_lines() or []
            if preview_lines:
                self.telemetry.menus_phase = "explicit_request"
                self.telemetry.menus_included = "preview"
                return "explicit", preview_lines
        return None, []

    def _menu_preview_lines(self) -> Optional[List[str]]:
        names = _load_catering_names()
        if not names:
            return ["Catering menus will be available once the manager shares the current list."]
        preview = ", ".join(names[:3])
        if len(names) > 3:
            preview += ", ..."
        return [f"Catering menus: {preview}"]

    def _default_next_question(self) -> Optional[Dict[str, Any]]:
        current = self.event.get("current_step") or 1
        if current >= 4:
            return {"intent": "offer_prepare", "data": {}}
        if current == 3:
            pending = self.event.get("room_pending_decision") or {}
            room = pending.get("selected_room")
            if room:
                return {"intent": "availability", "data": {"room": room}}
        if current <= 2:
            return {"intent": "date_choice", "data": {"reason": "date_missing"}}
        return None

    def _compose_message(self, next_question: Optional[Dict[str, Any]]) -> str:
        lines: List[str] = []
        combined_lines: List[str] = []
        if self.preask_ack_lines:
            lines.extend(self.preask_ack_lines)
            self.preask_ack_lines.clear()
            if lines:
                lines.append("")
        if self.summary_lines:
            combined_lines.extend(self.summary_lines)
        product_lines = self._build_product_confirmation_lines()
        if product_lines:
            if combined_lines and combined_lines[-1] != "":
                combined_lines.append("")
            combined_lines.extend(product_lines)
        if combined_lines:
            lines.append("Combined confirmation:")
            lines.extend(combined_lines)
        if next_question:
            question_text = self._question_for_intent(next_question["intent"], next_question["data"])
            if question_text:
                if lines:
                    lines.append("")
                lines.append("Next question:")
                lines.append(question_text)
        mode, addon_lines = self._compose_addons_section()
        if addon_lines:
            if lines:
                lines.append("")
            lines.append("Add-ons (optional)")
            lines.extend(addon_lines)
        else:
            if mode is None:
                self.telemetry.menus_included = "false"
        preask_lines = self._maybe_preask_lines()
        if preask_lines:
            if lines:
                lines.append("")
            lines.extend(preask_lines)
        return "\n".join(lines).strip()

    def _question_for_intent(self, intent_type: str, data: Dict[str, Any]) -> str:
        if intent_type == "time":
            chosen_date = self.user_info.get("event_date") or format_iso_date_to_ddmmyyyy(self.user_info.get("date"))
            if chosen_date:
                return f"What start and end time should we reserve for {chosen_date}? (e.g., 14:00–18:00)"
            return "What start and end time should we reserve? (e.g., 14:00–18:00)"
        if intent_type == "availability":
            room = data.get("room")
            if room:
                return f"Should I run availability for {room}? Let me know if you’d prefer a different space."
            return "Which room would you like me to check availability for?"
        if intent_type == "site_visit":
            return "Would you like me to propose a few slots for a site visit?"
        if intent_type == "date_choice":
            return "Which date should I check for you? Feel free to share a couple of options."
        if intent_type == "budget":
            currency = _budget_default_currency()
            return f"Could you share a budget cap? For example \"{currency} 60 total\" or \"{currency} 30 per item\"."
        if intent_type == "offer_hil":
            items = data.get("items") or []
            item_names = ", ".join(self._missing_item_display(item) for item in items)
            budget = data.get("budget") or self.budget_info
            currency = (budget or {}).get("currency") or _budget_default_currency()
            if budget:
                budget_text = budget.get("text") or self._format_money(budget.get("amount"), currency)
                return (
                    f"Would you like me to send a request to our manager for {item_names} with budget {budget_text}? "
                    "You'll receive an email once the manager replies."
                )
            if _capture_budget_on_hil():
                return (
                    f"Would you like me to send a request to our manager for {item_names}? "
                    f"If so, let me know a budget cap (e.g., \"{currency} 60 total\" or \"{currency} 30 per item\"). You'll receive an email once the manager replies."
                )
            return (
                f"Would you like me to send a request to our manager for {item_names}? "
                "You'll receive an email once they reply."
            )
        if intent_type == "billing":
            return "Could you confirm the billing address when you’re ready?"
        if intent_type == "offer_prepare":
            return "Should I start drafting the offer next, or is there another detail you'd like me to capture?"
        if intent_type == "product_followup":
            items = data.get("items") or []
            names = ", ".join(item.get("name") or "the item" for item in items) or "the pending item"
            return (
                f"I queued {names} for the next update because we already confirmed two items. "
                "Should I keep that plan, or is there another detail you’d like me to prioritize now?"
            )
        return "Let me know the next detail you’d like me to update."

    def _defer_intent(self, intent: ParsedIntent, reason: str) -> None:
        payload = {
            "type": intent.type,
            "entities": intent.data,
            "confidence": 0.95,
            "reason_deferred": reason,
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        self.telemetry.deferred.append(payload)
        self.pending_items.append(payload)
        if reason == "combined_limit_reached" and intent.type == "product_add":
            self.needs_input.append(ParsedIntent("product_followup", intent.data, verifiable=False, reason=reason))

    def _persist_pending_intents(self) -> None:
        if not self.pending_items:
            return
        existing = list(self.event.get("pending_intents") or [])
        existing.extend(self.pending_items)
        self.event["pending_intents"] = existing
        self.state.extras["persist"] = True

    def _record_telemetry_log(self) -> None:
        logs = self.event.setdefault("logs", [])
        log_entry = self.telemetry.to_log(self.state.message.msg_id, self.event.get("event_id"))
        log_entry["ts"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        log_entry["actor"] = "smart_shortcuts"
        logs.append(log_entry)

    def _group_manager_items(self) -> Dict[str, List[Dict[str, Any]]]:
        items = self.products_state.get("manager_added_items") or []
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for raw in items:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            class_name = str(raw.get("class") or "catering").strip().lower()
            grouped[class_name].append(dict(raw))
        return dict(grouped)

    def _manager_catalog_signature(self) -> List[Tuple[str, str]]:
        signature: List[Tuple[str, str]] = []
        for class_name, items in self.manager_items_by_class.items():
            for item in items:
                signature.append((class_name, str(item.get("name") or "")))
        signature.sort()
        return signature

    def _sync_manager_catalog_signature(self) -> None:
        current_signature = self._manager_catalog_signature()
        previous_raw = self.products_state.get("manager_catalog_signature") or []
        previous_signature = []
        for entry in previous_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            class_name = str(entry[0]).strip().lower()
            name = str(entry[1]).strip()
            previous_signature.append((class_name, name))
        previous_signature.sort()

        previous_map: Dict[str, set[str]] = defaultdict(set)
        for class_name, name in previous_signature:
            previous_map[class_name].add(name)
        current_map: Dict[str, set[str]] = defaultdict(set)
        for class_name, name in current_signature:
            current_map[class_name].add(name)

        changed_classes = {cls for cls in set(previous_map) | set(current_map) if previous_map.get(cls) != current_map.get(cls)}
        for class_name in changed_classes:
            self.presented_interest[class_name] = "unknown"
            self.preask_pending_state.pop(class_name, None)

        normalised_signature = [[cls, name] for cls, name in current_signature]
        should_persist = changed_classes or normalised_signature != previous_raw
        if should_persist:
            self.products_state["manager_catalog_signature"] = normalised_signature
            self.state.extras["persist"] = True

    def _load_choice_context(self) -> Optional[Dict[str, Any]]:
        context = self.event.get("choice_context")
        if not context:
            self.telemetry.choice_context_active = False
            return None
        ttl = context.get("ttl_turns")
        try:
            ttl_value = int(ttl)
        except (TypeError, ValueError):
            ttl_value = 0
        if ttl_value <= 0:
            self.event["choice_context"] = None
            self.state.extras["persist"] = True
            self.telemetry.choice_context_active = False
            self.telemetry.re_prompt_reason = "expired"
            kind = context.get("kind")
            if kind:
                self.preview_requests.append((kind, 0))
            return None
        refreshed = dict(context)
        refreshed["ttl_turns"] = ttl_value - 1
        self.event["choice_context"] = refreshed
        self.state.extras["persist"] = True
        self.telemetry.choice_context_active = True
        return refreshed

    def _products_state(self) -> Dict[str, Any]:
        return self.event.setdefault(
            "products_state",
            {
                "available_items": [],
                "manager_added_items": [],
                "line_items": [],
                "pending_hil_requests": [],
                "budgets": {},
            },
        )

    def _preask_feature_enabled(self) -> bool:
        return _event_scoped_upsell_enabled() and _no_unsolicited_menus() and bool(self.manager_items_by_class)

    def _process_preask(self) -> None:
        self.telemetry.preask_candidates = []
        self.telemetry.preask_shown = []
        self.telemetry.preview_class_shown = "none"
        self.telemetry.preview_items_count = 0
        self.telemetry.re_prompt_reason = "none"
        self.telemetry.selection_method = "none"
        self.telemetry.choice_context_active = bool(self.choice_context)
        if not self._preask_feature_enabled():
            return
        for class_name, status in (self.presented_interest or {}).items():
            if status == "interested":
                self.telemetry.preask_response.setdefault(class_name, "yes")
            elif status == "declined":
                self.telemetry.preask_response.setdefault(class_name, "no")
            else:
                self.telemetry.preask_response.setdefault(class_name, "n/a")
        message_text = (self.state.message.body or "").strip().lower()
        if not self._choice_context_handled:
            self._handle_choice_selection(message_text)
        self._handle_preask_responses(message_text)
        self._prepare_preview_for_requests()
        self._hydrate_preview_from_context()

    def _maybe_handle_choice_context_reply(self) -> Optional[PlannerResult]:
        context = self.choice_context
        if not context:
            return None
        message_text = (self.state.message.body or "").strip()
        if not message_text:
            return None

        selection = self._parse_choice_selection(context, message_text)
        if selection:
            confirmation, state_delta = self._complete_choice_selection(context, selection)
            self._choice_context_handled = True
            self.telemetry.selection_method = selection.get("method") or "label"
            self.telemetry.re_prompt_reason = "none"
            self.telemetry.choice_context_active = False
            return self._build_payload(confirmation, state_delta=state_delta)

        clarification = self._choice_clarification_prompt(context, message_text)
        if clarification:
            self._choice_context_handled = True
            self.telemetry.selection_method = "clarified"
            self.telemetry.re_prompt_reason = "ambiguous"
            kind = context.get("kind")
            if kind:
                self.telemetry.preask_response[kind] = "clarify"
            self.telemetry.choice_context_active = True
            return self._build_payload(clarification)

        return None

    def _choice_clarification_prompt(self, context: Dict[str, Any], text: str) -> Optional[str]:
        items = context.get("items") or []
        if not items:
            return None
        normalized = text.strip().lower()
        similarity: List[Tuple[float, Dict[str, Any]]] = []
        for item in items:
            label = str(item.get("label") or "").lower()
            if not label:
                continue
            ratio = SequenceMatcher(a=label, b=normalized).ratio()
            similarity.append((ratio, item))
        if not similarity:
            return None
        similarity.sort(key=lambda pair: pair[0], reverse=True)
        top_ratio, top_item = similarity[0]
        second_ratio = similarity[1][0] if len(similarity) > 1 else 0.0
        if top_ratio < 0.5:
            return None
        if len(similarity) > 1 and second_ratio >= 0.5 and abs(top_ratio - second_ratio) < 0.08:
            ambiguous_items = [item for ratio, item in similarity if abs(top_ratio - ratio) < 0.08]
            if ambiguous_items:
                chosen = min(ambiguous_items, key=lambda entry: entry.get("idx") or 0)
            else:
                chosen = top_item
            display = self._format_choice_item(chosen)
            return f"Do you mean {display}?"
        return None

    def _complete_choice_selection(
        self,
        context: Dict[str, Any],
        selection: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        item = selection.get("item") or {}
        raw_value = dict(item.get("value") or {})
        class_name = (context.get("kind") or raw_value.get("class") or "product").lower()
        idx = item.get("idx")
        manager_items = self.manager_items_by_class.get(class_name, [])
        if isinstance(idx, int) and 1 <= idx <= len(manager_items):
            value = dict(manager_items[idx - 1] or {})
        else:
            value = raw_value
        label = item.get("label") or value.get("name") or "this option"

        addition: Dict[str, Any] = {"name": value.get("name") or label}
        quantity = value.get("quantity") or (value.get("meta") or {}).get("quantity")
        if quantity is not None:
            try:
                addition["quantity"] = max(1, int(quantity))
            except (TypeError, ValueError):
                addition["quantity"] = 1
        else:
            addition["quantity"] = 1
        unit_price = value.get("unit_price")
        if unit_price is None:
            unit_price = (value.get("meta") or {}).get("unit_price")
        if unit_price is not None:
            try:
                addition["unit_price"] = float(unit_price)
            except (TypeError, ValueError):
                pass

        if class_name in {"catering", "av", "furniture", "product"}:
            self._apply_product_add([addition])
            self.telemetry.combined_confirmation = True
        self.presented_interest[class_name] = "interested"
        self.preask_pending_state[class_name] = False
        self.telemetry.preask_response[class_name] = self.telemetry.preask_response.get(class_name, "yes")
        self.choice_context = None
        self.event["choice_context"] = None
        self.state.extras["persist"] = True

        confirmation = f"Got it — I'll add {label}."
        state_delta = {
            "choice_context": {
                "kind": class_name,
                "selected": {
                    "label": label,
                    "idx": item.get("idx"),
                    "key": item.get("key"),
                },
            }
        }
        return confirmation, state_delta

    def _format_choice_item(self, item: Dict[str, Any]) -> str:
        label = item.get("label") or (item.get("value") or {}).get("name") or "this option"
        idx = item.get("idx")
        if idx is not None:
            return f"{idx}) {label}"
        return label

    def _maybe_emit_preask_prompt_only(self) -> Optional[PlannerResult]:
        if not self._preask_feature_enabled():
            return None
        lines = self._maybe_preask_lines()
        if not lines:
            return None
        message = "\n".join(lines).strip()
        return self._build_payload(message or "\u200b")

    def _maybe_emit_single_followup(self) -> Optional[PlannerResult]:
        if len(self.needs_input) != 1:
            return None
        intent = self.needs_input[0]
        question = self._question_for_intent(intent.type, intent.data)
        if not question:
            return None
        self.telemetry.needs_input_next = intent.type
        self.telemetry.combined_confirmation = False
        self.telemetry.answered_question_first = True
        if not self.telemetry.menus_included:
            self.telemetry.menus_included = "false"
        return self._build_payload(question)

    def _build_payload(self, message: str, state_delta: Optional[Dict[str, Any]] = None) -> PlannerResult:
        message = message.strip()
        if not message:
            message = "\u200b"
        preview_display = self.telemetry.preview_class_shown
        preview_count = self.telemetry.preview_items_count
        self._finalize_preask_state()
        if preview_display and preview_display != "none":
            self.telemetry.preview_class_shown = preview_display
        if preview_count:
            self.telemetry.preview_items_count = preview_count
        self._persist_pending_intents()
        telemetry_snapshot = asdict(self.telemetry)
        payload = {
            "combined_confirmation": self.telemetry.combined_confirmation,
            "executed_intents": list(self.telemetry.executed_intents),
            "needs_input_next": self.telemetry.needs_input_next,
            "deferred_count": len(self.telemetry.deferred),
            "message": message,
            "pending_intents": list(self.pending_items),
            "artifact_match": self.telemetry.artifact_match,
            "added_items": self.telemetry.added_items,
            "missing_items": self.telemetry.missing_items,
            "offered_hil": self.telemetry.offered_hil,
            "hil_request_created": self.telemetry.hil_request_created,
            "budget_provided": self.telemetry.budget_provided,
            "upsell_shown": self.telemetry.upsell_shown,
            "room_checked": self.telemetry.room_checked,
            "menus_included": self.telemetry.menus_included or "false",
            "menus_phase": self.telemetry.menus_phase,
            "product_prices_included": self.telemetry.product_prices_included,
            "product_price_missing": self.telemetry.product_price_missing,
            "gatekeeper_passed": self.telemetry.gatekeeper_passed,
            "answered_question_first": self.telemetry.answered_question_first,
            "delta_availability_used": self.telemetry.delta_availability_used,
            "preask_candidates": list(self.telemetry.preask_candidates or []),
            "preask_shown": list(self.telemetry.preask_shown or []),
            "preask_response": dict(self.telemetry.preask_response or {}),
            "preview_class_shown": self.telemetry.preview_class_shown,
            "preview_items_count": self.telemetry.preview_items_count,
            "choice_context_active": self.telemetry.choice_context_active,
            "selection_method": self.telemetry.selection_method,
            "re_prompt_reason": self.telemetry.re_prompt_reason,
            "legacy_shortcut_invocations": self.telemetry.legacy_shortcut_invocations,
            "shortcut_path_used": self.telemetry.shortcut_path_used,
            "telemetry": telemetry_snapshot,
            "state_delta": state_delta or {},
        }
        self._record_telemetry_log()
        return PlannerResult(payload)
    def _handle_choice_selection(self, text: str) -> None:
        if not self.choice_context:
            return
        if "show more" in text and self.choice_context.get("kind"):
            next_offset = self.choice_context.get("next_offset", len(self.choice_context.get("items") or []))
            self.preview_requests.append((self.choice_context.get("kind"), next_offset))
            return
        selection = self._parse_choice_selection(self.choice_context, text)
        if not selection:
            class_name = self.choice_context.get("kind")
            if class_name:
                keywords = set(_CLASS_KEYWORDS.get(class_name, set())) | {class_name}
                if any(keyword in text for keyword in keywords):
                    if class_name not in self.preask_clarifications:
                        self.preask_clarifications.append(class_name)
                    self.preask_pending_state[class_name] = True
                    self.telemetry.re_prompt_reason = "ambiguous"
                    self.telemetry.preask_response[class_name] = "clarify"
            return
        self._apply_choice_selection(self.choice_context, selection)
        self.choice_context = None
        self.event["choice_context"] = None
        self.state.extras["persist"] = True
        self.telemetry.choice_context_active = False

    def _parse_choice_selection(self, context: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        normalized = text.strip().lower()
        items = context.get("items") or []
        if not items:
            return None
        idx_map = {int(item.get("idx")): item for item in items if item.get("idx") is not None}
        ordinal_match = re.search(r"(?:^|\s)#?(\d{1,2})\b", normalized)
        if ordinal_match:
            try:
                idx = int(ordinal_match.group(1))
                if idx in idx_map:
                    return {"item": idx_map[idx], "method": "ordinal"}
            except ValueError:
                pass
        option_match = re.search(r"option\s+(\d{1,2})", normalized)
        if option_match:
            try:
                idx = int(option_match.group(1))
                if idx in idx_map:
                    return {"item": idx_map[idx], "method": "ordinal"}
            except ValueError:
                pass
        lang = str(context.get("lang") or "en").split("-")[0].lower()
        ordinal_words = _ORDINAL_WORDS_BY_LANG.get(lang, {})
        fallback_words = _ORDINAL_WORDS_BY_LANG.get("en", {})
        for raw_token in normalized.replace(".", " ").split():
            token = raw_token.strip()
            mapped = ordinal_words.get(token) or fallback_words.get(token)
            if mapped and mapped in idx_map:
                return {"item": idx_map[mapped], "method": "ordinal"}
        direct_matches = []
        for item in items:
            label = str(item.get("label") or "").lower()
            if label and label in normalized:
                direct_matches.append(item)
        if len(direct_matches) == 1:
            return {"item": direct_matches[0], "method": "label"}
        if len(direct_matches) > 1:
            return None
        similarity: List[Tuple[float, Dict[str, Any]]] = []
        for item in items:
            label = str(item.get("label") or "").lower()
            if not label:
                continue
            ratio = SequenceMatcher(a=label, b=normalized).ratio()
            similarity.append((ratio, item))
        if not similarity:
            return None
        similarity.sort(key=lambda pair: pair[0], reverse=True)
        best_ratio, best_item = similarity[0]
        second_ratio = similarity[1][0] if len(similarity) > 1 else 0.0
        # Treat as ambiguous if multiple close matches score similarly high.
        if len(similarity) > 1 and best_ratio >= 0.5 and second_ratio >= 0.5 and abs(best_ratio - second_ratio) < 0.08:
            return None
        if best_ratio >= 0.8:
            return {"item": best_item, "method": "fuzzy"}
        return None

    def _apply_choice_selection(self, context: Dict[str, Any], selection: Dict[str, Any]) -> None:
        item = selection.get("item") or {}
        value = item.get("value") or {}
        class_name = context.get("kind") or value.get("class") or "catering"
        product_name = value.get("name") or item.get("label")
        if not product_name:
            return
        addition: Dict[str, Any] = {"name": product_name, "quantity": value.get("quantity") or value.get("meta", {}).get("quantity") or 1}
        unit_price = value.get("unit_price") or value.get("meta", {}).get("unit_price")
        if unit_price is not None:
            try:
                addition["unit_price"] = float(unit_price)
            except (TypeError, ValueError):
                pass
        self._apply_product_add([addition])
        self.presented_interest[class_name] = "interested"
        self.preask_pending_state[class_name] = False
        self.telemetry.selection_method = selection.get("method") or "label"
        self.telemetry.preask_response[class_name] = self.telemetry.preask_response.get(class_name, "n/a")

    def _handle_preask_responses(self, text: str) -> None:
        if not text:
            return
        pending_classes = [cls for cls, flag in self.preask_pending_state.items() if flag]
        for class_name in pending_classes:
            response = self._detect_preask_response(class_name, text)
            if not response:
                continue
            if response == "yes":
                self.presented_interest[class_name] = "interested"
                self.preask_pending_state[class_name] = False
                self.preview_requests.append((class_name, 0))
                self.telemetry.preask_response[class_name] = "yes"
                self.telemetry.re_prompt_reason = "none"
            elif response == "no":
                self.presented_interest[class_name] = "declined"
                self.preask_pending_state[class_name] = False
                self.telemetry.preask_response[class_name] = "no"
                self.telemetry.re_prompt_reason = "none"
                self.preask_ack_lines.append(f"Noted — I'll skip {class_name} options for now.")
            elif response == "clarify":
                if class_name not in self.preask_clarifications:
                    self.preask_clarifications.append(class_name)
                self.telemetry.preask_response[class_name] = "clarify"
                self.telemetry.re_prompt_reason = "ambiguous"
            elif response == "show_more":
                next_offset = 0
                if self.choice_context and self.choice_context.get("kind") == class_name:
                    next_offset = self.choice_context.get("next_offset", len(self.choice_context.get("items") or []))
                self.preview_requests.append((class_name, next_offset))
            if response in {"yes", "no"} and class_name in self.preask_clarifications:
                self.preask_clarifications.remove(class_name)

    def _detect_preask_response(self, class_name: str, text: str) -> Optional[str]:
        keywords = set(_CLASS_KEYWORDS.get(class_name, set())) | {class_name}
        has_keyword = any(keyword in text for keyword in keywords)
        single_pending = self._single_pending_class(class_name)
        if "show more" in text and self.choice_context and self.choice_context.get("kind") == class_name:
            return "show_more"
        affirmatives = ["yes", "sure", "ok", "okay", "definitely", "sounds good", "go ahead"]
        negatives = ["no", "not now", "later", "skip", "nope", "don't"]
        if any(token in text for token in negatives) and (has_keyword or single_pending):
            return "no"
        if any(token in text for token in affirmatives) and (has_keyword or single_pending):
            return "yes"
        if has_keyword and ("?" in text or "which" in text or "what" in text):
            return "clarify"
        return None

    def _single_pending_class(self, class_name: str) -> bool:
        active = [cls for cls, flag in self.preask_pending_state.items() if flag]
        return len(active) == 1 and class_name in active

    def _prepare_preview_for_requests(self) -> None:
        if not self.preview_requests:
            return
        class_name, offset = self.preview_requests[-1]
        self._build_preview_for_class(class_name, offset)
        self.preview_requests.clear()

    def _hydrate_preview_from_context(self) -> None:
        if self.preview_lines or not self.choice_context:
            return
        items = self.choice_context.get("items") or []
        if not items:
            return
        lines: List[str] = []
        for item in items:
            idx = item.get("idx")
            label = str(item.get("label") or "").strip() or "This option"
            if idx is not None:
                lines.append(f"{idx}. {label}")
            else:
                lines.append(label)
        lines.append("Which one (1–3) or \"show more\"?")
        self.preview_lines = lines
        class_name = str(self.choice_context.get("kind") or "").strip().lower()
        if class_name:
            self.preview_class = class_name
            self.telemetry.preview_class_shown = class_name
        self.telemetry.preview_items_count = max(self.telemetry.preview_items_count, len(items))
        if self.telemetry.menus_phase == "none":
            self.telemetry.menus_phase = "post_room" if self.room_checked else "explicit_request"
        if self.telemetry.menus_included == "false":
            self.telemetry.menus_included = "preview"
        self.telemetry.choice_context_active = True

    def _build_preview_for_class(self, class_name: str, offset: int) -> None:
        items = self.manager_items_by_class.get(class_name, [])
        if not items:
            return
        subset = items[offset : offset + 3]
        if not subset:
            self.preview_lines = [f"That's all available for {class_name}."]
            self.preview_class = class_name
            self.choice_context = None
            self.event["choice_context"] = None
            self.telemetry.preview_class_shown = class_name
            self.telemetry.preview_items_count = 0
            self.state.extras["persist"] = True
            self.preask_pending_state[class_name] = False
            if class_name in self.preask_clarifications:
                self.preask_clarifications.remove(class_name)
            return
        lines: List[str] = []
        context_items: List[Dict[str, Any]] = []
        for idx, item in enumerate(subset, start=1):
            name = str(item.get("name") or "").strip()
            lines.append(f"{idx}. {name}")
            context_items.append(
                {
                    "idx": idx,
                    "key": f"{class_name}-{offset + idx}",
                    "label": name,
                    "value": dict(item),
                }
            )
        lines.append("Which one (1–3) or \"show more\"?")
        self.preview_lines = lines
        self.preview_class = class_name
        context = {
            "kind": class_name,
            "presented_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "items": context_items,
            "ttl_turns": 4,
            "next_offset": offset + len(subset),
            "lang": "en",
        }
        self.choice_context = context
        self.event["choice_context"] = dict(context)
        self.state.extras["persist"] = True
        self.telemetry.preview_class_shown = class_name
        self.telemetry.preview_items_count = len(subset)
        self.telemetry.choice_context_active = True
        if self.telemetry.menus_phase == "none":
            self.telemetry.menus_phase = "post_room" if self.room_checked else "explicit_request"
        self.telemetry.menus_included = "preview"
        self.preask_pending_state[class_name] = False
        if class_name in self.preask_clarifications:
            self.preask_clarifications.remove(class_name)

    def _maybe_preask_lines(self) -> List[str]:
        if not self._preask_feature_enabled():
            return []
        lines: List[str] = []
        unknown_classes = [cls for cls in self.manager_items_by_class if self.presented_interest.get(cls, "unknown") == "unknown"]
        self.telemetry.preask_candidates = unknown_classes
        shown: List[str] = []
        slots = 2
        for class_name in list(self.preask_clarifications):
            if slots <= 0:
                break
            prompt = f"Do you want to see {class_name} options now? (yes/no)"
            lines.append(prompt)
            shown.append(class_name)
            self.preask_pending_state[class_name] = True
            self.telemetry.preask_response[class_name] = self.telemetry.preask_response.get(class_name, "clarify")
            slots -= 1
        if slots > 0:
            for class_name in unknown_classes:
                if slots <= 0:
                    break
                if class_name in shown or self.preask_pending_state.get(class_name):
                    continue
                prompt = _PREASK_CLASS_COPY.get(class_name, f"Would you like to see {class_name} options we can provide?")
                lines.append(prompt)
                shown.append(class_name)
                self.preask_pending_state[class_name] = True
                slots -= 1
        for class_name in shown:
            self.telemetry.preask_response.setdefault(class_name, "n/a")
        self.telemetry.preask_shown = shown
        if lines and self.telemetry.menus_included == "false":
            self.telemetry.menus_included = "brief_upsell"
        if lines and self.telemetry.menus_phase == "none" and self.room_checked:
            self.telemetry.menus_phase = "post_room"
        return lines

    def _finalize_preask_state(self) -> None:
        if not self._preask_feature_enabled():
            if self.products_state.get("preask_pending"):
                self.products_state["preask_pending"] = {}
                self.state.extras["persist"] = True
            if self.event.get("choice_context"):
                self.event["choice_context"] = None
                self.state.extras["persist"] = True
            self.telemetry.choice_context_active = False
            return
        self.products_state["preask_pending"] = {cls: bool(flag) for cls, flag in self.preask_pending_state.items() if flag}
        self.products_state["presented_interest"] = dict(self.presented_interest)
        if self.choice_context:
            self.event["choice_context"] = dict(self.choice_context)
            self.telemetry.choice_context_active = True
        elif self.event.get("choice_context"):
            self.event["choice_context"] = None
            self.telemetry.choice_context_active = False
        self.preview_lines = []
        if not self.preview_class:
            self.telemetry.preview_class_shown = "none"
            self.telemetry.preview_items_count = 0
        self.preview_class = None
        self.state.extras["persist"] = True
    def _product_lookup(self, bucket: str) -> Dict[str, Dict[str, Any]]:
        items = self._products_state().get(bucket) or []
        lookup: Dict[str, Dict[str, Any]] = {}
        for entry in items:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            lookup[name.lower()] = dict(entry)
        return lookup

    def _normalise_products(self, payload: Any) -> List[Dict[str, Any]]:
        participant_count = self.user_info.get("participants") if isinstance(self.user_info.get("participants"), int) else None
        return normalise_product_payload(payload, participant_count=participant_count)

    @staticmethod
    def _missing_item_display(item: Dict[str, Any]) -> str:
        name = str(item.get("name") or "the item").strip() or "the item"
        return f"{name} — price pending (via manager)"

    def _extract_budget_info(self) -> Optional[Dict[str, Any]]:
        candidates = [
            ("budget_total", "total"),
            ("budget", "total"),
            ("budget_cap", "total"),
            ("budget_per_person", "per_person"),
        ]
        for key, scope in candidates:
            if key not in self.user_info:
                continue
            parsed = self._parse_budget_value(self.user_info[key], scope_default=scope)
            if parsed:
                return parsed
        return None

    def _parse_budget_value(self, value: Any, scope_default: str) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            amount = value.get("amount")
            currency = value.get("currency") or _budget_default_currency()
            scope = value.get("scope") or scope_default
            text = value.get("text")
            if amount is None and isinstance(text, str):
                parsed = self._parse_budget_text(text, scope)
                if parsed:
                    return parsed
            if amount is None:
                return None
            try:
                amount_value = float(amount)
            except (TypeError, ValueError):
                return None
            display = text or f"{currency} {amount_value:g}"
            return {"amount": amount_value, "currency": currency, "scope": scope, "text": display}
        if isinstance(value, (int, float)):
            amount_value = float(value)
            currency = _budget_default_currency()
            display = f"{currency} {amount_value:g}"
            return {"amount": amount_value, "currency": currency, "scope": scope_default, "text": display}
        if isinstance(value, str):
            return self._parse_budget_text(value, scope_default)
        return None

    @staticmethod
    def _parse_budget_text(value: str, scope_default: str) -> Optional[Dict[str, Any]]:
        text = (value or "").strip()
        if not text:
            return None
        pattern = re.compile(
            r"(?P<currency>[A-Za-z]{3})?\s*(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?P<scope>per\s*(?:person|guest|head)|total|overall)?",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None
        currency = match.group("currency") or _budget_default_currency()
        if not match.group("currency") and _budget_parse_strict():
            return None
        try:
            amount = float(match.group("amount").replace(",", "."))
        except (TypeError, ValueError):
            return None
        scope_token = (match.group("scope") or scope_default or "").lower().strip()
        if scope_token.startswith("per"):
            scope = "per_person"
        elif scope_token in {"total", "overall"}:
            scope = "total"
        else:
            scope = scope_default
        display = text if match.group("currency") else f"{currency} {amount:g} {scope.replace('_', ' ')}".strip()
        return {"amount": amount, "currency": currency, "scope": scope, "text": display}

    def _infer_quantity(self, product_entry: Dict[str, Any]) -> int:
        qty = product_entry.get("quantity")
        if isinstance(qty, (int, float)):
            value = int(qty)
            return max(1, value)
        participants = self._current_participant_count()
        if participants:
            return max(1, participants)
        return 1

    def _current_participant_count(self) -> Optional[int]:
        candidates = [
            self.user_info.get("participants"),
            (self.event.get("requirements") or {}).get("number_of_participants"),
            (self.event.get("event_data") or {}).get("Number of Participants"),
        ]
        for value in candidates:
            if value in (None, "", "Not specified"):
                continue
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _window_to_payload(window: ConfirmationWindow) -> Dict[str, Any]:
        return {
            "display_date": window.display_date,
            "iso_date": window.iso_date,
            "start_time": window.start_time,
            "end_time": window.end_time,
            "start_iso": window.start_iso,
            "end_iso": window.end_iso,
            "tz": getattr(window, "tz", "Europe/Zurich"),
            "inherited_times": getattr(window, "inherited_times", False),
            "partial": getattr(window, "partial", False),
            "source_message_id": getattr(window, "source_message_id", None),
        }

    @staticmethod
    def _window_from_payload(payload: Dict[str, Any]) -> ConfirmationWindow:
        return ConfirmationWindow(
            display_date=payload.get("display_date"),
            iso_date=payload.get("iso_date"),
            start_time=payload.get("start_time"),
            end_time=payload.get("end_time"),
            start_iso=payload.get("start_iso"),
            end_iso=payload.get("end_iso"),
            inherited_times=payload.get("inherited_times", False),
            partial=payload.get("partial", False),
            source_message_id=payload.get("source_message_id"),
        )

    @staticmethod
    def _normalize_time(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        text = text.replace(".", ":")
        if ":" not in text:
            if text.isdigit():
                text = f"{int(text) % 24:02d}:00"
            else:
                return None
        try:
            parsed = datetime.strptime(text, "%H:%M").time()
        except ValueError:
            return None
        return f"{parsed.hour:02d}:{parsed.minute:02d}"

    def _infer_times_for_date(self, iso_date: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        if not iso_date:
            return None, None
        requested = self.event.get("requested_window") or {}
        if requested:
            date_match = requested.get("date_iso") == iso_date
            display_match = requested.get("display_date") == format_iso_date_to_ddmmyyyy(iso_date)
            if date_match or display_match:
                start_time = requested.get("start_time")
                end_time = requested.get("end_time")
                if not start_time and requested.get("start"):
                    start_time = requested.get("start")[11:16]
                if not end_time and requested.get("end"):
                    end_time = requested.get("end")[11:16]
                return start_time, end_time
        requirements = self.event.get("requirements") or {}
        duration = requirements.get("event_duration") or {}
        if duration.get("start") and duration.get("end"):
            return duration.get("start"), duration.get("end")
        event_data = self.event.get("event_data") or {}
        start = event_data.get("Start Time")
        end = event_data.get("End Time")
        return start, end

    def _explicit_menu_requested(self) -> bool:
        text = f"{self.state.message.subject or ''}\n{self.state.message.body or ''}".lower()
        keywords = (
            "menu",
            "menus",
            "catering menu",
            "catering options",
            "food options",
        )
        return any(keyword in text for keyword in keywords)

@lru_cache(maxsize=1)
def _load_catering_names() -> List[str]:
    path = Path(__file__).resolve().parents[2] / "catering_menu.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    packages = data.get("catering_packages") or []
    names: List[str] = []
    for pkg in packages:
        name = str(pkg.get("name") or "").strip()
        if name:
            names.append(name)
    return names
