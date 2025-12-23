"""
MODULE: backend/detection/qna/sequential_workflow.py
PURPOSE: Detect when a client combines current step action + next step inquiry.

This is NOT a shortcut or Q&A - it's natural workflow continuation.
When a client confirms the current step AND asks about the next step,
they're simply anticipating the natural flow.

DEPENDS ON:
    - (none - self-contained regex patterns)

USED BY:
    - backend/workflows/steps/step2_date_confirmation/
    - backend/workflows/steps/step3_room_availability/
    - backend/workflows/steps/step4_offer/

EXPORTS:
    - detect_sequential_workflow_request(message, current_step) -> Dict

Examples:
    - Step 2→3: "Confirm May 8 and show me available rooms"
    - Step 3→4: "Room A looks good, what catering options do you have?"
    - Step 4→5/7: "Accept the offer, when can we do a site visit?"

RELATED TESTS:
    - backend/tests/detection/test_sequential_workflow.py

MIGRATION NOTE:
    This file was moved from backend/workflows/nlu/sequential_workflow.py
    Old import: from backend.workflows.nlu.sequential_workflow import ...
    New import: from backend.detection.qna.sequential_workflow import ...
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def _normalise_text(message: str) -> str:
    """Normalize text for pattern matching."""
    return re.sub(r"\s+", " ", (message or "").strip().lower())


# =========================================================================
# Step Action Patterns
# =========================================================================
# Patterns that indicate action/confirmation for each step
_STEP_ACTION_PATTERNS: Dict[int, Tuple[str, ...]] = {
    2: (
        # Date confirmation patterns
        r"\bconfirm\b.*\b(?:date|may|june|july|august|september|october|november|december|january|february|march|april|\d{1,2}[./-])",
        r"\bconfirm\s+(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\b",  # "confirm the 8th"
        r"\bbook\b.*\b(?:for|on)\b",
        r"\bgo\s+(?:with|for|ahead)\b.*\b(?:date|\d{1,2})",
        r"\bproceed\s+with\b.*\b(?:date|\d{1,2})",
        r"\byes\b.*\b(?:date|works|good|perfect|fine)\b",
        r"\b(?:that|this)\s+(?:date\s+)?(?:works|is\s+(?:good|fine|perfect))\b",
        r"\blet'?s?\s+(?:go|book|proceed)\b",
        r"\b(?:we'?ll?|i'?ll?|let's)\s+(?:take|book|go\s+with)\b",
        r"\bplease\s+(?:confirm|book|reserve)\b",
    ),
    3: (
        # Room selection patterns
        r"\b(?:room\s+)?[abce]\b.*\b(?:works|looks\s+good|is\s+(?:good|fine|perfect))\b",
        r"\bproceed\s+with\s+(?:room\s+)?[abce]\b",
        r"\bbook\s+(?:room\s+)?[abce]\b",
        r"\bgo\s+(?:with|for)\s+(?:room\s+)?[abce]\b",
        r"\bconfirm\s+(?:room\s+)?[abce]\b",
        r"\bchoose\s+(?:room\s+)?[abce]\b",
        r"\bselect\s+(?:room\s+)?[abce]\b",
        r"\b(?:we'?ll?|i'?ll?|let's)\s+(?:take|book)\s+(?:room\s+)?[abce]\b",
        r"\bpunkt[\s.]?null\b.*\b(?:works|good|fine|perfect)\b",
    ),
    4: (
        # Offer acceptance patterns
        r"\baccept\s+(?:the\s+)?(?:offer|quote|proposal)\b",
        r"\bapprove\s+(?:the\s+)?(?:offer|quote|proposal)\b",
        r"\bgo\s+ahead\s+(?:with\s+)?(?:the\s+)?(?:offer|quote)\b",
        r"\bproceed\s+(?:with\s+)?(?:the\s+)?(?:offer|quote)\b",
        r"\b(?:offer|quote|proposal)\s+(?:looks\s+)?(?:good|fine|ok|okay|great)\b",
        r"\bfinali[sz]e\s+(?:the\s+)?(?:offer|booking)\b",
        # Note: "send the contract" is NOT included here - it's a standalone action, not acceptance
    ),
}

# =========================================================================
# Next Step Mention Patterns
# =========================================================================
# Patterns that indicate asking about the next step
_NEXT_STEP_MENTIONS: Dict[int, Tuple[str, ...]] = {
    3: (
        # Asking about rooms (next after date confirmation)
        r"\bshow\b.*\b(?:rooms?|availability|space|venues?)\b",
        r"\bwhat\b.*\b(?:rooms?|space|venues?)\b",
        r"\bwhich\b.*\b(?:rooms?|space)\b",
        r"\brooms?\s+(?:available|free|options?)\b",
        r"\bavailable\s+(?:rooms?|space|venues?)\b",
        r"\brecommend\b.*\b(?:rooms?|space)\b",
        r"\bsuitable\s+(?:rooms?|space)\b",
        r"\broom\s+(?:options?|choices?|availability)\b",
    ),
    4: (
        # Asking about catering/offer (next after room selection)
        r"\bwhat\b.*\b(?:catering|menu|package|offer|price|cost)\b",
        r"\bshow\b.*\b(?:catering|menu|package|offer)\b",
        r"\b(?:catering|menu|package)\s+(?:options?|choices?)\b",
        r"\bhow\s+much\b",
        r"\bthe\s+price[s]?\b",
        r"\bwhat\b.*\bprice\b",
        r"\bsend\b.*\b(?:the\s+)?offer\b",  # "send the offer" is asking about the next step
    ),
    5: (
        # Asking about negotiation/next steps (next after offer)
        r"\bwhat'?s?\s+next\b",
        r"\bnext\s+step[s]?\b",
        r"\bdeposit\b",
        r"\bpayment\b",
        r"\bsend\s+(?:the\s+)?contract\b",  # "send the contract" = next step after offer
        r"\bcontract\b",  # just "contract" alone
        # Note: "site_visit" moved to step 7 for clearer priority
    ),
    7: (
        # Asking about confirmation/site visit (final steps)
        # Check step 7 patterns FIRST (site visit is more specific)
        r"\bsite\s+visit\b",
        r"\bvisit\s+(?:the\s+)?venue\b",
        r"\bwhen\s+(?:can|could)\s+(?:we|i)\b.*\b(?:visit|come|see)\b",
        r"\btour\b",
    ),
}


def detect_sequential_workflow_request(
    message: str,
    current_step: int,
) -> Dict[str, Any]:
    """
    Detect if message combines current step action + next step inquiry.

    This is NOT a shortcut or Q&A - it's natural workflow continuation.
    When a client confirms the current step AND asks about the next step,
    they're simply anticipating the natural flow.

    Args:
        message: The message text to analyze
        current_step: The current workflow step number (2-7)

    Returns:
        Dict with:
        - has_current_step_action: bool - True if message has action for current step
        - asks_next_step: int | None - Next step number if asking about it
        - is_sequential: bool - True if both action + lookahead detected
    """
    normalized = _normalise_text(message)

    result: Dict[str, Any] = {
        "has_current_step_action": False,
        "asks_next_step": None,
        "is_sequential": False,
    }

    if not normalized:
        return result

    # Check for current step action
    action_patterns = _STEP_ACTION_PATTERNS.get(current_step, ())
    has_action = any(re.search(pattern, normalized) for pattern in action_patterns)
    result["has_current_step_action"] = has_action

    # Check for next step mentions
    next_step = current_step + 1
    # Skip step 5 and 6 for standard flow (date->room->offer->negotiation/confirmation)
    if current_step == 4:
        # After offer, next could be negotiation (5) or confirmation (7)
        # Check step 7 FIRST because site visit is more specific than general "next steps"
        for check_step in (7, 5):
            mention_patterns = _NEXT_STEP_MENTIONS.get(check_step, ())
            if any(re.search(pattern, normalized) for pattern in mention_patterns):
                result["asks_next_step"] = check_step
                break
    else:
        mention_patterns = _NEXT_STEP_MENTIONS.get(next_step, ())
        if any(re.search(pattern, normalized) for pattern in mention_patterns):
            result["asks_next_step"] = next_step

    # Sequential if both action and lookahead detected
    result["is_sequential"] = result["has_current_step_action"] and result["asks_next_step"] is not None

    return result


__all__ = ["detect_sequential_workflow_request"]
