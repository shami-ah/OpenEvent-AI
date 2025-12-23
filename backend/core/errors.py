"""
MODULE: backend/core/errors.py
PURPOSE: Standardized error handling for OpenEvent.

RULES:
    1. NEVER use bare `except: pass` - always log or re-raise
    2. All exceptions include context (source, step, thread_id, function)
    3. Errors feed into the debug trace system
    4. Use safe_operation() context manager for graceful degradation

DEPENDS ON:
    - backend/debug/trace.py  # For emitting error events (optional)

USED BY:
    - All backend modules that need error handling

MIGRATION:
    Replace all `except: pass` blocks with:

    BEFORE:
        try:
            do_something()
        except:
            pass

    AFTER:
        with safe_operation("module.function", fallback_value=None):
            do_something()

    Or for explicit handling:

        try:
            do_something()
        except SomeError as e:
            logger.warning("[module.function] Operation failed: %s", e)
            # Handle or re-raise
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Optional, Type

logger = logging.getLogger(__name__)


@dataclass
class ErrorContext:
    """Context information attached to all OpenEvent errors."""

    source: str  # e.g., "detection.intent.classifier"
    step: Optional[int] = None
    thread_id: Optional[str] = None
    event_id: Optional[str] = None
    function: Optional[str] = None
    additional: dict = field(default_factory=dict)


class OpenEventError(Exception):
    """
    Base exception with mandatory context.

    All OpenEvent errors should inherit from this class and provide
    meaningful context to aid debugging.

    Usage:
        raise OpenEventError(
            "Failed to classify intent",
            source="detection.intent.classifier",
            step=2,
            thread_id="abc123"
        )
    """

    def __init__(
        self,
        message: str,
        *,
        source: str,
        step: Optional[int] = None,
        thread_id: Optional[str] = None,
        event_id: Optional[str] = None,
        original_error: Optional[Exception] = None,
        **kwargs: Any,
    ):
        self.context = ErrorContext(
            source=source,
            step=step,
            thread_id=thread_id,
            event_id=event_id,
            additional=kwargs,
        )
        self.original_error = original_error
        self.message = message

        # Format: [source] message
        formatted = f"[{source}] {message}"
        if original_error:
            formatted += f" (caused by: {type(original_error).__name__}: {original_error})"

        super().__init__(formatted)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "message": self.message,
            "source": self.context.source,
            "step": self.context.step,
            "thread_id": self.context.thread_id,
            "event_id": self.context.event_id,
            "original_error": str(self.original_error) if self.original_error else None,
            "additional": self.context.additional,
        }


class DetectionError(OpenEventError):
    """
    Detection-specific errors.

    Raised when intent classification, response detection, or other
    detection logic fails.

    Usage:
        raise DetectionError(
            "Low confidence classification",
            source="detection.intent.classifier",
            confidence=0.12,
            message_preview=text[:50]
        )
    """

    pass


class WorkflowError(OpenEventError):
    """
    Workflow step errors.

    Raised when a workflow step fails to process correctly.

    Usage:
        raise WorkflowError(
            "Gate validation failed",
            source="workflows.step2.date_confirmation",
            step=2,
            gate="date_present"
        )
    """

    pass


class LLMError(OpenEventError):
    """
    LLM provider errors.

    Raised when LLM calls fail (timeout, invalid response, etc.)

    Usage:
        raise LLMError(
            "OpenAI API timeout",
            source="llm.providers.openai",
            model="gpt-4",
            timeout_ms=30000
        )
    """

    pass


class FallbackTriggered(OpenEventError):
    """
    Indicates a fallback was triggered (not necessarily an error).

    This is a soft error that indicates the system fell back to
    a default response. Used for tracking/monitoring.

    Usage:
        raise FallbackTriggered(
            "No Q&A results found",
            source="qna.verbalizer",
            fallback_type="empty_results"
        )
    """

    pass


@contextmanager
def safe_operation(
    source: str,
    *,
    fallback_value: Any = None,
    log_level: str = "warning",
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    reraise: bool = False,
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
) -> Generator[None, None, None]:
    """
    Context manager for safe exception handling with logging.

    Catches exceptions, logs them with context, and optionally returns
    a fallback value instead of propagating the error.

    Args:
        source: Module/function identifier (e.g., "detection.intent.classifier")
        fallback_value: Value to return if exception occurs (via exception attribute)
        log_level: Logging level ("debug", "info", "warning", "error")
        exceptions: Tuple of exception types to catch
        reraise: If True, re-raise after logging
        step: Current workflow step for context
        thread_id: Thread ID for context

    Usage:
        # Simple case - suppress and return None
        with safe_operation("detection.intent"):
            result = classify_intent(msg)

        # With fallback value
        try:
            with safe_operation("detection.intent", fallback_value="unknown"):
                result = classify_intent(msg)
        except SafeOperationFallback as e:
            result = e.fallback_value

        # Logging only, still raises
        with safe_operation("detection.intent", reraise=True):
            result = classify_intent(msg)
    """
    log_func = getattr(logger, log_level, logger.warning)

    try:
        yield
    except exceptions as e:
        context_str = f"[{source}]"
        if step is not None:
            context_str += f" step={step}"
        if thread_id:
            context_str += f" thread={thread_id[:8]}"

        log_func(
            "%s Operation failed: %s: %s",
            context_str,
            type(e).__name__,
            str(e),
        )

        if reraise:
            raise

        # Store fallback value for caller to retrieve if needed
        # This is a pattern for when the caller needs to know a fallback occurred


def log_exception(
    source: str,
    error: Exception,
    *,
    level: str = "warning",
    step: Optional[int] = None,
    thread_id: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Log an exception with standardized formatting.

    Use this when you want to log an error but handle it yourself.

    Args:
        source: Module/function identifier
        error: The exception that occurred
        level: Logging level
        step: Current workflow step
        thread_id: Thread ID
        **extra: Additional context to log
    """
    log_func = getattr(logger, level, logger.warning)

    context_parts = [f"[{source}]"]
    if step is not None:
        context_parts.append(f"step={step}")
    if thread_id:
        context_parts.append(f"thread={thread_id[:8]}")

    context_str = " ".join(context_parts)
    extra_str = " ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""

    log_func(
        "%s %s: %s %s",
        context_str,
        type(error).__name__,
        str(error),
        extra_str,
    )
