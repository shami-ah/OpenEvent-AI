"""Shim module re-exporting domain models for compatibility."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

from backend.domain.models import ConversationState, EventInformation, EventStatus, RoomStatus

__all__ = ["ConversationState", "EventInformation", "EventStatus", "RoomStatus"]
