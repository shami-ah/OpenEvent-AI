"""
Unit tests for time validation against operating hours.

Tests the shared time_validation module used in Step 1 (intake),
Step 2 (confirmation), and detour flows.
"""

import pytest
from unittest.mock import patch


class TestValidateEventTimes:
    """Test cases for validate_event_times function."""

    def test_valid_times_within_hours(self):
        """Times within operating hours should be valid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("14:00", "18:00")

        assert result.is_valid is True
        assert result.issue is None
        assert result.friendly_message is None
        assert result.start_time == "14:00"
        assert result.end_time == "18:00"

    def test_start_too_early(self):
        """Start time before opening hour should be invalid."""
        from workflows.common.time_validation import validate_event_times

        # Default operating hours are 8:00-23:00
        result = validate_event_times("07:00", "12:00")

        assert result.is_valid is False
        assert result.issue == "start_too_early"
        assert "opens at 08:00" in result.friendly_message
        assert "07:00" in result.friendly_message

    def test_end_too_late(self):
        """End time after closing hour should be invalid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("19:00", "01:00")

        assert result.is_valid is False
        assert result.issue == "end_too_late"
        assert "closes at 23:00" in result.friendly_message
        assert "01:00" in result.friendly_message

    def test_end_too_late_past_midnight(self):
        """End time in early morning (past midnight) should be invalid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("20:00", "02:00")

        assert result.is_valid is False
        assert result.issue == "end_too_late"

    def test_end_exactly_at_closing_with_minutes(self):
        """End time with minutes past closing hour should be invalid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("18:00", "23:30")

        assert result.is_valid is False
        assert result.issue == "end_too_late"

    def test_both_invalid(self):
        """Both start too early and end too late should report both issues."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("06:00", "02:00")

        assert result.is_valid is False
        assert result.issue == "start_too_early_and_end_too_late"
        assert "fall outside" in result.friendly_message
        assert "06:00" in result.friendly_message
        assert "02:00" in result.friendly_message

    def test_no_times_provided(self):
        """No times provided should be valid (times are optional)."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times(None, None)

        assert result.is_valid is True
        assert result.issue is None

    def test_only_start_time_valid(self):
        """Only start time provided (valid) should be valid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("14:00", None)

        assert result.is_valid is True

    def test_only_start_time_invalid(self):
        """Only start time provided (too early) should be invalid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("06:00", None)

        assert result.is_valid is False
        assert result.issue == "start_too_early"

    def test_exact_opening_boundary(self):
        """Start time exactly at opening should be valid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("08:00", "12:00")

        assert result.is_valid is True

    def test_exact_closing_boundary(self):
        """End time exactly at closing (no minutes) should be valid."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("18:00", "23:00")

        assert result.is_valid is True

    def test_site_visit_bypass(self):
        """Site visit times should bypass validation."""
        from workflows.common.time_validation import validate_event_times

        # Even with "invalid" times, site visit should pass
        result = validate_event_times("06:00", "02:00", is_site_visit=True)

        assert result.is_valid is True
        assert result.issue is None

    def test_time_formats(self):
        """Various time formats should be parsed correctly."""
        from workflows.common.time_validation import validate_event_times

        # Simple hour format
        result1 = validate_event_times("14", "18")
        assert result1.is_valid is True

        # With colon
        result2 = validate_event_times("14:00", "18:00")
        assert result2.is_valid is True

        # With period (EU format)
        result3 = validate_event_times("14.00", "18.00")
        assert result3.is_valid is True

    @patch("workflows.common.time_validation.get_operating_hours")
    def test_custom_operating_hours(self, mock_hours):
        """Test with custom operating hours configuration."""
        from workflows.common.time_validation import validate_event_times

        # Custom hours: 9:00 - 22:00
        mock_hours.return_value = (9, 22)

        # 08:00 is now too early (before 9:00)
        result = validate_event_times("08:00", "12:00")
        assert result.is_valid is False
        assert result.issue == "start_too_early"
        assert "09:00" in result.friendly_message


class TestTimeValidationResult:
    """Test the TimeValidationResult dataclass."""

    def test_valid_result_defaults(self):
        """Valid result should have None for issue and message."""
        from workflows.common.time_validation import TimeValidationResult

        result = TimeValidationResult(is_valid=True)

        assert result.is_valid is True
        assert result.issue is None
        assert result.friendly_message is None
        assert result.start_time is None
        assert result.end_time is None

    def test_invalid_result_with_details(self):
        """Invalid result should have issue and message."""
        from workflows.common.time_validation import TimeValidationResult

        result = TimeValidationResult(
            is_valid=False,
            start_time="07:00",
            end_time="12:00",
            issue="start_too_early",
            friendly_message="Test message",
        )

        assert result.is_valid is False
        assert result.start_time == "07:00"
        assert result.end_time == "12:00"
        assert result.issue == "start_too_early"
        assert result.friendly_message == "Test message"


class TestFriendlyMessages:
    """Test the user-friendly warning messages."""

    def test_start_early_message(self):
        """Early start message should suggest adjustment."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("05:00", "10:00")

        assert "opens at" in result.friendly_message.lower()
        assert "adjust" in result.friendly_message.lower() or "later" in result.friendly_message.lower()

    def test_end_late_message(self):
        """Late end message should suggest adjustment."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("20:00", "01:00")

        assert "closes at" in result.friendly_message.lower()
        assert "adjust" in result.friendly_message.lower()

    def test_both_invalid_message(self):
        """Both invalid message should mention both times."""
        from workflows.common.time_validation import validate_event_times

        result = validate_event_times("05:00", "01:00")

        assert "05:00" in result.friendly_message
        assert "01:00" in result.friendly_message
        assert "operating hours" in result.friendly_message.lower() or "operates" in result.friendly_message.lower()
