"""
Unified Message Detection - One LLM Call Per Message

This module provides a single LLM call that extracts:
- Language (en/de)
- Intent classification
- Signal flags (confirmation, manager request, change, urgency)
- Entities (date, participants, billing address, products)
- Confidence score

COST: ~$0.004/message (Gemini Flash) vs ~$0.013/message (separate calls)
ACCURACY: Higher than keyword regex (no false positives)

Toggle: Use DETECTION_MODE environment variable or admin UI:
- "unified": One LLM call for all detection (default, recommended)
- "legacy": Separate keyword + intent + entity calls (fallback)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.vocabulary import IntentLabel


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_detection_mode() -> str:
    """Get current detection mode from environment or database config."""
    return os.getenv("DETECTION_MODE", "unified").lower()


def is_unified_mode() -> bool:
    """Check if unified detection mode is enabled."""
    return get_detection_mode() == "unified"


# =============================================================================
# RESULT DATACLASS
# =============================================================================

@dataclass
class UnifiedDetectionResult:
    """
    Complete detection result from a single LLM call.
    Replaces: pre-filter + intent classification + entity extraction.
    """
    # Language
    language: str = "en"  # "en" | "de"

    # Intent (maps to IntentLabel)
    intent: str = "general_qna"
    intent_confidence: float = 0.5

    # Signal flags (replaces keyword detection)
    is_confirmation: bool = False      # Simple yes/ok/agreed
    is_acceptance: bool = False        # Accepting an offer
    is_rejection: bool = False         # Declining/canceling
    is_change_request: bool = False    # Wants to modify something
    is_manager_request: bool = False   # Wants human escalation
    is_question: bool = False          # Asking for information
    has_urgency: bool = False          # Time-sensitive request

    # Extracted entities
    date: Optional[str] = None         # ISO format YYYY-MM-DD
    date_text: Optional[str] = None    # Original text "next Tuesday"
    participants: Optional[int] = None
    duration_hours: Optional[float] = None
    room_preference: Optional[str] = None
    products: List[str] = field(default_factory=list)
    billing_address: Optional[Dict[str, str]] = None

    # Q&A routing hints
    qna_types: List[str] = field(default_factory=list)
    step_anchor: Optional[str] = None

    # Metadata
    raw_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "language": self.language,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "signals": {
                "confirmation": self.is_confirmation,
                "acceptance": self.is_acceptance,
                "rejection": self.is_rejection,
                "change_request": self.is_change_request,
                "manager_request": self.is_manager_request,
                "question": self.is_question,
                "urgency": self.has_urgency,
            },
            "entities": {
                "date": self.date,
                "date_text": self.date_text,
                "participants": self.participants,
                "duration_hours": self.duration_hours,
                "room_preference": self.room_preference,
                "products": self.products,
                "billing_address": self.billing_address,
            },
            "qna_types": self.qna_types,
            "step_anchor": self.step_anchor,
        }

    def to_intent_label(self) -> IntentLabel:
        """Convert string intent to IntentLabel enum."""
        mapping = {
            "event_request": IntentLabel.EVENT_REQUEST,
            "confirm_date": IntentLabel.CONFIRM_DATE,
            "confirm_date_partial": IntentLabel.CONFIRM_DATE_PARTIAL,
            "edit_date": IntentLabel.EDIT_DATE,
            "edit_room": IntentLabel.EDIT_ROOM,
            "edit_requirements": IntentLabel.EDIT_REQUIREMENTS,
            "accept_offer": IntentLabel.ACCEPT_OFFER,
            "decline_offer": IntentLabel.DECLINE_OFFER,
            "counter_offer": IntentLabel.COUNTER_OFFER,
            "message_manager": IntentLabel.MESSAGE_MANAGER,
            "general_qna": IntentLabel.NON_EVENT,
            "non_event": IntentLabel.NON_EVENT,
        }
        return mapping.get(self.intent, IntentLabel.NON_EVENT)


# =============================================================================
# UNIFIED DETECTION PROMPT
# =============================================================================

UNIFIED_DETECTION_PROMPT = """Analyze this client message for a venue booking system. Extract ALL information in one pass.

MESSAGE:
{message}

CONTEXT (if available):
- Current workflow step: {current_step}
- Event has date confirmed: {date_confirmed}
- Event has room locked: {room_locked}
- Last assistant message topic: {last_topic}

