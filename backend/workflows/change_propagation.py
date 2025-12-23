"""
Change Propagation & DAG-based Routing (V4 Authoritative)

This module implements the deterministic change-routing logic per v4_dag_and_change_rules.md.
When a confirmed/captured variable is updated (date, room, requirements, products, offer),
ONLY the dependent steps re-run, using hash guards to avoid unnecessary recomputation.

Dependency DAG:
    participants ┐
    seating_layout ┼──► requirements ──► requirements_hash
    duration ┘
    special_requirements ┘
            │
            ▼
    chosen_date ───────────────────────────► Room Evaluation ──► locked_room_id
            │                                    │
            │                                    └────────► room_eval_hash
            ▼
    Offer Composition ──► selected_products ──► offer_hash
            ▼
    Confirmation / Deposit

Detour Flow:
    [ c a l l e r ] ──(change detected)──► [ owner step ]
    ▲                                           │
    └──────────(resolved + hashes)──────────────┘
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# Import enhanced detection from keyword_buckets
# MIGRATED: from backend.workflows.nlu.keyword_buckets -> backend.detection.keywords.buckets
from backend.detection.keywords.buckets import (
    DetourMode,
    MessageIntent,
    ChangeIntentResult,
    compute_change_intent_score,
    has_revision_signal,
    has_bound_target,
    is_pure_qa,
    is_confirmation,
    is_decline,
    detect_language,
    get_all_change_verbs,
    get_all_revision_markers,
    TARGET_PATTERNS,
)


class ChangeType(Enum):
    """Types of changes that can trigger re-evaluation."""

    DATE = "date"                    # chosen_date changed
    ROOM = "room"                    # locked_room_id requested change
    REQUIREMENTS = "requirements"    # participants/layout/duration/special changed
    PRODUCTS = "products"            # selected_products/catering changed
    COMMERCIAL = "commercial"        # pure price/terms negotiation
    DEPOSIT = "deposit"              # reservation/deposit/option operations
    SITE_VISIT = "site_visit"        # site visit date/time change
    CLIENT_INFO = "client_info"      # billing address, contact info, company details


@dataclass
class NextStepDecision:
    """Decision on which step to run next after a change."""

    next_step: int                          # Target step number (2-7)
    maybe_run_step3: bool = False           # Whether Step 3 might be needed
    updated_caller_step: Optional[int] = None  # New caller_step value
    skip_reason: Optional[str] = None       # Reason for skipping (e.g., "hash_match")
    needs_reeval: bool = True               # Whether re-evaluation is actually needed

    def __str__(self) -> str:
        parts = [f"next_step={self.next_step}"]
        if self.maybe_run_step3:
            parts.append("maybe_step3=True")
        if self.updated_caller_step:
            parts.append(f"caller={self.updated_caller_step}")
        if self.skip_reason:
            parts.append(f"skip={self.skip_reason}")
        if not self.needs_reeval:
            parts.append("needs_reeval=False")
        return f"NextStepDecision({', '.join(parts)})"


@dataclass
class EnhancedChangeResult:
    """
    Enhanced change detection result with dual-condition logic.

    This replaces the simple Optional[ChangeType] return with richer information
    including the detour mode and alternative intent if not a change.
    """
    is_change: bool                              # True if dual condition met
    change_type: Optional[ChangeType]            # Which variable is being changed
    mode: Optional[DetourMode]                   # LONG/FAST/EXPLICIT
    confidence: float                            # 0.0-1.0
    alternative_intent: Optional[MessageIntent]  # If not a change, what is it?
    revision_signals: List[str]                  # Which patterns matched
    target_matches: List[str]                    # Which target patterns matched
    language: str                                # "en", "de", or "mixed"
    old_value: Optional[Any] = None              # Previous value (if detectable)
    new_value: Optional[Any] = None              # New value (if provided)

    def __str__(self) -> str:
        if self.is_change:
            return (
                f"Change({self.change_type.value}, mode={self.mode.value if self.mode else 'none'}, "
                f"conf={self.confidence:.2f})"
            )
        return f"NoChange(intent={self.alternative_intent}, conf={self.confidence:.2f})"


# ============================================================================
# SHARED HELPER FUNCTIONS FOR CHANGE DETECTION
# ============================================================================


def has_requirement_update(event_state: Dict[str, Any], user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any requirement field updates.

    Args:
        event_state: Current event entry
        user_info: Extracted user information

    Returns:
        True if any requirement field differs from the current event_state
    """
    requirements = event_state.get("requirements") or {}
    duration_snapshot = requirements.get("event_duration") or {}
    requirement_fields = [
        "participants", "number_of_participants",
        "layout", "type", "seating_layout",
        "start_time", "end_time", "duration",
        "notes", "special_requirements"
    ]
    for field in requirement_fields:
        value = user_info.get(field)
        if value is None:
            continue

        # Map incoming user_info fields onto canonical requirement keys
        if field in ("participants", "number_of_participants"):
            current = requirements.get("number_of_participants")
        elif field in ("layout", "type", "seating_layout"):
            current = requirements.get("seating_layout")
        elif field in ("notes", "special_requirements"):
            current = requirements.get("special_requirements")
        elif field in ("start_time", "end_time", "duration"):
            new_start = user_info.get("start_time")
            new_end = user_info.get("end_time")
            current_start = duration_snapshot.get("start")
            current_end = duration_snapshot.get("end")

            # Treat any explicit change to start/end as a requirement update
            if new_start is not None and str(new_start) != str(current_start):
                return True
            if new_end is not None and str(new_end) != str(current_end):
                return True
            continue
        else:
            current = None

        if current is None and value not in (None, ""):
            return True
        if current is not None and str(current) != str(value):
            return True

    return False


