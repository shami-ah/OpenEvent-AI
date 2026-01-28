"""Room choice detection helper for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from workflows.io.database import load_rooms
from .normalization import normalize_room_token


import logging

logger = logging.getLogger(__name__)


def detect_room_choice(
    message_text: str,
    linked_event: Optional[Dict[str, Any]],
    unified_detection: Optional[Any] = None,
) -> Optional[str]:
    """Detect room selection in message text.

    Note: This function calls load_rooms() to get available rooms.
    Consider refactoring to accept rooms parameter in future.

    Args:
        message_text: The message text to analyze
        linked_event: The linked event entry
        unified_detection: Optional unified detection result from LLM

    Returns:
        Room name if detected, None otherwise.
    """
    if not message_text or not linked_event:
        return None

    # DEBUG: Log detection context
    is_acceptance = getattr(unified_detection, "is_acceptance", False) if unified_detection else False
    logger.debug("[ROOM_DETECT] unified_detection=%s, is_acceptance=%s, msg=%s...",
                 unified_detection is not None, is_acceptance, message_text[:50])

    # -------------------------------------------------------------------------
    # IDEMPOTENCY GUARD: If room is already locked, DON'T detect room choices.
    # A locked room means the client has already confirmed their room selection.
    # Re-mentioning the same room in an acceptance/confirmation message should
    # NOT trigger room choice detection - it's a NO-OP.
    # -------------------------------------------------------------------------
    locked_room = linked_event.get("locked_room_id")
    if locked_room:
        logger.debug("[ROOM_DETECT] IDEMPOTENCY_GUARD: Room already locked (%s), skipping room detection", locked_room)
        return None

    try:
        current_step = int(linked_event.get("current_step") or 0)
    except (TypeError, ValueError):
        current_step = 0
    print(f"[ROOM_DETECT_DEBUG] current_step={current_step}, message={message_text[:50] if message_text else None}")
    if current_step < 3:
        print(f"[ROOM_DETECT_DEBUG] BLOCKED: current_step={current_step} < 3")
        return None
    print(f"[ROOM_DETECT_DEBUG] PROCEEDING with detection")

    rooms = load_rooms()
    if not rooms:
        return None

    text = message_text.strip()
    if not text:
        return None
    lowered = text.lower()

    # -------------------------------------------------------------------------
    # FIX: Question guard - don't lock room if message is a question ABOUT the room
    # "Is Room A available?" should NOT lock Room A
    # BUT "Room B looks perfect. Do you offer catering?" SHOULD lock Room B
    # (the question is unrelated to the room selection)
    # -------------------------------------------------------------------------
    # Split into sentences (keep punctuation to detect questions)
    sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]?", lowered) if s.strip()]
    # Only block if the ENTIRE message is a question
    is_pure_question = len(sentences) == 1 and sentences[0].endswith("?")

    if is_pure_question:
        return None

    # Also check unified detection is_question signal.
    # Hybrid messages (statement + question) should still detect room from statement part.
    if unified_detection and getattr(unified_detection, "is_question", False):
        # If it's a single-sentence message, trust unified detection and skip locking.
        if len(sentences) == 1:
            return None
        # If all sentences are questions, skip locking.
        non_question_parts = [s for s in sentences if not s.endswith("?")]
        if not non_question_parts:
            return None

    # -------------------------------------------------------------------------
    # NOTE: The ACCEPTANCE_GUARD was removed because it's redundant and causes bugs.
    # - The IDEMPOTENCY_GUARD (line 51-54) already handles the case where room is locked.
    # - When room is NOT locked, is_acceptance=True for "Room B sounds perfect" is a
    #   valid room SELECTION, not an offer acceptance. Blocking it breaks the flow.
    # - "I accept this offer" with an already-locked room is handled by IDEMPOTENCY_GUARD.
    # -------------------------------------------------------------------------
    condensed = normalize_room_token(text)

    # direct match against known room labels (with word boundaries to avoid "room for" matching "Room F")
    for room in rooms:
        room_lower = room.lower()
        # Use word boundary regex to avoid "room for" matching "room f"
        room_pattern = rf"\b{re.escape(room_lower)}\b"
        if re.search(room_pattern, lowered):
            logger.info("[ROOM_DETECT] MATCHED room=%s in message (pattern=%s)", room, room_pattern)
            return room
        if normalize_room_token(room) and normalize_room_token(room) == condensed:
            return room

    # pattern like "room a" or "room-a"
    match = re.search(r"\broom\s*([a-z0-9]+)\b", lowered)
    if match:
        token = match.group(1)
        token_norm = normalize_room_token(token)
        for room in rooms:
            room_tokens = room.split()
            if room_tokens:
                last_token = normalize_room_token(room_tokens[-1])
                if token_norm and token_norm == last_token:
                    return room

    # single token equals last token of room name (e.g., "A")
    if len(lowered.split()) == 1:
        token_norm = condensed
        if token_norm:
            for room in rooms:
                last_token = normalize_room_token(room.split()[-1])
                if token_norm == last_token:
                    return room

    return None
