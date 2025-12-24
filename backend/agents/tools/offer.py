from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from backend.workflows.steps.step4_offer.trigger.process import (
    ComposeOffer,
    _record_offer,  # type: ignore
)
from backend.workflows.steps.step4_offer.llm.send_offer_llm import send_offer_email  # type: ignore
from backend.workflows.common.catalog import list_products, list_catering

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "tool_build_offer_draft": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "user_info": {"type": "object"},
        },
        "required": ["event_entry"],
        "additionalProperties": False,
    },
    "tool_persist_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "pricing_inputs": {"type": "object"},
            "user_info": {"type": "object"},
        },
        "required": ["event_entry", "pricing_inputs"],
        "additionalProperties": False,
    },
    "tool_send_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "offer_id": {"type": "string"},
            "to_email": {"type": "string"},
            "cc": {"type": ["string", "null"]},
        },
        "required": ["event_entry", "offer_id", "to_email"],
        "additionalProperties": False,
    },
    "tool_list_products": {
        "type": "object",
        "properties": {
            "room_id": {"type": ["string", "null"]},
            "categories": {"type": ["array", "null"], "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
    "tool_list_catering": {
        "type": "object",
        "properties": {
            "room_id": {"type": ["string", "null"]},
            "date_token": {"type": ["string", "null"]},
            "categories": {"type": ["array", "null"], "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
    "tool_add_product_to_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "product": {"type": "object"},
        },
        "required": ["event_entry", "product"],
        "additionalProperties": False,
    },
    "tool_remove_product_from_offer": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "product": {"type": "object"},
        },
        "required": ["event_entry", "product"],
        "additionalProperties": False,
    },
    "tool_follow_up_suggest": {
        "type": "object",
        "properties": {
            "event_entry": {"type": "object"},
            "user_info": {"type": ["object", "null"]},
        },
        "required": ["event_entry"],
        "additionalProperties": False,
    },
}


class ComposeOfferInput(BaseModel):
    event_entry: Dict[str, Any]
    user_info: Dict[str, Any] = Field(default_factory=dict)


class ComposeOfferOutput(BaseModel):
    offer_id: str
    total_amount: float
    draft_ready: bool


def tool_build_offer_draft(event_entry: Dict[str, Any], params: ComposeOfferInput) -> ComposeOfferOutput:
    """
    Compose or refresh the offer draft using the existing ComposeOffer helper.

    This tool mirrors the behaviour inside the offer trigger workflow so that
    business logic remains centralized.
    """

    compose = ComposeOffer()
    offer_payload = {
        "offer_ready_to_generate": True,
        "event_id": event_entry.get("event_id"),
        "pricing_inputs": event_entry.get("pricing_inputs") or {},
        "user_info_final": event_entry.get("requirements") or {},
        "selected_room": {"name": event_entry.get("locked_room_id")},
    }
    composed = compose.run(offer_payload)
    offer_id = composed["offer_id"]
    total_amount = float(composed["total_amount"])
    return ComposeOfferOutput(offer_id=offer_id, total_amount=total_amount, draft_ready=True)


class PersistOfferInput(BaseModel):
    event_entry: Dict[str, Any]
    pricing_inputs: Dict[str, Any]
    user_info: Dict[str, Any] = Field(default_factory=dict)


class PersistOfferOutput(BaseModel):
    offer_id: str
    offer_sequence: int
    total_amount: float


def tool_persist_offer(event_entry: Dict[str, Any], params: PersistOfferInput) -> PersistOfferOutput:
    offer_id, sequence, total_amount = _record_offer(
        event_entry,
        params.pricing_inputs,
        params.user_info,
    )
    return PersistOfferOutput(offer_id=offer_id, offer_sequence=sequence, total_amount=total_amount)


class SendOfferInput(BaseModel):
    event_entry: Dict[str, Any]
    offer_id: str
    to_email: str
    cc: Optional[str]

    @validator("to_email")
    def _validate_email(cls, value: str) -> str:
        if "@" not in value:
            raise ValueError("to_email must contain '@'")
        return value


class SendOfferOutput(BaseModel):
    sent_at: str


def tool_send_offer(params: SendOfferInput) -> SendOfferOutput:
    """
    Deliver the composed offer via the existing LLM adapter.

    The send_offer_email helper already knows how to frame the email template,
    so the agent simply proxies the request.
    """

    send_offer_email(
        params.event_entry,
        params.offer_id,
        params.to_email,
        params.cc,
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    return SendOfferOutput(sent_at=timestamp)


class ListProductsInput(BaseModel):
    room_id: Optional[str]
    categories: Optional[List[str]]


class ListProductsOutput(BaseModel):
    items: List[Dict[str, Any]]


def tool_list_products(params: ListProductsInput) -> ListProductsOutput:
    items = list_products(room_id=params.room_id, categories=params.categories)
    return ListProductsOutput(items=items)


class ListCateringInput(BaseModel):
    room_id: Optional[str]
    date_token: Optional[str]
    categories: Optional[List[str]]


class ListCateringOutput(BaseModel):
    packages: List[Dict[str, Any]]


def tool_list_catering(params: ListCateringInput) -> ListCateringOutput:
    packages = list_catering(
        room_id=params.room_id,
        date_token=params.date_token,
        categories=params.categories,
    )
    return ListCateringOutput(packages=packages)


class ModifyProductInput(BaseModel):
    event_entry: Dict[str, Any]
    product: Dict[str, Any] = Field(..., description="Product descriptor with at least a name.")

    @validator("product")
    def _require_name(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value.get("name"):
            raise ValueError("product.name is required")
        return value


class ModifyProductOutput(BaseModel):
    selected_products: List[Dict[str, Any]]


def _selected_products(event_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected = event_entry.setdefault("selected_products", [])
    if isinstance(selected, list):
        return selected
    selected_list: List[Dict[str, Any]] = []
    event_entry["selected_products"] = selected_list
    return selected_list


def tool_add_product_to_offer(params: ModifyProductInput) -> ModifyProductOutput:
    selected = _selected_products(params.event_entry)
    entry = dict(params.product)
    if "quantity" not in entry:
        entry["quantity"] = 1
    selected.append(entry)
    return ModifyProductOutput(selected_products=selected)


def tool_remove_product_from_offer(params: ModifyProductInput) -> ModifyProductOutput:
    selected = _selected_products(params.event_entry)
    name = params.product.get("name", "").strip().lower()
    remaining = [item for item in selected if str(item.get("name", "")).strip().lower() != name]
    params.event_entry["selected_products"] = remaining
    return ModifyProductOutput(selected_products=remaining)


class FollowUpSuggestInput(BaseModel):
    status: Optional[str]
    pending_actions: Optional[List[str]]


class FollowUpSuggestOutput(BaseModel):
    suggestions: List[str]


def tool_follow_up_suggest(params: FollowUpSuggestInput) -> FollowUpSuggestOutput:
    """
    Provide deterministic follow-up suggestions for Step 7 loops.
    """

    suggestions: List[str] = []
    if params.status == "Option":
        suggestions.append("Send a reminder about the expiry date.")
    if params.status == "Lead":
        suggestions.append("Share a gentle follow-up asking if any details are missing.")
    if not suggestions:
        suggestions.append("Check availability for adjustments or answer outstanding questions.")
    return FollowUpSuggestOutput(suggestions=suggestions)


# Backwards compatibility with legacy agent scaffolding.
tool_compose_offer = tool_build_offer_draft
