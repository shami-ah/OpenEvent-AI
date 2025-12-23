"""
Shared utility functions for the Q&A module.

CANONICAL LOCATION: backend/workflows/common/qna/utils.py
EXTRACTED FROM: backend/workflows/common/general_qna.py
"""

from datetime import datetime
from typing import Any, Iterable, List, Set


def _format_display_date(value: str) -> str:
    """Convert various date formats to DD.MM.YYYY display format."""
    token = value.strip()
    if not token:
        return token
    if "." in token and token.count(".") == 2:
        return token
    cleaned = token.replace("Z", "")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%d.%m.%Y")
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return token


def _extract_availability_lines(text: str) -> List[str]:
    """Extract availability-related lines from text."""
    lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:") or upper.startswith("NEXT STEP:"):
            continue
        if stripped.startswith("- "):
            continue
        if "available" in stripped.lower():
            lines.append(stripped)
    return lines


def _extract_info_lines(text: str) -> List[str]:
    """Extract info section lines from text."""
    capture = False
    info_lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:"):
            capture = True
            continue
        if upper.startswith("NEXT STEP:"):
            capture = False
            continue
        if capture and stripped.startswith("- "):
            info_lines.append(stripped)
    return info_lines


def _dedup_preserve_order(items: Iterable[Any]) -> List[str]:
    """Deduplicate items while preserving original order."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for raw in items:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


__all__ = [
    "_format_display_date",
    "_extract_availability_lines",
    "_extract_info_lines",
    "_dedup_preserve_order",
]
