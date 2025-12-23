"""
Centralized Fallback Diagnostics

Provides structured diagnostic information for fallback messages,
making it easier to understand WHY a fallback was triggered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Environment variable to control diagnostic output
# Default: True for dev/staging, set OE_FALLBACK_DIAGNOSTICS=false in production
SHOW_FALLBACK_DIAGNOSTICS = os.getenv("OE_FALLBACK_DIAGNOSTICS", "true").lower() == "true"


@dataclass
class FallbackReason:
    """Captures diagnostic info for fallback messages."""

    source: str  # e.g., "qna_verbalizer", "extraction", "adapter"
    trigger: str  # e.g., "llm_disabled", "empty_payload", "exception"
    failed_conditions: List[str] = field(default_factory=list)  # What checks failed
    context: Dict[str, Any] = field(default_factory=dict)  # Relevant state info
    original_error: Optional[str] = None  # Exception message if applicable

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source": self.source,
            "trigger": self.trigger,
            "failed_conditions": self.failed_conditions,
            "context": self.context,
            "original_error": self.original_error,
        }


def format_fallback_diagnostic(reason: FallbackReason) -> str:
    """
    Format a fallback reason into a diagnostic string.

    Returns a human-readable diagnostic block that can be appended to messages.
    """
    lines = [
        "",
        "---",
        "[FALLBACK MESSAGE]",
        f"Source: {reason.source}",
        f"Trigger: {reason.trigger}",
    ]

    if reason.failed_conditions:
        lines.append(f"Failed checks: {', '.join(reason.failed_conditions)}")

    if reason.context:
        context_items = [f"{k}={v}" for k, v in reason.context.items() if v is not None]
        if context_items:
            lines.append(f"Context: {', '.join(context_items)}")

    if reason.original_error:
        lines.append(f"Error: {reason.original_error}")

    return "\n".join(lines)


def append_fallback_diagnostic(body: str, reason: FallbackReason) -> str:
    """
    Append fallback diagnostic info to a message body.

    Only appends if SHOW_FALLBACK_DIAGNOSTICS is True.
    """
    if not SHOW_FALLBACK_DIAGNOSTICS:
        return body

    diagnostic = format_fallback_diagnostic(reason)
    return body + diagnostic


def create_fallback_reason(
    source: str,
    trigger: str,
    *,
    failed_conditions: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
    original_error: Optional[str] = None,
) -> FallbackReason:
    """
    Factory function to create a FallbackReason with sensible defaults.

    Common sources:
    - "qna_verbalizer": Q&A verbalization fallback
    - "qna_extraction": Q&A extraction fallback
    - "intent_adapter": Intent classification fallback
    - "structured_qna": Structured Q&A body fallback
    - "llm_provider": LLM provider failure

    Common triggers:
    - "llm_disabled": OpenAI API key not available
    - "llm_exception": LLM call threw an exception
    - "empty_payload": No data returned from DB query
    - "empty_results": Q&A query returned no rooms/dates/products
    - "provider_unavailable": LLM provider not initialized
    - "invalid_response": LLM returned unparseable response
    """
    return FallbackReason(
        source=source,
        trigger=trigger,
        failed_conditions=failed_conditions or [],
        context=context or {},
        original_error=original_error,
    )


# Pre-defined common fallback reasons
def llm_disabled_reason(source: str) -> FallbackReason:
    """Create a fallback reason for when LLM is disabled."""
    return create_fallback_reason(
        source=source,
        trigger="llm_disabled",
        context={"api_key_present": False, "openai_available": False},
    )


def llm_exception_reason(source: str, error: Exception) -> FallbackReason:
    """Create a fallback reason for LLM exceptions."""
    return create_fallback_reason(
        source=source,
        trigger="llm_exception",
        original_error=str(error),
    )


def empty_results_reason(
    source: str,
    rooms_count: int = 0,
    dates_count: int = 0,
    products_count: int = 0,
) -> FallbackReason:
    """Create a fallback reason for empty query results."""
    return create_fallback_reason(
        source=source,
        trigger="empty_results",
        failed_conditions=["no_data_from_db_query"],
        context={
            "rooms_count": rooms_count,
            "dates_count": dates_count,
            "products_count": products_count,
        },
    )


__all__ = [
    "FallbackReason",
    "SHOW_FALLBACK_DIAGNOSTICS",
    "format_fallback_diagnostic",
    "append_fallback_diagnostic",
    "create_fallback_reason",
    "llm_disabled_reason",
    "llm_exception_reason",
    "empty_results_reason",
]
