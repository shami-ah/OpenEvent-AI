from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.utils.openai_key import load_openai_api_key
from backend.ux.verb_rubric import enforce as enforce_rubric
from backend.workflows.io.config_store import get_currency_code

logger = logging.getLogger(__name__)

HEADERS_TO_PRESERVE = {
    "AVAILABLE DATES:",
    "ROOM OPTIONS:",
    "NEXT STEP:",
    "OFFER:",
    "PRICE:",
    "VALID UNTIL:",
    "DEPOSIT:",
    "DEADLINE:",
    "AVAILABLE SLOTS:",
    "FOLLOW-UP:",
    "INFO:",
}


def verbalize_gui_reply(
    drafts: List[Dict[str, Any]],
    fallback_text: str,
    *,
    client_email: str | None = None,
) -> str:
    """
    Generate the client-facing reply while preserving deterministic workflow facts.

    Tone selection is controlled by VERBALIZER_TONE (empathetic | plain). When
    the desired tone cannot be produced (e.g., SDK failure), the function
    automatically falls back to the plain deterministic text.
    """

    # Passthrough when workflow already provided structured Markdown.
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        pre = draft.get("body_markdown") or draft.get("body_md")
        if isinstance(pre, str) and pre.strip():
            return pre

    fallback_text = (fallback_text or "").strip()
    if not fallback_text:
        return fallback_text

    tone = _resolve_tone()
    sections = _split_required_sections(fallback_text)
    must_contain_slot = "18:00–22:00" in fallback_text

    if tone == "plain":
        logger.debug(
            "verbalizer plain tone used",
            extra=_telemetry_extra(tone, drafts, len(sections), False, None),
        )
        return enforce_rubric(fallback_text, fallback_text)

    try:
        prompt_input = _build_prompt_payload(drafts, fallback_text, sections, client_email)
        raw_response = _call_verbalizer(prompt_input)
    except Exception as exc:  # pragma: no cover - network guarded
        logger.warning(
            "verbalizer fallback to plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, str(exc)),
        )
        return enforce_rubric(fallback_text, fallback_text)

    candidate = raw_response.strip()
    if not candidate:
        logger.warning(
            "verbalizer empty response; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "empty"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    if not _validate_sections(candidate, sections):
        logger.warning(
            "verbalizer failed section validation; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "section_mismatch"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    if must_contain_slot and "18:00–22:00" not in candidate:
        logger.warning(
            "verbalizer missing 18:00–22:00 slot; using plain tone",
            extra=_telemetry_extra(tone, drafts, len(sections), True, "missing_slot"),
        )
        return enforce_rubric(fallback_text, fallback_text)

    logger.debug(
        "verbalizer empathetic tone applied",
        extra=_telemetry_extra(tone, drafts, len(sections), False, None),
    )
    return enforce_rubric(candidate, fallback_text)


def _resolve_tone() -> str:
    """Determine verbalization tone from environment.

    Default is 'empathetic' for human-like UX.
    Set VERBALIZER_TONE=plain to disable LLM verbalization.
    """
    tone_env = os.getenv("VERBALIZER_TONE")
    if tone_env:
        candidate = tone_env.strip().lower()
        if candidate in {"empathetic", "plain"}:
            return candidate
    # Check for explicit disable flag
    plain_flag = os.getenv("PLAIN_VERBALIZER", "")
    if plain_flag.strip().lower() in {"1", "true", "yes", "on"}:
        return "plain"
    # Default to empathetic for human-like UX
    return "empathetic"


def _telemetry_extra(
    tone: str,
    drafts: List[Dict[str, Any]],
    sections_count: int,
    fallback_used: bool,
    reason: Optional[str],
) -> Dict[str, Any]:
    step = next((draft.get("step") for draft in drafts if isinstance(draft, dict) and draft.get("step") is not None), None)
    status = next((draft.get("status") for draft in drafts if isinstance(draft, dict) and draft.get("status") is not None), None)
    payload: Dict[str, Any] = {
        "tone_mode": tone,
        "tone_fallback_used": fallback_used,
        "sections_count": sections_count,
        "step": step,
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    return payload


HEADER_PATTERN = re.compile(r"^[A-Z][A-Z \-/]+:\s*$")


def _split_required_sections(text: str) -> List[Tuple[str, List[str]]]:
    """
    Capture immutable sections: header line + immediate bullet lines.
    """

    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in HEADERS_TO_PRESERVE or HEADER_PATTERN.match(line):
            bullet_lines: List[str] = []
            j = i + 1
            while j < len(lines):
                candidate = lines[j]
                if candidate.startswith("- ") or candidate.startswith("• "):
                    bullet_lines.append(candidate)
                    j += 1
                else:
                    break
            sections.append((line, bullet_lines))
            i = j
        else:
            i += 1
    return sections


def _build_prompt_payload(
    drafts: List[Dict[str, Any]],
    fallback_text: str,
    sections: List[Tuple[str, List[str]]],
    client_email: str | None,
) -> Dict[str, Any]:
    preserve_instructions = "\n".join(
        ["- " + header if bullets else "- " + header for header, bullets in sections]
    )
    facts = {
        "client_email": client_email,
        "draft_messages": drafts,
        "fallback_text": fallback_text,
        "sections": [
            {"header": header, "bullets": bullets} for header, bullets in sections
        ],
    }
    return {
        "system": (
            "You are OpenEvent's professional event manager. Rewrite the provided draft in a direct, "
            "competent tone while preserving all factual content and workflow structure.\n\n"
            "Style Guidelines:\n"
            "- Be concise and confident. No fluff.\n"
            "- Avoid 'AI-isms' (delve, underscore, seamless, tapestry).\n"
            "- Do NOT use over-enthusiastic openers like 'Great news!'.\n\n"
            "Rules:\n"
            "1. Preserve the following headers exactly when they appear:\n"
            f"{preserve_instructions or '- (none)'}\n"
            "2. Do not reorder or alter the bullet lines immediately after each header.\n"
            "3. Keep monetary amounts, times (including 18:00–22:00), and room names exactly as given.\n"
            "4. You may add one professional lead-in sentence before the first header.\n"
            "5. Never invent new information."
        ),
        "user": (
            "Use the facts below to compose the reply.\n"
            "Return only the final message text.\n"
            f"Facts JSON:\n{json.dumps(facts, ensure_ascii=False)}"
        ),
    }


def _call_verbalizer(payload: Dict[str, Any]) -> str:
    deterministic = os.getenv("OPENAI_TEST_MODE") == "1"
    temperature = 0.0 if deterministic else 0.2
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"OpenAI SDK unavailable: {exc}") from exc

    api_key = load_openai_api_key()
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=os.getenv("OPENAI_VERBALIZER_MODEL", "gpt-4o-mini"),
        input=[
            {"role": "system", "content": payload["system"]},
            {"role": "user", "content": payload["user"]},
        ],
        temperature=temperature,
    )
    return getattr(response, "output_text", "").strip()


def _validate_sections(text: str, sections: List[Tuple[str, List[str]]]) -> bool:
    positions: List[int] = []
    for header, bullets in sections:
        header_idx = text.find(header)
        if header_idx == -1:
            return False
        positions.append(header_idx)
        last_idx = header_idx
        for bullet in bullets:
            bullet_idx = text.find(bullet, last_idx)
            if bullet_idx == -1:
                return False
            if bullet_idx < last_idx:
                return False
            last_idx = bullet_idx
    if positions != sorted(positions):
        return False
    return True


# ==============================================================================
# Safety Sandwich: Room/Offer Verbalizer
# ==============================================================================


def verbalize_room_offer(
    facts: "RoomOfferFacts",
    fallback_text: str,
    *,
    locale: str = "en",
) -> str:
    """
    Verbalize a room/offer message using the Safety Sandwich pattern.

    1. Build LLM request with facts bundle
    2. Get candidate LLM text
    3. Verify with deterministic verifier
    4. Return LLM text if OK, else fallback

    Args:
        facts: RoomOfferFacts bundle containing all deterministic facts
        fallback_text: Deterministic template to use if verification fails
        locale: Language locale (en or de)

    Returns:
        Verbalized text (LLM or fallback)
    """
    from backend.ux.verbalizer_payloads import RoomOfferFacts
    from backend.ux.verbalizer_safety import verify_output, log_verification_failure

    tone = _resolve_tone()
    if tone == "plain":
        logger.debug("verbalize_room_offer: plain tone, using fallback")
        return fallback_text

    # Check if LLM is available
    api_key = load_openai_api_key(required=False)
    if not api_key:
        logger.debug("verbalize_room_offer: no API key, using fallback")
        return fallback_text

    try:
        prompt_payload = _build_room_offer_prompt(facts, locale)
        llm_text = _call_verbalizer(prompt_payload)
    except Exception as exc:
        logger.warning(
            "verbalize_room_offer: LLM call failed, using fallback",
            extra={"error": str(exc)},
        )
        return fallback_text

    if not llm_text or not llm_text.strip():
        logger.warning("verbalize_room_offer: empty LLM response, using fallback")
        return fallback_text

    # Verify the LLM output
    result = verify_output(facts, llm_text)

    if result.ok:
        logger.debug("verbalize_room_offer: verification passed, using LLM text")
        return llm_text

    # Verification failed - log and use fallback
    log_verification_failure(facts, llm_text, result)
    return fallback_text


def _build_room_offer_prompt(
    facts: "RoomOfferFacts",
    locale: str,
) -> Dict[str, Any]:
    """Build the LLM prompt for room/offer verbalization."""
    from backend.ux.verbalizer_payloads import RoomOfferFacts

    locale_instruction = ""
    if locale == "de":
        locale_instruction = "Write the response in German (Deutsch). "
    else:
        locale_instruction = "Write the response in English. "

    # Get currency code from venue config
    currency = get_currency_code()

    system_content = f"""You are OpenEvent's professional event manager for a premium venue.

{locale_instruction}Your task is to present room options and offer details to a client in a concise, competent, and direct tone.

STYLE GUIDELINES:
- **Tone:** Professional and confident. Avoid marketing-heavy language or over-enthusiasm.
- **Brevity:** Keep the response brief. No unnecessary adjectives.
- **Negative Constraints:** DO NOT use "delve", "underscore", "seamless", "tapestry", "elevate", "Great news!".

STRICT RULES:
1. You MUST include ALL dates exactly as provided (format: DD.MM.YYYY)
2. You MUST include ALL room names exactly as provided
3. You MUST include ALL prices exactly as provided (format: {currency} XX or {currency} XX.XX)
4. You MUST include the participant count if provided
5. You MUST NOT invent any new dates, prices, room names, or numeric values
6. You MUST NOT change any numbers, dates, or prices
7. You MAY:
   - Add a brief, professional greeting
   - Explain differences between rooms briefly
8. ROOM ORDERING: If a "recommended_room" is specified in the facts, you MUST present that room FIRST as the primary recommendation. The client explicitly requested this room.

Keep the response concise (under 120 words)."""

    facts_json = json.dumps(facts.to_dict(), ensure_ascii=False, indent=2)

    user_content = f"""Please compose a client-facing message based on these facts:

{facts_json}

Return only the message text, starting with a greeting."""

    return {
        "system": system_content,
        "user": user_content,
    }


# Type hint import for runtime
try:
    from backend.ux.verbalizer_payloads import RoomOfferFacts  # noqa: F401
except ImportError:
    pass
