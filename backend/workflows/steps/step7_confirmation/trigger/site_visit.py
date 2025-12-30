"""Site visit handling for Step 7 confirmation.

Extracted from step7_handler.py as part of F2 refactoring (Dec 2025).

NOTE: This module is now a thin wrapper around the centralized site visit handler
at backend/workflows/common/site_visit_handler.py. The centralized handler supports
site visits from ANY workflow step (2-7), while this module maintains backward
compatibility for Step 7 specific flows.

Contains 9 functions for the complete site-visit subflow:
- _handle_site_visit: Main entry point
- _site_visit_unavailable_response: Fallback when not allowed
- _generate_visit_slots: Generate default time slots
- _extract_site_visit_preference: Parse date/time/weekday preferences
- _generate_preferred_visit_slots: Generate slots matching preferences
- _handle_site_visit_preference: Handle preference → slots
- _parse_slot_selection: Parse ordinal/date selection
- _handle_site_visit_confirmation: Confirm selected slot
- _ensure_calendar_block: Create calendar entry
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.workflows.common.prompts import append_footer
from backend.workflows.common.room_rules import site_visit_allowed
from backend.workflows.common.site_visit_state import (
    get_site_visit_state,
    set_site_visit_date,
)
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata

from .helpers import base_payload


def handle_site_visit(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Handle site visit request from client.

    This is the Step 7 specific entry point. For cross-step site visit handling,
    see backend/workflows/common/site_visit_handler.py
    """
    if not site_visit_allowed(event_entry):
        conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
        conf_state["pending"] = None
        return site_visit_unavailable_response(state, event_entry)

    slots = generate_visit_slots(event_entry)
    # Use shared state helpers for consistency
    visit_state = get_site_visit_state(event_entry)
    visit_state["status"] = "proposed"
    visit_state["proposed_slots"] = slots
    draft_lines = ["We'd be happy to arrange a site visit. Here are some possible times:"]
    draft_lines.extend(f"- {slot}" for slot in slots)
    draft_lines.append("Which would suit you? If you have other preferences, let me know and I'll try to accommodate.")
    draft = {
        "body": append_footer(
            "\n".join(draft_lines),
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_site_visit",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "site_visit"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_site_visit", payload=payload, halt=True)


def site_visit_unavailable_response(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Response when site visit is not available for this room/booking."""
    draft = {
        "body": append_footer(
            "Thanks for checking — for this room we aren't able to offer on-site visits before confirmation, "
            "but I'm happy to share additional details or photos.",
            step=7,
            next_step="Share any questions",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "confirmation_question",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def generate_visit_slots(event_entry: Dict[str, Any]) -> List[str]:
    """Generate default visit time slots before the event date."""
    base = event_entry.get("chosen_date") or "15.03.2025"
    try:
        day, month, year = map(int, base.split("."))
        anchor = datetime(year, month, day)
    except ValueError:
        anchor = datetime.utcnow()
    slots: List[str] = []
    for offset in range(3):
        candidate = anchor - timedelta(days=offset + 1)
        slot = candidate.replace(hour=10 + offset, minute=0)
        slots.append(slot.strftime("%d.%m.%Y at %H:%M"))
    return slots


def extract_site_visit_preference(user_info: Dict[str, Any], message_text: str) -> Optional[Dict[str, Any]]:
    """Extract site visit date/time preference from client message.

    Returns dict with keys: requested_date, requested_time, requested_weekday, requested_month
    or None if no preference detected.
    """
    # Check for date in user_info (from LLM extraction)
    raw_date = user_info.get("date") or user_info.get("event_date")

    # Parse time preference (e.g., "4 pm", "16:00", "around 4")
    time_match = re.search(r"(\d{1,2})\s*(?:pm|am|:00|h|uhr)?", message_text.lower())
    time_pref = None
    if time_match:
        hour = int(time_match.group(1))
        if "pm" in message_text.lower() and hour < 12:
            hour += 12
        elif "am" not in message_text.lower() and hour < 6:
            # Assume afternoon for small numbers without am/pm
            hour += 12
        time_pref = f"{hour:02d}:00"

    # Check for day-of-week preference (EN + DE)
    day_keywords = {
        "monday": 0, "montag": 0, "tuesday": 1, "dienstag": 1,
        "wednesday": 2, "mittwoch": 2, "thursday": 3, "donnerstag": 3,
        "friday": 4, "freitag": 4,
    }
    weekday_pref = None
    for day, num in day_keywords.items():
        if day in message_text.lower():
            weekday_pref = num
            break

    # Check for month references (parse "april" -> base date in that month)
    month_keywords = {
        "january": 1, "januar": 1, "february": 2, "februar": 2,
        "march": 3, "märz": 3, "marz": 3, "april": 4,
        "may": 5, "mai": 5, "june": 6, "juni": 6,
        "july": 7, "juli": 7, "august": 8,
        "september": 9, "october": 10, "oktober": 10,
        "november": 11, "december": 12, "dezember": 12,
    }
    month_pref = None
    for month_name, month_num in month_keywords.items():
        if month_name in message_text.lower():
            month_pref = month_num
            break

    if raw_date or time_pref or weekday_pref or month_pref:
        return {
            "requested_date": raw_date,        # ISO date from LLM
            "requested_time": time_pref,       # "16:00" format
            "requested_weekday": weekday_pref, # 0-4 Mon-Fri
            "requested_month": month_pref,     # 1-12
        }
    return None


def generate_preferred_visit_slots(
    event_entry: Dict[str, Any],
    preference: Dict[str, Any],
) -> List[str]:
    """Generate visit slots matching client's preference (before event date)."""
    event_date_str = event_entry.get("chosen_date") or "15.03.2025"
    try:
        day, month, year = map(int, event_date_str.split("."))
        event_date = datetime(year, month, day)
    except ValueError:
        event_date = datetime.utcnow() + timedelta(days=30)

    # Parse preference
    requested_date = preference.get("requested_date")
    requested_time = preference.get("requested_time") or "16:00"
    requested_weekday = preference.get("requested_weekday")
    requested_month = preference.get("requested_month")

    # Determine base date for slot search
    base: Optional[datetime] = None
    if requested_date:
        try:
            base = datetime.fromisoformat(requested_date.replace("Z", ""))
        except ValueError:
            pass
    if base is None and requested_month:
        # Use first day of requested month in event year
        base = datetime(event_date.year, requested_month, 1)
        # If month already passed this year, try next year
        if base < datetime.utcnow():
            base = datetime(event_date.year + 1, requested_month, 1)
    if base is None:
        # Default to 2-3 weeks before event
        base = event_date - timedelta(days=21)

    # Generate up to 3 slots matching weekday preference, before event date
    slots: List[str] = []
    candidate = base
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    for _ in range(60):  # Search 60 days max
        if candidate >= event_date:
            break
        if candidate < today:
            candidate += timedelta(days=1)
            continue
        if requested_weekday is None or candidate.weekday() == requested_weekday:
            try:
                hour = int(requested_time.split(":")[0])
            except (ValueError, IndexError):
                hour = 16
            slot_dt = candidate.replace(hour=hour, minute=0)
            slots.append(slot_dt.strftime("%d.%m.%Y at %H:%M"))
            if len(slots) >= 3:
                break
        candidate += timedelta(days=1)

    return slots


def handle_site_visit_preference(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    preference: Dict[str, Any],
) -> GroupResult:
    """Handle site visit date/time preference from client."""
    visit_state = event_entry.get("site_visit_state") or {}

    # Store the client's preference (Supabase-compatible)
    visit_state["requested_date"] = preference.get("requested_date")
    visit_state["requested_time"] = preference.get("requested_time")
    visit_state["requested_weekday"] = preference.get("requested_weekday")

    # Generate slots based on preference
    slots = generate_preferred_visit_slots(event_entry, preference)
    if not slots:
        # Fallback to default slots if preference yields no results
        slots = generate_visit_slots(event_entry)

    visit_state["proposed_slots"] = slots
    event_entry["site_visit_state"] = visit_state

    # Build response
    draft_lines = ["Here are available times matching your preference:"]
    draft_lines.extend(f"- {slot}" for slot in slots)
    draft_lines.append("Which would work best for you?")

    draft = {
        "body": append_footer(
            "\n".join(draft_lines),
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "site_visit_preference_slots",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "site_visit"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="site_visit_preference_slots", payload=payload, halt=True)


def parse_slot_selection(message_text: str, slots: List[str]) -> Optional[str]:
    """Parse which slot client selected from their message.

    Returns the selected slot string or None if not parseable.
    """
    lowered = message_text.lower()

    # Check for ordinal selection
    ordinals = [("first", 0), ("1st", 0), ("second", 1), ("2nd", 1), ("third", 2), ("3rd", 2)]
    for word, idx in ordinals:
        if word in lowered and idx < len(slots):
            return slots[idx]

    # Check for date match in message
    for slot in slots:
        date_part = slot.split(" at ")[0]  # "15.04.2026"
        if date_part in message_text:
            return slot

    # Generic confirmation = first slot
    confirm_words = ("yes", "proceed", "ok", "confirm", "sounds good", "perfect", "ja", "bitte")
    if any(word in lowered for word in confirm_words) and slots:
        return slots[0]

    return None


def handle_site_visit_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    """Confirm the selected site visit slot (direct confirm, no HIL)."""
    visit_state = get_site_visit_state(event_entry)
    slots = visit_state.get("proposed_slots", [])
    message_text = (state.message.body or "").strip()

    # Parse slot selection
    selected_slot = parse_slot_selection(message_text, slots)

    if selected_slot:
        # Parse into confirmed_date and confirmed_time
        try:
            date_part, time_part = selected_slot.split(" at ")
            parsed_date = datetime.strptime(date_part, "%d.%m.%Y")
            confirmed_date = parsed_date.date().isoformat()
            confirmed_time = time_part
        except (ValueError, IndexError):
            confirmed_date = None
            confirmed_time = None

        # Use shared state setter for consistency
        if confirmed_date:
            set_site_visit_date(event_entry, confirmed_date, confirmed_time)

        room_name = event_entry.get("locked_room_id") or "the venue"
        draft = {
            "body": append_footer(
                f"Your site visit is confirmed for {selected_slot}. "
                f"We look forward to showing you {room_name}!",
                step=7,
                next_step="Site visit scheduled - continue booking",
                thread_state="Awaiting Client",
            ),
            "step": 7,
            "topic": "site_visit_confirmed",
            "requires_approval": False,  # Direct confirm, no HIL
        }
        state.add_draft_message(draft)
        append_audit_entry(event_entry, 7, 7, "site_visit_confirmed")
        update_event_metadata(event_entry, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        payload = base_payload(state, event_entry)
        return GroupResult(action="site_visit_confirmed", payload=payload, halt=True)

    # Couldn't parse selection - ask for clarification
    draft = {
        "body": append_footer(
            "I couldn't determine which slot you'd prefer. "
            "Could you please specify which date and time works best for your visit?",
            step=7,
            next_step="Pick a visit slot",
            thread_state="Awaiting Client",
        ),
        "step": 7,
        "topic": "site_visit_clarification",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = base_payload(state, event_entry)
    return GroupResult(action="site_visit_clarification", payload=payload, halt=True)


def ensure_calendar_block(event_entry: Dict[str, Any]) -> None:
    """Create calendar block entry for confirmed event."""
    blocks = event_entry.setdefault("calendar_blocks", [])
    date_label = event_entry.get("chosen_date") or ""
    room = event_entry.get("locked_room_id") or "Room"
    blocks.append({"date": date_label, "room": room, "created_at": datetime.utcnow().isoformat()})
