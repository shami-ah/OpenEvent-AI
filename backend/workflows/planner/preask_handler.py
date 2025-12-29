"""
Smart Shortcuts - Preask Handler.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles preask flows for the shortcuts planner:
- Preask feature enablement and configuration
- Preask prompt generation
- Preask response handling (yes/no/clarify)
- Preview building and hydration
- Menu preview functionality

Usage:
    from .preask_handler import (
        preask_feature_enabled, process_preask,
        handle_preask_responses, finalize_preask_state,
    )
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .shortcuts_flags import (
    _event_scoped_upsell_enabled,
    _no_unsolicited_menus,
)
from .shortcuts_types import (
    PlannerResult,
    _CLASS_KEYWORDS,
    _PREASK_CLASS_COPY,
)
from .choice_handler import handle_choice_selection

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner


# --------------------------------------------------------------------------
# Preask feature control
# --------------------------------------------------------------------------


def preask_feature_enabled(planner: "_ShortcutPlanner") -> bool:
    """Check if preask feature is enabled for this planner.

    Requires:
    - Event-scoped upsell enabled
    - No unsolicited menus flag set
    - Manager items available by class

    Args:
        planner: The shortcuts planner instance

    Returns:
        True if preask is enabled
    """
    return (
        _event_scoped_upsell_enabled()
        and _no_unsolicited_menus()
        and bool(planner.manager_items_by_class)
    )


# --------------------------------------------------------------------------
# Menu preview
# --------------------------------------------------------------------------


def menu_preview_lines(planner: "_ShortcutPlanner") -> Optional[List[str]]:
    """Generate menu preview lines from catering names.

    Args:
        planner: The shortcuts planner instance

    Returns:
        List of preview lines, or None if no names available
    """
    # Import here to avoid circular import at module level
    from .product_handler import load_catering_names

    names = load_catering_names()
    if not names:
        return ["Catering menus will be available once the manager shares the current list."]
    preview = ", ".join(names[:3])
    if len(names) > 3:
        preview += ", ..."
    return [f"Catering menus: {preview}"]


def explicit_menu_requested(planner: "_ShortcutPlanner") -> bool:
    """Check if user explicitly requested a menu.

    Args:
        planner: The shortcuts planner instance

    Returns:
        True if menu-related keywords found in message
    """
    text = f"{planner.state.message.subject or ''}\n{planner.state.message.body or ''}".lower()
    keywords = (
        "menu",
        "menus",
        "catering menu",
        "catering options",
        "food options",
    )
    return any(keyword in text for keyword in keywords)


# --------------------------------------------------------------------------
# Preask processing
# --------------------------------------------------------------------------


def process_preask(planner: "_ShortcutPlanner") -> None:
    """Main preask processing entry point.

    Initializes telemetry, handles choice selection, processes responses,
    and prepares previews.

    Args:
        planner: The shortcuts planner instance
    """
    planner.telemetry.preask_candidates = []
    planner.telemetry.preask_shown = []
    planner.telemetry.preview_class_shown = "none"
    planner.telemetry.preview_items_count = 0
    planner.telemetry.re_prompt_reason = "none"
    planner.telemetry.selection_method = "none"
    planner.telemetry.choice_context_active = bool(planner.choice_context)

    if not preask_feature_enabled(planner):
        return

    for class_name, status in (planner.presented_interest or {}).items():
        if status == "interested":
            planner.telemetry.preask_response.setdefault(class_name, "yes")
        elif status == "declined":
            planner.telemetry.preask_response.setdefault(class_name, "no")
        else:
            planner.telemetry.preask_response.setdefault(class_name, "n/a")

    message_text = (planner.state.message.body or "").strip().lower()
    if not planner._choice_context_handled:
        handle_choice_selection(planner, message_text)
    handle_preask_responses(planner, message_text)
    prepare_preview_for_requests(planner)
    hydrate_preview_from_context(planner)


def maybe_emit_preask_prompt_only(planner: "_ShortcutPlanner") -> Optional[PlannerResult]:
    """Emit preask prompt if no other content to send.

    Args:
        planner: The shortcuts planner instance

    Returns:
        PlannerResult with preask prompt, or None if not applicable
    """
    if not preask_feature_enabled(planner):
        return None
    lines = maybe_preask_lines(planner)
    if not lines:
        return None
    message = "\n".join(lines).strip()
    return planner._build_payload(message or "\u200b")


# --------------------------------------------------------------------------
# Preask response handling
# --------------------------------------------------------------------------


def handle_preask_responses(planner: "_ShortcutPlanner", text: str) -> None:
    """Handle preask responses (yes/no/clarify/show_more).

    Args:
        planner: The shortcuts planner instance
        text: User's message text (lowercase)
    """
    if not text:
        return

    pending_classes = [cls for cls, flag in planner.preask_pending_state.items() if flag]

    for class_name in pending_classes:
        response = detect_preask_response(planner, class_name, text)
        if not response:
            continue

        if response == "yes":
            planner.presented_interest[class_name] = "interested"
            planner.preask_pending_state[class_name] = False
            planner.preview_requests.append((class_name, 0))
            planner.telemetry.preask_response[class_name] = "yes"
            planner.telemetry.re_prompt_reason = "none"
        elif response == "no":
            planner.presented_interest[class_name] = "declined"
            planner.preask_pending_state[class_name] = False
            planner.telemetry.preask_response[class_name] = "no"
            planner.telemetry.re_prompt_reason = "none"
            planner.preask_ack_lines.append(f"Noted, I'll skip {class_name} options for now.")
        elif response == "clarify":
            if class_name not in planner.preask_clarifications:
                planner.preask_clarifications.append(class_name)
            planner.telemetry.preask_response[class_name] = "clarify"
            planner.telemetry.re_prompt_reason = "ambiguous"
        elif response == "show_more":
            next_offset = 0
            if planner.choice_context and planner.choice_context.get("kind") == class_name:
                next_offset = planner.choice_context.get("next_offset", len(planner.choice_context.get("items") or []))
            planner.preview_requests.append((class_name, next_offset))

        if response in {"yes", "no"} and class_name in planner.preask_clarifications:
            planner.preask_clarifications.remove(class_name)


def detect_preask_response(
    planner: "_ShortcutPlanner",
    class_name: str,
    text: str,
) -> Optional[str]:
    """Detect preask response type from user text.

    Args:
        planner: The shortcuts planner instance
        class_name: The add-on class being asked about
        text: User's message text (lowercase)

    Returns:
        Response type: "yes", "no", "clarify", "show_more", or None
    """
    keywords = set(_CLASS_KEYWORDS.get(class_name, set())) | {class_name}
    has_keyword = any(keyword in text for keyword in keywords)
    single_pending = single_pending_class(planner, class_name)

    if "show more" in text and planner.choice_context and planner.choice_context.get("kind") == class_name:
        return "show_more"

    affirmatives = ["yes", "sure", "ok", "okay", "definitely", "sounds good", "go ahead"]
    negatives = ["no", "not now", "later", "skip", "nope", "don't"]

    if any(token in text for token in negatives) and (has_keyword or single_pending):
        return "no"
    if any(token in text for token in affirmatives) and (has_keyword or single_pending):
        return "yes"
    if has_keyword and ("?" in text or "which" in text or "what" in text):
        return "clarify"

    return None


def single_pending_class(planner: "_ShortcutPlanner", class_name: str) -> bool:
    """Check if class_name is the only pending preask class.

    Args:
        planner: The shortcuts planner instance
        class_name: Class to check

    Returns:
        True if this is the only pending class
    """
    active = [cls for cls, flag in planner.preask_pending_state.items() if flag]
    return len(active) == 1 and class_name in active


# --------------------------------------------------------------------------
# Preview building
# --------------------------------------------------------------------------


def prepare_preview_for_requests(planner: "_ShortcutPlanner") -> None:
    """Prepare preview for pending preview requests.

    Args:
        planner: The shortcuts planner instance
    """
    if not planner.preview_requests:
        return
    class_name, offset = planner.preview_requests[-1]
    build_preview_for_class(planner, class_name, offset)
    planner.preview_requests.clear()


def hydrate_preview_from_context(planner: "_ShortcutPlanner") -> None:
    """Hydrate preview lines from active choice context.

    Args:
        planner: The shortcuts planner instance
    """
    if planner.preview_lines or not planner.choice_context:
        return

    items = planner.choice_context.get("items") or []
    if not items:
        return

    lines: List[str] = []
    for item in items:
        idx = item.get("idx")
        label = str(item.get("label") or "").strip() or "This option"
        if idx is not None:
            lines.append(f"{idx}. {label}")
        else:
            lines.append(label)
    lines.append("Which one (1–3) or \"show more\"?")

    planner.preview_lines = lines
    class_name = str(planner.choice_context.get("kind") or "").strip().lower()
    if class_name:
        planner.preview_class = class_name
        planner.telemetry.preview_class_shown = class_name
    planner.telemetry.preview_items_count = max(planner.telemetry.preview_items_count, len(items))

    if planner.telemetry.menus_phase == "none":
        planner.telemetry.menus_phase = "post_room" if planner.room_checked else "explicit_request"
    if planner.telemetry.menus_included == "false":
        planner.telemetry.menus_included = "preview"
    planner.telemetry.choice_context_active = True


def build_preview_for_class(planner: "_ShortcutPlanner", class_name: str, offset: int) -> None:
    """Build preview lines for a product class.

    Creates choice context with TTL for interactive selection.

    Args:
        planner: The shortcuts planner instance
        class_name: Product class (catering, av, etc.)
        offset: Starting offset in items list
    """
    items = planner.manager_items_by_class.get(class_name, [])
    if not items:
        return

    subset = items[offset : offset + 3]
    if not subset:
        planner.preview_lines = [f"That's all available for {class_name}."]
        planner.preview_class = class_name
        planner.choice_context = None
        planner.event["choice_context"] = None
        planner.telemetry.preview_class_shown = class_name
        planner.telemetry.preview_items_count = 0
        planner.state.extras["persist"] = True
        planner.preask_pending_state[class_name] = False
        if class_name in planner.preask_clarifications:
            planner.preask_clarifications.remove(class_name)
        return

    lines: List[str] = []
    context_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(subset, start=1):
        name = str(item.get("name") or "").strip()
        lines.append(f"{idx}. {name}")
        context_items.append(
            {
                "idx": idx,
                "key": f"{class_name}-{offset + idx}",
                "label": name,
                "value": dict(item),
            }
        )
    lines.append("Which one (1–3) or \"show more\"?")

    planner.preview_lines = lines
    planner.preview_class = class_name

    context = {
        "kind": class_name,
        "presented_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "items": context_items,
        "ttl_turns": 4,
        "next_offset": offset + len(subset),
        "lang": "en",
    }
    planner.choice_context = context
    planner.event["choice_context"] = dict(context)
    planner.state.extras["persist"] = True

    planner.telemetry.preview_class_shown = class_name
    planner.telemetry.preview_items_count = len(subset)
    planner.telemetry.choice_context_active = True

    if planner.telemetry.menus_phase == "none":
        planner.telemetry.menus_phase = "post_room" if planner.room_checked else "explicit_request"
    planner.telemetry.menus_included = "preview"

    planner.preask_pending_state[class_name] = False
    if class_name in planner.preask_clarifications:
        planner.preask_clarifications.remove(class_name)


# --------------------------------------------------------------------------
# Preask prompt generation
# --------------------------------------------------------------------------


def maybe_preask_lines(planner: "_ShortcutPlanner") -> List[str]:
    """Generate preask prompt lines.

    Creates prompts for up to 2 add-on classes.

    Args:
        planner: The shortcuts planner instance

    Returns:
        List of preask prompt lines
    """
    if not preask_feature_enabled(planner):
        return []

    lines: List[str] = []
    unknown_classes = [
        cls for cls in planner.manager_items_by_class
        if planner.presented_interest.get(cls, "unknown") == "unknown"
    ]
    planner.telemetry.preask_candidates = unknown_classes
    shown: List[str] = []
    slots = 2

    # First show clarifications
    for class_name in list(planner.preask_clarifications):
        if slots <= 0:
            break
        prompt = f"Do you want to see {class_name} options now? (yes/no)"
        lines.append(prompt)
        shown.append(class_name)
        planner.preask_pending_state[class_name] = True
        planner.telemetry.preask_response[class_name] = planner.telemetry.preask_response.get(class_name, "clarify")
        slots -= 1

    # Then show new classes
    if slots > 0:
        for class_name in unknown_classes:
            if slots <= 0:
                break
            if class_name in shown or planner.preask_pending_state.get(class_name):
                continue
            prompt = _PREASK_CLASS_COPY.get(class_name, f"Would you like to see {class_name} options we can provide?")
            lines.append(prompt)
            shown.append(class_name)
            planner.preask_pending_state[class_name] = True
            slots -= 1

    for class_name in shown:
        planner.telemetry.preask_response.setdefault(class_name, "n/a")
    planner.telemetry.preask_shown = shown

    if lines and planner.telemetry.menus_included == "false":
        planner.telemetry.menus_included = "brief_upsell"
    if lines and planner.telemetry.menus_phase == "none" and planner.room_checked:
        planner.telemetry.menus_phase = "post_room"

    return lines


# --------------------------------------------------------------------------
# Preask state finalization
# --------------------------------------------------------------------------


def finalize_preask_state(planner: "_ShortcutPlanner") -> None:
    """Finalize preask state for persistence.

    Updates products_state and event with current preask state.

    Args:
        planner: The shortcuts planner instance
    """
    if not preask_feature_enabled(planner):
        if planner.products_state.get("preask_pending"):
            planner.products_state["preask_pending"] = {}
            planner.state.extras["persist"] = True
        if planner.event.get("choice_context"):
            planner.event["choice_context"] = None
            planner.state.extras["persist"] = True
        planner.telemetry.choice_context_active = False
        return

    planner.products_state["preask_pending"] = {
        cls: bool(flag) for cls, flag in planner.preask_pending_state.items() if flag
    }
    planner.products_state["presented_interest"] = dict(planner.presented_interest)

    if planner.choice_context:
        planner.event["choice_context"] = dict(planner.choice_context)
        planner.telemetry.choice_context_active = True
    elif planner.event.get("choice_context"):
        planner.event["choice_context"] = None
        planner.telemetry.choice_context_active = False

    planner.preview_lines = []
    if not planner.preview_class:
        planner.telemetry.preview_class_shown = "none"
        planner.telemetry.preview_items_count = 0
    planner.preview_class = None
    planner.state.extras["persist"] = True


__all__ = [
    # Feature control
    "preask_feature_enabled",
    # Menu preview
    "menu_preview_lines",
    "explicit_menu_requested",
    # Processing
    "process_preask",
    "maybe_emit_preask_prompt_only",
    # Response handling
    "handle_preask_responses",
    "detect_preask_response",
    "single_pending_class",
    # Preview building
    "prepare_preview_for_requests",
    "hydrate_preview_from_context",
    "build_preview_for_class",
    # Prompt generation
    "maybe_preask_lines",
    # State finalization
    "finalize_preask_state",
]
