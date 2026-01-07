"""Tests for the unified TimeWindow overlap detection module.

These tests verify that the system correctly detects time overlaps for:
- Same-day events with different time slots
- Multi-day events
- Adjacent (touching) time windows
- All-day events
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from workflows.common.time_window import TimeWindow, windows_overlap


class TestTimeWindowOverlap:
    """Test core overlap detection logic."""

    def test_no_overlap_same_day_sequential(self):
        """14:00-16:00 and 16:05-18:00 on same day = NO conflict."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "16:05", "18:00")
        assert w1 is not None
        assert w2 is not None
        assert not w1.overlaps(w2)

    def test_overlap_same_day_partial(self):
        """14:00-16:00 and 15:00-17:00 on same day = CONFLICT."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "15:00", "17:00")
        assert w1 is not None
        assert w2 is not None
        assert w1.overlaps(w2)

    def test_overlap_one_contains_other(self):
        """10:00-18:00 and 12:00-14:00 = CONFLICT (one contains the other)."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "10:00", "18:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "12:00", "14:00")
        assert w1 is not None
        assert w2 is not None
        assert w1.overlaps(w2)
        assert w2.overlaps(w1)  # Symmetric

    def test_no_overlap_different_days(self):
        """Any times on different days = NO conflict."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-16", "14:00", "16:00")
        assert w1 is not None
        assert w2 is not None
        assert not w1.overlaps(w2)

    def test_adjacent_no_conflict(self):
        """14:00-16:00 and 16:00-18:00 (touching end = start) = NO conflict."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "16:00", "18:00")
        assert w1 is not None
        assert w2 is not None
        assert not w1.overlaps(w2)

    def test_exact_same_window_overlaps(self):
        """Identical windows = CONFLICT."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        assert w1 is not None
        assert w2 is not None
        assert w1.overlaps(w2)


class TestMultiDayEvents:
    """Test multi-day event handling."""

    def test_multi_day_blocks_intermediate_day(self):
        """Fri 20:00 → Sun 14:00 blocks Saturday entirely."""
        # Multi-day event: Friday 20:00 to Sunday 14:00
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None

        # Saturday 10:00-12:00 should conflict
        saturday_event = TimeWindow.from_date_and_times("2026-02-14", "10:00", "12:00")
        assert saturday_event is not None
        assert multi_day.overlaps(saturday_event)

    def test_multi_day_no_conflict_before(self):
        """Event before multi-day start = NO conflict."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None

        # Friday 10:00-12:00 should NOT conflict (before 20:00 start)
        friday_morning = TimeWindow.from_date_and_times("2026-02-13", "10:00", "12:00")
        assert friday_morning is not None
        assert not multi_day.overlaps(friday_morning)

    def test_multi_day_no_conflict_after(self):
        """Event after multi-day end = NO conflict."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None

        # Sunday 16:00-18:00 should NOT conflict (after 14:00 end)
        sunday_evening = TimeWindow.from_date_and_times("2026-02-15", "16:00", "18:00")
        assert sunday_evening is not None
        assert not multi_day.overlaps(sunday_evening)

    def test_multi_day_partial_overlap_start_day(self):
        """Event overlapping start day = CONFLICT."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None

        # Friday 19:00-21:00 should conflict
        friday_overlap = TimeWindow.from_date_and_times("2026-02-13", "19:00", "21:00")
        assert friday_overlap is not None
        assert multi_day.overlaps(friday_overlap)

    def test_multi_day_partial_overlap_end_day(self):
        """Event overlapping end day = CONFLICT."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None

        # Sunday 12:00-16:00 should conflict
        sunday_overlap = TimeWindow.from_date_and_times("2026-02-15", "12:00", "16:00")
        assert sunday_overlap is not None
        assert multi_day.overlaps(sunday_overlap)

    def test_contains_date_intermediate(self):
        """Multi-day event contains intermediate dates."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None
        assert multi_day.contains_date("2026-02-14")  # Saturday

    def test_contains_date_start(self):
        """Multi-day event contains start date."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None
        assert multi_day.contains_date("2026-02-13")  # Friday

    def test_contains_date_end(self):
        """Multi-day event contains end date."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None
        assert multi_day.contains_date("2026-02-15")  # Sunday

    def test_does_not_contain_outside_date(self):
        """Multi-day event does not contain dates outside range."""
        multi_day = TimeWindow.multi_day("2026-02-13", "2026-02-15", "20:00", "14:00")
        assert multi_day is not None
        assert not multi_day.contains_date("2026-02-12")  # Thursday
        assert not multi_day.contains_date("2026-02-16")  # Monday


