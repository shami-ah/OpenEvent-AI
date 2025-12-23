"""
Tests for enhanced detour/change detection with dual-condition logic.

These tests verify:
1. Dual-condition requirement (revision signal + bound target)
2. EN/DE keyword detection
3. Three detour modes (LONG/FAST/EXPLICIT)
4. Q&A negative filtering (pure questions don't trigger detours)
5. Multi-class intent classification

Test ID format: DET_DETOUR_<category>_<number>_<description>
"""

import pytest
from typing import Dict, Any, Optional

# MIGRATED: from backend.workflows.nlu.keyword_buckets -> backend.detection.keywords.buckets
from backend.detection.keywords.buckets import (
    DetourMode,
    MessageIntent,
    ChangeIntentResult,
    compute_change_intent_score,
    has_revision_signal,
    has_bound_target,
    is_pure_qa,
    is_confirmation,
    is_decline,
    detect_language,
)
from backend.workflows.change_propagation import (
    ChangeType,
    EnhancedChangeResult,
    detect_change_type_enhanced,
    detect_change_with_fallback,
)
# MIGRATED: from backend.workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from backend.detection.response.matchers import (
    matches_change_pattern_enhanced,
    is_pure_qa_message,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def confirmed_date_state() -> Dict[str, Any]:
    """Event state with confirmed date."""
    return {
        "chosen_date": "2026-02-21",
        "date_confirmed": True,
        "locked_room_id": "room_a",
        "requirements": {
            "number_of_participants": 30,
            "seating_layout": "long_table",
        },
        "current_step": 3,
    }


@pytest.fixture
def step4_state() -> Dict[str, Any]:
    """Event state at Step 4 (Offer)."""
    return {
        "chosen_date": "2026-02-21",
        "date_confirmed": True,
        "locked_room_id": "room_a",
        "requirements": {
            "number_of_participants": 30,
            "seating_layout": "long_table",
        },
        "selected_products": ["three_course_menu", "wine_pairing"],
        "current_step": 4,
    }


# =============================================================================
# DUAL CONDITION TESTS
# =============================================================================

class TestDualConditionLogic:
    """Tests for the dual-condition requirement."""

    def test_DET_DETOUR_DUAL_001_both_conditions_met(self, confirmed_date_state):
        """Change verb + target = detour."""
        result = compute_change_intent_score(
            "Can we change the date to 2026-02-28?",
            confirmed_date_state
        )
        assert result.has_change_intent is True
        assert result.target_type == "date"
        assert len(result.revision_signals) > 0

    def test_DET_DETOUR_DUAL_002_revision_signal_only(self, confirmed_date_state):
        """Change verb without target = no detour."""
        # "I'd like to change something" - no specific target
        result = compute_change_intent_score(
            "Actually, I think we need to change something",
            confirmed_date_state
        )
        # Should not fire because no bound target
        assert result.has_change_intent is False or result.target_type is None

    def test_DET_DETOUR_DUAL_003_target_only_no_revision(self, confirmed_date_state):
        """Target mentioned without change intent = no detour."""
        result = compute_change_intent_score(
            "What dates are free in February?",
            confirmed_date_state
        )
        assert result.has_change_intent is False
        assert result.preliminary_intent == MessageIntent.GENERAL_QA

    def test_DET_DETOUR_DUAL_004_pure_qa_question(self, confirmed_date_state):
        """Pure Q&A question should not trigger detour."""
        result = compute_change_intent_score(
            "Do you have parking available?",
            confirmed_date_state
        )
        assert result.has_change_intent is False
        assert result.preliminary_intent == MessageIntent.GENERAL_QA


# =============================================================================
# ENGLISH CHANGE DETECTION TESTS
# =============================================================================

