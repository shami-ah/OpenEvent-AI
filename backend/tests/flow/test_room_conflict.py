"""
Tests for room conflict detection and resolution.

Scenario:
1. Client 1 reserves Room E on Feb 7th (status = Option)
2. Client 2 tries to reserve Room E on Feb 7th
3. Conflict detected → warning shown
4. Client 2 insists → HIL task created
5. Manager resolves → winner continues, loser redirected
"""

import pytest

pytestmark = pytest.mark.v4
from datetime import datetime

# MIGRATED: from backend.workflows.common.conflict -> backend.detection.special.room_conflict
from backend.detection.special.room_conflict import (
    ConflictType,
    detect_room_conflict,
    detect_conflict_type,
    get_available_rooms_on_date,
    compose_conflict_warning_message,
    compose_conflict_hil_task,
    compose_soft_conflict_warning,
    compose_hard_conflict_block,
    handle_loser_event,
    handle_soft_conflict,
    handle_hard_conflict,
    notify_conflict_resolution,
)


@pytest.fixture
def sample_db():
    """Create a sample database with two clients and events."""
    return {
        "clients": {
            "client_1": {
                "id": "client_1",
                "email": "laura.meier@bluewin.ch",
                "name": "Laura Meier",
            },
            "client_2": {
                "id": "client_2",
                "email": "max.mueller@gmail.com",
                "name": "Max Mueller",
            },
        },
        "events": {
            "event_1": {
                "event_id": "event_1",
                "client_id": "client_1",
                "client_email": "laura.meier@bluewin.ch",
                "client_name": "Laura Meier",
                "chosen_date": "2026-02-07",
                "locked_room_id": "Room E",
                "status": "Option",  # Client 1 has this room reserved
                "current_step": 4,
            },
            "event_2": {
                "event_id": "event_2",
                "client_id": "client_2",
                "client_email": "max.mueller@gmail.com",
                "client_name": "Max Mueller",
                "chosen_date": "2026-02-07",
                "locked_room_id": None,  # Client 2 hasn't locked a room yet
                "status": "Lead",
                "current_step": 3,
            },
        },
        "rooms": {
            "Room A": {"id": "Room A", "capacity": 20},
            "Room B": {"id": "Room B", "capacity": 60},
            "Room E": {"id": "Room E", "capacity": 120},
            "Room F": {"id": "Room F", "capacity": 45},
        },
        "tasks": {},
    }


class TestConflictDetection:
    """Tests for detect_room_conflict function."""

    def test_detect_conflict_same_room_same_date(self, sample_db):
        """Client 2 wants Room E on Feb 7 - same as Client 1's Option."""
        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
        )

        assert conflict is not None
        assert conflict["conflicting_event_id"] == "event_1"
        assert conflict["conflicting_client_email"] == "laura.meier@bluewin.ch"
        assert conflict["room_id"] == "Room E"
        assert conflict["event_date"] == "2026-02-07"
        assert conflict["status"] == "Option"

    def test_no_conflict_different_room(self, sample_db):
        """Client 2 wants Room B - no conflict."""
        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room B",
            event_date="2026-02-07",
        )

        assert conflict is None

    def test_no_conflict_different_date(self, sample_db):
        """Client 2 wants Room E on Feb 14 - no conflict."""
        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-14",
        )

        assert conflict is None

    def test_no_conflict_lead_status(self, sample_db):
        """No conflict if other event is only Lead (not Option/Confirmed)."""
        # Change Client 1's status to Lead
        sample_db["events"]["event_1"]["status"] = "Lead"

        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
        )

        assert conflict is None

    def test_conflict_confirmed_status(self, sample_db):
        """Conflict detected for Confirmed status too."""
        sample_db["events"]["event_1"]["status"] = "Confirmed"

        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
        )

        assert conflict is not None
        assert conflict["status"] == "Confirmed"


class TestAvailableRooms:
    """Tests for get_available_rooms_on_date function."""

    def test_rooms_available_excluding_option(self, sample_db):
        """Room E is Option, so only Room A, B, F should be available."""
        available = get_available_rooms_on_date(
            db=sample_db,
            event_id="event_2",
            event_date="2026-02-07",
        )

        assert "Room E" not in [r.lower() for r in available]
        assert len(available) == 3  # Room A, B, F

    def test_all_rooms_available_different_date(self, sample_db):
        """All rooms available on a date with no Options."""
        available = get_available_rooms_on_date(
            db=sample_db,
            event_id="event_2",
            event_date="2026-02-14",
        )

        assert len(available) == 4  # All rooms


class TestConflictWarning:
    """Tests for conflict warning message."""

    def test_warning_message_contains_key_info(self):
        """Warning message includes room, date, and options."""
        message = compose_conflict_warning_message("Room E", "2026-02-07")

        assert "Room E" in message
        assert "2026-02-07" in message
        assert "different room" in message.lower()
        assert "different date" in message.lower()
        assert "manager" in message.lower()


