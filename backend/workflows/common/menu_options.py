from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Optional, Sequence

_MONTH_KEYWORDS = {
    "jan": "january",
    "january": "january",
    "feb": "february",
    "february": "february",
    "mar": "march",
    "march": "march",
    "apr": "april",
    "april": "april",
    "may": "may",
    "jun": "june",
    "june": "june",
    "jul": "july",
    "july": "july",
    "aug": "august",
    "august": "august",
    "sep": "september",
    "sept": "september",
    "september": "september",
    "oct": "october",
    "october": "october",
    "nov": "november",
    "november": "november",
    "dec": "december",
    "december": "december",
}

_MENU_KEY_PATTERN = re.compile(r"\b(?:menu|menus|menu options)\b")
_THREE_COURSE_PATTERN = re.compile(r"(?:three|3)[-\s]?course")


# Database-backed menu options accessor - see config_store.py for defaults
from backend.workflows.io.config_store import get_dinner_menu_options


def _get_dinner_menus() -> Sequence[Dict[str, Any]]:
    """Load dinner menu options from database config (with fallback defaults)."""
    return tuple(get_dinner_menu_options())


# Legacy constant - now loads from database config
# Kept for backward compatibility but prefer using _get_dinner_menus() for fresh data
DINNER_MENU_OPTIONS: Sequence[Dict[str, Any]] = _get_dinner_menus()


def _normalize_month(month: Optional[str]) -> Optional[str]:
    if not month:
        return None
    token = str(month).strip().lower()
    return _MONTH_KEYWORDS.get(token, token or None)


def _contains_menu_keyword(text: str) -> bool:
    return bool(_MENU_KEY_PATTERN.search(text))


