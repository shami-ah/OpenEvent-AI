"""
[OpenEvent Config Store] Database-backed venue configuration accessors.

This module provides centralized access to venue-specific settings that were
previously hardcoded across the codebase. Settings are stored in the JSON DB
under db["config"]["venue"] and can be updated via the API or edited directly.

All accessors return sensible defaults if the config is missing, ensuring
backward compatibility with existing installations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Pattern, Tuple

from backend.workflows.io.database import load_db

__workflow_role__ = "ConfigStore"

# Database path (same as workflow_email.py)
DB_PATH = Path(__file__).resolve().parents[2] / "events_database.json"

# Default values - match current hardcoded behavior
_DEFAULTS: Dict[str, Any] = {
    "name": "The Atelier",
    "city": "Zurich",
    "timezone": "Europe/Zurich",
    "currency_code": "CHF",
    "operating_hours": {"start": 8, "end": 23},
    "from_email": "openevent@atelier.ch",
    "from_name": "OpenEvent AI",
    "frontend_url": "http://localhost:3000",
}

# Site visit defaults - match current hardcoded behavior
_SITE_VISIT_DEFAULTS: Dict[str, Any] = {
    "blocked_dates": [],  # Additional blocked dates (ISO format)
    "default_slots": [10, 14, 16],  # Hours in 24-hour format
    "weekdays_only": True,  # Only allow weekday site visits
    "min_days_ahead": 2,  # Minimum days before event for site visit
}

# Manager defaults
_MANAGER_DEFAULTS: Dict[str, Any] = {
    "names": [],  # Registered manager names for escalation detection
}

# Product config defaults
_PRODUCT_DEFAULTS: Dict[str, Any] = {
    "autofill_min_score": 0.5,  # Similarity threshold for auto-suggestions
}


def _get_venue_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load venue config from database with defaults."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        venue = config.get("venue", {})
        return venue
    except Exception:
        # If DB fails to load, return empty dict (defaults will be used)
        return {}


def get_venue_name() -> str:
    """[OpenEvent Config Store] Return the venue name (e.g., 'The Atelier')."""
    venue = _get_venue_config()
    return venue.get("name") or _DEFAULTS["name"]


def get_venue_city() -> str:
    """[OpenEvent Config Store] Return the venue city (e.g., 'Zurich')."""
    venue = _get_venue_config()
    return venue.get("city") or _DEFAULTS["city"]


def get_timezone() -> str:
    """[OpenEvent Config Store] Return the timezone identifier (e.g., 'Europe/Zurich')."""
    venue = _get_venue_config()
    return venue.get("timezone") or _DEFAULTS["timezone"]


def get_currency_code() -> str:
    """[OpenEvent Config Store] Return the ISO currency code (e.g., 'CHF')."""
    venue = _get_venue_config()
    return venue.get("currency_code") or _DEFAULTS["currency_code"]


def get_operating_hours() -> Tuple[int, int]:
    """[OpenEvent Config Store] Return (start_hour, end_hour) for venue operating hours."""
    venue = _get_venue_config()
    hours = venue.get("operating_hours", {})
    start = hours.get("start") if hours else None
    end = hours.get("end") if hours else None
    if start is None:
        start = _DEFAULTS["operating_hours"]["start"]
    if end is None:
        end = _DEFAULTS["operating_hours"]["end"]
    return (int(start), int(end))


def get_from_email() -> str:
    """[OpenEvent Config Store] Return the sender email for notifications."""
    venue = _get_venue_config()
    return venue.get("from_email") or _DEFAULTS["from_email"]


def get_from_name() -> str:
    """[OpenEvent Config Store] Return the sender name for email headers."""
    venue = _get_venue_config()
    return venue.get("from_name") or _DEFAULTS["from_name"]


def get_frontend_url() -> str:
    """[OpenEvent Config Store] Return the frontend base URL."""
    venue = _get_venue_config()
    return venue.get("frontend_url") or _DEFAULTS["frontend_url"]


def get_currency_regex() -> Pattern[str]:
    """[OpenEvent Config Store] Return compiled regex for currency pattern detection.

    Builds pattern dynamically from currency_code, e.g.:
    CHF -> r"\\b(CHF\\s*\\d+(?:[.,]\\d{1,2})?)\\b"
    """
    code = get_currency_code()
    pattern = rf"\b({re.escape(code)}\s*\d+(?:[.,]\d{{1,2}})?)\b"
    return re.compile(pattern)


def get_all_venue_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return the complete venue configuration dict.

    Used by the API endpoint to expose all settings at once.
    Missing values are filled with defaults.
    """
    venue = _get_venue_config()
    result = dict(_DEFAULTS)  # Start with defaults
    result.update({k: v for k, v in venue.items() if v is not None})
    return result


