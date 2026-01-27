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

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Any, Callable, Dict, Optional, Tuple

from workflows.common.types import GroupResult, WorkflowState
from workflow.guards import evaluate as evaluate_guards
from workflows.planner import maybe_run_smart_shortcuts
from detection.pre_filter import pre_filter, PreFilterResult, is_enhanced_mode
from detection.unified import run_unified_detection, UnifiedDetectionResult, is_unified_mode
from domain import TaskType
from workflows.io.tasks import enqueue_task
from workflows.io.config_store import get_manager_names
from workflows.common.billing_capture import capture_billing_anytime, add_billing_validation_draft
from workflows.common.capture import capture_fields_anytime


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

# User-friendly guidance for what action is expected at each step (F-04 fix)
STEP_GUIDANCE: Dict[int, str] = {
    1: "We're waiting for details about your event (date, number of guests, etc.).",
    2: "We're waiting for you to confirm your preferred event date.",
    3: "We're checking room availability for your requested date.",
    4: "We've sent you an offer - please let us know if you'd like to accept, decline, or discuss changes.",
    5: "We're in negotiation - please respond to the current offer discussion.",
    6: "We're finalizing the booking details.",
    7: "Your booking is confirmed! Let us know if you have any questions.",
}


# =============================================================================
# OOC EVIDENCE GUARDS
# =============================================================================

