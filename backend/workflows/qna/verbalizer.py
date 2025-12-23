from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - dependency may be missing in tests
    OpenAI = None  # type: ignore
from backend.utils.openai_key import load_openai_api_key
from backend.workflows.common.fallback_reason import (
    FallbackReason,
    append_fallback_diagnostic,
    llm_disabled_reason,
    llm_exception_reason,
    empty_results_reason,
)

MODEL_NAME = os.getenv("OPEN_EVENT_QNA_VERBALIZER_MODEL", "gpt-4.1-mini")
_LLM_ENABLED = bool(load_openai_api_key(required=False) and OpenAI is not None)

SYSTEM_PROMPT = (
    "You are OpenEvent's structured Q&A verbalizer. Craft concise markdown answers for clients "
    "using the provided structured context and query results. Keep tone helpful and factual."
)


def render_qna_answer(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert structured DB results into markdown answer blocks.

    When the gpt-4.1-mini runtime is unavailable, fall back to a deterministic formatter so tests
    remain stable.
    """
    fallback_reason: Optional[FallbackReason] = None

    if _LLM_ENABLED:
        try:
            return _call_llm(payload)
        except Exception as exc:  # pragma: no cover - defensive guard
            fallback_reason = llm_exception_reason("qna_verbalizer", exc)
    else:
        fallback_reason = llm_disabled_reason("qna_verbalizer")

    return _fallback_answer(payload, fallback_reason)


def _call_llm(payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        top_p=0,
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content if response.choices else ""
    return {
        "model": MODEL_NAME,
        "body_markdown": content.strip(),
        "used_fallback": False,
    }


def _fallback_answer(
    payload: Dict[str, Any],
    fallback_reason: Optional[FallbackReason] = None,
) -> Dict[str, Any]:
    intent = payload.get("qna_intent")
    subtype = payload.get("qna_subtype")
    effective = payload.get("effective") or {}
    db_results = payload.get("db_results") or {}

    lines = [f"*Intent*: {intent} · *Subtype*: {subtype}"]

    room_rows = db_results.get("rooms") or []
    if room_rows:
        lines.append("")
        lines.append("**Rooms**")
        for entry in room_rows:
            name = entry.get("room_name") or entry.get("room_id")
            cap = entry.get("capacity_max")
            status = entry.get("status")
            descriptor = []
            if cap:
                descriptor.append(f"capacity up to {cap}")
            if status:
                descriptor.append(status)
            lines.append(f"- {name}{' (' + ', '.join(descriptor) + ')' if descriptor else ''}")

    product_rows = db_results.get("products") or []
    if product_rows:
        lines.append("")
        lines.append("**Products**")
        for entry in product_rows:
            name = entry.get("product")
            availability = "available" if entry.get("available_today") else "not currently available"
            lines.append(f"- {name}: {availability}")

    date_rows = db_results.get("dates") or []
    if date_rows:
        lines.append("")
        lines.append("**Dates**")
        for entry in date_rows:
            date_label = entry.get("date")
            room_label = entry.get("room_name") or entry.get("room_id")
            status = entry.get("status")
            lines.append(f"- {date_label} — {room_label} ({status})")

    notes = db_results.get("notes") or []
    if notes:
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")

    if not lines:
        lines.append("Let me know if you'd like me to pull more details.")

    body = "\n".join(lines).strip()

    # Check if this is an empty result fallback (no rooms, dates, or products)
    rooms_count = len(room_rows)
    dates_count = len(date_rows)
    products_count = len(product_rows)

    if fallback_reason is None and rooms_count == 0 and dates_count == 0 and products_count == 0:
        fallback_reason = empty_results_reason(
            "qna_verbalizer",
            rooms_count=rooms_count,
            dates_count=dates_count,
            products_count=products_count,
        )

    # Append diagnostic info if we have a fallback reason
    if fallback_reason:
        # Add context about what data was available
        fallback_reason.context["rooms_count"] = rooms_count
        fallback_reason.context["dates_count"] = dates_count
        fallback_reason.context["products_count"] = products_count
        fallback_reason.context["intent"] = intent
        fallback_reason.context["subtype"] = subtype
        body = append_fallback_diagnostic(body, fallback_reason)

    return {
        "model": "fallback",
        "body_markdown": body,
        "used_fallback": True,
        "fallback_reason": fallback_reason.to_dict() if fallback_reason else None,
    }


__all__ = ["render_qna_answer"]
