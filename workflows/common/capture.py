from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

if TYPE_CHECKING:
    from detection.unified import UnifiedDetectionResult

logger = logging.getLogger(__name__)

from workflows.common.billing import update_billing_details
from workflows.common.types import WorkflowState


# Question indicators for sentence classification
_QUESTION_STARTERS = ("what", "which", "how", "would", "could", "can", "is", "are", "do", "does", "will")


def split_statement_vs_question(text: str) -> Tuple[str, str]:
    """
    Split text into statement part (to persist) and question part (Q&A only).

    Rules:
    - Sentences with '?' are questions
    - Sentences starting with question words are questions
    - Everything else is a statement

    Examples:
        "We'll have 50 people. What rooms work?"
        → statements: "We'll have 50 people."
        → questions: "What rooms work?"

        "We have 50 people but what about 70?"
        → statements: "We have 50 people"
        → questions: "what about 70?"
    """
    if not text:
        return "", ""

    # Handle "but what about" pattern specially
    but_pattern = re.compile(r"\s+but\s+(?=what|how|which|would|could|can)", re.IGNORECASE)
    parts_by_but = but_pattern.split(text)

    statements: List[str] = []
    questions: List[str] = []

    for part in parts_by_but:
        # Split on sentence boundaries (. ! ?)
        sentences = re.split(r"(?<=[.!?])\s+", part.strip())

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue

            # Check if it's a question
            if "?" in sent:
                questions.append(sent)
            elif sent.lower().startswith(_QUESTION_STARTERS):
                questions.append(sent)
            else:
                statements.append(sent)

    return " ".join(statements), " ".join(questions)


