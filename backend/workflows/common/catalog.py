from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .capacity import fits_capacity, layout_capacity


def _data_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _rooms_payload() -> Dict[str, Any]:
    path = _data_root() / "data" / "rooms.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _room_entries() -> Iterable[Dict[str, Any]]:
    payload = _rooms_payload()
    rooms = payload.get("rooms")
    if isinstance(rooms, list):
        return rooms
    return []


def _catering_payload() -> Dict[str, Any]:
    path = _data_root() / "data" / "products.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalise_feature(value: str) -> str:
    return value.strip().lower()


def _feature_matches(feature: str, entry: Dict[str, Any]) -> bool:
    target = _normalise_feature(feature)
    if not target:
        return False
    candidates: List[str] = []
    candidates.extend(entry.get("features") or [])
    candidates.extend(entry.get("equipment") or [])
    for raw in candidates:
        if target in _normalise_feature(str(raw)):
            return True
    return False


def _max_capacity(entry: Dict[str, Any]) -> Optional[int]:
    # Support both flat (capacity_max) and nested (capacity.max) formats
    value = entry.get("capacity_max")
    if value is None:
        block = entry.get("capacity") or {}
        value = block.get("max")
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def list_rooms_by_feature(
    feature: str,
    min_capacity: Optional[int] = None,
    layout: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return rooms that expose the requested feature and capacity bounds."""

    matches: List[Dict[str, Any]] = []
    for entry in _room_entries():
        name = entry.get("name")
        if not name or not _feature_matches(feature, entry):
            continue
        max_cap = _max_capacity(entry)
        if min_capacity is not None and max_cap is not None and max_cap < int(min_capacity):
            continue
        if min_capacity is not None and not fits_capacity(name, min_capacity, layout):
            continue
        layout_cap = layout_capacity(name, layout)
        matches.append(
            {
                "name": name,
                "max_capacity": max_cap,
                "layout_capacity": layout_cap,
                "features": list(entry.get("features") or []),
                "equipment": list(entry.get("equipment") or []),
            }
        )
    matches.sort(key=lambda item: (item["max_capacity"] or 0, item["name"]))
    return matches


def list_room_features(room_id: str) -> List[str]:
    """Expose features and equipment for a given room."""

    for entry in _room_entries():
        if str(entry.get("name")).strip().lower() == str(room_id).strip().lower():
            features = list(entry.get("features") or [])
            equipment = list(entry.get("equipment") or [])
            combined = features + equipment
            seen = set()
            ordered: List[str] = []
            for item in combined:
                key = item.strip()
                if key and key not in seen:
                    seen.add(key)
                    ordered.append(key)
            return ordered
    return []


# Database-backed product catalog accessor - see config_store.py for defaults
from backend.workflows.io.config_store import get_product_room_map


def _get_product_catalog() -> List[Dict[str, Any]]:
    """Load product catalog from database config (with fallback defaults)."""
    return get_product_room_map()


# Legacy constant - now loads from database config
# Kept for backward compatibility but prefer using _get_product_catalog() for fresh data
_PRODUCT_CATALOG: List[Dict[str, Any]] = _get_product_catalog()


def list_products(
    room_id: Optional[str] = None,
    categories: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Return add-on products optionally scoped to a room or category."""

    category_filter = {str(cat).strip().lower() for cat in categories or [] if str(cat).strip()}
    room_norm = str(room_id).strip().lower() if room_id else None
    items: List[Dict[str, Any]] = []
    for entry in _PRODUCT_CATALOG:
        entry_rooms = entry.get("rooms") or []
        if room_norm:
            normed = {str(r).strip().lower() for r in entry_rooms}
            if room_norm not in normed:
                continue
        if category_filter:
            if str(entry.get("category", "")).strip().lower() not in category_filter:
                continue
        items.append(
            {
                "name": entry["name"],
                "category": entry.get("category"),
            }
        )
    items.sort(key=lambda item: (item.get("category") or "", item["name"]))
    return items


def list_catering(
    room_id: Optional[str] = None,
    date_token: Optional[str] = None,
    categories: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Return catering options. Room/date parameters tailor messaging upstream but do not
    currently alter availability.
    """

    category_filter = {str(cat).strip().lower() for cat in categories or [] if str(cat).strip()}
    payload = _catering_payload()
    packages = payload.get("catering_packages") or []
    add_ons = payload.get("add_ons") or []
    beverages = payload.get("beverages") or {}
    results: List[Dict[str, Any]] = []

    for pkg in packages:
        entry = {
            "name": pkg.get("name"),
            "category": "package",
            "price_per_person": pkg.get("price_per_person"),
            "description": pkg.get("description"),
        }
        if category_filter and entry["category"] not in category_filter:
            continue
        results.append(entry)

    for section, items in beverages.items():
        label = "beverages"
        for item in items or []:
            entry = {
                "name": item.get("name"),
                "category": label,
                "price": item.get("price_per_person") or item.get("price_per_glass") or item.get("price_per_bottle"),
                "options": item.get("options"),
            }
            if category_filter and label not in category_filter:
                continue
            results.append(entry)

    for addon in add_ons:
        entry = {
            "name": addon.get("name"),
            "category": "add-on",
            "price": addon.get("price"),
            "description": addon.get("description"),
        }
        if category_filter and entry["category"] not in category_filter:
            continue
        results.append(entry)

    results.sort(key=lambda item: (item.get("category") or "", item.get("name") or ""))
    return results


def _resolve_anchor_date(anchor_month: Optional[int], anchor_day: Optional[int]) -> date:
    today = date.today()
    if not anchor_month:
        return today
    year = today.year
    if anchor_month < today.month or (anchor_month == today.month and anchor_day and anchor_day < today.day):
        year += 1
    safe_day = max(1, min(anchor_day or 1, 28))
    return date(year, anchor_month, safe_day)


def list_free_dates(
    anchor_month: Optional[int] = None,
    anchor_day: Optional[int] = None,
    count: int = 5,
    *,
    db: Optional[Dict[str, Any]] = None,
    preferred_room: Optional[str] = None,
) -> List[str]:
    """
    Produce deterministic candidate dates.

    When a database is provided we reuse the workflow `suggest_dates` helper to ensure
    availability-aware results. Otherwise we fall back to evenly spaced weekly slots.
    """

    if count <= 0:
        return []

    start_date = _resolve_anchor_date(anchor_month, anchor_day)
    preferred = preferred_room or "Room A"
    if db is not None:
        try:
            from backend.workflows.steps.step1_intake.condition.checks import suggest_dates
        except Exception:
            suggest_dates = None  # type: ignore
        if suggest_dates is not None:
            start_iso = datetime.combine(start_date, datetime.min.time()).isoformat() + "Z"
            candidates = suggest_dates(
                db,
                preferred_room=preferred,
                start_from_iso=start_iso,
                days_ahead=60,
                max_results=count,
            )
            if candidates:
                return candidates[:count]

    # Fallback: weekly cadence anchored to requested month/day.
    results: List[str] = []
    cursor = start_date
    if cursor <= date.today():
        cursor = date.today() + timedelta(days=7)
    while len(results) < count:
        results.append(cursor.strftime("%d.%m.%Y"))
        cursor += timedelta(days=7)
    return results


__all__ = [
    "list_rooms_by_feature",
    "list_room_features",
    "list_products",
    "list_catering",
    "list_free_dates",
]
