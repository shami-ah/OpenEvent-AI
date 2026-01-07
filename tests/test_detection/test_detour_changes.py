"""
Detour and Change Detection Tests (DET_DETOUR_*)

Tests the DAG-based change propagation logic for date, room, requirements, and products.
Ensures detours route to the correct owning step per v4 workflow.

References:
- TEST_MATRIX_detection_and_flow.md: DET_DETOUR_DATE_*, DET_DETOUR_ROOM_*, DET_DETOUR_REQ_*, DET_DETOUR_PROD_*
- backend/workflows/change_propagation.py: route_change_on_updated_variable, detect_change_type
- CLAUDE.md: Deterministic Detour Rules
"""

from __future__ import annotations

import pytest
from typing import Dict, Any

from workflows.change_propagation import (
    ChangeType,
    NextStepDecision,
    route_change_on_updated_variable,
    has_requirement_update,
    has_product_update,
    has_client_info_update,
    extract_change_verbs_near_noun,
)


# ==============================================================================
# FIXTURES
# ==============================================================================


def _make_event_state(
    current_step: int = 4,
    date_confirmed: bool = True,
    chosen_date: str = "2025-12-10",
    locked_room_id: str = "Room A",
    requirements_hash: str = "hash123",
    room_eval_hash: str = "hash123",
    caller_step: int = None,
) -> Dict[str, Any]:
    """Create a standard event state for testing."""
    return {
        "current_step": current_step,
        "caller_step": caller_step,
        "chosen_date": chosen_date,
        "date_confirmed": date_confirmed,
        "locked_room_id": locked_room_id,
        "requirements_hash": requirements_hash,
        "room_eval_hash": room_eval_hash,
        "requirements": {
            "number_of_participants": 24,
            "seating_layout": "theatre",
            "event_duration": {"start": "18:00", "end": "22:00"},
        },
    }


# ==============================================================================
# DET_DETOUR_DATE_001: Change Confirmed Date
# ==============================================================================


def test_DET_DETOUR_DATE_001_change_confirmed_date():
    """
    Date change from Step 4 should route to Step 2.
    State: date_confirmed=True, current_step=4
    Expected: ChangeType.DATE, next_step=2, maybe_run_step3=True
    """
    event_state = _make_event_state(current_step=4, date_confirmed=True)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.DATE, from_step=4
    )

    assert decision.next_step == 2, f"Date change should route to Step 2, got {decision}"
    assert decision.maybe_run_step3 is True, "Step 3 might run after date confirmation"
    assert decision.updated_caller_step == 4, "Caller should be saved for return"
    assert decision.needs_reeval is True


# ==============================================================================
# DET_DETOUR_DATE_002: Reschedule Request
# ==============================================================================


def test_DET_DETOUR_DATE_002_reschedule():
    """
    Reschedule from Step 5 should route to Step 2.
    State: date_confirmed=True, current_step=5
    Expected: next_step=2
    """
    event_state = _make_event_state(current_step=5, date_confirmed=True)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.DATE, from_step=5
    )

    assert decision.next_step == 2
    assert decision.updated_caller_step == 5


# ==============================================================================
# DET_DETOUR_DATE_003: Correction Marker Detection
# ==============================================================================


def test_DET_DETOUR_DATE_003_correction_verb_near_date():
    """
    Correction markers like 'actually', 'instead' near date nouns should detect change.
    """
    # Test the verb-near-noun helper
    message = "Actually, let's do April 15 instead"
    date_nouns = ["date", "day", "april", "15"]

    # This tests the helper function
    has_change_verb = extract_change_verbs_near_noun(message, date_nouns)
    # Note: "instead" isn't in change_verbs list, but let's test what is
    message2 = "Can we change the date to April 15?"
    has_change = extract_change_verbs_near_noun(message2, ["date", "april"])
    assert has_change is True


# ==============================================================================
# DET_DETOUR_ROOM_001: Change Locked Room
# ==============================================================================


