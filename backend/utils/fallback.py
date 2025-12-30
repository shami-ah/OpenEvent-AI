"""
Fallback handling utilities for visible error reporting.

This module provides utilities to make fallbacks VISIBLE rather than silent.
When something fails, users and developers should know about it instead of
receiving responses that pretend everything worked.

Usage:
    from backend.utils.fallback import create_fallback_context, wrap_fallback

    try:
        result = do_something()
    except Exception as exc:
        ctx = create_fallback_context(
            source="api.routes.messages.confirm_date",
            trigger="persistence_failed",
            event_id=event_id,
            error=exc,
        )
        return wrap_fallback(
            "I logged your confirmation, but our booking system didn't save "
            "the update. I've escalated it for manual follow-up.",
            ctx,
        )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class FallbackContext:
    """Context information for a fallback event."""

    source: str  # e.g., "api.routes.messages.confirm_date"
    trigger: str  # e.g., "persistence_failed", "llm_unavailable"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    # Optional context
    event_id: Optional[str] = None
    thread_id: Optional[str] = None
    step: Optional[int] = None
    topic: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "source": self.source,
            "trigger": self.trigger,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "thread_id": self.thread_id,
            "step": self.step,
            "topic": self.topic,
            "error": self.error,
        }


def create_fallback_context(
    source: str,
    trigger: str,
    *,
    event_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    step: Optional[int] = None,
    topic: Optional[str] = None,
    error: Optional[Exception] = None,
) -> FallbackContext:
    """
    Create a fallback context for tracking and debugging.

    Args:
        source: The code location (e.g., "ux.verbalizer", "api.confirm_date")
        trigger: What caused the fallback (e.g., "llm_failed", "db_unavailable")
        event_id: Associated event ID if available
        thread_id: Associated thread/session ID if available
        step: Workflow step number if applicable
        topic: Message topic if applicable
        error: The exception that caused the fallback

    Returns:
        FallbackContext with all relevant information
    """
    return FallbackContext(
        source=source,
        trigger=trigger,
        event_id=event_id,
        thread_id=thread_id,
        step=step,
        topic=topic,
        error=str(error) if error else None,
    )


def wrap_fallback(
    user_message: str,
    context: FallbackContext,
    *,
    include_dev_info: bool = False,
) -> str:
    """
    Wrap a fallback message with optional developer context.

    In development/staging, can include diagnostic info.
    In production, provides a user-friendly message without debug noise.

    Args:
        user_message: The user-facing message explaining what happened
        context: FallbackContext with debugging information
        include_dev_info: Whether to include developer diagnostics

    Returns:
        Formatted message string
    """
    # Log the fallback for monitoring
    _log_fallback(context)

    # Check if we should include developer info
    show_diagnostics = include_dev_info or os.getenv("OE_FALLBACK_DIAGNOSTICS", "").lower() in ("1", "true", "yes")

    if show_diagnostics:
        dev_info = f"\n\n[DEV] Fallback: {context.source} | {context.trigger}"
        if context.error:
            dev_info += f" | Error: {context.error}"
        return user_message + dev_info

    return user_message


def _log_fallback(context: FallbackContext) -> None:
    """Log fallback event for monitoring and debugging."""
    print(
        f"[FALLBACK] source={context.source} trigger={context.trigger} "
        f"step={context.step} event_id={context.event_id}"
    )
    if context.error:
        print(f"  Error: {context.error}")


def format_fallback_notice(
    component: str,
    user_message: str,
) -> str:
    """
    Format a simple fallback notice for inline use.

    Args:
        component: The component that fell back (e.g., "Tone reviewer")
        user_message: The actual message content

    Returns:
        Formatted message with fallback notice
    """
    show_notice = os.getenv("OE_FALLBACK_DIAGNOSTICS", "").lower() in ("1", "true", "yes")

    if show_notice:
        return f"[{component} offline] {user_message}"

    return user_message


__all__ = [
    "FallbackContext",
    "create_fallback_context",
    "wrap_fallback",
    "format_fallback_notice",
]
