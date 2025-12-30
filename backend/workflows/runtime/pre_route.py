"""Pre-routing pipeline for workflow message processing.

Extracted from workflow_email.py as part of P1 refactoring (Dec 2025).
Contains pre-routing checks that run after intake but before the step router:
- Pre-filter (unified keyword/signal detection)
- Duplicate message detection
- Post-intake halt handling
- Guard evaluation
- Smart shortcuts
- Billing flow step correction
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflow.guards import evaluate as evaluate_guards
from backend.workflows.planner import maybe_run_smart_shortcuts
from backend.detection.pre_filter import pre_filter, PreFilterResult, is_enhanced_mode
from backend.detection.unified import run_unified_detection, UnifiedDetectionResult, is_unified_mode
from backend.domain import TaskType
from backend.workflows.io.tasks import enqueue_task


# =============================================================================
# OUT-OF-CONTEXT INTENT MAPPING
# =============================================================================
# Maps intents to the steps where they're valid.
# Intents not in this map are considered valid at ALL steps (e.g., general_qna).
# If an intent is detected at an invalid step, it's "out of context" → no response.

INTENT_VALID_STEPS: Dict[str, set] = {
    # Date confirmation is only valid at step 2 (or as a change at later steps)
    "confirm_date": {2},
    "confirm_date_partial": {2},
    # Offer-related intents are only valid at steps 4-5
    "accept_offer": {4, 5},
    "decline_offer": {4, 5},
    "counter_offer": {4, 5},
}

# Intents that should NEVER be treated as out-of-context
# These represent cross-cutting concerns that can happen at any step
ALWAYS_VALID_INTENTS = {
    "event_request",  # New booking requests are always valid
    "edit_date",  # Date changes can happen at any step
    "edit_room",  # Room changes can happen at any step
    "edit_requirements",  # Requirement changes can happen at any step
    "message_manager",  # Manager requests are always valid
    "general_qna",  # Q&A is always valid
    "non_event",  # Non-event messages need other handling
}


# Type aliases for callback functions
PersistFn = Callable[[WorkflowState, Path, Path], None]
DebugFn = Callable[[str, WorkflowState, Optional[Dict[str, Any]]], None]
FinalizeFn = Callable[[GroupResult, WorkflowState, Path, Path], Dict[str, Any]]


def run_unified_pre_filter(
    state: WorkflowState,
    combined_text: str,
) -> Tuple[PreFilterResult, Optional[UnifiedDetectionResult]]:
    """Run the unified pre-filter and LLM detection on the incoming message.

    This runs two detection layers:
    1. Pre-filter ($0 regex): Duplicates, billing patterns - deterministic
    2. Unified LLM (~$0.004): Semantic signals - manager, confirmation, intent

    Results are stored in state.extras for downstream use.

    Args:
        state: Current workflow state
        combined_text: Combined subject + body text

    Returns:
        Tuple of (PreFilterResult, UnifiedDetectionResult or None)
    """
    # Get last message for duplicate detection
    last_message = None
    if state.event_entry:
        last_message = state.event_entry.get("last_client_message")

    # Get registered manager names if available (for escalation detection)
    # TODO: Load from client/venue config when available
    registered_manager_names = None

    # Run the pre-filter (regex only - $0 cost)
    pre_result = pre_filter(
        message=combined_text,
        last_message=last_message,
        event_entry=state.event_entry,
        registered_manager_names=registered_manager_names,
    )

    # Store pre-filter result
    state.extras["pre_filter"] = pre_result.to_dict()
    state.extras["pre_filter_mode"] = "enhanced" if is_enhanced_mode() else "legacy"

    # Run unified LLM detection for semantic signals (manager, confirmation, intent)
    # This is where semantic understanding happens (e.g., "Can I speak with someone?")
    unified_result: Optional[UnifiedDetectionResult] = None

    if is_unified_mode():
        # Extract context from event_entry for better detection
        current_step = None
        date_confirmed = False
        room_locked = False
        last_topic = None

        if state.event_entry:
            current_step = state.event_entry.get("current_step")
            date_confirmed = state.event_entry.get("date_confirmed", False)
            room_locked = state.event_entry.get("locked_room_id") is not None
            thread_state = state.event_entry.get("thread_state") or {}
            # Defensive: thread_state might be a string in some legacy data
            if isinstance(thread_state, dict):
                last_topic = thread_state.get("last_topic")
            else:
                last_topic = None

        unified_result = run_unified_detection(
            combined_text,
            current_step=current_step,
            date_confirmed=date_confirmed,
            room_locked=room_locked,
            last_topic=last_topic,
        )

        # Store unified detection result
        state.extras["unified_detection"] = unified_result.to_dict()

        print(f"[UNIFIED_DETECTION] intent={unified_result.intent}, manager={unified_result.is_manager_request}, conf={unified_result.is_confirmation}, qna_types={unified_result.qna_types}")

    # Log in enhanced mode
    if is_enhanced_mode() and pre_result.matched_patterns:
        print(f"[PRE_FILTER] Mode=enhanced, signals={pre_result.matched_patterns[:5]}")
        if pre_result.can_skip_intent_llm:
            print(f"[PRE_FILTER] Can skip intent LLM (pure confirmation)")

    return pre_result, unified_result


def is_out_of_context(
    unified_result: Optional[UnifiedDetectionResult],
    current_step: Optional[int],
) -> bool:
    """Check if the detected intent is out of context for the current step.

    An intent is "out of context" when:
    1. It's a step-specific intent (in INTENT_VALID_STEPS)
    2. The current step is NOT in the valid steps for that intent

    Out-of-context messages should receive NO response - the workflow
    only responds when the client takes the right action for their current step.

    Args:
        unified_result: Result from unified LLM detection
        current_step: Current workflow step (1-7)

    Returns:
        True if intent is out of context and should be silently ignored
    """
    if unified_result is None or current_step is None:
        return False

    intent = unified_result.intent

    # Always-valid intents are never out of context
    if intent in ALWAYS_VALID_INTENTS:
        return False

    # Check if this intent has step restrictions
    valid_steps = INTENT_VALID_STEPS.get(intent)
    if valid_steps is None:
        # Not in the mapping = valid at all steps
        return False

    # Intent has step restrictions - check if current step is valid
    if current_step not in valid_steps:
        print(f"[OUT_OF_CONTEXT] Intent '{intent}' is only valid at steps {valid_steps}, but current step is {current_step}")
        return True

    return False


def check_out_of_context(
    state: WorkflowState,
    unified_result: Optional[UnifiedDetectionResult],
    path: Path,
    lock_path: Path,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Check if the message is out of context and should be silently ignored.

    Out-of-context messages are step-specific actions sent at the wrong step.
    For example:
    - "I confirm the date" at step 5 (negotiation) - date confirmation is step 2
    - "I accept the offer" at step 2 (date confirmation) - offer acceptance is step 4-5

    These are NOT nonsense (gibberish) - they're valid actions at the wrong step.
    The workflow does not respond, waiting for the client to take the correct action.

    Returns finalized "no response" if out of context, None otherwise.
    """
    if not state.event_entry:
        return None

    current_step = state.event_entry.get("current_step")
    intent = unified_result.intent if unified_result else None
    print(f"[OOC_CHECK] intent={intent}, current_step={current_step}")

    if not is_out_of_context(unified_result, current_step):
        return None

    # Log the out-of-context detection
    intent = unified_result.intent if unified_result else "unknown"
    print(f"[PRE_ROUTE] Out-of-context message detected - no response")

    from backend.debug.hooks import trace_marker
    trace_marker(
        state.thread_id,
        "OUT_OF_CONTEXT_IGNORED",
        detail=f"Intent '{intent}' not valid at step {current_step}",
        owner_step=f"Step{current_step}",
    )

    # Return a "no response" result - workflow stays at current step, no message sent
    ooc_response = GroupResult(
        action="out_of_context_ignored",
        halt=True,
        payload={
            "reason": "step_mismatch",
            "intent": intent,
            "current_step": current_step,
            "valid_steps": list(INTENT_VALID_STEPS.get(intent, set())),
        },
    )

    return finalize_fn(ooc_response, state, path, lock_path)