# =============================================================================
# Site Visit Configuration
# =============================================================================

def _get_site_visit_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load site visit config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("site_visit", {})
    except Exception:
        return {}


def get_site_visit_blocked_dates() -> List[str]:
    """[OpenEvent Config Store] Return additional blocked dates for site visits.

    Returns ISO format date strings (YYYY-MM-DD) that should be blocked
    in addition to event dates. Use for holidays, maintenance days, etc.
    """
    sv = _get_site_visit_config()
    dates = sv.get("blocked_dates")
    if dates is None:
        return list(_SITE_VISIT_DEFAULTS["blocked_dates"])
    return list(dates)


def get_site_visit_slots() -> List[int]:
    """[OpenEvent Config Store] Return available hours for site visits.

    Returns list of hours in 24-hour format (e.g., [10, 14, 16]).
    """
    sv = _get_site_visit_config()
    slots = sv.get("default_slots")
    if slots is None:
        return list(_SITE_VISIT_DEFAULTS["default_slots"])
    return list(slots)


def get_site_visit_weekdays_only() -> bool:
    """[OpenEvent Config Store] Return whether site visits are weekdays only.

    If True, only Monday-Friday are available. If False, weekends allowed.
    """
    sv = _get_site_visit_config()
    val = sv.get("weekdays_only")
    if val is None:
        return _SITE_VISIT_DEFAULTS["weekdays_only"]
    return bool(val)


def get_site_visit_min_days_ahead() -> int:
    """[OpenEvent Config Store] Return minimum days ahead for site visit booking.

    Site visits must be booked at least this many days before the event.
    """
    sv = _get_site_visit_config()
    val = sv.get("min_days_ahead")
    if val is None:
        return _SITE_VISIT_DEFAULTS["min_days_ahead"]
    return int(val)


def get_all_site_visit_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete site visit config with defaults."""
    sv = _get_site_visit_config()
    result = dict(_SITE_VISIT_DEFAULTS)
    result.update({k: v for k, v in sv.items() if v is not None})
    return result


# =============================================================================
# Manager Configuration
# =============================================================================

def _get_manager_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load manager config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("managers", {})
    except Exception:
        return {}


def get_manager_names() -> List[str]:
    """[OpenEvent Config Store] Return registered manager names.

    Used for escalation detection - identifies when clients ask to speak
    with a specific manager by name.
    """
    mgr = _get_manager_config()
    names = mgr.get("names")
    if names is None:
        return list(_MANAGER_DEFAULTS["names"])
    return list(names)


def get_all_manager_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete manager config with defaults."""
    mgr = _get_manager_config()
    result = dict(_MANAGER_DEFAULTS)
    result.update({k: v for k, v in mgr.items() if v is not None})
    return result


# =============================================================================
# Product Configuration
# =============================================================================

def _get_product_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load product config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("products", {})
    except Exception:
        return {}


def get_product_autofill_threshold() -> float:
    """[OpenEvent Config Store] Return similarity threshold for product autofill.

    Products with preference match score >= this threshold are auto-included
    in offers. Range: 0.0 (include everything) to 1.0 (exact match only).
    Default: 0.5 (50% similarity required).
    """
    prod = _get_product_config()
    val = prod.get("autofill_min_score")
    if val is None:
        return _PRODUCT_DEFAULTS["autofill_min_score"]
    return float(val)


