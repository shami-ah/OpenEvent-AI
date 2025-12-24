from __future__ import annotations

import os
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import build_requirements, merge_client_profile, requirements_hash
from backend.workflows.common.timeutils import format_ts_to_ddmmyyyy, format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.change_propagation import (
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
import json

from backend.domain import IntentLabel
from backend.debug.hooks import (
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_prompt_in,
    trace_prompt_out,
    trace_state,
    trace_step,
)
from backend.workflows.io.database import (
    append_history,
    append_audit_entry,
    context_snapshot,
    create_event_entry,
    default_event_record,
    find_event_idx_by_id,
    last_event_for_email,
    load_rooms,
    tag_message,
    update_event_entry,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
import re
from ..llm.analysis import classify_intent, extract_user_information
from backend.workflows.nlu.preferences import extract_preferences
from backend.workflows.steps.step3_room_availability import handle_select_room_action
from ..billing_flow import handle_billing_capture
from backend.workflows.common.datetime_parse import parse_first_date, parse_time_range
from backend.services.products import list_product_records, merge_product_requests, normalise_product_payload
from backend.workflows.common.menu_options import DINNER_MENU_OPTIONS

__workflow_role__ = "trigger"


def _needs_vague_date_confirmation(user_info: Dict[str, Any]) -> bool:
    explicit_date = bool(user_info.get("event_date") or user_info.get("date"))
    vague_tokens = any(
        bool(user_info.get(key))
        for key in ("range_query_detected", "vague_month", "vague_weekday", "vague_time_of_day")
    )
    return vague_tokens and not explicit_date


def _initial_intent_detail(intent: IntentLabel) -> str:
    if intent == IntentLabel.EVENT_REQUEST:
        return "event_intake"
    if intent == IntentLabel.NON_EVENT:
        return "non_event"
    return intent.value


def _has_same_turn_shortcut(user_info: Dict[str, Any]) -> bool:
    participants = user_info.get("participants") or user_info.get("number_of_participants")
    date_value = user_info.get("date") or user_info.get("event_date")
    return bool(participants and date_value)


_DATE_TOKEN = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")
_MONTH_TOKENS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_AFFIRMATIVE_TOKENS = (
    "ok",
    "okay",
    "great",
    "sounds good",
    "lets do",
    "let's do",
    "we'll take",
    "lock",
    "confirm",
    "go with",
    "works",
    "take",
)

_PRODUCT_ADD_KEYWORDS = (
    "add",
    "include",
    "plus",
    "extra",
    "another",
    "additional",
    "also add",
    "bring",
    "upgrade",
)
_PRODUCT_REMOVE_KEYWORDS = (
    "remove",
    "without",
    "drop",
    "exclude",
    "skip",
    "no ",
    "minus",
    "cut",
)

_KEYWORD_REGEX_CACHE: Dict[str, re.Pattern[str]] = {}
_PRODUCT_TOKEN_REGEX_CACHE: Dict[str, re.Pattern[str]] = {}

def _menu_price_value(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        text = str(raw).lower().replace("chf", "").replace(" ", "")
        text = text.replace(",", "").strip()
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def _detect_menu_choice(message_text: str) -> Optional[Dict[str, Any]]:
    if not message_text:
        return None
    lowered = message_text.lower()
    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "")
        if not name:
            continue
        if name.lower() in lowered:
            price_value = _menu_price_value(menu.get("price"))
            return {
                "name": name,
                "price": price_value,
                "unit": "per_event",
                "month": menu.get("available_months"),
            }
    return None

def _fallback_year_from_ts(ts: Optional[str]) -> int:
    if not ts:
        return datetime.utcnow().year
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).year
    except ValueError:
        return datetime.utcnow().year


def _extract_confirmation_details(text: str, fallback_year: int) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    parsed = parse_first_date(text, fallback_year=fallback_year)
    iso_date = parsed.isoformat() if parsed else None
    start, end, _ = parse_time_range(text)

    def _fmt(value: Optional[time]) -> Optional[str]:
        if not value:
            return None
        return f"{value.hour:02d}:{value.minute:02d}"

    return iso_date, _fmt(start), _fmt(end)

def _looks_like_gate_confirmation(message_text: str, linked_event: Optional[Dict[str, Any]]) -> bool:
    if not linked_event:
        return False
    if linked_event.get("current_step") != 2:
        return False
    thread_state = (linked_event.get("thread_state") or "").lower()
    if thread_state not in {"awaiting client", "awaiting client response", "waiting on hil"}:
        return False

    text = (message_text or "").strip()
    if not text:
        return False
    lowered = text.lower()

    has_date_token = bool(_DATE_TOKEN.search(lowered))
    if not has_date_token:
        # handle formats like "07 feb" or "7 february"
        month_hit = any(token in lowered for token in _MONTH_TOKENS)
        day_hit = any(str(day) in lowered for day in range(1, 32))
        has_date_token = month_hit and day_hit

    if not has_date_token:
        return False

    if any(token in lowered for token in _AFFIRMATIVE_TOKENS):
        return True

    # plain date replies like "07.02.2026" or "2026-02-07"
    stripped_digits = lowered.replace(" ", "")
    if stripped_digits.replace(".", "").replace("-", "").replace("/", "").isdigit():
        return True

    # short replies with date plus punctuation
    if len(lowered.split()) <= 6 and has_date_token:
        return True

    return False


def _normalize_room_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _detect_room_choice(message_text: str, linked_event: Optional[Dict[str, Any]]) -> Optional[str]:
    if not message_text or not linked_event:
        return None
    try:
        current_step = int(linked_event.get("current_step") or 0)
    except (TypeError, ValueError):
        current_step = 0
    if current_step < 3:
        return None

    rooms = load_rooms()
    if not rooms:
        return None

    text = message_text.strip()
    if not text:
        return None
    lowered = text.lower()
    condensed = _normalize_room_token(text)

    # direct match against known room labels
    for room in rooms:
        room_lower = room.lower()
        if room_lower in lowered:
            return room
        if _normalize_room_token(room) and _normalize_room_token(room) == condensed:
            return room

    # pattern like "room a" or "room-a"
    match = re.search(r"\broom\s*([a-z0-9]+)\b", lowered)
    if match:
        token = match.group(1)
        token_norm = _normalize_room_token(token)
        for room in rooms:
            room_tokens = room.split()
            if room_tokens:
                last_token = _normalize_room_token(room_tokens[-1])
                if token_norm and token_norm == last_token:
                    return room

    # single token equals last token of room name (e.g., "A")
    if len(lowered.split()) == 1:
        token_norm = condensed
        if token_norm:
            for room in rooms:
                last_token = _normalize_room_token(room.split()[-1])
                if token_norm == last_token:
                    return room

    return None


def _participants_from_event(event_entry: Optional[Dict[str, Any]]) -> Optional[int]:
    if not event_entry:
        return None
    requirements = event_entry.get("requirements") or {}
    candidates = [
        requirements.get("number_of_participants"),
        (event_entry.get("event_data") or {}).get("Number of Participants"),
        (event_entry.get("captured") or {}).get("participants"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _keyword_regex(keyword: str) -> re.Pattern[str]:
    cached = _KEYWORD_REGEX_CACHE.get(keyword)
    if cached:
        return cached
    pattern = re.escape(keyword.strip())
    pattern = pattern.replace(r"\ ", r"\s+")
    regex = re.compile(rf"\b{pattern}\b")
    _KEYWORD_REGEX_CACHE[keyword] = regex
    return regex


def _contains_keyword(window: str, keywords: Tuple[str, ...]) -> bool:
    normalized = window.lower()
    for keyword in keywords:
        token = keyword.strip()
        if not token:
            continue
        if _keyword_regex(token).search(normalized):
            return True
    return False


def _product_token_regex(token: str) -> re.Pattern[str]:
    cached = _PRODUCT_TOKEN_REGEX_CACHE.get(token)
    if cached:
        return cached
    parts = re.split(r"[\s\-]+", token.strip())
    escaped_parts = [re.escape(part) for part in parts if part]
    if not escaped_parts:
        pattern = re.escape(token.strip())
    else:
        pattern = r"[\s\-]+".join(escaped_parts)
    regex = re.compile(rf"\b{pattern}\b")
    _PRODUCT_TOKEN_REGEX_CACHE[token] = regex
    return regex


def _match_product_token(text: str, token: str) -> Optional[int]:
    regex = _product_token_regex(token)
    match = regex.search(text)
    if match:
        return match.start()
    return None


def _extract_quantity_from_window(window: str, token: str) -> Optional[int]:
    escaped_token = re.escape(token.strip())
    pattern = re.compile(
        rf"(\d{{1,3}})\s*(?:x|times|pcs|pieces|units)?\s*(?:of\s+)?{escaped_token}s?",
        re.IGNORECASE,
    )
    match = pattern.search(window)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _menu_token_candidates(name: str) -> List[str]:
    """Return token variants to match a dinner menu mention in free text."""

    tokens: List[str] = []
    lowered = name.strip().lower()
    if not lowered:
        return tokens
    tokens.append(lowered)
    if not lowered.endswith("s"):
        tokens.append(f"{lowered}s")
    parts = lowered.split()
    if parts:
        last = parts[-1]
        if len(last) >= 3:
            tokens.append(last)
            if not last.endswith("s"):
                tokens.append(f"{last}s")
    return tokens


def _detect_product_update_request(
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
    linked_event: Optional[Dict[str, Any]],
) -> bool:
    subject = message_payload.get("subject") or ""
    body = message_payload.get("body") or ""
    text = f"{subject}\n{body}".strip().lower()
    if not text:
        return False

    participant_count = _participants_from_event(linked_event)
    existing_additions = user_info.get("products_add")
    existing_removals = user_info.get("products_remove")
    existing_ops = bool(existing_additions or existing_removals)
    additions: List[Dict[str, Any]] = []
    removals: List[str] = []
    catalog = list_product_records()

    for record in catalog:
        tokens: List[str] = []
        primary = (record.name or "").strip().lower()
        if primary:
            tokens.append(primary)
            if not primary.endswith("s"):
                tokens.append(f"{primary}s")
            # Also match the last word of the product name (e.g., "mic", "microphone")
            primary_parts = primary.split()
            if primary_parts:
                last_primary = primary_parts[-1]
                if len(last_primary) >= 3:
                    tokens.append(last_primary)
                    if not last_primary.endswith("s"):
                        tokens.append(f"{last_primary}s")
        for synonym in record.synonyms or []:
            synonym_token = str(synonym or "").strip().lower()
            if not synonym_token:
                continue
            tokens.append(synonym_token)
            if not synonym_token.endswith("s"):
                tokens.append(f"{synonym_token}s")
            # And the last word of each synonym (e.g., "mic")
            synonym_parts = synonym_token.split()
            if synonym_parts:
                last_syn = synonym_parts[-1]
                if len(last_syn) >= 3:
                    tokens.append(last_syn)
                    if not last_syn.endswith("s"):
                        tokens.append(f"{last_syn}s")
        matched_idx: Optional[int] = None
        matched_token: Optional[str] = None
        for token_candidate in tokens:
            idx = _match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue
        # Skip matches that occur inside parentheses; these are often explanatory
        # fragments (e.g., `covers "background music"`) rather than explicit
        # product selection signals.
        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue
        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]
        if _contains_keyword(window, _PRODUCT_REMOVE_KEYWORDS):
            removals.append(record.name)
            continue
        quantity = _extract_quantity_from_window(window, matched_token)
        add_signal = _contains_keyword(window, _PRODUCT_ADD_KEYWORDS)
        if add_signal or quantity:
            payload: Dict[str, Any] = {"name": record.name}
            if quantity:
                payload["quantity"] = quantity
            else:
                # Default to a single additional unit; downstream upsert increments existing quantity.
                payload["quantity"] = 1
            additions.append(payload)

    # Also detect dinner menu selections/removals so they behave like standard products.
    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "").strip()
        if not name:
            continue
        matched_idx: Optional[int] = None
        matched_token: Optional[str] = None
        for token_candidate in _menu_token_candidates(name):
            idx = _match_product_token(text, token_candidate)
            if idx is not None:
                matched_idx = idx
                matched_token = token_candidate
                break
        if matched_idx is None or matched_token is None:
            continue
        before = text[:matched_idx]
        if before.count("(") > before.count(")"):
            continue
        window_start = max(0, matched_idx - 80)
        window_end = min(len(text), matched_idx + len(matched_token) + 80)
        window = text[window_start:window_end]
        if _contains_keyword(window, _PRODUCT_REMOVE_KEYWORDS):
            removals.append(name)
            continue
        quantity = _extract_quantity_from_window(window, matched_token) or 1
        additions.append(
            {
                "name": name,
                "quantity": 1 if str(menu.get("unit") or "").strip().lower() == "per_event" else quantity,
                "unit_price": _menu_price_value(menu.get("price")),
                "unit": menu.get("unit") or "per_event",
                "category": "Catering",
                "wish": "menu",
            }
        )

    combined_additions: List[Dict[str, Any]] = []
    if existing_additions:
        combined_additions.extend(
            normalise_product_payload(existing_additions, participant_count=participant_count)
        )
    if additions:
        normalised = normalise_product_payload(additions, participant_count=participant_count)
        if normalised:
            combined_additions = (
                merge_product_requests(combined_additions, normalised) if combined_additions else normalised
            )
    if combined_additions:
        user_info["products_add"] = combined_additions

    combined_removals: List[str] = []
    removal_seen = set()
    if isinstance(existing_removals, list):
        for entry in existing_removals:
            name = entry.get("name") if isinstance(entry, dict) else entry
            text_name = str(name or "").strip()
            if text_name:
                lowered = text_name.lower()
                if lowered not in removal_seen:
                    removal_seen.add(lowered)
                    combined_removals.append(text_name)
    if removals:
        for name in removals:
            lowered = name.lower()
            if lowered not in removal_seen:
                removal_seen.add(lowered)
                combined_removals.append(name)
    if combined_removals:
        user_info["products_remove"] = combined_removals

    return bool(additions or removals or combined_additions or combined_removals or existing_ops)


def _normalize_quotes(text: str) -> str:
    """Normalize typographic apostrophes/quotes for downstream keyword checks."""

    if not text:
        return ""
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
    )


