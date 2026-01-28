"""
Unit tests for the Activity Logger module.

Tests:
- Progress bar calculation from current_step
- Activity transformation from trace events
- Activity persistence and granularity filtering
"""

import pytest
from activity import get_progress, STEP_TO_STAGE
from activity.types import Activity, Progress
from activity.transformer import transform_trace_to_activity
from activity.persistence import (
    log_activity,
    log_workflow_activity,
    get_persisted_activities,
    COARSE_ACTIVITIES,
)


class TestProgress:
    """Tests for progress bar calculation."""

    def test_step_1_returns_date_stage(self):
        """Step 1 (intake) maps to date stage at 0%."""
        event = {"current_step": 1}
        progress = get_progress(event)

        assert progress.current_stage == "date"
        assert progress.percentage == 0

    def test_step_2_returns_date_stage(self):
        """Step 2 (date confirmation) maps to date stage at 20%."""
        event = {"current_step": 2}
        progress = get_progress(event)

        assert progress.current_stage == "date"
        assert progress.percentage == 20

    def test_step_3_returns_room_stage(self):
        """Step 3 (room availability) maps to room stage at 40%."""
        event = {"current_step": 3}
        progress = get_progress(event)

        assert progress.current_stage == "room"
        assert progress.percentage == 40

    def test_step_4_returns_offer_stage(self):
        """Step 4 (offer) maps to offer stage at 60%."""
        event = {"current_step": 4}
        progress = get_progress(event)

        assert progress.current_stage == "offer"
        assert progress.percentage == 60

    def test_step_7_returns_confirmed_stage(self):
        """Step 7 (confirmation) maps to confirmed stage at 100%."""
        event = {"current_step": 7}
        progress = get_progress(event)

        assert progress.current_stage == "confirmed"
        assert progress.percentage == 100

    def test_null_event_returns_default(self):
        """None event returns default date stage at 0%."""
        progress = get_progress(None)

        assert progress.current_stage == "date"
        assert progress.percentage == 0

    def test_stages_ordered_correctly(self):
        """Progress stages are in correct order."""
        progress = get_progress({"current_step": 3})

        stage_ids = [s.id for s in progress.stages]
        assert stage_ids == ["date", "room", "offer", "deposit", "confirmed"]

    def test_current_stage_is_active(self):
        """Current stage has 'active' status."""
        progress = get_progress({"current_step": 3})

        room_stage = next(s for s in progress.stages if s.id == "room")
        assert room_stage.status == "active"

    def test_previous_stages_are_completed(self):
        """Stages before current are 'completed'."""
        progress = get_progress({"current_step": 4})

        date_stage = next(s for s in progress.stages if s.id == "date")
        room_stage = next(s for s in progress.stages if s.id == "room")
        assert date_stage.status == "completed"
        assert room_stage.status == "completed"

    def test_future_stages_are_pending(self):
        """Stages after current are 'pending'."""
        progress = get_progress({"current_step": 3})

        offer_stage = next(s for s in progress.stages if s.id == "offer")
        confirmed_stage = next(s for s in progress.stages if s.id == "confirmed")
        assert offer_stage.status == "pending"
        assert confirmed_stage.status == "pending"

    def test_to_dict_serialization(self):
        """Progress can be serialized to dict."""
        progress = get_progress({"current_step": 3})
        data = progress.to_dict()

        assert "current_stage" in data
        assert "stages" in data
        assert "percentage" in data
        assert isinstance(data["stages"], list)


