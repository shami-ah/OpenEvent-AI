"""
Tests for Room Search Intent Detection (DET_ROOM_SEARCH_*)

Tests the new room search intent categories added to the detection system:
- REQUEST_OPTION: Soft holds/tentative bookings
- CHECK_CAPACITY: Capacity/fit questions
- CHECK_ALTERNATIVES: Waitlist/alternative date requests
- CONFIRM_BOOKING: Strong confirmation signals

References:
- docs/plans/DETECTION_IMPROVEMENT_PLAN.md
- Industry best practices for booking intent classification
"""

from __future__ import annotations

import pytest

# MIGRATED: from backend.llm.intent_classifier -> backend.detection.intent.classifier
from backend.detection.intent.classifier import classify_intent, _detect_qna_types


# ==============================================================================
# DET_ROOM_SEARCH_001: REQUEST_OPTION Detection
# ==============================================================================


class TestRequestOptionDetection:
    """Tests for REQUEST_OPTION intent - soft holds/tentative bookings."""

    def test_DET_ROOM_SEARCH_001_can_i_hold(self):
        """'Can I hold the space?' -> request_option"""
        qna_types = _detect_qna_types("can i hold the space?")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_can_we_hold(self):
        """'Can we hold this date?' -> request_option"""
        qna_types = _detect_qna_types("can we hold this date?")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_tentative_booking(self):
        """'Is a tentative booking possible?' -> request_option"""
        qna_types = _detect_qna_types("is a tentative booking possible?")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_soft_hold(self):
        """'Can we put a soft hold on this?' -> request_option"""
        qna_types = _detect_qna_types("can we put a soft hold on this?")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_provisional_booking(self):
        """'We'd like a provisional booking' -> request_option"""
        qna_types = _detect_qna_types("we'd like a provisional booking")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_first_option(self):
        """'Do we have first option?' -> request_option"""
        qna_types = _detect_qna_types("do we have first option?")
        assert "request_option" in qna_types

    def test_DET_ROOM_SEARCH_001_put_on_hold(self):
        """'Put on hold' -> request_option"""
        qna_types = _detect_qna_types("can you put on hold for us?")
        assert "request_option" in qna_types


# ==============================================================================
# DET_ROOM_SEARCH_002: CONFIRM_BOOKING Detection (Stronger than generic yes)
# ==============================================================================


class TestConfirmBookingDetection:
    """Tests for CONFIRM_BOOKING intent - strong confirmation signals."""

    def test_DET_ROOM_SEARCH_002_green_light(self):
        """'Green light on this!' -> confirm_booking"""
        qna_types = _detect_qna_types("green light on this!")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_lock_it_in(self):
        """'Lock it in!' -> confirm_booking"""
        qna_types = _detect_qna_types("lock it in!")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_secure_the_date(self):
        """'Please secure the date' -> confirm_booking"""
        qna_types = _detect_qna_types("please secure the date")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_binding_booking(self):
        """'We want a binding booking' -> confirm_booking"""
        qna_types = _detect_qna_types("we want a binding booking")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_ready_to_book(self):
        """'Ready to book' -> confirm_booking"""
        qna_types = _detect_qna_types("we're ready to book")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_sign_us_up(self):
        """'Sign us up!' -> confirm_booking"""
        qna_types = _detect_qna_types("sign us up!")
        assert "confirm_booking" in qna_types

    def test_DET_ROOM_SEARCH_002_thats_a_deal(self):
        """'That's a deal' -> confirm_booking"""
        qna_types = _detect_qna_types("that's a deal")
        assert "confirm_booking" in qna_types


# ==============================================================================
# DET_ROOM_SEARCH_003: CHECK_CAPACITY Detection
# ==============================================================================