class TestHILTask:
    """Tests for HIL conflict task creation."""

    def test_create_hil_task(self, sample_db):
        """Create HIL task with both clients' info."""
        current_event = sample_db["events"]["event_2"]
        conflict_info = {
            "conflicting_event_id": "event_1",
            "conflicting_client_email": "laura.meier@bluewin.ch",
            "conflicting_client_name": "Laura Meier",
            "room_id": "Room E",
            "event_date": "2026-02-07",
            "status": "Option",
        }

        task = compose_conflict_hil_task(
            db=sample_db,
            current_event=current_event,
            conflict_info=conflict_info,
            insist_reason="It's my 50th birthday celebration",
        )

        assert task["type"] == "room_conflict_resolution"
        assert task["status"] == "pending"
        assert task["data"]["client_1"]["email"] == "laura.meier@bluewin.ch"
        assert task["data"]["client_2"]["email"] == "max.mueller@gmail.com"
        assert "birthday" in task["data"]["client_2"]["insist_reason"].lower()
        assert "Room E" in task["description"]
        assert "2026-02-07" in task["description"]


class TestLoserHandling:
    """Tests for handling the losing client after conflict resolution."""

    def test_loser_choose_another_room(self, sample_db):
        """Loser can choose another room if available on same date."""
        result = handle_loser_event(
            db=sample_db,
            loser_event_id="event_2",
        )

        assert result["action"] == "choose_another_room"
        assert result["step"] == 3
        assert len(result["available_rooms"]) == 3  # Room A, B, F

        # Check event was updated
        loser_event = sample_db["events"]["event_2"]
        assert loser_event["locked_room_id"] is None
        assert loser_event["current_step"] == 3

    def test_loser_choose_another_date_no_rooms(self, sample_db):
        """Loser must choose new date if no rooms available."""
        # Lock all other rooms for Feb 7
        sample_db["events"]["event_3"] = {
            "event_id": "event_3",
            "chosen_date": "2026-02-07",
            "locked_room_id": "Room A",
            "status": "Option",
        }
        sample_db["events"]["event_4"] = {
            "event_id": "event_4",
            "chosen_date": "2026-02-07",
            "locked_room_id": "Room B",
            "status": "Confirmed",
        }
        sample_db["events"]["event_5"] = {
            "event_id": "event_5",
            "chosen_date": "2026-02-07",
            "locked_room_id": "Room F",
            "status": "Option",
        }

        result = handle_loser_event(
            db=sample_db,
            loser_event_id="event_2",
        )

        assert result["action"] == "choose_another_date"
        assert result["step"] == 2

        # Check event was updated
        loser_event = sample_db["events"]["event_2"]
        assert loser_event["locked_room_id"] is None
        assert loser_event["chosen_date"] is None
        assert loser_event["date_confirmed"] is False
        assert loser_event["current_step"] == 2


class TestConflictFlow:
    """End-to-end test of the conflict resolution flow."""

    def test_full_conflict_flow_client1_wins(self, sample_db):
        """
        Full flow:
        1. Client 2 selects Room E (conflict detected)
        2. Client 2 insists
        3. HIL task created
        4. Manager picks Client 1 (first-come-first-served)
        5. Client 2 redirected to room selection
        """
        # Step 1: Detect conflict
        conflict = detect_room_conflict(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
        )
        assert conflict is not None

        # Step 2: Warning shown (just verify message is generated)
        warning = compose_conflict_warning_message("Room E", "2026-02-07")
        assert warning

        # Step 3: Client insists, HIL task created
        current_event = sample_db["events"]["event_2"]
        task = compose_conflict_hil_task(
            db=sample_db,
            current_event=current_event,
            conflict_info=conflict,
            insist_reason="Just really want this room",
        )

        # Add task to db
        task_id = "task_conflict_1"
        sample_db["tasks"][task_id] = task

        # Step 4: Manager picks Client 1 (no urgent reason from Client 2)
        # Winner is Client 1 (event_1), Loser is Client 2 (event_2)

        # Step 5: Handle loser
        result = handle_loser_event(
            db=sample_db,
            loser_event_id="event_2",
        )

        # Client 2 should be redirected to room selection
        assert result["action"] == "choose_another_room"
        assert result["step"] == 3

        # Client 1 is unaffected
        client1_event = sample_db["events"]["event_1"]
        assert client1_event["locked_room_id"] == "Room E"
        assert client1_event["status"] == "Option"

    def test_full_conflict_flow_client2_wins(self, sample_db):
        """
        Flow where Client 2 wins (e.g., birthday):
        1. Client 2 insists with good reason
        2. Manager picks Client 2
        3. Client 1 redirected to room selection
        """
        # Client 2 becomes the winner
        result = handle_loser_event(
            db=sample_db,
            loser_event_id="event_1",  # Client 1 loses
        )

        # Client 1 should be redirected
        assert result["action"] == "choose_another_room"
        assert result["step"] == 3

        loser_event = sample_db["events"]["event_1"]
        assert loser_event["locked_room_id"] is None
        assert loser_event["current_step"] == 3


