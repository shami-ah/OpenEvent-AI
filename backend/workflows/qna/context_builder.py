from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

EffectiveSource = str  # "Q", "C", "F", "UNUSED"


@dataclass
class EffectiveVariable:
    value: Any
    source: EffectiveSource
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QnAContext:
    intent: str
    subtype: str
    effective: Dict[str, EffectiveVariable]
    exclude_rooms: List[str]
    base_date: Optional[date]
    handled: bool
    unresolved: List[str]
    case_tags: Dict[str, List[str]] = field(default_factory=dict)


CASE_MAP: Dict[str, Dict[str, List[str]]] = {
    "room_capacity_static": {"N": ["N1", "N9"], "D": ["D9"], "P": [], "R": ["R1"]},
    "catalog_by_capacity": {"N": ["N2", "N7", "N10"], "D": ["D9"], "P": [], "R": ["R8"]},
    "room_list_for_us": {"N": ["N3", "N8"], "D": ["D2", "D5"], "P": ["P2"], "R": ["R5"]},
    "room_specific_capacity_check": {"N": ["N4", "N5"], "D": ["D9"], "P": [], "R": ["R1"]},
    "room_capacity_delta": {"N": ["N4"], "D": ["D9"], "P": [], "R": ["R4"]},
    "room_specific_availability": {"N": ["N6", "N9"], "D": ["D4", "D7"], "P": [], "R": ["R7"]},
    "room_recommendation_by_month": {"N": ["N3"], "D": ["D6"], "P": ["P2"], "R": ["R5"]},
    "date_pattern_availability": {"N": ["N6", "N8"], "D": ["D1"], "P": ["P1"], "R": ["R5"]},
    "date_pattern_availability_general": {"N": ["N6", "N8"], "D": ["D8"], "P": [], "R": ["R5"]},
    "room_catalog_with_products": {"N": ["N2", "N7"], "D": ["D9"], "P": ["P1"], "R": ["R8"]},
    "room_feature_truth": {"N": ["N9"], "D": ["D9"], "P": [], "R": ["R2"]},
    "room_product_truth": {"N": ["N9"], "D": ["D9"], "P": ["P3"], "R": ["R3"]},
    "room_followup_same_context": {"N": ["N6", "N8"], "D": ["D4", "D7"], "P": ["P2"], "R": ["R7"]},
    "room_exclusion_followup": {"N": ["N3", "N8"], "D": ["D2"], "P": ["P2"], "R": ["R6"]},
    "product_catalog": {"N": ["N9"], "D": ["D9"], "P": ["P5"], "R": ["R5"]},
    "product_truth": {"N": ["N9"], "D": ["D9"], "P": ["P6"], "R": ["R5"]},
    "product_recommendation_for_us": {"N": ["N8"], "D": ["D2"], "P": ["P7"], "R": ["R5"]},
    "repertoire_check": {"N": ["N9"], "D": ["D3"], "P": ["P4"], "R": ["R5"]},
    "non_event_info": {"N": ["N9"], "D": ["D9"], "P": [], "R": ["R5"]},
    "update_candidate": {"N": ["N9"], "D": ["D9"], "P": [], "R": ["R9"]},
}

_DEFAULT_CASE_TAGS = {"N": [], "D": [], "P": [], "R": []}