def capture_workflow_requirements(
    state: WorkflowState,
    text: str,
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Capture and PERSIST requirements from STATEMENT part of the message only.

    This is for workflow context (not Q&A). Requirements mentioned in statements
    are persisted to event_entry["requirements"]. Requirements in questions
    are NOT persisted (handled separately by qna_requirements).

    Args:
        state: Workflow state with event_entry to update
        text: Full message text
        user_info: Extracted user info dict

    Returns:
        Dict of captured requirements (empty if none found in statements)
    """
    statement_part, _ = split_statement_vs_question(text)

    if not statement_part:
        return {}  # No statements → nothing to persist

    event_entry = state.event_entry
    if not event_entry:
        return {}

    requirements = event_entry.setdefault("requirements", {})
    captured: Dict[str, Any] = {}

    # Extract and persist requirements from the statement part
    # Only persist if the value appears in the statement part (not question)
    statement_lower = statement_part.lower()

    # Participants / attendees
    participants = user_info.get("participants")
    if participants is not None:
        # Check if the number appears in statement part
        try:
            participant_str = str(int(participants))
            if participant_str in statement_part:
                requirements["number_of_participants"] = int(participants)
                captured["number_of_participants"] = int(participants)
        except (TypeError, ValueError):
            pass

    # Seating layout
    layout = user_info.get("layout")
    if layout and isinstance(layout, str) and layout.lower() in statement_lower:
        requirements["seating_layout"] = layout
        captured["seating_layout"] = layout

    # Preferred room
    room = user_info.get("room") or user_info.get("preferred_room")
    if room and isinstance(room, str) and room.lower() in statement_lower:
        requirements["preferred_room"] = room
        captured["preferred_room"] = room

    # Special requirements / notes
    notes = user_info.get("notes") or user_info.get("special_requirements")
    if notes and isinstance(notes, str):
        # Notes could be anywhere, check if any significant word appears in statement
        note_words = set(notes.lower().split())
        statement_words = set(statement_lower.split())
        if note_words & statement_words:  # Intersection not empty
            requirements["special_requirements"] = notes
            captured["special_requirements"] = notes

    if captured:
        # Update requirements hash if function available
        try:
            from workflows.common.requirements import requirements_hash
            event_entry["requirements_hash"] = requirements_hash(requirements)
        except ImportError:
            pass
        state.extras["persist"] = True

    return captured


@dataclass(frozen=True)
class FieldSpec:
    alias: str
    path: Tuple[str, ...]
    step: int
    deferred: Optional[str] = None
    hold_until_owner: bool = False


_FIELD_SPECS: Dict[str, FieldSpec] = {
    # Step 2 — date & time window
    "date": FieldSpec(alias="date", path=("date",), step=2, deferred="date_confirmation"),
    "event_date": FieldSpec(alias="event_date", path=("event_date",), step=2, deferred="date_confirmation"),
    "start_time": FieldSpec(alias="start_time", path=("start_time",), step=2, deferred="date_confirmation"),
    "end_time": FieldSpec(alias="end_time", path=("end_time",), step=2, deferred="date_confirmation"),
    # Step 3 — room / requirements
    "room": FieldSpec(alias="room", path=("preferred_room",), step=3, deferred="room_selection"),
    "preferred_room": FieldSpec(alias="preferred_room", path=("preferred_room",), step=3, deferred="room_selection"),
    # Step 4/7 — billing & contacts
    "billing_address": FieldSpec(
        alias="billing_address",
        path=("billing", "address"),
        step=4,
        deferred="billing_update",
        hold_until_owner=True,
    ),
    "company": FieldSpec(
        alias="company",
        path=("billing", "company"),
        step=4,
        deferred="billing_update",
        hold_until_owner=True,
    ),
    "name": FieldSpec(alias="name", path=("contact", "name"), step=4, deferred="contact_update"),
    "email": FieldSpec(alias="email", path=("contact", "email"), step=4, deferred="contact_update"),
    "phone": FieldSpec(alias="phone", path=("contact", "phone"), step=4, deferred="contact_update"),
}


def capture_user_fields(state: WorkflowState, *, current_step: int, source: Optional[str] = None) -> None:
    """Capture out-of-order fields into the event entry for later promotion."""

    event_entry = state.event_entry
    user_info = state.user_info or {}
    if not event_entry or not user_info:
        return

    captured_root = event_entry.setdefault("captured", {})
    sources = event_entry.setdefault("captured_sources", [])
    deferred_intents = event_entry.setdefault("deferred_intents", [])

    telemetry_captured: List[str] = state.telemetry.setdefault("captured_fields", [])
    telemetry_deferred: List[str] = state.telemetry.setdefault("deferred_intents", list(deferred_intents))
    source_label = source or "user_message"

    for alias, spec in _FIELD_SPECS.items():
        if alias not in user_info:
            continue
        value = user_info[alias]
        if value in (None, "", [], {}):
            continue

        _set_nested(captured_root, spec.path, value)
        dotted = _path_to_str(spec.path)
        if dotted not in telemetry_captured:
            telemetry_captured.append(dotted)
        label = f"{source_label}:{dotted}"
        if label not in sources:
            sources.append(label)

        if spec.deferred and current_step < spec.step and spec.deferred not in deferred_intents:
            deferred_intents.append(spec.deferred)
        if spec.deferred and current_step < spec.step and spec.deferred not in telemetry_deferred:
            telemetry_deferred.append(spec.deferred)

        if spec.hold_until_owner and current_step < spec.step:
            user_info.pop(alias, None)

    # Keep telemetry deferred intents in sync with entry
    state.telemetry.deferred_intents = list(dict.fromkeys(deferred_intents))


# =============================================================================
# GLOBAL FIELD CAPTURE (capture_fields_anytime)
# =============================================================================

@dataclass
class FieldCaptureResult:
    """Result of global field capture attempt."""

    captured: bool = False
    fields: List[str] = field(default_factory=list)  # e.g., ["date", "room", "contact_email"]
    source: str = ""  # "unified_llm" | "already_captured"


def capture_fields_anytime(
    state: WorkflowState,
    unified_result: Optional["UnifiedDetectionResult"],
    current_step: int,
) -> FieldCaptureResult:
    """
    Capture date/room/time/contact fields from unified detection at ANY step.

    This is the CENTRAL field capture function called from pre_route.py.
    It ensures fields are captured regardless of which step we're at.

    Similar to capture_billing_anytime(), this runs on EVERY message and
    piggybacks on the unified detection LLM call (zero extra cost).

    Args:
        state: Current workflow state with event_entry
        unified_result: Result from unified LLM detection
        current_step: Current workflow step (for deferred intent tracking)

    Returns:
        FieldCaptureResult with captured flag and field list
    """
    if unified_result is None:
        return FieldCaptureResult(captured=False, source="no_detection")

    event_entry = state.event_entry
    if not event_entry:
        return FieldCaptureResult(captured=False, source="no_event")

    # Check if already captured this turn (avoid duplicate processing)
    turn_capture_key = "fields_captured_this_turn"
    if state.turn_notes.get(turn_capture_key):
        return FieldCaptureResult(captured=False, source="already_captured")

    captured_root = event_entry.setdefault("captured", {})
    sources = event_entry.setdefault("captured_sources", [])
    deferred_intents = event_entry.setdefault("deferred_intents", [])

    captured_fields: List[str] = []

    # --- Date/Time Fields (Step 2) ---
    # Guard: Don't capture site_visit_date as event date
    if unified_result.date and not unified_result.site_visit_date:
        _set_nested(captured_root, ("date",), unified_result.date)
        captured_fields.append("date")
        if "unified:date" not in sources:
            sources.append("unified:date")
        if current_step < 2 and "date_confirmation" not in deferred_intents:
            deferred_intents.append("date_confirmation")

    if unified_result.start_time:
        _set_nested(captured_root, ("start_time",), unified_result.start_time)
        captured_fields.append("start_time")
        if "unified:start_time" not in sources:
            sources.append("unified:start_time")

    if unified_result.end_time:
        _set_nested(captured_root, ("end_time",), unified_result.end_time)
        captured_fields.append("end_time")
        if "unified:end_time" not in sources:
            sources.append("unified:end_time")

    # --- Room Preference (Step 3) ---
    if unified_result.room_preference:
        _set_nested(captured_root, ("preferred_room",), unified_result.room_preference)
        captured_fields.append("preferred_room")
        if "unified:preferred_room" not in sources:
            sources.append("unified:preferred_room")
        if current_step < 3 and "room_selection" not in deferred_intents:
            deferred_intents.append("room_selection")

    # --- Contact Fields (Step 4) ---
    if unified_result.contact_name:
        _set_nested(captured_root, ("contact", "name"), unified_result.contact_name)
        captured_fields.append("contact.name")
        if "unified:contact.name" not in sources:
            sources.append("unified:contact.name")
        if current_step < 4 and "contact_update" not in deferred_intents:
            deferred_intents.append("contact_update")

    if unified_result.contact_email:
        _set_nested(captured_root, ("contact", "email"), unified_result.contact_email)
        captured_fields.append("contact.email")
        if "unified:contact.email" not in sources:
            sources.append("unified:contact.email")
        if current_step < 4 and "contact_update" not in deferred_intents:
            deferred_intents.append("contact_update")

    if unified_result.contact_phone:
        _set_nested(captured_root, ("contact", "phone"), unified_result.contact_phone)
        captured_fields.append("contact.phone")
        if "unified:contact.phone" not in sources:
            sources.append("unified:contact.phone")
        if current_step < 4 and "contact_update" not in deferred_intents:
            deferred_intents.append("contact_update")

    # Mark turn as processed
    state.turn_notes[turn_capture_key] = True

    if captured_fields:
        state.extras["persist"] = True
        logger.debug(
            "[FIELD_CAPTURE] Captured at step %s: %s",
            current_step,
            captured_fields,
        )
        return FieldCaptureResult(
            captured=True,
            fields=captured_fields,
            source="unified_llm",
        )

    return FieldCaptureResult(captured=False, source="no_fields")


def promote_fields(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    promotions: Dict[Tuple[str, ...], Any],
    *,
    remove_deferred: Optional[Iterable[str]] = None,
) -> None:
    """Promote captured fields into the verified store and clean deferred intents."""

    if not promotions:
        return
    verified = event_entry.setdefault("verified", {})
    captured = event_entry.setdefault("captured", {})

    promoted_fields: List[str] = state.telemetry.setdefault("promoted_fields", [])

    for path, value in promotions.items():
        if value in (None, "", [], {}):
            continue
        _set_nested(verified, path, value)
        _delete_nested(captured, path)
        dotted = _path_to_str(path)
        if dotted not in promoted_fields:
            promoted_fields.append(dotted)

    if remove_deferred:
        deferred_intents = event_entry.setdefault("deferred_intents", [])
        for label in remove_deferred:
            if label in deferred_intents:
                deferred_intents.remove(label)
        state.telemetry.deferred_intents = list(dict.fromkeys(deferred_intents))


def get_captured_value(event_entry: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    """Return a captured field value given its path."""

    captured = event_entry.get("captured") or {}
    return _get_nested(captured, path)


def promote_billing_from_captured(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    """Promote captured billing fields into the event record when available."""

    promotions: Dict[Tuple[str, ...], Any] = {}
    address = get_captured_value(event_entry, ("billing", "address"))
    company = get_captured_value(event_entry, ("billing", "company"))

    if address not in (None, ""):
        event_entry.setdefault("event_data", {})["Billing Address"] = address
        promotions[("billing", "address")] = address

    if company not in (None, ""):
        event_entry.setdefault("event_data", {})["Company"] = company
        promotions[("billing", "company")] = company

    if not promotions:
        return

    update_billing_details(event_entry)
    promote_fields(state, event_entry, promotions, remove_deferred=["billing_update"])
    state.extras["persist"] = True


def _set_nested(container: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    cursor = container
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def _get_nested(container: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cursor = container
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def _delete_nested(container: Dict[str, Any], path: Tuple[str, ...]) -> None:
    stack: List[Tuple[Dict[str, Any], str]] = []
    cursor = container
    for key in path[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            return
        stack.append((cursor, key))
        cursor = cursor[key]
    cursor.pop(path[-1], None)
    # Clean up empty dicts
    while stack:
        parent, key = stack.pop()
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key, None)


def _path_to_str(path: Tuple[str, ...]) -> str:
    return ".".join(path)