class TestEnglishChangeDetection:
    """Tests for English change patterns."""

    # --- Date changes ---

    def test_DET_DETOUR_EN_DATE_001_simple_change(self, confirmed_date_state):
        """Simple date change request."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Can we change the date to 2026-02-28?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE
        assert result.mode == DetourMode.FAST

    def test_DET_DETOUR_EN_DATE_002_sorry_correction(self, confirmed_date_state):
        """Apology-based correction."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Sorry, I meant 2026-02-28 instead"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE
        assert result.mode == DetourMode.FAST

    def test_DET_DETOUR_EN_DATE_003_reschedule(self, confirmed_date_state):
        """Reschedule request."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-03-15"},
            message_text="We need to reschedule to March 15th"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE

    def test_DET_DETOUR_EN_DATE_004_conflict(self, confirmed_date_state):
        """Conflict-based change."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="Something's come up on that day, can we move it?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE
        assert result.mode == DetourMode.LONG  # No new date provided

    def test_DET_DETOUR_EN_DATE_005_double_booked(self, confirmed_date_state):
        """Double-booked scenario."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="I just realized I'm double-booked that day"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.LONG

    def test_DET_DETOUR_EN_DATE_006_push_back(self, confirmed_date_state):
        """Push back idiom."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-03-01"},
            message_text="Could we push it back to March 1st?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE

    def test_DET_DETOUR_EN_DATE_007_no_longer_works(self, confirmed_date_state):
        """Date no longer works."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="That date doesn't work anymore for us"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.LONG

    # --- Room changes ---

    def test_DET_DETOUR_EN_ROOM_001_switch_room(self, confirmed_date_state):
        """Simple room switch."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"room": "room_b"},
            message_text="Can we switch to Room B instead?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.ROOM

    def test_DET_DETOUR_EN_ROOM_002_bigger_room(self, confirmed_date_state):
        """Request for bigger room."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="That room is too small, can we change it?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.ROOM
        assert result.mode == DetourMode.LONG

    def test_DET_DETOUR_EN_ROOM_003_prefer_different(self, confirmed_date_state):
        """Preference for different room."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"room": "sky_loft"},
            message_text="We'd prefer a different room, maybe Sky Loft?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.ROOM

    # --- Requirements changes ---

    def test_DET_DETOUR_EN_REQ_001_more_people(self, confirmed_date_state):
        """Increased attendee count."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"participants": 50},
            message_text="Actually we're 50 people now, not 30"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.REQUIREMENTS

    def test_DET_DETOUR_EN_REQ_002_numbers_up(self, confirmed_date_state):
        """Numbers have gone up."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"participants": 45},
            message_text="Our numbers have gone up to 45 participants"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.REQUIREMENTS

    def test_DET_DETOUR_EN_REQ_003_layout_change(self, confirmed_date_state):
        """Layout change request."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"layout": "u_shape"},
            message_text="Can we change to U-shape layout instead?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.REQUIREMENTS

    # --- Product changes ---

    def test_DET_DETOUR_EN_PROD_001_add_product(self, step4_state):
        """Add product to order."""
        result = detect_change_type_enhanced(
            step4_state,
            {"products_add": "prosecco"},
            message_text="Could we add Prosecco to the order?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.PRODUCTS

    def test_DET_DETOUR_EN_PROD_002_upgrade_package(self, step4_state):
        """Upgrade package."""
        result = detect_change_type_enhanced(
            step4_state,
            {"products": "premium_package"},
            message_text="Let's upgrade to the premium package"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.PRODUCTS


# =============================================================================
# GERMAN CHANGE DETECTION TESTS
# =============================================================================

class TestGermanChangeDetection:
    """Tests for German change patterns."""

    def test_DET_DETOUR_DE_DATE_001_termin_verschieben(self, confirmed_date_state):
        """German: Termin verschieben."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-03-14"},
            message_text="Können wir den Termin auf den 14. März verschieben?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE
        assert result.language == "de"

    def test_DET_DETOUR_DE_DATE_002_doch_nicht_mehr(self, confirmed_date_state):
        """German: klappt doch nicht mehr."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="Der 21. klappt doch nicht mehr, ginge der 28.?"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.LONG

    def test_DET_DETOUR_DE_DATE_003_stattdessen(self, confirmed_date_state):
        """German: stattdessen."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Stattdessen am 28. Februar?"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.DATE

    def test_DET_DETOUR_DE_DATE_004_doch_lieber(self, confirmed_date_state):
        """German: doch lieber."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-03-01"},
            message_text="Wir würden den Termin doch lieber am 1. März machen"
        )
        assert result.is_change is True

    def test_DET_DETOUR_DE_ROOM_001_raum_wechseln(self, confirmed_date_state):
        """German: Raum wechseln."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"room": "saal_b"},
            message_text="Können wir den Raum wechseln? Lieber Saal B"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.ROOM

    def test_DET_DETOUR_DE_REQ_001_mehr_personen(self, confirmed_date_state):
        """German: mehr Personen."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"participants": 50},
            message_text="Wir sind doch mehr Personen als gedacht, etwa 50"
        )
        assert result.is_change is True
        assert result.change_type == ChangeType.REQUIREMENTS


# =============================================================================
# DETOUR MODE TESTS
# =============================================================================

class TestDetourModes:
    """Tests for the three detour modes."""

    def test_DET_DETOUR_MODE_001_long_no_new_value(self, confirmed_date_state):
        """LONG mode: no new value provided."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="I need to change the date please"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.LONG

    def test_DET_DETOUR_MODE_002_fast_new_value(self, confirmed_date_state):
        """FAST mode: new value provided."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Sorry, I meant 2026-02-28"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.FAST

    def test_DET_DETOUR_MODE_003_explicit_old_and_new(self, confirmed_date_state):
        """EXPLICIT mode: both old and new mentioned."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="I wanted to change from 2026-02-21 to 2026-02-28"
        )
        assert result.is_change is True
        assert result.mode == DetourMode.EXPLICIT