def get_all_product_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete product config with defaults."""
    prod = _get_product_config()
    result = dict(_PRODUCT_DEFAULTS)
    result.update({k: v for k, v in prod.items() if v is not None})
    return result


# =============================================================================
# Menus Configuration (Catering)
# =============================================================================

# Default dinner menu options - match current hardcoded behavior in menu_options.py
_MENU_DEFAULTS: Dict[str, Any] = {
    "dinner_options": [
        {
            "menu_name": "Seasonal Garden Trio",
            "courses": 3,
            "vegetarian": True,
            "wine_pairing": True,
            "price": "CHF 92",
            "description": "Charred leek tart, truffle risotto, and citrus pavlova matched with Swiss whites.",
            "available_months": ["december", "january", "february", "march"],
            "season_label": "Available December–March",
            "notes": ["vegetarian"],
            "priority": 1,
        },
        {
            "menu_name": "Alpine Roots Degustation",
            "courses": 3,
            "vegetarian": True,
            "wine_pairing": True,
            "price": "CHF 105",
            "description": "Roasted beet mille-feuille, herb gnocchi, and warm chocolate tart with alpine wine pairing.",
            "available_months": ["november", "december", "january", "february"],
            "season_label": "Available November–February",
            "notes": ["vegetarian"],
            "priority": 2,
        },
        {
            "menu_name": "Lakeview Signature Journey",
            "courses": 3,
            "vegetarian": False,
            "wine_pairing": True,
            "price": "CHF 118",
            "description": "Lake char crudo, veal tenderloin, and Swiss meringue finale with matching wines.",
            "available_months": ["february", "march", "april"],
            "season_label": "Available February–April",
            "notes": ["includes meat & seafood"],
            "priority": 3,
        },
    ],
}


def _get_menus_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load menus config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("menus", {})
    except Exception:
        return {}


def get_dinner_menu_options() -> List[Dict[str, Any]]:
    """[OpenEvent Config Store] Return dinner menu options.

    Returns list of menu dicts with: menu_name, courses, vegetarian,
    wine_pairing, price, description, available_months, season_label,
    notes, priority.

    Empty array in DB means "use built-in defaults".
    """
    menus = _get_menus_config()
    options = menus.get("dinner_options")
    # None or empty array means use defaults
    if not options:
        return list(_MENU_DEFAULTS["dinner_options"])
    return list(options)


def get_all_menus_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete menus config with defaults."""
    menus = _get_menus_config()
    result = dict(_MENU_DEFAULTS)
    result.update({k: v for k, v in menus.items() if v is not None})
    return result


# =============================================================================
# Product Catalog (Room-Availability Mapping)
# =============================================================================

# Default product catalog - maps products to rooms they're available in
_CATALOG_DEFAULTS: Dict[str, Any] = {
    "product_room_map": [
        {"name": "Projector & Screen", "category": "av", "rooms": ["Room A", "Room B", "Room C"]},
        {"name": "Wireless Microphones (pair)", "category": "av", "rooms": ["Room B", "Room C"]},
        {"name": "Flip Chart Pack", "category": "equipment", "rooms": ["Room A", "Room B", "Room C"]},
        {"name": "Hybrid Video Kit", "category": "av", "rooms": ["Room B", "Room C"]},
        {"name": "Stage Lighting Kit", "category": "lighting", "rooms": ["Room C"]},
        {"name": "Breakout Furniture Set", "category": "furniture", "rooms": ["Room C"]},
        {"name": "Facilitator Supplies Bundle", "category": "supplies", "rooms": ["Room A", "Room B"]},
    ],
}


def _get_catalog_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load product catalog config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("catalog", {})
    except Exception:
        return {}


def get_product_room_map() -> List[Dict[str, Any]]:
    """[OpenEvent Config Store] Return product-to-room availability mapping.

    Returns list of dicts with: name, category, rooms (list of room names).

    Empty array in DB means "use built-in defaults".
    """
    catalog = _get_catalog_config()
    mapping = catalog.get("product_room_map")
    # None or empty array means use defaults
    if not mapping:
        return list(_CATALOG_DEFAULTS["product_room_map"])
    return list(mapping)