# =============================================================================
# SCENARIO-SPECIFIC TESTS
# =============================================================================


class TestConflictTypeDetection:
    """Tests for detect_conflict_type - distinguishing soft vs hard conflicts."""

    def test_soft_conflict_option_plus_select(self, sample_db):
        """Scenario A: Option + Option → SOFT conflict."""
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="select",  # Client 2 is selecting (becoming Option)
        )

        assert conflict_type == ConflictType.SOFT
        assert conflict_info is not None
        assert conflict_info["status"] == "Option"

    def test_hard_conflict_option_plus_confirm(self, sample_db):
        """Scenario B: Option + Confirm → HARD conflict."""
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="confirm",  # Client 2 is trying to confirm
        )

        assert conflict_type == ConflictType.HARD
        assert conflict_info is not None

    def test_hard_conflict_confirmed_plus_select(self, sample_db):
        """If other is Confirmed, always HARD conflict."""
        sample_db["events"]["event_1"]["status"] = "Confirmed"

        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="select",
        )

        assert conflict_type == ConflictType.HARD
        assert conflict_info["status"] == "Confirmed"

    def test_no_conflict(self, sample_db):
        """No conflict if room is different."""
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room B",
            event_date="2026-02-07",
            action="select",
        )

        assert conflict_type == ConflictType.NONE
        assert conflict_info is None


class TestSoftConflictHandling:
    """Tests for Scenario A: Option + Option handling."""

    def test_soft_warning_message(self):
        """Soft warning is informative but not blocking."""
        warning = compose_soft_conflict_warning("Room E", "2026-02-07")

        assert "provisional hold" in warning.lower()
        assert "Room E" in warning
        assert "can still proceed" in warning.lower()

    def test_handle_soft_conflict_allows_proceed(self, sample_db):
        """Soft conflict allows client to proceed with warning."""
        conflict_info = {
            "conflicting_event_id": "event_1",
            "room_id": "Room E",
            "event_date": "2026-02-07",
        }

        result = handle_soft_conflict(
            db=sample_db,
            event_id="event_2",
            conflict_info=conflict_info,
        )

        assert result["action"] == "proceed_with_warning"
        assert result["conflict_type"] == "soft"
        assert result["allow_proceed"] is True
        assert "warning" in result

        # Check event flags set
        event = sample_db["events"]["event_2"]
        assert event["has_conflict"] is True
        assert event["conflict_type"] == "soft"


class TestHardConflictHandling:
    """Tests for Scenario B: Option + Confirm handling."""

    def test_hard_block_message(self):
        """Hard conflict message explains the situation."""
        message = compose_hard_conflict_block("Room E", "2026-02-07")

        assert "Room E" in message
        assert "held by another client" in message.lower()
        assert "manager" in message.lower()

    def test_hard_conflict_without_reason_asks(self, sample_db):
        """Without a reason, client is asked for one."""
        conflict_info = {
            "conflicting_event_id": "event_1",
            "room_id": "Room E",
            "event_date": "2026-02-07",
        }

        result = handle_hard_conflict(
            db=sample_db,
            event_id="event_2",
            conflict_info=conflict_info,
            client_reason=None,  # No reason provided
        )

        assert result["action"] == "ask_for_reason"
        assert result["allow_proceed"] is False
        assert "message" in result

        # Check event flags
        event = sample_db["events"]["event_2"]
        assert event["conflict_type"] == "hard_pending"

    def test_hard_conflict_with_reason_creates_hil(self, sample_db):
        """With a reason, HIL task is created."""
        conflict_info = {
            "conflicting_event_id": "event_1",
            "conflicting_client_email": "laura.meier@bluewin.ch",
            "room_id": "Room E",
            "event_date": "2026-02-07",
        }

        result = handle_hard_conflict(
            db=sample_db,
            event_id="event_2",
            conflict_info=conflict_info,
            client_reason="It's my 50th birthday!",
        )

        assert result["action"] == "hil_task_created"
        assert result["allow_proceed"] is False
        assert "task_id" in result

        # Check task was created
        tasks = sample_db["tasks"]
        assert len(tasks) == 1
        task = list(tasks.values())[0]
        assert task["type"] == "room_conflict_resolution"
        assert "birthday" in task["data"]["client_2"]["insist_reason"].lower()

        # Check event flags
        event = sample_db["events"]["event_2"]
        assert event["conflict_type"] == "hard"
        assert event["thread_state"] == "Waiting on HIL"