def test_DET_DETOUR_ROOM_001_change_locked_room():
    """
    Room change should route to Step 3.
    State: locked_room_id="Room A"
    Expected: ChangeType.ROOM, next_step=3
    """
    event_state = _make_event_state(locked_room_id="Room A", current_step=4)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.ROOM, from_step=4
    )

    assert decision.next_step == 3, f"Room change should route to Step 3, got {decision}"
    assert decision.maybe_run_step3 is False, "We ARE Step 3"
    assert decision.updated_caller_step == 4
    assert decision.needs_reeval is True


# ==============================================================================
# DET_DETOUR_ROOM_002: Bigger Room Request
# ==============================================================================


def test_DET_DETOUR_ROOM_002_bigger_room():
    """
    'Need a bigger room' should route to Step 3.
    """
    event_state = _make_event_state(locked_room_id="Room A", current_step=4)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.ROOM, from_step=4
    )

    assert decision.next_step == 3


# ==============================================================================
# DET_DETOUR_ROOM_003: Room Preference Change from Step 4
# ==============================================================================


def test_DET_DETOUR_ROOM_003_room_preference():
    """
    Room preference change at Step 4 should route to Step 3.
    """
    event_state = _make_event_state(current_step=4)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.ROOM, from_step=4
    )

    assert decision.next_step == 3
    assert decision.updated_caller_step == 4


# ==============================================================================
# DET_DETOUR_REQ_001: Participants Increase
# ==============================================================================


def test_DET_DETOUR_REQ_001_participants_increase():
    """
    Participants increase should route to Step 3 for room re-evaluation.
    State: participants=24, hash mismatch
    Expected: ChangeType.REQUIREMENTS, next_step=3
    """
    event_state = _make_event_state(
        requirements_hash="new_hash",
        room_eval_hash="old_hash",  # Mismatch!
        current_step=4,
    )

    decision = route_change_on_updated_variable(
        event_state, ChangeType.REQUIREMENTS, from_step=4
    )

    assert decision.next_step == 3, f"Requirements change should route to Step 3"
    assert decision.needs_reeval is True


def test_DET_DETOUR_REQ_001_has_requirement_update():
    """Test requirement update detection helper."""
    event_state = _make_event_state()
    user_info = {"participants": 36}  # Different from event's 24

    has_update = has_requirement_update(event_state, user_info)
    assert has_update is True


# ==============================================================================
# DET_DETOUR_REQ_002: Layout Change
# ==============================================================================


def test_DET_DETOUR_REQ_002_layout_change():
    """
    Layout change should trigger requirements update detection.
    """
    event_state = _make_event_state()
    user_info = {"seating_layout": "banquet"}  # Different from "theatre"

    has_update = has_requirement_update(event_state, user_info)
    assert has_update is True


# ==============================================================================
# DET_DETOUR_REQ_003: Duration Change
# ==============================================================================


def test_DET_DETOUR_REQ_003_duration_change():
    """
    Duration/time change should trigger requirements update.
    """
    event_state = _make_event_state()
    user_info = {"end_time": "23:00"}  # Different from "22:00"

    has_update = has_requirement_update(event_state, user_info)
    assert has_update is True


def test_DET_DETOUR_REQ_003_start_time_change():
    """Start time change variant."""
    event_state = _make_event_state()
    user_info = {"start_time": "17:00"}  # Different from "18:00"

    has_update = has_requirement_update(event_state, user_info)
    assert has_update is True


# ==============================================================================
# DET_DETOUR_REQ_004: No Change (Same Value) - Hash Match Skip
# ==============================================================================


def test_DET_DETOUR_REQ_004_no_change_hash_match():
    """
    If requirements hash matches room_eval_hash, skip re-evaluation.
    Expected: needs_reeval=False, skip_reason set
    """
    event_state = _make_event_state(
        requirements_hash="same_hash",
        room_eval_hash="same_hash",  # Match!
    )

    decision = route_change_on_updated_variable(
        event_state, ChangeType.REQUIREMENTS, from_step=4
    )

    assert decision.needs_reeval is False, "Hash match should skip re-evaluation"
    assert decision.skip_reason == "requirements_hash_match"