class TestCheckCapacityDetection:
    """Tests for CHECK_CAPACITY intent - capacity/fit questions."""

    def test_DET_ROOM_SEARCH_003_does_it_fit(self):
        """'Does it fit 50 people?' -> check_capacity"""
        qna_types = _detect_qna_types("does it fit 50 people?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_standing_capacity(self):
        """'What is the standing capacity?' -> check_capacity"""
        qna_types = _detect_qna_types("what is the standing capacity?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_theater_style(self):
        """'Theater style for 100?' -> check_capacity"""
        qna_types = _detect_qna_types("can you do theater style for 100?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_how_many_people(self):
        """'How many people can it hold?' -> check_capacity"""
        qna_types = _detect_qna_types("how many people can it hold?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_max_capacity(self):
        """'What's the max capacity?' -> check_capacity"""
        qna_types = _detect_qna_types("what's the max capacity?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_enough_space(self):
        """'Is there enough space for 80?' -> check_capacity"""
        qna_types = _detect_qna_types("is there enough space for 80?")
        assert "check_capacity" in qna_types

    def test_DET_ROOM_SEARCH_003_seated_capacity(self):
        """'What is the seated capacity?' -> check_capacity"""
        qna_types = _detect_qna_types("what is the seated capacity?")
        assert "check_capacity" in qna_types


# ==============================================================================
# DET_ROOM_SEARCH_004: CHECK_ALTERNATIVES Detection
# ==============================================================================


class TestCheckAlternativesDetection:
    """Tests for CHECK_ALTERNATIVES intent - waitlist/fallback requests."""

    def test_DET_ROOM_SEARCH_004_waitlist(self):
        """'Can we be on the waitlist?' -> check_alternatives"""
        qna_types = _detect_qna_types("can we be on the waitlist?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_waiting_list(self):
        """'Is there a waiting list?' -> check_alternatives"""
        qna_types = _detect_qna_types("is there a waiting list?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_next_opening(self):
        """'What's the next opening?' -> check_alternatives"""
        qna_types = _detect_qna_types("what's the next opening?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_backup_option(self):
        """'Do you have a backup option?' -> check_alternatives"""
        qna_types = _detect_qna_types("do you have a backup option?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_alternative_dates(self):
        """'Any alternative dates?' -> check_alternatives"""
        qna_types = _detect_qna_types("any alternative dates?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_next_available(self):
        """'When is the next available?' -> check_alternatives"""
        qna_types = _detect_qna_types("when is the next available?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_other_rooms(self):
        """'Any other rooms available?' -> check_alternatives"""
        qna_types = _detect_qna_types("any other rooms available?")
        assert "check_alternatives" in qna_types

    def test_DET_ROOM_SEARCH_004_what_else(self):
        """'What else do you have?' -> check_alternatives"""
        qna_types = _detect_qna_types("what else do you have?")
        assert "check_alternatives" in qna_types


# ==============================================================================
# DET_ROOM_SEARCH_005: CHECK_AVAILABILITY Detection
# ==============================================================================


class TestCheckAvailabilityDetection:
    """Tests for CHECK_AVAILABILITY intent - basic availability checks."""

    def test_DET_ROOM_SEARCH_005_is_it_available(self):
        """'Is it available?' -> check_availability"""
        qna_types = _detect_qna_types("is it available on the 15th?")
        assert "check_availability" in qna_types

    def test_DET_ROOM_SEARCH_005_is_it_free(self):
        """'Is it free?' -> check_availability"""
        qna_types = _detect_qna_types("is it free that day?")
        assert "check_availability" in qna_types

    def test_DET_ROOM_SEARCH_005_can_we_book(self):
        """'Can we book it?' -> check_availability"""
        qna_types = _detect_qna_types("can we book it?")
        assert "check_availability" in qna_types

    def test_DET_ROOM_SEARCH_005_status_of(self):
        """'Status of Room A?' -> check_availability"""
        qna_types = _detect_qna_types("what's the status of room a?")
        assert "check_availability" in qna_types


# ==============================================================================
# DET_ROOM_SEARCH_006: Step Anchor Routing
# ==============================================================================


class TestStepAnchorRouting:
    """Tests for _step_anchor_from_qna updates with new Q&A types."""

    def test_DET_ROOM_SEARCH_006_request_option_routes_to_offer(self):
        """REQUEST_OPTION should route to Offer Review."""
        result = classify_intent("Can we option the space?", current_step=3)
        assert result["step_anchor"] == "Offer Review"

    def test_DET_ROOM_SEARCH_006_confirm_booking_routes_to_offer(self):
        """CONFIRM_BOOKING should route to Offer Review."""
        result = classify_intent("Green light, let's lock it in!", current_step=3)
        assert result["step_anchor"] == "Offer Review"

    def test_DET_ROOM_SEARCH_006_check_capacity_routes_to_room(self):
        """CHECK_CAPACITY should route to Room Availability."""
        result = classify_intent("What's the standing capacity?", current_step=2)
        assert result["step_anchor"] == "Room Availability"

    def test_DET_ROOM_SEARCH_006_check_alternatives_routes_to_room(self):
        """CHECK_ALTERNATIVES should route to Room Availability."""
        result = classify_intent("Any alternative dates?", current_step=2)
        assert result["step_anchor"] == "Room Availability"

    def test_DET_ROOM_SEARCH_006_check_availability_routes_to_room(self):
        """CHECK_AVAILABILITY should route to Room Availability."""
        # Note: Avoid date-related words (Friday, December, etc.) which trigger
        # date_confirmation routing. Use purely availability-focused phrase.
        result = classify_intent("Can we book it for our event?", current_step=3)
        assert result["step_anchor"] == "Room Availability"


# ==============================================================================
# DET_ROOM_SEARCH_007: Disambiguation (Option vs Availability)
# ==============================================================================


class TestIntentDisambiguation:
    """Tests ensuring similar phrases are correctly distinguished."""

    def test_DET_ROOM_SEARCH_007_hold_vs_available(self):
        """'Can I hold it?' (option) vs 'Is it available?' (availability)"""
        hold_types = _detect_qna_types("can i hold the room?")
        # Use exact phrase from _QNA_KEYWORDS["check_availability"]
        avail_types = _detect_qna_types("is it available on friday?")

        assert "request_option" in hold_types
        assert "check_availability" in avail_types
        # They should be different
        assert "request_option" not in avail_types

    def test_DET_ROOM_SEARCH_007_lock_in_vs_generic_yes(self):
        """'Lock it in' (strong confirm) vs 'yes' (resume phrase)"""
        strong_types = _detect_qna_types("lock it in!")
        assert "confirm_booking" in strong_types

    def test_DET_ROOM_SEARCH_007_capacity_vs_room_features(self):
        """Capacity question vs room features question"""
        cap_types = _detect_qna_types("what's the capacity?")
        feat_types = _detect_qna_types("does it have hdmi?")

        assert "check_capacity" in cap_types
        assert "rooms_by_feature" in feat_types


# ==============================================================================
# DET_ROOM_SEARCH_008: No False Positives
# ==============================================================================


class TestNoFalsePositives:
    """Tests ensuring we don't over-detect intents."""

    def test_DET_ROOM_SEARCH_008_generic_greeting(self):
        """Generic greeting should not trigger room search intents."""
        qna_types = _detect_qna_types("hello, how are you?")
        room_search_types = {"check_availability", "request_option", "check_capacity",
                            "check_alternatives", "confirm_booking"}
        assert not any(t in qna_types for t in room_search_types)

    def test_DET_ROOM_SEARCH_008_pure_date_reply(self):
        """Pure date reply should not trigger room search intents."""
        qna_types = _detect_qna_types("december 15th works for us")
        assert "request_option" not in qna_types
        assert "confirm_booking" not in qna_types

    def test_DET_ROOM_SEARCH_008_catering_question(self):
        """Catering question should be detected as catering, not room search."""
        qna_types = _detect_qna_types("what menus do you offer?")
        assert "catering_for" in qna_types
        assert "check_availability" not in qna_types
