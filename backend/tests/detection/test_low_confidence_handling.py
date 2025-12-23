
import pytest

# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import (
    should_seek_clarification,
    should_ignore_message,
    classify_response_action,
    has_workflow_signal,
    is_gibberish,
    CONFIDENCE_NONSENSE,
)
from backend.workflows.groups import negotiation_close


class DummyState:
    def __init__(self) -> None:
        self.client_id = "client-1"
        self.intent = None
        self.confidence = 0.0
        self.draft_messages = []
        self.thread_state = ""
        self.context_snapshot = {}
        self.extras = {}
        self.current_step = None
        self.user_info = {}

    def add_draft_message(self, draft):
        self.draft_messages.append(draft)

    def set_thread_state(self, value: str) -> None:
        self.thread_state = value


@pytest.fixture(autouse=True)
def stub_update_event_metadata(monkeypatch):
    monkeypatch.setattr(negotiation_close, "update_event_metadata", lambda *args, **kwargs: None)


def test_low_confidence_triggers_clarification():
    state = DummyState()
    event_entry = {}
    classification, confidence = negotiation_close._classify_message("maybe")

    assert should_seek_clarification(confidence)
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "maybe",
        [("clarification", confidence)],
        confidence=confidence,
    )

    assert result.halt is True
    assert state.thread_state == "Awaiting Client Response"
    assert state.draft_messages[-1]["requires_approval"] is False


def test_clarification_message_contains_options():
    state = DummyState()
    event_entry = {}
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "sounds good but maybe negotiate",
        [("accept", 0.8), ("counter", 0.7)],
        confidence=0.3,
    )

    body = state.draft_messages[-1]["body"]
    assert "confirm the booking" in body
    assert "discuss pricing" in body
    assert result.halt is True


def test_high_confidence_skips_clarification_threshold():
    classification, confidence = negotiation_close._classify_message("Yes please proceed")
    assert classification == "accept"
    assert confidence >= 0.7
    assert not should_seek_clarification(confidence)


def test_room_selection_classifies_separately():
    classification, confidence = negotiation_close._classify_message("Room A looks good")
    assert classification == "room_selection"
    assert confidence >= 0.8


def test_very_low_confidence_defers_to_human():
    state = DummyState()
    event_entry = {}
    result = negotiation_close._ask_classification_clarification(
        state,
        event_entry,
        "unclear",
        [("clarification", 0.1)],
        confidence=0.1,
    )
    assert state.draft_messages[-1]["requires_approval"] is True
    assert result.halt is True


# ============================================================================
# Silent Ignore Tests (No Reply for Nonsense / Off-Topic)
# ============================================================================


class TestWorkflowSignalDetection:
    """Tests for has_workflow_signal() - detecting workflow-relevant content."""

    def test_date_patterns_are_workflow_signals(self):
        """Date mentions should be detected as workflow signals."""
        assert has_workflow_signal("let's do 15.12.2025")
        assert has_workflow_signal("December 20th works")
        assert has_workflow_signal("next Monday")
        assert has_workflow_signal("am Freitag")

    def test_booking_keywords_are_workflow_signals(self):
        """Booking-related words should be detected."""
        assert has_workflow_signal("I want to book a room")
        assert has_workflow_signal("please confirm the reservation")
        assert has_workflow_signal("can we reserve the space?")
        assert has_workflow_signal("ich möchte buchen")

    def test_acceptance_decline_are_workflow_signals(self):
        """Yes/no/ok responses should be detected."""
        assert has_workflow_signal("yes please")
        assert has_workflow_signal("no thanks")
        assert has_workflow_signal("ok, proceed")
        assert has_workflow_signal("ja, einverstanden")

    def test_pricing_capacity_are_workflow_signals(self):
        """Price and capacity mentions should be detected."""
        assert has_workflow_signal("what's the price?")
        assert has_workflow_signal("for 50 people")
        assert has_workflow_signal("CHF 500")
        assert has_workflow_signal("was kostet das?")

    def test_off_topic_has_no_workflow_signal(self):
        """Off-topic messages should NOT have workflow signals."""
        assert not has_workflow_signal("I love Darth Vader")
        assert not has_workflow_signal("The weather is nice today")
        assert not has_workflow_signal("My cat is sleeping")
        assert not has_workflow_signal("Random thoughts about life")
        assert not has_workflow_signal("hahahaha")

    def test_gibberish_has_no_workflow_signal(self):
        """Gibberish should NOT have workflow signals."""
        assert not has_workflow_signal("asdfghjkl")
        assert not has_workflow_signal("qwertyuiop")
        assert not has_workflow_signal("aaaaaaa")