def _looks_like_offer_acceptance(text: str) -> bool:
    """
    Heuristic: short, declarative acknowledgements without question marks that contain approval verbs.
    """

    if not text:
        return False
    normalized = _normalize_quotes(text).lower()
    if "?" in normalized:
        return False
    if len(normalized) > 200:
        return False

    accept_re = re.compile(
        r"\b("
        r"accept(?:ed)?|"
        r"approv(?:e|ed|al)|"
        r"confirm(?:ed)?|"
        r"proceed|continue|go ahead|"
        r"send (?:it|to client)|please send|ok to send|"
        r"all good|looks good|sounds good|good to go|"
        r"(?:that'?s|thats) fine|fine for me"
        r")\b"
    )
    if accept_re.search(normalized):
        return True

    # Fallback to legacy tokens for odd phrasing.
    accept_tokens = (
        "accept",
        "accepted",
        "confirm",
        "confirmed",
        "approve",
        "approved",
        "continue",
        "please send",
        "send it",
        "send to client",
        "ok to send",
        "go ahead",
        "proceed",
        "that's fine",
        "thats fine",
        "fine for me",
        "sounds good",
        "good to go",
        "ok thats fine",
        "ok that's fine",
        "all good",
    )
    return any(token in normalized for token in accept_tokens)


