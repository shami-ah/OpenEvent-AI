"""
Data providers for test pages.
Serves structured data that test pages can display.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from backend.workflows.common.menu_options import DINNER_MENU_OPTIONS
from backend.workflows.steps.step3_room_availability.db_pers import load_rooms_config


def get_rooms_for_display(date: Optional[str] = None, capacity: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get detailed room information for display, combining manager config with defaults."""
    rooms: List[Dict[str, Any]] = []
    config_rooms = load_rooms_config() or []

    default_prices = {
        "Room A": 500,
        "Room B": 800,
        "Room C": 1200,
        "Punkt.Null": 1500,
    }

    for room_config in config_rooms:
        room_name = room_config.get("name", "")
        if not room_name:
            continue

        max_capacity = room_config.get("capacity_max") or room_config.get("capacity") or room_config.get("max_capacity")
        try:
            max_capacity_int = int(max_capacity) if max_capacity is not None else 0
        except (TypeError, ValueError):
            max_capacity_int = 0

        room_info = {
            "name": room_name,
            "capacity": max_capacity_int,
            "status": "Available",
            "price": default_prices.get(room_name, 0),
            "features": room_config.get("features", []),
            "equipment": room_config.get("services", []),  # Manager items
            "layout_options": list(room_config.get("capacity_by_layout", {}).keys()),
            "description": f"Manager-configured room with {len(room_config.get('features', []))} features",
            "menus": _get_menus_for_room(room_name),
        }

        try:
            capacity_filter = int(capacity) if capacity is not None else None
        except (TypeError, ValueError):
            capacity_filter = None
        if capacity_filter and room_info["capacity"] < capacity_filter:
            continue

        rooms.append(room_info)

    return sorted(rooms, key=lambda x: x["capacity"])


