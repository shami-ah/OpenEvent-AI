from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.services.qna_readonly import (
    RoomAvailabilityRow,
    RoomSummary,
    fetch_product_repertoire,
    fetch_room_availability,
    list_rooms_by_capacity,
    load_room_static,
)
from backend.workflows.common.types import WorkflowState
from backend.workflows.qna.context_builder import EffectiveVariable, QnAContext, build_qna_context
from backend.workflows.qna.verbalizer import render_qna_answer


@dataclass
class StructuredQnAResult:
    handled: bool
    action_payload: Dict[str, Any]
    body_markdown: Optional[str]
    unresolved: List[str]
    debug: Dict[str, Any]


def build_structured_qna_result(state: WorkflowState, extraction: Dict[str, Any]) -> Optional[StructuredQnAResult]:
    """
    Combine extraction payload, captured state, read-only adapters, and verbalizer output into the
    debugger-friendly action payload.
    """

    if not extraction or extraction.get("msg_type") == "non_event":
        return None

    qna_intent = extraction.get("qna_intent")
    qna_subtype = extraction.get("qna_subtype") or ""
    if qna_intent not in {"select_dependent", "select_static", "update_candidate"}:
        return None

    q_values = extraction.get("q_values") or {}
    captured_state = _captured_state(state.event_entry)
    context = build_qna_context(qna_intent, qna_subtype, q_values, captured_state)

    effective_payload = _effective_payload(context)
    debug_info = {
        "extraction": extraction,
        "case_tags": context.case_tags,
        "effective": effective_payload,
        "unresolved": list(context.unresolved),
    }
    state.turn_notes["structured_qna"] = debug_info
    state.turn_notes["structured_qna_handled"] = context.handled

    base_payload: Dict[str, Any] = {
        "qna_intent": context.intent,
        "qna_subtype": context.subtype,
        "effective": effective_payload,
        "exclude_rooms": context.exclude_rooms,
        "case_tags": context.case_tags,
        "extraction": extraction,
        "debug": debug_info,
    }

    if not context.handled:
        action_payload = dict(base_payload)
        action_payload.update(
            {
                "handled": False,
                "unresolved": list(context.unresolved),
                "db_summary": {"rooms": [], "dates": [], "products": [], "notes": []},
            }
        )
        return StructuredQnAResult(
            handled=False,
            action_payload=action_payload,
            body_markdown=None,
            unresolved=list(context.unresolved),
            debug=debug_info,
        )

    db_results = _execute_query(context)
    action_payload = dict(base_payload)
    action_payload.update(
        {
            "handled": True,
            "unresolved": list(context.unresolved),
            "db_summary": db_results,
        }
    )

    verbalizer_payload = {
        "qna_intent": context.intent,
        "qna_subtype": context.subtype,
        "effective": effective_payload,
        "db_results": db_results,
        "unresolved": list(context.unresolved),
    }
    verbalizer_output = render_qna_answer(verbalizer_payload)
    action_payload["verbalizer"] = verbalizer_output

    body_markdown = verbalizer_output.get("body_markdown")
    return StructuredQnAResult(
        handled=True,
        action_payload=action_payload,
        body_markdown=body_markdown,
        unresolved=list(context.unresolved),
        debug=debug_info,
    )


def _execute_query(context: QnAContext) -> Dict[str, List[Dict[str, Any]]]:
    subtype = context.subtype
    eff = context.effective
    results = {"rooms": [], "dates": [], "products": [], "notes": []}

    if subtype in {"catalog_by_capacity", "room_catalog_with_products"}:
        rows = list_rooms_by_capacity(
            min_capacity=_attendee_min(eff["N"]),
            capacity_range=eff["N"].value if isinstance(eff["N"].value, dict) else None,
            product_requirements=eff["P"].value if isinstance(eff["P"].value, list) else [],
        )
        results["rooms"] = [_room_summary_to_dict(row) for row in rows]
        return results

    if subtype in {
        "room_list_for_us",
        "room_specific_availability",
        "room_followup_same_context",
        "room_recommendation_by_month",
        "room_exclusion_followup",
        "date_pattern_availability",
        "date_pattern_availability_general",
    }:
        rows = fetch_room_availability(
            date_scope=_date_scope_payload(eff["D"], context.base_date),
            attendee_scope=eff["N"].value,
            room_filter=eff["R"].value,
            exclude_rooms=context.exclude_rooms,
            product_requirements=eff["P"].value if isinstance(eff["P"].value, list) else [],
        )
        results["rooms"] = [_room_availability_to_dict(row) for row in rows]
        results["dates"] = [entry for entry in results["rooms"] if entry.get("date")]
        return results

    if subtype in {"room_capacity_static", "room_specific_capacity_check", "room_capacity_delta"}:
        room_id = eff["R"].value
        if not room_id:
            return results
        room_static = load_room_static(room_id)
        results["rooms"] = [room_static] if room_static else []
        capacity_note = _capacity_note(room_static, eff["N"])
        if capacity_note:
            results["notes"].append(capacity_note)
        return results

    if subtype == "room_feature_truth":
        room_id = eff["R"].value
        if room_id:
            room_static = load_room_static(room_id)
            results["rooms"] = [room_static] if room_static else []
        return results

    if subtype == "room_product_truth":
        room_id = eff["R"].value
        products = eff["P"].value if isinstance(eff["P"].value, list) else []
        records = fetch_product_repertoire(
            product_names=products,
            effective_date=date.today(),
            room_filter=room_id,
        )
        results["products"] = [_product_record_to_dict(record) for record in records]
        if room_id:
            room_static = load_room_static(room_id)
            if room_static:
                results["rooms"] = [room_static]
        return results

    if subtype in {"product_catalog", "product_truth", "product_recommendation_for_us", "repertoire_check"}:
        products = eff["P"].value if isinstance(eff["P"].value, list) else []
        records = fetch_product_repertoire(
            product_names=products,
            effective_date=date.today(),
            room_filter=eff["R"].value,
        )
        results["products"] = [_product_record_to_dict(record) for record in records]
        return results

    # Fallback for unhandled subtypes (including "non_event_info"):
    # If we have captured context (date, attendees), still try to return room availability
    # This prevents empty results when classification produces unexpected subtypes
    if subtype in {"non_event_info", "unknown"} or not subtype:
        # Check if we have any useful context from the captured state
        has_date = eff["D"].value is not None or eff["D"].source == "C"
        has_attendees = eff["N"].value is not None or eff["N"].source == "C"

        if has_date or has_attendees:
            # Try room availability query with whatever context we have
            rows = fetch_room_availability(
                date_scope=_date_scope_payload(eff["D"], context.base_date),
                attendee_scope=eff["N"].value,
                room_filter=eff["R"].value,
                exclude_rooms=context.exclude_rooms,
                product_requirements=eff["P"].value if isinstance(eff["P"].value, list) else [],
            )
            results["rooms"] = [_room_availability_to_dict(row) for row in rows]
            results["dates"] = [entry for entry in results["rooms"] if entry.get("date")]
            if results["rooms"]:
                results["notes"].append(
                    "Showing available rooms based on your event details."
                )
            return results

        # No context available - return rooms by capacity as a fallback
        rows = list_rooms_by_capacity(
            min_capacity=None,
            capacity_range=None,
            product_requirements=[],
        )
        results["rooms"] = [_room_summary_to_dict(row) for row in rows]
        if results["rooms"]:
            results["notes"].append(
                "Here are our available rooms. Let me know your date and guest count for specific availability."
            )
        return results

    return results


