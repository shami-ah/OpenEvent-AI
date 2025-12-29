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
from backend.detection.keywords.buckets import has_revision_signal
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
from ..billing_flow import handle_billing_capture
from backend.workflows.common.datetime_parse import parse_first_date
from backend.services.products import list_product_records, merge_product_requests, normalise_product_payload
from backend.workflows.common.menu_options import DINNER_MENU_OPTIONS

# Extracted pure helpers (I1 refactoring)
from .normalization import normalize_quotes as _normalize_quotes
from .normalization import normalize_room_token as _normalize_room_token
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from .gate_confirmation import looks_like_offer_acceptance as _looks_like_offer_acceptance
from .gate_confirmation import looks_like_billing_fragment as _looks_like_billing_fragment


def _extract_billing_from_body(body: str) -> Optional[str]:
    """
    Extract billing address from message body if it contains billing info.

    Handles cases where billing is embedded in a larger message (e.g., event request
    that also includes billing address).

    Returns the extracted billing portion, or None if no billing info found.
    """
    if not body or not body.strip():
        return None

    # Check for explicit billing section markers
    billing_markers = [
        r"(?:our\s+)?billing\s+address(?:\s+is)?[:\s]*",
        r"(?:our\s+)?address(?:\s+is)?[:\s]*",
        r"invoice\s+(?:to|address)[:\s]*",
        r"send\s+invoice\s+to[:\s]*",
    ]

    for pattern in billing_markers:
        match = re.search(pattern + r"(.+?)(?:\n\n|Best|Kind|Thank|Regards|$)", body, re.IGNORECASE | re.DOTALL)
        if match:
            billing_text = match.group(1).strip()
            # Validate it looks like an address (has street/postal)
            if _looks_like_billing_fragment(billing_text):
                return billing_text

    # Fallback: check if message contains billing keywords but no explicit marker
    # Only extract if it looks like a complete address
    if _looks_like_billing_fragment(body):
        # Try to find a multi-line address block
        lines = body.split("\n")
        address_lines = []
        in_address = False

        for line in lines:
            line = line.strip()
            if not line:
                if in_address and len(address_lines) >= 2:
                    break  # End of address block
                continue

            # Check if line looks like address part (has postal code, street number, or company name)
            has_postal = re.search(r"\b\d{4,6}\b", line)
            has_street_num = re.search(r"\d+\w*\s*$|\s\d+\s", line)
            is_company = bool(re.search(r"\b(gmbh|ag|ltd|inc|corp|llc|sarl|sa)\b", line, re.IGNORECASE))
            is_city_country = bool(re.search(r"\b(zurich|zürich|geneva|bern|basel|switzerland|schweiz)\b", line, re.IGNORECASE))

            if has_postal or has_street_num or is_company or is_city_country:
                in_address = True
                address_lines.append(line)
            elif in_address:
                # Continue adding lines until we hit something that's clearly not address
                if len(line) < 50 and not re.search(r"\b(hello|hi|dear|please|thank|we|i am|looking)\b", line, re.IGNORECASE):
                    address_lines.append(line)
                else:
                    break

        if len(address_lines) >= 2:
            return "\n".join(address_lines)

    return None

# I1 Phase 1: Intent helpers
from .intent_helpers import (
    needs_vague_date_confirmation as _needs_vague_date_confirmation,
    initial_intent_detail as _initial_intent_detail,
    has_same_turn_shortcut as _has_same_turn_shortcut,
    resolve_owner_step as _resolve_owner_step,
)

# I1 Phase 1: Keyword matching
from .keyword_matching import (
    PRODUCT_ADD_KEYWORDS as _PRODUCT_ADD_KEYWORDS,
    PRODUCT_REMOVE_KEYWORDS as _PRODUCT_REMOVE_KEYWORDS,
    keyword_regex as _keyword_regex,
    contains_keyword as _contains_keyword,
    product_token_regex as _product_token_regex,
    match_product_token as _match_product_token,
    extract_quantity_from_window as _extract_quantity_from_window,
    menu_token_candidates as _menu_token_candidates,
)

# I1 Phase 1: Confirmation parsing
from .confirmation_parsing import (
    DATE_TOKEN as _DATE_TOKEN,
    MONTH_TOKENS as _MONTH_TOKENS,
    AFFIRMATIVE_TOKENS as _AFFIRMATIVE_TOKENS,
    extract_confirmation_details as _extract_confirmation_details,
    looks_like_gate_confirmation as _looks_like_gate_confirmation,
)

# I1 Phase 2: Room detection
from .room_detection import detect_room_choice as _detect_room_choice

# I1 Phase 2: Product detection
from .product_detection import (
    menu_price_value as _menu_price_value,
    detect_menu_choice as _detect_menu_choice,
)

# I1 Phase 2: Entity extraction
from .entity_extraction import participants_from_event as _participants_from_event

# Dev/test mode helper (I2 refactoring)
from .dev_test_mode import maybe_show_dev_choice as _maybe_show_dev_choice

__workflow_role__ = "trigger"