class TestConflictResolutionNotification:
    """Tests for notify_conflict_resolution - resolving and notifying both parties."""

    def test_resolve_client1_wins(self, sample_db):
        """Client 1 (first-come) wins, Client 2 notified only."""
        # Setup: Create a conflict task
        conflict_info = {
            "conflicting_event_id": "event_1",
            "conflicting_client_email": "laura.meier@bluewin.ch",
            "room_id": "Room E",
            "event_date": "2026-02-07",
        }
        result = handle_hard_conflict(
            db=sample_db,
            event_id="event_2",
            conflict_info=conflict_info,
            client_reason="It's my birthday",
        )
        task_id = result["task_id"]

        # Manager resolves: Client 1 wins
        winner_result, loser_result = notify_conflict_resolution(
            db=sample_db,
            task_id=task_id,
            winner_event_id="event_1",
            manager_notes="No urgent reason from Client 2",
        )

        # Winner (Client 1) is NOT notified (they don't know about conflict)
        assert winner_result["event_id"] == "event_1"
        assert winner_result["notify"] is False
        assert winner_result["message"] is None

        # Loser (Client 2) is redirected
        assert loser_result["action"] == "choose_another_room"
        assert loser_result["step"] == 3

    def test_resolve_client2_wins(self, sample_db):
        """Client 2 (insister) wins, both notified."""
        # Setup: Create a conflict task
        conflict_info = {
            "conflicting_event_id": "event_1",
            "conflicting_client_email": "laura.meier@bluewin.ch",
            "room_id": "Room E",
            "event_date": "2026-02-07",
        }
        result = handle_hard_conflict(
            db=sample_db,
            event_id="event_2",
            conflict_info=conflict_info,
            client_reason="It's my 50th birthday and we've been planning this for a year!",
        )
        task_id = result["task_id"]

        # Manager resolves: Client 2 wins (good reason)
        winner_result, loser_result = notify_conflict_resolution(
            db=sample_db,
            task_id=task_id,
            winner_event_id="event_2",
            manager_notes="50th birthday is a valid reason",
        )

        # Winner (Client 2) IS notified (they insisted)
        assert winner_result["event_id"] == "event_2"
        assert winner_result["notify"] is True
        assert "approved" in winner_result["message"].lower()

        # Loser (Client 1) is redirected
        assert loser_result["action"] == "choose_another_room"
        assert loser_result["step"] == 3


class TestFullScenarioFlow:
    """Full end-to-end tests for both scenarios."""

    def test_scenario_a_option_option_flow(self, sample_db):
        """
        Scenario A: Option + Option (Soft Conflict)
        1. Client 1 has Room E as Option
        2. Client 2 selects Room E
        3. Soft conflict detected
        4. Client 2 becomes Option with warning
        5. Later, Client 2 tries to confirm
        6. Hard conflict triggered
        """
        # Step 1-2: Already in fixture (Client 1 has Option)

        # Step 3: Client 2 selects same room
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="select",
        )
        assert conflict_type == ConflictType.SOFT

        # Step 4: Handle soft conflict - Client 2 proceeds with warning
        result = handle_soft_conflict(sample_db, "event_2", conflict_info)
        assert result["allow_proceed"] is True

        # Simulate Client 2 becoming Option
        sample_db["events"]["event_2"]["locked_room_id"] = "Room E"
        sample_db["events"]["event_2"]["status"] = "Option"

        # Step 5: Later, Client 2 tries to confirm
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="confirm",  # Now confirming
        )

        # Step 6: Now it's a HARD conflict
        assert conflict_type == ConflictType.HARD

    def test_scenario_b_confirm_blocked_flow(self, sample_db):
        """
        Scenario B: Option + Confirm (Hard Conflict)
        1. Client 1 has Room E as Option
        2. Client 2 tries to confirm Room E directly
        3. Blocked immediately with HIL
        """
        # Client 2 tries to confirm (skipping the soft conflict)
        conflict_type, conflict_info = detect_conflict_type(
            db=sample_db,
            event_id="event_2",
            room_id="Room E",
            event_date="2026-02-07",
            action="confirm",
        )

        assert conflict_type == ConflictType.HARD

        # Handle hard conflict without reason first
        result = handle_hard_conflict(sample_db, "event_2", conflict_info)
        assert result["action"] == "ask_for_reason"
        assert result["allow_proceed"] is False

        # Client provides reason
        result = handle_hard_conflict(
            sample_db, "event_2", conflict_info,
            client_reason="I need this room because of accessibility requirements"
        )
        assert result["action"] == "hil_task_created"

        # Now wait for manager resolution...
