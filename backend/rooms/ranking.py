from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.workflows.steps.step3_room_availability.db_pers import load_rooms_config

_STATUS_WEIGHTS = {
    "available": 2,
    "option": 1,
}

_COFFEE_TOKENS = {"coffee service", "coffee", "coffee & tea", "coffee/tea"}


@dataclass
class RoomProfile:
    room: str
    status: str
    date_score: int
    coffee_badge: str
    coffee_score: int
    coffee_available: bool
    requirements_badges: Dict[str, str]
    requirements_score: float
    capacity_badge: str
    capacity_fit: int
    capacity: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room": self.room,
            "status": self.status,
            "date_score": self.date_score,
            "coffee_badge": self.coffee_badge,
            "coffee_score": self.coffee_score,
            "coffee_available": self.coffee_available,
            "requirements_badges": dict(self.requirements_badges),
            "requirements_score": self.requirements_score,
            "capacity_badge": self.capacity_badge,
            "capacity_fit": self.capacity_fit,
            "capacity": self.capacity,
        }


def rank(
    date_iso: Optional[str],
    pax: Optional[int],
    *,
    status_map: Dict[str, str],
    needs_catering: Optional[Sequence[str]] = None,
    needs_products: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Compute deterministic room rankings with badges for downstream rendering."""

    config_map = _config_by_name()
    requested_coffee = _has_coffee_request(needs_catering)
    requested_products = _normalise_products(needs_products)

    profiles: List[RoomProfile] = []
    for room, status in status_map.items():
        config = config_map.get(room, {})
        normalized_status = str(status).strip().lower()
        date_score = _STATUS_WEIGHTS.get(normalized_status, 0)
        capacity_value = _room_capacity(config)
        capacity_fit_flag = 1 if pax is None or (capacity_value is not None and capacity_value >= pax) else 0
        capacity_badge = "✓" if capacity_fit_flag else "✗"

        coffee_available = _supports_coffee(config)
        coffee_badge = "✓" if coffee_available else "✗"
        coffee_score = 1 if coffee_available else 0

        requirements_badges, requirements_score = _requirements_badges(config, requested_products, pax)

        profile = RoomProfile(
            room=room,
            status=status,
            date_score=date_score,
            coffee_badge=coffee_badge,
            coffee_score=coffee_score,
            coffee_available=coffee_available,
            requirements_badges=requirements_badges,
            requirements_score=requirements_score,
            capacity_badge=capacity_badge,
            capacity_fit=capacity_fit_flag,
            capacity=capacity_value,
        )
        profiles.append(profile)

    profiles.sort(
        key=lambda entry: (
            -entry.date_score,
            -entry.coffee_score,
            -entry.requirements_score,
            -entry.capacity_fit,
            entry.room,
        )
    )
    return [profile.to_dict() for profile in profiles]


def _config_by_name() -> Dict[str, Dict[str, Any]]:
    rooms = load_rooms_config() or []
    return {str(room.get("name")): room for room in rooms if room.get("name")}


def _has_coffee_request(needs_catering: Optional[Sequence[str]]) -> bool:
    if not needs_catering:
        return False
    for token in needs_catering:
        if str(token).strip().lower() in _COFFEE_TOKENS:
            return True
    return False


def _normalise_products(needs_products: Optional[Sequence[str]]) -> List[str]:
    if not needs_products:
        return []
    normalised: List[str] = []
    for token in needs_products:
        cleaned = str(token).strip().lower()
        if not cleaned:
            continue
        normalised.append(cleaned)
    return normalised


def _room_capacity(config: Dict[str, Any]) -> Optional[int]:
    capacity = config.get("capacity_max") or config.get("capacity") or config.get("max_capacity")
    if capacity is None:
        return None
    try:
        return int(capacity)
    except (TypeError, ValueError):
        return None


def _supports_coffee(config: Dict[str, Any]) -> bool:
    services = _lower_tokens(config.get("services"))
    features = _lower_tokens(config.get("features"))
    return any("coffee" in token for token in services or features)


def _requirements_badges(
    config: Dict[str, Any],
    requested_products: Sequence[str],
    pax: Optional[int],
) -> Tuple[Dict[str, str], float]:
    badges: Dict[str, str] = {}
    score = 0.0
    for product in requested_products:
        if product in {"u-shape", "u_shape", "ushape"}:
            badge, value = _u_shape_badge(config, pax)
        elif product in {"projector", "projection"}:
            badge, value = _projector_badge(config)
        else:
            badge, value = ("~", 0.0)
        badges[_canonical_product_key(product)] = badge
        score += value
    return badges, score


def _u_shape_badge(config: Dict[str, Any], pax: Optional[int]) -> Tuple[str, float]:
    layout_map = config.get("capacity_by_layout") or {}
    capacity = None
    for key in ("u_shape", "u-shape", "ushape"):
        if key in layout_map:
            capacity = layout_map[key]
            break
    if capacity is None:
        return "✗", 0.0
    try:
        capacity_value = int(capacity)
    except (TypeError, ValueError):
        capacity_value = None
    if pax is None or capacity_value is None:
        return "✓", 1.0
    if capacity_value >= pax:
        return "✓", 1.0
    return "~", 0.5


def _projector_badge(config: Dict[str, Any]) -> Tuple[str, float]:
    features = _lower_tokens(config.get("features"))
    if any(token in {"projector", "beamer"} for token in features):
        return "✓", 1.0
    if "screen" in features or "projection" in features:
        return "~", 0.5
    return "✗", 0.0


def _lower_tokens(values: Optional[Iterable[Any]]) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    tokens: List[str] = []
    for value in values:
        if value is None:
            continue
        tokens.append(str(value).strip().lower())
    return tokens


def _canonical_product_key(product: str) -> str:
    token = str(product).strip().lower()
    if token in {"u_shape", "u-shape", "ushape"}:
        return "u-shape"
    if token in {"projector", "projection"}:
        return "projector"
    return token
