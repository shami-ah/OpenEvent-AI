from __future__ import annotations

from typing import Any, Dict

from .. import OpenEventAction

__workflow_role__ = "hil"

__all__ = ["CreateProfessionalOffer"]


class CreateProfessionalOffer(OpenEventAction):
    """
    Manager approval node that locks visit/deposit rules
    and authorises the system to generate the professional offer.
    """

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_id = payload["event_id"]
        ui_rules: Dict[str, Any] = payload.get("ui_rules", {})

        visit_allowed = bool(ui_rules.get("visit_allowed", False))
        working_hours = ui_rules.get("working_hours") or {"start": "09:00", "end": "18:00"}
        deposit_percent = ui_rules.get("deposit_percent")

        response: Dict[str, Any] = {
            "event_id": event_id,
            "offer_ready_to_generate": True,
            "visit_allowed": visit_allowed,
            "working_hours": working_hours,
            "deposit_percent": deposit_percent,
        }

        response["user_info_final"] = payload.get("user_info_final", {})
        response["selected_room"] = payload.get("selected_room", {})
        response["pricing_inputs"] = payload.get("pricing_inputs", {})
        response["client_contact"] = payload.get("client_contact", {})

        return response
