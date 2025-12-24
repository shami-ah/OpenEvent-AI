from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.services.products import list_product_records
from backend.prefs.semantics import normalize_catering, normalize_products

PreferencePayload = Dict[str, Any]


def extract_preferences(user_info: Dict[str, Any], raw_text: Optional[str] = None) -> Optional[PreferencePayload]:
    """
    Normalise structured product/menu preferences captured during intake and
    derive quick room recommendations so downstream steps can reuse them.
    """

    if not isinstance(user_info, dict):
        return None

    raw_wish_products = _collect_wish_products(user_info)
    raw_detected = _detect_raw_text_preferences(raw_text)
    if raw_detected:
        for item in raw_detected:
            if item not in raw_wish_products:
                raw_wish_products.append(item)
    catering_sources: List[str] = []
    catering_pref = user_info.get("catering")
    if isinstance(catering_pref, str) and catering_pref.strip():
        catering_sources.append(catering_pref)
    catering_sources.extend(raw_wish_products)
    catering_tokens = normalize_catering(catering_sources)
    catering_lower = {token.lower() for token in catering_tokens}

    wish_products = [item for item in raw_wish_products if item.lower() not in catering_lower]

    product_sources: List[str] = list(wish_products)
    layout = user_info.get("layout")
    if isinstance(layout, str) and layout.strip():
        layout_lower = layout.strip().lower()
        if layout_lower not in {item.lower() for item in product_sources}:
            product_sources.append(layout)
    notes = user_info.get("notes")
    if isinstance(notes, str) and notes.strip():
        product_sources.append(notes)

    product_tokens = normalize_products(product_sources)

    if not wish_products and product_tokens:
        wish_products = [token.title() for token in product_tokens]

    keywords = _collect_keywords(user_info, wish_products)

    if not wish_products and not keywords and not catering_tokens and not product_tokens:
        return None

    default_hint = wish_products[0] if wish_products else (product_tokens[0].title() if product_tokens else "Products available")
    preferences: PreferencePayload = {
        "wish_products": wish_products,
        "keywords": keywords,
        "default_hint": default_hint,
    }
    if catering_tokens:
        preferences["catering"] = catering_tokens
    if product_tokens:
        preferences["products"] = product_tokens

    scoring_wishes: List[str] = []
    scoring_wishes.extend(wish_products)
    scoring_wishes.extend(
        token.title()
        for token in product_tokens
        if token and token.title() not in scoring_wishes
    )
    scoring_wishes.extend(
        token.title()
        for token in catering_tokens
        if token and token.title() not in scoring_wishes
    )
    if not scoring_wishes:
        scoring_wishes = [token.title() for token in product_tokens]
    if not scoring_wishes and catering_tokens:
        scoring_wishes = [token.title() for token in catering_tokens]
    if scoring_wishes:
        recommendations = _score_rooms_by_products(scoring_wishes)
        if recommendations:
            preferences["room_recommendations"] = recommendations
            preferences["room_similarity"] = {entry["room"]: entry["score"] for entry in recommendations}
            preferences["room_match_breakdown"] = {
                entry["room"]: {
                    "matched": entry["matched"],
                    "closest": entry.get("closest", []),
                    "missing": entry["missing"],
                    "matches_detail": entry.get("matches_detail", []),
                    "alternatives": entry.get("alternatives", []),
                }
                for entry in recommendations
            }

    return preferences


def _collect_wish_products(user_info: Dict[str, Any]) -> List[str]:
    result: List[str] = []

    def _append(values: Iterable[str]) -> None:
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned.lower() not in {"none", "not specified"} and cleaned not in result:
                result.append(cleaned)

    raw_wishes = user_info.get("wish_products")
    _append(_normalise_sequence(raw_wishes))

    products_add = user_info.get("products_add")
    if isinstance(products_add, list):
        extracted: List[str] = []
        for entry in products_add:
            if isinstance(entry, dict) and entry.get("name"):
                extracted.append(str(entry["name"]))
            elif isinstance(entry, str):
                extracted.append(entry)
        _append(extracted)

    catering_pref = user_info.get("catering")
    if isinstance(catering_pref, str) and catering_pref.strip():
        _append([catering_pref])

    notes = user_info.get("notes")
    if isinstance(notes, str) and notes.strip():
        fragments = re.split(r"(?:[\n\r]+|[•\-–]\s*)", notes)
        cleaned = [fragment.strip(" .") for fragment in fragments if fragment and fragment.strip()]
        _append(cleaned)

    layout_pref = user_info.get("layout")
    if isinstance(layout_pref, str) and layout_pref.strip():
        _append([layout_pref])

    event_type = user_info.get("type")
    if isinstance(event_type, str) and event_type.strip():
        _append([event_type])

    return result[:10]


