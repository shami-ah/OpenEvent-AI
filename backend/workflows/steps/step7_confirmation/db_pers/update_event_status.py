from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import OpenEventAction
__workflow_role__ = "db_pers"

__all__ = ["UpdateEventStatus"]


class UpdateEventStatus(OpenEventAction):
    """Persist event state after interpreting the client's response."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_id = payload["event_id"]
        intent = payload.get("intent", "questions")
        deposit_percent = payload.get("deposit_percent")
        deposit_acknowledged = bool(payload.get("deposit_acknowledged", False))
        deposit_status_override = payload.get("deposit_status_override")
        proposed_times: List[str] = list(payload.get("proposed_times") or [])
        total_amount = float(payload.get("total_amount", 0.0))
        visit_allowed = bool(payload.get("visit_allowed", False))
        current_status = payload.get("current_event_status", "Option")

        deposit_status = self._determine_deposit_status(
            deposit_percent,
            deposit_acknowledged,
            deposit_status_override,
        )

        event_status = current_status
        next_required_action = "none"

        if intent == "reserve_only":
            event_status = "Option"
            if deposit_status not in {"not_required", "paid"}:
                next_required_action = "await_deposit"
        elif intent == "request_viewing":
            # Status remains unchanged, but schedule viewing if allowed.
            if visit_allowed and proposed_times:
                next_required_action = "schedule_viewing"
            else:
                next_required_action = "none"
        elif intent in {"negotiate", "questions"}:
            event_status = current_status
            next_required_action = "manager_clarification" if intent == "negotiate" else "none"
        elif intent == "accept":
            if deposit_percent in (None, 0):
                event_status = "Confirmed"
                next_required_action = "none"
            elif deposit_status == "paid":
                event_status = "Confirmed"
                next_required_action = "none"
            else:
                event_status = "Option"
                next_required_action = "await_deposit"
        else:
            event_status = current_status

        deposit_due_amount = round(total_amount * ((deposit_percent or 0) / 100.0), 2)

        response: Dict[str, Any] = {
            "event_id": event_id,
            "event_status": event_status,
            "deposit_status": deposit_status,
            "deposit_percent": deposit_percent,
            "deposit_due_amount": deposit_due_amount,
            "viewing_requested_times": proposed_times if intent == "request_viewing" else [],
            "next_required_action": next_required_action,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        if intent in {"negotiate", "questions"}:
            response["requested_changes"] = payload.get("requested_changes", {})

        return response

    @staticmethod
    def _determine_deposit_status(
        deposit_percent: Optional[float],
        deposit_acknowledged: bool,
        deposit_status_override: Optional[str],
    ) -> str:
        if deposit_percent in (None, 0):
            return "not_required"
        if deposit_status_override == "paid":
            return "paid"
        if deposit_acknowledged:
            return "acknowledged"
        return "required"