def build_qna_context(
    qna_intent: str,
    qna_subtype: str,
    q_values: Dict[str, Any],
    captured_state: Dict[str, Any],
    *,
    now_fn: Callable[[], date] = date.today,
) -> QnAContext:
    case_tags = CASE_MAP.get(qna_subtype, _DEFAULT_CASE_TAGS)
    effective = _empty_effective()
    exclude_rooms = _normalize_list(q_values.get("exclude_rooms"))
    unresolved: List[str] = []

    if qna_intent == "update_candidate" or qna_subtype == "update_candidate":
        return QnAContext(
            intent=qna_intent,
            subtype=qna_subtype,
            effective=effective,
            exclude_rooms=exclude_rooms,
            base_date=None,
            handled=False,
            unresolved=["update_flow"],
            case_tags=case_tags,
        )

    effective["N"], n_unresolved = _resolve_attendees(qna_subtype, q_values, captured_state)
    if n_unresolved:
        unresolved.append(n_unresolved)

    effective["D"], d_unresolved = _resolve_date(qna_subtype, q_values, captured_state, now_fn)
    if d_unresolved:
        unresolved.append(d_unresolved)

    effective["R"], r_unresolved = _resolve_room(qna_subtype, q_values, captured_state)
    if r_unresolved:
        unresolved.append(r_unresolved)

    effective["P"], p_unresolved = _resolve_products(qna_subtype, q_values, captured_state)
    if p_unresolved:
        unresolved.append(p_unresolved)

    base_date = _derive_base_date(effective["D"], now_fn)

    return QnAContext(
        intent=qna_intent,
        subtype=qna_subtype,
        effective=effective,
        exclude_rooms=exclude_rooms,
        base_date=base_date,
        handled=True,
        unresolved=unresolved,
        case_tags=case_tags,
    )


def _empty_effective() -> Dict[str, EffectiveVariable]:
    return {
        "D": EffectiveVariable(value=None, source="UNUSED"),
        "N": EffectiveVariable(value=None, source="UNUSED"),
        "R": EffectiveVariable(value=None, source="UNUSED"),
        "P": EffectiveVariable(value=None, source="UNUSED"),
    }


