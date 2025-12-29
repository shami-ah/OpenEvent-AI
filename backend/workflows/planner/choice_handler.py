"""
Smart Shortcuts - Choice Handler.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles choice selection flows for the shortcuts planner:
- Choice context loading and validation (TTL-based)
- Choice selection parsing (ordinal, label, fuzzy matching)
- Choice confirmation and application
- Clarification prompts for ambiguous selections

Usage:
    from .choice_handler import (
        load_choice_context, maybe_handle_choice_context_reply,
        parse_choice_selection, apply_choice_selection,
    )
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .shortcuts_types import (
    PlannerResult,
    _CLASS_KEYWORDS,
    _ORDINAL_WORDS_BY_LANG,
)

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner


# --------------------------------------------------------------------------
# Choice context management
# --------------------------------------------------------------------------


def load_choice_context(planner: "_ShortcutPlanner") -> Optional[Dict[str, Any]]:
    """Load and validate choice context from event.

    Manages TTL-based expiry: decrements ttl_turns on each access,
    clears context when TTL reaches zero.

    Args:
        planner: The shortcuts planner instance

    Returns:
        The active choice context dict, or None if expired/missing
    """
    context = planner.event.get("choice_context")
    if not context:
        planner.telemetry.choice_context_active = False
        return None

    ttl = context.get("ttl_turns")
    try:
        ttl_value = int(ttl)
    except (TypeError, ValueError):
        ttl_value = 0

    if ttl_value <= 0:
        planner.event["choice_context"] = None
        planner.state.extras["persist"] = True
        planner.telemetry.choice_context_active = False
        planner.telemetry.re_prompt_reason = "expired"
        kind = context.get("kind")
        if kind:
            planner.preview_requests.append((kind, 0))
        return None

    refreshed = dict(context)
    refreshed["ttl_turns"] = ttl_value - 1
    planner.event["choice_context"] = refreshed
    planner.state.extras["persist"] = True
    planner.telemetry.choice_context_active = True
    return refreshed


# --------------------------------------------------------------------------
# Choice selection parsing
# --------------------------------------------------------------------------


def parse_choice_selection(
    planner: "_ShortcutPlanner",
    context: Dict[str, Any],
    text: str,
) -> Optional[Dict[str, Any]]:
    """Parse a choice selection from user text.

    Attempts to match user input to a choice item using:
    1. Ordinal matching (1, 2, 3 or "option 1")
    2. Language-specific ordinal words ("first", "zweite")
    3. Direct label matching
    4. Fuzzy label matching (>= 0.8 similarity)

    Args:
        planner: The shortcuts planner instance
        context: The active choice context
        text: User's message text

    Returns:
        Selection dict with 'item' and 'method', or None if no match
    """
    if not text:
        return None

    normalized = text.strip().lower()
    items = context.get("items") or []
    if not items:
        return None

    idx_map = {int(item.get("idx")): item for item in items if item.get("idx") is not None}

    # Try ordinal matching (e.g., "1", "#2", "3")
    ordinal_match = re.search(r"(?:^|\s)#?(\d{1,2})\b", normalized)
    if ordinal_match:
        try:
            idx = int(ordinal_match.group(1))
            if idx in idx_map:
                return {"item": idx_map[idx], "method": "ordinal"}
        except ValueError:
            pass

    # Try "option N" matching
    option_match = re.search(r"option\s+(\d{1,2})", normalized)
    if option_match:
        try:
            idx = int(option_match.group(1))
            if idx in idx_map:
                return {"item": idx_map[idx], "method": "ordinal"}
        except ValueError:
            pass

    # Try language-specific ordinal words
    lang = str(context.get("lang") or "en").split("-")[0].lower()
    ordinal_words = _ORDINAL_WORDS_BY_LANG.get(lang, {})
    fallback_words = _ORDINAL_WORDS_BY_LANG.get("en", {})
    for raw_token in normalized.replace(".", " ").split():
        token = raw_token.strip()
        mapped = ordinal_words.get(token) or fallback_words.get(token)
        if mapped and mapped in idx_map:
            return {"item": idx_map[mapped], "method": "ordinal"}

    # Try direct label matching
    direct_matches = []
    for item in items:
        label = str(item.get("label") or "").lower()
        if label and label in normalized:
            direct_matches.append(item)
    if len(direct_matches) == 1:
        return {"item": direct_matches[0], "method": "label"}
    if len(direct_matches) > 1:
        return None  # Ambiguous

    # Try fuzzy matching
    similarity: List[Tuple[float, Dict[str, Any]]] = []
    for item in items:
        label = str(item.get("label") or "").lower()
        if not label:
            continue
        ratio = SequenceMatcher(a=label, b=normalized).ratio()
        similarity.append((ratio, item))

    if not similarity:
        return None

    similarity.sort(key=lambda pair: pair[0], reverse=True)
    best_ratio, best_item = similarity[0]
    second_ratio = similarity[1][0] if len(similarity) > 1 else 0.0

    # Treat as ambiguous if multiple close matches score similarly high
    if len(similarity) > 1 and best_ratio >= 0.5 and second_ratio >= 0.5 and abs(best_ratio - second_ratio) < 0.08:
        return None

    if best_ratio >= 0.8:
        return {"item": best_item, "method": "fuzzy"}

    return None


def choice_clarification_prompt(
    planner: "_ShortcutPlanner",
    context: Dict[str, Any],
    text: str,
) -> Optional[str]:
    """Generate a clarification prompt for ambiguous selections.

    When user input partially matches multiple options, generates a
    "Do you mean X?" prompt for the best match.

    Args:
        planner: The shortcuts planner instance
        context: The active choice context
        text: User's message text

    Returns:
        Clarification prompt string, or None if not needed
    """
    items = context.get("items") or []
    if not items:
        return None

    normalized = text.strip().lower()
    similarity: List[Tuple[float, Dict[str, Any]]] = []

    for item in items:
        label = str(item.get("label") or "").lower()
        if not label:
            continue
        ratio = SequenceMatcher(a=label, b=normalized).ratio()
        similarity.append((ratio, item))

    if not similarity:
        return None

    similarity.sort(key=lambda pair: pair[0], reverse=True)
    top_ratio, top_item = similarity[0]
    second_ratio = similarity[1][0] if len(similarity) > 1 else 0.0

    if top_ratio < 0.5:
        return None

    if len(similarity) > 1 and second_ratio >= 0.5 and abs(top_ratio - second_ratio) < 0.08:
        ambiguous_items = [item for ratio, item in similarity if abs(top_ratio - ratio) < 0.08]
        if ambiguous_items:
            chosen = min(ambiguous_items, key=lambda entry: entry.get("idx") or 0)
        else:
            chosen = top_item
        display = format_choice_item(planner, chosen)
        return f"Do you mean {display}?"

    return None


def format_choice_item(planner: "_ShortcutPlanner", item: Dict[str, Any]) -> str:
    """Format a choice item for display.

    Args:
        planner: The shortcuts planner instance
        item: Choice item dict with label/value/idx

    Returns:
        Formatted string like "1) Champagne" or just "Champagne"
    """
    label = item.get("label") or (item.get("value") or {}).get("name") or "this option"
    idx = item.get("idx")
    if idx is not None:
        return f"{idx}) {label}"
    return label


# --------------------------------------------------------------------------
# Choice selection application
# --------------------------------------------------------------------------


def apply_choice_selection(
    planner: "_ShortcutPlanner",
    context: Dict[str, Any],
    selection: Dict[str, Any],
) -> None:
    """Apply a choice selection to the planner state.

    Updates products, presented_interest, and telemetry.

    Args:
        planner: The shortcuts planner instance
        context: The active choice context
        selection: Selection dict with 'item' and 'method'
    """
    item = selection.get("item") or {}
    value = item.get("value") or {}
    class_name = context.get("kind") or value.get("class") or "catering"
    product_name = value.get("name") or item.get("label")

    if not product_name:
        return

    addition: Dict[str, Any] = {
        "name": product_name,
        "quantity": value.get("quantity") or value.get("meta", {}).get("quantity") or 1,
    }
    unit_price = value.get("unit_price") or value.get("meta", {}).get("unit_price")
    if unit_price is not None:
        try:
            addition["unit_price"] = float(unit_price)
        except (TypeError, ValueError):
            pass

    planner._apply_product_add([addition])
    planner.presented_interest[class_name] = "interested"
    planner.preask_pending_state[class_name] = False
    planner.telemetry.selection_method = selection.get("method") or "label"
    planner.telemetry.preask_response[class_name] = planner.telemetry.preask_response.get(class_name, "n/a")


def complete_choice_selection(
    planner: "_ShortcutPlanner",
    context: Dict[str, Any],
    selection: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Complete a choice selection with confirmation message.

    Applies the selection and returns confirmation text with state delta.

    Args:
        planner: The shortcuts planner instance
        context: The active choice context
        selection: Selection dict with 'item' and 'method'

    Returns:
        Tuple of (confirmation_message, state_delta_dict)
    """
    item = selection.get("item") or {}
    raw_value = dict(item.get("value") or {})
    class_name = (context.get("kind") or raw_value.get("class") or "product").lower()
    idx = item.get("idx")

    manager_items = planner.manager_items_by_class.get(class_name, [])
    if isinstance(idx, int) and 1 <= idx <= len(manager_items):
        value = dict(manager_items[idx - 1] or {})
    else:
        value = raw_value

    label = item.get("label") or value.get("name") or "this option"

    addition: Dict[str, Any] = {"name": value.get("name") or label}
    quantity = value.get("quantity") or (value.get("meta") or {}).get("quantity")
    if quantity is not None:
        try:
            addition["quantity"] = max(1, int(quantity))
        except (TypeError, ValueError):
            addition["quantity"] = 1
    else:
        addition["quantity"] = 1

    unit_price = value.get("unit_price")
    if unit_price is None:
        unit_price = (value.get("meta") or {}).get("unit_price")
    if unit_price is not None:
        try:
            addition["unit_price"] = float(unit_price)
        except (TypeError, ValueError):
            pass

    if class_name in {"catering", "av", "furniture", "product"}:
        planner._apply_product_add([addition])
        planner.telemetry.combined_confirmation = True

    planner.presented_interest[class_name] = "interested"
    planner.preask_pending_state[class_name] = False
    planner.telemetry.preask_response[class_name] = planner.telemetry.preask_response.get(class_name, "yes")
    planner.choice_context = None
    planner.event["choice_context"] = None
    planner.state.extras["persist"] = True

    confirmation = f"Got it, I'll add {label}."
    state_delta = {
        "choice_context": {
            "kind": class_name,
            "selected": {
                "label": label,
                "idx": item.get("idx"),
                "key": item.get("key"),
            },
        }
    }
    return confirmation, state_delta