def _resolve_owner_step(step_num: int) -> str:
    mapping = {
        1: "Step1_Intake",
        2: "Step2_Date",
        3: "Step3_Room",
        4: "Step4_Offer",
        5: "Step5_Negotiation",
        6: "Step6_Transition",
        7: "Step7_Confirmation",
    }
    return mapping.get(step_num, f"Step{step_num}")


@trace_step("Step1_Intake")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""

    message_payload = state.message.to_payload()
    thread_id = _thread_id(state)

    # Resolve owner step for tracing based on existing conversation state
    email = (message_payload.get("from_email") or "").lower()
    linked_event = last_event_for_email(state.db, email) if email else None
    current_step = linked_event.get("current_step") if linked_event else 1
    # Fallback if current_step is None/invalid
    if not isinstance(current_step, int):
        current_step = 1
    owner_step = _resolve_owner_step(current_step)

    # [TESTING CONVENIENCE] When in dev/test mode, offer choice to continue or reset
    # This helps with testing by not auto-continuing stale sessions
    # Skip if message has skip_dev_choice flag (user already chose to continue)
    dev_test_mode = os.getenv("DEV_TEST_MODE", "").lower() in ("1", "true", "yes")
    skip_dev_choice = state.extras.get("skip_dev_choice", False)
    if dev_test_mode and linked_event and current_step > 1 and not skip_dev_choice:
        event_id = linked_event.get("event_id")
        event_date = linked_event.get("chosen_date") or (linked_event.get("event_data") or {}).get("Event Date", "unknown")
        locked_room = linked_event.get("locked_room_id") or "none"
        offer_accepted = bool(linked_event.get("offer_accepted"))

        return GroupResult(
            action="dev_choice_required",
            payload={
                "client_id": email,
                "event_id": event_id,
                "current_step": current_step,
                "step_name": owner_step,
                "event_date": event_date,
                "locked_room": locked_room,
                "offer_accepted": offer_accepted,
                "options": [
                    {"id": "continue", "label": f"Continue at {owner_step}"},
                    {"id": "reset", "label": "Reset client (delete all data)"},
                ],
                "message": f"Existing event detected for {email} at {owner_step}. Date: {event_date}, Room: {locked_room}",
            },
            halt=True,
        )

    trace_marker(
        thread_id,
        "TRIGGER_Intake",
        detail=message_payload.get("subject"),
        data={"msg_id": state.message.msg_id},
        owner_step=owner_step,
    )
    prompt_payload = (
        f"Subject: {message_payload.get('subject') or ''}\n"
        f"Body:\n{message_payload.get('body') or ''}"
    )
    trace_prompt_in(thread_id, owner_step, "classify_intent", prompt_payload)
    intent, confidence = classify_intent(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "classify_intent",
        json.dumps({"intent": intent.value, "confidence": round(confidence, 3)}, ensure_ascii=False),
        outputs={"intent": intent.value, "confidence": round(confidence, 3)},
    )
    trace_marker(
        thread_id,
        "AGENT_CLASSIFY",
        detail=intent.value,
        data={"confidence": round(confidence, 3)},
        owner_step=owner_step,
    )
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = _initial_intent_detail(intent)

    trace_prompt_in(thread_id, owner_step, "extract_user_information", prompt_payload)
    user_info = extract_user_information(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "extract_user_information",
        json.dumps(user_info, ensure_ascii=False),
        outputs=user_info,
    )
    # [REGEX FALLBACK] If LLM failed to extract date, try regex parsing
    # This handles cases like "February 14th, 2026" that LLM might miss
    if not user_info.get("date") and not user_info.get("event_date"):
        body_text = message_payload.get("body") or ""
        fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
        parsed_date = parse_first_date(body_text, fallback_year=fallback_year)
        if parsed_date:
            user_info["date"] = parsed_date.isoformat()
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(parsed_date.isoformat())
            print(f"[Step1] Regex fallback extracted date: {parsed_date.isoformat()}")
            # Boost confidence if we found date via regex - indicates valid event request
            if intent == IntentLabel.EVENT_REQUEST and confidence < 0.90:
                confidence = 0.90
                state.confidence = confidence
                print(f"[Step1] Boosted confidence to {confidence} due to regex date extraction")
    # Preserve raw message content for downstream semantic extraction.
    needs_vague_date_confirmation = _needs_vague_date_confirmation(user_info)
    if needs_vague_date_confirmation:
        user_info.pop("event_date", None)
        user_info.pop("date", None)
    raw_pref_text = "\n".join(
        [
            message_payload.get("subject") or "",
            message_payload.get("body") or "",
        ]
    ).strip()
    preferences = extract_preferences(user_info, raw_text=raw_pref_text or None)
    if preferences:
        user_info["preferences"] = preferences
    if intent == IntentLabel.EVENT_REQUEST and _has_same_turn_shortcut(user_info):
        state.intent_detail = "event_intake_shortcut"
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")
    _trace_user_entities(state, message_payload, user_info, owner_step)

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    # linked_event is already fetched above
    body_text_raw = message_payload.get("body") or ""
    body_text = _normalize_quotes(body_text_raw)
    fallback_year = _fallback_year_from_ts(message_payload.get("ts"))

    confirmation_detected = False
    if (
        linked_event
        and not user_info.get("date")
        and not user_info.get("event_date")
        and _looks_like_gate_confirmation(body_text, linked_event)
    ):
        iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year)
        if iso_date:
            user_info["date"] = iso_date
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
            confirmation_detected = True
        if start_time and "start_time" not in user_info:
            user_info["start_time"] = start_time
        if end_time and "end_time" not in user_info:
            user_info["end_time"] = end_time
    # Capture short acceptances on existing offers to avoid manual-review loops.
    acceptance_detected = linked_event and _looks_like_offer_acceptance(body_text)
    if acceptance_detected:
        intent = IntentLabel.EVENT_REQUEST
        confidence = max(confidence, 0.99)
        state.intent = intent
        state.confidence = confidence
        if state.intent_detail in (None, "intake"):
            state.intent_detail = "event_intake_negotiation_accept"
        # Always route acceptances through HIL so the manager can approve/decline before confirmation.
        target_step = max(linked_event.get("current_step") or 0, 5)
        user_info.setdefault("hil_approve_step", target_step)
        update_event_metadata(
            linked_event,
            current_step=target_step,
            thread_state="Waiting on HIL",
            caller_step=None,
        )
        state.extras["persist"] = True
    # Early room-choice detection so we don't rely on classifier confidence
    early_room_choice = _detect_room_choice(body_text, linked_event)
    if early_room_choice:
        user_info["room"] = early_room_choice
        user_info["_room_choice_detected"] = True
        state.extras["room_choice_selected"] = early_room_choice
        # Bump confidence to prevent Step 3 nonsense gate from triggering HIL
        confidence = 1.0
        intent = IntentLabel.EVENT_REQUEST
        state.intent = intent
        state.confidence = confidence

    # Capture explicit menu selection (e.g., "Room E with Seasonal Garden Trio")
    menu_choice = _detect_menu_choice(body_text)
    if menu_choice:
        user_info["menu_choice"] = menu_choice["name"]
        participants = _participants_from_event(linked_event) or user_info.get("participants")
        try:
            participants = int(participants) if participants is not None else None
        except (TypeError, ValueError):
            participants = None
        if menu_choice.get("price"):
            product_payload = {
                "name": menu_choice["name"],
                "quantity": 1 if menu_choice.get("unit") == "per_event" else (participants or 1),
                "unit_price": menu_choice["price"],
                "unit": menu_choice.get("unit") or "per_event",
                "category": "Catering",
                "wish": "menu",
            }
            existing = user_info.get("products_add") or []
            if isinstance(existing, list):
                user_info["products_add"] = existing + [product_payload]
            else:
                user_info["products_add"] = [product_payload]

    product_update_detected = _detect_product_update_request(message_payload, user_info, linked_event)
    if product_update_detected:
        state.extras["product_update_detected"] = True
        if not is_event_request(intent):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_product_update"
        elif state.intent_detail in (None, "intake", "event_intake"):
            state.intent_detail = "event_intake_product_update"
    state.user_info = user_info
    append_history(client, message_payload, intent.value, confidence, user_info)

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    # [SKIP MANUAL REVIEW FOR EXISTING EVENTS]
    # If there's an existing event at step > 1, we should NOT do "is this an event?"
    # classification. These messages should flow through to the step-specific handlers
    # which have their own logic for handling detours, Q&A, confirmations, etc.
    skip_manual_review_check = linked_event and linked_event.get("current_step", 1) > 1

    if not skip_manual_review_check and (not is_event_request(intent) or confidence < 0.85):
        body_text = message_payload.get("body") or ""
        awaiting_billing = linked_event and (linked_event.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        if awaiting_billing:
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_billing_update"
            if body_text.strip() and _looks_like_billing_fragment(body_text):
                user_info["billing_address"] = body_text.strip()
        elif _looks_like_gate_confirmation(body_text, linked_event):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.95)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_followup"
            fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
            iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year)
            if iso_date:
                user_info["date"] = iso_date
                user_info["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
            if start_time:
                user_info["start_time"] = start_time
            if end_time:
                user_info["end_time"] = end_time
        else:
            room_choice = _detect_room_choice(body_text, linked_event)
            if room_choice:
                intent = IntentLabel.EVENT_REQUEST
                confidence = max(confidence, 0.96)
                state.intent = intent
                state.confidence = confidence
                state.intent_detail = "event_intake_room_choice"
                user_info["room"] = room_choice
                user_info["_room_choice_detected"] = True
                state.extras["room_choice_selected"] = room_choice
                # Only lock immediately if no room is currently locked; otherwise let Step 3 handle a switch.
                if linked_event:
                    locked = linked_event.get("locked_room_id")
                    if not locked:
                        req_hash = linked_event.get("requirements_hash")
                        update_event_metadata(
                            linked_event,
                            locked_room_id=room_choice,
                            room_eval_hash=req_hash,
                            room_status="Available",
                            caller_step=None,
                        )
            else:
                if _looks_like_billing_fragment(body_text):
                    intent = IntentLabel.EVENT_REQUEST
                    confidence = max(confidence, 0.92)
                    state.intent = intent
                    state.confidence = confidence
                    state.intent_detail = "event_intake_billing_capture"
                    user_info["billing_address"] = body_text.strip()
                if not is_event_request(intent) or confidence < 0.85:
                    trace_marker(
                        thread_id,
                        "CONDITIONAL_HIL",
                        detail="manual_review_required",
                        data={"intent": intent.value, "confidence": round(confidence, 3)},
                        owner_step=owner_step,
                    )
                    linked_event_id = linked_event.get("event_id") if linked_event else None
                    task_payload: Dict[str, Any] = {
                        "subject": message_payload.get("subject"),
                        "snippet": (message_payload.get("body") or "")[:200],
                        "ts": message_payload.get("ts"),
                        "reason": "manual_review_required",
                        "thread_id": thread_id,
                    }
                    task_id = enqueue_manual_review_task(
                        state.db,
                        state.client_id,
                        linked_event_id,
                        task_payload,
                    )
                    state.extras.update({"task_id": task_id, "persist": True})
                    clarification = (
                        "Thanks for your message. A member of our team will review it shortly "
                        "to make sure it reaches the right place."
                    )
                    clarification = append_footer(
                        clarification,
                        step=1,
                        next_step="Team review (HIL)",
                        thread_state="Waiting on HIL",
                    )
                    state.add_draft_message(
                        {
                            "body": clarification,
                            "step": 1,
                            "topic": "manual_review",
                        }
                    )
                    state.set_thread_state("Waiting on HIL")
                    if os.getenv("OE_DEBUG") == "1":
                        print(
                            "[DEBUG] manual_review_enqueued:",
                            f"conf={confidence:.2f}",
                            f"parsed_date={user_info.get('date')}",
                            f"intent={intent.value}",
                        )
                    payload = {
                        "client_id": state.client_id,
                        "event_id": linked_event_id,
                        "intent": intent.value,
                        "confidence": round(confidence, 3),
                        "persisted": True,
                        "task_id": task_id,
                        "user_info": user_info,
                        "context": context,
                        "draft_messages": state.draft_messages,
                        "thread_state": state.thread_state,
                    }
                    return GroupResult(action="manual_review_enqueued", payload=payload, halt=True)

    event_entry = _ensure_event_record(state, message_payload, user_info)
    if event_entry.get("pending_hil_requests"):
        event_entry["pending_hil_requests"] = []
        state.extras["persist"] = True

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True
    handle_billing_capture(state, event_entry)
    menu_choice_name = user_info.get("menu_choice")
    if menu_choice_name:
        catering_list = event_entry.setdefault("selected_catering", [])
        if menu_choice_name not in catering_list:
            catering_list.append(menu_choice_name)
            event_entry.setdefault("event_data", {})["Catering Preference"] = menu_choice_name
            state.extras["persist"] = True
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    requirements_snapshot = event_entry.get("requirements") or {}

    def _needs_fallback(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return len(value) == 0
        return False

    if _needs_fallback(user_info.get("participants")) and requirements_snapshot.get("number_of_participants") is not None:
        user_info["participants"] = requirements_snapshot.get("number_of_participants")

    snapshot_layout = requirements_snapshot.get("seating_layout")
    if snapshot_layout:
        if _needs_fallback(user_info.get("layout")):
            user_info["layout"] = snapshot_layout
        if _needs_fallback(user_info.get("type")):
            user_info["type"] = snapshot_layout

    duration_snapshot = requirements_snapshot.get("event_duration")
    if isinstance(duration_snapshot, dict):
        if _needs_fallback(user_info.get("start_time")) and duration_snapshot.get("start"):
            user_info["start_time"] = duration_snapshot.get("start")
        if _needs_fallback(user_info.get("end_time")) and duration_snapshot.get("end"):
            user_info["end_time"] = duration_snapshot.get("end")

    snapshot_notes = requirements_snapshot.get("special_requirements")
    if snapshot_notes and _needs_fallback(user_info.get("notes")):
        user_info["notes"] = snapshot_notes

    snapshot_room = requirements_snapshot.get("preferred_room")
    if snapshot_room and _needs_fallback(user_info.get("room")):
        user_info["room"] = snapshot_room

    requirements = build_requirements(user_info)
    new_req_hash = requirements_hash(requirements)
    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    preferences = user_info.get("preferences") or {}
    wish_products = list((preferences.get("wish_products") or []))
    vague_month = user_info.get("vague_month")
    vague_weekday = user_info.get("vague_weekday")
    vague_time = user_info.get("vague_time_of_day")
    week_index = user_info.get("week_index")
    weekdays_hint = user_info.get("weekdays_hint")
    window_scope = user_info.get("window") if isinstance(user_info.get("window"), dict) else None
    metadata_updates: Dict[str, Any] = {}
    if wish_products:
        metadata_updates["wish_products"] = wish_products
    if preferences:
        metadata_updates["preferences"] = preferences
    if vague_month:
        metadata_updates["vague_month"] = vague_month
    if vague_weekday:
        metadata_updates["vague_weekday"] = vague_weekday
    if vague_time:
        metadata_updates["vague_time_of_day"] = vague_time
    if week_index:
        metadata_updates["week_index"] = week_index
    if weekdays_hint:
        metadata_updates["weekdays_hint"] = list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else weekdays_hint
    if window_scope:
        metadata_updates["window_scope"] = {
            key: value
            for key, value in window_scope.items()
            if key in {"month", "week_index", "weekdays_hint"}
        }
    if metadata_updates:
        update_event_metadata(event_entry, **metadata_updates)

    room_choice_selected = state.extras.pop("room_choice_selected", None)
    if room_choice_selected:
        pending_info = event_entry.get("room_pending_decision") or {}
        selected_status = None
        if isinstance(pending_info, dict) and pending_info.get("selected_room") == room_choice_selected:
            selected_status = pending_info.get("selected_status")
        status_value = selected_status or "Available"
        chosen_date = (
            event_entry.get("chosen_date")
            or user_info.get("event_date")
            or user_info.get("date")
        )
        update_event_metadata(
            event_entry,
            locked_room_id=room_choice_selected,
            room_status=status_value,
            room_eval_hash=event_entry.get("requirements_hash"),
            caller_step=None,
            current_step=4,
            thread_state="Awaiting Client",
        )
        event_entry.setdefault("event_data", {})["Preferred Room"] = room_choice_selected
        append_audit_entry(event_entry, state.current_step or 1, 4, "room_choice_captured")
        state.current_step = 4
        state.caller_step = None
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": intent.value,
            "confidence": round(confidence, 3),
            "locked_room_id": room_choice_selected,
            "thread_state": state.thread_state,
            "persisted": True,
        }
        return GroupResult(action="room_choice_captured", payload=payload, halt=False)

    new_preferred_room = requirements.get("preferred_room")

    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1
    detoured_to_step2 = False

    # Use centralized change propagation system for systematic change detection and routing
    # Enhanced detection with dual-condition logic (revision signal + bound target)
    # Skip change detection during billing flow - billing addresses shouldn't trigger date/room changes
    in_billing_flow = (
        event_entry.get("offer_accepted")
        and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    message_text = (state.message.subject or "") + "\n" + (state.message.body or "")
    if in_billing_flow:
        # In billing flow, don't detect changes - just continue with billing capture
        change_type = None
    else:
        enhanced_result = detect_change_type_enhanced(event_entry, user_info, message_text=message_text)
        change_type = enhanced_result.change_type if enhanced_result.is_change else None

    if needs_vague_date_confirmation and not in_billing_flow:
        event_entry["range_query_detected"] = True
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
            thread_state="Awaiting Client Response",
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_pending_vague_request")
        detoured_to_step2 = True
        state.set_thread_state("Awaiting Client Response")

    # Handle change routing using DAG-based change propagation
    if change_type is not None and previous_step > 1:
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)

        # Apply the routing decision
        if decision.updated_caller_step is not None and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)
            trace_marker(
                _thread_id(state),
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": previous_step,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                },
                owner_step="Step1_Intake",
            )

        if decision.next_step != previous_step:
            update_event_metadata(event_entry, current_step=decision.next_step)
            audit_reason = f"{change_type.value}_change_detected"
            append_audit_entry(event_entry, previous_step, decision.next_step, audit_reason)

            # Clear room lock for date/requirements changes
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                        locked_room_id=None,
                    )
                    detoured_to_step2 = True

    # Fallback: legacy logic for cases not handled by change propagation
    # Skip during billing flow - billing addresses shouldn't trigger date changes
    elif new_date and new_date != event_entry.get("chosen_date") and not in_billing_flow:
        if (
            previous_step not in (None, 1, 2)
            and event_entry.get("caller_step") is None
        ):
            update_event_metadata(event_entry, caller_step=previous_step)
        if previous_step <= 1:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=True,
                current_step=3,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 3, "date_updated_initial")
            detoured_to_step2 = False
        else:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=False,
                current_step=2,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 2, "date_updated")
            detoured_to_step2 = True

    # Handle missing date (initial flow, not a change)
    if needs_vague_date_confirmation:
        new_date = None
    if not new_date and not event_entry.get("chosen_date") and change_type is None:
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_missing")
        detoured_to_step2 = True

    # Fallback: requirements change detection (legacy)
    if prev_req_hash is not None and prev_req_hash != new_req_hash and not detoured_to_step2 and change_type is None:
        target_step = 3
        if previous_step != target_step and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=previous_step)
            update_event_metadata(event_entry, current_step=target_step)
            append_audit_entry(event_entry, previous_step, target_step, "requirements_updated")
            # Clear stale negotiation state - old offer no longer valid after requirements change
            event_entry.pop("negotiation_pending_decision", None)

    # Fallback: room change detection (legacy)
    # Skip room change detection if in billing flow - billing addresses shouldn't trigger room changes
    in_billing_flow = (
        event_entry.get("offer_accepted")
        and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    if new_preferred_room and new_preferred_room != event_entry.get("locked_room_id") and change_type is None:
        if not detoured_to_step2 and not in_billing_flow:
            prev_step_for_room = event_entry.get("current_step") or previous_step
            if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
                update_event_metadata(event_entry, caller_step=prev_step_for_room)
                update_event_metadata(event_entry, current_step=3)
                append_audit_entry(event_entry, prev_step_for_room, 3, "room_preference_updated")

    tag_message(event_entry, message_payload.get("msg_id"))

    if not event_entry.get("thread_state"):
        update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": intent.value,
        "confidence": round(confidence, 3),
        "user_info": user_info,
        "context": context,
        "persisted": True,
        "current_step": event_entry.get("current_step"),
        "caller_step": event_entry.get("caller_step"),
        "thread_state": event_entry.get("thread_state"),
        "draft_messages": state.draft_messages,
    }
    trace_state(
        _thread_id(state),
        "Step1_Intake",
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "current_step": event_entry.get("current_step"),
            "caller_step": event_entry.get("caller_step"),
            "thread_state": event_entry.get("thread_state"),
        },
    )
    return GroupResult(action="intake_complete", payload=payload)