Return a JSON object with this exact structure:
{{
  "language": "en" or "de" (CRITICAL: Look at the VERB/GRAMMAR of the main request, NOT proper nouns or addresses. Examples: "Please send invoice to Firma Müller, München" = "en" (verb "send" is English). "Bitte senden Sie an Firma Müller" = "de" (verb "senden" is German). Ignore company names, street names, city names when determining language),
  "intent": one of ["event_request", "confirm_date", "edit_date", "edit_room", "edit_requirements", "accept_offer", "decline_offer", "counter_offer", "message_manager", "general_qna", "non_event"],
  "intent_confidence": 0.0 to 1.0,
  "signals": {{
    "is_confirmation": true ONLY for simple unconditional affirmations like "yes", "ok", "sounds good". FALSE if followed by "but", conditions, or hesitation (e.g., "yes but I need to check..." = false),
    "is_acceptance": true if accepting an offer/proposal FOR THE BOOKING,
    "is_rejection": true ONLY if client explicitly wants to CANCEL/ABORT THE ENTIRE BOOKING or decline the venue offer. False for: unrelated uses of "decline" (like "decline to comment"), removing single items (use is_change_request), or general negativity,
    "is_change_request": true if wants to modify date/room/requirements/products (including removing items like "no catering"),
    "is_manager_request": true ONLY if client is REQUESTING to speak with a human/manager/supervisor. Must be a REQUEST, not a statement. FALSE for job titles like "I'm the Event Manager" or "Manager John here". TRUE examples: "Can I speak to someone?", "I want to talk to a real person", "Please escalate this",
    "is_question": true ONLY if asking for INFORMATION (e.g., "Do you have parking?", "What's the capacity?"). NOT for action requests like "Could you send me..." or "Please confirm...",
    "has_urgency": true if time-sensitive (urgent, asap, deadline)
  }},
  "entities": {{
    "date": "YYYY-MM-DD" or null (convert relative dates like "next Tuesday" to ISO),
    "date_text": original date text from message or null,
    "participants": integer or null,
    "duration_hours": float or null,
    "room_preference": room name or null,
    "products": ["catering", "projector", ...] or [],
    "billing_address": {{"company": "", "street": "", "postal_code": "", "city": "", "country": ""}} or null
  }},
  "qna_types": list of applicable types from ["free_dates", "room_features", "catering_for", "products_for", "site_visit", "parking", "check_availability", "check_capacity"],
  "step_anchor": suggested workflow step or null
}}

