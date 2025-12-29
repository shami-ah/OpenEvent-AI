
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.debug.hooks import set_subloop, trace_general_qa_status
from backend.workflows.io.database import update_event_metadata
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.common.capacity import fits_capacity, layout_capacity
from backend.workflows.common.catalog import list_catering, list_room_features
from backend.workflows.common.fallback_reason import (
    SHOW_FALLBACK_DIAGNOSTICS,
    empty_results_reason,
    format_fallback_diagnostic,
)
from backend.workflows.common.menu_options import build_menu_payload, format_menu_line
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.router import route_general_qna

# TODO(openevent-team): Move extended room descriptions to dedicated metadata instead of the products mapping workaround.

CLIENT_AVAILABILITY_HEADER = "Availability overview"

ROOM_IDS = ["Room A", "Room B", "Room C"]
LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "u shape": "U-shape",
    "boardroom": "Boardroom",
    "board-room": "Boardroom",
}
FEATURE_KEYWORDS = {
    "projector": "Projector",
    "projectors": "Projector",
    "flipchart": "Flip chart",
    "flipcharts": "Flip chart",
    "flip chart": "Flip chart",
    "screen": "Screen",
    "hdmi": "HDMI",
    "sound system": "Sound system",
    "sound": "Sound system",
}
CATERING_KEYWORDS = {
    "lunch": "Light lunch",
    "coffee": "Coffee break service",
    "tea": "Coffee break service",
    "break": "Coffee break service",
}

STATUS_PRIORITY = {
    "available": 0,
    "option": 1,
    "hold": 2,
    "waitlist": 3,
    "unavailable": 4,
}

MONTH_INDEX_TO_NAME = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

_MENU_ONLY_SUBTYPES = {
    "product_catalog",
    "product_truth",
    "product_recommendation_for_us",
    "repertoire_check",
}

_ROOM_MENU_SUBTYPES = {
    "room_catalog_with_products",
    "room_product_truth",
}

_DATE_PARSE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%a %d %b %Y",
    "%A %d %B %Y",
)

DEFAULT_NEXT_STEP_LINE = "- Confirm your preferred date (and any other must-haves) so I can fast-track the next workflow step for you."
DEFAULT_ROOM_NEXT_STEP_LINE = "- Confirm the room you like (and any final requirements) so I can move ahead with the offer preparation."


