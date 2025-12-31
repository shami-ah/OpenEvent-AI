"""
Safety verifier for LLM-verbalized output.

Ensures that hard facts (dates, prices, room names, counts) are preserved
in the LLM output and that no new facts are invented.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.ux.verbalizer_payloads import RoomOfferFacts
from backend.workflows.io.config_store import get_currency_regex

logger = logging.getLogger(__name__)


@dataclass
class HardFacts:
    """Extracted hard facts that must be preserved."""

    dates: Set[str] = field(default_factory=set)  # DD.MM.YYYY format
    room_names: Set[str] = field(default_factory=set)
    currency_amounts: Set[str] = field(default_factory=set)  # e.g., "CHF 92", "CHF 500.00"
    numeric_counts: Set[str] = field(default_factory=set)  # participant counts, capacities
    time_strings: Set[str] = field(default_factory=set)  # e.g., "14:00", "18:00–22:00"


@dataclass
class VerificationResult:
    """Result of verifying LLM output against facts."""

    ok: bool
    missing_facts: Dict[str, List[str]] = field(default_factory=dict)
    invented_facts: Dict[str, List[str]] = field(default_factory=dict)
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "missing_facts": self.missing_facts,
            "invented_facts": self.invented_facts,
            "reason": self.reason,
        }


# Regex patterns for fact extraction
DATE_PATTERN = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")
# Legacy constant (use _get_currency_pattern() for dynamic currency code)
CURRENCY_PATTERN = re.compile(r"\b(CHF\s*\d+(?:[.,]\d{1,2})?)\b", re.IGNORECASE)
TIME_PATTERN = re.compile(r"\b(\d{1,2}:\d{2}(?:–\d{1,2}:\d{2})?)\b")
PARTICIPANT_COUNT_PATTERN = re.compile(r"\b(\d+)\s*(?:people|persons|participants|guests|attendees|pax)\b", re.IGNORECASE)


def _get_currency_pattern() -> re.Pattern:
    """Get currency pattern from config (dynamic based on venue currency code)."""
    return get_currency_regex()


def extract_hard_facts(facts: RoomOfferFacts) -> HardFacts:
    """
    Extract canonical hard facts from the facts bundle.

    These are the facts that MUST appear in the LLM output.
    """
    result = HardFacts()

    # Dates
    if facts.event_date:
        result.dates.add(facts.event_date)

    # Room names
    for room in facts.rooms:
        if room.name:
            result.room_names.add(room.name)
            # Also add common variants
            result.room_names.add(room.name.replace(".", ""))  # "Punkt.Null" -> "PunktNull"

    if facts.recommended_room:
        result.room_names.add(facts.recommended_room)

    # Currency amounts
    if facts.total_amount:
        result.currency_amounts.add(_normalize_currency(facts.total_amount))

    if facts.deposit_amount:
        result.currency_amounts.add(_normalize_currency(facts.deposit_amount))

    for menu in facts.menus:
        if menu.price:
            result.currency_amounts.add(_normalize_currency(menu.price))

    # Numeric counts - participant count is critical
    if facts.participants_count is not None:
        result.numeric_counts.add(str(facts.participants_count))

    # Room capacities
    for room in facts.rooms:
        if room.capacity_max is not None:
            result.numeric_counts.add(str(room.capacity_max))

    # Time strings
    if facts.time_window:
        result.time_strings.add(facts.time_window)

    return result


def _normalize_currency(amount: str) -> str:
    """Normalize currency string for comparison."""
    # Remove extra spaces, standardize format
    normalized = re.sub(r"\s+", " ", amount.strip())
    # Ensure "CHF" prefix
    if not normalized.upper().startswith("CHF"):
        normalized = f"CHF {normalized}"
    return normalized.upper().replace(",", ".")


def _extract_facts_from_text(text: str) -> HardFacts:
    """Extract hard facts from LLM-generated text."""
    result = HardFacts()

    # Extract dates
    for match in DATE_PATTERN.finditer(text):
        result.dates.add(match.group(1))

    # Extract currency amounts (uses dynamic pattern from venue config)
    for match in _get_currency_pattern().finditer(text):
        result.currency_amounts.add(_normalize_currency(match.group(1)))

    # Extract time strings
    for match in TIME_PATTERN.finditer(text):
        result.time_strings.add(match.group(1))

    # Note: Room names and numeric counts are validated differently
    # (we check presence, not extraction from text)

    return result


def verify_output(facts: RoomOfferFacts, llm_text: str) -> VerificationResult:
    """
    Verify that the LLM output preserves all hard facts and invents none.

    Returns a VerificationResult indicating success or failure with diagnostics.
    """
    if not llm_text or not llm_text.strip():
        return VerificationResult(ok=False, reason="empty_output")

    canonical = extract_hard_facts(facts)
    extracted = _extract_facts_from_text(llm_text)

    missing: Dict[str, List[str]] = {}
    invented: Dict[str, List[str]] = {}

    # Check dates: every canonical date must appear
    text_lower = llm_text.lower()
    for date in canonical.dates:
        if date not in llm_text:
            missing.setdefault("dates", []).append(date)

    # Check room names: every room must be mentioned
    for room_name in canonical.room_names:
        # Case-insensitive check, also check without dots
        room_lower = room_name.lower()
        room_no_dot = room_name.replace(".", "").lower()
        if room_lower not in text_lower and room_no_dot not in text_lower:
            missing.setdefault("room_names", []).append(room_name)

    # Check currency amounts: every price must appear
    for amount in canonical.currency_amounts:
        # Normalize for comparison
        amount_normalized = amount.replace(" ", "").upper()
        text_normalized = llm_text.replace(" ", "").upper()
        # Also check without decimal places for whole numbers
        amount_no_decimal = re.sub(r"\.00$", "", amount_normalized)
        if amount_normalized not in text_normalized and amount_no_decimal not in text_normalized:
            missing.setdefault("currency_amounts", []).append(amount)

    # Check participant count: must appear somewhere in text
    for count in canonical.numeric_counts:
        if count not in llm_text:
            # Only flag participant count as missing, not capacities
            if facts.participants_count is not None and count == str(facts.participants_count):
                missing.setdefault("numeric_counts", []).append(count)

    # Check for invented facts
    # Invented dates: dates in output not in canonical
    for date in extracted.dates:
        if date not in canonical.dates:
            invented.setdefault("dates", []).append(date)

    # Invented currency amounts: amounts in output not in canonical
    for amount in extracted.currency_amounts:
        found = False
        for canonical_amount in canonical.currency_amounts:
            # Flexible matching for currency
            canonical_norm = canonical_amount.replace(" ", "").upper()
            amount_norm = amount.replace(" ", "").upper()
            canonical_no_decimal = re.sub(r"\.00$", "", canonical_norm)
            amount_no_decimal = re.sub(r"\.00$", "", amount_norm)
            if canonical_norm == amount_norm or canonical_no_decimal == amount_no_decimal:
                found = True
                break
        if not found:
            invented.setdefault("currency_amounts", []).append(amount)

    # Determine overall result
    ok = not missing and not invented

    reason = None
    if missing and invented:
        reason = "missing_and_invented_facts"
    elif missing:
        reason = "missing_facts"
    elif invented:
        reason = "invented_facts"

    return VerificationResult(
        ok=ok,
        missing_facts=missing,
        invented_facts=invented,
        reason=reason,
    )


def log_verification_failure(
    facts: RoomOfferFacts,
    llm_text: str,
    result: VerificationResult,
) -> None:
    """Log a verification failure with diagnostics (no secrets)."""
    logger.warning(
        "Safety Sandwich verification failed",
        extra={
            "reason": result.reason,
            "missing_facts": result.missing_facts,
            "invented_facts": result.invented_facts,
            "event_date": facts.event_date,
            "room_count": len(facts.rooms),
            "menu_count": len(facts.menus),
            "llm_text_length": len(llm_text),
        },
    )


__all__ = [
    "HardFacts",
    "VerificationResult",
    "extract_hard_facts",
    "verify_output",
    "log_verification_failure",
]