class TestGibberishDetection:
    """Tests for is_gibberish() - detecting keyboard mashing etc."""

    def test_keyboard_mashing_is_gibberish(self):
        """Common keyboard patterns should be gibberish."""
        assert is_gibberish("asdfghjkl")
        assert is_gibberish("qwertyuiop")
        assert is_gibberish("zxcvbnm")

    def test_repeated_chars_is_gibberish(self):
        """Repeated single characters are gibberish."""
        assert is_gibberish("aaaaaaa")
        assert is_gibberish("hhhhhhh")

    def test_mostly_symbols_is_gibberish(self):
        """Mostly non-alphabetic content is gibberish."""
        assert is_gibberish("12345!@#$%")
        assert is_gibberish("...???!!!")

    def test_very_short_is_gibberish(self):
        """Very short messages (< 3 chars) are gibberish."""
        assert is_gibberish("x")
        assert is_gibberish("ab")

    def test_normal_words_not_gibberish(self):
        """Normal English/German words are not gibberish."""
        assert not is_gibberish("hello")
        assert not is_gibberish("I love pizza")
        assert not is_gibberish("Darth Vader is cool")


class TestSilentIgnore:
    """Tests for should_ignore_message() - the main no-reply logic."""

    def test_gibberish_is_ignored(self):
        """Keyboard mashing with low confidence is ignored."""
        assert should_ignore_message(0.15, "asdfghjkl")
        assert should_ignore_message(0.15, "qwertyuiop")
        assert should_ignore_message(0.15, "zxcvbnm")

    def test_very_short_nonsense_is_ignored(self):
        """Single characters with low confidence are ignored."""
        assert should_ignore_message(0.15, "x")
        assert should_ignore_message(0.15, "ab")

    def test_repeated_characters_are_ignored(self):
        """Repeated characters with low confidence are ignored."""
        assert should_ignore_message(0.15, "aaaaaaa")
        assert should_ignore_message(0.15, "hhhhhh")

    def test_off_topic_very_low_conf_is_ignored(self):
        """Off-topic content with very low confidence is ignored."""
        # Below 0.20 threshold for off-topic non-gibberish
        assert should_ignore_message(0.15, "I love Darth Vader")
        assert should_ignore_message(0.10, "The weather is nice")
        assert should_ignore_message(0.18, "My cat is sleeping")

    def test_workflow_message_never_ignored(self):
        """Messages with workflow signals are NEVER ignored, even with low conf."""
        # Has "room" + "book" workflow signals
        assert not should_ignore_message(0.10, "I want to book a room")
        # Has "yes" workflow signal
        assert not should_ignore_message(0.05, "yes")
        # Has "confirm" workflow signal
        assert not should_ignore_message(0.15, "hahahaha. ok confirm date")
        # Has "free" workflow signal
        assert not should_ignore_message(0.10, "what rooms are free?")

    def test_above_threshold_never_ignored(self):
        """Messages at or above CONFIDENCE_NONSENSE are never ignored."""
        assert not should_ignore_message(0.30, "random gibberish asdf")
        assert not should_ignore_message(0.35, "I love Darth Vader")
        assert not should_ignore_message(CONFIDENCE_NONSENSE, "anything")

    def test_mixed_content_with_workflow_signal_not_ignored(self):
        """Gibberish mixed with workflow signal is NOT ignored."""
        assert not should_ignore_message(0.15, "asdfasdf but yes I confirm")
        assert not should_ignore_message(0.15, "hahaha ok book the room")
        assert not should_ignore_message(0.10, "lol December 15 works")