def _detect_raw_text_preferences(raw_text: Optional[str]) -> List[str]:
    """Heuristically extract missing preference hints from the raw message."""

    if not raw_text:
        return []
    text = raw_text.lower()
    detected: List[str] = []

    def _mark(flag: bool, label: str) -> None:
        if flag and label not in detected:
            detected.append(label)

    _mark("finger-food" in text or "finger food" in text, "finger food catering")
    _mark("standing reception" in text, "standing reception")
    has_cocktail = "cocktail" in text
    cocktail_context = has_cocktail and any(token in text for token in ("setup", "bar", "reception", "evening"))
    _mark(cocktail_context or "bar area" in text, "cocktail bar")
    _mark("bar area" in text, "bar area")
    _mark("background music" in text, "background music")
    _mark("live music" in text, "background music")
    _mark("sound system" in text, "sound system")
    return detected[:10]


def _collect_keywords(user_info: Dict[str, Any], wish_products: Sequence[str]) -> List[str]:
    tokens: List[str] = []

    def _extend(text: Optional[Any]) -> None:
        if not text:
            return
        for token in _tokenize(str(text)):
            if len(token) >= 3 and token not in tokens:
                tokens.append(token)

    for wish in wish_products:
        _extend(wish)

    for field in ("notes", "catering", "layout", "type"):
        _extend(user_info.get(field))

    return tokens[:20]


