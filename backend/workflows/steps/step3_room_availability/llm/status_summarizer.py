from __future__ import annotations

from typing import Dict, List

__workflow_role__ = "llm"


def summarize_room_statuses(statuses: List[Dict[str, str]]) -> str:
    """[LLM] Produce a concise textual summary from room status data."""

    fragments = []
    for entry in statuses:
        for room, status in entry.items():
            fragments.append(f"{room}: {status}")
    joined = "; ".join(fragments) if fragments else "No rooms configured."
    return f"Room availability summary — {joined}."