def _ensure_event_record(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """[Trigger] Create or refresh the event record for the intake step."""

    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    event_data = default_event_record(user_info, message_payload, received_date)

    last_event = last_event_for_email(state.db, state.client_id)
    if not last_event:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    # Check if we should create a NEW event instead of reusing the existing one
    # This happens when:
    # 1. The new message has a DIFFERENT event date than the existing event (new inquiry)
    # 2. The existing event is in a terminal state (Confirmed, site visit scheduled)
    should_create_new = False
    new_event_date = event_data.get("Event Date")
    existing_event_date = last_event.get("chosen_date") or (last_event.get("event_data") or {}).get("Event Date")

    # Different dates = new inquiry, but ONLY if BOTH dates are actual dates
    # (not "Not specified" default value)
    placeholder_values = ("Not specified", "not specified", None, "")
    new_date_is_actual = new_event_date and new_event_date not in placeholder_values
    existing_date_is_actual = existing_event_date and existing_event_date not in placeholder_values
    if new_date_is_actual and existing_date_is_actual and new_event_date != existing_event_date:
        should_create_new = True
        trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
            "reason": "different_date",
            "new_date": new_event_date,
            "existing_date": existing_event_date,
        })

    # Terminal states - don't reuse
    existing_status = last_event.get("status", "").lower()
    if existing_status in ("confirmed", "completed", "cancelled"):
        should_create_new = True
        trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
            "reason": "terminal_status",
            "status": existing_status,
        })

    # Offer already accepted - this event is essentially complete
    # UNLESS the client is still providing billing/deposit info for the accepted offer
    # In that case, we should continue the existing flow, not start fresh
    if last_event.get("offer_accepted"):
        # Check if this is a continuation of the accepted offer flow
        billing_reqs = last_event.get("billing_requirements") or {}
        awaiting_billing = billing_reqs.get("awaiting_billing_for_accept", False)
        deposit_state = last_event.get("deposit_state") or {}
        awaiting_deposit = deposit_state.get("required") and not deposit_state.get("paid")

        # Also check if the message looks like billing info (address, postal code, etc.)
        message_body = (state.message.body or "").strip().lower()
        looks_like_billing = _looks_like_billing_fragment(message_body) if message_body else False

        # Only create new event if this is truly a NEW inquiry, not a billing/deposit follow-up
        if awaiting_billing or awaiting_deposit or looks_like_billing:
            # Continue with existing event - don't create new
            trace_db_write(_thread_id(state), "Step1_Intake", "offer_accepted_continue", {
                "reason": "billing_or_deposit_followup",
                "awaiting_billing": awaiting_billing,
                "awaiting_deposit": awaiting_deposit,
                "looks_like_billing": looks_like_billing,
            })
        else:
            # New inquiry from same client after offer was accepted - create fresh event
            should_create_new = True
            trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
                "reason": "offer_already_accepted",
                "event_id": last_event.get("event_id"),
            })

    # Site visit in progress or scheduled - don't reuse for new inquiries
    # When site_visit_state.status is "proposed" or "scheduled", the event is mid-process
    visit_state = last_event.get("site_visit_state") or {}
    if visit_state.get("status") in ("proposed", "scheduled"):
        should_create_new = True
        trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
            "reason": f"site_visit_{visit_state.get('status')}",
        })

    if should_create_new:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {
            "event_id": event_entry.get("event_id"),
            "reason": "new_inquiry_detected",
        })
        return event_entry

    idx = find_event_idx_by_id(state.db, last_event["event_id"])
    if idx is None:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        # Store thread_id so tasks can be filtered by session in frontend
        event_entry["thread_id"] = _thread_id(state)
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    state.updated_fields = update_event_entry(state.db, idx, event_data)
    event_entry = state.db["events"][idx]
    # Ensure thread_id is set for backward compatibility with existing events
    if not event_entry.get("thread_id"):
        event_entry["thread_id"] = _thread_id(state)
    trace_db_write(
        _thread_id(state),
        "Step1_Intake",
        "db.events.update",
        {"event_id": event_entry.get("event_id"), "updated": list(state.updated_fields)},
    )
    update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
    return event_entry


def _looks_like_billing_fragment(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("room "):
        return False
    keywords = ("postal", "postcode", "zip", "street", "avenue", "road", "switzerland", " ch", "city", "country")
    if any(k in lowered for k in keywords):
        return True
    digit_groups = sum(1 for token in lowered.replace(",", " ").split() if token.isdigit() and len(token) >= 3)
    return digit_groups >= 1


def _trace_user_entities(state: WorkflowState, message_payload: Dict[str, Any], user_info: Dict[str, Any], owner_step: str) -> None:
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
    if email:
        trace_entity(thread_id, owner_step, "email", "message_header", True, {"value": email})

    event_date = user_info.get("event_date") or user_info.get("date")
    if event_date:
        trace_entity(thread_id, owner_step, "event_date", "llm", True, {"value": event_date})

    participants = user_info.get("participants") or user_info.get("number_of_participants")
    if participants:
        trace_entity(thread_id, owner_step, "participants", "llm", True, {"value": participants})


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