def _resolve_attendees(
    subtype: str,
    q_values: Dict[str, Any],
    captured_state: Dict[str, Any],
) -> Tuple[EffectiveVariable, Optional[str]]:
    q_exact = _to_int(q_values.get("n_exact"))
    q_range = _normalize_range(q_values.get("n_range"))
    captured = _to_int(captured_state.get("attendees"))

    if subtype in {
        "room_capacity_static",
        "room_feature_truth",
        "room_product_truth",
        "product_catalog",
        "product_truth",
        "repertoire_check",
    }:
        return EffectiveVariable(value=None, source="UNUSED"), None

    # non_event_info: use captured state if available (enables fallback room queries)
    if subtype == "non_event_info":
        if captured is not None:
            return EffectiveVariable(value=captured, source="C", meta={"fallback": True}), None
        return EffectiveVariable(value=None, source="UNUSED"), None

    if subtype in {"catalog_by_capacity", "room_catalog_with_products"}:
        if q_range:
            return EffectiveVariable(value=q_range, source="Q", meta={"kind": "range"}), None
        if q_exact is not None:
            return EffectiveVariable(value=q_exact, source="Q"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    if subtype in {"room_capacity_delta"}:
        meta: Dict[str, Any] = {"scenario": True}
        if captured is None:
            return EffectiveVariable(value=None, source="UNUSED", meta=meta), "attendees"
        delta = _to_int(q_values.get("n_exact"))
        if delta is None:
            meta["base"] = captured
            return EffectiveVariable(value=captured, source="C", meta=meta), "attendees_delta"
        meta.update({"base": captured, "delta": delta, "delta_source": "Q"})
        return EffectiveVariable(value=captured + delta, source="C", meta=meta), None

    if subtype in {"room_list_for_us", "room_exclusion_followup"}:
        if q_range:
            return EffectiveVariable(value=q_range, source="Q", meta={"kind": "range"}), None
        if q_exact is not None:
            return EffectiveVariable(value=q_exact, source="Q"), None
        if captured is not None:
            return EffectiveVariable(value=captured, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    if subtype == "room_specific_capacity_check":
        if q_exact is not None:
            return EffectiveVariable(value=q_exact, source="Q"), None
        if q_range:
            return EffectiveVariable(value=q_range, source="Q", meta={"kind": "range"}), None
        if captured is not None:
            return EffectiveVariable(value=captured, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    if subtype in {"room_specific_availability", "room_followup_same_context"}:
        if q_range:
            return EffectiveVariable(value=q_range, source="Q", meta={"kind": "range"}), None
        if q_exact is not None:
            return EffectiveVariable(value=q_exact, source="Q"), None
        if captured is not None:
            return EffectiveVariable(value=captured, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    if subtype in {"room_recommendation_by_month", "product_recommendation_for_us"}:
        if captured is not None:
            return EffectiveVariable(value=captured, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    if subtype in {"date_pattern_availability", "date_pattern_availability_general"}:
        if q_range:
            return EffectiveVariable(value=q_range, source="Q", meta={"kind": "range"}), None
        if q_exact is not None:
            return EffectiveVariable(value=q_exact, source="Q"), None
        if captured is not None:
            return EffectiveVariable(value=captured, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "attendees"

    # Default fallback: use captured attendees if available.
    if captured is not None:
        return EffectiveVariable(value=captured, source="C"), None
    return EffectiveVariable(value=q_exact, source="Q" if q_exact is not None else "UNUSED"), (
        None if q_exact is not None else "attendees"
    )


def _resolve_date(
    subtype: str,
    q_values: Dict[str, Any],
    captured_state: Dict[str, Any],
    now_fn: Callable[[], date],
) -> Tuple[EffectiveVariable, Optional[str]]:
    q_date = _clean_str(q_values.get("date"))
    q_range = _normalize_date_range(q_values.get("date_range"))
    q_pattern = _clean_str(q_values.get("date_pattern"))
    captured_date = _clean_str(captured_state.get("date"))

    if subtype in {
        "room_capacity_static",
        "catalog_by_capacity",
        "room_specific_capacity_check",
        "room_capacity_delta",
        "room_catalog_with_products",
        "room_feature_truth",
        "room_product_truth",
        "product_catalog",
        "product_truth",
        "product_recommendation_for_us",
        "update_candidate",
    }:
        return EffectiveVariable(value=None, source="UNUSED"), None

    # non_event_info: use captured date if available (enables fallback room queries)
    if subtype == "non_event_info":
        if captured_date:
            return EffectiveVariable(value=captured_date, source="C", meta={"fallback": True}), None
        return EffectiveVariable(value=None, source="UNUSED"), None

    if subtype == "repertoire_check":
        today_iso = now_fn().isoformat()
        return EffectiveVariable(value=today_iso, source="F", meta={"label": "today"}), None

    if subtype in {"room_list_for_us", "room_exclusion_followup"}:
        if q_date or q_range or q_pattern:
            meta = _pattern_meta(q_pattern)
            value = _select_date_value(q_date, q_range, q_pattern)
            if meta:
                return EffectiveVariable(value=value, source="Q", meta=meta), None
            return EffectiveVariable(value=value, source="Q"), None
        if captured_date:
            return EffectiveVariable(value=captured_date, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "date"

    if subtype in {"room_specific_availability", "room_followup_same_context"}:
        if q_date or q_range or q_pattern:
            meta = _pattern_meta(q_pattern)
            if meta:
                return EffectiveVariable(value=_select_date_value(q_date, q_range, q_pattern), source="Q", meta=meta), None
            return EffectiveVariable(value=_select_date_value(q_date, q_range, q_pattern), source="Q"), None
        if captured_date:
            return EffectiveVariable(value=captured_date, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "date"

    if subtype == "room_recommendation_by_month":
        if q_pattern:
            return EffectiveVariable(value=q_pattern, source="Q", meta=_pattern_meta(q_pattern)), None
        return EffectiveVariable(value=captured_date, source="C" if captured_date else "UNUSED"), (
            None if captured_date else "date"
        )

    if subtype in {"date_pattern_availability", "date_pattern_availability_general"}:
        if q_pattern:
            return EffectiveVariable(value=q_pattern, source="Q", meta=_pattern_meta(q_pattern)), None
        if q_date or q_range:
            return EffectiveVariable(value=_select_date_value(q_date, q_range, None), source="Q"), None
        if captured_date:
            return EffectiveVariable(value=captured_date, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "date"

    if subtype == "product_recommendation_for_us":
        if captured_date:
            return EffectiveVariable(value=captured_date, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "date"

    selected = _select_date_value(q_date, q_range, q_pattern)
    if q_pattern:
        meta = _pattern_meta(q_pattern)
        if meta:
            return EffectiveVariable(value=selected, source="Q", meta=meta), None
    return EffectiveVariable(value=selected, source="Q"), None


def _resolve_room(
    subtype: str,
    q_values: Dict[str, Any],
    captured_state: Dict[str, Any],
) -> Tuple[EffectiveVariable, Optional[str]]:
    q_room = _clean_str(q_values.get("room"))
    captured_room = _clean_str(captured_state.get("room")) or _clean_str(captured_state.get("locked_room"))

    if subtype in {
        "catalog_by_capacity",
        "room_list_for_us",
        "room_recommendation_by_month",
        "date_pattern_availability",
        "date_pattern_availability_general",
        "room_catalog_with_products",
        "room_exclusion_followup",
        "product_catalog",
        "product_truth",
        "product_recommendation_for_us",
        "repertoire_check",
    }:
        return EffectiveVariable(value=None, source="UNUSED"), None

    # non_event_info: use captured room if available (enables fallback room queries)
    if subtype == "non_event_info":
        if captured_room:
            return EffectiveVariable(value=captured_room, source="C", meta={"fallback": True}), None
        return EffectiveVariable(value=None, source="UNUSED"), None

    if subtype == "room_capacity_delta":
        if captured_room:
            return EffectiveVariable(value=captured_room, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "room"

    if subtype in {"room_capacity_static", "room_specific_capacity_check", "room_specific_availability", "room_product_truth", "room_feature_truth", "room_followup_same_context"}:
        if q_room:
            return EffectiveVariable(value=q_room, source="Q"), None
        if captured_room and subtype != "room_capacity_static":
            return EffectiveVariable(value=captured_room, source="C"), None
        return EffectiveVariable(value=None, source="UNUSED"), "room"

    return EffectiveVariable(value=q_room, source="Q" if q_room else "UNUSED"), None


def _resolve_products(
    subtype: str,
    q_values: Dict[str, Any],
    captured_state: Dict[str, Any],
) -> Tuple[EffectiveVariable, Optional[str]]:
    q_products = _normalize_list(q_values.get("products"))
    q_attributes = _normalize_list(q_values.get("product_attributes"))
    captured_products = _normalize_list(captured_state.get("products"))

    if subtype in {
        "room_capacity_static",
        "catalog_by_capacity",
        "room_specific_capacity_check",
        "room_capacity_delta",
        "room_feature_truth",
        "non_event_info",
    }:
        return EffectiveVariable(value=None, source="UNUSED"), None

    if subtype in {"room_list_for_us", "room_followup_same_context", "room_exclusion_followup", "room_recommendation_by_month"}:
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        if captured_products:
            return EffectiveVariable(value=captured_products, source="C", meta={"weight": "soft"}), None
        return EffectiveVariable(value=[], source="F"), None

    if subtype == "room_specific_availability":
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        return EffectiveVariable(value=[], source="F"), None

    if subtype in {"date_pattern_availability", "room_catalog_with_products"}:
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        return EffectiveVariable(value=[], source="F"), "products" if subtype == "room_catalog_with_products" else None

    if subtype == "date_pattern_availability_general":
        return EffectiveVariable(value=[], source="F"), None

    if subtype == "room_product_truth":
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        if q_attributes:
            return EffectiveVariable(value=q_attributes, source="Q", meta={"attributes": True}), None
        return EffectiveVariable(value=None, source="UNUSED"), "products"

    if subtype == "product_catalog":
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        if captured_products:
            return EffectiveVariable(value=captured_products, source="C", meta={"weight": "soft"}), None
        return EffectiveVariable(value=[], source="F"), None

    if subtype == "product_truth":
        if q_products or q_attributes:
            value = q_products or q_attributes
            meta = {"attributes": bool(q_attributes and not q_products)}
            return EffectiveVariable(value=value, source="Q", meta=meta), None
        return EffectiveVariable(value=None, source="UNUSED"), "products"

    if subtype == "product_recommendation_for_us":
        if captured_products:
            return EffectiveVariable(value=captured_products, source="C", meta={"weight": "soft"}), None
        return EffectiveVariable(value=[], source="F"), None

    if subtype == "repertoire_check":
        if q_products:
            return EffectiveVariable(value=q_products, source="Q"), None
        if q_attributes:
            return EffectiveVariable(value=q_attributes, source="Q", meta={"attributes": True}), None
        return EffectiveVariable(value=None, source="UNUSED"), "products"

    return EffectiveVariable(value=q_products, source="Q" if q_products else "UNUSED"), None


def _derive_base_date(effective_date: EffectiveVariable, now_fn: Callable[[], date]) -> Optional[date]:
    value = effective_date.value
    meta = effective_date.meta or {}
    if isinstance(value, str):
        parsed = _parse_iso_date(value)
        if parsed:
            return parsed
    if isinstance(value, dict):
        start = value.get("start")
        if isinstance(start, str):
            parsed = _parse_iso_date(start)
            if parsed:
                return parsed
        date_token = value.get("date")
        if isinstance(date_token, str):
            parsed = _parse_iso_date(date_token)
            if parsed:
                return parsed
    if meta:
        year = meta.get("year")
        month_index = meta.get("month_index")
        days_hint = meta.get("days_hint")
        if not year:
            year = now_fn().year
        if month_index:
            if days_hint:
                for day in sorted({d for d in days_hint if isinstance(d, int)}):
                    try:
                        return date(year, month_index, day)
                    except ValueError:
                        continue
            try:
                return date(year, month_index, 1)
            except ValueError:
                pass
    if isinstance(value, dict):
        start = value.get("start")
        if isinstance(start, str):
            parsed = _parse_iso_date(start)
            if parsed:
                return parsed
    return now_fn()


def _normalize_range(raw: Any) -> Optional[Dict[str, int]]:
    if not isinstance(raw, dict):
        return None
    start = _to_int(raw.get("min"))
    end = _to_int(raw.get("max"))
    if start is None and end is None:
        return None
    result: Dict[str, int] = {}
    if start is not None:
        result["min"] = start
    if end is not None:
        result["max"] = end
    return result or None


def _normalize_date_range(raw: Any) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    start = _clean_str(raw.get("start"))
    end = _clean_str(raw.get("end"))
    if not start and not end:
        return None
    result: Dict[str, str] = {}
    if start:
        result["start"] = start
    if end:
        result["end"] = end
    return result or None


def _normalize_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, (list, tuple, set)):
        items: List[str] = []
        for entry in raw:
            text = _clean_str(entry)
            if text:
                items.append(text)
        return items
    return []


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            return None


def _select_date_value(
    q_date: Optional[str],
    q_range: Optional[Dict[str, str]],
    q_pattern: Optional[str],
) -> Any:
    if q_range:
        return q_range
    if q_date:
        return q_date
    if q_pattern:
        return q_pattern
    return None


def _pattern_meta(pattern: Optional[str]) -> Dict[str, Any]:
    if not pattern:
        return {}
    lowered = pattern.lower()
    meta: Dict[str, Any] = {"pattern": pattern}
    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    weekdays = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    for idx, name in enumerate(months, start=1):
        if name in lowered:
            meta["month_index"] = idx
            break
    for name in weekdays:
        if name in lowered:
            meta["weekday"] = name
            break
    week_terms = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5,
    }
    for token, index in week_terms.items():
        if f"{token} week" in lowered:
            meta["week_index"] = index
            break
    year_match = re.search(r"(20\d{2})", pattern)
    if year_match:
        try:
            meta["year"] = int(year_match.group(1))
        except ValueError:
            pass
    day_tokens = []
    for candidate in re.findall(r"\b(\d{1,2})\b", pattern):
        try:
            day_value = int(candidate)
        except ValueError:
            continue
        if day_value > 31:
            continue
        day_tokens.append(day_value)
    if day_tokens:
        meta["days_hint"] = sorted({day for day in day_tokens if day >= 1})
    return meta


__all__ = ["build_qna_context", "QnAContext", "EffectiveVariable", "CASE_MAP"]