def get_all_catering_menus(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Get catering menus for catalog display, filtered by parameters."""
    filters = filters or {}
    menus: List[Dict[str, Any]] = []

    for menu in DINNER_MENU_OPTIONS:
        # Apply filters (same logic as _get_full_menu_details)
        # Filter by month
        if filters.get("month"):
            available_months = menu.get("available_months", [])
            month_str = str(filters["month"]).lower()
            if available_months and month_str not in [str(m).lower() for m in available_months]:
                continue

        # Filter by vegetarian
        if filters.get("vegetarian") is True and not menu.get("vegetarian"):
            continue

        # Filter by vegan
        if filters.get("vegan") is True and not menu.get("vegetarian"):
            continue

        # Filter by courses
        if filters.get("courses") and menu.get("courses") != filters["courses"]:
            continue

        # Filter by wine pairing
        if filters.get("wine_pairing") is True and not menu.get("wine_pairing"):
            continue

        menu_slug = menu.get("menu_name", "").lower().replace(" ", "-")
        menus.append({
            "name": menu.get("menu_name"),
            "slug": menu_slug,
            "price_per_person": menu.get("price"),
            "summary": menu.get("description", ""),
            "dietary_options": _extract_dietary_info(str(menu)),
            "availability_window": menu.get("available_months", "Year-round"),
        })
    return menus


def get_catering_menu_details(menu_slug: str) -> Optional[Dict[str, Any]]:
    """Get detailed menu information."""
    for menu in DINNER_MENU_OPTIONS:
        if menu.get("menu_name", "").lower().replace(" ", "-") == menu_slug:
            return {
                "name": menu.get("menu_name"),
                "slug": menu_slug,
                "price_per_person": menu.get("price"),
                "courses": [
                    {
                        "course": "Starter",
                        "description": menu.get("starter", ""),
                        "dietary": _extract_dietary_info(menu.get("starter", "")),
                        "allergens": [],
                    },
                    {
                        "course": "Main Course",
                        "description": menu.get("main", ""),
                        "dietary": _extract_dietary_info(menu.get("main", "")),
                        "allergens": [],
                    },
                    {
                        "course": "Dessert",
                        "description": menu.get("dessert", ""),
                        "dietary": _extract_dietary_info(menu.get("dessert", "")),
                        "allergens": [],
                    }
                ],
                "beverages_included": menu.get("beverages", ["House wine selection", "Soft drinks", "Coffee & tea"]),
                "minimum_order": menu.get("min_order", 10),
                "description": menu.get("description", "A delightful culinary experience for your event."),
            }
    return None


def get_qna_items(category: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get Q&A items, optionally filtered by category and other parameters."""
    from backend.workflows.io.config_store import get_faq_items as load_faq_items

    filters = filters or {}

    # Load FAQ items from database config (with fallback defaults)
    raw_items = load_faq_items()

    # Add empty related_links for display compatibility
    all_items = [
        {**item, "related_links": item.get("related_links", [])}
        for item in raw_items
    ]

    categories = sorted(list(set(item["category"] for item in all_items)))

    normalized_category = category.lower() if isinstance(category, str) else None
    if category:
        items = [item for item in all_items if item["category"] == category]
    else:
        items = all_items

    result = {
        "items": items,
        "categories": categories,
        "menus": _get_full_menu_details(filters) if normalized_category == "catering" else [],
    }

    # Include filter metadata so frontend can display what's being filtered
    if filters:
        result["applied_filters"] = filters

    return result


def _extract_dietary_info(text: str) -> List[str]:
    """Extract dietary information from text."""
    dietary: List[str] = []
    text_lower = text.lower()
    if "vegetarian" in text_lower:
        dietary.append("Vegetarian")
    if "vegan" in text_lower:
        dietary.append("Vegan")
    if "gluten-free" in text_lower or "gluten free" in text_lower:
        dietary.append("Gluten-Free")
    return dietary


def _menus_for_room(room_name: str) -> List[Dict[str, Any]]:
    """
    Placeholder mapping of menus to rooms.
    In production this should query the manager's assignments.
    """
    menus: List[Dict[str, Any]] = []
    for menu in DINNER_MENU_OPTIONS:
        menu_slug = menu.get("menu_name", "").lower().replace(" ", "-")
        menus.append(
            {
                "name": menu.get("menu_name"),
                "slug": menu_slug,
                "price_per_person": menu.get("price"),
                "summary": menu.get("description", ""),
                "dietary_options": _extract_dietary_info(str(menu)),
            }
        )
    return menus


def _get_full_menu_details(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Get full menu details for Q&A page display, filtered by parameters."""
    filters = filters or {}
    menus: List[Dict[str, Any]] = []

    for menu in DINNER_MENU_OPTIONS:
        # Apply filters
        # Filter by month
        if filters.get("month"):
            available_months = menu.get("available_months", [])
            month_str = str(filters["month"]).lower()
            if available_months and month_str not in [str(m).lower() for m in available_months]:
                continue

        # Filter by vegetarian
        if filters.get("vegetarian") is True and not menu.get("vegetarian"):
            continue

        # Filter by vegan (stricter than vegetarian)
        if filters.get("vegan") is True:
            # For now, skip non-vegetarian menus (vegan would need explicit flag)
            if not menu.get("vegetarian"):
                continue

        # Filter by courses
        if filters.get("courses") and menu.get("courses") != filters["courses"]:
            continue

        # Filter by wine pairing
        if filters.get("wine_pairing") is True and not menu.get("wine_pairing"):
            continue

        menu_slug = menu.get("menu_name", "").lower().replace(" ", "-")
        menus.append(
            {
                "name": menu.get("menu_name"),
                "slug": menu_slug,
                "price_per_person": menu.get("price"),
                "description": menu.get("description", ""),
                "availability_window": menu.get("available_months", "Year-round"),
                "courses": {
                    "starter": menu.get("starter", ""),
                    "main": menu.get("main", ""),
                    "dessert": menu.get("dessert", ""),
                },
                "dietary": _extract_dietary_info(str(menu)),
            }
        )
    return menus