class TestActivityTransformer:
    """Tests for trace event to activity transformation."""

    def test_high_granularity_filters_detailed(self):
        """High granularity filter excludes detailed events."""
        trace = {
            "kind": "DB_READ",  # This is detailed-only
            "ts": 1706450000,
            "row_id": "test_1",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is None

    def test_detailed_granularity_includes_all(self):
        """Detailed granularity includes all events."""
        trace = {
            "kind": "DB_READ",
            "ts": 1706450000,
            "row_id": "test_1",
            "details": "event_data",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="detailed")
        assert activity is not None
        assert activity.granularity == "detailed"

    def test_step_enter_is_high_granularity(self):
        """STEP_ENTER events are manager-visible (high)."""
        trace = {
            "kind": "STEP_ENTER",
            "ts": 1706450000,
            "row_id": "test_2",
            "step": "Step3_room_availability",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is not None
        assert activity.granularity == "high"

    def test_timestamp_is_local_timezone(self):
        """Timestamps are formatted in local timezone."""
        trace = {
            "kind": "STEP_ENTER",
            "ts": 1706450000,  # 2024-01-28 ~12:00 UTC
            "row_id": "test_3",
            "step": "Step2",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is not None
        # Should be ISO format without 'Z' (local time)
        assert "T" in activity.timestamp
        assert activity.timestamp.count(":") >= 2

    def test_semantic_patterns_override_kind(self):
        """Semantic patterns (like step_2) override kind-based mapping."""
        trace = {
            "kind": "STEP_ENTER",
            "ts": 1706450000,
            "row_id": "test_4",
            "step": "Step2_date_confirmation",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is not None
        assert "Date" in activity.title

    def test_activity_has_icon(self):
        """Activities have emoji icons."""
        trace = {
            "kind": "DRAFT_SEND",
            "ts": 1706450000,
            "row_id": "test_5",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is not None
        assert len(activity.icon) > 0

    def test_activity_id_format(self):
        """Activity IDs have expected format."""
        trace = {
            "kind": "STEP_ENTER",
            "ts": 1706450000,
            "row_id": "12345.0001",
            "step": "Step1",
        }

        activity = transform_trace_to_activity(trace, granularity_filter="high")
        assert activity is not None
        assert activity.id.startswith("act_")


class TestActivityPersistence:
    """Tests for activity persistence and granularity filtering."""

    def test_log_activity_creates_log(self):
        """log_activity creates activity_log in event."""
        event = {"event_id": "test"}
        log_activity(event, "📅", "Test Activity", "Details", "high")

        assert "activity_log" in event
        assert len(event["activity_log"]) == 1

    def test_log_activity_includes_granularity(self):
        """Logged activities include granularity field."""
        event = {"event_id": "test"}
        log_activity(event, "📅", "Test", "", "detailed")

        activity = event["activity_log"][0]
        assert activity["granularity"] == "detailed"

    def test_log_workflow_activity_coarse(self):
        """Workflow activities in COARSE_ACTIVITIES get high granularity."""
        event = {"event_id": "test"}
        log_workflow_activity(event, "offer_sent", amount="€500")

        activity = event["activity_log"][0]
        assert activity["granularity"] == "high"
        assert "€500" in activity["detail"]

    def test_log_workflow_activity_fine(self):
        """Workflow activities not in COARSE_ACTIVITIES get detailed granularity."""
        event = {"event_id": "test"}
        log_workflow_activity(event, "step_3_entered")

        activity = event["activity_log"][0]
        assert activity["granularity"] == "detailed"

    def test_get_persisted_high_filters_detailed(self):
        """High granularity filter excludes detailed activities."""
        event = {"event_id": "test"}
        log_activity(event, "📅", "High Activity", "", "high")
        log_activity(event, "🔧", "Detailed Activity", "", "detailed")

        high_only = get_persisted_activities(event, granularity="high")
        assert len(high_only) == 1
        assert high_only[0]["title"] == "High Activity"

    def test_get_persisted_detailed_includes_all(self):
        """Detailed granularity includes all activities."""
        event = {"event_id": "test"}
        log_activity(event, "📅", "High Activity", "", "high")
        log_activity(event, "🔧", "Detailed Activity", "", "detailed")

        all_activities = get_persisted_activities(event, granularity="detailed")
        assert len(all_activities) == 2

    def test_get_persisted_returns_most_recent_first(self):
        """Activities are returned most recent first."""
        event = {"event_id": "test"}
        log_activity(event, "1️⃣", "First", "", "high")
        log_activity(event, "2️⃣", "Second", "", "high")
        log_activity(event, "3️⃣", "Third", "", "high")

        activities = get_persisted_activities(event, granularity="high")
        assert activities[0]["title"] == "Third"
        assert activities[2]["title"] == "First"

    def test_timestamp_is_local_format(self):
        """Timestamps are in local ISO format."""
        event = {"event_id": "test"}
        log_activity(event, "📅", "Test", "", "high")

        timestamp = event["activity_log"][0]["timestamp"]
        # Format: YYYY-MM-DDTHH:MM:SS (no Z for UTC)
        assert "T" in timestamp
        assert timestamp.count(":") == 2
        assert "Z" not in timestamp

    def test_coarse_activities_defined(self):
        """COARSE_ACTIVITIES contains expected business milestones."""
        assert "offer_sent" in COARSE_ACTIVITIES
        assert "date_changed" in COARSE_ACTIVITIES
        assert "deposit_paid" in COARSE_ACTIVITIES
        assert "client_saved" in COARSE_ACTIVITIES
        # Step transitions should NOT be coarse
        assert "step_3_entered" not in COARSE_ACTIVITIES
