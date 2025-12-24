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
    filters = filters or {}
    all_items = [
        {
            "category": "Parking",
            "question": "Where can guests park?",
            "answer": "The Atelier offers underground parking with 50 spaces available for event guests. Additional street parking is available nearby. Parking vouchers can be arranged for your guests at CHF 5 per vehicle for the full event duration.",
            "related_links": []
        },
        {
            "category": "Parking",
            "question": "Is there disabled parking available?",
            "answer": "Yes, we have 3 designated disabled parking spaces directly at the main entrance with level access to all event spaces. These spaces are wider than standard spots and connect to our accessible routes throughout the venue.",
            "related_links": []
        },
        {
            "category": "Parking",
            "question": "Can we reserve parking spaces for VIP guests?",
            "answer": "Absolutely! We can reserve specific parking spaces closest to the entrance for your VIP guests. Please let us know how many VIP spaces you need when finalizing your booking.",
            "related_links": []
        },
        {
            "category": "Catering",
            "question": "Can you accommodate dietary restrictions?",
            "answer": "Absolutely! All our menus can be adapted for vegetarian, vegan, gluten-free, and other dietary requirements. Our chef team is experienced in handling allergies and religious dietary needs. Please inform us of any restrictions when booking, and we'll create appropriate alternatives.",
            "related_links": []
        },
        {
            "category": "Catering",
            "question": "Can we bring our own catering?",
            "answer": "While we prefer to use our in-house catering team who know our facilities best, we can accommodate external catering for special circumstances. A kitchen usage fee of CHF 500 applies, and external caterers must provide food safety certification.",
            "related_links": []
        },
        {
            "category": "Booking",
            "question": "How far in advance should I book?",
            "answer": "We recommend booking at least 4 weeks in advance for the best availability. For peak seasons (May-June, September-October, and December), 6-8 weeks advance booking is advisable. We can sometimes accommodate last-minute requests, so always feel free to ask!",
            "related_links": []
        },
        {
            "category": "Booking",
            "question": "What's your cancellation policy?",
            "answer": "Cancellations made more than 30 days before the event: Full refund minus CHF 200 admin fee. 14-30 days: 50% refund. Less than 14 days: No refund, but we'll try to reschedule if possible. We strongly recommend event insurance for large bookings.",
            "related_links": []
        },
        {
            "category": "Equipment",
            "question": "What AV equipment is included?",
            "answer": "All rooms include: HD projector or LED screen, wireless microphones, sound system, WiFi, and basic lighting. Additional equipment like recording devices, live streaming setup, or special lighting can be arranged for an extra fee.",
            "related_links": []
        },
        {
            "category": "Equipment",
            "question": "Can we live stream our event?",
            "answer": "Yes! Rooms B, C, and Punkt.Null are equipped with live streaming capabilities. We provide the technical setup and can assign a technician to manage the stream. Streaming to up to 500 viewers is included; larger audiences require upgraded bandwidth.",
            "related_links": []
        },
        {
            "category": "Access",
            "question": "Is the venue wheelchair accessible?",
            "answer": "Yes, The Atelier is fully wheelchair accessible. We have ramps to all entrances, an elevator to all floors, accessible restrooms on each level, and adjustable-height presentation equipment. Please let us know about any specific accessibility needs.",
            "related_links": []
        },
        {
            "category": "Access",
            "question": "How early can we access the venue for setup?",
            "answer": "Standard bookings include 1 hour setup time. For elaborate setups, we can arrange early access from 2-4 hours before your event start time for an additional CHF 100 per hour. Our team can also assist with setup if needed.",
            "related_links": []
        }
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