def _build_verbalize_context(
    db_summary: Dict[str, Any],
    event_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build verbalize_context from Q&A db_summary for verbalizer fact verification.

    Extracts dates, room names, amounts, and product names that MUST be preserved
    during verbalization (the verbalizer "sandwich" will verify these facts).
    """
    context: Dict[str, Any] = {}

    # Extract room names
    rooms = db_summary.get("rooms") or []
    if rooms:
        room_names = [r.get("name") or r.get("room_name") for r in rooms if r.get("name") or r.get("room_name")]
        if room_names:
            context["rooms"] = room_names

    # Extract dates
    dates = db_summary.get("dates") or []
    if dates:
        date_values = []
        for d in dates:
            date_str = d.get("date") or d.get("date_iso")
            if date_str:
                date_values.append(date_str)
        if date_values:
            context["dates"] = date_values

    # Extract product names
    products = db_summary.get("products") or []
    if products:
        product_names = [p.get("name") or p.get("product_name") for p in products if p.get("name") or p.get("product_name")]
        if product_names:
            context["products"] = product_names

    # Extract amounts from event requirements
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    if participants:
        context["amounts"] = {"participants": participants}

    return context


def _normalise_iso_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = {text, text.replace("Z", ""), text.replace("Z", "+00:00")}
    for candidate in list(candidates):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.date().isoformat()
        except ValueError:
            continue
    for candidate in candidates:
        for fmt in _DATE_PARSE_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed.date().isoformat()
            except ValueError:
                continue
    return None


def _normalise_candidate_date(raw_date: str) -> Tuple[str, Optional[str]]:
    token = str(raw_date or "").strip()
    display_date = _format_display_date(token)
    iso_date = _normalise_iso_date(token) or _normalise_iso_date(display_date)
    return display_date, iso_date


def _range_results_lookup(range_results: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    if not range_results:
        return mapping
    for entry in range_results:
        if not isinstance(entry, dict):
            continue
        iso_date = (
            _normalise_iso_date(entry.get("iso_date"))
            or _normalise_iso_date(entry.get("date"))
            or _normalise_iso_date(entry.get("iso"))
            or _normalise_iso_date(entry.get("date_label"))
        )
        if not iso_date:
            continue
        record = {
            "room": entry.get("room") or entry.get("rooms") or entry.get("room_name"),
            "status": entry.get("status"),
            "summary": entry.get("summary"),
        }
        mapping.setdefault(iso_date, []).append(record)
    for rows in mapping.values():
        rows.sort(key=lambda rec: STATUS_PRIORITY.get(str(rec.get("status") or "").lower(), 9))
    return mapping


def _normalise_next_step_line(block_text: Optional[str], *, default_line: str = DEFAULT_NEXT_STEP_LINE) -> str:
    text = (block_text or "").strip()
    if not text:
        return default_line
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullet = next((line for line in lines if line.startswith("-")), None)
    if bullet:
        candidate = bullet.lstrip("- ").strip()
    else:
        candidate = re.sub(r"(?i)^next step:\s*", "", lines[0]).strip() if lines else ""
    if not candidate:
        return default_line
    candidate = candidate[0].upper() + candidate[1:] if candidate else candidate
    line = f"- {candidate}"
    if "fast-track" not in line.lower():
        stripped = line.rstrip(".")
        line = stripped + " — mention any other confirmed details (room/setup, catering) and I'll fast-track the next workflow step for you."
    return line



def _qna_message_payload(state: WorkflowState) -> Dict[str, str]:
    message = state.message
    subject = message.subject if message else ""
    body = message.body if message else ""
    return {
        "subject": subject or "",
        "body": body or "",
        "msg_id": message.msg_id if message else "",
        "thread_id": state.thread_id,
    }


def _extract_preference_tokens(text: str) -> Tuple[Optional[str], List[str], List[str]]:
    lowered = text.lower()
    layout = None
    for token, layout_name in LAYOUT_KEYWORDS.items():
        if token in lowered:
            layout = layout_name
            break

    features: List[str] = []
    for token, canonical in FEATURE_KEYWORDS.items():
        if token in lowered and canonical not in features:
            features.append(canonical)

    catering: List[str] = []
    for token, label in CATERING_KEYWORDS.items():
        if token in lowered and label not in catering:
            catering.append(label)

    return layout, features, catering


def _capture_preferences(state: WorkflowState, catering: Sequence[str], features: Sequence[str]) -> None:
    event_entry = state.event_entry or {}
    captured = event_entry.setdefault("captured", {})
    if catering:
        captured.setdefault("catering", list(catering))
    if features:
        captured.setdefault("products", list(features))
    state.event_entry = event_entry
    state.extras["captured_preferences"] = {"catering": list(catering), "features": list(features)}


def _room_feature_summary(room_id: str, features: Iterable[str]) -> str:
    matches: List[str] = []
    missing: List[str] = []
    available = set(map(str.strip, list_room_features(room_id)))
    for feature in features:
        if feature in available:
            matches.append(f"{feature} ✓")
        else:
            missing.append(f"{feature} ✗")
    summary_bits = matches[:2]
    if missing and not summary_bits:
        summary_bits.extend(missing[:1])
    elif missing:
        summary_bits.append(missing[0])
    return "; ".join(summary_bits)


def _room_recommendations(
    preferences: Dict[str, Any],
    participants: Optional[int],
) -> List[Dict[str, Any]]:
    layout = preferences.get("layout")
    features = preferences.get("features") or []

    recommendations: List[Dict[str, Any]] = []
    for room in ROOM_IDS:
        if participants and not fits_capacity(room, participants, layout):
            continue
        layout_note = ""
        if layout:
            capacity = layout_capacity(room, layout)
            if capacity:
                layout_note = f"{layout} up to {capacity}"
            else:
                layout_note = f"{layout} layout available"

        feature_summary = _room_feature_summary(room, features)
        score = feature_summary.count("✓")
        summary = ", ".join(filter(None, [layout_note, feature_summary])).strip(", ")
        recommendations.append(
            {
                "name": room,
                "summary": summary,
                "score": score,
            }
        )

    recommendations.sort(key=lambda entry: entry["score"], reverse=True)
    return recommendations[:3]


def _catering_recommendations(preferences: Dict[str, Any]) -> List[str]:
    catering_tokens = preferences.get("catering") or []
    if not catering_tokens:
        return []
    items = list_catering()
    selections: List[str] = []
    for label in catering_tokens:
        matched = next((item for item in items if label.lower() in str(item.get("name", "")).lower()), None)
        if matched:
            descriptor = matched.get("description") or matched.get("category") or "Package"
            price = matched.get("price_per_person") or matched.get("price")
            price_text = f" — CHF {price}" if price else ""
            selections.append(f"- {matched.get('name')}{price_text}: {descriptor}.")
        else:
            selections.append(f"- {label}.")
    return selections[:3]


def _preprocess_preferences(state: WorkflowState) -> Dict[str, Any]:
    payload = _qna_message_payload(state)
    text = f"{payload.get('subject', '')}\n{payload.get('body', '')}"
    layout, features, catering = _extract_preference_tokens(text)
    preferences = {
        "layout": layout,
        "features": features,
        "catering": catering,
    }
    _capture_preferences(state, catering, features)
    return preferences


def _split_body_footer(body: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split the body into core content, NEXT STEP block, and footer."""

    next_step_block: Optional[str] = None
    core_text = body

    next_step_match = re.search(r"(?:\n{2,}|^)(NEXT STEP:\n.*?)(?=\n{2,}|\Z)", body, flags=re.IGNORECASE | re.DOTALL)
    if next_step_match:
        next_step_block = next_step_match.group(1).strip()
        start, end = next_step_match.span()
        core_text = body[:start] + body[end:]
    else:
        inline_match = re.search(r"(?i)(next step:\s*.+)", core_text)
        if inline_match:
            line = inline_match.group(1).strip()
            instruction = re.sub(r"(?i)^next step:\s*", "", line).strip()
            if instruction:
                instruction = instruction[0].upper() + instruction[1:] if instruction else instruction
                next_step_block = f"NEXT STEP:\n- {instruction}"
            core_text = core_text.replace(inline_match.group(0), "")

    footer_text = None
    if "---" in core_text:
        core_part, _, footer_part = core_text.partition("---")
        core_text = core_part
        footer_text = footer_part.strip()

    return core_text.strip(), next_step_block, footer_text


def _build_room_and_catering_sections(
    state: WorkflowState,
    preferences: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[str]]:
    if preferences is None:
        preferences = _preprocess_preferences(state)
    participants = None
    try:
        participants = int((state.user_info or {}).get("participants") or (state.event_entry or {}).get("requirements", {}).get("number_of_participants") or 0)
    except (TypeError, ValueError):
        participants = None

    room_recs = _room_recommendations(preferences, participants)
    sections: List[str] = []
    headers: List[str] = []
    if (preferences.get("features") or preferences.get("layout")) and room_recs:
        lines = ["Rooms that already cover your requested setup:"]
        for rec in room_recs:
            bullet = f"- {rec['name']}"
            if rec["summary"]:
                bullet += f" — {rec['summary']}"
            lines.append(bullet)
        sections.append("Rooms & Setup\n" + "\n".join(lines))
        headers.append("Rooms & Setup")

    catering_lines = _catering_recommendations(preferences)
    if preferences.get("catering") and catering_lines:
        sections.append("Refreshments\n" + "\n".join(catering_lines))
        headers.append("Refreshments")

    return sections, headers, room_recs, catering_lines


def _menu_lines_from_payload(payload: Optional[Dict[str, Any]]) -> List[str]:
    if not payload:
        return []
    title = payload.get("title") or "Menu options we can offer:"
    lines = [title]
    for row in payload.get("rows", []):
        rendered = format_menu_line(row, month_hint=payload.get("month"))
        if rendered:
            lines.append(rendered)
    return lines


def _format_display_date(value: str) -> str:
    token = value.strip()
    if not token:
        return token
    if "." in token and token.count(".") == 2:
        return token
    cleaned = token.replace("Z", "")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%d.%m.%Y")
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return token


def _extract_availability_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:") or upper.startswith("NEXT STEP:"):
            continue
        if stripped.startswith("- "):
            continue
        if "available" in stripped.lower():
            lines.append(stripped)
    return lines


def _extract_info_lines(text: str) -> List[str]:
    capture = False
    info_lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:"):
            capture = True
            continue
        if upper.startswith("NEXT STEP:"):
            capture = False
            continue
        if capture and stripped.startswith("- "):
            info_lines.append(stripped)
    return info_lines



def _dedup_preserve_order(items: Iterable[Any]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for raw in items:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered

def _load_structured_action_payload_for_general_qna(state: WorkflowState) -> Optional[Dict[str, Any]]:
    cached = state.turn_notes.get("_general_qna_structured_payload")
    if isinstance(cached, dict):
        return cached

    extraction = state.extras.get("qna_extraction")
    if not extraction:
        cache = (state.event_entry or {}).get("qna_cache") or {}
        extraction = cache.get("extraction")
    if not extraction:
        return None

    result = build_structured_qna_result(state, extraction)
    if not result:
        return None

    payload = result.action_payload
    state.turn_notes["_general_qna_structured_payload"] = payload
    return payload


def _determine_select_and_where_fields(
    qna_subtype: str,
    q_values: Dict[str, Any],
    effective: Dict[str, Any],
    db_summary: Dict[str, Any],
    menu_payload: Optional[Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    subtype = (qna_subtype or "").lower()
    select_fields: List[str] = []
    if subtype in _MENU_ONLY_SUBTYPES:
        select_fields.append("menu")
    elif subtype in _ROOM_MENU_SUBTYPES:
        select_fields.extend(["room", "menu"])
    else:
        select_fields.append("room")

    if (db_summary.get("products") or (menu_payload or {}).get("rows")) and "menu" not in select_fields:
        if not db_summary.get("rooms"):
            select_fields = ["menu"]
        else:
            select_fields.append("menu")

    select_fields = _dedup_preserve_order(select_fields)

    where_fields: List[str] = ["dates"]
    date_meta = ((effective or {}).get("D") or {}).get("meta") or {}
    if date_meta.get("month_index"):
        where_fields.append("month")
    if date_meta.get("weekday"):
        where_fields.append("weekday")
    time_hint = q_values.get("time_of_day") or q_values.get("time_hint") or q_values.get("day_part")
    if time_hint:
        where_fields.append("time_of_day")
    if ((effective or {}).get("N") or {}).get("value") not in (None, "", []):
        where_fields.append("guests")
    if ((effective or {}).get("P") or {}).get("value"):
        where_fields.append("products")

    return select_fields, _dedup_preserve_order(where_fields)


def _date_sort_key(label: str) -> str:
    iso_label = _normalise_iso_date(label)
    if iso_label:
        return iso_label
    return label


def _collect_room_rows(
    select_fields: Sequence[str],
    db_summary: Dict[str, Any],
    range_results: Optional[Sequence[Dict[str, Any]]],
    candidate_dates: Sequence[str],
    room_recs: Sequence[Dict[str, Any]],
    catering_lines: Sequence[str],
    menu_payload: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, str]], Dict[str, Set[Any]]]:
    rooms_summary = db_summary.get("rooms") or []
    products_summary = db_summary.get("products") or []
    menu_rows = (menu_payload or {}).get("rows") or []
    summary_map = {
        str(rec.get("name")).strip(): rec.get("summary")
        for rec in room_recs
        if rec.get("name")
    }
    catering_summary = (
        "; ".join(item.strip("- ") for item in catering_lines[:2] if item)
        if catering_lines
        else ""
    )

    buckets: Dict[str, Dict[str, Any]] = {}

    def _ensure_bucket(room_label: Any) -> Dict[str, Any]:
        label = str(room_label or "").strip() or "Any matching room"
        return buckets.setdefault(
            label,
            {
                "dates": set(),
                "sort_keys": set(),
                "notes": [],
                "notes_seen": set(),
                "menus": set(),
                "status_priority": 99,
            },
        )

    def _add_note(payload: Dict[str, Any], text: Any) -> None:
        clean = str(text or "").strip()
        if not clean or clean in payload["notes_seen"]:
            return
        payload["notes"].append(clean)
        payload["notes_seen"].add(clean)

    for entry in rooms_summary:
        room_name = entry.get("room_name") or entry.get("room_id") or "Room"
        bucket = _ensure_bucket(room_name)
        date_value = entry.get("date")
        if date_value:
            display_date = _format_display_date(str(date_value))
            if display_date:
                bucket["dates"].add(display_date)
            iso_value = _normalise_iso_date(str(date_value))
            if iso_value:
                bucket["sort_keys"].add(iso_value)
        status = entry.get("status")
        if status:
            _add_note(bucket, f"Status: {status}")
            bucket["status_priority"] = min(
                bucket["status_priority"],
                STATUS_PRIORITY.get(str(status).lower(), 99),
            )
        capacity = entry.get("capacity_max")
        if capacity:
            _add_note(bucket, f"Capacity up to {capacity}")
        for product in entry.get("products") or []:
            name = str(product).strip()
            if name:
                bucket["menus"].add(name)
        mapped_summary = summary_map.get(str(room_name).strip())
        if mapped_summary:
            _add_note(bucket, mapped_summary)

    handled_iso: Set[str] = set()
    for entry in range_results or []:
        room_name = entry.get("room") or entry.get("room_name")
        if not room_name:
            continue
        bucket = _ensure_bucket(room_name)
        iso_token = entry.get("iso_date") or entry.get("date") or entry.get("iso")
        display_date = entry.get("date_label")
        if iso_token:
            iso_norm = _normalise_iso_date(str(iso_token))
            if iso_norm:
                handled_iso.add(iso_norm)
                bucket["sort_keys"].add(iso_norm)
                if not display_date:
                    display_date = _format_display_date(iso_norm)
        if display_date:
            bucket["dates"].add(_format_display_date(str(display_date)))
        status = entry.get("status")
        if status:
            _add_note(bucket, f"Status: {status}")
            bucket["status_priority"] = min(
                bucket["status_priority"],
                STATUS_PRIORITY.get(str(status).lower(), 99),
            )
        summary = entry.get("summary")
        if summary:
            _add_note(bucket, summary)
        mapped_summary = summary_map.get(str(room_name).strip())
        if mapped_summary:
            _add_note(bucket, mapped_summary)

    remaining_dates: List[Tuple[Optional[str], str]] = []
    for raw_date in list(candidate_dates)[:8]:
        display_date, iso_date = _normalise_candidate_date(raw_date)
        if iso_date and iso_date in handled_iso:
            continue
        if display_date:
            remaining_dates.append((iso_date, display_date))
    if remaining_dates:
        bucket = _ensure_bucket("Any matching room")
        for iso_date, display_date in remaining_dates:
            bucket["dates"].add(display_date)
            if iso_date:
                bucket["sort_keys"].add(iso_date)

    for entry in products_summary:
        name = str(entry.get("product") or "").strip()
        if not name:
            continue
        rooms = entry.get("rooms") or []
        if not rooms and select_fields == ["room"]:
            continue
        if not rooms:
            for payload in buckets.values():
                payload["menus"].add(name)
            continue
        for room_name in rooms:
            bucket = _ensure_bucket(room_name)
            bucket["menus"].add(name)

    menu_names: List[str] = []
    if menu_rows:
        for entry in menu_rows:
            name = str(entry.get("menu_name") or "").strip()
            if not name:
                continue
            descriptor_bits: List[str] = []
            if entry.get("vegetarian"):
                descriptor_bits.append("vegetarian")
            if entry.get("wine_pairing"):
                descriptor_bits.append("wine pairing")
            courses = entry.get("courses")
            if courses:
                descriptor_bits.append(f"{courses}-course")
            season = entry.get("season_label")
            if season:
                descriptor_bits.append(str(season))
            note = " (" + "; ".join(descriptor_bits) + ")" if descriptor_bits else ""
            menu_names.append(f"{name}{note}" if note else name)
        if "menu" in select_fields:
            for payload in buckets.values():
                for item in menu_names:
                    payload["menus"].add(item)

    if catering_summary:
        for payload in buckets.values():
            _add_note(payload, catering_summary)

    rows: List[Dict[str, str]] = []
    variation: Dict[str, Set[Any]] = defaultdict(set)

    for room_name, payload in sorted(
        buckets.items(),
        key=lambda item: (
            item[1]["status_priority"],
            min(item[1]["sort_keys"]) if item[1]["sort_keys"] else "",
            item[0].lower(),
        ),
    ):
        row: Dict[str, str] = {}
        if "room" in select_fields:
            row["room"] = room_name
        if "menu" in select_fields:
            menus = sorted(payload["menus"])
            row["menu"] = ", ".join(menus) if menus else "—"
        dates_sorted = sorted(payload["dates"], key=_date_sort_key)
        row["dates"] = ", ".join(dates_sorted) if dates_sorted else "—"
        variation["dates"].add(tuple(dates_sorted))
        notes_list = payload["notes"]
        row["notes"] = "; ".join(notes_list) if notes_list else "—"
        rows.append(row)

    return rows, dict(variation)


def _collect_menu_rows(
    menu_payload: Optional[Dict[str, Any]],
    products_summary: Sequence[Dict[str, Any]],
    candidate_dates: Sequence[str],
) -> Tuple[List[Dict[str, str]], Dict[str, Set[Any]]]:
    rows: List[Dict[str, str]] = []
    variation: Dict[str, Set[Any]] = defaultdict(set)
    seen: Set[str] = set()

    display_dates = _dedup_preserve_order([
        _format_display_date(str(date)) for date in candidate_dates if str(date).strip()
    ])
    if display_dates:
        variation["dates"].add(tuple(display_dates))

    if menu_payload:
        for entry in menu_payload.get("rows", []):
            name = str(entry.get("menu_name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            notes_bits: List[str] = []
            price = entry.get("price")
            if price:
                price_text = str(price).strip()
                if price_text:
                    notes_bits.append(
                        price_text if "per" in price_text.lower() else f"{price_text} per guest"
                    )
            if entry.get("vegetarian"):
                notes_bits.append("Vegetarian")
            if entry.get("wine_pairing"):
                notes_bits.append("Wine pairing included")
            notes_bits.extend(entry.get("notes") or [])
            season = entry.get("season_label")
            if season:
                notes_bits.append(str(season))
            notes = "; ".join(_dedup_preserve_order(notes_bits))
            rows.append({
                "menu": name,
                "notes": notes or "—",
                "dates": ", ".join(display_dates) if display_dates else "—",
            })
            seen.add(key)

    for entry in products_summary:
        name = str(entry.get("product") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        notes_bits: List[str] = []
        rooms = _dedup_preserve_order(entry.get("rooms") or [])
        if rooms:
            notes_bits.append(f"Rooms: {', '.join(rooms)}")
        if entry.get("available_today") is False:
            notes_bits.append("Not available today")
        notes = "; ".join(_dedup_preserve_order(notes_bits))
        rows.append({
            "menu": name,
            "notes": notes or "—",
            "dates": ", ".join(display_dates) if display_dates else "—",
        })
        seen.add(key)

    for row in rows:
        row.setdefault("notes", "—")
        row.setdefault("dates", ", ".join(display_dates) if display_dates else "—")

    return rows, dict(variation)


def _compute_column_plan(
    select_fields: Sequence[str],
    where_fields: Sequence[str],
    rows: Sequence[Dict[str, str]],
    variation: Dict[str, Set[Any]],
) -> Tuple[List[str], Dict[str, Any]]:
    column_order: List[str] = []
    constants: Dict[str, Any] = {}

    for field in select_fields:
        if any(row.get(field) not in (None, "", "—") for row in rows):
            column_order.append(field)

    has_dates = any(row.get("dates") not in (None, "", "—") for row in rows)
    date_variations = {tuple(val) for val in variation.get("dates", set()) if val}
    if date_variations or has_dates:
        if "dates" not in column_order:
            column_order.append("dates")
        if len(date_variations) == 1:
            constants["dates"] = list(next(iter(date_variations)))

    if "notes" not in column_order:
        column_order.append("notes")

    return column_order, constants


def _column_label(field: str, select_fields: Sequence[str]) -> str:
    if field == "room":
        return "Room"
    if field == "menu":
        return "Menus" if "room" in select_fields and len(select_fields) > 1 else "Menu"
    if field == "dates":
        return "Dates"
    if field == "month":
        return "Month"
    if field == "weekday":
        return "Weekday"
    if field == "time_of_day":
        return "Time"
    if field == "guests":
        return "Guests"
    if field == "products":
        return "Products"
    if field == "notes":
        return "Notes"
    return field.capitalize()

def _render_markdown_table(
    rows: Sequence[Dict[str, str]],
    column_order: Sequence[str],
    select_fields: Sequence[str],
) -> List[str]:
    if not rows or not column_order:
        return []
    header_labels = [_column_label(field, select_fields) for field in column_order]
    header = "| " + " | ".join(header_labels) + " |"
    divider = "| " + " | ".join("---" for _ in column_order) + " |"
    lines = [header, divider]
    for row in rows:
        cells: List[str] = []
        for field in column_order:
            value = row.get(field, "—")
            cell = str(value if value not in (None, "") else "—")
            cells.append(cell)
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _time_hint_with_source(state: WorkflowState) -> Tuple[Optional[str], Optional[str]]:
    user_info = state.user_info or {}
    hint = user_info.get("vague_time_of_day")
    if hint:
        return str(hint), "Q"
    event_entry = state.event_entry or {}
    hint = event_entry.get("vague_time_of_day")
    if hint:
        return str(hint), "C"
    return None, None


def _attendee_phrase(variable: Dict[str, Any]) -> Optional[str]:
    value = (variable or {}).get("value")
    if value is None:
        return None
    if isinstance(value, dict):
        minimum = value.get("min")
        maximum = value.get("max")
        if minimum is not None and maximum is not None:
            return f"{minimum}-{maximum} guests"
        if minimum is not None:
            return f"{minimum}+ guests"
        if maximum is not None:
            return f"up to {maximum} guests"
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return f"{text} guests" if text else None
    if numeric.is_integer():
        return f"{int(numeric)} guests"
    return f"{numeric} guests"


def _products_phrase(variable: Dict[str, Any]) -> Optional[str]:
    value = (variable or {}).get("value")
    if not value:
        return None
    if isinstance(value, list):
        entries = _dedup_preserve_order(value)
        return _join_phrases(entries)
    text = str(value).strip()
    return text or None


def _join_phrases(items: Sequence[str]) -> str:
    entries = [item.strip() for item in items if item]
    if not entries:
        return ""
    if len(entries) == 1:
        return entries[0]
    return ", ".join(entries[:-1]) + f" and {entries[-1]}"


def _format_intro_paragraph(
    select_fields: Sequence[str],
    effective: Dict[str, Any],
    q_values: Dict[str, Any],
    constants: Dict[str, Any],
    menu_payload: Optional[Dict[str, Any]],
    state: WorkflowState,
    column_order: Sequence[str],
) -> str:
    sentences: List[str] = []
    assumed_filters: List[str] = []

    date_var = effective.get("D") or {}
    date_source = date_var.get("source")
    meta = date_var.get("meta") or {}
    month_index = meta.get("month_index")
    year = meta.get("year")
    month_label = MONTH_INDEX_TO_NAME.get(month_index) if month_index else None
    if month_label and year:
        month_label = f"{month_label} {year}"
    elif month_label:
        month_label = str(month_label)

    weekday_token = meta.get("weekday")
    weekday_label = None
    if isinstance(weekday_token, str) and weekday_token:
        weekday_label = weekday_token.capitalize()

    time_hint, time_source = _time_hint_with_source(state)

    attendee_var = effective.get("N") or {}
    attendee_phrase = _attendee_phrase(attendee_var)
    attendee_source = attendee_var.get("source")
    if attendee_phrase is None:
        requirements = (state.event_entry or {}).get("requirements") or {}
        user_info = state.user_info or {}
        fallback_value = (
            requirements.get("number_of_participants")
            or requirements.get("participants")
            or user_info.get("participants")
        )
        try:
            fallback_value = int(fallback_value)
        except (TypeError, ValueError):
            pass
        if fallback_value:
            attendee_phrase = _attendee_phrase({"value": fallback_value})
            attendee_source = "C"
    if attendee_phrase:
        sentences.append(f"All options below fit {attendee_phrase}.")
        if attendee_source in {"C", "F"}:
            assumed_filters.append(attendee_phrase)

    dates_constant = constants.get("dates") or []
    availability_bits: List[str] = []
    if dates_constant:
        availability_bits.append(f"available on {_join_phrases(dates_constant)}")
        if date_source in {"C", "F"}:
            assumed_filters.append(f"dates {_join_phrases(dates_constant)}")

    schedule_phrase = None
    if weekday_label and time_hint:
        base = f"{weekday_label} {str(time_hint).lower()}s"
        schedule_phrase = f"during {base}"
        if time_source in {"C", "F"}:
            assumed_filters.append(base)
    elif weekday_label:
        schedule_phrase = f"on {weekday_label}s"
        if date_source in {"C", "F"}:
            assumed_filters.append(f"{weekday_label}s")
    elif time_hint:
        label = str(time_hint).lower()
        schedule_phrase = f"during the {label}"
        if time_source in {"C", "F"}:
            assumed_filters.append(f"{label}")
    if schedule_phrase:
        availability_bits.append(schedule_phrase)

    if month_label:
        availability_bits.append(f"in {month_label}")
        if date_source in {"C", "F"}:
            assumed_filters.append(month_label)

    products_var = effective.get("P") or {}
    products_phrase = _products_phrase(products_var)
    preference_bits: List[str] = []
    if products_phrase:
        preference_bits.append(f"including {products_phrase}")
        if products_var.get("source") in {"C", "F"}:
            assumed_filters.append(products_phrase)

    menu_request_phrases: List[str] = []
    if menu_payload:
        request = menu_payload.get("request") or {}
        if request.get("vegetarian"):
            menu_request_phrases.append("vegetarian menus")
        if request.get("wine_pairing"):
            menu_request_phrases.append("wine pairings")
        if request.get("three_course"):
            menu_request_phrases.append("three-course menus")
        month_hint = menu_payload.get("month") or menu_payload.get("request_month")
        if month_hint:
            menu_request_phrases.append(f"{str(month_hint).capitalize()} menus")
    if menu_request_phrases:
        preference_bits.append(f"with {_join_phrases(menu_request_phrases)}")

    detail_segments: List[str] = []
    if availability_bits:
        detail_segments.append(_join_phrases(availability_bits))
    if preference_bits:
        detail_segments.append(_join_phrases(preference_bits))

    if detail_segments:
        sentences.append(f"They are { ' and '.join(detail_segments) }.")

    if assumed_filters:
        assumed_sentence = _join_phrases(_dedup_preserve_order(assumed_filters))
        sentences.append(f"I assumed {assumed_sentence} from your previous details.")

    paragraph = " ".join(segment for segment in sentences if segment).strip()
    return paragraph or "Here's what I can offer."

def enrich_general_qna_step2(state: WorkflowState, classification: Dict[str, Any]) -> None:
    thread_id = state.thread_id
    if not state.draft_messages:
        trace_general_qa_status(thread_id, "skip:no_drafts", {"reason": "no_draft_messages"})
        return
    draft = state.draft_messages[-1]
    if draft.get("subloop") != "general_q_a":
        trace_general_qa_status(
            thread_id,
            "skip:subloop_mismatch",
            {"topic": draft.get("topic"), "subloop": draft.get("subloop")},
        )
        return
    if draft.get("topic") not in {"general_room_qna", "structured_qna"}:
        trace_general_qa_status(
            thread_id,
            "skip:topic_mismatch",
            {"topic": draft.get("topic"), "subloop": draft.get("subloop")},
        )
        return

    body_text = draft.get("body") or ""
    _, next_step_block, _ = _split_body_footer(body_text)

    preferences = _preprocess_preferences(state)
    _sections, _headers, room_recs, catering_lines = _build_room_and_catering_sections(state, preferences)

    structured_payload = _load_structured_action_payload_for_general_qna(state)
    db_summary = structured_payload.get("db_summary") if structured_payload else {}
    extraction_payload = (structured_payload or {}).get("extraction") or {}
    q_values = extraction_payload.get("q_values") or {}
    effective = (structured_payload or {}).get("effective") or {}
    qna_subtype = (structured_payload or {}).get("qna_subtype") or ""

    menu_payload = build_menu_payload(
        (state.message.body or "") if state.message else "",
        context_month=(state.event_entry or {}).get("vague_month"),
    )
    if menu_payload:
        state.turn_notes["general_qa"] = menu_payload

    select_fields, where_fields = _determine_select_and_where_fields(
        qna_subtype,
        q_values,
        effective,
        db_summary or {},
        menu_payload,
    )

    candidate_dates = draft.get("candidate_dates") or []
    range_results = draft.get("range_results") or []

    if "room" in select_fields or (db_summary or {}).get("rooms"):
        table_rows, variation = _collect_room_rows(
            select_fields,
            db_summary or {},
            range_results,
            candidate_dates,
            room_recs,
            catering_lines,
            menu_payload,
        )
    else:
        table_rows, variation = _collect_menu_rows(
            menu_payload,
            (db_summary or {}).get("products") or [],
            candidate_dates,
        )

    next_step_line = _normalise_next_step_line(next_step_block, default_line=DEFAULT_NEXT_STEP_LINE)

    if not table_rows:
        fallback_line = "I need a specific date before I can confirm availability."
        # Don't include header in body - it's set in headers[] and joined by _format_draft_text
        body_lines = [fallback_line, "", next_step_line]
        body_markdown = "\n".join(body_lines).strip()
        footer_text = "Step: 2 Date Confirmation · Next: Room Availability · State: Awaiting Client"
        draft["body_markdown"] = body_markdown
        draft["body"] = f"{body_markdown}\n\n---\n{footer_text}"
        draft["footer"] = footer_text
        draft["headers"] = [CLIENT_AVAILABILITY_HEADER]
        draft.pop("table_blocks", None)
        trace_general_qa_status(
            thread_id,
            "applied",
            {
                "topic": draft.get("topic"),
                "candidate_dates": len(candidate_dates),
                "has_table": False,
                "has_menu_payload": bool(menu_payload),
                "range_results": len(range_results),
                "select_fields": select_fields,
                "table_columns": [],
            },
        )
        return

    column_order, constants = _compute_column_plan(select_fields, where_fields, table_rows, variation)

    display_rows: List[Dict[str, str]] = []
    for row in table_rows:
        display_row: Dict[str, str] = {}
        for field in column_order:
            value = row.get(field, "—")
            display_row[field] = str(value if value not in (None, "") else "—")
        display_rows.append(display_row)

    table_lines = _render_markdown_table(display_rows, column_order, select_fields)
    intro_text = _format_intro_paragraph(select_fields, effective, q_values, constants, menu_payload, state, column_order)

    # --- VERBALIZED CONTENT PRESERVATION ---
    # Check if draft already has LLM-verbalized content (not raw table data).
    # The verbalizer runs BEFORE this enrichment step and may have already
    # created proper prose. We must NOT overwrite it with raw table markdown.
    existing_body = draft.get("body_markdown", "")

    def _is_verbalized_content(text: str) -> bool:
        """Detect if text is LLM-verbalized prose vs raw table/fallback data."""
        if not text or len(text) < 50:
            return False
        text_lower = text.lower()
        # Verbalized prose typically contains conversational phrases
        verbalized_markers = [
            "i'd be happy to",
            "i would be happy to",
            "let me check",
            "here's what i found",
            "based on your",
            "for your event",
            "i can confirm",
            "good news",
            "i've checked",
            "looking at",
            "regarding your",
            "thank you for",
            "happy to help",
            "pleased to",
        ]
        # Raw table markers indicate non-verbalized content
        raw_table_markers = [
            "status: available",
            "status: option",
            "status: confirmed",
            "capacity up to",
            "| status:",
            "| capacity:",
            "room |",
            "| room",
            "dates |",
            "| dates",
        ]
        has_verbalized = any(marker in text_lower for marker in verbalized_markers)
        has_raw_table = any(marker in text_lower for marker in raw_table_markers)
        # If it has verbalized markers and no raw table markers, it's verbalized
        return has_verbalized and not has_raw_table

    # Preserve verbalized content - don't overwrite with raw tables
    if _is_verbalized_content(existing_body):
        # Keep the verbalized content, just ensure table_blocks are set for frontend
        trace_general_qa_status(
            thread_id,
            "preserved_verbalized",
            {
                "topic": draft.get("topic"),
                "body_preview": existing_body[:100],
                "had_table_lines": bool(table_lines),
            },
        )
        # Still set table_blocks for structured frontend rendering
        footer_text = "Step: 2 Date Confirmation · Next: Room Availability · State: Awaiting Client"
        draft["footer"] = footer_text
        draft["headers"] = [CLIENT_AVAILABILITY_HEADER]
        # Fall through to set table_blocks below without overwriting body_markdown
    else:
        # No verbalized content - build conversational response
        # Note: Don't include CLIENT_AVAILABILITY_HEADER in body_lines - it's set
        # in headers[] and _format_draft_text joins headers + body
        # IMPORTANT: Tables are NOT included in chat messages per UX requirement.
        # The table_blocks structure is set below for the frontend to render
        # in a dedicated comparison section (not inline in chat).
        body_lines = []
        if intro_text:
            body_lines.append(intro_text)
        # Add a brief summary instead of raw table
        if display_rows:
            room_count = len(display_rows)
            if room_count == 1:
                body_lines.append("I found 1 option that works for you.")
            else:
                body_lines.append(f"I found {room_count} options that work for you.")
        body_lines.extend(["", next_step_line])
        body_markdown = "\n".join(body_lines).strip()

        # Preserve router Q&A content (catering, products, etc.) that was appended earlier
        if draft.get("router_qna_appended"):
            old_body_markdown = draft.get("body_markdown", "")
            # Extract the router Q&A section (everything after "---\n\nINFO:")
            if "\n\n---\n\nINFO:" in old_body_markdown:
                router_section = old_body_markdown.split("\n\n---\n\nINFO:", 1)[1]
                body_markdown = f"{body_markdown}\n\n---\n\nINFO:{router_section}"
            elif "\n\n---\n\n" in old_body_markdown and "catering packages" in old_body_markdown.lower():
                # Fallback: try to find catering content after separator
                parts = old_body_markdown.rsplit("\n\n---\n\n", 1)
                if len(parts) == 2 and "catering packages" in parts[1].lower():
                    body_markdown = f"{body_markdown}\n\n---\n\n{parts[1]}"

        footer_text = "Step: 2 Date Confirmation · Next: Room Availability · State: Awaiting Client"
        draft["body_markdown"] = body_markdown
        draft["body"] = f"{body_markdown}\n\n---\n{footer_text}"
        draft["footer"] = footer_text
        draft["headers"] = [CLIENT_AVAILABILITY_HEADER]

    columns_meta = [
        {
            "key": field,
            "label": _column_label(field, select_fields),
        }
        for field in column_order
    ]
    table_block_rows = [
        {field: row[field] for field in column_order}
        for row in display_rows
    ]
    draft["table_blocks"] = [
        {
            "type": "table",
            "label": f"{CLIENT_AVAILABILITY_HEADER} Summary",
            "columns": columns_meta,
            "rows": table_block_rows,
            "column_order": list(column_order),
        }
    ]

    trace_general_qa_status(
        thread_id,
        "applied",
        {
            "topic": draft.get("topic"),
            "candidate_dates": len(candidate_dates),
            "has_table": True,
            "has_menu_payload": bool(menu_payload),
            "range_results": len(range_results),
            "select_fields": select_fields,
            "table_columns": list(column_order),
        },
    )


def render_general_qna_reply(state: WorkflowState, classification: Dict[str, Any]) -> Optional[GroupResult]:
    if not classification or not classification.get("is_general"):
        return None

    event_entry_after = state.event_entry or {}
    extraction_payload = state.extras.get("qna_extraction")
    structured_result = build_structured_qna_result(state, extraction_payload) if extraction_payload else None

    if structured_result is None:
        return None

    raw_step = event_entry_after.get("current_step")
    try:
        current_step = int(raw_step) if raw_step is not None else 2
    except (TypeError, ValueError):
        current_step = 2
    thread_state = event_entry_after.get("thread_state") or state.thread_state or "Awaiting Client"

    table_blocks = _structured_table_blocks(structured_result.action_payload.get("db_summary", {}))
    body_markdown = (structured_result.body_markdown or _fallback_structured_body(structured_result.action_payload)).strip()

    if structured_result.handled and body_markdown:
        # Build verbalize_context from db_summary for fact verification
        db_summary = structured_result.action_payload.get("db_summary", {})
        verbalize_context = _build_verbalize_context(db_summary, event_entry_after)

        footer_body = append_footer(
            body_markdown,
            step=current_step,
            next_step=current_step,
            thread_state=thread_state,
            topic="structured_qna",
            verbalize_context=verbalize_context,
        )
        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": current_step,
            "topic": "structured_qna",
            "next_step": current_step,
            "thread_state": thread_state,
            "headers": [CLIENT_AVAILABILITY_HEADER],
            "requires_approval": False,
            "subloop": "structured_qna",
            "table_blocks": table_blocks,
        }
        state.record_subloop("structured_qna")
        state.add_draft_message(draft_message)
        state.set_thread_state(thread_state)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry_after.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": False,
        "general_qna": True,
        "structured_qna": structured_result.handled,
        "qna_select_result": structured_result.action_payload,
        "structured_qna_debug": structured_result.debug,
        "structured_qna_tables": table_blocks,
    }
    if extraction_payload:
        payload["qna_extraction"] = extraction_payload

    state.turn_notes["structured_qna_table"] = table_blocks
    return GroupResult(action="qna_select_result", payload=payload)


def _structured_table_blocks(db_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rooms = db_summary.get("rooms") or []
    if not rooms:
        return []

    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in rooms:
        name = str(entry.get("room_name") or entry.get("room_id") or "Room").strip()
        bucket = grouped.setdefault(
            name,
            {"dates": set(), "notes": set()},
        )
        date_label = entry.get("date")
        if date_label:
            bucket["dates"].add(_format_display_date(str(date_label)))
        status = entry.get("status")
        if status:
            bucket["notes"].add(f"Status: {status}")
        capacity = entry.get("capacity_max")
        if capacity:
            bucket["notes"].add(f"Capacity up to {capacity}")
        products = entry.get("products") or []
        if products:
            bucket["notes"].add(f"Products: {', '.join(products)}")

    rows: List[Dict[str, Any]] = []
    for name, payload in sorted(grouped.items(), key=lambda item: item[0].lower()):
        rows.append(
            {
                "Room": name,
                "Dates": ", ".join(sorted(payload["dates"])) if payload["dates"] else "—",
                "Notes": "; ".join(sorted(payload["notes"])) if payload["notes"] else "—",
            }
        )
    if not rows:
        return []
    return [
        {
            "type": "dates",
            "label": "Dates & Rooms",
            "rows": rows,
        }
    ]


def _fallback_structured_body(action_payload: Dict[str, Any]) -> str:
    # Don't include header here - it's set in headers[] and joined by _format_draft_text
    lines = []
    summary = action_payload.get("db_summary") or {}
    rooms = summary.get("rooms") or []
    products = summary.get("products") or []
    dates = summary.get("dates") or []
    notes = summary.get("notes") or []

    if rooms:
        lines.append("")
        lines.append("Rooms:")
        for entry in rooms[:5]:
            name = entry.get("room_name") or entry.get("room_id")
            date_label = entry.get("date")
            capacity = entry.get("capacity_max")
            status = entry.get("status")
            descriptor = []
            if capacity:
                descriptor.append(f"up to {capacity} pax")
            if status:
                descriptor.append(status)
            if date_label:
                descriptor.append(_format_display_date(str(date_label)))
            suffix = f" ({', '.join(descriptor)})" if descriptor else ""
            lines.append(f"- {name}{suffix}")

    if dates:
        lines.append("")
        lines.append("Dates:")
        for entry in dates[:5]:
            date_label = entry.get("date")
            room_label = entry.get("room_name") or entry.get("room_id")
            status = entry.get("status")
            descriptor = " – ".join(filter(None, [room_label, status]))
            lines.append(f"- {_format_display_date(str(date_label))} {descriptor}".strip())

    if products:
        lines.append("")
        lines.append("Products:")
        for entry in products[:5]:
            name = entry.get("product")
            availability = "available" if entry.get("available_today") else "not available today"
            lines.append(f"- {name} ({availability})")

    if notes:
        lines.append("")
        for entry in notes[:3]:
            lines.append(f"- {entry}")

    body = "\n".join(lines).strip()

    # Add fallback diagnostic if no data was found
    rooms_count = len(rooms)
    dates_count = len(dates)
    products_count = len(products)

    if SHOW_FALLBACK_DIAGNOSTICS and rooms_count == 0 and dates_count == 0 and products_count == 0:
        reason = empty_results_reason(
            source="structured_qna_body",
            rooms_count=rooms_count,
            dates_count=dates_count,
            products_count=products_count,
        )
        # Add context about what query produced empty results
        effective = action_payload.get("effective") or {}
        reason.context["query_date"] = effective.get("date")
        reason.context["query_attendees"] = effective.get("attendees")
        reason.context["query_room"] = effective.get("room")
        body += format_fallback_diagnostic(reason)

    return body


def append_general_qna_to_primary(state: WorkflowState) -> bool:
    """
    Attach the most recent general Q&A draft to the current primary draft message.

    Returns True if the merge succeeded (and the Q&A draft was consumed), False otherwise.
    """

    drafts = state.draft_messages
    if not drafts:
        return False

    qa_draft = drafts.pop()
    if not drafts:
        drafts.append(qa_draft)
        return False

    qa_body = (qa_draft.get("body_markdown") or qa_draft.get("body") or "").strip()
    if not qa_body:
        drafts.append(qa_draft)
        return False

    lowered_body = qa_body.lower()
    if (
        "no specific information available" in lowered_body
        or "[structured_qna_fallback" in lowered_body
    ):
        drafts.append(qa_draft)
        return False

    primary = drafts[-1]
    primary_body = (primary.get("body_markdown") or primary.get("body") or "").strip()
    combined_body = f"{primary_body}\n\n{qa_body}" if primary_body else qa_body
    primary["body_markdown"] = combined_body

    footer = primary.get("footer") or ""
    if footer:
        primary["body"] = f"{combined_body}\n\n---\n{footer}"
    else:
        primary["body"] = combined_body

    primary.setdefault("table_blocks", [])
    primary["table_blocks"].extend(qa_draft.get("table_blocks") or [])

    headers = list(primary.get("headers") or [])
    for header in qa_draft.get("headers") or []:
        if header not in headers:
            headers.append(header)
    if headers:
        primary["headers"] = headers

    return True


# -----------------------------------------------------------------------------
# Shared Q&A Handler for Steps 3, 4, 5, 7
# -----------------------------------------------------------------------------


def present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
    step_number: int,
    step_name: str,
) -> GroupResult:
    """
    Handle general Q&A using a unified pattern across workflow steps.

    This shared implementation replaces duplicate ~170-line functions in
    step3_handler, step4_handler, step5_handler, and step7_handler.

    Args:
        state: Current workflow state
        event_entry: Event database record
        classification: Q&A classification result
        thread_id: Optional thread identifier
        step_number: Current step number (3, 4, 5, or 7)
        step_name: Human-readable step name for messages (e.g., "Room Availability")

    Returns:
        GroupResult with action "general_rooms_qna"
    """
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    resolved_thread_id = thread_id or state.thread_id

    if thread_id:
        set_subloop(thread_id, subloop_label)

    # Extract fresh from current message (multi-turn Q&A fix)
    message = state.message
    subject = (message.subject if message else "") or ""
    body = (message.body if message else "") or ""
    message_text = f"{subject}\n{body}".strip() or body or subject

    # -------------------------------------------------------------------------
    # CATERING/PRODUCT Q&A ROUTING FIX
    # Check if this is a catering or product question based on classification
    # secondary types. Route to route_general_qna for proper handling.
    # -------------------------------------------------------------------------
    secondary_types = classification.get("secondary") or []
    catering_types = {"catering_for", "products_for"}
    is_catering_question = bool(set(secondary_types) & catering_types)

    if is_catering_question:
        # Use route_general_qna for catering/product questions - it has proper handling
        msg_payload = {
            "subject": subject,
            "body": body,
            "thread_id": thread_id or state.thread_id,
            "msg_id": message.msg_id if message else "",
        }
        qna_result = route_general_qna(
            msg_payload,
            event_entry,
            event_entry,
            state.db,
            classification,
        )
        # Build response from route_general_qna result
        post_blocks = qna_result.get("post_step") or []
        pre_blocks = qna_result.get("pre_step") or []
        all_blocks = pre_blocks + post_blocks

        if all_blocks:
            first_block = all_blocks[0]
            body_markdown = first_block.get("body", "")
            topic = first_block.get("topic", "catering_for")
            footer_body = append_footer(
                body_markdown,
                step=step_number,
                next_step=step_number,
                thread_state="Awaiting Client",
            )
            draft_message = {
                "body": footer_body,
                "body_markdown": body_markdown,
                "step": step_number,
                "next_step": step_number,
                "thread_state": "Awaiting Client",
                "topic": topic,
                "subloop": subloop_label,
                "headers": ["Availability overview"],
                "router_qna_appended": True,
            }
            state.add_draft_message(draft_message)
            update_event_metadata(
                event_entry,
                thread_state="Awaiting Client",
                current_step=step_number,
            )
            state.set_thread_state("Awaiting Client")
            state.record_subloop(subloop_label)
            state.extras["persist"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
                "general_qna": True,
                "catering_qna": True,
                "qna_router_result": qna_result,
            }
            return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    scan = state.extras.get("general_qna_scan")
    # Force fresh extraction for multi-turn Q&A
    ensure_qna_extraction(state, message_text, scan, force_refresh=True)
    extraction = state.extras.get("qna_extraction")

    # Clear stale qna_cache AFTER extraction
    if isinstance(event_entry, dict):
        event_entry.pop("qna_cache", None)

    structured = build_structured_qna_result(state, extraction) if extraction else None

    if structured and structured.handled:
        rooms = structured.action_payload.get("db_summary", {}).get("rooms", [])
        date_lookup: Dict[str, str] = {}
        for entry in rooms:
            iso_date = entry.get("date") or entry.get("iso_date")
            if not iso_date:
                continue
            try:
                parsed = datetime.fromisoformat(iso_date)
            except ValueError:
                try:
                    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
                except ValueError:
                    continue
            label = parsed.strftime("%d.%m.%Y")
            date_lookup.setdefault(label, parsed.date().isoformat())

        candidate_dates = sorted(date_lookup.keys(), key=lambda lbl: date_lookup[lbl])[:5]
        actions = [
            {
                "type": "select_date",
                "label": f"Confirm {label}",
                "date": label,
                "iso_date": date_lookup[label],
            }
            for label in candidate_dates
        ]

        body_markdown = (structured.body_markdown or _fallback_structured_body(structured.action_payload)).strip()
        footer_body = append_footer(
            body_markdown,
            step=step_number,
            next_step=step_number,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": step_number,
            "next_step": step_number,
            "thread_state": "Awaiting Client",
            "topic": "general_room_qna",
            "candidate_dates": candidate_dates,
            "actions": actions,
            "subloop": subloop_label,
            "headers": ["Availability overview"],
        }

        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            thread_state="Awaiting Client",
            current_step=step_number,
            candidate_dates=candidate_dates,
        )
        state.set_thread_state("Awaiting Client")
        state.record_subloop(subloop_label)
        state.intent_detail = "event_intake_with_question"
        state.extras["persist"] = True

        # Store minimal last_general_qna context for follow-up detection only
        if extraction and isinstance(event_entry, dict):
            q_values = extraction.get("q_values") or {}
            event_entry["last_general_qna"] = {
                "topic": structured.action_payload.get("qna_subtype"),
                "date_pattern": q_values.get("date_pattern"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "candidate_dates": candidate_dates,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "general_qna": True,
            "structured_qna": structured.handled,
            "qna_select_result": structured.action_payload,
            "structured_qna_debug": structured.debug,
            "actions": actions,
        }
        if extraction:
            payload["qna_extraction"] = extraction
        return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    # Fallback if structured Q&A failed
    fallback_prompt = "[STRUCTURED_QNA_FALLBACK]\nI couldn't load the structured Q&A context for this request. Please review extraction logs."
    draft_message = {
        "step": step_number,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: {step_number} {step_name} · Next: {step_number} {step_name} · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": step_number,
        "thread_state": "Awaiting Client",
        "headers": ["Availability overview"],
        "requires_approval": False,
        "subloop": subloop_label,
        "actions": [],
        "candidate_dates": [],
    }
    state.add_draft_message(draft_message)
    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=step_number,
        candidate_dates=[],
    )
    state.set_thread_state("Awaiting Client")
    state.record_subloop(subloop_label)
    state.intent_detail = "event_intake_with_question"
    state.extras["structured_qna_fallback"] = True
    structured_payload = structured.action_payload if structured else {}
    structured_debug = structured.debug if structured else {"reason": "missing_structured_context"}

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": [],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "general_qna": True,
        "structured_qna": False,
        "structured_qna_fallback": True,
        "qna_select_result": structured_payload,
        "structured_qna_debug": structured_debug,
    }
    if extraction:
        payload["qna_extraction"] = extraction
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)


__all__ = [
    "append_general_qna_to_primary",
    "present_general_room_qna",
    "render_general_qna_reply",
    "enrich_general_qna_step2",
]