def extract_menu_request(message_text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse incoming text and detect if it contains a menu-related question."""

    if not message_text:
        return None
    lowered = message_text.lower()
    if not _contains_menu_keyword(lowered):
        return None

    vegetarian = any(token in lowered for token in ("vegetarian", "veg-friendly", "veggie", "plant-based", "meatless"))
    vegan = "vegan" in lowered
    if vegan:
        vegetarian = True
    wine_pairing = "wine" in lowered or "pairing" in lowered or "paired wines" in lowered
    three_course = bool(_THREE_COURSE_PATTERN.search(lowered))

    month_hint: Optional[str] = None
    for token, canonical in _MONTH_KEYWORDS.items():
        if token in lowered:
            month_hint = canonical
            break

    return {
        "vegetarian": vegetarian,
        "wine_pairing": wine_pairing,
        "three_course": three_course,
        "month": month_hint,
        "menu_requested": True,
    }


def _menu_matches_request(menu: Dict[str, Any], request: Dict[str, Any]) -> bool:
    if request.get("vegetarian") and not menu.get("vegetarian"):
        return False
    if request.get("three_course") and menu.get("courses") not in (None, 3):
        return False
    if request.get("wine_pairing") and not menu.get("wine_pairing"):
        return False
    return True


def select_menu_options(
    request: Dict[str, Any],
    *,
    month_hint: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Filter dinner menus based on the client request."""

    month_token = _normalize_month(month_hint or request.get("month"))
    filtered: List[Dict[str, Any]] = []

    for menu in DINNER_MENU_OPTIONS:
        if not _menu_matches_request(menu, request):
            continue
        menu_months = menu.get("available_months") or []
        if month_token and menu_months and month_token not in menu_months:
            continue
        filtered.append(dict(menu))

    if not filtered and month_token:
        for menu in DINNER_MENU_OPTIONS:
            if not _menu_matches_request(menu, request):
                continue
            filtered.append(dict(menu))

    filtered.sort(key=lambda item: (item.get("priority", 100), item.get("price") or ""))
    return filtered[:limit]


def build_menu_title(request: Dict[str, Any]) -> str:
    """Compose a heading describing the detected menu request."""

    segments: List[str] = []
    if request.get("vegetarian"):
        segments.append("Vegetarian")
    else:
        segments.append("Dinner")

    if request.get("three_course"):
        segments.append("three-course menus")
    else:
        segments.append("menu options")

    base = " ".join(segments)
    if request.get("wine_pairing"):
        return f"{base} with wine pairings:"
    return f"{base} we can offer:"


def _normalise_price(value: Any) -> str:
    if value is None:
        return "CHF ?"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"CHF {int(value)}"
        return f"CHF {value:.2f}"
    text = str(value).strip()
    if not text:
        return "CHF ?"
    lowered = text.lower()
    if lowered.startswith("chf"):
        stripped = text[3:].strip()
        return f"CHF {stripped}" if stripped else "CHF ?"
    return f"CHF {text}"


def format_menu_line(menu: Dict[str, Any], *, month_hint: Optional[str] = None) -> str:
    """Render a friendly bullet point for a dinner menu option."""

    name = str(menu.get("menu_name") or "").strip()
    if not name:
        return ""
    price_text = _normalise_price(menu.get("price"))

    notes: List[str] = []
    if menu.get("wine_pairing"):
        notes.append("wine pairings included")
    if menu.get("vegetarian"):
        notes.append("vegetarian")
    notes.extend(menu.get("notes") or [])

    season_label = menu.get("season_label")
    if season_label:
        notes.append(str(season_label))
    elif month_hint:
        menu_months = {str(month).lower() for month in menu.get("available_months") or []}
        token = _normalize_month(month_hint)
        if token and (not menu_months or token in menu_months):
            notes.append(f"available in {token.capitalize()}")

    notes_deduped: List[str] = []
    for entry in notes:
        clean = str(entry).strip()
        if clean and clean not in notes_deduped:
            notes_deduped.append(clean)

    line = f"- {name}: {price_text} per guest"
    if notes_deduped:
        line += f" ({'; '.join(notes_deduped)})"
    line += "."

    description = str(menu.get("description") or "").strip()
    if description:
        line += f" {description}"
    return line


# ============================================================================
# CONTENT ABBREVIATION THRESHOLD
# ============================================================================
# When menu/catering content exceeds this character count in the chat, we:
#   1. Abbreviate the display (show name + price only, no descriptions)
#   2. Add a link to the full info page with snapshot data
#
# Current threshold: 400 characters (UX standard for focused chat messages)
#
# ADJUSTMENT NOTES:
#   - Lower value (e.g., 200): More aggressive abbreviation, cleaner chat
#   - Higher value (e.g., 600): More detail in chat before linking out
#   - Set to 0: Always abbreviate and link (never show full details in chat)
#   - Remove threshold check: Always show full details (may clutter chat)
#
# The link always goes to /info/qna with snapshot_id for persistent data.
# See also: room_availability/trigger/process.py uses QNA_SUMMARY_CHAR_THRESHOLD
# which references this constant for consistency.
# ============================================================================
MENU_CONTENT_CHAR_THRESHOLD = 400


def format_menu_line_short(menu: Dict[str, Any]) -> str:
    """
    Render an abbreviated menu line (name + price only, no description).

    Used when content exceeds display threshold and we link to full info page.
    Matches the pattern from room_availability's _short_menu_line().
    """
    name = str(menu.get("menu_name") or "").strip()
    if not name:
        return ""
    price_text = _normalise_price(menu.get("price"))
    # Keep it minimal: name + price + "Rooms: all" indicator
    suffix = " per event" if price_text and "per" not in price_text.lower() else ""
    return f"- {name}: {price_text}{suffix} (Rooms: all)"


def build_menu_payload(
    message_text: Optional[str],
    *,
    context_month: Optional[str] = None,
    limit: int = 3,
    allow_context_fallback: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Return a structured payload describing menu options for the general Q&A block."""

    request = extract_menu_request(message_text)
    if not request:
        return None

    request_month = _normalize_month(request.get("month"))
    primary_month = request_month
    link_context = ALLOW_CONTEXTUAL_HINTS if allow_context_fallback is None else allow_context_fallback
    context_hint = _normalize_month(context_month)
    if not primary_month and link_context and context_hint:
        primary_month = context_hint

    options = select_menu_options(request, month_hint=primary_month, limit=limit)
    if not options:
        return None

    rows: List[Dict[str, Any]] = []
    for menu in options:
        rows.append(
            {
                "menu_name": menu.get("menu_name"),
                "courses": menu.get("courses"),
                "vegetarian": menu.get("vegetarian"),
                "wine_pairing": menu.get("wine_pairing"),
                "price": menu.get("price"),
                "notes": menu.get("notes"),
                "description": menu.get("description"),
                "available_months": menu.get("available_months"),
                "season_label": menu.get("season_label"),
            }
        )

    where_clauses: List[str] = []
    if request.get("three_course"):
        where_clauses.append("courses=3")
    if request.get("vegetarian"):
        where_clauses.append("vegetarian=true")
    if request.get("wine_pairing"):
        where_clauses.append("wine_pairing=true")
    if request_month:
        where_clauses.append(f"available_month='{request_month.capitalize()}'")

    payload: Dict[str, Any] = {
        "select_expr": "SELECT menu_name, courses, vegetarian, wine_pairing, price",
        "where_clauses": where_clauses,
        "rows": rows,
        "title": build_menu_title(request),
        "request": request,
    }
    if primary_month:
        payload["month"] = primary_month
        if link_context and primary_month == context_hint and primary_month != request_month:
            payload["context_linked"] = True
    if request_month:
        payload["request_month"] = request_month
    return payload


def normalize_menu_for_display(menu: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform internal menu format to frontend display format.

    Internal format (from DINNER_MENU_OPTIONS):
        - menu_name, price, description, season_label, available_months, vegetarian, wine_pairing

    Frontend format (expected by /info/qna):
        - name, slug, price_per_person, description, availability_window, dietary
    """
    name = menu.get("menu_name") or menu.get("name") or ""
    slug = name.lower().replace(" ", "-")
    price = menu.get("price") or ""

    # Build dietary tags
    dietary = []
    if menu.get("vegetarian"):
        dietary.append("vegetarian")
    if menu.get("wine_pairing"):
        dietary.append("wine pairing included")
    dietary.extend(menu.get("notes") or [])

    # Build availability window
    availability = menu.get("season_label") or ""
    if not availability and menu.get("available_months"):
        months = menu.get("available_months", [])
        if isinstance(months, list) and len(months) >= 2:
            availability = f"Available {months[0].capitalize()}–{months[-1].capitalize()}"

    return {
        "name": name,
        "slug": slug,
        "price_per_person": price,
        "description": menu.get("description") or "",
        "availability_window": availability,
        "dietary": dietary,
        # Keep original fields for reference
        "courses": menu.get("courses"),
        "vegetarian": menu.get("vegetarian"),
        "wine_pairing": menu.get("wine_pairing"),
    }


__all__ = [
    "build_menu_payload",
    "build_menu_title",
    "extract_menu_request",
    "format_menu_line",
    "format_menu_line_short",
    "MENU_CONTENT_CHAR_THRESHOLD",
    "normalize_menu_for_display",
    "select_menu_options",
]
_LINK_CONTEXT_ENV = os.getenv("OPENEVENT_MENU_CONTEXT_LINK", "").strip()
ALLOW_CONTEXTUAL_HINTS = _LINK_CONTEXT_ENV.lower() in {"1", "true", "yes"}
# TODO(openevent-team): Revisit whether contextual hints should be linked by default.
