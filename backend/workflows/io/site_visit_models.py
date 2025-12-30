"""Site Visit Database Models.

TypedDicts for site visit database tables.

These models mirror the Supabase tables:
- site_visits: Individual site visit bookings
- site_visit_config: Manager configuration for site visit availability

IMPORTANT: Site visits are VENUE-WIDE (not room-specific).
- Client visits the whole venue/selection
- Manager configures available time slots
- Conflict rules:
  - Site visits CANNOT be booked on event days (hard block)
  - Events CAN be booked on site visit days (triggers manager notification)
"""
from __future__ import annotations

from typing import List, Literal, Optional, TypedDict


SiteVisitStatus = Literal[
    "proposed",     # Slots offered to client
    "date_pending", # Awaiting date selection
    "scheduled",    # Date confirmed
    "completed",    # Visit happened
    "cancelled",    # Cancelled by client/manager
    "no_show",      # Client didn't show up
]

ConflictResolution = Literal[
    "kept_both",       # Manager decided to handle both
    "cancelled_visit", # Site visit was cancelled
    "moved_visit",     # Site visit moved to different date
]

SiteVisitOutcome = Literal[
    "proceeded_to_booking",  # Client booked after visit
    "no_booking",            # Client didn't book
    "cancelled",             # Visit was cancelled
]


class SiteVisitRecord(TypedDict, total=False):
    """Database record for site_visits table.

    Represents a single site visit booking. Site visits are venue-wide,
    so there's no room_id field.

    Special Case Note:
    While site visits are venue-wide (no room_id), the associated event
    may have a specific room. The client visits the whole venue but
    their event booking might be for a specific room.
    """
    # Primary identifiers
    id: str                           # UUID
    team_id: str                      # UUID - which venue/team
    event_id: Optional[str]           # UUID - may be NULL if standalone visit
    client_id: str                    # UUID - who requested the visit

    # Scheduling (venue-wide, NO room!)
    scheduled_date: str               # ISO date (YYYY-MM-DD)
    scheduled_time: Optional[str]     # HH:MM format
    time_slot: Optional[str]          # "morning" | "afternoon" | "evening"
    duration_minutes: int             # Typically 60

    # Status tracking
    status: SiteVisitStatus

    # Conflict tracking (when event is booked on site visit day)
    has_event_conflict: bool          # Event was booked on this date
    conflict_resolved: bool           # Manager handled conflict
    conflict_resolution: Optional[ConflictResolution]

    # Workflow context
    initiated_at_step: Optional[int]  # Which step (2-7) triggered
    proposed_slots: Optional[List[str]]  # Array of offered time slots

    # Timestamps (ISO format)
    created_at: str                   # When record was created
    scheduled_at: Optional[str]       # When visit was confirmed
    completed_at: Optional[str]       # When visit actually happened
    cancelled_at: Optional[str]       # When visit was cancelled

    # Outcome
    notes: Optional[str]              # Manager/system notes
    outcome: Optional[SiteVisitOutcome]


class SiteVisitConfig(TypedDict, total=False):
    """Manager configuration for site visits.

    One record per team, controls site visit availability and rules.
    """
    id: str                           # UUID
    team_id: str                      # UUID - which venue/team (unique)

    # Availability settings
    enabled: bool                     # Site visits allowed at all?
    available_days: List[str]         # ["monday", "tuesday", "wednesday", "thursday", "friday"]
    available_slots: List[str]        # ["10:00", "14:00", "16:00"]
    default_duration_minutes: int     # Typically 60

    # Booking rules
    min_advance_days: int             # Must book at least N days ahead
    max_advance_days: int             # Can book up to N days ahead
    auto_cancel_on_conflict: bool     # Auto-cancel visit if event booked same day

    # Metadata
    updated_at: str                   # ISO timestamp
    updated_by: Optional[str]         # UUID of user who updated


# Default configuration for new teams
DEFAULT_SITE_VISIT_CONFIG: SiteVisitConfig = {
    "enabled": True,
    "available_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "available_slots": ["10:00", "14:00", "16:00"],
    "default_duration_minutes": 60,
    "min_advance_days": 2,
    "max_advance_days": 60,
    "auto_cancel_on_conflict": False,
}


__all__ = [
    "SiteVisitRecord",
    "SiteVisitConfig",
    "SiteVisitStatus",
    "ConflictResolution",
    "SiteVisitOutcome",
    "DEFAULT_SITE_VISIT_CONFIG",
]
