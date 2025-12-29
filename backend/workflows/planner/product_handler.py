"""
Smart Shortcuts - Product Handler.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles product/add-on processing for the shortcuts planner:
- Product intent parsing and matching
- Product state management
- Product display formatting
- Quantity inference

Usage:
    from .product_handler import (
        parse_product_intent, apply_product_add,
        format_money, products_state,
    )
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.services.products import normalise_product_payload

from .shortcuts_flags import (
    _budget_default_currency,
    _capture_budget_on_hil,
    _max_missing_items_per_hil,
    _product_flow_enabled,
)

if TYPE_CHECKING:
    from .shortcuts_types import ParsedIntent
    from .smart_shortcuts import _ShortcutPlanner


# --------------------------------------------------------------------------
# Static utilities
# --------------------------------------------------------------------------


def format_money(amount: Optional[float], currency: str) -> str:
    """Format a monetary amount with currency.

    Args:
        amount: The amount to format (None returns "TBD")
        currency: Currency code (e.g., "CHF")

    Returns:
        Formatted string like "CHF 150" or "TBD"
    """
    if amount is None:
        return "TBD"
    rounded = round(amount, 2)
    if abs(rounded - round(rounded)) < 1e-6:
        value = str(int(round(rounded)))
    else:
        value = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return f"{currency} {value}"


def missing_item_display(item: Dict[str, Any]) -> str:
    """Format a missing item for display.

    Args:
        item: Dict with 'name' key

    Returns:
        Display string like "Champagne - price pending (via manager)"
    """
    name = str(item.get("name") or "the item").strip() or "the item"
    return f"{name} - price pending (via manager)"


# --------------------------------------------------------------------------
# Product state management
# --------------------------------------------------------------------------


def products_state(planner: "_ShortcutPlanner") -> Dict[str, Any]:
    """Get or create the products_state dict in the event.

    Returns the event's products_state, initializing with default structure
    if it doesn't exist.
    """
    return planner.event.setdefault(
        "products_state",
        {
            "available_items": [],
            "manager_added_items": [],
            "line_items": [],
            "pending_hil_requests": [],
            "budgets": {},
        },
    )


def product_lookup(planner: "_ShortcutPlanner", bucket: str) -> Dict[str, Dict[str, Any]]:
    """Build a lookup dict from a product bucket.

    Args:
        planner: The shortcuts planner instance
        bucket: Bucket name ("available_items" or "manager_added_items")

    Returns:
        Dict mapping lowercase names to product entries
    """
    items = products_state(planner).get(bucket) or []
    lookup: Dict[str, Dict[str, Any]] = {}
    for entry in items:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        lookup[name.lower()] = dict(entry)
    return lookup


def normalise_products(planner: "_ShortcutPlanner", payload: Any) -> List[Dict[str, Any]]:
    """Normalize a product payload to a list of product dicts.

    Args:
        planner: The shortcuts planner instance
        payload: Raw product payload (list, dict, or string)

    Returns:
        List of normalized product dicts with name/quantity
    """
    participant_count = (
        planner.user_info.get("participants")
        if isinstance(planner.user_info.get("participants"), int)
        else None
    )
    return normalise_product_payload(payload, participant_count=participant_count)


def current_participant_count(planner: "_ShortcutPlanner") -> Optional[int]:
    """Get the current participant count from various sources.

    Checks in order:
    1. user_info.participants
    2. requirements.number_of_participants
    3. event_data["Number of Participants"]
    """
    candidates = [
        planner.user_info.get("participants"),
        (planner.event.get("requirements") or {}).get("number_of_participants"),
        (planner.event.get("event_data") or {}).get("Number of Participants"),
    ]
    for value in candidates:
        if value in (None, "", "Not specified"):
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return None


def infer_quantity(planner: "_ShortcutPlanner", product_entry: Dict[str, Any]) -> int:
    """Infer quantity for a product entry.

    Uses explicit quantity if present, otherwise falls back to participant count.

    Args:
        planner: The shortcuts planner instance
        product_entry: Product dict that may have 'quantity'

    Returns:
        Inferred quantity (minimum 1)
    """
    qty = product_entry.get("quantity")
    if isinstance(qty, (int, float)):
        value = int(qty)
        return max(1, value)
    participants = current_participant_count(planner)
    if participants:
        return max(1, participants)
    return 1


# --------------------------------------------------------------------------
# Product display/formatting
# --------------------------------------------------------------------------


def format_product_line(planner: "_ShortcutPlanner", detail: Dict[str, Any]) -> str:
    """Format a single product line for display.

    Args:
        planner: The shortcuts planner instance
        detail: Product detail dict with name, quantity, unit_price, etc.

    Returns:
        Formatted line like "• Champagne: 2 × CHF 75 = CHF 150"
    """
    name = detail.get("name") or "Unnamed item"
    quantity = detail.get("quantity") or 1
    unit_price = detail.get("unit_price")
    currency = detail.get("currency") or _budget_default_currency()
    if unit_price is None:
        return f"• {name}: {quantity} × TBD (price pending)"
    subtotal = detail.get("subtotal")
    unit_str = format_money(unit_price, currency)
    subtotal_str = format_money(subtotal or 0.0, currency)
    return f"• {name}: {quantity} × {unit_str} = {subtotal_str}"


def product_subtotal_lines(planner: "_ShortcutPlanner") -> List[str]:
    """Generate subtotal lines for products.

    Returns a list of subtotal lines, one per currency if multiple.
    """
    if not planner.product_currency_totals:
        return []
    if len(planner.product_currency_totals) == 1:
        currency, amount = next(iter(planner.product_currency_totals.items()))
        return [f"Products subtotal: {format_money(amount, currency)}"]
    lines: List[str] = []
    for currency in sorted(planner.product_currency_totals.keys()):
        amount = planner.product_currency_totals[currency]
        lines.append(f"Products subtotal ({currency}): {format_money(amount, currency)}")
    return lines


def build_product_confirmation_lines(planner: "_ShortcutPlanner") -> List[str]:
    """Build confirmation message lines for products.

    Returns a formatted list of product lines with subtotals.
    """
    if not planner.product_line_details:
        planner.telemetry.product_prices_included = False
        planner.telemetry.product_price_missing = planner.product_price_missing
        return []

    lines: List[str] = ["Products added:"]
    any_missing = False
    for detail in planner.product_line_details:
        line = format_product_line(planner, detail)
        if detail.get("price_missing"):
            any_missing = True
        lines.append(line)

    subtotal_lines_list = product_subtotal_lines(planner)
    lines.extend(subtotal_lines_list)

    any_priced = any(not detail.get("price_missing") for detail in planner.product_line_details)
    all_priced = all(not detail.get("price_missing") for detail in planner.product_line_details)
    planner.telemetry.product_prices_included = all_priced and any_priced
    planner.product_price_missing = planner.product_price_missing or any_missing
    planner.telemetry.product_price_missing = planner.product_price_missing or any_missing
    return lines


# --------------------------------------------------------------------------
# Product intent parsing
# --------------------------------------------------------------------------


def parse_product_intent(planner: "_ShortcutPlanner") -> None:
    """Parse product intents from user_info and add to verifiable/needs_input.

    Matches products against available_items and manager_added_items catalogs.
    Creates product_add intent for matched items and offer_hil for missing items.
    """
    if not _product_flow_enabled():
        return

    raw_products = normalise_products(planner, planner.user_info.get("products_add"))
    if not raw_products:
        return

    available_map = product_lookup(planner, "available_items")
    manager_map = product_lookup(planner, "manager_added_items")

    matched: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []

    for item in raw_products:
        name_key = item["name"].lower()
        catalog_entry = available_map.get(name_key) or manager_map.get(name_key)
        if catalog_entry:
            merged = dict(catalog_entry)
            merged.setdefault("name", catalog_entry.get("name") or item["name"])
            merged["quantity"] = item.get("quantity") or merged.get("quantity") or infer_quantity(planner, merged)
            matched.append(merged)
        else:
            missing.append(item)

    if matched:
        planner.pending_product_additions.extend(matched)
        # Import here to avoid circular import at module level
        from .shortcuts_types import ParsedIntent

        planner.verifiable.append(ParsedIntent("product_add", {"items": matched}, verifiable=True))

    limited_missing = missing[: _max_missing_items_per_hil()]

    if missing:
        planner.pending_missing_products.extend(limited_missing)
        payload: Dict[str, Any] = {
            "items": limited_missing,
            "ask_budget": _capture_budget_on_hil(),
        }
        if planner.budget_info:
            payload["budget"] = planner.budget_info
            planner.telemetry.budget_provided = True
        planner.telemetry.offered_hil = True
        planner._add_needs_input("offer_hil", payload, reason="missing_products")
        planner.product_price_missing = True

    if matched and not missing:
        if planner.telemetry.artifact_match is None:
            planner.telemetry.artifact_match = "all"
    elif matched and missing:
        planner.telemetry.artifact_match = "partial"
    elif not matched and missing:
        if planner.telemetry.artifact_match is None:
            planner.telemetry.artifact_match = "none"

    if missing:
        planner.telemetry.missing_items.extend({"name": item.get("name")} for item in limited_missing)


def apply_product_add(planner: "_ShortcutPlanner", items: List[Dict[str, Any]]) -> bool:
    """Apply product additions to the event.

    Updates both event.products and products_state.line_items.
    Tracks prices and calculates subtotals.

    Args:
        planner: The shortcuts planner instance
        items: List of product items to add

    Returns:
        True if items were added, False if list was empty
    """
    if not items:
        return False

    products_list = planner.event.setdefault("products", [])
    line_items = products_state(planner).setdefault("line_items", [])
    currency_default = _budget_default_currency()

    for item in items:
        name = item.get("name") or "Unnamed item"
        quantity = max(1, int(item.get("quantity") or infer_quantity(planner, item)))
        unit_price_raw = item.get("unit_price")
        currency = item.get("currency") or currency_default

        unit_price_value: Optional[float] = None
        if unit_price_raw is not None:
            try:
                unit_price_value = float(unit_price_raw)
            except (TypeError, ValueError):
                unit_price_value = None

        subtotal: Optional[float] = None
        if unit_price_value is not None:
            subtotal = unit_price_value * quantity
        else:
            planner.product_price_missing = True

        # Update or add to products_list
        updated = False
        for existing in products_list:
            if existing.get("name", "").lower() == name.lower():
                existing["quantity"] = quantity
                if unit_price_value is not None:
                    existing["unit_price"] = unit_price_value
                updated = True
                break
        if not updated:
            entry: Dict[str, Any] = {"name": name, "quantity": quantity}
            if unit_price_value is not None:
                entry["unit_price"] = unit_price_value
            products_list.append(entry)

        # Update or add to line_items
        line_updated = False
        for existing_line in line_items:
            if existing_line.get("name", "").lower() == name.lower():
                existing_line["quantity"] = quantity
                if unit_price_value is not None:
                    existing_line["unit_price"] = unit_price_value
                line_updated = True
                break
        if not line_updated:
            entry = {"name": name, "quantity": quantity}
            if unit_price_value is not None:
                entry["unit_price"] = unit_price_value
            line_items.append(entry)

        # Track telemetry and totals
        planner.telemetry.added_items.append({"name": name, "quantity": quantity})
        if subtotal is not None:
            planner.product_currency_totals[currency] = (
                planner.product_currency_totals.get(currency, 0.0) + subtotal
            )
        else:
            planner.product_price_missing = True
        planner.product_line_details.append(
            {
                "name": name,
                "quantity": quantity,
                "currency": currency,
                "unit_price": unit_price_value,
                "subtotal": subtotal,
                "price_missing": unit_price_value is None,
            }
        )

    if items:
        planner.telemetry.executed_intents.append("product_add")
    planner.state.extras["persist"] = True
    return True


# --------------------------------------------------------------------------
# Module-level utilities
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_catering_names() -> List[str]:
    """Load catering/product names from products.json.

    Returns a cached list of product names (catering category).
    """
    path = Path(__file__).resolve().parents[2] / "data" / "products.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    products = data.get("products") or []
    names: List[str] = []
    for prod in products:
        # Include all products (catering, beverages, etc.)
        name = str(prod.get("name") or "").strip()
        if name:
            names.append(name)
    return names


__all__ = [
    # Static utilities
    "format_money",
    "missing_item_display",
    # Product state
    "products_state",
    "product_lookup",
    "normalise_products",
    "current_participant_count",
    "infer_quantity",
    # Product display
    "format_product_line",
    "product_subtotal_lines",
    "build_product_confirmation_lines",
    # Product intent
    "parse_product_intent",
    "apply_product_add",
    # Module-level
    "load_catering_names",
]