def _effective_payload(context: QnAContext) -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    for key, variable in context.effective.items():
        payload[key] = {
            "value": variable.value,
            "source": variable.source,
            "meta": variable.meta,
        }
    return payload


def _captured_state(event_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    captured = {
        "date": None,
        "attendees": None,
        "room": None,
        "locked_room": None,
        "products": [],
    }
    if not event_entry:
        return captured

    requirements = event_entry.get("requirements") or {}
    attendees = requirements.get("number_of_participants") or requirements.get("participants")
    try:
        captured["attendees"] = int(attendees) if attendees is not None else None
    except (TypeError, ValueError):
        captured["attendees"] = None

    captured["locked_room"] = event_entry.get("locked_room_id")
    captured["room"] = captured["locked_room"] or requirements.get("preferred_room")

    requested_window = event_entry.get("requested_window") or {}
    if requested_window.get("date_iso"):
        captured["date"] = requested_window["date_iso"]
    else:
        chosen = event_entry.get("chosen_date")
        if chosen:
            try:
                parsed = datetime.strptime(chosen, "%d.%m.%Y")
                captured["date"] = parsed.date().isoformat()
            except (ValueError, TypeError):
                captured["date"] = None

    wish_products = event_entry.get("wish_products")
    products = event_entry.get("products") or event_entry.get("selected_products")
    if wish_products and isinstance(wish_products, list):
        captured["products"] = [str(entry).strip() for entry in wish_products if str(entry).strip()]
    elif products and isinstance(products, list):
        captured["products"] = [str(entry).strip() for entry in products if str(entry).strip()]

    return captured


def _room_availability_to_dict(row: RoomAvailabilityRow) -> Dict[str, Any]:
    return {
        "room_id": row.room_id,
        "room_name": row.room_name,
        "capacity_max": row.capacity_max,
        "date": row.date,
        "status": row.status,
        "features": list(row.features),
        "products": list(row.products),
    }


def _room_summary_to_dict(row: RoomSummary) -> Dict[str, Any]:
    return {
        "room_id": row.room_id,
        "room_name": row.room_name,
        "capacity_max": row.capacity_max,
        "capacity_by_layout": dict(row.capacity_by_layout),
        "products": list(row.products),
    }


def _product_record_to_dict(record) -> Dict[str, Any]:
    return {
        "product": record.product,
        "category": record.category,
        "rooms": list(record.rooms),
        "available_today": record.available_today,
        "attributes": list(record.attributes),
    }


def _capacity_note(room_static: Dict[str, Any], effective_attendees: EffectiveVariable) -> Optional[str]:
    if not room_static:
        return None
    max_capacity = room_static.get("capacity_max")
    attendees = effective_attendees.value
    if attendees is None:
        return None
    required = _attendee_min(effective_attendees)
    if required is None or max_capacity is None:
        return None
    if max_capacity >= required:
        return f"{room_static.get('room_name', 'Room')} fits {required} guests."
    return f"{room_static.get('room_name', 'Room')} caps at {max_capacity} guests — below the requested {required}."


def _attendee_min(variable: EffectiveVariable) -> Optional[int]:
    value = variable.value
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        minimum = value.get("min") or value.get("minimum") or value.get("max") or value.get("maximum")
        try:
            return int(minimum) if minimum is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _date_scope_payload(effective_date: EffectiveVariable, base_date: Optional[date]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "value": effective_date.value,
        "meta": effective_date.meta,
        "source": effective_date.source,
        "base_date": base_date.isoformat() if base_date else None,
    }
    return payload


__all__ = ["build_structured_qna_result", "StructuredQnAResult"]
