from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import LLMNode, OpenEventAction

__all__ = ["ComposeOffer", "EmailOffer", "ChatFollowUp", "send_offer_email"]


class ComposeOffer(LLMNode):
    """Compose the structured offer payload from event details."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not payload.get("offer_ready_to_generate", True):
            raise ValueError("Offer generation not approved by manager.")

        event_id = payload["event_id"]
        pricing_inputs: Dict[str, Any] = payload.get("pricing_inputs", {})
        line_items: List[Dict[str, Any]] = list(pricing_inputs.get("line_items") or [])

        total_amount = 0.0
        base_rate = pricing_inputs.get("base_rate")
        if base_rate is not None:
            total_amount += float(base_rate)

        for item in line_items:
            amount = float(item.get("amount", 0))
            total_amount += amount
            item["amount"] = amount

        manual_total = pricing_inputs.get("total_amount")
        if manual_total is not None and total_amount == 0.0:
            total_amount = float(manual_total)

        if total_amount == 0.0 and pricing_inputs.get("quantity") and pricing_inputs.get("unit_price"):
            total_amount = float(pricing_inputs["quantity"]) * float(pricing_inputs["unit_price"])

        offer_document = {
            "event_id": event_id,
            "user_info": payload.get("user_info_final", {}),
            "selected_room": payload.get("selected_room", {}),
            "pricing": {
                "line_items": line_items,
                "notes": pricing_inputs.get("notes"),
            },
        }

        offer_id = payload.get("offer_id") or f"{event_id}-OFFER"
        return {
            "offer_id": offer_id,
            "offer_document": offer_document,
            "total_amount": round(total_amount, 2),
        }


class EmailOffer(OpenEventAction):
    """Adapter to deliver the composed offer via email."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        client_contact = payload.get("client_contact", {})
        if not client_contact.get("email"):
            raise ValueError("Client email address is required to send the offer.")

        sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return {
            "offer_id": payload["offer_id"],
            "email_sent": True,
            "sent_at": sent_at,
        }


class ChatFollowUp(LLMNode):
    """LLM-crafted follow-up message posted in chat after emailing the offer."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        visit_allowed = bool(payload.get("visit_allowed", False))
        working_hours: Dict[str, str] = payload.get("working_hours") or {"start": "09:00", "end": "18:00"}
        deposit_percent = payload.get("deposit_percent")

        message_parts: List[str] = [
            "Thanks for sending all the details. We now have everything we need.",
            "I've just sent you an initial offer by email based on your selected options.",
            "If you'd like, we can place an initial reservation for this date.",
        ]

        if visit_allowed:
            message_parts.append(
                f"We can also arrange a viewing. Please propose 2-3 times that work for you; "
                f"our working hours are {working_hours['start']}–{working_hours['end']}."
            )

        if deposit_percent is not None and deposit_percent > 0:
            message_parts.append(
                f"To fully confirm the event, a {deposit_percent}% deposit of the total will be required."
            )

        message = " ".join(message_parts)
        return {
            "chat_posted": True,
            "message": message,
        }


def send_offer_email(event_entry: Dict[str, Any], offer_id: str, to_email: str, cc: Optional[str] = None) -> Dict[str, Any]:
    """Thin wrapper used by tools for deterministic offer delivery."""

    action = EmailOffer()
    payload = {
        "offer_id": offer_id,
        "client_contact": {"email": to_email, "cc": cc},
        "event_entry": event_entry,
    }
    return action.run(payload)