def handle_manager_escalation(
    state: WorkflowState,
    unified_result: Optional[UnifiedDetectionResult],
    path: Path,
    lock_path: Path,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Handle manager escalation requests detected by LLM semantic analysis.

    Uses unified LLM detection (Gemini) for semantic understanding of manager
    requests like "Can I speak with someone?" rather than regex keywords.

    When a client asks to speak with a manager/human, we:
    1. Create a MESSAGE_MANAGER HIL task for manager review
    2. Return a response acknowledging the request

    Args:
        state: Current workflow state
        unified_result: Result from LLM unified detection with is_manager_request
        path: Database file path
        lock_path: Database lock file path
        finalize_fn: Callback to finalize and return result

    Returns:
        Finalized response if escalation detected, None otherwise
    """
    # Use LLM-based detection for semantic understanding
    # This correctly handles phrases like "Can I speak with someone?" without
    # false positives on email addresses like "test-manager@example.com"
    if unified_result is None:
        return None

    if not unified_result.is_manager_request:
        return None

    print(f"[PRE_ROUTE] Manager escalation detected - creating HIL task")

    # Get client and event info
    client_id = state.client_id or "unknown"
    event_id = state.event_entry.get("event_id") if state.event_entry else None
    thread_id = state.thread_id

    # Build task payload with context
    task_payload = {
        "snippet": (state.message.body[:200] if state.message and state.message.body else ""),
        "thread_id": thread_id,
        "step_id": state.event_entry.get("current_step") if state.event_entry else 1,
        "reason": "client_requested_manager",
        "event_summary": None,
    }

    # Add event summary if we have an event
    if state.event_entry:
        task_payload["event_summary"] = {
            "client_name": state.event_entry.get("client_name", "Not specified"),
            "email": client_id,
            "chosen_date": state.event_entry.get("chosen_date"),
            "locked_room": state.event_entry.get("locked_room_id"),
            "current_step": state.event_entry.get("current_step", 1),
        }

    # Create task using the db from state (already loaded)
    from backend.workflows.io.database import lock_path_for, save_db

    task_id = enqueue_task(
        state.db,
        TaskType.MESSAGE_MANAGER,
        client_id,
        event_id,
        task_payload,
    )
    # Save the updated database
    save_db(state.db, state.db_path, lock_path_for(state.db_path))

    print(f"[PRE_ROUTE] Created manager escalation task: {task_id}")

    # Set flag on event for downstream handlers
    if state.event_entry:
        flags = state.event_entry.setdefault("flags", {})
        flags["manager_requested"] = True
        state.extras["persist"] = True

    # Add acknowledgment draft message
    draft_message = {
        "body_markdown": (
            "I understand you'd like to speak with a manager. "
            "I've forwarded your request to our team, and someone will be in touch with you shortly. "
            "In the meantime, is there anything else I can help you with regarding your booking?"
        ),
        "step": state.event_entry.get("current_step", 1) if state.event_entry else 1,
        "topic": "manager_escalation",
        "requires_approval": False,  # This response doesn't need HIL approval
    }
    state.add_draft_message(draft_message)

    # Return response indicating escalation handled
    escalation_response = GroupResult(
        action="manager_escalation",
        halt=True,
        payload={
            "task_id": task_id,
            "topic": "manager_escalation",
        },
    )

    from backend.debug.hooks import trace_marker
    trace_marker(
        state.thread_id,
        "MANAGER_ESCALATION_DETECTED",
        detail=f"Created HIL task {task_id} for manager review",
        owner_step=f"Step{state.event_entry.get('current_step', 1) if state.event_entry else 1}",
    )

    return finalize_fn(escalation_response, state, path, lock_path)


def check_duplicate_message(
    state: WorkflowState,
    combined_text: str,
    path: Path,
    lock_path: Path,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Check if client sent the exact same message twice in a row.

    Returns finalized response if duplicate detected, None otherwise.
    Also stores current message for next comparison.
    """
    if not state.event_entry:
        return None

    last_client_msg = state.event_entry.get("last_client_message", "")
    normalized_current = combined_text.strip().lower()
    normalized_last = (last_client_msg or "").strip().lower()

    # Only check for duplicates if we have a previous message and messages are identical
    if normalized_last and normalized_current == normalized_last:
        # Don't flag as duplicate if this is a detour return or offer update flow
        is_detour = state.event_entry.get("caller_step") is not None
        current_step = state.event_entry.get("current_step", 1)
        # Don't flag as duplicate during billing flow - client may resend billing info
        in_billing_flow = (
            state.event_entry.get("offer_accepted")
            and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        )

        if not is_detour and not in_billing_flow and current_step >= 2:
            # Return friendly "same message" response instead of processing
            duplicate_response = GroupResult(
                action="duplicate_message",
                halt=True,
                payload={
                    "draft": {
                        "body_markdown": (
                            "I notice this is the same message as before. "
                            "Is there something specific you'd like to add or clarify? "
                            "I'm happy to help with any questions or changes."
                        ),
                        "hil_required": False,
                    },
                },
            )
            from backend.debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel

            trace_marker(
                state.thread_id,
                "DUPLICATE_MESSAGE_DETECTED",
                detail="Client sent identical message twice in a row",
                owner_step=f"Step{current_step}",
            )
            return finalize_fn(duplicate_response, state, path, lock_path)

    # Store current message for next comparison (only if not a duplicate)
    state.event_entry["last_client_message"] = combined_text.strip()
    state.extras["persist"] = True
    return None


def evaluate_pre_route_guards(state: WorkflowState) -> None:
    """Evaluate guards and apply metadata decisions.

    P2 refactoring: Guards are now pure - this function applies their decisions.
    The guard snapshot contains:
    - forced_step: Step to force if different from current
    - requirements_hash_changed: Whether requirements_hash was recomputed
    - deposit_bypass: Whether deposit payment bypass is active (force step 5)
    - candidate_dates: Dates to suggest for step 2
    """
    guard_snapshot = evaluate_guards(state)

    if not state.event_entry:
        return

    event_id = state.event_entry.get("event_id")

    # Apply deposit bypass - force step 5 for deposit flow
    if guard_snapshot.deposit_bypass and guard_snapshot.forced_step == 5:
        print(f"[WF][GUARDS] Deposit bypass: forcing step 5 for event {event_id}")
        state.event_entry["current_step"] = 5
        state.extras["persist"] = True
        return  # Skip other guard logic during deposit flow

    # [BILLING FLOW BYPASS] Skip guard forcing during billing flow
    # This follows Pattern 1: Special Flow State Detection from CLAUDE.md
    in_billing_flow = (
        state.event_entry.get("offer_accepted")
        and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    if in_billing_flow:
        print(f"[WF][GUARDS] Billing flow active: skipping guard forcing for event {event_id}")
        return  # Skip guard logic during billing flow - step should remain at 5

    # Apply requirements_hash update if changed
    if guard_snapshot.requirements_hash_changed and guard_snapshot.requirements_hash:
        print(f"[WF][GUARDS] Requirements hash updated: {guard_snapshot.requirements_hash}")
        state.event_entry["requirements_hash"] = guard_snapshot.requirements_hash
        state.extras["persist"] = True

    # Apply forced step if needed (step 2, 3, or 4 guard)
    if guard_snapshot.forced_step is not None:
        current = state.event_entry.get("current_step")
        print(f"[WF][GUARDS] Forcing step from {current} to {guard_snapshot.forced_step}")
        state.event_entry["current_step"] = guard_snapshot.forced_step
        state.extras["persist"] = True

    # Store candidate dates for step 2
    if guard_snapshot.step2_required and guard_snapshot.candidate_dates:
        state.extras["guard_candidate_dates"] = list(guard_snapshot.candidate_dates)


def try_smart_shortcuts(
    state: WorkflowState,
    path: Path,
    lock_path: Path,
    debug_fn: DebugFn,
    persist_fn: PersistFn,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Try to run smart shortcuts.

    Returns finalized response if shortcut fired, None otherwise.
    """
    shortcut_result = maybe_run_smart_shortcuts(state)
    if shortcut_result is not None:
        debug_fn(
            "smart_shortcut",
            state,
            {"shortcut_action": shortcut_result.action},
        )
        persist_fn(state, path, lock_path)
        return finalize_fn(shortcut_result, state, path, lock_path)
    return None


def correct_billing_flow_step(state: WorkflowState) -> None:
    """Force step=5 when in billing flow.

    This handles cases where step was incorrectly set before billing flow started.
    """
    if not state.event_entry:
        return

    in_billing_flow = (
        state.event_entry.get("offer_accepted")
        and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    stored_step = state.event_entry.get("current_step")

    if in_billing_flow and stored_step != 5:
        print(f"[WF][BILLING_FIX] Correcting step from {stored_step} to 5 for billing flow")
        state.event_entry["current_step"] = 5
        state.extras["persist"] = True
    elif in_billing_flow:
        print(f"[WF][BILLING_FLOW] Already at step 5, proceeding with billing flow")


def run_pre_route_pipeline(
    state: WorkflowState,
    intake_result: GroupResult,
    combined_text: str,
    path: Path,
    lock_path: Path,
    *,
    persist_fn: PersistFn,
    debug_fn: DebugFn,
    finalize_fn: FinalizeFn,
) -> Tuple[Optional[Dict[str, Any]], GroupResult]:
    """Run the complete pre-routing pipeline.

    Executes all pre-routing checks after intake:
    0. Unified pre-filter (keyword/signal detection)
    0.5. Manager escalation handling (creates HIL task if manager requested)
    1. Duplicate message detection
    2. Post-intake halt check
    3. Guard evaluation
    4. Smart shortcuts
    5. Billing flow step correction

    Args:
        state: Current workflow state
        intake_result: Result from intake step
        combined_text: Combined subject + body text
        path: Database file path
        lock_path: Database lock file path
        persist_fn: Callback to persist state
        debug_fn: Callback for debug logging
        finalize_fn: Callback to finalize and return result

    Returns:
        Tuple of (early_return, last_result) where:
        - early_return is the Dict to return if pipeline short-circuited, or None to continue
        - last_result is the intake result (unchanged if continuing to router)
    """
    # 0. Unified pre-filter + LLM detection (runs before all other checks)
    # - Pre-filter: $0 regex for duplicates, billing patterns
    # - Unified LLM: Semantic signals (manager, confirmation, intent)
    pre_filter_result, unified_result = run_unified_pre_filter(state, combined_text)

    # 0.5. Manager escalation check (before duplicate detection)
    # Uses LLM-based semantic detection for phrases like "Can I speak with someone?"
    # This avoids regex false positives on emails like "test-manager@example.com"
    escalation_result = handle_manager_escalation(
        state, unified_result, path, lock_path, finalize_fn
    )
    if escalation_result is not None:
        return escalation_result, intake_result

    # 0.6. Out-of-context check - step-specific intents at wrong steps
    # Example: "I confirm the date" at step 5 (negotiation) → silently ignored
    # This is NOT nonsense - it's a valid action at the wrong step
    ooc_result = check_out_of_context(
        state, unified_result, path, lock_path, finalize_fn
    )
    if ooc_result is not None:
        return ooc_result, intake_result

    # 1. Duplicate message detection (now uses pre-filter result if in enhanced mode)
    # In enhanced mode, pre_filter_result.is_duplicate is already computed
    duplicate_result = check_duplicate_message(state, combined_text, path, lock_path, finalize_fn)
    if duplicate_result is not None:
        return duplicate_result, intake_result

    # 2. Post-intake halt check
    persist_fn(state, path, lock_path)
    if intake_result.halt:
        debug_fn("halt_post_intake", state, None)
        return finalize_fn(intake_result, state, path, lock_path), intake_result

    # 3. Guard evaluation
    evaluate_pre_route_guards(state)

    # 4. Smart shortcuts
    shortcut_response = try_smart_shortcuts(
        state, path, lock_path, debug_fn, persist_fn, finalize_fn
    )
    if shortcut_response is not None:
        return shortcut_response, intake_result

    # 5. Billing flow step correction
    correct_billing_flow_step(state)

    # Pre-route debug logging
    print(f"[WF][PRE_ROUTE] About to enter routing loop, event_entry exists={state.event_entry is not None}")
    if state.event_entry:
        print(f"[WF][PRE_ROUTE] current_step={state.event_entry.get('current_step')}, offer_accepted={state.event_entry.get('offer_accepted')}")

    # Continue to router
    return None, intake_result