class TestAllDayEvents:
    """Test all-day event handling."""

    def test_all_day_blocks_any_time(self):
        """All-day event conflicts with any timed event on same date."""
        all_day = TimeWindow.all_day("2026-02-15")
        assert all_day is not None

        timed_event = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        assert timed_event is not None
        assert all_day.overlaps(timed_event)

    def test_all_day_no_conflict_different_date(self):
        """All-day event does not conflict with events on different dates."""
        all_day = TimeWindow.all_day("2026-02-15")
        assert all_day is not None

        other_day = TimeWindow.from_date_and_times("2026-02-16", "14:00", "16:00")
        assert other_day is not None
        assert not all_day.overlaps(other_day)


class TestFromEvent:
    """Test TimeWindow.from_event() extraction."""

    def test_from_event_with_requested_window(self):
        """Extract from requested_window ISO timestamps."""
        event = {
            "requested_window": {
                "start": "2026-02-15T14:00:00+01:00",
                "end": "2026-02-15T18:00:00+01:00",
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 14
        assert window.end.hour == 18

    def test_from_event_with_chosen_date_and_times(self):
        """Extract from chosen_date + event_data times."""
        event = {
            "chosen_date": "15.02.2026",
            "event_data": {
                "Start Time": "14:00",
                "End Time": "18:00",
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 14
        assert window.end.hour == 18

    def test_from_event_with_requirements_duration(self):
        """Extract from requirements.event_duration."""
        event = {
            "chosen_date": "15.02.2026",
            "requirements": {
                "event_duration": {
                    "start": "10:00",
                    "end": "12:00",
                }
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 10
        assert window.end.hour == 12

    def test_from_event_chosen_date_only(self):
        """Extract all-day window from chosen_date only."""
        event = {
            "chosen_date": "15.02.2026",
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 0
        assert window.end.hour == 23

    def test_from_event_with_not_specified_times(self):
        """Handle 'Not specified' times as all-day."""
        event = {
            "chosen_date": "15.02.2026",
            "event_data": {
                "Start Time": "Not specified",
                "End Time": "Not specified",
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 0
        assert window.end.hour == 23

    def test_from_event_multi_day(self):
        """Extract multi-day window from end_date_iso."""
        event = {
            "chosen_date": "13.02.2026",
            "end_date_iso": "2026-02-15",
            "event_data": {
                "Start Time": "20:00",
                "End Time": "14:00",
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.day == 13
        assert window.start.hour == 20
        assert window.end.day == 15
        assert window.end.hour == 14

    def test_from_event_no_date(self):
        """Return None if no date info."""
        event = {}
        window = TimeWindow.from_event(event)
        assert window is None

    def test_from_event_iso_chosen_date(self):
        """Handle ISO format chosen_date."""
        event = {
            "chosen_date": "2026-02-15",
            "event_data": {
                "Start Time": "14:00",
                "End Time": "18:00",
            }
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.day == 15


class TestFromIso:
    """Test TimeWindow.from_iso() parsing."""

    def test_from_iso_with_offset(self):
        """Parse ISO with timezone offset."""
        window = TimeWindow.from_iso(
            "2026-02-15T14:00:00+01:00",
            "2026-02-15T18:00:00+01:00",
        )
        assert window is not None
        assert window.start.hour == 14
        assert window.end.hour == 18

    def test_from_iso_with_z(self):
        """Parse ISO with Z (Zulu/UTC) suffix."""
        window = TimeWindow.from_iso(
            "2026-02-15T14:00:00Z",
            "2026-02-15T18:00:00Z",
        )
        assert window is not None
        assert window.start.tzinfo is not None

    def test_from_iso_invalid(self):
        """Return None for invalid ISO."""
        window = TimeWindow.from_iso("invalid", "also-invalid")
        assert window is None


class TestWindowsOverlapHelper:
    """Test windows_overlap() helper function."""

    def test_both_none_returns_true(self):
        """Conservative: assume overlap if both None."""
        assert windows_overlap(None, None) is True

    def test_one_none_returns_true(self):
        """Conservative: assume overlap if one is None."""
        w = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        assert windows_overlap(None, w) is True
        assert windows_overlap(w, None) is True

    def test_both_valid_checks_overlap(self):
        """When both valid, delegates to overlaps()."""
        w1 = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        w2 = TimeWindow.from_date_and_times("2026-02-15", "16:00", "18:00")
        assert windows_overlap(w1, w2) is False  # Adjacent, no overlap


class TestOvernightEvents:
    """Test events that cross midnight."""

    def test_overnight_event(self):
        """22:00-02:00 overnight event."""
        window = TimeWindow.from_date_and_times("2026-02-15", "22:00", "02:00")
        assert window is not None
        assert window.start.day == 15
        assert window.end.day == 16  # Next day
        assert window.end.hour == 2

    def test_overnight_overlap_with_next_day(self):
        """Overnight event overlaps with early next day event."""
        overnight = TimeWindow.from_date_and_times("2026-02-15", "22:00", "02:00")
        next_morning = TimeWindow.from_date_and_times("2026-02-16", "01:00", "03:00")
        assert overnight is not None
        assert next_morning is not None
        assert overnight.overlaps(next_morning)

    def test_overnight_no_overlap_with_later_next_day(self):
        """Overnight event does not overlap with later next day event."""
        overnight = TimeWindow.from_date_and_times("2026-02-15", "22:00", "02:00")
        next_afternoon = TimeWindow.from_date_and_times("2026-02-16", "14:00", "16:00")
        assert overnight is not None
        assert next_afternoon is not None
        assert not overnight.overlaps(next_afternoon)


class TestSiteVisitTimeAwareOverlap:
    """Test time-aware site visit conflict detection."""

    def test_site_visit_no_conflict_different_times(self):
        """Site visit 10:00-11:00 vs event 14:00-16:00 = NO conflict."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "sv-event",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                        "time_slot": "10:00",
                    },
                }
            ]
        }

        # Query for 14:00-16:00 - should NOT find the 10:00 site visit
        visits = get_site_visits_on_date(
            db, "2026-02-15", query_start_time="14:00", query_end_time="16:00"
        )
        assert len(visits) == 0

    def test_site_visit_conflict_overlapping_times(self):
        """Site visit 10:00-11:00 vs event 10:30-12:00 = CONFLICT."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "sv-event",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                        "time_slot": "10:00",
                    },
                }
            ]
        }

        # Query for 10:30-12:00 - SHOULD find the 10:00-11:00 site visit
        visits = get_site_visits_on_date(
            db, "2026-02-15", query_start_time="10:30", query_end_time="12:00"
        )
        assert len(visits) == 1
        assert visits[0]["event_id"] == "sv-event"

    def test_site_visit_no_time_slot_blocks_all_day(self):
        """Site visit without time_slot blocks any time on that day."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "sv-event",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                        # No time_slot = all-day
                    },
                }
            ]
        }

        # Any time query should find the all-day site visit
        visits = get_site_visits_on_date(
            db, "2026-02-15", query_start_time="14:00", query_end_time="16:00"
        )
        assert len(visits) == 1

    def test_site_visit_backward_compatibility_no_times(self):
        """Without query times, uses date-only comparison (backward compat)."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "sv-event",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                        "time_slot": "10:00",
                    },
                }
            ]
        }

        # Without times, should find by date only
        visits = get_site_visits_on_date(db, "2026-02-15")
        assert len(visits) == 1

        # Different date should not match
        visits = get_site_visits_on_date(db, "2026-02-16")
        assert len(visits) == 0

    def test_site_visit_adjacent_times_no_conflict(self):
        """Site visit 10:00-11:00 vs event 11:00-12:00 = NO conflict (adjacent)."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "sv-event",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                        "time_slot": "10:00",  # Implies 10:00-11:00
                    },
                }
            ]
        }

        # Query for 11:00-12:00 - adjacent, should NOT overlap
        visits = get_site_visits_on_date(
            db, "2026-02-15", query_start_time="11:00", query_end_time="12:00"
        )
        assert len(visits) == 0


class TestNoTimeBlocksAllDay:
    """Test that events without times block the entire day."""

    def test_event_without_times_is_all_day(self):
        """Event with no start/end time creates all-day window."""
        event = {
            "chosen_date": "15.02.2026",
            "event_data": {},  # No times
        }
        window = TimeWindow.from_event(event)
        assert window is not None
        assert window.start.hour == 0
        assert window.start.minute == 0
        assert window.end.hour == 23
        assert window.end.minute == 59

    def test_all_day_event_blocks_timed_event(self):
        """All-day event (no times) blocks any timed event on same day."""
        all_day = TimeWindow.from_date_and_times("2026-02-15", None, None)
        timed = TimeWindow.from_date_and_times("2026-02-15", "14:00", "16:00")
        assert all_day is not None
        assert timed is not None
        assert all_day.overlaps(timed)
        assert timed.overlaps(all_day)  # Symmetric

    def test_timed_event_blocks_all_day(self):
        """A timed event conflicts with an all-day event on same date."""
        timed = TimeWindow.from_date_and_times("2026-02-15", "10:00", "11:00")
        all_day = TimeWindow.from_date_and_times("2026-02-15", None, None)
        assert timed is not None
        assert all_day is not None
        assert timed.overlaps(all_day)

    def test_two_all_day_events_conflict(self):
        """Two all-day events on same date conflict."""
        day1 = TimeWindow.from_date_and_times("2026-02-15", None, None)
        day2 = TimeWindow.from_date_and_times("2026-02-15", None, None)
        assert day1 is not None
        assert day2 is not None
        assert day1.overlaps(day2)

    def test_all_day_no_conflict_different_dates(self):
        """All-day events on different dates don't conflict."""
        day1 = TimeWindow.from_date_and_times("2026-02-15", None, None)
        day2 = TimeWindow.from_date_and_times("2026-02-16", None, None)
        assert day1 is not None
        assert day2 is not None
        assert not day1.overlaps(day2)

    def test_partial_time_only_start_blocks_rest_of_day(self):
        """If only start time given, end defaults to end of day."""
        # Only start time, no end time
        window = TimeWindow.from_date_and_times("2026-02-15", "14:00", None)
        assert window is not None
        assert window.start.hour == 14
        assert window.end.hour == 23
        assert window.end.minute == 59

        # This should overlap with a 20:00-22:00 event
        evening = TimeWindow.from_date_and_times("2026-02-15", "20:00", "22:00")
        assert evening is not None
        assert window.overlaps(evening)

    def test_partial_time_only_end_blocks_start_of_day(self):
        """If only end time given, start defaults to start of day."""
        # Only end time, no start time
        window = TimeWindow.from_date_and_times("2026-02-15", None, "14:00")
        assert window is not None
        assert window.start.hour == 0
        assert window.end.hour == 14

        # This should overlap with a 10:00-12:00 event
        morning = TimeWindow.from_date_and_times("2026-02-15", "10:00", "12:00")
        assert morning is not None
        assert window.overlaps(morning)


class TestRoomConflictNoTimeScenarios:
    """Test room conflict detection with events missing time info."""

    def test_room_conflict_both_no_times_same_date(self):
        """Two events without times on same day = CONFLICT."""
        from detection.special.room_conflict import detect_room_conflict

        db = {
            "events": [
                {
                    "event_id": "event-1",
                    "chosen_date": "15.02.2026",
                    "locked_room_id": "Room E",
                    "status": "Option",
                    "event_data": {},  # No times
                }
            ]
        }

        # New event also without times on same date
        new_event = {
            "event_id": "event-2",
            "chosen_date": "15.02.2026",
            "event_data": {},  # No times
        }

        conflict = detect_room_conflict(
            db=db,
            event_id="event-2",
            room_id="Room E",
            event_date="15.02.2026",
            event_entry=new_event,
        )

        assert conflict is not None
        assert conflict["conflicting_event_id"] == "event-1"

    def test_room_conflict_one_timed_one_all_day(self):
        """Timed event vs all-day event on same day = CONFLICT."""
        from detection.special.room_conflict import detect_room_conflict

        db = {
            "events": [
                {
                    "event_id": "event-1",
                    "chosen_date": "15.02.2026",
                    "locked_room_id": "Room E",
                    "status": "Option",
                    "event_data": {},  # All day - no times
                }
            ]
        }

        # New event with specific time
        new_event = {
            "event_id": "event-2",
            "chosen_date": "15.02.2026",
            "event_data": {
                "Start Time": "14:00",
                "End Time": "16:00",
            },
        }

        conflict = detect_room_conflict(
            db=db,
            event_id="event-2",
            room_id="Room E",
            event_date="15.02.2026",
            event_entry=new_event,
        )

        assert conflict is not None
        assert conflict["conflicting_event_id"] == "event-1"

    def test_room_no_conflict_timed_vs_all_day_different_dates(self):
        """Timed event vs all-day event on different days = NO conflict."""
        from detection.special.room_conflict import detect_room_conflict

        db = {
            "events": [
                {
                    "event_id": "event-1",
                    "chosen_date": "15.02.2026",
                    "locked_room_id": "Room E",
                    "status": "Option",
                    "event_data": {},  # All day
                }
            ]
        }

        # New event on different date
        new_event = {
            "event_id": "event-2",
            "chosen_date": "16.02.2026",
            "event_data": {
                "Start Time": "14:00",
                "End Time": "16:00",
            },
        }

        conflict = detect_room_conflict(
            db=db,
            event_id="event-2",
            room_id="Room E",
            event_date="16.02.2026",
            event_entry=new_event,
        )

        assert conflict is None

    def test_room_no_conflict_same_date_non_overlapping_times(self):
        """Two timed events on same day with no overlap = NO conflict."""
        from detection.special.room_conflict import detect_room_conflict

        db = {
            "events": [
                {
                    "event_id": "event-1",
                    "chosen_date": "15.02.2026",
                    "locked_room_id": "Room E",
                    "status": "Option",
                    "event_data": {
                        "Start Time": "09:00",
                        "End Time": "11:00",
                    },
                }
            ]
        }

        # New event in afternoon - no overlap
        new_event = {
            "event_id": "event-2",
            "chosen_date": "15.02.2026",
            "event_data": {
                "Start Time": "14:00",
                "End Time": "16:00",
            },
        }

        conflict = detect_room_conflict(
            db=db,
            event_id="event-2",
            room_id="Room E",
            event_date="15.02.2026",
            event_entry=new_event,
        )

        assert conflict is None  # No overlap = no conflict
