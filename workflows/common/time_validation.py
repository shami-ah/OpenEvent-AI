"""
Shared time validation against operating hours (LLM-first).

This module validates event times against venue operating hours.
It's called from multiple integration points for defense-in-depth:
- Step 1: Initial intake validation
- Step 2: When times are finalized in confirmation flow
- Detours: When times change during detour flows

IMPORTANT: Times should come from unified_detection (LLM-extracted),
NOT re-parsed from message body text. This follows the LLM-First Rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from services.availability import parse_time_label
from workflows.io.config_store import get_operating_hours

logger = logging.getLogger(__name__)


@dataclass
class TimeValidationResult:
    """Result of time validation against operating hours."""

    is_valid: bool
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    issue: Optional[str] = None  # "start_too_early", "end_too_late", "start_too_early_and_end_too_late"
    friendly_message: Optional[str] = None


def validate_event_times(
    start_time: Optional[str],
    end_time: Optional[str],
    is_site_visit: bool = False,
) -> TimeValidationResult:
    """
    Validate times against venue operating hours.

    IMPORTANT: Times should come from unified_detection (LLM-extracted),
    NOT re-parsed from message body text. This follows the LLM-First Rule.

    Args:
        start_time: Start time string (e.g., "19:00", "7pm")
        end_time: End time string (e.g., "01:00", "1am")
        is_site_visit: If True, skip validation (site visit times are not
                      subject to event operating hours constraints)

    Returns:
        TimeValidationResult with is_valid=True if times are within operating hours,
        or is_valid=False with issue and friendly_message if outside hours.

    Examples:
        >>> validate_event_times("14:00", "18:00")
        TimeValidationResult(is_valid=True, ...)

        >>> validate_event_times("07:00", "12:00")
        TimeValidationResult(is_valid=False, issue="start_too_early", ...)

        >>> validate_event_times("19:00", "01:00")
        TimeValidationResult(is_valid=False, issue="end_too_late", ...)
    """
    # Guard: Site visit times are NOT subject to event operating hours
    if is_site_visit:
        logger.debug("[TIME_VALIDATION] Skipping validation - is_site_visit=True")
        return TimeValidationResult(is_valid=True, start_time=start_time, end_time=end_time)

    # No times provided - not an error (times are optional in early workflow)
    if not start_time and not end_time:
        return TimeValidationResult(is_valid=True)

    # Get operating hours from config (default 8:00-23:00)
    op_start, op_end = get_operating_hours()

    # Parse times using existing availability module
    start_parsed = parse_time_label(start_time) if start_time else None
    end_parsed = parse_time_label(end_time) if end_time else None

    issues = []

    # Check start time against opening hour
    if start_parsed and start_parsed.hour < op_start:
        issues.append("start_too_early")
        logger.debug(
            "[TIME_VALIDATION] Start time %s (hour=%d) is before opening hour %d",
            start_time, start_parsed.hour, op_start
        )

    # Check end time against closing hour
    # Handle midnight crossing (e.g., "1am" = past closing for same-day event)
    if end_parsed:
        # Times between midnight and opening (e.g., 1am-7am) are past closing
        if 0 < end_parsed.hour < op_start:
            issues.append("end_too_late")
            logger.debug(
                "[TIME_VALIDATION] End time %s (hour=%d) crosses midnight - past closing",
                end_time, end_parsed.hour
            )
        # Times after closing hour
        elif end_parsed.hour > op_end:
            issues.append("end_too_late")
            logger.debug(
                "[TIME_VALIDATION] End time %s (hour=%d) is after closing hour %d",
                end_time, end_parsed.hour, op_end
            )
        # Exactly at closing hour with minutes (e.g., 23:30)
        elif end_parsed.hour == op_end and end_parsed.minute > 0:
            issues.append("end_too_late")
            logger.debug(
                "[TIME_VALIDATION] End time %s extends past closing %d:00",
                end_time, op_end
            )

    # All checks passed
    if not issues:
        return TimeValidationResult(
            is_valid=True,
            start_time=start_time,
            end_time=end_time,
        )

    # Build result with issue and friendly message
    issue_str = "_and_".join(issues)
    friendly_msg = _build_friendly_message(start_time, end_time, op_start, op_end, issues)

    logger.info(
        "[TIME_VALIDATION] Times outside hours: start=%s, end=%s, issue=%s",
        start_time, end_time, issue_str
    )

    return TimeValidationResult(
        is_valid=False,
        start_time=start_time,
        end_time=end_time,
        issue=issue_str,
        friendly_message=friendly_msg,
    )


def _build_friendly_message(
    start: Optional[str],
    end: Optional[str],
    op_start: int,
    op_end: int,
    issues: list,
) -> str:
    """Build user-friendly warning message about operating hours."""
    hours_str = f"{op_start:02d}:00 to {op_end:02d}:00"

    if "start_too_early" in issues and "end_too_late" in issues:
        return (
            f"Please note: Our venue operates {hours_str}. "
            f"The requested times ({start} to {end}) fall outside these hours. "
            f"We'd be happy to help you find a suitable time window within our operating hours."
        )
    elif "start_too_early" in issues:
        return (
            f"Please note: Our venue opens at {op_start:02d}:00. "
            f"The requested start time ({start}) is earlier than our opening hours. "
            f"Would you like to adjust to a later start time?"
        )
    else:  # end_too_late
        return (
            f"Please note: Our venue closes at {op_end:02d}:00. "
            f"The requested end time ({end}) extends past our closing hours. "
            f"Would you like to adjust the event timing?"
        )
