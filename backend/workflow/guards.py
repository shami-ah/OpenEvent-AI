from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.workflow.state import WorkflowStep, write_stage
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
from backend.workflows.io.database import update_event_metadata

if TYPE_CHECKING:
    from backend.workflows.common.types import WorkflowState


@dataclass
class GuardSnapshot:
    """Deterministic guard outcome for steps 2–4."""

    step2_required: bool
    step3_required: bool
    step4_required: bool
    requirements_hash: Optional[str]
    room_eval_hash: Optional[str]
    chosen_date: Optional[str]
    candidate_dates: List[str]


def _iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return to_iso_date(value) or value


def _normalize_date(value: Optional[str]) -> Optional[str]:
    iso_val = _iso(value)
    if not iso_val:
        return None
    return format_iso_date_to_ddmmyyyy(iso_val) or iso_val


def _compute_candidate_dates(state: "WorkflowState", preferred_room: Optional[str]) -> List[str]:
    if not state.event_entry:
        return []
    anchor_ts = state.message.ts or datetime.utcnow().isoformat() + "Z"
    candidates_ddmmyyyy = suggest_dates(
        state.db,
        preferred_room=preferred_room or "Not specified",
        start_from_iso=anchor_ts,
        days_ahead=45,
        max_results=5,
    )
    iso_values: List[str] = []
    seen: set[str] = set()
    for raw in candidates_ddmmyyyy:
        iso = to_iso_date(raw)
        if not iso or iso in seen:
            continue
        seen.add(iso)
        iso_values.append(iso)
        if len(iso_values) >= 5:
            break
    return iso_values


def evaluate(state: "WorkflowState") -> GuardSnapshot:
    """
    Evaluate deterministic entry guards for Steps 2–4 and surface derived state.
    """

    event_entry = state.event_entry or {}

    # [DEPOSIT PAYMENT BYPASS] When deposit is just paid and offer was accepted,
    # skip guard-forced step changes so workflow proceeds to step 5.
    # We always route to step 5 (even if gate not ready) because step 5 has the
    # confirmation gate logic to check billing/deposit and generate appropriate responses.
    is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
    if is_deposit_signal and event_entry.get("offer_accepted"):
        # Ensure step is 5 for negotiation handler to process confirmation gate
        if event_entry.get("current_step") != 5:
            update_event_metadata(event_entry, current_step=5)
            state.current_step = 5
            state.extras["persist"] = True
        # Return early with no forced steps
        return GuardSnapshot(
            step2_required=False,
            step3_required=False,
            step4_required=False,
            requirements_hash=event_entry.get("requirements_hash"),
            room_eval_hash=event_entry.get("room_eval_hash"),
            chosen_date=_normalize_date(event_entry.get("chosen_date")),
            candidate_dates=[],
        )
    user_info = state.user_info or {}

    chosen_date = event_entry.get("chosen_date")
    date_confirmed = bool(event_entry.get("date_confirmed"))
    user_date = user_info.get("event_date") or user_info.get("date")
    normalized_user_date = _normalize_date(user_date)
    normalized_chosen = _normalize_date(chosen_date)

    # Step 2 guard -----------------------------------------------------------
    step2_required = False
    candidate_dates: List[str] = []

    if not chosen_date or not date_confirmed:
        step2_required = True
    elif normalized_user_date and normalized_user_date != normalized_chosen:
        step2_required = True

    requirements = event_entry.get("requirements") or {}
    req_hash = event_entry.get("requirements_hash")
    if requirements:
        computed_hash = requirements_hash(requirements)
        if req_hash != computed_hash:
            req_hash = computed_hash
            update_event_metadata(event_entry, requirements_hash=req_hash)
            state.extras["persist"] = True
    else:
        req_hash = None

    room_eval_hash = event_entry.get("room_eval_hash")
    locked_room_id = event_entry.get("locked_room_id")
    user_room = user_info.get("room")

    # Step 3 guard -----------------------------------------------------------
    step3_required = False
    if not step2_required:
        if not locked_room_id:
            step3_required = True
        elif user_room and user_room != locked_room_id:
            step3_required = True
        elif req_hash and room_eval_hash and req_hash != room_eval_hash:
            step3_required = True

    # Step 4 guard -----------------------------------------------------------
    step4_required = False
    if not step2_required and not step3_required:
        if not date_confirmed:
            step4_required = False
        else:
            offer_status = str(event_entry.get("offer_status") or "").strip().lower()
            if not locked_room_id:
                step4_required = False
            elif req_hash and room_eval_hash and req_hash != room_eval_hash:
                step4_required = False
            else:
                step4_required = offer_status not in {"sent", "accepted", "accepted_final"}

    if step2_required and not candidate_dates:
        preferred_room = requirements.get("preferred_room")
        candidate_dates = _compute_candidate_dates(state, preferred_room)
        state.extras["step2_candidate_dates"] = candidate_dates

    # Adjust current step ordering deterministically
    forced_step: Optional[int] = None
    if step2_required:
        forced_step = 2
    elif step3_required:
        forced_step = 3
    elif step4_required:
        forced_step = 4

    current_step = event_entry.get("current_step")
    if forced_step and forced_step != current_step:
        update_event_metadata(event_entry, current_step=forced_step)
        write_stage(event_entry, current_step=WorkflowStep(f"step_{forced_step}"))
        state.current_step = forced_step
        state.extras["persist"] = True

    return GuardSnapshot(
        step2_required=step2_required,
        step3_required=step3_required,
        step4_required=step4_required,
        requirements_hash=req_hash,
        room_eval_hash=room_eval_hash,
        chosen_date=normalized_chosen,
        candidate_dates=candidate_dates,
    )


def shortcut_ready(state: "WorkflowState") -> bool:
    """
    Determine whether the first message contains enough signals for the fast-path.
    """

    if not state.event_entry:
        return False

    user_info = state.user_info or {}
    date_ready = bool(user_info.get("date") or user_info.get("event_date"))
    attendees_ready = bool(user_info.get("participants"))

    if not (date_ready and attendees_ready):
        return False

    chosen_date = state.event_entry.get("chosen_date")
    if chosen_date:
        return False

    return True