# =============================================================================
# Q&A NEGATIVE FILTER TESTS
# =============================================================================

class TestQANegativeFilter:
    """Tests ensuring pure Q&A doesn't trigger detours."""

    def test_DET_DETOUR_QA_001_what_rooms_free(self, confirmed_date_state):
        """Q&A: What rooms are free."""
        result = compute_change_intent_score(
            "What rooms are free in December?",
            confirmed_date_state
        )
        assert result.has_change_intent is False
        assert result.preliminary_intent == MessageIntent.GENERAL_QA

    def test_DET_DETOUR_QA_002_do_you_have_parking(self, confirmed_date_state):
        """Q&A: Do you have parking."""
        result = compute_change_intent_score(
            "Do you have parking available?",
            confirmed_date_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_QA_003_whats_the_price(self, confirmed_date_state):
        """Q&A: What's the price."""
        result = compute_change_intent_score(
            "What's the total price?",
            confirmed_date_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_QA_004_which_room_fits(self, confirmed_date_state):
        """Q&A: Which room fits."""
        result = compute_change_intent_score(
            "Which room fits 30 people?",
            confirmed_date_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_QA_005_german_gibt_es(self, confirmed_date_state):
        """Q&A: German gibt es."""
        result = compute_change_intent_score(
            "Gibt es einen freien Termin im Dezember?",
            confirmed_date_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_QA_006_what_menu_options(self, step4_state):
        """Q&A: What menu options."""
        result = compute_change_intent_score(
            "What menu options do you have?",
            step4_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_QA_007_is_pure_qa_function(self):
        """Test is_pure_qa_message helper."""
        assert is_pure_qa_message("What rooms are free?") is True
        assert is_pure_qa_message("Do you have parking?") is True
        assert is_pure_qa_message("Can we change the date?") is False


# =============================================================================
# CONFIRMATION VS CHANGE TESTS
# =============================================================================

class TestConfirmationVsChange:
    """Tests for distinguishing confirmation from change."""

    def test_DET_DETOUR_CONF_001_sounds_good(self, confirmed_date_state):
        """Confirmation: Sounds good."""
        result = compute_change_intent_score(
            "That sounds good, let's proceed",
            confirmed_date_state
        )
        assert result.has_change_intent is False
        # Should be confirmation, not change

    def test_DET_DETOUR_CONF_002_yes_proceed(self, confirmed_date_state):
        """Confirmation: Yes, proceed."""
        result = compute_change_intent_score(
            "Yes, please proceed with that date",
            confirmed_date_state
        )
        assert result.has_change_intent is False

    def test_DET_DETOUR_CONF_003_same_value_mentioned(self, confirmed_date_state):
        """Same value mentioned = confirmation, not change."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-21"},  # Same as current
            message_text="I confirm the date 2026-02-21"
        )
        # Should detect this is same value
        assert result.is_change is False or result.new_value == result.old_value


# =============================================================================
# HYPOTHETICAL QUESTION TESTS
# =============================================================================

class TestHypotheticalQuestions:
    """Tests for hypothetical questions (shouldn't trigger change)."""

    def test_DET_DETOUR_HYPO_001_what_if(self, confirmed_date_state):
        """Hypothetical: What if we changed."""
        is_match, _, _, result = matches_change_pattern_enhanced(
            "What if we changed the date?",
            confirmed_date_state
        )
        assert is_match is False

    def test_DET_DETOUR_HYPO_002_hypothetically(self, confirmed_date_state):
        """Hypothetical: Hypothetically."""
        is_match, _, _, result = matches_change_pattern_enhanced(
            "Hypothetically, could we move to a bigger room?",
            confirmed_date_state
        )
        assert is_match is False

    def test_DET_DETOUR_HYPO_003_just_wondering(self, confirmed_date_state):
        """Hypothetical: Just wondering."""
        is_match, _, _, result = matches_change_pattern_enhanced(
            "Just wondering, would it be possible to change the time?",
            confirmed_date_state
        )
        assert is_match is False


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_DET_DETOUR_EDGE_001_empty_message(self, confirmed_date_state):
        """Empty message."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text=""
        )
        assert result.is_change is False

    def test_DET_DETOUR_EDGE_002_none_message(self, confirmed_date_state):
        """None message."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text=None
        )
        assert result.is_change is False

    def test_DET_DETOUR_EDGE_003_mixed_language(self, confirmed_date_state):
        """Mixed EN/DE message - should detect change even with loanwords."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Sorry, können wir den date auf 28.02 ändern?"
        )
        assert result.is_change is True
        # Language might be "de" or "mixed" depending on detection thresholds
        # The important thing is that the change is detected
        assert result.language in ("de", "mixed")

    def test_DET_DETOUR_EDGE_004_multiple_targets(self, confirmed_date_state):
        """Message mentions multiple targets."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {"date": "2026-02-28", "room": "room_b"},
            message_text="Can we change the date to Feb 28 and also switch to Room B?"
        )
        # Should detect at least one change
        assert result.is_change is True

    def test_DET_DETOUR_EDGE_005_indirect_phrasing(self, confirmed_date_state):
        """Indirect/uncommon phrasing."""
        result = detect_change_type_enhanced(
            confirmed_date_state,
            {},
            message_text="If it's not too late, could we do Friday instead?"
        )
        assert result.is_change is True


# =============================================================================
# BACKWARD COMPATIBILITY TESTS
# =============================================================================

class TestBackwardCompatibility:
    """Tests for backward compatibility with legacy detection."""

    def test_DET_DETOUR_COMPAT_001_fallback_wrapper(self, confirmed_date_state):
        """detect_change_with_fallback returns both formats."""
        change_type, enhanced = detect_change_with_fallback(
            confirmed_date_state,
            {"date": "2026-02-28"},
            message_text="Can we change the date to 2026-02-28?"
        )
        assert change_type == ChangeType.DATE
        assert enhanced.is_change is True
        assert enhanced.change_type == ChangeType.DATE

    def test_DET_DETOUR_COMPAT_002_no_change_fallback(self, confirmed_date_state):
        """No change returns None for legacy compat."""
        change_type, enhanced = detect_change_with_fallback(
            confirmed_date_state,
            {},
            message_text="What rooms are free?"
        )
        assert change_type is None
        assert enhanced.is_change is False


# =============================================================================
# AMBIGUOUS TARGET RESOLUTION TESTS
# =============================================================================

from backend.workflows.change_propagation import (
    resolve_ambiguous_target,
    detect_change_type_enhanced_with_disambiguation,
    AmbiguousTargetResult,
    _has_value_without_explicit_type,
)


class TestAmbiguousTargetResolution:
    """Tests for resolving ambiguous targets (value without explicit type)."""

    @pytest.fixture
    def state_with_both_dates(self) -> Dict[str, Any]:
        """Event state with both event date and site visit date confirmed."""
        return {
            "chosen_date": "2026-02-21",
            "date_confirmed": True,
            "date_confirmed_at_step": 2,
            "site_visit_date": "2026-02-10",
            "site_visit_confirmed_at_step": 7,
            "locked_room_id": "room_a",
            "current_step": 4,
        }

    @pytest.fixture
    def state_with_event_date_only(self) -> Dict[str, Any]:
        """Event state with only event date confirmed."""
        return {
            "chosen_date": "2026-02-21",
            "date_confirmed": True,
            "date_confirmed_at_step": 2,
            "locked_room_id": "room_a",
            "current_step": 3,
        }

    def test_DET_DETOUR_AMBIG_001_value_without_type_detected(self):
        """Detect value without explicit type mention."""
        # Has date value, doesn't say "date"
        assert _has_value_without_explicit_type(
            "change to 2026-02-14 18:00-22:00",
            "date"
        ) is True

        # Has date value AND says "date"
        assert _has_value_without_explicit_type(
            "change the date to 2026-02-14",
            "date"
        ) is False

    def test_DET_DETOUR_AMBIG_002_single_variable_no_ambiguity(self, state_with_event_date_only):
        """Single confirmed variable - no ambiguity."""
        result = resolve_ambiguous_target(
            state_with_event_date_only,
            "date",
            "change to 2026-02-28"
        )
        assert result.is_ambiguous is False
        assert result.inferred_target == "event_date"
        assert result.needs_disambiguation_message is False

    def test_DET_DETOUR_AMBIG_003_multiple_variables_ambiguous(self, state_with_both_dates):
        """Multiple confirmed variables - is ambiguous."""
        result = resolve_ambiguous_target(
            state_with_both_dates,
            "date",
            "change to 2026-02-28"
        )
        assert result.is_ambiguous is True
        assert result.needs_disambiguation_message is True
        assert result.disambiguation_message is not None

    def test_DET_DETOUR_AMBIG_004_recency_based_inference(self):
        """More recent confirmation is preferred when unambiguous."""
        # Event date at step 2, site visit at step 7
        # Current step is 7, so site visit (step 7) is closest
        state = {
            "chosen_date": "2026-02-21",
            "date_confirmed": True,
            "date_confirmed_at_step": 2,
            "site_visit_date": "2026-02-10",
            "site_visit_confirmed_at_step": 7,
            "current_step": 7,  # Currently at step 7
        }
        result = resolve_ambiguous_target(
            state,
            "date",
            "change to 2026-02-28"
        )
        # Site visit was confirmed at step 7, we're at step 7, so it's closest
        assert result.is_ambiguous is True
        assert result.inferred_target == "site_visit_date"
        assert result.needs_disambiguation_message is True

    def test_DET_DETOUR_AMBIG_005_explicit_type_no_disambiguation(self, state_with_both_dates):
        """Explicit type mention skips disambiguation."""
        enhanced, disambiguation = detect_change_type_enhanced_with_disambiguation(
            state_with_both_dates,
            {"date": "2026-02-28"},
            message_text="change the date to 2026-02-28"  # Says "date" explicitly
        )
        assert enhanced.is_change is True
        assert disambiguation is None  # No disambiguation needed

    def test_DET_DETOUR_AMBIG_006_implicit_type_needs_disambiguation(self, state_with_both_dates):
        """Implicit type (value only) triggers disambiguation."""
        enhanced, disambiguation = detect_change_type_enhanced_with_disambiguation(
            state_with_both_dates,
            {"date": "2026-02-28"},
            message_text="change to 2026-02-28"  # No "date" mentioned
        )
        assert enhanced.is_change is True
        assert disambiguation is not None
        assert disambiguation.is_ambiguous is True

    def test_DET_DETOUR_AMBIG_007_disambiguation_message_format(self, state_with_both_dates):
        """Disambiguation message has correct format."""
        result = resolve_ambiguous_target(
            state_with_both_dates,
            "date",
            "change to 2026-02-28"
        )
        if result.disambiguation_message:
            # Should mention how to switch
            assert "change" in result.disambiguation_message.lower()
            # Should mention the alternative
            assert any(alt in result.disambiguation_message.lower()
                      for alt in ["site visit", "event date"])

    def test_DET_DETOUR_AMBIG_008_no_confirmed_variables(self):
        """No confirmed variables - default to event-level."""
        empty_state = {"current_step": 2}
        result = resolve_ambiguous_target(
            empty_state,
            "date",
            "change to 2026-02-28"
        )
        assert result.is_ambiguous is False
        assert result.inferred_target == "event_date"
        assert result.inference_reason == "no_confirmed_variables"
