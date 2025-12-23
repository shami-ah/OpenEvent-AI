from __future__ import annotations

"""
DEPRECATED: This module has been migrated to backend/detection/intent/confidence.py

Please update your imports:
    OLD: from backend.workflows.common.confidence import ...
    NEW: from backend.detection.intent.confidence import ...

This file will be removed in a future release.
---

Confidence thresholds and utilities for detection confidence gating.

Threshold Hierarchy (from high to low):
- CONFIDENCE_HIGH (0.85): Auto-proceed with high confidence
- CONFIDENCE_MEDIUM (0.65): Proceed with some caution
- CONFIDENCE_LOW (0.40): Ask for clarification
- CONFIDENCE_NONSENSE (0.30): Silent ignore if no workflow signals

The "silent ignore" mechanism is for messages with ZERO workflow relevance:
- Random keyboard mashing ("asdfghjkl")
- Completely off-topic content ("I love Darth Vader")
- Messages that fail all workflow pattern detection

IMPORTANT: A message is NOT nonsense if it contains ANY workflow signal,
even if mixed with gibberish. "hahahaha. ok confirm date" → NOT nonsense.
"""

import re
from typing import Tuple

# Threshold constants
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.65
CONFIDENCE_LOW = 0.40
CONFIDENCE_NONSENSE = 0.30  # Below this + no workflow signals = ignore

# Workflow-relevant patterns (EN/DE) - if ANY match, message is not nonsense
# These are lightweight checks; full classification happens elsewhere
WORKFLOW_SIGNALS = [
    # Dates and times
    r"\b\d{1,2}[./\-]\d{1,2}(?:[./\-]\d{2,4})?\b",  # Date patterns
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\w*\b",
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
    r"\b\d{1,2}:\d{2}\b",  # Time patterns
    r"\b(?:morning|afternoon|evening|vormittag|nachmittag|abend)\b",

    # Numbers that suggest capacity/pricing
    r"\b\d+\s*(?:people|persons|guests|attendees|pax|personen|gäste|teilnehmer|chf|francs?|euro|€)\b",
    r"\b(?:chf|eur|€)\s*\d+",

    # Booking/event keywords
    r"\b(?:book|reserve|reserv|confirm|buchen|reservieren|bestätigen)\w*\b",
    r"\b(?:event|meeting|conference|workshop|seminar|party|wedding|veranstaltung|tagung|hochzeit|feier)\b",
    r"\b(?:room|space|venue|hall|raum|saal|zimmer|lokal)\b",
    r"\b(?:cancel|stornieren|absagen)\w*\b",

    # Acceptance/decline signals
    r"\b(?:yes|no|ok|okay|ja|nein|agree|accept|decline|proceed|confirm)\b",
    r"\b(?:sounds?\s+good|looks?\s+good|perfect|great|fine|einverstanden|passt|geht\s+klar)\b",

    # Questions about venue/booking
    r"\b(?:available|availability|free|open|verfügbar|frei)\b",
    r"\b(?:price|cost|rate|preis|kosten|kostet|tarif)\b",
    r"\b(?:capacity|size|fits?|platz|kapazität)\b",
    r"\b(?:catering|food|drinks|menu|essen|getränke)\b",

    # Change/update signals
    r"\b(?:change|modify|update|adjust|switch|move|ändern|wechseln|verschieben)\b",
    r"\b(?:instead|rather|actually|correction|stattdessen|eigentlich|korrektur)\b",

    # Common booking phrases
    r"\b(?:looking\s+for|interested\s+in|would\s+like|need\s+a|suche|brauche|möchte)\b",
    r"\b(?:for\s+\d+|für\s+\d+)\b",  # "for 50 people"
]

# Compile patterns for efficiency
_WORKFLOW_PATTERN = re.compile("|".join(WORKFLOW_SIGNALS), re.IGNORECASE)


def has_workflow_signal(text: str) -> bool:
    """
    Check if text contains ANY workflow-relevant signal.

    If True, the message should NEVER be ignored, regardless of confidence.
    """
    if not text:
        return False
    return bool(_WORKFLOW_PATTERN.search(text))


