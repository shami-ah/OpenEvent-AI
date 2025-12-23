"""
MODULE: backend/core/__init__.py
PURPOSE: Core infrastructure for error handling, logging, and fallback management.

This module provides foundational utilities used across the entire backend.
All error handling and fallback logic should use these standardized patterns.

CONTAINS:
    - errors.py     Standardized exception classes with mandatory context
    - fallback.py   Fallback message wrapping with diagnostics
    - logging.py    Structured logging configuration (future)

DESIGN PRINCIPLES:
    1. NEVER use bare `except: pass` - always log or re-raise
    2. All exceptions include context (source, step, thread_id)
    3. Errors feed into the debug trace system
    4. All fallback messages include diagnostic information

EXPORTS:
    Error Classes:
        - OpenEventError      Base exception with context
        - DetectionError      Detection-specific errors
        - WorkflowError       Workflow step errors
        - LLMError            LLM provider errors

    Error Handling:
        - safe_operation()    Context manager for safe exception handling

    Fallback:
        - FallbackContext     Structured fallback diagnostic data
        - wrap_fallback()     Wrap message with diagnostics
        - is_likely_fallback() Check if message looks like fallback

ENVIRONMENT:
    OE_FALLBACK_DIAGNOSTICS=true   # Show diagnostics (default in dev)
    OE_FALLBACK_DIAGNOSTICS=false  # Hide diagnostics (production)
"""

# Export from submodules
from backend.core.errors import (
    OpenEventError,
    DetectionError,
    WorkflowError,
    LLMError,
    FallbackTriggered,
    safe_operation,
    log_exception,
)
from backend.core.fallback import (
    FallbackContext,
    wrap_fallback,
    create_fallback_context,
    is_likely_fallback,
    SHOW_FALLBACK_DIAGNOSTICS,
    KNOWN_FALLBACK_PATTERNS,
    # Pre-built fallback factories
    llm_disabled_fallback,
    llm_exception_fallback,
    empty_results_fallback,
    low_confidence_fallback,
)

__all__ = [
    # Error classes
    "OpenEventError",
    "DetectionError",
    "WorkflowError",
    "LLMError",
    "FallbackTriggered",
    # Error handling utilities
    "safe_operation",
    "log_exception",
    # Fallback handling
    "FallbackContext",
    "wrap_fallback",
    "create_fallback_context",
    "is_likely_fallback",
    "SHOW_FALLBACK_DIAGNOSTICS",
    "KNOWN_FALLBACK_PATTERNS",
    # Fallback factories
    "llm_disabled_fallback",
    "llm_exception_fallback",
    "empty_results_fallback",
    "low_confidence_fallback",
]
