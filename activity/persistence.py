"""
MODULE: activity/persistence.py
PURPOSE: Persist high-level activities to the event database.

Activities are stored in event_entry["activity_log"] for:
- Manager tracing of what happened at each step
- Post-restart access to activity history
- Audit trail of AI actions

GRANULARITY LEVELS:
- "high" (coarse): Main business milestones - what manager sees by default
- "detailed" (fine): More granular steps - for deeper investigation

DESIGN:
- Both granularity levels are persisted (frontend filters)
- Activities are appended in chronological order
- Max 50 activities per event (oldest trimmed)
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
import logging

logger = logging.getLogger(__name__)

MAX_ACTIVITIES_PER_EVENT = 50

Granularity = Literal["high", "detailed"]

# Activities that are "high" (coarse) granularity - main business milestones
COARSE_ACTIVITIES = {
    # CRM & Calendar
    "client_saved", "event_created",
    # Room Status (Lead → Option → Confirmed) - ALWAYS VISIBLE
    "status_lead", "status_option", "status_confirmed", "status_cancelled",
    # Date confirmation (main milestone!)
    "date_confirmed",
    # Detours / Event changes
    "date_changed", "room_changed", "participants_changed", "products_changed", "special_request",
    # Site visit
    "site_visit_booked", "site_visit_completed",
    # Offer & Pricing
    "offer_sent", "offer_accepted", "offer_rejected", "price_updated",
    # Deposit
    "deposit_required", "deposit_paid", "deposit_updated", "deposit_set", "billing_updated",
    # Verification Failures (important for manager!)
    "date_denied", "room_denied", "date_conflict", "room_conflict", "capacity_exceeded",
    # HIL (Manager Approvals - managers need to verify their decisions!)
    "hil_approved", "hil_rejected", "hil_modified", "product_sourced",
}


def log_activity(
    event_entry: Dict[str, Any],
    icon: str,
    title: str,
    detail: str = "",
    granularity: Granularity = "high",
) -> None:
    """
    Log an activity to the event record.

    Args:
        event_entry: Event dict from workflow database
        icon: Emoji icon
        title: Short action title
        detail: Optional longer description
        granularity: "high" for main milestones, "detailed" for finer steps

    Example:
        log_activity(event_entry, "📅", "Date Confirmed", "March 15, 2025", "high")
    """
    if not event_entry:
        return

    activity_log = event_entry.setdefault("activity_log", [])

    # Create activity record with local timestamp
    now = datetime.now()
    activity = {
        "id": f"act_{int(now.timestamp() * 1000)}",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "icon": icon,
        "title": title,
        "detail": detail,
        "granularity": granularity,
    }

    activity_log.append(activity)

    # Trim to max size (keep most recent)
    if len(activity_log) > MAX_ACTIVITIES_PER_EVENT:
        event_entry["activity_log"] = activity_log[-MAX_ACTIVITIES_PER_EVENT:]


def get_persisted_activities(
    event_entry: Optional[Dict[str, Any]],
    limit: int = 50,
    granularity: Granularity = "high",
) -> List[Dict[str, Any]]:
    """
    Get persisted activities from event database.

    Args:
        event_entry: Event dict from workflow database
        limit: Maximum activities to return
        granularity: "high" for main milestones only, "detailed" for all activities

    Returns:
        List of activity dicts, most recent first
    """
    if not event_entry:
        return []

    activity_log = event_entry.get("activity_log") or []

    # Filter by granularity
    # "detailed" shows everything, "high" shows only high-granularity activities
    if granularity == "high":
        filtered = [a for a in activity_log if a.get("granularity", "high") == "high"]
    else:
        filtered = activity_log

    # Return most recent first, limited
    return list(reversed(filtered[-limit:]))


# Pre-defined activity templates for common workflow events
# Format: (icon, title_template, detail_template)
#
# GRANULARITY GUIDE:
# - "high" (coarse): Main business milestones - what the manager needs to see
# - "detailed" (fine): More granular steps - for deeper investigation
#
# VOCABULARY: Aligned with OpenEvent UX terminology
# - Room status: Lead → Option → Confirmed
# - Payment: Deposit (not "payment")
# - Failures: "denied" with reason
#
WORKFLOW_ACTIVITIES = {
    # ═══════════════════════════════════════════════════════════════════
    # COARSE GRANULARITY - Main business milestones (always shown)
    # ═══════════════════════════════════════════════════════════════════

    # CRM & Calendar
    "client_saved": ("👤", "Client Saved to CRM", "{client_name}"),
    "event_created": ("📅", "Event Created", "Status: {status}"),

    # Room Status (Lead → Option → Confirmed) - ALWAYS VISIBLE
    "status_lead": ("🔵", "Room Status: Lead", "New inquiry"),
    "status_option": ("🟡", "Room Status: Option", "Tentatively reserved"),
    "status_confirmed": ("🟢", "Room Status: Confirmed", "Booking confirmed"),
    "status_cancelled": ("🔴", "Room Status: Cancelled", "{reason}"),

    # Detours / Event changes
    "date_changed": ("📅", "Date Changed", "{old_date} → {new_date}"),
    "room_changed": ("🏢", "Room Changed", "{old_room} → {new_room}"),
    "participants_changed": ("👥", "Participants Changed", "{old_count} → {new_count}"),
    "products_changed": ("📦", "Products Changed", "{details}"),
    "special_request": ("⭐", "Special Request", "{request}"),

    # Site visit
    "site_visit_booked": ("🏛️", "Site Visit Booked", "{date}"),
    "site_visit_completed": ("✓", "Site Visit Completed", ""),

    # Offer & Pricing
    "offer_sent": ("📄", "Offer Sent", "{amount}"),
    "offer_accepted": ("✓", "Offer Accepted", ""),
    "offer_rejected": ("✗", "Offer Rejected", "{reason}"),
    "price_updated": ("💰", "Price Updated", "{old_price} → {new_price}"),

    # Deposit (payment)
    "deposit_set": ("💳", "Deposit Configured", "{amount} due {due_date}"),
    "deposit_required": ("💳", "Deposit Required", "{amount}"),
    "deposit_paid": ("💰", "Deposit Paid", "{amount}"),
    "deposit_updated": ("💳", "Deposit Updated", "{old_amount} → {new_amount}"),
    "billing_updated": ("📋", "Billing Info Updated", ""),

    # HIL (Manager Approvals) - COARSE so managers see their own decisions
    "hil_approved": ("✓", "Manager Approved", "Step {step}: {task_type}"),
    "hil_rejected": ("✗", "Manager Rejected", "Step {step}: {reason}"),
    "hil_modified": ("✏️", "Manager Edited Response", "Step {step}"),
    "product_sourced": ("📦", "Product Sourced", "{products}"),

    # Verification Failures (COARSE - manager needs to see these!)
    "date_denied": ("❌", "Date Denied", "{date} - {reason}"),
    "room_denied": ("❌", "Room Denied", "{room} - {reason}"),
    "date_conflict": ("⚠️", "Date Conflict", "{date} - {details}"),
    "room_conflict": ("⚠️", "Room Conflict", "{room} not available"),
    "capacity_exceeded": ("⚠️", "Capacity Exceeded", "{room} max {max_capacity}, requested {requested}"),

    # ═══════════════════════════════════════════════════════════════════
    # FINE GRANULARITY - Manager investigation details
    # (Still business-relevant, just more granular than coarse)
    # ═══════════════════════════════════════════════════════════════════

    # Step transitions (workflow progress)
    "step_1_entered": ("📧", "Processing Inquiry", ""),
    "step_2_entered": ("📅", "Confirming Date", ""),
    "step_3_entered": ("🏢", "Checking Availability", ""),
    "step_4_entered": ("📄", "Preparing Offer", ""),
    "step_5_entered": ("💬", "Negotiation", ""),
    "step_6_entered": ("💳", "Deposit Processing", ""),
    "step_7_entered": ("✅", "Finalizing Booking", ""),

    # Date workflow details
    "date_confirmed": ("📅", "Date Confirmed", "{date}"),
    "dates_suggested": ("📅", "Dates Suggested", "{dates}"),
    "date_checked": ("📅", "Date Checked", "{date} - {result}"),

    # Room workflow details
    "rooms_checked": ("🏢", "Rooms Checked", "{count} available for {date}"),
    "room_selected": ("🏢", "Room Selected", "{room}"),
    "room_locked": ("🔒", "Room Reserved", "{room}"),
    "room_released": ("🔓", "Room Released", "{room}"),

    # User Preferences (captured in Step 1)
    "preference_event_type": ("🎉", "Event Type", "{event_type}"),
    "preference_date": ("📅", "Preferred Date", "{date}"),
    "preference_participants": ("👥", "Expected Guests", "{count}"),
    "preference_room": ("🏢", "Preferred Room", "{room}"),
    "preference_catering": ("🍽️", "Catering Preference", "{preference}"),
    "preference_setup": ("🪑", "Room Setup", "{setup}"),
    "preference_equipment": ("🎤", "Equipment Needed", "{equipment}"),
    "preference_timing": ("🕐", "Event Timing", "{start} - {end}"),
    "preference_budget": ("💶", "Budget Range", "{budget}"),
    "preference_notes": ("📝", "Additional Notes", "{notes}"),

    # Contact info captured
    "contact_name": ("👤", "Name", "{name}"),
    "contact_email": ("📧", "Email", "{email}"),
    "contact_phone": ("📞", "Phone", "{phone}"),
    "contact_company": ("🏢", "Company", "{company}"),
    "contact_address": ("📍", "Address", "{address}"),

    # Manager review workflow (waiting is detailed, decisions are coarse - see above)
    "hil_waiting": ("👀", "Awaiting Manager Review", "Step {step}"),

    # Communication
    "email_sent": ("📤", "Email Sent", "To: {recipient}"),
    "email_received": ("📥", "Email Received", "From: {sender}"),
    "message_sent": ("💬", "Message Sent", ""),
    "message_received": ("📥", "Client Message", ""),

    # Verification checks (detailed)
    "availability_checked": ("🔍", "Availability Checked", "{date} - {result}"),
    "capacity_checked": ("🔍", "Capacity Checked", "{room} - {result}"),
    "pricing_calculated": ("🔍", "Pricing Calculated", "{details}"),

    # Time validation (detailed)
    "time_outside_hours": ("🕐", "Time Outside Operating Hours", "{time} ({issue})"),
}


def log_workflow_activity(
    event_entry: Dict[str, Any],
    activity_key: str,
    **format_args,
) -> None:
    """
    Log a pre-defined workflow activity.

    Automatically determines granularity:
    - "high" for main business milestones (COARSE_ACTIVITIES)
    - "detailed" for finer workflow steps

    Args:
        event_entry: Event dict from workflow database
        activity_key: Key from WORKFLOW_ACTIVITIES
        **format_args: Values to format into title/detail templates

    Example:
        log_workflow_activity(event_entry, "date_changed", old_date="March 10", new_date="March 15")
    """
    template = WORKFLOW_ACTIVITIES.get(activity_key)
    if not template:
        logger.warning("Unknown activity key: %s", activity_key)
        return

    icon, title_template, detail_template = template

    try:
        title = title_template.format(**format_args)
    except KeyError:
        title = title_template

    try:
        detail = detail_template.format(**format_args)
    except KeyError:
        detail = detail_template

    # Determine granularity based on activity type
    granularity: Granularity = "high" if activity_key in COARSE_ACTIVITIES else "detailed"

    log_activity(event_entry, icon, title, detail, granularity)