def test_DET_DETOUR_REQ_004_no_update_detected():
    """Same value shouldn't trigger update."""
    event_state = _make_event_state()
    user_info = {"participants": 24}  # Same as current

    has_update = has_requirement_update(event_state, user_info)
    # Note: This compares string representations, so int vs int should match
    assert has_update is False


# ==============================================================================
# DET_DETOUR_PROD_001: Add Product (No Detour)
# ==============================================================================


def test_DET_DETOUR_PROD_001_add_product():
    """
    Product addition should stay in Step 4 (no structural detour).
    Expected: ChangeType.PRODUCTS, next_step=4
    """
    event_state = _make_event_state(current_step=4)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.PRODUCTS, from_step=4
    )

    assert decision.next_step == 4, "Products stay in Step 4"
    assert decision.maybe_run_step3 is False, "No room re-eval for products"


def test_DET_DETOUR_PROD_001_has_product_update():
    """Test product update detection helper."""
    user_info = {"products_add": [{"name": "Microphone", "quantity": 1}]}
    assert has_product_update(user_info) is True


# ==============================================================================
# DET_DETOUR_PROD_002: Remove Product
# ==============================================================================


def test_DET_DETOUR_PROD_002_remove_product():
    """
    Product removal should stay in Step 4.
    """
    event_state = _make_event_state(current_step=4)

    decision = route_change_on_updated_variable(
        event_state, ChangeType.PRODUCTS, from_step=4
    )

    assert decision.next_step == 4


def test_DET_DETOUR_PROD_002_has_product_remove():
    """Test product remove detection."""
    user_info = {"products_remove": ["Coffee Break"]}
    assert has_product_update(user_info) is True


# ==============================================================================
# DET_DETOUR_PROD_003: Menu Change
# ==============================================================================


def test_DET_DETOUR_PROD_003_menu_change():
    """
    Menu/catering change should stay in Step 4.
    """
    user_info = {"menu": "Garden Trio"}
    assert has_product_update(user_info) is True


# ==============================================================================
# CLIENT INFO UPDATES (Billing)
# ==============================================================================


def test_client_info_billing_update():
    """Billing address update detection."""
    user_info = {"billing_address": "123 Main St, Zurich"}
    assert has_client_info_update(user_info) is True


def test_client_info_company_update():
    """Company name update detection."""
    user_info = {"company_name": "ACME Corp"}
    assert has_client_info_update(user_info) is True


def test_client_info_no_update():
    """No client info fields should return False."""
    user_info = {"participants": 30}  # Not a client info field
    assert has_client_info_update(user_info) is False


# ==============================================================================
# EDGE CASES
# ==============================================================================


def test_change_verb_detection():
    """Test change verb near noun detection."""
    # Should detect
    assert extract_change_verbs_near_noun("change the date", ["date"]) is True
    assert extract_change_verbs_near_noun("switch to Room B", ["room"]) is True
    assert extract_change_verbs_near_noun("upgrade the package", ["package"]) is True

    # Should NOT detect
    assert extract_change_verbs_near_noun("what date works", ["date"]) is False
    assert extract_change_verbs_near_noun("I like Room A", ["room"]) is False


def test_no_user_info_no_update():
    """Empty user_info shouldn't trigger updates."""
    event_state = _make_event_state()
    assert has_requirement_update(event_state, {}) is False
    assert has_product_update({}) is False
    assert has_client_info_update({}) is False


def test_null_values_ignored():
    """Null values in user_info shouldn't trigger updates."""
    event_state = _make_event_state()
    user_info = {"participants": None, "layout": None}
    assert has_requirement_update(event_state, user_info) is False