def is_gibberish(text: str) -> bool:
    """
    Check if text appears to be keyboard mashing or random characters.

    Heuristics:
    - Very short (< 3 chars)
    - Mostly non-alphabetic (< 40% letters)
    - Repeated single character (aaaaaaa)
    - Common keyboard patterns
    """
    if not text:
        return True

    text = text.strip()
    if len(text) < 3:
        return True

    # Mostly non-alphabetic
    alpha_ratio = sum(1 for c in text if c.isalpha()) / max(len(text), 1)
    if alpha_ratio < 0.4:
        return True

    # Repeated single character
    if re.match(r'^(.)\1{4,}$', text.lower()):
        return True

    # Common keyboard mash patterns
    keyboard_patterns = [
        r'^[asdfghjkl]+$',
        r'^[qwertyuiop]+$',
        r'^[zxcvbnm]+$',
    ]
    lowered = text.lower()
    for pattern in keyboard_patterns:
        if re.match(pattern, lowered):
            return True

    return False


def should_defer_to_human(confidence: float) -> bool:
    """Return True if confidence is too low to auto-proceed (needs HIL)."""
    return confidence < CONFIDENCE_NONSENSE


def should_seek_clarification(confidence: float) -> bool:
    """Return True if we should ask a clarifying question."""
    return confidence < CONFIDENCE_LOW


def should_ignore_message(confidence: float, message_text: str = "") -> bool:
    """
    Return True if we should NOT respond to this message at all.

    A message is nonsense (ignorable) if ALL of these are true:
    1. Confidence is below CONFIDENCE_NONSENSE (0.30)
    2. Message contains NO workflow-relevant signals
    3. Message appears to be gibberish OR is completely off-topic

    Examples that ARE ignored:
    - "asdfghjkl" (keyboard mash, no workflow signal)
    - "I love Darth Vader" (off-topic, no workflow signal)
    - "hahahahaha" (no workflow signal)

    Examples that are NOT ignored:
    - "hahahaha. ok confirm date" (has workflow signal "confirm date")
    - "maybe" (has "yes/no" adjacent meaning, ambiguous but relevant)
    - "what rooms are free?" (has "rooms" + "free")
    """
    # High enough confidence = never ignore
    if confidence >= CONFIDENCE_NONSENSE:
        return False

    # Has workflow signal = never ignore, even with low confidence
    if message_text and has_workflow_signal(message_text):
        return False

    # Low confidence + no workflow signal = check for gibberish
    if message_text and is_gibberish(message_text):
        return True

    # Low confidence + no workflow signal + not obvious gibberish
    # This catches off-topic messages like "I love Darth Vader"
    # Only ignore if confidence is really low
    if confidence < 0.20:
        return True

    return False


def confidence_level(score: float) -> str:
    """Return human-readable confidence level."""
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    if score >= CONFIDENCE_LOW:
        return "low"
    if score >= CONFIDENCE_NONSENSE:
        return "very_low"
    return "nonsense"


def classify_response_action(confidence: float, message_text: str = "") -> str:
    """
    Determine what action to take based on confidence level.

    Returns one of:
    - "proceed": High enough confidence to continue
    - "clarify": Ask for clarification
    - "defer": Send to HIL for human review
    - "ignore": Don't respond at all
    """
    if should_ignore_message(confidence, message_text):
        return "ignore"
    if should_defer_to_human(confidence):
        return "defer"
    if should_seek_clarification(confidence):
        return "clarify"
    return "proceed"


# Thresholds for step handler nonsense gate
NONSENSE_IGNORE_THRESHOLD = 0.15  # Below this: silent ignore
NONSENSE_HIL_THRESHOLD = 0.25     # Below this but above ignore: defer to HIL


def check_nonsense_gate(confidence: float, message_text: str) -> str:
    """
    Check if a message should be ignored or sent to HIL based on confidence.

    This is designed to be called by step handlers AFTER their own classification,
    using their existing confidence score (no extra LLM call).

    Args:
        confidence: The confidence score from the step's own classifier
        message_text: The original message text

    Returns:
        - "proceed": Message has workflow signal OR confidence high enough
        - "ignore": No workflow signal + very low confidence (silent, no reply)
        - "hil": No workflow signal + borderline confidence (defer to human)

    Decision matrix:
        | Confidence    | Workflow Signal | Action  |
        |---------------|-----------------|---------|
        | Any           | YES             | proceed |
        | < 0.15        | NO              | ignore  |
        | 0.15 - 0.25   | NO              | hil     |
        | >= 0.25       | NO              | proceed |
    """
    # Has workflow signal = always proceed, even with low confidence
    if has_workflow_signal(message_text):
        return "proceed"

    # No workflow signal - check confidence thresholds
    if confidence < NONSENSE_IGNORE_THRESHOLD:
        return "ignore"

    if confidence < NONSENSE_HIL_THRESHOLD:
        return "hil"

    return "proceed"
