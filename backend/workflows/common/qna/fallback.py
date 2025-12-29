"""
Fallback body generation for Q&A responses.

CANONICAL LOCATION: backend/workflows/common/qna/fallback.py
EXTRACTED FROM: backend/workflows/common/general_qna.py
"""

from typing import Any, Dict, List

from backend.workflows.common.fallback_reason import (
    SHOW_FALLBACK_DIAGNOSTICS,
    empty_results_reason,
    format_fallback_diagnostic,
)
from .constants import CLIENT_AVAILABILITY_HEADER
from .utils import _format_display_date


def _structured_table_blocks(db_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build structured table blocks from database summary."""
    rooms = db_summary.get("rooms") or []
    if not rooms:
        return []

    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in rooms:
        name = str(entry.get("room_name") or entry.get("room_id") or "Room").strip()
        bucket = grouped.setdefault(
            name,
            {"dates": set(), "notes": set()},
        )
        date_label = entry.get("date")
        if date_label:
            bucket["dates"].add(_format_display_date(str(date_label)))
        status = entry.get("status")
        if status:
            bucket["notes"].add(f"Status: {status}")
        capacity = entry.get("capacity_max")
        if capacity:
            bucket["notes"].add(f"Capacity up to {capacity}")
        products = entry.get("products") or []
        if products:
            bucket["notes"].add(f"Products: {', '.join(products)}")

    rows: List[Dict[str, Any]] = []
    for name, payload in sorted(grouped.items(), key=lambda item: item[0].lower()):
        rows.append(
            {
                "Room": name,
                "Dates": ", ".join(sorted(payload["dates"])) if payload["dates"] else "-",
                "Notes": "; ".join(sorted(payload["notes"])) if payload["notes"] else "-",
            }
        )
    if not rows:
        return []
    return [
        {
            "type": "dates",
            "label": "Dates & Rooms",
            "rows": rows,
        }
    ]


def _fallback_structured_body(action_payload: Dict[str, Any]) -> str:
    """Generate a fallback structured body when LLM verbalization fails."""
    # Don't include header here - it's set in headers[] and joined by _format_draft_text
    lines = []
    summary = action_payload.get("db_summary") or {}
    rooms = summary.get("rooms") or []
    products = summary.get("products") or []
    dates = summary.get("dates") or []
    notes = summary.get("notes") or []

    if rooms:
        lines.append("")
        lines.append("Rooms:")
        for entry in rooms[:5]:
            name = entry.get("room_name") or entry.get("room_id")
            date_label = entry.get("date")
            capacity = entry.get("capacity_max")
            status = entry.get("status")
            descriptor = []
            if capacity:
                descriptor.append(f"up to {capacity} pax")
            if status:
                descriptor.append(status)
            if date_label:
                descriptor.append(_format_display_date(str(date_label)))
            suffix = f" ({', '.join(descriptor)})" if descriptor else ""
            lines.append(f"- {name}{suffix}")

    if dates:
        lines.append("")
        lines.append("Dates:")
        for entry in dates[:5]:
            date_label = entry.get("date")
            room_label = entry.get("room_name") or entry.get("room_id")
            status = entry.get("status")
            descriptor = " – ".join(filter(None, [room_label, status]))
            lines.append(f"- {_format_display_date(str(date_label))} {descriptor}".strip())

    if products:
        lines.append("")
        lines.append("Products:")
        for entry in products[:5]:
            name = entry.get("product")
            availability = "available" if entry.get("available_today") else "not available today"
            lines.append(f"- {name} ({availability})")

    if notes:
        lines.append("")
        for entry in notes[:3]:
            lines.append(f"- {entry}")

    body = "\n".join(lines).strip()

    # Add fallback diagnostic if no data was found
    rooms_count = len(rooms)
    dates_count = len(dates)
    products_count = len(products)

    if SHOW_FALLBACK_DIAGNOSTICS and rooms_count == 0 and dates_count == 0 and products_count == 0:
        reason = empty_results_reason(
            source="structured_qna_body",
            rooms_count=rooms_count,
            dates_count=dates_count,
            products_count=products_count,
        )
        # Add context about what query produced empty results
        effective = action_payload.get("effective") or {}
        reason.context["query_date"] = effective.get("date")
        reason.context["query_attendees"] = effective.get("attendees")
        reason.context["query_room"] = effective.get("room")
        body += format_fallback_diagnostic(reason)

    return body


__all__ = [
    "_structured_table_blocks",
    "_fallback_structured_body",
]