# --------------------------------------------------------------------------
# Choice context reply handling
# --------------------------------------------------------------------------


def handle_choice_selection(planner: "_ShortcutPlanner", text: str) -> None:
    """Handle choice selection from user text.

    Processes "show more" requests or parses selection from text.

    Args:
        planner: The shortcuts planner instance
        text: User's message text (lowercase)
    """
    if not planner.choice_context:
        return

    if "show more" in text and planner.choice_context.get("kind"):
        next_offset = planner.choice_context.get("next_offset", len(planner.choice_context.get("items") or []))
        planner.preview_requests.append((planner.choice_context.get("kind"), next_offset))
        return

    selection = parse_choice_selection(planner, planner.choice_context, text)
    if not selection:
        class_name = planner.choice_context.get("kind")
        if class_name:
            keywords = set(_CLASS_KEYWORDS.get(class_name, set())) | {class_name}
            if any(keyword in text for keyword in keywords):
                if class_name not in planner.preask_clarifications:
                    planner.preask_clarifications.append(class_name)
                planner.preask_pending_state[class_name] = True
                planner.telemetry.re_prompt_reason = "ambiguous"
                planner.telemetry.preask_response[class_name] = "clarify"
        return

    apply_choice_selection(planner, planner.choice_context, selection)
    planner.choice_context = None
    planner.event["choice_context"] = None
    planner.state.extras["persist"] = True
    planner.telemetry.choice_context_active = False


