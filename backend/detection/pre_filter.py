"""
Unified Pre-Filter for Per-Message Detection

This module provides a fast keyword-based pre-filter that runs on EVERY message
before any LLM calls. It sets flags that downstream processing can use to:
1. Skip unnecessary LLM calls (e.g., pure confirmations)
2. Route to special handlers (e.g., manager escalation)
3. Boost confidence for known patterns

Toggle: Use PRE_FILTER_MODE environment variable or admin UI:
- "enhanced": Use unified LLM call for ambiguous cases (default)
- "legacy": Use regex-only detection (fallback)

Cost: $0 for keyword detection, $0.00125 if LLM verification needed
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_pre_filter_mode() -> str:
    """Get current pre-filter mode from environment or database config."""
    return os.getenv("PRE_FILTER_MODE", "legacy").lower()


def is_enhanced_mode() -> bool:
    """Check if enhanced (LLM-assisted) pre-filter is enabled."""
    return get_pre_filter_mode() == "enhanced"


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class PreFilterResult:
    """
    Result of the pre-filter scan. All fields are computed from keywords/regex.
    No LLM calls are made in the pre-filter itself.
    """
    # Core detection
    is_duplicate: bool = False
    language: str = "en"  # "en" | "de"

    # Signal flags (trigger downstream behavior)
    has_question_signal: bool = False      # "?", "what", "which"
    has_confirmation_signal: bool = False  # "yes", "ok", "agree"
    has_change_signal: bool = False        # "change", "actually", "instead"
    has_manager_signal: bool = False       # "manager", "speak to", names
    has_urgency_signal: bool = False       # "urgent", "asap", "dringend"
    has_billing_signal: bool = False       # postal codes, street patterns
    has_acceptance_signal: bool = False    # "accept", "agree", "confirmed"
    has_rejection_signal: bool = False     # "cancel", "decline", "no thanks"

    # Extracted values (if found)
    detected_manager_name: Optional[str] = None
    detected_language_confidence: float = 0.5

    # Flags for downstream
    can_skip_intent_llm: bool = False      # Pure confirmation, skip LLM
    can_skip_entity_llm: bool = False      # No entities needed
    requires_hil_routing: bool = False     # Route to manager immediately

    # Debug info
    matched_patterns: List[str] = field(default_factory=list)
    confidence_boost: float = 0.0          # Add to LLM confidence

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "is_duplicate": self.is_duplicate,
            "language": self.language,
            "signals": {
                "question": self.has_question_signal,
                "confirmation": self.has_confirmation_signal,
                "change": self.has_change_signal,
                "manager": self.has_manager_signal,
                "urgency": self.has_urgency_signal,
                "billing": self.has_billing_signal,
                "acceptance": self.has_acceptance_signal,
                "rejection": self.has_rejection_signal,
            },
            "can_skip_intent_llm": self.can_skip_intent_llm,
            "can_skip_entity_llm": self.can_skip_entity_llm,
            "requires_hil_routing": self.requires_hil_routing,
            "matched_patterns": self.matched_patterns,
            "confidence_boost": self.confidence_boost,
        }


# =============================================================================
# KEYWORD BUCKETS
# =============================================================================

# Manager/Escalation signals
MANAGER_SIGNALS_EN = [
    "manager", "speak to", "talk to", "escalate", "human", "real person",
    "someone else", "supervisor", "person in charge", "contact someone",
    "actual person", "live person", "representative", "support team",
    "customer service", "help desk", "escalate this",
]

MANAGER_SIGNALS_DE = [
    "geschäftsführer", "vorgesetzten", "jemand anderen", "echte person",
    "mit jemandem sprechen", "eskalieren", "kundenservice", "support",
    "verantwortlichen", "ansprechpartner", "persönlich sprechen",
]

# Urgency signals
URGENCY_SIGNALS_EN = [
    "urgent", "asap", "immediately", "rush", "priority", "time-sensitive",
    "as soon as possible", "right away", "critical", "emergency",
    "deadline", "today", "now", "quickly", "fast",
]

URGENCY_SIGNALS_DE = [
    "dringend", "sofort", "eilig", "schnell", "priorität", "zeitkritisch",
    "so schnell wie möglich", "umgehend", "notfall", "heute noch",
]

# Confirmation signals (simple yes/ok)
CONFIRMATION_SIGNALS_EN = [
    "yes", "ok", "okay", "sure", "sounds good", "perfect", "great",
    "let's do it", "proceed", "go ahead", "confirmed", "that works",
    "works for me", "all good", "fine", "agreed", "deal",
]

CONFIRMATION_SIGNALS_DE = [
    "ja", "ok", "einverstanden", "passt", "perfekt", "super", "gut",
    "machen wir", "weiter", "bestätigt", "in ordnung", "geht klar",
    "abgemacht", "einig",
]

# Acceptance signals (for offers)
ACCEPTANCE_SIGNALS_EN = [
    "accept", "i accept", "we accept", "accepted", "approve", "approved",
    "i agree", "we agree", "book it", "confirm booking", "finalize",
    "let's book", "go with this", "take it",
]

ACCEPTANCE_SIGNALS_DE = [
    "akzeptieren", "akzeptiert", "annehmen", "angenommen", "genehmigt",
    "buchen", "buchung bestätigen", "abschließen", "nehmen wir",
]

# Rejection signals
REJECTION_SIGNALS_EN = [
    "no", "no thanks", "not interested", "cancel", "decline", "reject",
    "pass", "skip", "nevermind", "forget it", "not now", "maybe later",
    "too expensive", "can't afford",
]

REJECTION_SIGNALS_DE = [
    "nein", "nein danke", "kein interesse", "absagen", "ablehnen",
    "stornieren", "vergiss es", "vielleicht später", "zu teuer",
]

# Change signals
CHANGE_SIGNALS_EN = [
    "change", "modify", "update", "different", "instead", "actually",
    "switch", "move", "reschedule", "prefer", "rather", "correction",
    "on second thought", "wait", "hold on",
]

CHANGE_SIGNALS_DE = [
    "ändern", "wechseln", "verschieben", "anders", "stattdessen",
    "eigentlich", "korrektur", "ich meinte", "moment", "halt",
    "doch lieber", "bevorzuge",
]

# Question signals
QUESTION_SIGNALS = [
    "?", "what", "which", "when", "where", "who", "how", "why",
    "can you", "could you", "would you", "do you", "is there",
    "are there", "does", "is it possible",
    # German
    "was", "welche", "wann", "wo", "wer", "wie", "warum",
    "können sie", "könnten sie", "gibt es", "ist es möglich",
]

# Language detection keywords (unique to each language)
GERMAN_UNIQUE_WORDS = [
    "und", "ist", "für", "mit", "von", "wir", "ich", "sie", "das", "die",
    "der", "den", "dem", "ein", "eine", "einen", "nicht", "auch", "aber",
    "oder", "wenn", "noch", "schon", "sehr", "nur", "kann", "muss",
    "bitte", "danke", "grüße", "freundliche", "herzliche",
]

# Billing address patterns (regex)
BILLING_PATTERNS = [
    r'\b\d{4,5}\s+[A-Za-zÀ-ÿ]+',           # Postal code + city (4-5 digits)
    r'\b[A-Za-zÀ-ÿ]+(?:strasse|straße|str\.?)\s*\d+',  # German street
    r'\b[A-Za-zÀ-ÿ]+\s*(?:street|road|avenue|lane)\s*\d+',  # English street
    r'\bCH[-\s]?\d{4}\b',                   # Swiss postal code
    r'\b\d{5}\s+[A-Za-zÀ-ÿ]+',             # German postal (5 digits)
    r'\b(?:switzerland|schweiz|suisse|ch)\b',  # Country mentions
]


# =============================================================================
# PRE-FILTER FUNCTIONS
# =============================================================================

def run_pre_filter(
    message: str,
    last_message: Optional[str] = None,
    event_entry: Optional[Dict[str, Any]] = None,
    registered_manager_names: Optional[List[str]] = None,
) -> PreFilterResult:
    """
    Run the unified pre-filter on an incoming message.

    This function ONLY uses keywords and regex - no LLM calls.
    It sets flags that downstream processing can use to optimize LLM usage.

    Args:
        message: The client message text
        last_message: Previous message for duplicate detection
        event_entry: Current event state (for context)
        registered_manager_names: List of known manager names to detect

    Returns:
        PreFilterResult with all detection flags set
    """
    result = PreFilterResult()
    text_lower = message.lower().strip()

    # -------------------------------------------------------------------------
    # 1. Duplicate Detection
    # -------------------------------------------------------------------------
    if last_message:
        last_lower = last_message.lower().strip()
        if text_lower == last_lower:
            result.is_duplicate = True
            result.matched_patterns.append("duplicate_exact_match")
            # Check bypass conditions
            if event_entry:
                # Don't flag as duplicate in special flows
                in_billing_flow = (
                    event_entry.get("offer_accepted") and
                    (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
                )
                in_detour = event_entry.get("caller_step") is not None
                if in_billing_flow or in_detour:
                    result.is_duplicate = False
                    result.matched_patterns.append("duplicate_bypassed_special_flow")

    # -------------------------------------------------------------------------
    # 2. Language Detection
    # -------------------------------------------------------------------------
    german_count = sum(1 for word in GERMAN_UNIQUE_WORDS if f" {word} " in f" {text_lower} ")
    if german_count >= 2:
        result.language = "de"
        result.detected_language_confidence = min(0.5 + german_count * 0.1, 0.95)
        result.matched_patterns.append(f"language_de_{german_count}_words")
    else:
        result.language = "en"
        result.detected_language_confidence = 0.7

    # -------------------------------------------------------------------------
    # 3. Question Signals
    # -------------------------------------------------------------------------
    for signal in QUESTION_SIGNALS:
        if signal in text_lower:
            result.has_question_signal = True
            result.matched_patterns.append(f"question:{signal}")
            break

    # -------------------------------------------------------------------------
    # 4. Confirmation Signals
    # -------------------------------------------------------------------------
    confirmation_list = CONFIRMATION_SIGNALS_EN + CONFIRMATION_SIGNALS_DE
    for signal in confirmation_list:
        if signal in text_lower:
            result.has_confirmation_signal = True
            result.matched_patterns.append(f"confirmation:{signal}")
            result.confidence_boost = 0.1
            break

    # -------------------------------------------------------------------------
    # 5. Acceptance Signals
    # -------------------------------------------------------------------------
    acceptance_list = ACCEPTANCE_SIGNALS_EN + ACCEPTANCE_SIGNALS_DE
    for signal in acceptance_list:
        if signal in text_lower:
            result.has_acceptance_signal = True
            result.matched_patterns.append(f"acceptance:{signal}")
            result.confidence_boost = 0.2
            break

    # -------------------------------------------------------------------------
    # 6. Rejection Signals
    # -------------------------------------------------------------------------
    rejection_list = REJECTION_SIGNALS_EN + REJECTION_SIGNALS_DE
    for signal in rejection_list:
        if signal in text_lower:
            result.has_rejection_signal = True
            result.matched_patterns.append(f"rejection:{signal}")
            break

    # -------------------------------------------------------------------------
    # 7. Change Signals
    # -------------------------------------------------------------------------
    change_list = CHANGE_SIGNALS_EN + CHANGE_SIGNALS_DE
    for signal in change_list:
        if signal in text_lower:
            result.has_change_signal = True
            result.matched_patterns.append(f"change:{signal}")
            break

    # -------------------------------------------------------------------------
    # 8. Manager/Escalation Signals - REMOVED (now uses LLM semantic detection)
    # Manager requests like "Can I speak with someone?" need semantic understanding,
    # not regex keywords. This prevents false positives on emails like
    # "test-manager@example.com". See unified.py for LLM-based detection.
    # -------------------------------------------------------------------------
    # NOTE: has_manager_signal and requires_hil_routing are no longer set here.
    # Use unified_detection.is_manager_request instead.

    # -------------------------------------------------------------------------
    # 9. Urgency Signals
    # -------------------------------------------------------------------------
    urgency_list = URGENCY_SIGNALS_EN + URGENCY_SIGNALS_DE
    for signal in urgency_list:
        if signal in text_lower:
            result.has_urgency_signal = True
            result.matched_patterns.append(f"urgency:{signal}")
            break

    # -------------------------------------------------------------------------
    # 10. Billing Address Signals (Regex)
    # -------------------------------------------------------------------------
    for pattern in BILLING_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            result.has_billing_signal = True
            result.matched_patterns.append(f"billing:{pattern[:20]}...")
            break

    # -------------------------------------------------------------------------
    # 11. Determine Skip Flags
    # -------------------------------------------------------------------------

    # Can skip intent LLM if pure confirmation with no other signals
    # NOTE: Manager detection is now via unified LLM, so we don't check has_manager_signal here
    word_count = len(text_lower.split())
    is_pure_confirmation = (
        result.has_confirmation_signal and
        not result.has_question_signal and
        not result.has_change_signal and
        word_count <= 5
    )
    if is_pure_confirmation:
        result.can_skip_intent_llm = True
        result.matched_patterns.append("skip_intent_pure_confirmation")

    # Can skip entity LLM if simple acceptance/rejection
    is_simple_response = (
        (result.has_acceptance_signal or result.has_rejection_signal) and
        not result.has_billing_signal and
        not result.has_change_signal and
        word_count <= 10
    )
    if is_simple_response:
        result.can_skip_entity_llm = True
        result.matched_patterns.append("skip_entity_simple_response")

    # NOTE: requires_hil_routing is no longer set based on regex manager detection.
    # Manager escalation is now detected via LLM semantic analysis in unified.py
    # and handled in pre_route.py using unified_detection.is_manager_request

    return result


def detect_manager_escalation(
    message: str,
    registered_manager_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Specialized function to detect manager escalation requests.

    Returns:
        {
            "is_escalation": bool,
            "confidence": float (0.0-1.0),
            "detected_name": str or None,
            "escalation_type": "explicit" | "implicit" | None,
            "matched_signals": [str]
        }
    """
    text_lower = message.lower().strip()
    result = {
        "is_escalation": False,
        "confidence": 0.0,
        "detected_name": None,
        "escalation_type": None,
        "matched_signals": [],
    }

    # Check explicit escalation keywords
    explicit_signals = [
        "speak to manager", "talk to manager", "escalate",
        "speak to a human", "talk to a person", "real person",
        "customer service", "supervisor", "person in charge",
        "mit dem manager sprechen", "vorgesetzten",
    ]

    for signal in explicit_signals:
        if signal in text_lower:
            result["is_escalation"] = True
            result["confidence"] = 0.9
            result["escalation_type"] = "explicit"
            result["matched_signals"].append(signal)

    # Check implicit escalation (frustration patterns)
    implicit_signals = [
        "this is ridiculous", "not helpful", "useless",
        "i give up", "forget it", "waste of time",
        "das ist lächerlich", "nicht hilfreich", "zeitverschwendung",
    ]

    for signal in implicit_signals:
        if signal in text_lower:
            result["is_escalation"] = True
            result["confidence"] = max(result["confidence"], 0.7)
            result["escalation_type"] = result["escalation_type"] or "implicit"
            result["matched_signals"].append(signal)

    # Check for manager names
    if registered_manager_names:
        name_patterns = [
            r"ask\s+{name}", r"contact\s+{name}", r"speak\s+to\s+{name}",
            r"talk\s+to\s+{name}", r"email\s+{name}", r"call\s+{name}",
            r"frag\s+{name}", r"kontaktiere\s+{name}",
        ]
        for name in registered_manager_names:
            for pattern in name_patterns:
                full_pattern = pattern.format(name=re.escape(name.lower()))
                if re.search(full_pattern, text_lower):
                    result["is_escalation"] = True
                    result["confidence"] = 0.95
                    result["detected_name"] = name
                    result["escalation_type"] = "explicit"
                    result["matched_signals"].append(f"name:{name}")

    return result


