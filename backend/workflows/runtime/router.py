"""Step router for workflow message processing.

Extracted from workflow_email.py as part of W3 refactoring (Dec 2025).
Contains the main step dispatching loop that routes messages through Steps 2-7.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from backend.detection.unified import UnifiedDetectionResult
from backend.workflows.common.site_visit_handler import (
    handle_site_visit_request,
    is_site_visit_intent,
)
from backend.workflows.common.site_visit_state import is_site_visit_active
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.steps import step2_date_confirmation as date_confirmation
from backend.workflows.steps import step3_room_availability as room_availability
from backend.workflows.steps.step4_offer.trigger import process as process_offer
from backend.workflows.steps.step5_negotiation import process as process_negotiation
from backend.workflows.steps.step6_transition import process as process_transition
from backend.workflows.steps.step7_confirmation.trigger import process as process_confirmation


# Type aliases for callback functions
PersistFn = Callable[[WorkflowState, Path, Path], None]
DebugFn = Callable[[str, WorkflowState], None]
FinalizeFn = Callable[[GroupResult, WorkflowState, Path, Path], Dict[str, Any]]


def dispatch_step(state: WorkflowState, step: int) -> Optional[GroupResult]:
    """Dispatch to the appropriate step handler.

    Returns the GroupResult from the step handler, or None if step is not recognized.
    """
    if step == 2:
        return date_confirmation.process(state)
    if step == 3:
        return room_availability.process(state)
    if step == 4:
        return process_offer(state)
    if step == 5:
        return process_negotiation(state)
    if step == 6:
        return process_transition(state)
    if step == 7:
        return process_confirmation(state)
    return None


def run_routing_loop(
    state: WorkflowState,
    initial_result: GroupResult,
    path: Path,
    lock_path: Path,
    *,
    persist_fn: PersistFn,
    debug_fn: DebugFn,
    finalize_fn: FinalizeFn,
    max_iterations: int = 6,
) -> Tuple[Optional[Dict[str, Any]], GroupResult]:
    """Run the step routing loop through Steps 2-7.

    Iterates through workflow steps, calling the appropriate handler for each step.
    The loop continues until:
    - A step handler returns with halt=True (early return)
    - No event_entry exists (break)
    - Step is not recognized (break)
    - Max iterations reached (break)

    Args:
        state: Current workflow state
        initial_result: Result from intake step
        path: Database file path
        lock_path: Database lock file path
        persist_fn: Callback to persist state after each step
        debug_fn: Callback for debug logging
        finalize_fn: Callback to finalize and return result
        max_iterations: Maximum loop iterations (default 6)

    Returns:
        Tuple of (finalized_output, last_result) where:
        - finalized_output is the Dict to return if loop halted, or None if loop completed
        - last_result is the most recent GroupResult for post-loop handling
    """
    last_result = initial_result

    for iteration in range(max_iterations):
        event_entry = state.event_entry
        if not event_entry:
            print(f"[WF][ROUTE][{iteration}] No event_entry, breaking")
            break

        step = event_entry.get("current_step")
        print(f"[WF][ROUTE][{iteration}] current_step={step}")

        # =================================================================
        # SITE VISIT INTERCEPT: Handle site visit requests at ANY step
        # =================================================================
        # Check if there's an active site visit flow OR new site visit intent
        site_visit_result = _check_site_visit_intercept(state, event_entry)
        if site_visit_result:
            last_result = site_visit_result
            debug_fn(f"site_visit_intercept_step{step}", state)
            persist_fn(state, path, lock_path)
            if last_result.halt:
                debug_fn(f"halt_site_visit_step{step}", state)
                return finalize_fn(last_result, state, path, lock_path), last_result
            # Site visit handled but didn't halt - continue to normal step
        # =================================================================

        step_result = dispatch_step(state, step)

        if step_result is None:
            print(f"[WF][ROUTE] No handler for step {step}, breaking")
            break

        last_result = step_result

        # Debug and persist after each step
        debug_fn(f"post_step{step}", state)
        persist_fn(state, path, lock_path)

        # Check for halt - return early with finalized result
        if last_result.halt:
            debug_fn(f"halt_step{step}", state)
            return finalize_fn(last_result, state, path, lock_path), last_result

    # Loop completed without halting
    return None, last_result


def _check_site_visit_intercept(
    state: WorkflowState,
    event_entry: Dict[str, Any],
) -> Optional[GroupResult]:
    """Check if site visit intercept should handle this message.

    Site visit can be initiated at ANY step (2-7). This function checks:
    1. If there's an active site visit flow (room_pending or date_pending)
    2. If the current message indicates a new site visit request

    Returns GroupResult if site visit was handled, None otherwise.
    """
    # Check if site visit flow is already active
    if is_site_visit_active(event_entry):
        # Continue the active site visit flow
        detection = _get_detection_result(state)
        return handle_site_visit_request(state, event_entry, detection)

    # Check if this is a new site visit request
    detection = _get_detection_result(state)
    if is_site_visit_intent(detection):
        print(f"[WF][SITE_VISIT] New site visit request detected at step {event_entry.get('current_step')}")
        return handle_site_visit_request(state, event_entry, detection)

    return None


def _get_detection_result(state: WorkflowState) -> Optional[UnifiedDetectionResult]:
    """Get the unified detection result from state extras if available.

    The detection result is stored as a dict in state.extras["unified_detection"],
    so we need to rebuild the dataclass from it.
    """
    detection_data = state.extras.get("unified_detection")
    if not detection_data:
        return None

    # If it's already the object, return it
    if isinstance(detection_data, UnifiedDetectionResult):
        return detection_data

    # Rebuild from dict
    if isinstance(detection_data, dict):
        return UnifiedDetectionResult(
            language=detection_data.get("language", "en"),
            intent=detection_data.get("intent", "general_qna"),
            intent_confidence=detection_data.get("intent_confidence", 0.5),
            is_confirmation=detection_data.get("signals", {}).get("confirmation", False),
            is_acceptance=detection_data.get("signals", {}).get("acceptance", False),
            is_rejection=detection_data.get("signals", {}).get("rejection", False),
            is_change_request=detection_data.get("signals", {}).get("change_request", False),
            is_manager_request=detection_data.get("signals", {}).get("manager_request", False),
            is_question=detection_data.get("signals", {}).get("question", False),
            has_urgency=detection_data.get("signals", {}).get("urgency", False),
            date=detection_data.get("entities", {}).get("date"),
            date_text=detection_data.get("entities", {}).get("date_text"),
            participants=detection_data.get("entities", {}).get("participants"),
            duration_hours=detection_data.get("entities", {}).get("duration_hours"),
            room_preference=detection_data.get("entities", {}).get("room_preference"),
            products=detection_data.get("entities", {}).get("products", []),
            billing_address=detection_data.get("entities", {}).get("billing_address"),
            site_visit_room=detection_data.get("entities", {}).get("site_visit_room"),
            site_visit_date=detection_data.get("entities", {}).get("site_visit_date"),
            qna_types=detection_data.get("qna_types", []),
            step_anchor=detection_data.get("step_anchor"),
        )

    return None