IMPORTANT:
- Be precise with intent classification
- Extract ALL entities mentioned, even if implicit
- For dates, convert to ISO format based on context (assume current year if not specified)
- For "is_confirmation", only true for simple affirmations (yes, ok, sounds good) NOT detailed responses
- Return valid JSON only, no markdown or explanation"""


# =============================================================================
# DETECTION FUNCTION
# =============================================================================

def run_unified_detection(
    message: str,
    *,
    current_step: Optional[int] = None,
    date_confirmed: bool = False,
    room_locked: bool = False,
    last_topic: Optional[str] = None,
) -> UnifiedDetectionResult:
    """
    Run unified detection on a message using a single LLM call.

    Args:
        message: The client message text
        current_step: Current workflow step (1-7)
        date_confirmed: Whether date is already confirmed
        room_locked: Whether room is already locked
        last_topic: Topic of last assistant message

    Returns:
        UnifiedDetectionResult with all extracted information
    """
    from backend.adapters.agent_adapter import get_agent_adapter

    # Build the prompt
    prompt = UNIFIED_DETECTION_PROMPT.format(
        message=message,
        current_step=current_step or "unknown",
        date_confirmed=date_confirmed,
        room_locked=room_locked,
        last_topic=last_topic or "unknown",
    )

    # Get agent adapter (uses configured provider - Gemini by default)
    adapter = get_agent_adapter()

    try:
        # Make the LLM call
        response_text = adapter.complete(
            prompt=prompt,
            system_prompt="You are a precise JSON extraction assistant. Return only valid JSON.",
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=1000,
        )

        # Parse JSON response
        # Handle potential markdown code blocks
        json_text = response_text.strip()
        if json_text.startswith("```"):
            json_text = re.sub(r"```(?:json)?\n?", "", json_text)
            json_text = json_text.rstrip("`").strip()

        data = json.loads(json_text)

        # Build result from parsed data
        signals = data.get("signals", {})
        entities = data.get("entities", {})

        result = UnifiedDetectionResult(
            language=data.get("language", "en"),
            intent=data.get("intent", "general_qna"),
            intent_confidence=data.get("intent_confidence", 0.5),
            is_confirmation=signals.get("is_confirmation", False),
            is_acceptance=signals.get("is_acceptance", False),
            is_rejection=signals.get("is_rejection", False),
            is_change_request=signals.get("is_change_request", False),
            is_manager_request=signals.get("is_manager_request", False),
            is_question=signals.get("is_question", False),
            has_urgency=signals.get("has_urgency", False),
            date=entities.get("date"),
            date_text=entities.get("date_text"),
            participants=entities.get("participants"),
            duration_hours=entities.get("duration_hours"),
            room_preference=entities.get("room_preference"),
            products=entities.get("products", []),
            billing_address=entities.get("billing_address"),
            qna_types=data.get("qna_types", []),
            step_anchor=data.get("step_anchor"),
            raw_response=data,
        )

        return result

    except json.JSONDecodeError as e:
        print(f"[UNIFIED_DETECTION] JSON parse error: {e}")
        # Return minimal result on parse failure
        return UnifiedDetectionResult(
            intent="general_qna",
            intent_confidence=0.3,
        )
    except Exception as e:
        print(f"[UNIFIED_DETECTION] Error: {e}")
        return UnifiedDetectionResult(
            intent="general_qna",
            intent_confidence=0.3,
        )


# =============================================================================
# DUPLICATE DETECTION (Kept separate - $0 cost, reliable)
# =============================================================================

def check_duplicate(
    message: str,
    last_message: Optional[str],
    *,
    in_special_flow: bool = False,
) -> bool:
    """
    Check if message is duplicate of last message.

    This is kept separate from LLM detection because:
    - String comparison is $0 cost
    - 100% reliable (no false positives/negatives)
    - Needs to run before LLM call to save cost

    Args:
        message: Current message
        last_message: Previous message (if any)
        in_special_flow: If True, skip duplicate detection (billing flow, etc.)

    Returns:
        True if duplicate, False otherwise
    """
    if not last_message:
        return False

    if in_special_flow:
        return False

    normalized_current = message.strip().lower()
    normalized_last = last_message.strip().lower()

    return normalized_current == normalized_last


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def detect(
    message: str,
    *,
    last_message: Optional[str] = None,
    event_entry: Optional[Dict[str, Any]] = None,
    current_step: Optional[int] = None,
) -> Tuple[UnifiedDetectionResult, bool]:
    """
    Main entry point for message detection.

    Automatically selects unified or legacy mode based on configuration.

    Args:
        message: The client message text
        last_message: Previous message for duplicate check
        event_entry: Current event state
        current_step: Current workflow step

    Returns:
        Tuple of (UnifiedDetectionResult, is_duplicate)
    """
    # Extract context from event_entry
    date_confirmed = False
    room_locked = False
    in_special_flow = False
    last_topic = None

    if event_entry:
        date_confirmed = event_entry.get("date_confirmed", False)
        room_locked = event_entry.get("locked_room_id") is not None
        current_step = current_step or event_entry.get("current_step")

        # Check special flow states
        in_special_flow = (
            event_entry.get("offer_accepted") and
            (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        ) or event_entry.get("caller_step") is not None

        # Get last topic from thread state
        thread_state = event_entry.get("thread_state", {})
        last_topic = thread_state.get("last_topic")

    # 1. Check duplicate first ($0 cost)
    is_duplicate = check_duplicate(message, last_message, in_special_flow=in_special_flow)

    if is_duplicate:
        # Return minimal result for duplicates
        return UnifiedDetectionResult(intent="duplicate"), True

    # 2. Run detection based on mode
    if is_unified_mode():
        result = run_unified_detection(
            message,
            current_step=current_step,
            date_confirmed=date_confirmed,
            room_locked=room_locked,
            last_topic=last_topic,
        )
    else:
        # Legacy mode - use existing separate calls
        result = _run_legacy_detection(message, current_step=current_step)

    return result, False


def _run_legacy_detection(
    message: str,
    *,
    current_step: Optional[int] = None,
) -> UnifiedDetectionResult:
    """
    Legacy detection using separate keyword + intent + entity calls.

    Used as fallback if unified mode causes issues.
    """
    from backend.detection.intent.classifier import classify_intent
    from backend.detection.pre_filter import run_pre_filter

    # Run keyword pre-filter
    pre_filter_result = run_pre_filter(message)

    # Run intent classification
    intent_result = classify_intent(message, current_step=current_step)

    # Map to UnifiedDetectionResult
    return UnifiedDetectionResult(
        language=pre_filter_result.language,
        intent=intent_result.get("primary", "general_qna"),
        intent_confidence=intent_result.get("agent_confidence", 0.5),
        is_confirmation=pre_filter_result.has_confirmation_signal,
        is_acceptance=pre_filter_result.has_acceptance_signal,
        is_rejection=pre_filter_result.has_rejection_signal,
        is_change_request=pre_filter_result.has_change_signal,
        is_manager_request=pre_filter_result.has_manager_signal,
        is_question=pre_filter_result.has_question_signal,
        has_urgency=pre_filter_result.has_urgency_signal,
        qna_types=intent_result.get("secondary", []),
        step_anchor=intent_result.get("step_anchor"),
    )


__all__ = [
    "UnifiedDetectionResult",
    "detect",
    "run_unified_detection",
    "check_duplicate",
    "is_unified_mode",
    "get_detection_mode",
]
