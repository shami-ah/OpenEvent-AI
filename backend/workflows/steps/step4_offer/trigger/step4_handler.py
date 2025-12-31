from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from backend.workflows.common.requirements import merge_client_profile, requirements_hash
from backend.workflows.common.billing import (
    billing_prompt_for_missing_fields,
    format_billing_display,
    missing_billing_fields,
    update_billing_details,
)
# Billing gate helpers (O2 consolidation)
from backend.workflows.common.billing_gate import (
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
    has_offer_update as _has_offer_update,
    infer_participant_count as _infer_participant_count,
    room_alias_map as _room_alias_map,
    room_aliases as _room_aliases,
    product_unavailable_in_room as _product_unavailable_in_room,
    normalise_products as _normalise_products,
    normalise_product_names as _normalise_product_names,
    normalise_product_fields as _normalise_product_fields,
    upsert_product as _upsert_product,
    menu_name_set as _menu_name_set,
    build_product_line_from_record as _build_product_line_from_record,
    summarize_product_line as _summarize_product_line,
    build_alternative_suggestions as _build_alternative_suggestions,
)
from backend.workflows.common.confirmation_gate import (
    auto_continue_if_ready,
    get_next_prompt,
)
from backend.workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import check_nonsense_gate
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
    _fallback_structured_body,
)
from backend.workflows.change_propagation import (
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io.config_store import get_product_autofill_threshold
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.pricing import build_deposit_info, derive_room_rate, normalise_rate
from backend.workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from backend.debug.hooks import trace_db_write, trace_detour, trace_gate, trace_state, trace_step, trace_marker, trace_general_qa_status, set_subloop
from backend.debug.trace import set_hil_open
from backend.utils.profiler import profile_step
from backend.workflow.state import WorkflowStep, write_stage
from backend.services.products import find_product, normalise_product_payload
from backend.services.rooms import load_room_catalog
from backend.workflows.steps.step5_negotiation import _handle_accept, _offer_summary_lines as _hil_offer_summary_lines
# MIGRATED: from backend.workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from backend.detection.response.matchers import matches_acceptance_pattern
from backend.workflows.common.menu_options import DINNER_MENU_OPTIONS
from backend.utils.pseudolinks import (
    generate_catering_catalog_link,
    generate_catering_menu_link,
    generate_room_details_link,
)
from backend.utils.page_snapshots import create_snapshot

from ..llm.send_offer_llm import ComposeOffer

# O3 refactoring: Offer compose/persist functions extracted to dedicated module
from .compose import build_offer, _record_offer, _determine_offer_total

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
    if event_id and event_entry.get("offer_accepted"):
        from backend.workflows.common.confirmation_gate import check_confirmation_gate, reload_and_check_gate

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
            print(f"[Step4] Confirmation gate passed: billing_complete={gate_status.billing_complete}, "
                  f"deposit_required={gate_status.deposit_required}, deposit_paid={gate_status.deposit_paid}")
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
    enhanced_result = detect_change_type_enhanced(event_entry, user_info, message_text=message_text)
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

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

        if decision.next_step != 4:
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

            # Skip Q&A: return detour signal
            # CRITICAL: Update event_entry BEFORE state.current_step so routing loop sees the change
            update_event_metadata(event_entry, current_step=decision.next_step)
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True

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
                    f"Once the deposit is received, I'll immediately send your confirmation for final approval. "
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
    has_offer_update = _has_offer_update(user_info)

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
    if general_qna_applicable and has_offer_update:
        deferred_general_qna = True
        general_qna_applicable = False
    if general_qna_applicable:
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
            print(f"[Step4] Detected skip products phrase in message")
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

    write_stage(event_entry, current_step=WorkflowStep.STEP_4, caller_step=None)
    update_event_metadata(event_entry, caller_step=None)
    state.extras["persist"] = True
    state.caller_step = None

    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)

    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info, thread_id)

    # Attach deposit info based on global deposit configuration
    deposit_config = (state.db.get("config") or {}).get("global_deposit") or {}
    deposit_info = build_deposit_info(total_amount, deposit_config)
    if deposit_info:
        event_entry["deposit_info"] = deposit_info

    summary_lines = _compose_offer_summary(event_entry, total_amount, state)
    billing_display = format_billing_display(
        event_entry.get("billing_details") or {},
        (event_entry.get("event_data") or {}).get("Billing Address"),
    )

    # Universal Verbalizer: only verbalize the introduction text
    # The structured offer (line items, prices, total) must remain as-is
    from backend.workflows.common.prompts import verbalize_draft_body

    # Create a brief intro message for verbalization
    room = event_entry.get("locked_room_id") or "your preferred room"
    chosen_date = event_entry.get("chosen_date") or "your requested date"
    formatted_date = format_iso_date_to_ddmmyyyy(chosen_date) if chosen_date != "your requested date" else chosen_date
    intro_text = f"Here is your offer for {room} on {formatted_date}."

    # Verbalize only the intro, not the structured offer
    verbalized_intro = verbalize_draft_body(
        intro_text,
        step=4,
        topic="offer_intro",
        event_date=formatted_date,
        participants_count=_infer_participant_count(event_entry),
        room_name=room,
        total_amount=total_amount,
        products=event_entry.get("products"),
    )

    # Combine verbalized intro with structured offer (keeping line items intact)
    offer_body_markdown = verbalized_intro + "\n\n" + "\n".join(summary_lines)

    draft_message = {
        "body_markdown": offer_body_markdown,
        "step": 4,
        "next_step": "Await feedback",
        "thread_state": "Awaiting Client",
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "requires_approval": False,
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

    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="Awaiting Client",
        transition_ready=False,
        caller_step=None,
    )
    if caller is not None:
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    state.current_step = 5
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
    result = GroupResult(action="offer_draft_prepared", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


# O3: build_offer moved to compose.py


def _evaluate_preconditions(
    event_entry: Dict[str, Any],
    current_requirements_hash: Optional[str],
    thread_id: str,
) -> Optional[Tuple[str, Union[int, str]]]:
    date_ok = bool(event_entry.get("date_confirmed"))
    trace_gate(thread_id, "Step4_Offer", "P1 date_confirmed", date_ok, {})
    if not date_ok:
        return "P1", 2

    locked_room_id = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")
    p2_ok = (
        locked_room_id
        and current_requirements_hash
        and room_eval_hash
        and current_requirements_hash == room_eval_hash
    )
    trace_gate(
        thread_id,
        "Step4_Offer",
        "P2 room_locked",
        bool(p2_ok),
        {"locked_room_id": locked_room_id, "room_eval_hash": room_eval_hash, "requirements_hash": current_requirements_hash},
    )
    if not p2_ok:
        return "P2", 3

    capacity_ok = _has_capacity(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P3 capacity_confirmed", capacity_ok, {})
    if not capacity_ok:
        return "P3", 3

    products_ok = _products_ready(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P4 products_ready", products_ok, {})
    if not products_ok:
        return "P4", "products"

    return None


def _route_to_owner_step(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    target_step: int,
    reason_code: str,
    thread_id: str,
) -> GroupResult:
    caller_step = WorkflowStep.STEP_4
    target_enum = WorkflowStep(f"step_{target_step}")
    write_stage(event_entry, current_step=target_enum, caller_step=caller_step)

    # Clear stale negotiation state when detouring back - old offer no longer valid
    if target_step in (2, 3):
        event_entry.pop("negotiation_pending_decision", None)

    thread_state = "Awaiting Client" if target_step in (2, 3) else "Waiting on HIL"
    update_event_metadata(event_entry, thread_state=thread_state)
    append_audit_entry(event_entry, 4, target_step, f"offer_gate_{reason_code.lower()}")

    trace_detour(
        thread_id,
        "Step4_Offer",
        _step_name(target_step),
        f"offer_gate_{reason_code.lower()}",
        {},
    )

    state.current_step = target_step
    state.caller_step = caller_step.numeric
    state.set_thread_state(thread_state)
    set_hil_open(thread_id, thread_state == "Waiting on HIL")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "target_step": target_step,
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_detour", payload=payload, halt=False)


def _handle_products_pending(state: WorkflowState, event_entry: Dict[str, Any], reason_code: str) -> GroupResult:
    products_state = event_entry.setdefault("products_state", {})
    first_prompt = not products_state.get("awaiting_client_products")

    if first_prompt:
        products_state["awaiting_client_products"] = True
        prompt = (
            "Before I prepare your tailored proposal, could you share which catering or add-ons you'd like to include? "
            "Let me know if you'd prefer to proceed without extras."
        )
        draft_message = {
            "body_markdown": prompt,
            "step": 4,
            "next_step": "Share preferred products",
            "thread_state": "Awaiting Client",
            "topic": "offer_products_prompt",
            "requires_approval": False,
            "actions": [
                {
                    "type": "share_products",
                    "label": "Provide preferred products",
                }
            ],
        }
        state.add_draft_message(draft_message)
        append_audit_entry(event_entry, 4, 4, "offer_products_prompt")
    else:
        # Still awaiting products - re-prompt with variation to avoid silent fallback
        repeat_prompt = (
            "I still need your product preferences before preparing the offer. "
            "Would you like catering, beverages, or any add-ons? "
            "You can also say 'no extras' to proceed without additional products."
        )
        draft_message = {
            "body_markdown": repeat_prompt,
            "step": 4,
            "next_step": "Share preferred products",
            "thread_state": "Awaiting Client",
            "topic": "offer_products_repeat_prompt",
            "requires_approval": False,
            "actions": [
                {
                    "type": "share_products",
                    "label": "Add products",
                },
                {
                    "type": "skip_products",
                    "label": "No extras needed",
                },
            ],
        }
        state.add_draft_message(draft_message)
        append_audit_entry(event_entry, 4, 4, "offer_products_repeat_prompt")

    write_stage(event_entry, current_step=WorkflowStep.STEP_4)
    update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = 4
    state.caller_step = event_entry.get("caller_step")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_products_pending", payload=payload, halt=True)


def _has_capacity(event_entry: Dict[str, Any]) -> bool:
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    if participants is None:
        participants = (event_entry.get("event_data") or {}).get("Number of Participants")
    if participants is None:
        participants = (event_entry.get("captured") or {}).get("participants")
    try:
        return int(str(participants).strip()) > 0
    except (TypeError, ValueError, AttributeError):
        return False


# NOTE: Product operations functions moved to product_ops.py (O1 refactoring):
# _products_ready, _ensure_products_container, _has_offer_update,
# _autofill_products_from_preferences, _apply_product_operations, _normalise_products,
# _normalise_product_names, _upsert_product, _build_product_line_from_record,
# _summarize_product_line, _build_alternative_suggestions, _infer_participant_count,
# _product_unavailable_in_room, _room_alias_map, _room_aliases, _menu_name_set,
# _normalise_product_fields


def _rebuild_pricing_inputs(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
    pricing_inputs = dict(event_entry.get("pricing_inputs") or {})
    override_total = user_info.get("offer_total_override")
    menu_names = _menu_name_set()

    base_rate_override = normalise_rate(user_info.get("room_rate")) if "room_rate" in user_info else None
    if base_rate_override is not None:
        pricing_inputs["base_rate"] = base_rate_override

    if normalise_rate(pricing_inputs.get("base_rate")) is None:
        derived_rate = derive_room_rate(event_entry)
        if derived_rate is not None:
            pricing_inputs["base_rate"] = derived_rate

    line_items: List[Dict[str, Any]] = []
    normalised_products: List[Dict[str, Any]] = []
    for product in event_entry.get("products", []):
        normalised = _normalise_product_fields(product, menu_names=menu_names)
        line_items.append(
            {
                "description": normalised["name"],
                "quantity": normalised["quantity"],
                "unit_price": normalised["unit_price"],
                "amount": normalised["quantity"] * normalised["unit_price"],
            }
        )
        normalised_products.append(normalised)
    if normalised_products:
        event_entry["products"] = normalised_products
    pricing_inputs["line_items"] = line_items
    if override_total is not None:
        try:
            pricing_inputs["total_amount"] = float(override_total)
        except (TypeError, ValueError):
            pricing_inputs.pop("total_amount", None)
    event_entry["pricing_inputs"] = pricing_inputs
    return pricing_inputs


# Old product ops functions removed in O1 refactoring - now imported from product_ops.py


# O3: _record_offer moved to compose.py


def _compose_offer_summary(event_entry: Dict[str, Any], total_amount: float, state: WorkflowState) -> List[str]:
    chosen_date = event_entry.get("chosen_date") or "Date TBD"
    room = event_entry.get("locked_room_id") or "Room TBD"
    link_date = event_entry.get("chosen_date") or (chosen_date if chosen_date != "Date TBD" else "")
    event_data = event_entry.get("event_data") or {}
    billing_details = event_entry.get("billing_details") or {}
    billing_address = format_billing_display(billing_details, event_data.get("Billing Address"))
    pricing_inputs = event_entry.get("pricing_inputs") or {}
    contact_parts = [
        part.strip()
        for part in (event_data.get("Name"), event_data.get("Company"))
        if isinstance(part, str) and part.strip() and part.strip().lower() != "not specified"
    ]
    email = (event_data.get("Email") or "").strip() or None
    if email and email.lower() != "not specified":
        contact_parts.append(email)
    products = event_entry.get("products") or []
    products_state = event_entry.get("products_state") or {}
    autofill_summary = products_state.get("autofill_summary") or {}
    matched_summary = autofill_summary.get("matched") or []
    product_alternatives = autofill_summary.get("alternatives") or []
    catering_alternatives = autofill_summary.get("catering_alternatives") or []
    if not catering_alternatives and not event_entry.get("selected_catering"):
        catering_alternatives = _default_menu_alternatives(event_entry)

    # Extract Q&A parameters for catering catalog link
    qna_extraction = state.extras.get("qna_extraction", {})
    q_values = qna_extraction.get("q_values", {})
    query_params: Dict[str, str] = {}

    # Extract date/month from Q&A detection
    if q_values.get("date_pattern"):
        query_params["month"] = str(q_values["date_pattern"]).lower()

    # Extract product attributes (vegetarian, vegan, wine pairing, etc.) from Q&A detection
    product_attrs = q_values.get("product_attributes") or []
    if isinstance(product_attrs, list):
        for attr in product_attrs:
            attr_lower = str(attr).lower()
            if "vegetarian" in attr_lower:
                query_params["vegetarian"] = "true"
            if "vegan" in attr_lower:
                query_params["vegan"] = "true"
            if "wine" in attr_lower or "pairing" in attr_lower:
                query_params["wine_pairing"] = "true"
            if ("three" in attr_lower or "3" in attr_lower) and "course" in attr_lower:
                query_params["courses"] = "3"

    intro_room = room if room != "Room TBD" else "your preferred room"
    intro_date = chosen_date if chosen_date != "Date TBD" else "your requested date"
    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))
    if manager_requested:
        lines = [
            f"Great, {intro_room} on {intro_date} is ready for manager review.",
            f"Offer draft for {chosen_date} · {room}",
        ]
    else:
        lines = [f"Offer draft for {chosen_date} · {room}"]

    spacer_added = False
    if contact_parts or billing_address:
        lines.append("")
        if contact_parts:
            lines.append("Client: " + " · ".join(contact_parts))
        if billing_address:
            lines.append(f"Billing address: {billing_address}")
        lines.append("")
        spacer_added = True

    room_rate = normalise_rate(pricing_inputs.get("base_rate"))
    if room_rate is None:
        room_rate = derive_room_rate(event_entry)
    if room_rate is not None:
        if not spacer_added:
            lines.append("")
        lines.append("**Room booking**")
        lines.append(f"- {room} · CHF {room_rate:,.2f}")
        spacer_added = True

    lines.append("")
    if matched_summary:
        lines.append("**Included products**")
        for entry in matched_summary:
            normalized = _normalise_product_fields(entry, menu_names=_menu_name_set())
            quantity = int(normalized.get("quantity") or 1)
            name = normalized.get("name") or "Unnamed item"
            unit_price = float(normalized.get("unit_price") or 0.0)
            unit = normalized.get("unit")
            total_line = float(entry.get("total") or quantity * unit_price)
            wish = entry.get("wish")

            price_text = f"CHF {total_line:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"
            elif unit == "per_event":
                price_text += " (per event)"

            details: List[str] = []
            if entry.get("match_pct") is not None:
                details.append(f"match {entry.get('match_pct')}%")
            if wish:
                details.append(f'for "{wish}"')
            detail_text = f" ({', '.join(details)})" if details else ""

            lines.append(f"- {quantity}× {name}{detail_text} · {price_text}")

    elif products:
        lines.append("**Included products**")
        for product in products:
            normalized = _normalise_product_fields(product, menu_names=_menu_name_set())
            quantity = int(normalized.get("quantity") or 1)
            name = normalized.get("name") or "Unnamed item"
            unit_price = float(normalized.get("unit_price") or 0.0)
            unit = normalized.get("unit")

            price_text = f"CHF {unit_price * quantity:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"
            elif unit == "per_event":
                price_text += " (per event)"

            lines.append(f"- {quantity}× {name} · {price_text}")
    else:
        lines.append("No optional products selected yet.")

    display_total = _determine_offer_total(event_entry, total_amount)

    # Add deposit info to the offer if enabled
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_required = deposit_info.get("deposit_required", False)
    deposit_amount = deposit_info.get("deposit_amount")
    deposit_due_date = deposit_info.get("deposit_due_date")

    lines.extend([
        "",
        "---",
        f"**Total: CHF {display_total:,.2f}**",
    ])

    # Add deposit info on separate lines after total (if enabled)
    if deposit_required and deposit_amount:
        lines.append("")  # Blank line before deposit section
        lines.append(f"**Deposit to reserve: CHF {deposit_amount:,.2f}** (required before confirmation)")
        if deposit_due_date:
            # Format date nicely (e.g., "12 January 2026" instead of "2026-01-12")
            try:
                due_dt = datetime.strptime(deposit_due_date, "%Y-%m-%d")
                formatted_due_date = due_dt.strftime("%d %B %Y")
            except (ValueError, TypeError):
                formatted_due_date = deposit_due_date
            lines.append("")  # Blank line to force new paragraph
            lines.append(f"**Deposit due by:** {formatted_due_date}")

    lines.extend([
        "---",
        "",
    ])

    selected_catering = event_entry.get("selected_catering")
    if not selected_catering and catering_alternatives:
        # Create snapshot for catering catalog with all alternatives
        catalog_snapshot_data = {
            "catering_alternatives": [dict(e) for e in catering_alternatives],
            "room": room,
            "date": link_date,
            "query_params": query_params,
        }
        catalog_snapshot_id = create_snapshot(
            snapshot_type="catering_catalog",
            data=catalog_snapshot_data,
            event_id=state.event_id,
            params=query_params,
        )
        catalog_link = generate_catering_catalog_link(query_params=query_params if query_params else None, snapshot_id=catalog_snapshot_id)
        lines.append("")
        lines.append(catalog_link)
        lines.append("Menu options you can add:")
        for entry in catering_alternatives:
            name = entry.get("name") or "Catering option"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit_label = (entry.get("unit") or "per event").replace("_", " ")
            # Create snapshot for individual menu
            menu_snapshot_data = {
                "menu": dict(entry),
                "name": name,
                "room": room,
                "date": link_date,
            }
            menu_snapshot_id = create_snapshot(
                snapshot_type="catering_menu",
                data=menu_snapshot_data,
                event_id=state.event_id,
                params={"menu": name, "room": room, "date": link_date},
            )
            menu_link = generate_catering_menu_link(name, room=room, date=link_date, snapshot_id=menu_snapshot_id)
            lines.append(f"- {name} · CHF {unit_price:,.2f} {unit_label}")
            lines.append(f"  {menu_link}")
        lines.append("")
        catering_alternatives = []

    has_alternatives = product_alternatives or catering_alternatives
    if has_alternatives:
        lines.append("**Suggestions for you**")
        lines.append("")

    if product_alternatives:
        lines.append("*Other close matches you can add:*")
        for entry in product_alternatives:
            name = entry.get("name") or "Unnamed add-on"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit = entry.get("unit")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            price_text = f"CHF {unit_price:,.2f}"
            if unit == "per_person":
                price_text += " per person"

            qualifiers: List[str] = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            qualifier_text = f" ({', '.join(qualifiers)})" if qualifiers else ""

            lines.append(f"- {name}{qualifier_text} · {price_text}")
        if catering_alternatives:
            lines.append("")

    if catering_alternatives:
        lines.append("*Catering alternatives with a close fit:*")
        for entry in catering_alternatives:
            name = entry.get("name") or "Catering option"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit_label = (entry.get("unit") or "per event").replace("_", " ")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            qualifiers: List[str] = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            detail = ", ".join(qualifiers)
            detail_text = f" ({detail})" if detail else ""

            lines.append(f"- {name}{detail_text} · CHF {unit_price:,.2f} {unit_label}")

    if has_alternatives:
        lines.append("")

    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))
    if manager_requested:
        lines.append("Please review and approve before sending to the manager.")
    else:
        lines.append("Please review and approve to confirm.")
    return lines


def _default_menu_alternatives(event_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return default dinner menu options as catering suggestions."""

    results: List[Dict[str, Any]] = []
    participants = event_entry.get("event_data", {}).get("Number of Participants")
    try:
        participants = int(participants) if participants is not None else None
    except (TypeError, ValueError):
        participants = None
    for menu in DINNER_MENU_OPTIONS:
        name = menu.get("menu_name")
        if not name:
            continue
        price = menu.get("price")
        try:
            unit_price = float(str(price).replace("CHF", "").strip())
        except (TypeError, ValueError):
            unit_price = None
        results.append(
            {
                "name": name,
                "unit_price": unit_price or 0.0,
                "unit": "per_event",
                "wish": "menu",
                "match_pct": 90,
                "quantity": 1,
            }
        )
    return results


# O3: _determine_offer_total moved to compose.py


def _step_name(step: int) -> str:
    mapping = {
        1: "Step1_Intake",
        2: "Step2_Date",
        3: "Step3_Room",
        4: "Step4_Offer",
        5: "Step5_Negotiation",
        6: "Step6_Transition",
        7: "Step7_Confirmation",
    }
    return mapping.get(step, f"Step{step}")


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state."""
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
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