_DATE_EVIDENCE_PATTERN = re.compile(
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_MONTH_TOKENS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_WEEKDAY_TOKENS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
_COUNTER_KEYWORDS = ("counter", "discount", "lower", "cheaper", "price", "budget", "instead")
_CURRENCY_TOKENS = ("chf", "eur", "usd", "$")


def _get_pre_filter_signals(state: WorkflowState) -> Dict[str, bool]:
    pre_filter = (state.extras or {}).get("pre_filter")
    if isinstance(pre_filter, dict):
        signals = pre_filter.get("signals")
        if isinstance(signals, dict):
            return signals
    return {}


def _has_date_evidence(
    text: str,
    unified_result: Optional[UnifiedDetectionResult],
) -> bool:
    if unified_result and (unified_result.date or unified_result.date_text):
        return True
    if not text:
        return False
    text_lower = text.lower()
    if _DATE_EVIDENCE_PATTERN.search(text_lower):
        return True
    if any(token in text_lower for token in _MONTH_TOKENS):
        return True
    if any(token in text_lower for token in _WEEKDAY_TOKENS):
        return True
    return False


def _has_counter_evidence(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    if any(token in text_lower for token in _CURRENCY_TOKENS):
        return True
    if any(token in text_lower for token in _COUNTER_KEYWORDS) and re.search(r"\b\d{2,}\b", text_lower):
        return True
    if re.search(r"\b(can|could|would)\s+you\s+do\s+\d", text_lower):
        return True
    return False


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

    # Get registered manager names from config (for escalation detection)
    manager_names = get_manager_names()
    registered_manager_names = manager_names if manager_names else None

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

        logger.debug(
            "[UNIFIED_DETECTION] intent=%s, manager=%s, conf=%s, qna_types=%s",
            unified_result.intent, unified_result.is_manager_request,
            unified_result.is_confirmation, unified_result.qna_types
        )
        print(f"[UNIFIED_DETECTION] is_acceptance={unified_result.is_acceptance}, is_question={unified_result.is_question}, is_change={unified_result.is_change_request}")
        logger.debug(
            "[UNIFIED_DETECTION] is_acceptance=%s, is_question=%s, is_change=%s",
            unified_result.is_acceptance, unified_result.is_question,
            unified_result.is_change_request
        )

    # Log in enhanced mode
    if is_enhanced_mode() and pre_result.matched_patterns:
        logger.debug("[PRE_FILTER] Mode=enhanced, signals=%s", pre_result.matched_patterns[:5])
        if pre_result.can_skip_intent_llm:
            logger.debug("[PRE_FILTER] Can skip intent LLM (pure confirmation)")

    return pre_result, unified_result


def is_out_of_context(
    unified_result: Optional[UnifiedDetectionResult],
    current_step: Optional[int],
    event_entry: Optional[Dict[str, Any]] = None,
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
        event_entry: Current event entry (for site visit state check)

    Returns:
        True if intent is out of context and should be silently ignored
    """
    if unified_result is None or current_step is None:
        return False

    intent = unified_result.intent

    # Always-valid intents are never out of context
    if intent in ALWAYS_VALID_INTENTS:
        return False

    # GUARD: When site visit flow is active, date-related intents are for site visit
    # selection, not event date confirmation. Pass through to router for site visit handler.
    if event_entry:
        from workflows.common.site_visit_state import is_site_visit_active
        if is_site_visit_active(event_entry):
            if intent in {"confirm_date", "confirm_date_partial"}:
                logger.debug("[OOC_CHECK] Site visit active - bypassing OOC for date intent")
                return False

    # Room selection messages should never be treated as out-of-context
    # even if misclassified as confirm_date (common LLM confusion)
    if unified_result.room_preference:
        return False

    # Offer-stage confirmations can be misclassified as confirm_date.
    # Let Step 4/5 handlers decide instead of blocking early.
    if intent in {"confirm_date", "confirm_date_partial"} and current_step in {4, 5}:
        if unified_result.is_confirmation or unified_result.is_acceptance:
            logger.debug(
                "[OOC_CHECK] Treating confirmation as in-context at step %s",
                current_step,
            )
            return False

    # Check if this intent has step restrictions
    valid_steps = INTENT_VALID_STEPS.get(intent)
    if valid_steps is None:
        # Not in the mapping = valid at all steps
        return False

    # Intent has step restrictions - check if current step is valid
    if current_step not in valid_steps:
        logger.warning("[OUT_OF_CONTEXT] Intent '%s' is only valid at steps %s, but current step is %s",
                      intent, valid_steps, current_step)
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
    # Continuation messages bypass out-of-context check entirely
    # These are system-triggered after HIL approval to advance the workflow
    if state.message and (state.message.extras or {}).get("is_continuation"):
        logger.debug("[OOC_CHECK] Skipping check - continuation message")
        return None

    # Deposit payment messages bypass out-of-context check
    # These are synthetic messages from the Pay Deposit button that trigger Step 7
    if state.message and (state.message.extras or {}).get("deposit_just_paid"):
        logger.debug("[OOC_CHECK] Skipping check - deposit_just_paid message")
        return None

    if not state.event_entry:
        return None

    # Billing details should be captured even if intent looks out-of-context
    if (state.user_info or {}).get("billing_address"):
        logger.debug("[OOC_CHECK] Skipping check - billing_address present")
        return None
    if unified_result and unified_result.billing_address:
        logger.debug("[OOC_CHECK] Skipping check - billing_address detected by unified LLM")
        return None
    pre_filter_signals = _get_pre_filter_signals(state)
    if pre_filter_signals.get("billing"):
        logger.debug("[OOC_CHECK] Skipping check - billing signal present")
        return None

    # Bypass OOC check when waiting for "continue without product" response
    # Step 3 has its own LLM detection for this flow
    if state.event_entry.get("sourcing_declined"):
        logger.debug("[OOC_CHECK] Skipping check - waiting for sourcing_declined response")
        return None

    current_step = state.event_entry.get("current_step")
    intent = unified_result.intent if unified_result else None
    logger.debug("[OOC_CHECK] intent=%s, current_step=%s", intent, current_step)

    message_text = (state.message.body or "") if state.message else ""
    if intent in {"confirm_date", "confirm_date_partial"} and not _has_date_evidence(message_text, unified_result):
        logger.debug("[OOC_CHECK] Skipping check - no date evidence for intent %s", intent)
        return None
    if intent == "accept_offer":
        has_acceptance = pre_filter_signals.get("acceptance", False)
        if unified_result and unified_result.is_acceptance:
            has_acceptance = True
        if not has_acceptance:
            logger.debug("[OOC_CHECK] Skipping check - no acceptance evidence")
            return None
    if intent == "decline_offer":
        has_rejection = pre_filter_signals.get("rejection", False)
        if unified_result and unified_result.is_rejection:
            has_rejection = True
        if not has_rejection:
            logger.debug("[OOC_CHECK] Skipping check - no rejection evidence")
            return None
    if intent == "counter_offer" and not _has_counter_evidence(message_text):
        logger.debug("[OOC_CHECK] Skipping check - no counter evidence")
        return None

    if not is_out_of_context(unified_result, current_step, state.event_entry):
        return None

    # Log the out-of-context detection
    intent = unified_result.intent if unified_result else "unknown"
    logger.warning("[PRE_ROUTE] Out-of-context message detected - providing guidance")

    from debug.hooks import trace_marker
    trace_marker(
        state.thread_id or "unknown",
        "OUT_OF_CONTEXT_GUIDED",
        detail=f"Intent '{intent}' not valid at step {current_step}",
        owner_step=f"Step{current_step}",
    )

    # Build a helpful guidance message instead of silent ignore (F-04 fix)
    # This helps users understand what action the system is waiting for
    guidance = STEP_GUIDANCE.get(current_step or 1, "We're processing your request.")
    guidance_message = f"Thanks for your message! {guidance}"

    # Add draft message to state so it gets included in the response
    state.add_draft_message({
        "body_markdown": guidance_message,
        "topic": "out_of_context_guidance",
    })

    ooc_response = GroupResult(
        action="out_of_context_guided",  # Changed from _ignored to _guided
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

    # Skip manager escalation for system continuation messages (e.g., after HIL approval)
    # These are workflow-triggered, not actual client requests
    if state.message and (state.message.extras or {}).get("is_continuation"):
        logger.debug("[MANAGER_ESCALATION] Skipping - continuation message")
        return None

    # [BILLING FLOW BYPASS] Skip manager escalation during billing capture flow
    # When client is providing billing address, don't misclassify as manager request
    # This follows Pattern 1: Special Flow State Detection from CLAUDE.md
    if state.event_entry:
        in_billing_flow = (
            state.event_entry.get("offer_accepted")
            and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        )
        if in_billing_flow:
            logger.debug("[MANAGER_ESCALATION] Skipping - billing flow active")
            return None

    if not unified_result.is_manager_request:
        return None

    logger.info("[PRE_ROUTE] Manager escalation detected - creating HIL task")

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
    from workflows.io.database import lock_path_for, save_db

    task_id = enqueue_task(
        state.db,
        TaskType.MESSAGE_MANAGER,
        client_id,
        event_id,
        task_payload,
    )
    # Save the updated database
    save_db(state.db, state.db_path, lock_path_for(state.db_path))

    logger.info("[PRE_ROUTE] Created manager escalation task: %s", task_id)

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

    from debug.hooks import trace_marker
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

    Note: Skip duplicate detection for very short messages (< 30 chars) since these
    are likely subject-only messages (e.g., "Re: Room Booking") which are commonly
    reused in email threads and shouldn't trigger duplicate detection.
    """
    if not state.event_entry:
        return None

    last_client_msg = state.event_entry.get("last_client_message", "")
    normalized_current = combined_text.strip().lower()
    normalized_last = (last_client_msg or "").strip().lower()

    # Skip duplicate detection for very short messages (likely subject-only)
    # Email subjects are commonly reused in threads
    MIN_LENGTH_FOR_DUPLICATE_CHECK = 30
    if len(normalized_current) < MIN_LENGTH_FOR_DUPLICATE_CHECK:
        # Still store the message, just don't check for duplicates
        state.event_entry["last_client_message"] = combined_text.strip()
        state.extras["persist"] = True
        return None

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
            from debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel

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
        logger.debug("[WF][GUARDS] Deposit bypass: forcing step 5 for event %s", event_id)
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
        logger.debug("[WF][GUARDS] Billing flow active: skipping guard forcing for event %s", event_id)
        return  # Skip guard logic during billing flow - step should remain at 5

    # Apply requirements_hash update if changed
    if guard_snapshot.requirements_hash_changed and guard_snapshot.requirements_hash:
        logger.debug("[WF][GUARDS] Requirements hash updated: %s", guard_snapshot.requirements_hash)
        state.event_entry["requirements_hash"] = guard_snapshot.requirements_hash
        state.extras["persist"] = True

    # Apply forced step if needed (step 2, 3, or 4 guard)
    if guard_snapshot.forced_step is not None:
        current = state.event_entry.get("current_step")
        logger.debug("[WF][GUARDS] Forcing step from %s to %s", current, guard_snapshot.forced_step)
        state.event_entry["current_step"] = guard_snapshot.forced_step

        # Set caller_step for detours: when forcing to a lower step (2 or 3) from a higher step,
        # record the current step so we can return there after the detour completes.
        # This ensures proper return after date/room changes.
        existing_caller = state.event_entry.get("caller_step")
        if existing_caller is None and current and current > guard_snapshot.forced_step:
            state.event_entry["caller_step"] = current
            logger.debug("[WF][GUARDS] Setting caller_step=%s for detour return", current)

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
        logger.debug("[WF][BILLING_FIX] Correcting step from %s to 5 for billing flow", stored_step)
        state.event_entry["current_step"] = 5
        state.extras["persist"] = True
    elif in_billing_flow:
        logger.debug("[WF][BILLING_FLOW] Already at step 5, proceeding with billing flow")


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

    # 0.1. PARTICIPANTS CAPTURE-ANYTIME: Capture participant count at ANY workflow step
    # This ensures guest count changes (e.g., "Actually 60 guests instead of 30") are persisted
    # so Step 3 can properly evaluate room capacity
    if unified_result and unified_result.participants:
        event_entry = state.event_entry or {}
        current_participants = event_entry.get("participants")
        new_participants = unified_result.participants

        # Only update if changed (or not set)
        if new_participants != current_participants:
            event_entry["participants"] = new_participants
            # Also update requirements dict for consistency with intake extraction
            requirements = event_entry.setdefault("requirements", {})
            requirements["participants"] = new_participants
            requirements["number_of_participants"] = new_participants
            logger.info(
                "[PRE_ROUTE] Participants captured: %s -> %s (from unified detection)",
                current_participants, new_participants
            )

    # 0.3. BILLING CAPTURE-ANYTIME: Capture billing at ANY workflow step
    # This runs BEFORE OOC check so billing is always captured regardless of intent
    # Uses pre-filter signals ($0) first, then LLM structured data if available
    pre_filter_signals = {
        "billing": pre_filter_result.has_billing_signal,
        "confirmation": pre_filter_result.has_confirmation_signal,
        "acceptance": pre_filter_result.has_acceptance_signal,
        "rejection": pre_filter_result.has_rejection_signal,
    }
    billing_capture_result = capture_billing_anytime(
        state=state,
        unified_result=unified_result,
        pre_filter_signals=pre_filter_signals,
        message_text=combined_text,
    )
    if billing_capture_result.captured:
        logger.info(
            "[PRE_ROUTE] Billing captured (complete=%s, missing=%s)",
            billing_capture_result.complete,
            billing_capture_result.missing_fields,
        )
        # Store result for downstream handlers to potentially prompt for missing fields
        state.extras["billing_capture_result"] = {
            "captured": billing_capture_result.captured,
            "complete": billing_capture_result.complete,
            "missing_fields": billing_capture_result.missing_fields,
            "source": billing_capture_result.source,
        }

        # IMMEDIATE VALIDATION: If billing incomplete, add prompt for missing fields
        # This provides instant feedback rather than waiting for a later step
        if not billing_capture_result.complete:
            add_billing_validation_draft(state, billing_capture_result)
            logger.debug(
                "[PRE_ROUTE] Added billing validation prompt (missing: %s)",
                billing_capture_result.missing_fields,
            )

    # NOTE: Manager escalation handling REMOVED (2026-01-14)
    # In this venue booking system, the AI assistant IS the manager's representative.
    # Special requests go through HIL approval, not a separate "speak with manager" flow.
    # The escalation feature was causing false positives on billing addresses.
    # If you need this feature, see handle_manager_escalation() in this file.

    # 0.4. GLOBAL FIELD CAPTURE: Capture date/room/time/contact at ANY step
    # This ensures fields are captured regardless of which step we're at.
    # Similar to billing capture - piggybacks on unified detection (zero extra LLM cost).
    if unified_result:
        current_step_for_capture = (state.event_entry or {}).get("current_step", 1)
        field_capture_result = capture_fields_anytime(
            state=state,
            unified_result=unified_result,
            current_step=current_step_for_capture,
        )
        if field_capture_result.captured:
            logger.debug(
                "[PRE_ROUTE] Fields captured at step %s: %s",
                current_step_for_capture,
                field_capture_result.fields,
            )

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
    logger.debug("[WF][PRE_ROUTE] About to enter routing loop, event_entry exists=%s",
                state.event_entry is not None)
    if state.event_entry:
        logger.debug("[WF][PRE_ROUTE] current_step=%s, offer_accepted=%s",
                    state.event_entry.get('current_step'), state.event_entry.get('offer_accepted'))

    # Continue to router
    return None, intake_result
