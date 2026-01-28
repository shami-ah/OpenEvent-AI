"""
MODULE: activity/transformer.py
PURPOSE: Transform TraceEvent objects into Activity objects for UI display.

Provides:
- Kind-to-activity mapping with icons and titles
- Granularity filtering (manager-friendly vs detailed for devs)
- Local timezone timestamps
- Human-readable detail text generation

DESIGN NOTES:
- "high" granularity = manager-friendly, non-technical
- "detailed" granularity = developer debugging (hidden by default)
- Timestamps are in LOCAL timezone for manager convenience
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from debug.trace import BUS, TraceKind
from .types import Activity, Granularity


# Map TraceEvent kinds to activity display properties
# Format: {kind: (granularity, icon, title_template)}
# NOTE: "high" = manager-visible, "detailed" = dev-only (hidden from managers)
KIND_TO_ACTIVITY: Dict[TraceKind, tuple[Granularity, str, str]] = {
    # Manager-visible events (high)
    "STEP_ENTER": ("high", "🔄", "Processing {step}"),
    "DRAFT_SEND": ("high", "📤", "Response Prepared"),
    "GATE_FAIL": ("high", "⏳", "Waiting for {detail}"),
    "DETOUR": ("high", "🔀", "Change Requested"),

    # Dev-only events (detailed) - hidden from managers
    "STEP_EXIT": ("detailed", "✓", "Completed {step}"),
    "GATE_PASS": ("detailed", "✓", "Passed: {detail}"),
    "DB_READ": ("detailed", "📖", "Read: {detail}"),
    "DB_WRITE": ("detailed", "💾", "Saved: {detail}"),
    "ENTITY_CAPTURE": ("detailed", "📝", "Captured: {subject}"),
    "ENTITY_SUPERSEDED": ("detailed", "🔄", "Updated: {subject}"),
    "QA_ENTER": ("detailed", "💬", "Processing Question"),
    "QA_EXIT": ("detailed", "💬", "Answered Question"),
    "GENERAL_QA": ("detailed", "💬", "Q&A Response"),
    "STATE_SNAPSHOT": ("detailed", "📊", "State Updated"),
    "AGENT_PROMPT_IN": ("detailed", "🤖", "AI Processing"),
    "AGENT_PROMPT_OUT": ("detailed", "🤖", "AI Response Ready"),
}

# High-level semantic events (detected from trace data patterns)
# These are the MAIN manager-visible milestones - clear business language
SEMANTIC_PATTERNS = {
    # Step-based patterns - business milestones
    "step_1": ("high", "📧", "New Inquiry Received"),
    "step_2": ("high", "📅", "Date Confirmed"),
    "step_3": ("high", "🏢", "Checking Room Availability"),
    "step_4": ("high", "📄", "Offer Prepared"),
    "step_5": ("high", "💬", "Negotiation"),
    "step_6": ("high", "💳", "Payment Processing"),
    "step_7": ("high", "✅", "Finalizing Booking"),

    # Event-based patterns - business actions
    "date_confirmed": ("high", "📅", "Date Confirmed"),
    "room_selected": ("high", "🏢", "Room Selected"),
    "room_avail": ("high", "🏢", "Rooms Available"),
    "offer_generated": ("high", "📄", "Offer Sent"),
    "offer_accepted": ("high", "✓", "Offer Accepted"),
    "deposit_captured": ("high", "💳", "Deposit Details Received"),
    "deposit_paid": ("high", "💰", "Deposit Paid"),
    "billing_captured": ("high", "📋", "Billing Info Received"),
    "client_created": ("high", "👤", "Client Registered"),
    "email_sent": ("high", "📤", "Email Sent"),
    "site_visit": ("high", "🏛️", "Site Visit"),
    "booking_confirmed": ("high", "✅", "Booking Confirmed"),
    "hil_waiting": ("high", "👀", "Awaiting Manager Review"),
    "hil_approved": ("high", "✓", "Manager Approved"),
}


def transform_trace_to_activity(
    trace: Dict[str, Any],
    granularity_filter: Granularity = "high",
) -> Optional[Activity]:
    """
    Transform a single trace event dict into an Activity.

    Args:
        trace: Dict from TraceBus.get() (TraceEvent as dict)
        granularity_filter: "high" returns only manager-friendly events,
                           "detailed" returns all events

    Returns:
        Activity if trace matches filter, None otherwise
    """
    kind: TraceKind = trace.get("kind", "STATE_SNAPSHOT")

    # Try semantic pattern detection first
    activity_props = _detect_semantic_pattern(trace)

    # Fall back to kind-based mapping
    if not activity_props:
        activity_props = KIND_TO_ACTIVITY.get(kind)

    if not activity_props:
        return None

    event_granularity, icon, title_template = activity_props

    # Filter by granularity
    # "detailed" filter shows everything
    # "high" filter only shows "high" granularity events
    if granularity_filter == "high" and event_granularity == "detailed":
        return None

    # Build title from template
    title = _format_title(title_template, trace)

    # Build detail text (manager-friendly)
    detail = _build_detail(trace)

    # Format timestamp in LOCAL timezone (manager preference)
    ts = trace.get("ts", 0)
    if isinstance(ts, (int, float)):
        local_dt = datetime.fromtimestamp(ts)
        # ISO format with timezone offset for frontend parsing
        timestamp = local_dt.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        timestamp = str(ts)

    # Generate unique ID
    row_id = trace.get("row_id", str(ts))
    activity_id = f"act_{row_id}"

    return Activity(
        id=activity_id,
        timestamp=timestamp,
        icon=icon,
        title=title,
        detail=detail,
        granularity=event_granularity,
    )


def _detect_semantic_pattern(trace: Dict[str, Any]) -> Optional[tuple[Granularity, str, str]]:
    """
    Detect high-level semantic events from trace data.

    Looks for patterns in:
    - step field (e.g., "Step2")
    - payload/data fields
    - summary field
    """
    # Check step field for step transitions
    step = trace.get("step") or trace.get("owner_step") or ""
    step_lower = str(step).lower().replace(" ", "_")

    for pattern_key, props in SEMANTIC_PATTERNS.items():
        if pattern_key in step_lower:
            return props

    # Check payload for semantic events
    payload = trace.get("payload") or trace.get("data") or {}
    if isinstance(payload, dict):
        action = payload.get("action", "").lower()
        for pattern_key, props in SEMANTIC_PATTERNS.items():
            if pattern_key in action:
                return props

    # Check summary for keywords
    summary = trace.get("summary") or ""
    summary_lower = str(summary).lower()
    for pattern_key, props in SEMANTIC_PATTERNS.items():
        if pattern_key.replace("_", " ") in summary_lower:
            return props

    return None


def _format_title(template: str, trace: Dict[str, Any]) -> str:
    """Format title template with trace data."""
    # Extract values for template
    step = trace.get("step") or trace.get("owner_step") or "workflow"
    detail = trace.get("details") or trace.get("detail") or ""
    subject = trace.get("subject") or ""

    # Clean up step name (e.g., "Step2_date_confirmation" -> "Date Confirmation")
    step_clean = _clean_step_name(step)

    # Handle detail dict
    if isinstance(detail, dict):
        detail = detail.get("label") or detail.get("fn") or str(detail)

    return template.format(
        step=step_clean,
        detail=detail,
        subject=subject,
    )


def _clean_step_name(step: str) -> str:
    """Convert step identifier to human-readable name."""
    if not step:
        return "Workflow"

    step_str = str(step)

    # Remove "Step" prefix and number
    if step_str.lower().startswith("step"):
        step_str = step_str[4:]  # Remove "Step"
        step_str = step_str.lstrip("0123456789_")  # Remove numbers and underscores

    # Convert underscores to spaces and title case
    step_str = step_str.replace("_", " ")
    return step_str.strip().title() or "Workflow"


def _build_detail(trace: Dict[str, Any]) -> str:
    """Build manager-friendly description text from trace data.

    Focuses on business-relevant info, avoids technical jargon.
    """
    parts = []

    # Use summary if available and it's business-relevant
    summary = trace.get("summary")
    if summary:
        summary_str = str(summary)
        # Skip technical summaries
        technical_keywords = ["gate", "hash", "db", "entity", "payload"]
        if not any(kw in summary_str.lower() for kw in technical_keywords):
            parts.append(summary_str)

    # Extract business-relevant info from payload
    payload = trace.get("payload") or trace.get("data") or {}
    if isinstance(payload, dict):
        # Look for user-friendly fields
        friendly_fields = {
            "room": "Room",
            "date": "Date",
            "amount": "Amount",
            "client_name": "Client",
            "event_date": "Event Date",
            "reason": None,  # Use value directly
        }
        for key, label in friendly_fields.items():
            if key in payload and payload[key]:
                value = payload[key]
                if label:
                    parts.append(f"{label}: {value}")
                else:
                    parts.append(str(value))
                break

    # If still empty, try subject
    if not parts:
        subject = trace.get("subject")
        if subject:
            parts.append(str(subject))

    return parts[0] if parts else ""


def get_activities_for_event(
    thread_id: str,
    granularity: Granularity = "high",
    limit: int = 50,
) -> List[Activity]:
    """
    Get all activities for an event from TraceBus.

    Args:
        thread_id: Event thread ID
        granularity: "high" for manager-friendly, "detailed" for all
        limit: Maximum activities to return

    Returns:
        List of Activity objects, most recent first
    """
    traces = BUS.get(thread_id)

    activities = []
    for trace in reversed(traces):  # Most recent first
        activity = transform_trace_to_activity(trace, granularity)
        if activity:
            activities.append(activity)
            if len(activities) >= limit:
                break

    return activities


def get_recent_activities(
    thread_id: str,
    granularity: Granularity = "high",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Get recent activities for embedding in API response.

    Returns list of dicts (not Activity objects) for JSON serialization.
    """
    activities = get_activities_for_event(thread_id, granularity, limit)
    return [
        {"icon": a.icon, "title": a.title, "granularity": a.granularity}
        for a in activities
    ]