def _normalise_sequence(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        chunks = re.split(r"[,\n;]+", value)
        return [chunk.strip() for chunk in chunks if chunk.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _score_rooms_by_products(wish_products: Sequence[str]) -> List[Dict[str, Any]]:
    catalog = _room_catalog()
    rooms_data = {room["name"]: room for room in _load_rooms()}
    recommendations: List[Dict[str, Any]] = []

    for room, data in catalog.items():
        phrases = data["phrases"]
        variants_map = data.get("product_variants") or {}
        # Get room's native features, services, and layout types for direct matching
        room_info = rooms_data.get(room, {})
        room_features = set(_normalise_phrase(f) for f in (room_info.get("features") or []))
        room_services = set(_normalise_phrase(s) for s in (room_info.get("services") or []))
        # Include layout types (workshop, theatre, u_shape, etc.) as matchable features
        room_layouts = set(_normalise_phrase(k) for k in (room_info.get("capacity_by_layout") or {}).keys())
        room_all_features = room_features | room_services | room_layouts

        score = 0.0
        matched: List[str] = []  # Strong matches (>= 0.85)
        closest: List[str] = []  # Moderate matches (0.65-0.85) - "comes closest to your X"
        missing: List[str] = []
        matches_detail: List[Dict[str, Any]] = []
        alternatives_detail: List[Dict[str, Any]] = []
        matched_lower: Set[str] = set()
        closest_lower: Set[str] = set()
        alternatives_seen: Set[Tuple[str, str]] = set()
        for wish in wish_products:
            wish_normalized = _normalise_phrase(wish)

            # First, check direct match against room features/services
            feature_match = _match_against_features(wish_normalized, room_all_features)
            if feature_match:
                score += 1.0
                feature_label = wish.title()
                if feature_label.lower() not in matched_lower:
                    matched.append(feature_label)
                    matched_lower.add(feature_label.lower())
                matches_detail.append(_make_match_entry(wish, feature_label, 1.0))
                continue

            # Then check product catalog matches
            top_matches = _top_product_matches(wish, variants_map)
            if not top_matches:
                ratio, label = _best_phrase_match(wish, phrases)
                if ratio >= 0.65 and label:
                    score += 0.5
                    if label.lower() not in matched_lower:
                        matched.append(label)
                        matched_lower.add(label.lower())
                    matches_detail.append(_make_match_entry(wish, label, ratio))
                else:
                    missing.append(wish)
                continue

            best_ratio, best_product = top_matches[0]
            if best_ratio >= 0.85:
                # Strong match - "includes the X you mentioned"
                score += 1.0
                if best_product.lower() not in matched_lower:
                    matched.append(best_product)
                    matched_lower.add(best_product.lower())
                matches_detail.append(_make_match_entry(wish, best_product, best_ratio))
            elif best_ratio >= 0.65:
                # Moderate match - "X comes closest to your Y preference"
                score += 0.5
                if best_product.lower() not in closest_lower:
                    closest.append(f"{best_product} (closest to {wish})")
                    closest_lower.add(best_product.lower())
                matches_detail.append(_make_match_entry(wish, best_product, best_ratio))
            elif best_ratio >= 0.5:
                missing.append(wish)
                entry = _make_match_entry(wish, best_product, best_ratio)
                key = (entry["wish"], entry["product"].lower())
                if key not in alternatives_seen:
                    alternatives_detail.append(entry)
                    alternatives_seen.add(key)
            else:
                missing.append(wish)

            for ratio, product_name in top_matches[1:]:
                if ratio < 0.5:
                    continue
                key = (wish, product_name.lower())
                if product_name.lower() in matched_lower or key in alternatives_seen:
                    continue
                alternatives_detail.append(_make_match_entry(wish, product_name, ratio))
                alternatives_seen.add(key)
        recommendations.append(
            {
                "room": room,
                "score": round(score, 3),
                "matched": matched,
                "closest": closest,  # Moderate matches with context
                "missing": missing,
                "matches_detail": matches_detail,
                "alternatives": alternatives_detail,
            }
        )

    recommendations.sort(key=lambda entry: (-entry["score"], entry["room"]))
    return recommendations[:5]


def _match_against_features(wish_normalized: str, features: Set[str]) -> bool:
    """Check if a wish matches any room feature using fuzzy matching."""
    if not wish_normalized or not features:
        return False
    # Direct containment check
    for feature in features:
        if wish_normalized in feature or feature in wish_normalized:
            return True
        # Handle common variations: "sound system" vs "sound_system"
        wish_no_space = wish_normalized.replace(" ", "")
        feature_no_space = feature.replace(" ", "")
        if wish_no_space in feature_no_space or feature_no_space in wish_no_space:
            return True
    # Fuzzy match for close variations
    for feature in features:
        ratio = difflib.SequenceMatcher(a=wish_normalized, b=feature).ratio()
        if ratio >= 0.8:
            return True
    return False


def _best_phrase_match(needle: str, phrases: Dict[str, str]) -> Tuple[float, Optional[str]]:
    if not needle:
        return 0.0, None
    target = _normalise_phrase(needle)
    if not target:
        return 0.0, None
    best_ratio = 0.0
    best_label: Optional[str] = None
    for variant, label in phrases.items():
        if not variant:
            continue
        if target == variant:
            return 1.0, label
        if target in variant or variant in target:
            ratio = 0.92
        else:
            ratio = difflib.SequenceMatcher(a=target, b=variant).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_label = label
    return best_ratio, best_label


def _top_product_matches(
    wish: str,
    variants_map: Dict[str, Sequence[str]],
    *,
    limit: int = 3,
) -> List[Tuple[float, str]]:
    needle = _normalise_phrase(wish)
    if not needle:
        return []
    scored: List[Tuple[float, str]] = []
    for product, variants in variants_map.items():
        ratios = [_similarity_ratio(needle, variant) for variant in variants if variant]
        if not ratios:
            continue
        best_ratio = max(ratios)
        scored.append((best_ratio, product))
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return scored[:limit]


def _similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def _make_match_entry(wish: str, product: str, ratio: float) -> Dict[str, Any]:
    return {
        "wish": wish,
        "product": product,
        "score": round(float(ratio), 3),
    }


def _normalise_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


@lru_cache(maxsize=1)
def _room_catalog() -> Dict[str, Dict[str, Any]]:
    rooms = _load_rooms()
    room_products = {}
    for room in rooms:
        # Collect all matchable features: features + services + layout types
        features = list(room.get("features") or [])
        features.extend(room.get("services") or [])
        # Include capacity_by_layout keys (e.g., "workshop", "theatre", "u_shape")
        # These are valid room capabilities that clients may request
        layout_keys = list((room.get("capacity_by_layout") or {}).keys())
        features.extend(layout_keys)
        room_products[room["name"]] = {
            "phrases": {},
            "features": features,
            "product_variants": {},
        }
    room_ids = {room.get("id", "").strip().lower(): room["name"] for room in rooms if room.get("id")}
    room_aliases = {room["name"].strip().lower(): room["name"] for room in rooms}
    product_records = list_product_records()

    for record in product_records:
        variants = [record.name] + [syn for syn in record.synonyms if syn]
        variants = [variant for variant in variants if variant]
        base_tokens = set()
        for variant in variants:
            base_tokens.update(_tokenize(variant))
        if record.category:
            base_tokens.update(_tokenize(record.category))

        unavailable = {
            room_ids.get(str(room_id).strip().lower())
            or room_aliases.get(str(room_id).strip().lower())
            for room_id in record.unavailable_in
        }
        available_rooms = [room for room in room_products if room not in unavailable]

        for room in available_rooms:
            phrases = room_products[room]["phrases"]
            variants_map = room_products[room]["product_variants"]
            for variant in variants:
                normalized = _normalise_phrase(variant)
                if normalized:
                    phrases.setdefault(normalized, record.name)
                    variants_map.setdefault(record.name, set()).add(normalized)
            for token in base_tokens:
                if len(token) >= 3:
                    phrases.setdefault(token, record.name)
                    variants_map.setdefault(record.name, set()).add(token)

    for entry in room_products.values():
        variants_map = entry.get("product_variants") or {}
        for product_name, variants in list(variants_map.items()):
            variants_map[product_name] = sorted(variants)

    return room_products


@lru_cache(maxsize=1)
def _load_rooms() -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parents[2] / "rooms.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = payload.get("rooms")
    if not isinstance(rooms, list):
        return []
    normalised: List[Dict[str, Any]] = []
    for entry in rooms:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        normalised.append(entry)
    return normalised


__all__ = ["extract_preferences"]
