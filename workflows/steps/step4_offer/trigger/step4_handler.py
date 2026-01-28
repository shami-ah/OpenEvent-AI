from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

from workflows.common.requirements import merge_client_profile, requirements_hash
from workflows.common.billing import (
    billing_prompt_for_missing_fields,
    format_billing_display,
    missing_billing_fields,
    update_billing_details,
)
# Billing gate helpers (O2 consolidation)
from workflows.common.billing_gate import (
    refresh_billing as _refresh_billing,
    flag_billing_accept_pending as _flag_billing_accept_pending,
    billing_prompt_draft as _billing_prompt_draft,
)
# Product operations helpers (O1 refactoring)
from .product_ops import (
    apply_product_operations as _apply_product_operations,
    autofill_products_from_preferences as _autofill_products_from_preferences,
    products_ready as _products_ready,
    ensure_products_container as _ensure_products_container,
    infer_participant_count as _infer_participant_count,
    room_alias_map as _room_alias_map,
    room_aliases as _room_aliases,
    product_unavailable_in_room as _product_unavailable_in_room,
    normalise_products as _normalise_products,
    normalise_product_names as _normalise_product_names,
    upsert_product as _upsert_product,
    menu_name_set as _menu_name_set,
    build_product_line_from_record as _build_product_line_from_record,
    summarize_product_line as _summarize_product_line,
    build_alternative_suggestions as _build_alternative_suggestions,
)
# Note: _normalise_product_fields moved to offer_summary.py usage only
from workflows.common.confirmation_gate import (
    auto_continue_if_ready,
    get_next_prompt,
)
from workflows.common.site_visit_state import is_site_visit_scheduled
from workflows.io.integration.config import is_hil_all_replies_enabled
from workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from workflows.common.confidence -> backend.detection.intent.confidence
from detection.intent.confidence import check_nonsense_gate
from workflows.common.detection_utils import get_unified_detection
from workflows.common.prompts import append_footer
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
    _fallback_structured_body,
)
from workflows.change_propagation import (
    ChangeType,
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.detour_acknowledgment import (
    generate_detour_acknowledgment,
    add_detour_acknowledgment_draft,
)
from workflows.qna.engine import build_structured_qna_result
from workflows.qna.extraction import ensure_qna_extraction
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.io.config_store import get_product_autofill_threshold
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.common.pricing import build_deposit_info
from workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from debug.hooks import trace_db_write, trace_detour, trace_gate, trace_state, trace_step, trace_marker, trace_general_qa_status, set_subloop
from debug.trace import set_hil_open
from utils.profiler import profile_step
from workflow.state import WorkflowStep, write_stage
from services.products import find_product, normalise_product_payload
from services.rooms import load_room_catalog
from workflows.steps.step5_negotiation import _handle_accept, _offer_summary_lines as _hil_offer_summary_lines
# MIGRATED: from workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from detection.response.matchers import matches_acceptance_pattern
# Note: DINNER_MENU_OPTIONS, generate_catering_catalog_link, generate_catering_menu_link,
# create_snapshot moved to offer_summary.py (Jan 2026 god-file refactoring)

from ..llm.send_offer_llm import ComposeOffer

# O3 refactoring: Offer compose/persist functions extracted to dedicated module
from .compose import build_offer, _record_offer, _determine_offer_total

# God-file refactoring (Jan 2026): Preconditions extracted to dedicated module
from .preconditions import (
    evaluate_preconditions as _evaluate_preconditions,
    has_capacity as _has_capacity,
    route_to_owner_step as _route_to_owner_step,
    handle_products_pending as _handle_products_pending,
    _step_name,
)

# God-file refactoring (Jan 2026): Pricing extracted to dedicated module
from .pricing import rebuild_pricing_inputs as _rebuild_pricing_inputs

# God-file refactoring (Jan 2026): Offer summary extracted to dedicated module
from .offer_summary import (
    compose_offer_summary as _compose_offer_summary,
    default_menu_alternatives as _default_menu_alternatives,
)

__workflow_role__ = "trigger"


@trace_step("Step4_Offer")
@profile_step("workflow.step4.offer")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Step 4 — offer preparation and transmission."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": None,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event",
            "context": state.context_snapshot,
        }
        return GroupResult(action="offer_missing_event", payload=payload, halt=True)

    previous_step = event_entry.get("current_step") or 3
    state.current_step = 4
    thread_id = _thread_id(state)

    # If an acceptance is already awaiting HIL (step 5), do not emit another offer.
    pending_negotiation = event_entry.get("negotiation_pending_decision")
    pending_hil = [
        req for req in (event_entry.get("pending_hil_requests") or []) if req.get("step") == 5
    ]
    if pending_negotiation or pending_hil:
        state.set_thread_state("Waiting on HIL")
        set_hil_open(thread_id, True)
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "pending_decision": pending_negotiation,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
        }
        return GroupResult(action="offer_waiting_hil", payload=payload, halt=True)

    # -------------------------------------------------------------------------
    # SITE VISIT HANDLING: If site_visit_state.status == "proposed", route to Step 7
    # Client's date mentions are for site visits, not event date changes
    # -------------------------------------------------------------------------
    visit_state = event_entry.get("site_visit_state") or {}
    if visit_state.get("status") == "proposed":
        # Route to Step 7 for site visit handling
        update_event_metadata(event_entry, current_step=7)
        state.current_step = 7
        state.extras["persist"] = True
        return GroupResult(
            action="route_to_site_visit",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "reason": "site_visit_in_progress",
                "persisted": True,
            },
            halt=False,  # Continue to Step 7
        )

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    if (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept"):
        # Skip billing capture for synthetic deposit payment messages
        # (their body is "I have paid the deposit." which would corrupt billing)
        is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
        if not is_deposit_signal:
            message_text = (state.message.body or "").strip() if state.message else ""
            if message_text:
                event_entry.setdefault("event_data", {})["Billing Address"] = message_text
                state.extras["persist"] = True

    billing_missing = _refresh_billing(event_entry)
    state.extras["persist"] = True

    # -------------------------------------------------------------------------
    # UNIFIED CONFIRMATION GATE: Order-independent check for all prerequisites
    # Uses in-memory event_entry (which has latest billing) but reloads deposit
    # status from database (in case it was paid via frontend API)
    # -------------------------------------------------------------------------
    event_id = event_entry.get("event_id")

    # DETOUR FIX: If we came from a detour (caller_step is set), we need to regenerate
    # the offer even if the previous one was accepted. The date/room/requirements may have
    # changed, invalidating the old offer.
    caller_step = event_entry.get("caller_step")
    if caller_step is not None and event_entry.get("offer_accepted"):
        logger.info("[Step4] Detour in progress (caller=%s) - clearing offer_accepted to regenerate offer", caller_step)
        event_entry["offer_accepted"] = False
        state.extras["persist"] = True

    if event_id and event_entry.get("offer_accepted"):
        from workflows.common.confirmation_gate import check_confirmation_gate, reload_and_check_gate

        # First check in-memory state (has latest billing)
        gate_status = check_confirmation_gate(event_entry)

        # If deposit is required but not paid in memory, check database for API updates
        if gate_status.deposit_required and not gate_status.deposit_paid:
            _, db_status, fresh_entry = auto_continue_if_ready(event_id, event_entry)
            # If deposit was paid via API, update our status
            if db_status.deposit_paid:
                gate_status = db_status
                # Also update event_entry with fresh deposit info
                event_entry["deposit_info"] = fresh_entry.get("deposit_info", {})
                event_entry["deposit_state"] = fresh_entry.get("deposit_state", {})

        if gate_status.ready_for_hil:
            # All prerequisites met - continue to HIL
            logger.debug("[Step4] Confirmation gate passed: billing_complete=%s, deposit_required=%s, deposit_paid=%s",
                        gate_status.billing_complete, gate_status.deposit_required, gate_status.deposit_paid)
            return _start_hil_acceptance_flow(
                state,
                event_entry,
                previous_step,
                thread_id,
                audit_label="offer_accept_pending_hil_gate_passed",
                action="offer_accept_pending_hil",
            )

        # Not ready - check if we need to prompt for missing items
        next_prompt = get_next_prompt(gate_status, step=4)
        if next_prompt:
            state.add_draft_message(next_prompt)
            update_event_metadata(event_entry, current_step=4, thread_state="Awaiting Client")
            state.set_thread_state("Awaiting Client")
            state.extras["persist"] = True
            return GroupResult(
                action="awaiting_prerequisites",
                payload={
                    "pending": gate_status.pending_items,
                    "billing_complete": gate_status.billing_complete,
                    "deposit_paid": gate_status.deposit_paid,
                },
                halt=True,
            )

    # [CHANGE DETECTION + Q&A] Tap incoming stream BEFORE offer composition to detect client revisions
    message_text = _message_text(state)
    normalized_message_text = _normalize_quotes(message_text)
    user_info = state.user_info or {}

    # -------------------------------------------------------------------------
    # CATERING -> PRODUCTS_ADD CONVERSION
    # When user confirms a catering item (e.g., "yes we'd like the Classic Apéro"),
    # Gemini extracts it to the 'catering' field, not 'products_add'.
    # Convert catalog products from 'catering' to 'products_add' for the product flow.
    # -------------------------------------------------------------------------
    catering_pref = user_info.get("catering")
    if catering_pref and isinstance(catering_pref, str) and not user_info.get("products_add"):
        catering_product = find_product(catering_pref)
        if catering_product:
            # Infer quantity from participant count
            participant_count = (
                user_info.get("participants")
                or (event_entry.get("requirements") or {}).get("number_of_participants")
                or (event_entry.get("event_data") or {}).get("Number of Participants")
            )
            try:
                quantity = int(participant_count) if participant_count else 1
            except (TypeError, ValueError):
                quantity = 1
            user_info["products_add"] = [{"name": catering_product.name, "quantity": quantity}]
            state.user_info = user_info
            logger.info("[Step4] Converted catering field '%s' to products_add: %s (qty: %d)",
                       catering_pref, catering_product.name, quantity)

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        # Silent ignore - no reply, no further processing
        return GroupResult(
            action="nonsense_ignored",
            payload={"reason": "low_confidence_no_workflow_signal", "step": 4},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=4,
                next_step=4,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=4, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 4},
            halt=True,
        )
    # -------------------------------------------------------------------------

    # Q&A classification
    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]

    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step4_Offer",
        )

    # [CHANGE DETECTION] Run BEFORE Q&A dispatch
    # Use enhanced detection with dual-condition logic (revision signal + bound target)
    # Pass unified_detection so Q&A messages don't trigger false change detours
    unified_detection = get_unified_detection(state)
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None
    if state.extras.get("detour_change_applied") == "date" and change_type == ChangeType.DATE:
        change_type = None
        if thread_id:
            trace_marker(
                thread_id,
                "SKIP_DUPLICATE_DATE_DETOUR",
                detail="Date change already applied in detour flow; skipping re-detection in Step4",
                owner_step="Step4_Offer",
            )

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=4)

        # Trace logging for parity with Step 2
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 4,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step4_Offer",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        # PRODUCTS change stays in step 4 - set flag to skip Q&A and regenerate offer
        if change_type.value == "products" and decision.next_step == 4:
            state.extras["products_change_detected"] = True
            # Extract product name from message text for _apply_product_operations
            if message_text and not user_info.get("products_add"):
                # Try to find product in full catalog using find_product
                product_match = find_product(message_text)
                if product_match:
                    # find_product returns ProductRecord dataclass, not dict
                    user_info["products_add"] = [{"name": product_match.name, "quantity": 1}]
                    state.user_info = user_info
                    logger.info("[Step4] Extracted product from message: %s", product_match.name)
                else:
                    # Fallback: check dinner menu names
                    menu_names = _menu_name_set()
                    text_lower = message_text.lower()
                    for menu in menu_names:
                        if menu.lower() in text_lower:
                            user_info["products_add"] = [{"name": menu, "quantity": 1}]
                            state.user_info = user_info
                            logger.info("[Step4] Extracted menu from message: %s", menu)
                            break
            # Continue to product processing (skip Q&A)
        elif decision.next_step != 4:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # For date changes: Keep room lock, invalidate room_eval_hash so Step 3 re-verifies
            # Step 3 will check if the locked room is still available on the new date
            # and skip room selection if so, or clear the lock if not
            if change_type.value == "date" and decision.next_step == 2:
                update_event_metadata(
                    event_entry,
                    date_confirmed=False,
                    room_eval_hash=None,  # Invalidate to trigger re-verification in Step 3
                    # NOTE: Keep locked_room_id to allow fast-skip in Step 3 if room still available
                )
            # For requirements changes, clear the lock since room may no longer fit
            elif change_type.value == "requirements" and decision.next_step in (2, 3):
                # BUG FIX: Only set date_confirmed=False when going to Step 2
                # Passing None would overwrite existing True value!
                metadata_updates = {
                    "room_eval_hash": None,
                    "locked_room_id": None,
                }
                if decision.next_step == 2:
                    metadata_updates["date_confirmed"] = False
                update_event_metadata(event_entry, **metadata_updates)

            append_audit_entry(event_entry, 4, decision.next_step, f"{change_type.value}_change_detected")

            # IMMEDIATE ACKNOWLEDGMENT: Add detour acknowledgment draft
            ack_result = generate_detour_acknowledgment(
                change_type=change_type,
                decision=decision,
                event_entry=event_entry,
                user_info=user_info,
            )
            if ack_result.generated:
                add_detour_acknowledgment_draft(state, ack_result)

            # Skip Q&A: return detour signal
            # CRITICAL: Update event_entry BEFORE state.current_step so routing loop sees the change
            update_event_metadata(event_entry, current_step=decision.next_step)
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True
            # Clear stale hybrid Q&A from previous turns (prevents old Q&A being appended to detour response)
            state.extras.pop("hybrid_qna_response", None)

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "change_type": change_type.value,
                "detour_to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="change_detour", payload=payload, halt=False)

    # Acceptance (no product/date change) — short-circuit to HIL review.
    # Guard: ignore room-selection clicks (labels like "Proceed with Room E") so they don't look like acceptances.
    room_choice_signal = bool(user_info.get("_room_choice_detected"))
    room_selection_phrase = "proceed with room" in (normalized_message_text or "").lower()
    acceptance_applicable = not (room_choice_signal or room_selection_phrase)

    if acceptance_applicable and _looks_like_offer_acceptance(normalized_message_text):
        # Mark offer as accepted so we can continue after deposit payment
        event_entry["offer_accepted"] = True
        state.extras["persist"] = True

        billing_missing = _refresh_billing(event_entry)
        if billing_missing:
            _flag_billing_accept_pending(event_entry, billing_missing)
            prompt = _billing_prompt_draft(billing_missing, step=4)
            state.add_draft_message(prompt)
            append_audit_entry(event_entry, previous_step, 4, "offer_accept_blocked_missing_billing")
            update_event_metadata(
                event_entry,
                current_step=5,
                thread_state="Awaiting Client",
                transition_ready=False,
                caller_step=None,
            )
            state.current_step = 5
            state.caller_step = None
            state.set_thread_state("Awaiting Client")
            set_hil_open(thread_id, False)
            state.extras["persist"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "missing": billing_missing,
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="offer_accept_requires_billing", payload=payload, halt=True)

        # Check if deposit is required but not paid
        deposit_info = event_entry.get("deposit_info") or {}
        deposit_required = deposit_info.get("deposit_required", False)
        deposit_paid = deposit_info.get("deposit_paid", False)
        deposit_amount = deposit_info.get("deposit_amount", 0)

        if deposit_required and not deposit_paid and deposit_amount > 0:
            # Friendly reminder: deposit must be paid before confirmation
            deposit_reminder = {
                "body_markdown": (
                    f"Thank you for wanting to confirm! Before I can proceed with your booking, "
                    f"please complete the deposit payment of CHF {deposit_amount:,.2f}. "
                    f"Once the deposit is received, I'll finalize your booking. "
                    f"You can pay the deposit using the payment option shown in the offer."
                ),
                "step": 4,
                "topic": "deposit_reminder",
                "next_step": "Awaiting deposit payment",
                "thread_state": "Awaiting Client",
                "requires_approval": False,
            }
            state.add_draft_message(deposit_reminder)
            append_audit_entry(event_entry, previous_step, 4, "offer_accept_blocked_deposit_unpaid")
            update_event_metadata(
                event_entry,
                current_step=4,
                thread_state="Awaiting Client",
                transition_ready=False,
            )
            state.current_step = 4
            state.set_thread_state("Awaiting Client")
            set_hil_open(thread_id, False)
            state.extras["persist"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "deposit_required": deposit_amount,
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="offer_accept_requires_deposit", payload=payload, halt=True)

        # Always route acceptances through HIL so the manager dashboard shows the approval buttons.
        return _start_hil_acceptance_flow(
            state,
            event_entry,
            previous_step,
            thread_id,
            audit_label="offer_accept_pending_hil",
            action="offer_accept_pending_hil",
        )

    # No change detected: check if Q&A should be handled
    # Note: has_offer_update previously used for deferred Q&A - now handled differently

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client accepts the offer AND asks about next steps (site visit, deposit),
    # that's NOT general Q&A - it's natural workflow continuation.
    # Example: "Accept the offer, when can we do a site visit?"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=4)
    if sequential_check.get("is_sequential"):
        # Client is accepting offer AND asking about next step - natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
        if thread_id:
            trace_marker(
                thread_id,
                "SEQUENTIAL_WORKFLOW",
                detail=f"step4_to_step{sequential_check.get('asks_next_step')}",
                data=sequential_check,
            )

    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general")
    # Skip Q&A when products change was detected - we need to regenerate the offer
    if state.extras.get("products_change_detected"):
        general_qna_applicable = False
        logger.debug("[Step4] Skipping Q&A dispatch - products change detected")

    # [FIX JAN-12-2026] At Step 4, Q&A should be sent SEPARATELY from offer (never in same message).
    # Send Q&A first with requires_approval=False, then continue to generate offer.
    # This ensures: 1) Q&A is answered immediately, 2) Offer goes through HIL approval.
    if general_qna_applicable:
        # Check if we should be generating an offer (room and date confirmed)
        room_locked = bool(event_entry.get("locked_room_id"))
        date_confirmed = event_entry.get("date_confirmed", False)
        should_generate_offer = room_locked and date_confirmed

        if should_generate_offer:
            # Check if this is PURE Q&A (no acceptance signal, no room confirmation this turn)
            # LLM-first: Check unified detection for acceptance signal
            llm_has_acceptance = (
                unified_detection is not None
                and unified_detection.is_acceptance
            )
            text_has_acceptance = _looks_like_offer_acceptance(normalized_message_text)
            has_acceptance = llm_has_acceptance or text_has_acceptance
            # LLM-first: Check unified detection for question signal (fixes BUG-036)
            # Only use question mark as fallback when LLM detection unavailable
            llm_says_question = (
                unified_detection is not None
                and unified_detection.is_question
                and not unified_detection.is_change_request
            )
            question_mark_fallback = unified_detection is None and "?" in message_text
            is_pure_question = llm_says_question or question_mark_fallback
            # Room confirmation prefix indicates room was just confirmed by Step 3 in this turn
            # When present, we should generate the offer (not treat as pure Q&A)
            room_just_confirmed = bool(event_entry.get("room_confirmation_prefix"))

            # Check if we came from a detour (date/room change) - if so, always generate offer
            is_detour_call = event_entry.get("caller_step") is not None

            # Guard: If user is providing contact info, it's NOT pure Q&A
            # e.g., "You can reach Sarah at sarah@acme.com for any questions" provides booking info
            has_contact_info = (
                unified_detection is not None
                and (unified_detection.contact_name or unified_detection.contact_email or unified_detection.contact_phone)
            )

            # Debug logging for QNA_GUARD decision
            logger.debug(
                "[Step4][QNA_GUARD_CHECK] is_question=%s, has_acceptance=%s (llm=%s, text=%s), "
                "room_confirmed=%s, detour=%s, has_contact=%s",
                is_pure_question, has_acceptance, llm_has_acceptance, text_has_acceptance,
                room_just_confirmed, is_detour_call, has_contact_info
            )

            if is_pure_question and not has_acceptance and not room_just_confirmed and not is_detour_call and not has_contact_info:
                # PURE Q&A: Return early - don't generate offer or progress steps
                # E.g., "Does Room A have a projector?" at Step 4 should stay at Step 4
                # But NOT for detour calls - those must regenerate the offer
                logger.info("[Step4][QNA_GUARD] Pure Q&A detected - returning without offer generation")
                result = _present_general_room_qna(state, event_entry, classification, thread_id)
                return result
            elif is_detour_call:
                logger.info("[Step4][DETOUR_BYPASS] Bypassing QNA_GUARD - came from detour (caller=%s)", event_entry.get("caller_step"))
            elif has_contact_info:
                logger.info("[Step4][CONTACT_BYPASS] Bypassing QNA_GUARD - contact info provided")
            else:
                # HYBRID: Room confirmation + Q&A, or acceptance + Q&A
                # E.g., "Room B looks perfect. Do you offer catering?" - confirm room, answer Q&A, then offer
                # E.g., "Yes I accept. What's your parking policy?" - answer Q&A then process acceptance
                if room_just_confirmed:
                    logger.info("[Step4][HYBRID] Room just confirmed - generating offer with Q&A")
                qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
                if qa_result and state.draft_messages:
                    for draft in state.draft_messages:
                        draft["requires_approval"] = False
                    logger.debug("[Step4] Q&A sent separately before offer generation (hybrid message)")
                # Continue to generate offer below
        else:
            # Not ready for offer - just return Q&A (legacy behavior)
            result = _present_general_room_qna(state, event_entry, classification, thread_id)
            return result

    requirements = event_entry.get("requirements") or {}
    current_req_hash = event_entry.get("requirements_hash")
    computed_hash = requirements_hash(requirements) if requirements else None
    if computed_hash and computed_hash != current_req_hash:
        update_event_metadata(event_entry, requirements_hash=computed_hash)
        current_req_hash = computed_hash
        state.extras["persist"] = True

    _ensure_products_container(event_entry)
    # [SKIP PRODUCTS TEXT DETECTION] Detect "no extras", "skip products" etc. from message body
    if state.user_info is not None:
        message_body = (state.message.body or "").lower() if state.message else ""
        skip_phrases = (
            "no extras", "keine extras", "skip products", "skip product",
            "without extras", "ohne extras", "no add-ons", "no addons",
            "proceed without", "just the room", "nur den raum",
            "no catering", "keine produkte", "no products",
        )
        if any(phrase in message_body for phrase in skip_phrases):
            state.user_info["skip_products"] = True
            logger.debug("[Step4] Detected skip products phrase in message")
    products_changed = _apply_product_operations(event_entry, state.user_info or {})
    if products_changed:
        state.extras["persist"] = True
    autofilled = _autofill_products_from_preferences(
        event_entry,
        state.user_info or {},
        min_score=get_product_autofill_threshold(),
    )
    if autofilled:
        state.extras["persist"] = True

    precondition = _evaluate_preconditions(event_entry, current_req_hash, thread_id)
    if precondition:
        code, target = precondition
        if target in (2, 3):
            return _route_to_owner_step(state, event_entry, target, code, thread_id)
        return _handle_products_pending(state, event_entry, code)

    # NOTE: Don't clear caller_step here - we need it later to decide whether to stay at step 4
    # or advance to step 5 after offer generation. caller_step is cleared at the end of this handler.
    write_stage(event_entry, current_step=WorkflowStep.STEP_4)
    state.extras["persist"] = True

    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)

    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info, thread_id)

    # Attach deposit info based on global deposit configuration
    deposit_config = (state.db.get("config") or {}).get("global_deposit") or {}
    # Parse event date for deposit due date calculation (relative to event, not just today)
    # Try multiple date formats: DD.MM.YYYY (stored format) and YYYY-MM-DD (ISO format)
    event_date_dt = None
    chosen_date_str = event_entry.get("chosen_date")
    if chosen_date_str:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                event_date_dt = datetime.strptime(chosen_date_str, fmt)
                break
            except (ValueError, TypeError):
                continue
    deposit_info = build_deposit_info(total_amount, deposit_config, event_date=event_date_dt)
    if deposit_info:
        event_entry["deposit_info"] = deposit_info
        # Log activity when deposit is first configured
        from activity.persistence import log_workflow_activity
        deposit_amount = deposit_info.get("deposit_amount", 0)
        deposit_due = deposit_info.get("deposit_due_date", "before event")
        log_workflow_activity(
            event_entry, "deposit_set",
            amount=f"CHF {deposit_amount:,.2f}",
            due_date=deposit_due
        )

    summary_lines = _compose_offer_summary(event_entry, total_amount, state)
    billing_display = format_billing_display(
        event_entry.get("billing_details") or {},
        (event_entry.get("event_data") or {}).get("Billing Address"),
    )

    # Universal Verbalizer: only verbalize the introduction text
    # The structured offer (line items, prices, total) must remain as-is
    from workflows.common.prompts import verbalize_draft_body

    # Create a brief intro message for verbalization
    room = event_entry.get("locked_room_id") or "your preferred room"
    chosen_date = event_entry.get("chosen_date") or "your requested date"
    formatted_date = format_iso_date_to_ddmmyyyy(chosen_date) if chosen_date != "your requested date" else chosen_date
    intro_text = f"Here is your offer for {room} on {formatted_date}."

    # Verbalize only the intro, not the structured offer
    # NOTE: Don't pass total_amount or products to offer_intro - these are shown
    # in the structured offer card below. Passing them causes the LLM to try to
    # mention amounts, which risks hallucination (e.g., "CHF 1" instead of "CHF 1050").
    verbalized_intro = verbalize_draft_body(
        intro_text,
        step=4,
        topic="offer_intro",
        event_date=formatted_date,
        participants_count=_infer_participant_count(event_entry),
        room_name=room,
    )

    # [HYBRID MESSAGE] Check for prefixes to prepend:
    # 1. Room confirmation prefix (from Step 3 when room is confirmed)
    # 2. Sourcing prefix (from product sourcing flow)
    # This creates a combined "Room confirmed + Offer" message instead of separate messages
    room_confirmation_prefix = event_entry.pop("room_confirmation_prefix", "")  # Clear after use
    sourced_products = event_entry.get("sourced_products") or {}
    sourcing_prefix = sourced_products.get("sourcing_prefix", "")

    # Combine all prefixes with verbalized intro and structured offer
    combined_prefix = room_confirmation_prefix + sourcing_prefix

    # [TIME WARNING] Include operating hours warning if times are outside venue hours
    time_warning = state.extras.get("time_warning")
    time_warning_suffix = ""
    if time_warning:
        # Log activity for visibility
        from activity.persistence import log_workflow_activity
        log_workflow_activity(
            event_entry, "time_outside_hours",
            time=f"{state.user_info.get('start_time', '')} - {state.user_info.get('end_time', '')}",
            issue=state.extras.get("time_warning_issue", "outside_hours"),
        )
        time_warning_suffix = f"\n\n---\n**Note:** {time_warning}"
        logger.info("[Step4][TIME_WARNING] Including operating hours warning in offer")

    offer_body_markdown = combined_prefix + verbalized_intro + "\n\n" + "\n".join(summary_lines) + time_warning_suffix

    draft_message = {
        "body_markdown": offer_body_markdown,
        "step": 4,
        "next_step": "Await feedback",
        "thread_state": "Awaiting Client",
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        # When toggle ON: All messages go to HIL including offers
        # When toggle OFF: Offers are sent automatically (manager reviews only after deposit)
        "requires_approval": is_hil_all_replies_enabled(),
        "table_blocks": [
            {
                "type": "table",
                "header": ["Field", "Value"],
                "rows": [
                    ["Event Date", event_entry.get("chosen_date") or "TBD"],
                    ["Room", event_entry.get("locked_room_id") or "TBD"],
                    ["Billing address", billing_display or "Pending"],
                    ["Total", f"CHF {total_amount:,.2f}"],
                ],
            }
        ],
        "actions": [
            {
                "type": "send_offer",
                "label": "Send to client",
                "offer_id": offer_id,
            }
        ],
        "headers": ["Offer"],
    }
    state.add_draft_message(draft_message)

    append_audit_entry(event_entry, previous_step, 4, "offer_generated")

    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    caller = event_entry.get("caller_step")
    if caller != 5:
        negotiation_state["counter_count"] = 0
        negotiation_state["manual_review_task_id"] = None

    # After a detour (caller_step set), stay at step 4 awaiting client response to the new offer.
    # Only advance to step 5 in normal flow (first offer generation, no detour).
    if caller is not None:
        # Detour flow: client must respond to regenerated offer, stay at step 4
        next_step = 4
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    else:
        # Normal flow: advance to step 5
        next_step = 5

    update_event_metadata(
        event_entry,
        current_step=next_step,
        thread_state="Awaiting Client",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = next_step
    state.caller_step = None
    state.set_thread_state("Awaiting Client")
    set_hil_open(thread_id, False)
    state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step4_Offer",
        {
            "offer_id": offer_id,
            "offer_version": offer_version,
            "total_amount": total_amount,
            "products_ready": _products_ready(event_entry),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "products": list(event_entry.get("products") or []),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }

    # Log offer sent activity
    from activity.persistence import log_workflow_activity
    amount_str = f"€{total_amount}" if total_amount else ""
    log_workflow_activity(event_entry, "offer_sent", amount=amount_str)

    result = GroupResult(action="offer_draft_prepared", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


# O3: build_offer moved to compose.py

# God-file refactoring (Jan 2026): Precondition functions moved to preconditions.py:
# - _evaluate_preconditions
# - _route_to_owner_step
# - _handle_products_pending
# - _has_capacity
# - _step_name

# NOTE: Product operations functions moved to product_ops.py (O1 refactoring):
# _products_ready, _ensure_products_container, _has_offer_update,
# _autofill_products_from_preferences, _apply_product_operations, _normalise_products,
# _normalise_product_names, _upsert_product, _build_product_line_from_record,
# _summarize_product_line, _build_alternative_suggestions, _infer_participant_count,
# _product_unavailable_in_room, _room_alias_map, _room_aliases, _menu_name_set,
# _normalise_product_fields


# God-file refactoring (Jan 2026): _rebuild_pricing_inputs moved to pricing.py

# Old product ops functions removed in O1 refactoring - now imported from product_ops.py


# O3: _record_offer moved to compose.py


# God-file refactoring (Jan 2026): _compose_offer_summary and _default_menu_alternatives
# moved to offer_summary.py

# O3: _determine_offer_total moved to compose.py

# God-file refactoring (Jan 2026): _step_name moved to preconditions.py


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _strip_system_subject(subject: str) -> str:
    """Strip system-generated metadata from subject lines.

    The API adds "Client follow-up (YYYY-MM-DD HH:MM)" to follow-up messages.
    This timestamp should NOT be used for change detection as it would incorrectly
    trigger DATE change detection due to the timestamp in the subject.
    """
    import re
    # Pattern: "Client follow-up (YYYY-MM-DD HH:MM)" or similar system-generated prefixes
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state, stripping system-generated subject prefixes."""
    message = state.message
    if not message:
        return ""
    subject = _strip_system_subject(message.subject or "")
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _normalize_quotes(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "’": "'",
        "‘": "'",
        "´": "'",
        "`": "'",
        "“": '"',
        "”": '"',
    }
    for bad, repl in replacements.items():
        text = text.replace(bad, repl)
    return text

# NOTE: _check_deposit_payment_continuation and _auto_accept_if_billing_ready
# were removed (dead code) - replaced by unified confirmation_gate.py


def _manager_request_detected(state: WorkflowState, event_entry: Dict[str, Any]) -> bool:
    """Detect explicit manager/special-request signals."""

    if (event_entry.get("flags") or {}).get("manager_requested"):
        return True
    text = (_message_text(state) or "").lower()
    manager_tokens = (
        "manager",
        "boss",
        "owner",
        "director",
        "gm",
        "general manager",
        "approve with manager",
        "manager approval",
    )
    if any(token in text for token in manager_tokens):
        flags = event_entry.setdefault("flags", {})
        flags["manager_requested"] = True
        # ensure persistence
        state.extras["persist"] = True
        return True
    return False


def _auto_confirm_without_hil(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
) -> GroupResult:
    offers = event_entry.get("offers") or []
    current_offer_id = event_entry.get("current_offer_id")
    summary_lines = _hil_offer_summary_lines(event_entry, include_cta=False)
    room_label = event_entry.get("locked_room_id") or event_entry.get("selected_room") or "the room"
    display_date = event_entry.get("chosen_date") or ""
    billing_display = format_billing_display(event_entry.get("billing_details") or {}, (event_entry.get("event_data") or {}).get("Billing Address"))

    body_lines = [
        f"Confirmed: {room_label} on {display_date} is locked in.",
    ]
    if billing_display:
        body_lines.append(f"Billing address: {billing_display}.")
    body_lines.append("")
    body_lines.append("\n".join(summary_lines))
    body_lines.append("")
    # Show appropriate next step based on site visit status
    if is_site_visit_scheduled(event_entry):
        sv_state = event_entry.get("site_visit_state") or {}
        sv_date = sv_state.get("date_iso", "")
        sv_time = sv_state.get("time_slot", "")
        sv_display = f"{sv_date} at {sv_time}" if sv_time else sv_date
        body_lines.append(
            f"Your site visit is already scheduled for {sv_display}. "
            "We'll finalize the details closer to your event date."
        )
    else:
        body_lines.append("Next step: let's line up a site visit. Do you have preferred dates or times?")
    body = "\n".join(line for line in body_lines if line)

    draft = {
        "body": append_footer(body, step=5, next_step=5, thread_state="In Progress"),
        "step": 5,
        "topic": "negotiation_accept_no_hil",
        "requires_approval": False,
    }
    for offer in offers:
        if offer.get("offer_id") == current_offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    event_entry["offer_status"] = "Accepted"
    event_entry["negotiation_pending_decision"] = None
    event_entry["pending_hil_requests"] = []
    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="In Progress",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("In Progress")
    set_hil_open(thread_id, False)
    state.add_draft_message(draft)
    append_audit_entry(event_entry, previous_step, 5, "offer_accept_no_hil")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_accept_no_hil", payload=payload, halt=True)


def _start_hil_acceptance_flow(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
    *,
    audit_label: str,
    action: str,
) -> GroupResult:
    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    negotiation_state["counter_count"] = 0

    response = _handle_accept(event_entry)
    state.add_draft_message(response["draft"])
    append_audit_entry(event_entry, previous_step, 5, audit_label)
    event_entry["negotiation_pending_decision"] = response["pending"]
    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="Waiting on HIL",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("Waiting on HIL")
    set_hil_open(thread_id, True)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": response["offer_id"],
        "pending_decision": response["pending"],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action=action, payload=payload, halt=True)


def _looks_like_offer_acceptance(message_text: str) -> bool:
    normalized = _normalize_quotes(message_text or "").lower()
    is_match, confidence, _ = matches_acceptance_pattern(normalized)
    return is_match and confidence > 0.5


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 4 - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id,
        step_number=4, step_name="Offer"
    )


def _append_deferred_general_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> None:
    pre_count = len(state.draft_messages)
    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        return
    appended = append_general_qna_to_primary(state)
    if not appended:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