# NOTE: _detect_product_update_request kept here as it has side effects (mutates user_info)
# and DB dependencies - candidate for future refactoring to return tuple instead of mutating
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

    # [TESTING CONVENIENCE] Dev/test mode choice prompt (I2 extraction)
    skip_dev_choice = state.extras.get("skip_dev_choice", False)
    dev_choice_result = _maybe_show_dev_choice(
        linked_event=linked_event,
        current_step=current_step,
        owner_step=owner_step,
        client_email=email,
        skip_dev_choice=skip_dev_choice,
    )
    if dev_choice_result:
        return dev_choice_result

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

    # Extract billing from message body if not already captured
    # This allows billing to be captured even from event requests that include billing info
    if not user_info.get("billing_address"):
        body_text = message_payload.get("body") or ""
        extracted_billing = _extract_billing_from_body(body_text)
        if extracted_billing:
            user_info["billing_address"] = extracted_billing
            trace_entity(thread_id, owner_step, "billing_address", extracted_billing[:100], True)

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
        existing_lock = event_entry.get("locked_room_id")
        # If a different room is already locked, DON'T update the lock here.
        # Let the normal workflow continue so change detection can route to Step 3.
        if existing_lock and existing_lock != room_choice_selected:
            print(f"[Step1] Room change detected: {existing_lock} → {room_choice_selected}, skipping room_choice_captured")
            # Don't return here - let the normal flow continue with change detection
            # The user_info["room"] is already set, so detect_change_type_enhanced will find it
        else:
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
    # BUG FIX: Only use message body for change detection, NOT subject.
    # The subject contains system-generated timestamps (e.g., "Client follow-up (2025-12-24 17:18)")
    # which were incorrectly triggering DATE change detection.
    message_text = state.message.body or ""
    if in_billing_flow:
        # In billing flow, don't detect changes - just continue with billing capture
        change_type = None
    else:
        enhanced_result = detect_change_type_enhanced(event_entry, user_info, message_text=message_text)
        change_type = enhanced_result.change_type if enhanced_result.is_change else None
        print(f"[Step1][CHANGE_DETECT] user_info.date={user_info.get('date')}, user_info.event_date={user_info.get('event_date')}")
        print(f"[Step1][CHANGE_DETECT] is_change={enhanced_result.is_change}, change_type={change_type}")
        print(f"[Step1][CHANGE_DETECT] message_text={message_text[:100] if message_text else 'None'}...")

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

            # Handle room lock based on change type
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    if change_type.value == "date":
                        # DATE change to Step 2: KEEP locked_room_id so Step 3 can fast-skip
                        # if the room is still available on the new date
                        update_event_metadata(
                            event_entry,
                            date_confirmed=False,
                            room_eval_hash=None,  # Invalidate for re-verification
                            # NOTE: Do NOT clear locked_room_id for date changes
                        )
                    else:
                        # REQUIREMENTS change to Step 2: clear room lock since room may no longer fit
                        update_event_metadata(
                            event_entry,
                            date_confirmed=False,
                            room_eval_hash=None,
                            locked_room_id=None,
                        )
                    detoured_to_step2 = True
                elif decision.next_step == 3:
                    # Going to Step 3 for requirements change: clear room lock but KEEP date confirmed
                    update_event_metadata(
                        event_entry,
                        room_eval_hash=None,
                        locked_room_id=None,
                    )

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
    # (not "Not specified" default value) AND there's no DATE CHANGE intent
    placeholder_values = ("Not specified", "not specified", None, "")
    new_date_is_actual = new_event_date and new_event_date not in placeholder_values
    existing_date_is_actual = existing_event_date and existing_event_date not in placeholder_values

    # Check if this is a DATE CHANGE request vs a NEW inquiry
    # Date changes have revision signals ("change", "switch", "actually", "instead", etc.)
    message_text = (state.message.body or "") + " " + (state.message.subject or "")
    is_date_change_request = has_revision_signal(message_text)

    if new_date_is_actual and existing_date_is_actual and new_event_date != existing_event_date:
        if is_date_change_request:
            # This is a date CHANGE on existing event - don't create new event
            trace_db_write(_thread_id(state), "Step1_Intake", "date_change_detected", {
                "reason": "date_change_request",
                "old_date": existing_event_date,
                "new_date": new_event_date,
            })
            # Don't set should_create_new = True; continue with existing event
        else:
            # This is a genuine NEW inquiry with a different date
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
        # FIX: Use correct field name (deposit_info, not deposit_state)
        deposit_info = last_event.get("deposit_info") or {}
        awaiting_deposit = deposit_info.get("deposit_required") and not deposit_info.get("deposit_paid")

        # Also check if the message looks like billing info (address, postal code, etc.)
        message_body = (state.message.body or "").strip().lower()
        looks_like_billing = _looks_like_billing_fragment(message_body) if message_body else False

        # Check if this is a synthetic deposit payment notification
        # (comes from pay_deposit endpoint with deposit_just_paid flag)
        deposit_just_paid = state.message.extras.get("deposit_just_paid", False)

        # Check if message includes explicit event_id matching this event
        msg_event_id = state.message.extras.get("event_id")
        event_id_matches = msg_event_id and msg_event_id == last_event.get("event_id")

        # Only create new event if this is truly a NEW inquiry, not a billing/deposit follow-up
        if awaiting_billing or awaiting_deposit or looks_like_billing or deposit_just_paid or event_id_matches:
            # Continue with existing event - don't create new
            trace_db_write(_thread_id(state), "Step1_Intake", "offer_accepted_continue", {
                "reason": "billing_or_deposit_followup",
                "awaiting_billing": awaiting_billing,
                "awaiting_deposit": awaiting_deposit,
                "looks_like_billing": looks_like_billing,
                "deposit_just_paid": deposit_just_paid,
                "event_id_matches": event_id_matches,
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