class TestClassifyResponseAction:
    """Tests for classify_response_action() - the main decision function."""

    def test_returns_ignore_for_gibberish(self):
        """Gibberish with low confidence returns 'ignore'."""
        assert classify_response_action(0.15, "asdfghjkl") == "ignore"
        assert classify_response_action(0.10, "aaaaaaa") == "ignore"

    def test_returns_ignore_for_off_topic(self):
        """Off-topic with very low confidence returns 'ignore'."""
        assert classify_response_action(0.15, "I love Darth Vader") == "ignore"

    def test_returns_defer_for_unclear_workflow(self):
        """Low confidence workflow message returns 'defer'."""
        # Has "room" signal, so not ignored, but low conf = defer
        assert classify_response_action(0.25, "maybe the room") == "defer"

    def test_returns_clarify_for_medium_low(self):
        """Medium-low confidence (0.30-0.40) returns 'clarify'."""
        assert classify_response_action(0.35, "sounds interesting") == "clarify"

    def test_returns_proceed_for_high(self):
        """High confidence returns 'proceed'."""
        assert classify_response_action(0.70, "yes please confirm") == "proceed"
        assert classify_response_action(0.85, "book the room for December 15") == "proceed"


# ============================================================================
# check_nonsense_gate Tests (Step Handler Integration)
# ============================================================================

# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import (
    check_nonsense_gate,
    NONSENSE_IGNORE_THRESHOLD,
    NONSENSE_HIL_THRESHOLD,
)


class TestCheckNonsenseGate:
    """Tests for check_nonsense_gate() - the step handler decision function."""

    def test_workflow_signal_always_proceeds(self):
        """Messages with workflow signals always return 'proceed'."""
        # Even with very low confidence, workflow signals proceed
        assert check_nonsense_gate(0.05, "yes") == "proceed"
        assert check_nonsense_gate(0.10, "book a room") == "proceed"
        assert check_nonsense_gate(0.01, "confirm the date") == "proceed"
        assert check_nonsense_gate(0.15, "December 15") == "proceed"

    def test_gibberish_without_signal_is_ignored(self):
        """Gibberish without workflow signal is ignored."""
        assert check_nonsense_gate(0.10, "asdfghjkl") == "ignore"
        assert check_nonsense_gate(0.05, "qwertyuiop") == "ignore"
        assert check_nonsense_gate(0.10, "aaaaaaa") == "ignore"

    def test_off_topic_very_low_conf_is_ignored(self):
        """Off-topic without workflow signal at very low conf is ignored."""
        # Below NONSENSE_IGNORE_THRESHOLD (0.15)
        assert check_nonsense_gate(0.10, "I love Darth Vader") == "ignore"
        assert check_nonsense_gate(0.12, "The weather is nice") == "ignore"

    def test_off_topic_borderline_goes_to_hil(self):
        """Off-topic at borderline confidence goes to HIL."""
        # Between NONSENSE_IGNORE_THRESHOLD (0.15) and NONSENSE_HIL_THRESHOLD (0.25)
        assert check_nonsense_gate(0.18, "I love Darth Vader") == "hil"
        assert check_nonsense_gate(0.20, "My cat is sleeping") == "hil"
        assert check_nonsense_gate(0.22, "Random thoughts") == "hil"

    def test_above_hil_threshold_proceeds(self):
        """Messages above HIL threshold proceed even without signal."""
        # Above NONSENSE_HIL_THRESHOLD (0.25) - let step handler deal with it
        assert check_nonsense_gate(0.30, "I love Darth Vader") == "proceed"
        assert check_nonsense_gate(0.50, "unclear message") == "proceed"

    def test_mixed_content_with_signal_proceeds(self):
        """Gibberish mixed with workflow signal proceeds."""
        assert check_nonsense_gate(0.10, "asdf but yes I confirm") == "proceed"
        assert check_nonsense_gate(0.05, "hahaha book the room") == "proceed"

    def test_threshold_boundaries(self):
        """Test exact threshold boundaries."""
        # At exactly NONSENSE_IGNORE_THRESHOLD
        assert check_nonsense_gate(NONSENSE_IGNORE_THRESHOLD, "off topic") == "hil"
        # Just below
        assert check_nonsense_gate(NONSENSE_IGNORE_THRESHOLD - 0.01, "off topic") == "ignore"
        # At exactly NONSENSE_HIL_THRESHOLD
        assert check_nonsense_gate(NONSENSE_HIL_THRESHOLD, "off topic") == "proceed"
        # Just below
        assert check_nonsense_gate(NONSENSE_HIL_THRESHOLD - 0.01, "off topic") == "hil"
