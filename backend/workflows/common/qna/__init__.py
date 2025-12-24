"""
Q&A module for general question answering in the workflow.

CANONICAL LOCATION: backend/workflows/common/qna/

This module provides utilities extracted from general_qna.py for better organization.
The main entry points remain in general_qna.py for now.

Submodules:
    constants.py - Shared constants
    utils.py     - Utility functions
    fallback.py  - Fallback body generation

Usage:
    # Import constants
    from backend.workflows.common.qna.constants import CLIENT_AVAILABILITY_HEADER

    # Import utilities
    from backend.workflows.common.qna.utils import _format_display_date

    # Import fallback functions
    from backend.workflows.common.qna.fallback import _fallback_structured_body
"""

# Re-export from submodules for convenience
from .constants import (
    CLIENT_AVAILABILITY_HEADER,
    ROOM_IDS,
    LAYOUT_KEYWORDS,
    FEATURE_KEYWORDS,
    CATERING_KEYWORDS,
    STATUS_PRIORITY,
    MONTH_INDEX_TO_NAME,
    _MENU_ONLY_SUBTYPES,
    _ROOM_MENU_SUBTYPES,
    _DATE_PARSE_FORMATS,
    DEFAULT_NEXT_STEP_LINE,
    DEFAULT_ROOM_NEXT_STEP_LINE,
)

from .utils import (
    _format_display_date,
    _extract_availability_lines,
    _extract_info_lines,
    _dedup_preserve_order,
)

from .fallback import (
    _fallback_structured_body,
    _structured_table_blocks,
)

__all__ = [
    # Constants
    "CLIENT_AVAILABILITY_HEADER",
    "ROOM_IDS",
    "LAYOUT_KEYWORDS",
    "FEATURE_KEYWORDS",
    "CATERING_KEYWORDS",
    "STATUS_PRIORITY",
    "MONTH_INDEX_TO_NAME",
    "_MENU_ONLY_SUBTYPES",
    "_ROOM_MENU_SUBTYPES",
    "_DATE_PARSE_FORMATS",
    "DEFAULT_NEXT_STEP_LINE",
    "DEFAULT_ROOM_NEXT_STEP_LINE",
    # Utilities
    "_format_display_date",
    "_extract_availability_lines",
    "_extract_info_lines",
    "_dedup_preserve_order",
    # Fallback
    "_fallback_structured_body",
    "_structured_table_blocks",
]