# =============================================================================
# LEGACY MODE FUNCTIONS (Fallback)
# =============================================================================

def run_pre_filter_legacy(
    message: str,
    last_message: Optional[str] = None,
    event_entry: Optional[Dict[str, Any]] = None,
) -> PreFilterResult:
    """
    Legacy pre-filter that does duplicate detection only.

    Manager escalation detection is now handled via unified LLM detection,
    which provides semantic understanding of phrases like "Can I speak with someone?"
    rather than relying on regex keywords that can have false positives.
    """
    result = PreFilterResult()
    text_lower = message.lower().strip()

    # Only do duplicate detection
    if last_message:
        last_lower = last_message.lower().strip()
        if text_lower == last_lower:
            result.is_duplicate = True
            # Check bypass conditions
            if event_entry:
                in_billing_flow = (
                    event_entry.get("offer_accepted") and
                    (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
                )
                in_detour = event_entry.get("caller_step") is not None
                if in_billing_flow or in_detour:
                    result.is_duplicate = False

    # NOTE: Manager/Escalation Signals are now detected via LLM semantic detection
    # in unified.py rather than regex keywords here. This prevents false positives
    # on emails like "test-manager@example.com" and provides better understanding
    # of phrases like "Can I speak with someone?"

    # Legacy mode doesn't set any skip flags - always run LLM
    result.can_skip_intent_llm = False
    result.can_skip_entity_llm = False

    return result


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def pre_filter(
    message: str,
    last_message: Optional[str] = None,
    event_entry: Optional[Dict[str, Any]] = None,
    registered_manager_names: Optional[List[str]] = None,
) -> PreFilterResult:
    """
    Main entry point for pre-filter. Automatically selects enhanced or legacy mode
    based on configuration.

    Args:
        message: The client message text
        last_message: Previous message for duplicate detection
        event_entry: Current event state
        registered_manager_names: Known manager names for escalation detection

    Returns:
        PreFilterResult with detection flags
    """
    if is_enhanced_mode():
        return run_pre_filter(
            message=message,
            last_message=last_message,
            event_entry=event_entry,
            registered_manager_names=registered_manager_names,
        )
    else:
        return run_pre_filter_legacy(
            message=message,
            last_message=last_message,
            event_entry=event_entry,
        )
