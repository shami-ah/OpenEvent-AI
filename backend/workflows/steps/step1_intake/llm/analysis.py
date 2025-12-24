"""
DEPRECATED: Import from intent_classifier.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .intent_classifier import classify_intent, extract_user_information, sanitize_user_info

__all__ = ["classify_intent", "extract_user_information", "sanitize_user_info"]
