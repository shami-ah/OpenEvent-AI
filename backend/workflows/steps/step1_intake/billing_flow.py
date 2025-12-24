from __future__ import annotations

from typing import Any, Dict, Optional

from backend.workflows.common.billing import billing_prompt_for_missing_fields, empty_billing_details
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.types import WorkflowState
from backend.workflows.io.database import update_event_billing
from backend.workflows.nlu import parse_billing_address


def handle_billing_capture(state: WorkflowState, event_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process newly captured billing information during intake."""

    user_info = state.user_info or {}
    raw_address = user_info.get("billing_address")
    if not raw_address:
        return None

    fallback_name = user_info.get("company")
    if not fallback_name:
        event_data = event_entry.get("event_data") or {}
        fallback_name = event_data.get("Company") or event_data.get("Name")

    parsed, missing = parse_billing_address(raw_address, fallback_name=fallback_name)
    parsed.setdefault("raw", raw_address.strip() if isinstance(raw_address, str) else raw_address)

    # Prevent re-processing on subsequent turns
    user_info.pop("billing_address", None)

    if missing:
        prompt = billing_prompt_for_missing_fields(missing)
        notice_lines = [
            "Thanks for sharing your billing details.",
            "",  # blank line for readability
            prompt,
        ]
        body = "\n".join(line for line in notice_lines if line)
        footer_body = append_footer(
            body,
            step=4,
            next_step="Provide billing info",
            thread_state="Awaiting Client",
        )
        state.add_draft_message(
            {
                "body": footer_body,
                "step": 4,
                "next_step": "Provide billing info",
                "thread_state": "Awaiting Client",
                "topic": "billing_missing_fields",
                "requires_approval": False,
            }
        )
        state.set_thread_state("Awaiting Client")
        event_entry.setdefault("billing_details", empty_billing_details())
        event_entry.setdefault("billing_validation", {})["missing"] = list(missing)
        state.extras["persist"] = True
        return {"status": "missing_fields", "missing": list(missing)}

    event_id = event_entry.get("event_id")
    if not event_id:
        return {"status": "error", "reason": "missing_event_id"}

    try:
        update_event_billing(state.db, event_id, parsed)
    except Exception as exc:  # pragma: no cover - defensive guard
        return {"status": "error", "reason": str(exc)}

    state.extras["persist"] = True
    return {"status": "saved"}