def get_all_catalog_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete catalog config with defaults."""
    catalog = _get_catalog_config()
    result = dict(_CATALOG_DEFAULTS)
    result.update({k: v for k, v in catalog.items() if v is not None})
    return result


def get_catering_teaser_products() -> List[Dict[str, Any]]:
    """[OpenEvent Config Store] Return popular catering products for teaser messages.

    Reads from products.json and returns the first 2 catering/beverage items
    with their current prices. Used in step3 to suggest popular options.

    Returns:
        List of product dicts with: name, unit_price, unit
    """
    from pathlib import Path
    import json

    products_path = Path(__file__).parent.parent.parent / "data" / "products.json"
    if not products_path.exists():
        # Fallback defaults if products.json missing
        return [
            {"name": "Classic Apéro", "unit_price": 18.0, "unit": "per_person"},
            {"name": "Coffee & Tea Bar", "unit_price": 7.50, "unit": "per_person"},
        ]

    try:
        with open(products_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        products = data.get("products", [])
        # Get first catering item and first beverage item
        catering = next((p for p in products if p.get("category") == "Catering"), None)
        beverage = next((p for p in products if p.get("category") == "Beverages"), None)

        result = []
        for p in [catering, beverage]:
            if p:
                result.append({
                    "name": p.get("name", ""),
                    "unit_price": p.get("unit_price", 0),
                    "unit": p.get("unit", "per_person"),
                })
        return result if result else [
            {"name": "Classic Apéro", "unit_price": 18.0, "unit": "per_person"},
            {"name": "Coffee & Tea Bar", "unit_price": 7.50, "unit": "per_person"},
        ]
    except Exception:
        return [
            {"name": "Classic Apéro", "unit_price": 18.0, "unit": "per_person"},
            {"name": "Coffee & Tea Bar", "unit_price": 7.50, "unit": "per_person"},
        ]


# =============================================================================
# FAQ/Q&A Items Configuration
# =============================================================================

# Default FAQ items - venue-specific answers to common questions
_FAQ_DEFAULTS: Dict[str, Any] = {
    "items": [
        {"category": "Parking", "question": "Where can guests park?",
         "answer": "The Atelier offers underground parking with 50 spaces available for event guests. Additional street parking is available nearby. Parking vouchers can be arranged for your guests at CHF 5 per vehicle for the full event duration."},
        {"category": "Parking", "question": "Is there disabled parking available?",
         "answer": "Yes, we have 3 designated disabled parking spaces directly at the main entrance with level access to all event spaces. These spaces are wider than standard spots and connect to our accessible routes throughout the venue."},
        {"category": "Parking", "question": "Can we reserve parking spaces for VIP guests?",
         "answer": "Absolutely! We can reserve specific parking spaces closest to the entrance for your VIP guests. Please let us know how many VIP spaces you need when finalizing your booking."},
        {"category": "Catering", "question": "Can you accommodate dietary restrictions?",
         "answer": "Absolutely! All our menus can be adapted for vegetarian, vegan, gluten-free, and other dietary requirements. Our chef team is experienced in handling allergies and religious dietary needs. Please inform us of any restrictions when booking, and we'll create appropriate alternatives."},
        {"category": "Catering", "question": "Can we bring our own catering?",
         "answer": "While we prefer to use our in-house catering team who know our facilities best, we can accommodate external catering for special circumstances. A kitchen usage fee of CHF 500 applies, and external caterers must provide food safety certification."},
        {"category": "Booking", "question": "How far in advance should I book?",
         "answer": "We recommend booking at least 4 weeks in advance for the best availability. For peak seasons (May-June, September-October, and December), 6-8 weeks advance booking is advisable. We can sometimes accommodate last-minute requests, so always feel free to ask!"},
        {"category": "Booking", "question": "What's your cancellation policy?",
         "answer": "Cancellations made more than 30 days before the event: Full refund minus CHF 200 admin fee. 14-30 days: 50% refund. Less than 14 days: No refund, but we'll try to reschedule if possible. We strongly recommend event insurance for large bookings."},
        {"category": "Equipment", "question": "What AV equipment is included?",
         "answer": "All rooms include: HD projector or LED screen, wireless microphones, sound system, WiFi, and basic lighting. Additional equipment like recording devices, live streaming setup, or special lighting can be arranged for an extra fee."},
        {"category": "Equipment", "question": "Can we live stream our event?",
         "answer": "Yes! Rooms B, C, and Punkt.Null are equipped with live streaming capabilities. We provide the technical setup and can assign a technician to manage the stream. Streaming to up to 500 viewers is included; larger audiences require upgraded bandwidth."},
        {"category": "Access", "question": "Is the venue wheelchair accessible?",
         "answer": "Yes, The Atelier is fully wheelchair accessible. We have ramps to all entrances, an elevator to all floors, accessible restrooms on each level, and adjustable-height presentation equipment. Please let us know about any specific accessibility needs."},
        {"category": "Access", "question": "How early can we access the venue for setup?",
         "answer": "Standard bookings include 1 hour setup time. For elaborate setups, we can arrange early access from 2-4 hours before your event start time for an additional CHF 100 per hour. Our team can also assist with setup if needed."},
    ],
}


def _get_faq_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Load FAQ config from database."""
    try:
        db = load_db(DB_PATH)
        config = db.get("config", {})
        return config.get("faq", {})
    except Exception:
        return {}


def get_faq_items() -> List[Dict[str, Any]]:
    """[OpenEvent Config Store] Return FAQ items.

    Returns list of dicts with: category, question, answer.

    Empty array in DB means "use built-in defaults".
    """
    faq = _get_faq_config()
    items = faq.get("items")
    # None or empty array means use defaults
    if not items:
        return list(_FAQ_DEFAULTS["items"])
    return list(items)


def get_all_faq_config() -> Dict[str, Any]:
    """[OpenEvent Config Store] Return complete FAQ config with defaults."""
    faq = _get_faq_config()
    result = dict(_FAQ_DEFAULTS)
    result.update({k: v for k, v in faq.items() if v is not None})
    return result