def maybe_handle_choice_context_reply(planner: "_ShortcutPlanner") -> Optional[PlannerResult]:
    """Handle a reply when choice context is active.

    Attempts to parse selection or generate clarification prompt.

    Args:
        planner: The shortcuts planner instance

    Returns:
        PlannerResult if handled, None otherwise
    """
    context = planner.choice_context
    if not context:
        return None

    message_text = (planner.state.message.body or "").strip()
    if not message_text:
        return None

    selection = parse_choice_selection(planner, context, message_text)
    if selection:
        confirmation, state_delta = complete_choice_selection(planner, context, selection)
        planner._choice_context_handled = True
        planner.telemetry.selection_method = selection.get("method") or "label"
        planner.telemetry.re_prompt_reason = "none"
        planner.telemetry.choice_context_active = False
        return planner._build_payload(confirmation, state_delta=state_delta)

    clarification = choice_clarification_prompt(planner, context, message_text)
    if clarification:
        planner._choice_context_handled = True
        planner.telemetry.selection_method = "clarified"
        planner.telemetry.re_prompt_reason = "ambiguous"
        kind = context.get("kind")
        if kind:
            planner.telemetry.preask_response[kind] = "clarify"
        planner.telemetry.choice_context_active = True
        return planner._build_payload(clarification)

    return None


__all__ = [
    # Context management
    "load_choice_context",
    # Selection parsing
    "parse_choice_selection",
    "choice_clarification_prompt",
    "format_choice_item",
    # Selection application
    "apply_choice_selection",
    "complete_choice_selection",
    # Reply handling
    "handle_choice_selection",
    "maybe_handle_choice_context_reply",
]