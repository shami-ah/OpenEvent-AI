"""Tests for cross-step site visit booking.

Site visits can be initiated at ANY workflow step (2-7).

IMPORTANT: Site visits are VENUE-WIDE (not room-specific).
- No room selection needed
- Conflict with events: site visits CANNOT be booked on event days
"""
import pytest

from backend.workflows.common.site_visit_state import (
    SiteVisitState,
    cancel_site_visit,
    complete_site_visit,
    get_site_visit_state,
    is_site_visit_active,
    is_site_visit_scheduled,
    mark_site_visit_conflict,
    reset_site_visit_state,
    set_site_visit_date,
    start_site_visit_flow,
)


class TestSiteVisitState:
    """Test site visit state management."""

    def test_get_site_visit_state_creates_default(self):
        """get_site_visit_state should create default state if not exists."""
        event_entry = {}
        state = get_site_visit_state(event_entry)

        assert state["status"] == "idle"
        assert state["date_iso"] is None
        assert state["time_slot"] is None
        assert state["proposed_slots"] == []
        assert state["initiated_at_step"] is None
        assert state["has_event_conflict"] is False
        assert "site_visit_state" in event_entry

    def test_get_site_visit_state_preserves_existing(self):
        """get_site_visit_state should preserve existing state."""
        event_entry = {
            "site_visit_state": {
                "status": "scheduled",
                "date_iso": "2026-02-10",
                "time_slot": "14:00",
            }
        }
        state = get_site_visit_state(event_entry)

        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-10"
        assert state["time_slot"] == "14:00"

    def test_start_site_visit_flow(self):
        """Starting site visit should go directly to date_pending (venue-wide)."""
        event_entry = {}
        state = start_site_visit_flow(event_entry, initiated_at_step=4)

        assert state["status"] == "date_pending"
        assert state["initiated_at_step"] == 4
        assert state["date_iso"] is None
        assert state["proposed_slots"] == []

    def test_set_site_visit_date(self):
        """Setting date should transition to scheduled status."""
        event_entry = {}
        start_site_visit_flow(event_entry)

        set_site_visit_date(event_entry, "2026-02-15", "14:00")
        state = get_site_visit_state(event_entry)

        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-15"
        assert state["time_slot"] == "14:00"

    def test_is_site_visit_active(self):
        """is_site_visit_active should return True for date_pending."""
        event_entry = {}

        # idle -> not active
        assert is_site_visit_active(event_entry) is False

        # date_pending -> active
        start_site_visit_flow(event_entry)
        assert is_site_visit_active(event_entry) is True

        # scheduled -> not active
        set_site_visit_date(event_entry, "2026-02-15")
        assert is_site_visit_active(event_entry) is False

    def test_is_site_visit_scheduled(self):
        """is_site_visit_scheduled should return True only when scheduled."""
        event_entry = {}

        assert is_site_visit_scheduled(event_entry) is False

        start_site_visit_flow(event_entry)
        assert is_site_visit_scheduled(event_entry) is False

        set_site_visit_date(event_entry, "2026-02-15")
        assert is_site_visit_scheduled(event_entry) is True

    def test_complete_site_visit(self):
        """complete_site_visit should set status to completed."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        complete_site_visit(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "completed"

    def test_cancel_site_visit(self):
        """cancel_site_visit should set status to cancelled."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        cancel_site_visit(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "cancelled"

    def test_mark_site_visit_conflict(self):
        """mark_site_visit_conflict should set has_event_conflict flag."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        mark_site_visit_conflict(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["has_event_conflict"] is True

    def test_reset_site_visit_state(self):
        """reset_site_visit_state should clear all state."""
        event_entry = {}
        start_site_visit_flow(event_entry, initiated_at_step=5)
        set_site_visit_date(event_entry, "2026-02-15", "14:00")
        mark_site_visit_conflict(event_entry)

        reset_site_visit_state(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "idle"
        assert state["date_iso"] is None
        assert state["time_slot"] is None
        assert state["proposed_slots"] == []
        assert state["initiated_at_step"] is None
        assert state["has_event_conflict"] is False


class TestSiteVisitIntentDetection:
    """Test site visit intent detection."""

    def test_site_visit_keywords_in_classifier(self):
        """site_visit_request keywords should be recognized."""
        from backend.detection.intent.classifier import _detect_qna_types

        # Test various site visit request phrases
        test_phrases = [
            "I would like to book a site visit",
            "Can we schedule a visit to see the room?",
            "We want to see the venue before booking",
            "Can I visit beforehand?",
            "I'd like to tour the room",
        ]

        for phrase in test_phrases:
            qna_types = _detect_qna_types(phrase.lower())
            assert "site_visit_request" in qna_types or "site_visit_overview" in qna_types, \
                f"Expected site visit intent in '{phrase}', got {qna_types}"

    def test_site_visit_step_mapping(self):
        """site_visit_request should map to step 0 (cross-step)."""
        from backend.detection.intent.classifier import QNA_TYPE_TO_STEP

        assert QNA_TYPE_TO_STEP.get("site_visit_request") == 0  # Cross-step


class TestSiteVisitHandler:
    """Test site visit handler integration."""

    def test_is_site_visit_intent_detection(self):
        """is_site_visit_intent should detect site visit from detection result."""
        from backend.detection.unified import UnifiedDetectionResult
        from backend.workflows.common.site_visit_handler import is_site_visit_intent

        # No detection result
        assert is_site_visit_intent(None) is False

        # Detection without site visit
        result = UnifiedDetectionResult(intent="general_qna", qna_types=[])
        assert is_site_visit_intent(result) is False

        # Detection with site_visit_request
        result = UnifiedDetectionResult(intent="general_qna", qna_types=["site_visit_request"])
        assert is_site_visit_intent(result) is True

        # Detection with site_visit_overview
        result = UnifiedDetectionResult(intent="general_qna", qna_types=["site_visit_overview"])
        assert is_site_visit_intent(result) is True

        # Detection with Site Visit step anchor
        result = UnifiedDetectionResult(intent="general_qna", step_anchor="Site Visit")
        assert is_site_visit_intent(result) is True


class TestSiteVisitConflictDetection:
    """Test site visit conflict detection with events."""

    def test_blocked_dates_includes_event_date(self):
        """Event date should be in blocked dates."""
        from backend.workflows.common.site_visit_handler import _get_blocked_dates

        # Provide empty db to avoid loading from file
        db = {"events": []}
        event_entry = {"chosen_date": "15.02.2026"}
        blocked = _get_blocked_dates(event_entry, db=db)

        assert "2026-02-15" in blocked

    def test_blocked_dates_handles_iso_format(self):
        """ISO format dates should also work."""
        from backend.workflows.common.site_visit_handler import _get_blocked_dates

        db = {"events": []}
        event_entry = {"user_info": {"date": "2026-03-20"}}
        blocked = _get_blocked_dates(event_entry, db=db)

        assert "2026-03-20" in blocked

    def test_slot_generation_excludes_blocked_dates(self):
        """Generated slots should not include blocked dates."""
        from backend.workflows.common.site_visit_handler import _generate_visit_slots

        event_entry = {"chosen_date": "15.02.2026"}
        blocked = {"2026-02-14", "2026-02-13"}  # Block dates before event

        slots = _generate_visit_slots(event_entry, blocked)

        # Verify no slot is on a blocked date
        for slot in slots:
            date_part = slot.split(" at ")[0]  # "12.02.2026"
            day, month, year = map(int, date_part.split("."))
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            assert date_iso not in blocked, f"Slot {slot} is on blocked date {date_iso}"


class TestSiteVisitConflictWithMultipleEvents:
    """Test site visit conflict detection with multiple events in database."""

    def _create_mock_db(self, events_data):
        """Helper to create a mock database with events."""
        events = []
        for i, data in enumerate(events_data):
            events.append({
                "event_id": f"evt-{i}",
                "status": data.get("status", "Lead"),
                "chosen_date": data.get("chosen_date"),
                "event_data": {
                    "Event Date": data.get("event_date"),
                    "Email": f"client{i}@example.com",
                },
            })
        return {"events": events, "clients": {}, "tasks": []}

    def test_get_event_dates_returns_all_dates(self):
        """get_event_dates should return dates from all events."""
        from backend.workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
            {"event_date": "20.02.2026"},  # From event_data
        ])

        dates = get_event_dates(db)

        assert "2026-02-10" in dates
        assert "2026-02-15" in dates
        assert "2026-02-20" in dates
        assert len(dates) == 3

    def test_get_event_dates_excludes_cancelled(self):
        """get_event_dates should exclude cancelled events."""
        from backend.workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026", "status": "Lead"},
            {"chosen_date": "15.02.2026", "status": "Cancelled"},
            {"chosen_date": "20.02.2026", "status": "Confirmed"},
        ])

        dates = get_event_dates(db, exclude_cancelled=True)

        assert "2026-02-10" in dates
        assert "2026-02-15" not in dates  # Cancelled
        assert "2026-02-20" in dates
        assert len(dates) == 2

    def test_get_event_dates_can_include_cancelled(self):
        """get_event_dates with exclude_cancelled=False includes all."""
        from backend.workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026", "status": "Lead"},
            {"chosen_date": "15.02.2026", "status": "Cancelled"},
        ])

        dates = get_event_dates(db, exclude_cancelled=False)

        assert "2026-02-10" in dates
        assert "2026-02-15" in dates
        assert len(dates) == 2

    def test_get_event_dates_excludes_specific_event(self):
        """get_event_dates should exclude specified event_id."""
        from backend.workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
        ])

        dates = get_event_dates(db, exclude_event_id="evt-0")

        assert "2026-02-10" not in dates  # Excluded
        assert "2026-02-15" in dates
        assert len(dates) == 1

    def test_blocked_dates_includes_all_events_from_db(self):
        """_get_blocked_dates should block all event dates from database."""
        from backend.workflows.common.site_visit_handler import _get_blocked_dates

        # Create db with multiple events
        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
            {"chosen_date": "20.02.2026"},
        ])

        # Current event (not in db yet)
        event_entry = {"chosen_date": "25.02.2026"}

        blocked = _get_blocked_dates(event_entry, db=db)

        # Should include all dates
        assert "2026-02-10" in blocked
        assert "2026-02-15" in blocked
        assert "2026-02-20" in blocked
        assert "2026-02-25" in blocked  # Current event
        assert len(blocked) == 4

    def test_blocked_dates_with_db_loader_injection(self):
        """Test db loader injection for testing."""
        from backend.workflows.common.site_visit_handler import (
            _get_blocked_dates,
            set_db_loader,
        )

        # Create mock db
        mock_db = self._create_mock_db([
            {"chosen_date": "10.03.2026"},
            {"chosen_date": "15.03.2026"},
        ])

        # Set the db loader
        set_db_loader(lambda: mock_db)

        try:
            event_entry = {}  # No date, just checking db loader works
            blocked = _get_blocked_dates(event_entry)

            assert "2026-03-10" in blocked
            assert "2026-03-15" in blocked
        finally:
            # Reset loader
            set_db_loader(None)

    def test_slot_generation_avoids_all_event_dates(self):
        """Slot generation should avoid all event dates from database."""
        from backend.workflows.common.site_visit_handler import _generate_visit_slots

        # Current event is on 28.02.2026
        # Other events are on 20.02 and 21.02
        event_entry = {"chosen_date": "28.02.2026"}

        # Block dates that other events occupy
        blocked = {"2026-02-20", "2026-02-21", "2026-02-28"}

        slots = _generate_visit_slots(event_entry, blocked)

        # Verify no slot is on a blocked date
        for slot in slots:
            date_part = slot.split(" at ")[0]
            day, month, year = map(int, date_part.split("."))
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            assert date_iso not in blocked, f"Slot {slot} is on blocked date {date_iso}"

    def test_get_site_visits_on_date(self):
        """get_site_visits_on_date should find events with scheduled site visits."""
        from backend.workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "evt-1",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-10",
                    },
                },
                {
                    "event_id": "evt-2",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                    },
                },
                {
                    "event_id": "evt-3",
                    "site_visit_state": {
                        "status": "proposed",  # Not scheduled
                        "date_iso": "2026-02-10",
                    },
                },
            ],
            "clients": {},
            "tasks": [],
        }

        # Find visits on 2026-02-10
        visits = get_site_visits_on_date(db, "2026-02-10")

        assert len(visits) == 1  # Only evt-1, not evt-3 (not scheduled)
        assert visits[0]["event_id"] == "evt-1"

        # Find visits on 2026-02-15
        visits = get_site_visits_on_date(db, "2026-02-15")
        assert len(visits) == 1
        assert visits[0]["event_id"] == "evt-2"

        # No visits on 2026-02-20
        visits = get_site_visits_on_date(db, "2026-02-20")
        assert len(visits) == 0

    def test_conflict_rule_site_visit_blocked_on_event_day(self):
        """Site visits cannot be booked on event days."""
        from backend.workflows.common.site_visit_handler import _get_blocked_dates

        # Event on 15.02.2026
        db = self._create_mock_db([{"chosen_date": "15.02.2026"}])
        event_entry = {}

        blocked = _get_blocked_dates(event_entry, db=db)

        # 15.02.2026 is blocked for site visits
        assert "2026-02-15" in blocked

    def test_conflict_rule_event_allowed_on_site_visit_day(self):
        """Events CAN be booked on site visit days (triggers notification)."""
        from backend.workflows.io.database import get_site_visits_on_date

        # Client has site visit scheduled for 10.02.2026
        db = {
            "events": [{
                "event_id": "evt-1",
                "site_visit_state": {
                    "status": "scheduled",
                    "date_iso": "2026-02-10",
                },
            }],
            "clients": {},
            "tasks": [],
        }

        # When booking an event on that day, check for site visit conflicts
        visits = get_site_visits_on_date(db, "2026-02-10")

        # Should find the site visit - caller can create manager notification
        assert len(visits) == 1

        # The event CAN still be booked (not blocked)
        # The site visit conflict just triggers a notification


class TestSiteVisitVenueWide:
    """Test that site visits are venue-wide (no room needed)."""

    def test_no_room_in_state(self):
        """Site visit state should not require room_id."""
        event_entry = {}
        state = start_site_visit_flow(event_entry, initiated_at_step=3)

        # Room fields should be deprecated (None or missing)
        assert state.get("room_id") is None
        # Status should go directly to date_pending (no room_pending)
        assert state["status"] == "date_pending"

    def test_deprecated_room_functions_return_none(self):
        """Deprecated room functions should return None/no-op."""
        from backend.workflows.common.site_visit_state import (
            get_default_room_for_site_visit,
            get_site_visit_room,
            set_site_visit_room,
        )

        event_entry = {"locked_room_id": "Room A"}

        # These functions are deprecated and should return None
        assert get_site_visit_room(event_entry) is None
        assert get_default_room_for_site_visit(event_entry) is None

        # set_site_visit_room should be a no-op
        set_site_visit_room(event_entry, "Room B")
        state = get_site_visit_state(event_entry)
        assert state.get("room_id") is None  # Should not have been set