def has_product_update(user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any product/catering field updates.

    Args:
        user_info: Extracted user information

    Returns:
        True if any product field is present in user_info
    """
    product_fields = [
        "products", "catering", "menu", "wine", "beverage",
        "products_add", "products_remove"
    ]
    return any(user_info.get(field) is not None for field in product_fields)


def has_client_info_update(user_info: Dict[str, Any]) -> bool:
    """
    Check if user_info contains any client information field updates.

    Args:
        user_info: Extracted user information

    Returns:
        True if any client info field is present in user_info
    """
    client_fields = [
        "billing_address", "billing_name", "company", "company_name",
        "vat", "vat_number", "phone", "email", "contact"
    ]
    return any(user_info.get(field) is not None for field in client_fields)


def extract_change_verbs_near_noun(message_text: str, target_nouns: List[str]) -> bool:
    """
    Check if change verbs appear near target nouns using regex.

    Example: "upgrade the coffee package" → True (upgrade + coffee/package)
    Example: "what coffee do you have" → False (no change verb)

    Args:
        message_text: Message text to search
        target_nouns: List of target nouns to look for near change verbs

    Returns:
        True if change verb appears within 5 words of target noun
    """
    if not message_text:
        return False

    text_lower = message_text.lower()

    # Change verb patterns
    change_verbs = [
        "change", "switch", "modify", "update", "adjust", "upgrade",
        "downgrade", "swap", "replace", "amend", "revise", "alter",
        "reschedule", "move"
    ]

    # Create pattern: (change_verb) .{0,50} (target_noun) OR (target_noun) .{0,50} (change_verb)
    # This allows up to ~10 words (5 chars/word avg) between verb and noun
    for verb in change_verbs:
        for noun in target_nouns:
            # Verb before noun: "upgrade ... package"
            pattern_forward = rf"\b{re.escape(verb)}\b.{{0,50}}\b{re.escape(noun)}\b"
            # Noun before verb: "package ... upgrade"
            pattern_backward = rf"\b{re.escape(noun)}\b.{{0,50}}\b{re.escape(verb)}\b"

            if re.search(pattern_forward, text_lower) or re.search(pattern_backward, text_lower):
                return True

    return False


HYPOTHETICAL_MARKERS = [
    r"\bwhat\s+if\b",
    r"\bhypothetically\b",
    r"\bin\s+theory\b",
    r"\bwould\s+it\s+be\s+possible\b",
    r"\bcould\s+we\s+potentially\b",
    r"\bjust\s+(curious|wondering|asking)\b",
    r"\bthinking\s+about\b",
    r"\bconsidering\b",
]


def is_hypothetical_question(text: str) -> bool:
    """Check if message is a hypothetical question vs actual change request."""
    text_lower = (text or "").lower()
    if not text_lower:
        return False
    for marker in HYPOTHETICAL_MARKERS:
        if re.search(marker, text_lower) and "?" in text_lower:
            return True
    return False


def has_change_intent_near_target(
    text: str,
    change_verbs: List[str],
    target_keywords: List[str],
    max_distance: int = 5,
) -> bool:
    """
    Check if change verbs appear within max_distance words of target keywords.
    """
    if not text:
        return False

    words = [token for token in re.split(r"\W+", text.lower()) if token]
    if not words:
        return False

    change_positions = [idx for idx, word in enumerate(words) if word in change_verbs]
    if not change_positions:
        return False

    target_positions = [
        idx for idx, word in enumerate(words) if any(keyword in word for keyword in target_keywords)
    ]
    if not target_positions:
        return False

    for cp in change_positions:
        for tp in target_positions:
            if abs(cp - tp) <= max_distance:
                return True

    return False


def route_change_on_updated_variable(
    event_state: Dict[str, Any],
    change_type: ChangeType,
    *,
    from_step: Optional[int] = None,
) -> NextStepDecision:
    """
    Route a change to the correct owning step per v4 DAG change matrix.

    Args:
        event_state: Event entry dict containing:
            - current_step: int
            - caller_step: Optional[int]
            - chosen_date: str
            - date_confirmed: bool
            - requirements_hash: str
            - room_eval_hash: str
            - locked_room_id: str
            - offer_hash: str (if applicable)
        change_type: Type of change that occurred
        from_step: Current step making the change (if known)

    Returns:
        NextStepDecision with routing information

    Behavior per v4 DAG:
        - DATE → Step 2 (Date Confirmation)
        - ROOM → Step 3 (Room Availability)
        - REQUIREMENTS → Step 3 (if requirements_hash ≠ room_eval_hash)
        - PRODUCTS → Step 4 (stay in products mini-flow)
        - COMMERCIAL → Step 5 (Negotiation)
        - DEPOSIT → Step 7 (Confirmation)
    """
    current_step = event_state.get("current_step") or 1
    caller_step = event_state.get("caller_step")
    requirements_hash_val = event_state.get("requirements_hash")
    room_eval_hash_val = event_state.get("room_eval_hash")
    date_confirmed = bool(event_state.get("date_confirmed"))
    locked_room_id = event_state.get("locked_room_id")

    # Determine the caller_step for detours
    # If not already set, use from_step or current_step
    if caller_step is None:
        new_caller = from_step if from_step is not None else current_step
    else:
        new_caller = caller_step

    # DATE CHANGE → Always detour to Step 2
    if change_type == ChangeType.DATE:
        return NextStepDecision(
            next_step=2,
            maybe_run_step3=True,  # Step 3 might run after date confirmation
            updated_caller_step=new_caller if new_caller != 2 else None,
            needs_reeval=True,
        )

    # ROOM CHANGE → Always detour to Step 3
    elif change_type == ChangeType.ROOM:
        return NextStepDecision(
            next_step=3,
            maybe_run_step3=False,  # We ARE Step 3
            updated_caller_step=new_caller if new_caller != 3 else None,
            needs_reeval=True,
        )

    # REQUIREMENTS CHANGE → Step 3 if hash mismatch
    elif change_type == ChangeType.REQUIREMENTS:
        # Check if requirements actually changed
        if requirements_hash_val and room_eval_hash_val:
            hashes_match = str(requirements_hash_val) == str(room_eval_hash_val)
            if hashes_match:
                # Fast-skip: requirements didn't actually change
                return NextStepDecision(
                    next_step=new_caller if new_caller else 4,
                    maybe_run_step3=False,
                    updated_caller_step=None,
                    skip_reason="requirements_hash_match",
                    needs_reeval=False,
                )

        # Requirements changed → detour to Step 3
        return NextStepDecision(
            next_step=3,
            maybe_run_step3=False,
            updated_caller_step=new_caller if new_caller != 3 else None,
            needs_reeval=True,
        )

    # PRODUCTS CHANGE → Stay in Step 4 products mini-flow
    elif change_type == ChangeType.PRODUCTS:
        # Products are confined to Step 4; no structural dependencies upward
        return NextStepDecision(
            next_step=4,
            maybe_run_step3=False,
            updated_caller_step=None,  # Don't set caller for products loop
            skip_reason="products_only",
            needs_reeval=True,  # Still need to recompute offer
        )

    # COMMERCIAL CHANGE → Step 5 (Negotiation) only
    elif change_type == ChangeType.COMMERCIAL:
        return NextStepDecision(
            next_step=5,
            maybe_run_step3=False,
            updated_caller_step=None,
            needs_reeval=True,
        )

    # DEPOSIT/RESERVATION CHANGE → Step 7 (Confirmation) only
    elif change_type == ChangeType.DEPOSIT:
        return NextStepDecision(
            next_step=7,
            maybe_run_step3=False,
            updated_caller_step=None,
            needs_reeval=True,
        )

    # SITE VISIT CHANGE → Step 7 (Confirmation) only
    elif change_type == ChangeType.SITE_VISIT:
        return NextStepDecision(
            next_step=7,
            maybe_run_step3=False,
            updated_caller_step=None,
            skip_reason="site_visit_reschedule",
            needs_reeval=True,
        )

    # CLIENT INFO CHANGE → Stay in current step, update in place
    elif change_type == ChangeType.CLIENT_INFO:
        return NextStepDecision(
            next_step=current_step,  # No routing needed
            maybe_run_step3=False,
            updated_caller_step=None,
            skip_reason="client_info_update",
            needs_reeval=False,  # Local update only
        )

    # Fallback: shouldn't reach here
    return NextStepDecision(
        next_step=current_step,
        maybe_run_step3=False,
        updated_caller_step=None,
        skip_reason="unknown_change_type",
        needs_reeval=False,
    )


def detect_change_type(
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    message_text: Optional[str] = None,
) -> Optional[ChangeType]:
    """
    Detect which type of change occurred based on user_info and event state.

    Args:
        event_state: Current event entry
        user_info: Extracted user information from message
        message_text: Optional message text for heuristic detection

    Returns:
        ChangeType if a change is detected, None otherwise

    Detection Rules (PRECISE PATTERN):
        Change fires ONLY when:
        1. Confirmed/existing variable is mentioned in message
        2. AND change intent signals present ("change", "switch", "actually", "instead")
        3. AND/OR new value extracted in user_info

        Supported Change Types (ALL gatekeeping variables):
        - DATE: "Can we change the date to March 5th?" ✅
        - ROOM: "Let's switch to Sky Loft instead" ✅
        - REQUIREMENTS: "Actually we're 50 people now" ✅
        - PRODUCTS: "Add Prosecco to the order" ✅
        - COMMERCIAL: "Could you do CHF 3000 instead?" ✅
        - DEPOSIT: "I'd like to proceed with the deposit" ✅
        - SITE_VISIT: "Can we reschedule the site visit to Tuesday?" ✅
        - CLIENT_INFO: "Update billing address to Zurich HQ" ✅

        Examples that DON'T fire (no change intent):
        - "What's the total price?" ❌
        - "When is the deposit due?" ❌
        - "How many people can the room hold?" ❌
    """
    date_confirmed = bool(event_state.get("date_confirmed"))
    chosen_date = event_state.get("chosen_date")
    locked_room_id = event_state.get("locked_room_id")
    current_step = event_state.get("current_step") or 1

    # Prepare message text for pattern matching
    text_lower = message_text.lower() if message_text else ""

    if text_lower and is_hypothetical_question(text_lower):
        return None

    # === CHANGE INTENT SIGNALS (EXPANDED) ===
    # Explicit change verbs
    change_verbs = [
        "change", "switch", "modify", "update", "adjust", "move to", "shift",
        "upgrade", "downgrade", "swap", "replace", "amend", "revise", "alter",
        "reschedule", "move", "drop", "reduce", "lower", "increase", "raise"
    ]
    # Redefinition markers
    redefinition_markers = [
        "actually", "instead", "rather", "correction", "make it", "make that",
        "in fact", "no wait", "sorry", "i meant", "to be clear", "let me correct"
    ]
    # Comparative language
    comparative = [
        "different", "another", "new", "alternate", "alternative",
        "better", "larger", "smaller", "bigger", "fewer", "more"
    ]
    # Question patterns requesting change
    change_questions = [
        "can we change", "could we change", "is it possible to change",
        "would it be possible", "can i change", "could i change",
        "what if we", "how about", "could you", "would you",
        "can we", "can you", "could we", "could you do"
    ]

    def has_change_intent(text: str) -> bool:
        """Check if text contains change intent signals."""
        return (
            any(verb in text for verb in change_verbs) or
            any(marker in text for marker in redefinition_markers) or
            any(comp in text for comp in comparative) or
            any(question in text for question in change_questions)
        )

    def keyword_present(text: str, keywords: List[str]) -> bool:
        for keyword in keywords:
            if " " in keyword:
                if keyword in text:
                    return True
            else:
                if re.search(rf"\b{re.escape(keyword)}\b", text):
                    return True
        return False

    # === DATE CHANGE ===
    # Pattern: confirmed date mentioned + change intent + new date value
    user_date = user_info.get("date") or user_info.get("event_date")
    if user_date and date_confirmed and chosen_date:
        # New value extraction is present
        if user_date != chosen_date:
            # Check for date mention + change intent in message
            date_keywords = ["date", "day", "when", chosen_date.replace(".", "/")]
            date_mentioned = any(keyword in text_lower for keyword in date_keywords)
            date_intent_near = has_change_intent_near_target(text_lower, change_verbs, date_keywords)

            if date_mentioned and (has_change_intent(text_lower) or date_intent_near):
                return ChangeType.DATE
            # Also fire if new date extracted without explicit intent (strong signal)
            elif date_mentioned:
                return ChangeType.DATE

    # === ROOM CHANGE ===
    # Pattern: room mentioned + change intent + new room value
    user_room = user_info.get("room") or user_info.get("preferred_room")
    if user_room and locked_room_id:
        if str(user_room).strip().lower() != str(locked_room_id).strip().lower():
            # Check for room mention + change intent
            room_keywords = ["room", "space", "venue", locked_room_id.lower()]
            room_mentioned = any(keyword in text_lower for keyword in room_keywords)
            room_intent_near = has_change_intent_near_target(text_lower, change_verbs, room_keywords)

            if room_mentioned and (has_change_intent(text_lower) or room_intent_near):
                return ChangeType.ROOM
            # Also fire if new room extracted (strong signal)
            elif room_mentioned:
                return ChangeType.ROOM
            # Fire if new room extracted + change intent, even without explicit room mention
            elif has_change_intent(text_lower) or room_intent_near:
                return ChangeType.ROOM

    # === REQUIREMENTS CHANGE ===
    # Pattern: requirement field mentioned + change intent + new value
    has_req_change = has_requirement_update(event_state, user_info)

    if has_req_change and locked_room_id:
        # Check for requirement mention + change intent
        req_keywords = ["people", "guests", "participants", "attendees", "capacity",
                        "layout", "setup", "time", "duration", "requirement"]
        req_mentioned = any(keyword in text_lower for keyword in req_keywords)
        req_intent_near = has_change_intent_near_target(text_lower, change_verbs, req_keywords)

        if req_mentioned and (has_change_intent(text_lower) or req_intent_near):
            return ChangeType.REQUIREMENTS
        # Also fire if new requirement extracted (strong signal)
        elif req_mentioned:
            return ChangeType.REQUIREMENTS
        # Fire if requirement field extracted + change intent, even without explicit mention
        elif has_change_intent(text_lower) or req_intent_near:
            return ChangeType.REQUIREMENTS

    # === PRODUCTS CHANGE ===
    # Pattern: product mentioned + change intent + new value
    has_product_change = has_product_update(user_info)

    if has_product_change and current_step >= 4:
        # Check for product mention + change intent (EXPANDED keywords)
        product_keywords = [
            "product", "catering", "menu", "food", "drink", "wine", "beverage",
            "coffee", "prosecco", "tea", "juice", "water", "snack", "breakfast",
            "lunch", "dinner", "appetizer", "dessert", "package", "setup",
            "add", "remove", "include", "upgrade", "premium", "deluxe", "standard"
        ]
        product_mentioned = any(keyword in text_lower for keyword in product_keywords)
        product_intent_near = has_change_intent_near_target(text_lower, change_verbs, product_keywords)

        if product_mentioned and product_intent_near:
            return ChangeType.PRODUCTS
        # Also fire if explicit add/remove in user_info (strong signal)
        elif user_info.get("products_add") or user_info.get("products_remove"):
            return ChangeType.PRODUCTS

    # === COMMERCIAL CHANGE ===
    # Pattern: price/commercial term mentioned + change intent (NOT just questions)
    if message_text and current_step >= 5:
        # EXPANDED keywords for commercial/pricing changes
        commercial_keywords = [
            "price", "discount", "cheaper", "negotiate", "budget",
            "cost", "expensive", "payment terms", "total", "amount",
            "rate", "fee", "charge", "pricing", "quote", "estimate",
            "reduce", "lower", "decrease", "increase", "adjust price",
            "financial", "affordability", "affordable", "value", "competitive"
        ]
        commercial_mentioned = keyword_present(text_lower, commercial_keywords)
        commercial_intent_near = has_change_intent_near_target(text_lower, change_verbs, commercial_keywords)

        # Check for currency mentions (CHF, EUR, USD, $, €, etc.) - strong price signal
        currency_patterns = ["chf", "eur", "usd", "$", "€", "£", "fr.", "francs"]
        has_currency = any(curr in text_lower for curr in currency_patterns)

        # ONLY fire if change intent is present (prevents "What's the price?" false positives)
        if commercial_mentioned and (has_change_intent(text_lower) or commercial_intent_near):
            return ChangeType.COMMERCIAL
        # Fire if currency + change intent (e.g., "Could you do CHF 3000?")
        elif has_currency and (has_change_intent(text_lower) or commercial_intent_near):
            return ChangeType.COMMERCIAL

        # Also check for explicit counter-offer language (EXPANDED)
        counter_signals = [
            "counter", "offer", "can you do", "would you accept",
            "how about", "what if we", "lower the", "reduce the",
            "meet us at", "work with", "budget is", "max we can do",
            "willing to pay", "comfortable with"
        ]
        if commercial_intent_near or any(signal in text_lower for signal in counter_signals):
            return ChangeType.COMMERCIAL

    # === DEPOSIT CHANGE ===
    # Pattern: deposit/reservation term mentioned + action intent (NOT just questions)
    if message_text and current_step >= 7:
        # EXPANDED keywords for deposit/payment
        deposit_keywords = [
            "deposit", "reservation", "reserve", "option", "hold",
            "payment", "invoice", "upfront", "prepayment", "advance payment",
            "down payment", "initial payment", "partial payment", "installment",
            "pay now", "settle", "transfer", "wire", "book", "booking"
        ]
        deposit_mentioned = any(keyword in text_lower for keyword in deposit_keywords)

        # ONLY fire if change intent OR action verbs present (prevents "When is deposit due?" false positives)
        action_verbs = [
            "want to", "would like to", "ready to", "proceed with",
            "let's", "i'll", "we'll", "confirm", "book", "finalize",
            "go ahead", "complete", "process", "submit", "send"
        ]
        has_action_intent = any(verb in text_lower for verb in action_verbs)

        if deposit_mentioned and (has_change_intent(text_lower) or has_action_intent):
            return ChangeType.DEPOSIT

    # === SITE VISIT CHANGE ===
    # Pattern: site visit mentioned + date/time change intent
    if message_text and current_step >= 7:
        site_visit_keywords = ["site visit", "visit", "tour", "walkthrough", "viewing", "see the space"]
        site_visit_mentioned = any(keyword in text_lower for keyword in site_visit_keywords)

        # Check for time/date patterns with site visit
        time_keywords = ["time", "when", "schedule", "appointment", "slot"]
        time_mentioned = any(keyword in text_lower for keyword in time_keywords)

        if site_visit_mentioned and (has_change_intent(text_lower) or time_mentioned):
            # Also check if user_info has extracted a new time/date for site visit
            if user_info.get("site_visit_time") or user_info.get("visit_date"):
                return ChangeType.SITE_VISIT
            # Or if change language is present with site visit mention
            elif site_visit_mentioned and has_change_intent(text_lower):
                return ChangeType.SITE_VISIT

    # === CLIENT INFO CHANGE ===
    # Pattern: billing/contact info mentioned + change intent + new value
    has_client_info_change = has_client_info_update(user_info)

    if has_client_info_change:
        # Check for client info mention + change intent
        client_info_keywords = ["address", "billing", "invoice", "company", "vat",
                                "phone", "email", "contact", "name"]
        client_info_mentioned = any(keyword in text_lower for keyword in client_info_keywords)

        if client_info_mentioned and has_change_intent(text_lower):
            return ChangeType.CLIENT_INFO
        # Also fire if new client info extracted (strong signal)
        elif client_info_mentioned:
            return ChangeType.CLIENT_INFO

    return None


def should_skip_step3_after_date_change(
    event_state: Dict[str, Any],
    new_date: str,
) -> bool:
    """
    Determine if Step 3 can be skipped after a date change.

    Per v4 rules: Skip Step 3 if the same room remains valid and was
    explicitly locked for the new date.

    Args:
        event_state: Event entry with locked_room_id, room_eval_hash
        new_date: New confirmed date

    Returns:
        True if Step 3 can be skipped, False otherwise

    NOTE: This is a conservative check. The actual availability check
    happens in Step 3's process function. This just provides a hint.
    """
    locked_room_id = event_state.get("locked_room_id")
    room_eval_hash = event_state.get("room_eval_hash")
    requirements_hash_val = event_state.get("requirements_hash")

    # If no room is locked, can't skip
    if not locked_room_id:
        return False

    # If hashes don't match, can't skip
    if not room_eval_hash or not requirements_hash_val:
        return False

    if str(room_eval_hash) != str(requirements_hash_val):
        return False

    # Conservative: Let Step 3 decide based on actual calendar availability
    # We return False here to force the check, but Step 3 can still fast-skip
    # if the room is actually available
    return False


def compute_offer_hash(offer_payload: Dict[str, Any]) -> str:
    """
    Compute a stable hash for an offer to detect when it changes.

    Args:
        offer_payload: Offer dict with products, pricing, totals

    Returns:
        SHA256 hash of the offer
    """
    from backend.workflows.common.requirements import stable_hash

    # Extract relevant fields for offer hash
    offer_subset = {
        "products": offer_payload.get("products"),
        "total": offer_payload.get("total"),
        "subtotal": offer_payload.get("subtotal"),
        "tax": offer_payload.get("tax"),
        "pricing": offer_payload.get("pricing"),
    }

    return stable_hash(offer_subset)


# ============================================================================
# ENHANCED DETECTION WITH DUAL-CONDITION LOGIC (V2)
# ============================================================================


def _map_target_to_change_type(target_type: Optional[str]) -> Optional[ChangeType]:
    """Map keyword bucket target type to ChangeType enum."""
    if target_type == "date":
        return ChangeType.DATE
    elif target_type == "room":
        return ChangeType.ROOM
    elif target_type == "requirements":
        return ChangeType.REQUIREMENTS
    elif target_type == "products":
        return ChangeType.PRODUCTS
    return None


def _extract_old_new_values(
    text: str,
    target_type: Optional[str],
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Extract old and new values from message and state.

    Returns:
        (old_value, new_value) tuple
    """
    old_value = None
    new_value = None

    if target_type == "date":
        old_value = event_state.get("chosen_date")
        new_value = user_info.get("date") or user_info.get("event_date")

    elif target_type == "room":
        old_value = event_state.get("locked_room_id")
        new_value = user_info.get("room") or user_info.get("preferred_room")

    elif target_type == "requirements":
        # For requirements, old_value is the current requirements dict
        old_value = event_state.get("requirements")
        # New value is extracted fields from user_info
        new_value = {}
        for field in ["participants", "number_of_participants", "layout", "seating_layout",
                      "start_time", "end_time", "special_requirements"]:
            if user_info.get(field):
                new_value[field] = user_info.get(field)
        if not new_value:
            new_value = None

    elif target_type == "products":
        old_value = event_state.get("selected_products")
        new_value = user_info.get("products") or user_info.get("products_add")

    return old_value, new_value


def _determine_detour_mode(
    old_value: Optional[Any],
    new_value: Optional[Any],
    text: str,
) -> DetourMode:
    """
    Determine which detour mode based on provided values.

    - LONG: No new value provided (need to ask)
    - FAST: New value provided (can validate and proceed)
    - EXPLICIT: Both old and new values mentioned in message
    """
    text_lower = text.lower()

    # Check for explicit old+new pattern - must mention BOTH values
    # Pattern: "from X to Y" or "instead of X, Y" or "not X but Y"
    explicit_patterns = [
        r"(instead\s+of|not)\s+\S+.*?(but|,)\s+\S+",  # "instead of X, Y"
        r"from\s+\d{1,2}[./\-]\d{1,2}.*?to\s+\d{1,2}[./\-]\d{1,2}",  # "from 21.02 to 28.02"
        r"from\s+\d{4}[./\-]\d{1,2}[./\-]\d{1,2}.*?to\s+\d{4}[./\-]\d{1,2}[./\-]\d{1,2}",  # ISO dates
    ]

    # Only count as EXPLICIT if old_value is actually mentioned in the text
    old_mentioned = False
    if old_value:
        old_str = str(old_value).lower()
        # Check if old value or its parts are in the text
        if old_str in text_lower:
            old_mentioned = True
        elif old_str.replace("-", ".") in text_lower:
            old_mentioned = True
        elif old_str.replace("-", "/") in text_lower:
            old_mentioned = True

    has_explicit = any(re.search(p, text_lower) for p in explicit_patterns)

    if has_explicit and old_mentioned and old_value and new_value:
        return DetourMode.EXPLICIT
    elif new_value:
        return DetourMode.FAST
    else:
        return DetourMode.LONG


def detect_change_type_enhanced(
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    message_text: Optional[str] = None,
) -> EnhancedChangeResult:
    """
    Enhanced change detection using dual-condition logic.

    A message triggers a detour ONLY when BOTH conditions are met:
    1. Has revision signal (change verb OR revision marker)
    2. Has bound target (explicit value OR anaphoric reference)

    This prevents false positives on pure Q&A questions.

    Args:
        event_state: Current event entry
        user_info: Extracted user information from message
        message_text: Client message text

    Returns:
        EnhancedChangeResult with full detection details

    Examples that trigger detour:
        - "Sorry, I meant 2026-02-28" -> DETOUR_DATE (fast)
        - "Can we change the room?" -> DETOUR_ROOM (long)
        - "Der 10. klappt doch nicht mehr" -> DETOUR_DATE (long, German)

    Examples that DON'T trigger (route to Q&A):
        - "What rooms are free in December?" -> GENERAL_QA
        - "Do you have parking?" -> GENERAL_QA
        - "What's the price?" -> GENERAL_QA
    """
    if not message_text:
        return EnhancedChangeResult(
            is_change=False,
            change_type=None,
            mode=None,
            confidence=0.0,
            alternative_intent=MessageIntent.UNCLEAR,
            revision_signals=[],
            target_matches=[],
            language="en",
        )

    # Use the comprehensive keyword bucket detection
    intent_result = compute_change_intent_score(message_text, event_state)

    # If no change intent detected, return early with alternative intent
    if not intent_result.has_change_intent:
        return EnhancedChangeResult(
            is_change=False,
            change_type=None,
            mode=None,
            confidence=intent_result.score,
            alternative_intent=intent_result.preliminary_intent,
            revision_signals=intent_result.revision_signals,
            target_matches=intent_result.target_matches,
            language=intent_result.language,
        )

    # Map target type to ChangeType
    change_type = _map_target_to_change_type(intent_result.target_type)

    # If we couldn't determine specific change type, try to infer from user_info
    if change_type is None:
        # Check what fields are present in user_info
        if user_info.get("date") or user_info.get("event_date"):
            change_type = ChangeType.DATE
        elif user_info.get("room") or user_info.get("preferred_room"):
            change_type = ChangeType.ROOM
        elif has_requirement_update(event_state, user_info):
            change_type = ChangeType.REQUIREMENTS
        elif has_product_update(user_info):
            change_type = ChangeType.PRODUCTS

    # Extract old/new values
    old_value, new_value = _extract_old_new_values(
        message_text,
        intent_result.target_type,
        event_state,
        user_info,
    )

    # Determine detour mode
    mode = _determine_detour_mode(old_value, new_value, message_text)

    # Validate that this is actually a change (not just mentioning same value)
    if old_value and new_value and str(old_value) == str(new_value):
        # Same value mentioned - not a real change
        return EnhancedChangeResult(
            is_change=False,
            change_type=None,
            mode=None,
            confidence=0.3,
            alternative_intent=MessageIntent.CONFIRMATION,
            revision_signals=intent_result.revision_signals,
            target_matches=intent_result.target_matches,
            language=intent_result.language,
            old_value=old_value,
            new_value=new_value,
        )

    return EnhancedChangeResult(
        is_change=True,
        change_type=change_type,
        mode=mode,
        confidence=intent_result.score,
        alternative_intent=None,
        revision_signals=intent_result.revision_signals,
        target_matches=intent_result.target_matches,
        language=intent_result.language,
        old_value=old_value,
        new_value=new_value,
    )


def detect_change_with_fallback(
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    message_text: Optional[str] = None,
) -> Tuple[Optional[ChangeType], EnhancedChangeResult]:
    """
    Wrapper that provides backward compatibility with detect_change_type
    while also returning enhanced result.

    Returns:
        (Optional[ChangeType], EnhancedChangeResult) - first value for backward compat,
        second value has full detection details
    """
    enhanced = detect_change_type_enhanced(event_state, user_info, message_text=message_text)

    if enhanced.is_change:
        return enhanced.change_type, enhanced
    return None, enhanced


# ============================================================================
# AMBIGUOUS TARGET RESOLUTION (when value provided without explicit type)
# ============================================================================

@dataclass
class AmbiguousTargetResult:
    """Result of ambiguous target resolution."""
    is_ambiguous: bool                      # True if multiple targets could match
    inferred_target: Optional[str]          # Best guess: "event_date", "site_visit_date", "room", etc.
    alternative_targets: List[str]          # Other possible targets
    confidence: float                       # 0.0-1.0
    inference_reason: str                   # Why we chose this target
    needs_disambiguation_message: bool      # Should we add clarification message?
    disambiguation_message: Optional[str]   # The message to append if ambiguous


# Value type patterns (detect type of value without explicit mention)
VALUE_TYPE_PATTERNS = {
    "date_value": [
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",  # ISO date: 2026-02-14
        r"\d{1,2}[-./]\d{1,2}[-./]\d{4}",  # DD.MM.YYYY
        r"\d{1,2}[-./]\d{1,2}\b",           # DD.MM
        r"\b(january|february|march|april|may|june|july|august|september|oktober|november|december)\s+\d{1,2}",
        r"\b\d{1,2}\s+(january|february|march|april|may|june|july|august|september|oktober|november|december)",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ],
    "time_value": [
        r"\d{1,2}:\d{2}",                   # 18:00
        r"\d{1,2}\s*(am|pm)\b",             # 6pm
    ],
    "room_value": [
        r"\broom\s+[a-z]\b",                # Room A
        r"\b(sky\s*loft|garden|terrace|punkt\.?\s*null)\b",
    ],
    "capacity_value": [
        r"\b\d+\s*(people|persons?|guests?|pax|attendees?)\b",
    ],
}


def _has_value_without_explicit_type(
    text: str,
    target_type: str,
) -> bool:
    """
    Check if text contains a value of the given type WITHOUT explicitly
    mentioning the type name.

    E.g., "change to 2026-02-14" has a date value but doesn't say "date".
    """
    text_lower = text.lower()

    # Check if value pattern matches
    patterns = VALUE_TYPE_PATTERNS.get(f"{target_type}_value", [])
    has_value = any(re.search(p, text_lower) for p in patterns)

    if not has_value:
        return False

    # Check if type is explicitly mentioned
    type_keywords = {
        "date": ["date", "day", "termin", "datum"],
        "time": ["time", "uhrzeit", "zeit"],
        "room": ["room", "space", "venue", "raum", "saal"],
    }

    keywords = type_keywords.get(target_type, [])
    type_mentioned = any(kw in text_lower for kw in keywords)

    return has_value and not type_mentioned


def _get_confirmed_variables_of_type(
    event_state: Dict[str, Any],
    value_type: str,
) -> List[Tuple[str, Any, Optional[int]]]:
    """
    Get all confirmed/captured variables of the given type.

    Returns:
        List of (variable_name, value, confirmation_step) tuples
    """
    results = []

    if value_type == "date":
        # Event date
        if event_state.get("date_confirmed") and event_state.get("chosen_date"):
            step = event_state.get("date_confirmed_at_step", 2)
            results.append(("event_date", event_state["chosen_date"], step))

        # Site visit date
        site_visit_date = event_state.get("site_visit_date")
        if site_visit_date:
            step = event_state.get("site_visit_confirmed_at_step", 7)
            results.append(("site_visit_date", site_visit_date, step))

    elif value_type == "room":
        # Locked room
        if event_state.get("locked_room_id"):
            step = event_state.get("room_confirmed_at_step", 3)
            results.append(("event_room", event_state["locked_room_id"], step))

        # Site visit room
        site_visit_room = event_state.get("site_visit_room")
        if site_visit_room:
            step = event_state.get("site_visit_room_at_step", 7)
            results.append(("site_visit_room", site_visit_room, step))

    return results


def _get_last_interaction_context(
    event_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get context about the last interaction to help disambiguate.

    Returns:
        Dict with:
        - last_step: int
        - last_qna_topic: Optional[str] (e.g., "event_date", "site_visit")
        - last_confirmed_variable: Optional[str]
    """
    context = {
        "last_step": event_state.get("current_step", 1),
        "last_qna_topic": None,
        "last_confirmed_variable": None,
    }

    # Check audit log for last Q&A topic
    audit_log = event_state.get("audit_log", [])
    if audit_log:
        last_entry = audit_log[-1] if isinstance(audit_log, list) else None
        if last_entry:
            action = last_entry.get("action", "")
            if "site_visit" in action.lower():
                context["last_qna_topic"] = "site_visit"
            elif "date" in action.lower():
                context["last_qna_topic"] = "event_date"
            elif "room" in action.lower():
                context["last_qna_topic"] = "room"

    return context


def resolve_ambiguous_target(
    event_state: Dict[str, Any],
    value_type: str,
    message_text: str,
) -> AmbiguousTargetResult:
    """
    Resolve which target the client means when they provide a value
    without explicitly mentioning the type.

    E.g., "change to 2026-02-14" - is it event date or site visit date?

    Resolution rules:
    1. If only ONE variable of that type exists → use it
    2. If MULTIPLE exist:
       a. Check if last step/Q&A was about one of them → use that
       b. Check recency (which was confirmed more recently) → use that
       c. If still ambiguous → needs clarification

    Args:
        event_state: Current event state
        value_type: Type of value detected ("date", "room", etc.)
        message_text: Original message text

    Returns:
        AmbiguousTargetResult with resolution details
    """
    confirmed = _get_confirmed_variables_of_type(event_state, value_type)

    # No confirmed variables of this type
    if not confirmed:
        return AmbiguousTargetResult(
            is_ambiguous=False,
            inferred_target=f"event_{value_type}",  # Default to event-level
            alternative_targets=[],
            confidence=0.8,
            inference_reason="no_confirmed_variables",
            needs_disambiguation_message=False,
            disambiguation_message=None,
        )

    # Only one variable of this type
    if len(confirmed) == 1:
        var_name, _, _ = confirmed[0]
        return AmbiguousTargetResult(
            is_ambiguous=False,
            inferred_target=var_name,
            alternative_targets=[],
            confidence=0.95,
            inference_reason="single_confirmed_variable",
            needs_disambiguation_message=False,
            disambiguation_message=None,
        )

    # Multiple variables - need to disambiguate
    context = _get_last_interaction_context(event_state)
    current_step = context["last_step"]

    # Rule 2a: Check if last Q&A/step was about one of them
    if context["last_qna_topic"]:
        for var_name, _, _ in confirmed:
            if context["last_qna_topic"] in var_name:
                alt_targets = [v[0] for v in confirmed if v[0] != var_name]
                return AmbiguousTargetResult(
                    is_ambiguous=True,
                    inferred_target=var_name,
                    alternative_targets=alt_targets,
                    confidence=0.75,
                    inference_reason=f"last_qna_topic_was_{context['last_qna_topic']}",
                    needs_disambiguation_message=True,
                    disambiguation_message=_build_disambiguation_message(var_name, alt_targets),
                )

    # Rule 2b: Check recency (which step was more recent)
    # Sort by step number (higher = more recent)
    sorted_confirmed = sorted(confirmed, key=lambda x: x[2] or 0, reverse=True)
    most_recent = sorted_confirmed[0]

    var_name, _, step = most_recent
    alt_targets = [v[0] for v in sorted_confirmed[1:]]

    # Check step distance
    step_distance_to_most_recent = abs(current_step - (step or 0))
    step_distance_to_second = abs(current_step - (sorted_confirmed[1][2] or 0)) if len(sorted_confirmed) > 1 else 999

    # If most recent is clearly closer, use it with disambiguation message
    if step_distance_to_most_recent < step_distance_to_second:
        return AmbiguousTargetResult(
            is_ambiguous=True,
            inferred_target=var_name,
            alternative_targets=alt_targets,
            confidence=0.7,
            inference_reason=f"most_recent_confirmed_at_step_{step}",
            needs_disambiguation_message=True,
            disambiguation_message=_build_disambiguation_message(var_name, alt_targets),
        )

    # Truly ambiguous - ask for clarification
    return AmbiguousTargetResult(
        is_ambiguous=True,
        inferred_target=None,
        alternative_targets=[v[0] for v in confirmed],
        confidence=0.3,
        inference_reason="equally_recent_need_clarification",
        needs_disambiguation_message=True,
        disambiguation_message=_build_clarification_request(value_type, [v[0] for v in confirmed]),
    )


def _build_disambiguation_message(
    inferred_target: str,
    alternative_targets: List[str],
) -> str:
    """
    Build a message to append when we've made an inference but alternatives exist.

    E.g., "If you meant site visit date, please write 'change site visit date'
           and this change will be cancelled."
    """
    if not alternative_targets:
        return ""

    # Map internal names to user-friendly names
    friendly_names = {
        "event_date": "event date",
        "site_visit_date": "site visit date",
        "event_room": "event room",
        "site_visit_room": "site visit room",
    }

    alt_name = friendly_names.get(alternative_targets[0], alternative_targets[0].replace("_", " "))

    return (
        f"\n\n---\n"
        f"If you meant the **{alt_name}** instead, please write "
        f"'change {alt_name}' and this update will be cancelled."
    )


def _build_clarification_request(
    value_type: str,
    options: List[str],
) -> str:
    """
    Build a message asking for clarification when we can't infer.
    """
    friendly_names = {
        "event_date": "event date",
        "site_visit_date": "site visit date",
        "event_room": "event room",
        "site_visit_room": "site visit room",
    }

    options_text = " or ".join([friendly_names.get(o, o.replace("_", " ")) for o in options])

    return (
        f"I noticed you want to change a {value_type}, but I'm not sure which one. "
        f"Could you please clarify if you mean the **{options_text}**?"
    )


def detect_change_type_enhanced_with_disambiguation(
    event_state: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    message_text: Optional[str] = None,
) -> Tuple[EnhancedChangeResult, Optional[AmbiguousTargetResult]]:
    """
    Enhanced change detection with ambiguous target resolution.

    When a client provides a value without explicitly mentioning the type
    (e.g., "change to 2026-02-14" without saying "date"), this function
    resolves which variable they likely mean.

    Returns:
        (EnhancedChangeResult, Optional[AmbiguousTargetResult])
        - AmbiguousTargetResult is populated when disambiguation was needed
    """
    enhanced = detect_change_type_enhanced(event_state, user_info, message_text=message_text)

    if not enhanced.is_change:
        return enhanced, None

    # Check if target type was explicitly mentioned
    if message_text and enhanced.target_matches:
        # If we matched explicit type keywords (not just values), no disambiguation needed
        explicit_type_patterns = [
            r"\b(date|day|termin|datum)\b",
            r"\b(room|space|venue|raum|saal)\b",
            r"\b(site\s+visit|besichtigung)\b",
        ]
        text_lower = message_text.lower()
        has_explicit_type = any(re.search(p, text_lower) for p in explicit_type_patterns)

        if has_explicit_type:
            return enhanced, None

    # Check for implicit target (value without type)
    if message_text:
        for value_type in ["date", "room"]:
            if _has_value_without_explicit_type(message_text, value_type):
                disambiguation = resolve_ambiguous_target(event_state, value_type, message_text)

                if disambiguation.is_ambiguous:
                    return enhanced, disambiguation

    return enhanced, None
