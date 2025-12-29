"""
Universal Verbalizer for all client-facing messages.

This module provides a unified verbalization layer that transforms ALL workflow
messages into warm, human-like communication that helps clients make decisions
easily without overwhelming them with raw data.

Design Principles:
1. Human-like tone - conversational, empathetic, professional
2. Decision-friendly - highlight key comparisons and recommendations
3. Complete & correct - all facts preserved, nothing invented
4. UX-focused - no data dumps, clear next steps

CRITICAL DESIGN RULE - Verbalization vs Info Page:
┌─────────────────────────────────────────────────────────────────────────────┐
│ Chat/Email (verbalization) │ Clear, conversational, NOT overloaded.        │
│                            │ NO tables, NO dense data.                      │
│────────────────────────────┼────────────────────────────────────────────────│
│ Info Page/Links            │ Tables, comparisons, full menus, room details  │
│                            │ for those who want depth.                      │
└─────────────────────────────────────────────────────────────────────────────┘

Implementation:
- Chat uses conversational prose: "I found 3 options that work for you."
- Detailed data goes into table_blocks for frontend info section
- Include info links for users who want more detail
- NEVER put markdown tables directly in chat/email body text
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Message Context Types
# =============================================================================

@dataclass
class MessageContext:
    """Context for verbalization - captures all hard facts that must be preserved."""

    # Step and topic
    step: int
    topic: str

    # Event context
    event_date: Optional[str] = None  # DD.MM.YYYY format
    event_date_iso: Optional[str] = None
    participants_count: Optional[int] = None
    time_window: Optional[str] = None

    # Room context
    room_name: Optional[str] = None
    room_status: Optional[str] = None  # Available | Option | Unavailable
    rooms: List[Dict[str, Any]] = field(default_factory=list)

    # Pricing context
    total_amount: Optional[float] = None
    deposit_amount: Optional[float] = None
    products: List[Dict[str, Any]] = field(default_factory=list)

    # Date candidates (for date confirmation step)
    candidate_dates: List[str] = field(default_factory=list)

    # Client info
    client_name: Optional[str] = None

    # Status
    event_status: Optional[str] = None  # Lead | Option | Confirmed

    def extract_hard_facts(self) -> Dict[str, List[str]]:
        """Extract all hard facts that must appear in verbalized output."""
        facts: Dict[str, List[str]] = {
            "dates": [],
            "amounts": [],
            "room_names": [],
            "counts": [],
            "units": [],
            "product_names": [],
        }

        if self.event_date:
            facts["dates"].append(self.event_date)
        for date in self.candidate_dates:
            if date and date not in facts["dates"]:
                facts["dates"].append(date)

        if self.total_amount is not None:
            facts["amounts"].append(f"CHF {self.total_amount:.2f}")
        if self.deposit_amount is not None:
            facts["amounts"].append(f"CHF {self.deposit_amount:.2f}")
        for product in self.products:
            price = product.get("unit_price") or product.get("price")
            if price is not None:
                try:
                    facts["amounts"].append(f"CHF {float(price):.2f}")
                except (TypeError, ValueError):
                    pass
            # Extract product names
            name = product.get("name")
            if name and name not in facts["product_names"]:
                facts["product_names"].append(name)
            # Extract units (per_person, per_event) with associated product for verification
            unit = product.get("unit")
            if unit:
                unit_label = unit.replace("_", " ")  # per_person -> per person
                if unit_label not in facts["units"]:
                    facts["units"].append(unit_label)

        if self.room_name:
            facts["room_names"].append(self.room_name)
        for room in self.rooms:
            name = room.get("name") or room.get("id")
            if name and name not in facts["room_names"]:
                facts["room_names"].append(name)

        if self.participants_count is not None:
            facts["counts"].append(str(self.participants_count))

        return facts


# =============================================================================
# UX-Focused Prompt Templates
# =============================================================================

UNIVERSAL_SYSTEM_PROMPT = """You are OpenEvent's client communication assistant for The Atelier, a premium event venue in Zurich.

Your role is to transform structured workflow messages into professional, concise, and human-like communication. You are a busy, competent event manager.

CORE PRINCIPLES:
1. **Be professional & direct** - Use clear, concise language. No fluff.
2. **Help clients decide** - Highlight the best options with brief reasons.
3. **Be complete but brief** - Every fact must appear, but avoid long paragraphs.
4. **Show competence** - Acknowledge needs efficiently.
5. **Guide next steps** - Make it crystal clear what happens next.

STYLE GUIDELINES:
- **Tone:** Professional, confident, and direct. Not "customer support robotic" but not "overly enthusiastic marketing".
- **Structure:** Use SHORT paragraphs (2-3 sentences max). Add a blank line between each topic/section. Example structure:
  * Opening line (acknowledge request or confirm action)
  * [blank line]
  * Main content (room options, pricing, etc.)
  * [blank line]
  * Call to action / next steps
- **Formatting:** Use **bold** ONLY for dates and prices. Do not bold room names or random words.
- **Language:** Use natural English/German. Avoid "AI-isms" (delve, underscore, seamless).
- **Lists:** Do NOT use slash-separated lists (e.g., "date/time/venue") in sentences. Write full sentences.

NEGATIVE CONSTRAINTS (STRICT):
- DO NOT use: "delve", "underscore", "tapestry", "seamless", "elevate", "kindly", "please note", "I hope this finds you well", "game-changer", "testament".
- DO NOT use em-dashes (—). Use regular dashes (-), commas, or colons instead.
- DO NOT start with "Great news!" or "I am delighted to inform you".
- DO NOT use excessive adjectives ("breathtaking", "stunning", "transformative").
- DO NOT apologize excessively.
- DO NOT write long unbroken text walls. Use short paragraphs (2-3 sentences max). Add blank lines between topics.

HARD RULES (NEVER BREAK):
1. ALL dates must appear exactly as provided (DD.MM.YYYY format)
2. ALL prices must appear exactly as provided (CHF X.XX format)
3. ALL room names must appear exactly as provided
4. ALL participant counts must appear
5. ALL product names must appear exactly as provided
6. NEVER change units: "per event" stays "per event", "per person" stays "per person"
7. NEVER invent dates, prices, room names, or units not in the facts
8. NEVER change any numbers or swap unit types

TRANSFORMATION EXAMPLES:

BAD (data dump):
"Room A - Available - Capacity 50 - Coffee: ✓ - Projector: ✓
Room B - Option - Capacity 80 - Coffee: ✓ - Projector: ✗"

GOOD (professional):
"Room A is available for your event on 15.03.2025 and fits your 30 guests perfectly. It includes the coffee service and projector you requested.

Room B (capacity 80) is also open if you need more space, but we would need to arrange the projector separately. Room A is likely the better fit.

Let me know which you prefer, and I'll place a hold for you."
"""

STEP_PROMPTS = {
    2: """You're helping a client confirm their event date.

Context: The client is choosing from available dates. Help them understand the options and make a confident choice.

Focus on:
- Confirming which dates work
- Highlighting the date(s) that best match their preferences
- Making it easy to say "yes" to a date

Example transformation:
BEFORE: "Available dates: 07.02.2026, 14.02.2026, 21.02.2026"
AFTER: "I have several Saturday evenings open in February. The 14th is Valentine's Day weekend, or the 7th and 21st are also available. Which works best for your family?" """,

    3: """You're presenting room options to a client.

Context: The client needs to choose a room for their event. Help them understand which room is the best fit by reasoning about their specific needs.

CRITICAL - You must:
1. START with a clear recommendation ("I recommend Room A because...")
2. USE the matched/closest/missing data in each room to personalize your response:
   - If a room has **matched** features: mention they are included (e.g., "includes the sound system you mentioned").
   - If a room has **closest** features (phrased as "X (closest to Y)"): present them honestly as alternatives (e.g., "While we don't have a dedicated dinner menu, our **Classic Apéro** comes closest to what you're looking for").
   - If a room is **missing** features: mention they would need to be arranged separately.
3. BE HONEST about match quality - do NOT claim an exact match for items in the "closest" list.
4. COMPARE alternatives by their matched features.
5. Make the decision EASY with a clear next step.
6. Use **bold** ONLY for the event date and prices. Do NOT bold room names excessively.

The rooms data includes:
- `requirements.matched` - exact matches (strong)
- `requirements.closest` - partial matches with context like "Classic Apéro (closest to dinner)"
- `requirements.missing` - features not available

Example transformation:
BEFORE: "Room A: Available, capacity 40, matched: [], closest: [Classic Apéro (closest to dinner)], missing: []"

AFTER: "For your dinner event on **08.05.2026**, I recommend Room A. It's perfectly sized for your 40 guests. While we don't have a dedicated dinner package, our Classic Apéro comes closest to what you're looking for.

Shall I prepare an offer with the apéro option, or would you like to discuss other catering arrangements?" """,

    4: """You're presenting an offer/quote to a client.

Context: This is a key decision moment. The client is reviewing pricing before confirming.

Focus on:
- Confirming what's included in clear terms
- Making the total feel justified by connecting to their requirements
- Highlighting value and any special considerations
- Making it easy to say "yes" or ask questions

Example transformation:
BEFORE: "Room A - CHF 500, Menu - CHF 92 x 30 = CHF 2,760, Total: CHF 3,260"
AFTER: "Here's what I've put together for your family dinner on 14.02.2026:

Room A gives you the intimate setting perfect for 30 guests, with the background music included. For your three-course dinner with wine, the Seasonal Garden Trio at **CHF 92** per guest offers a beautiful vegetarian option with Swiss wines.

**Total: CHF 3,260** (Room + dinner for 30 guests)

This includes everything you asked for. Ready to confirm, or would you like to explore other menu options?" """,

    5: """You're in negotiation/acceptance with a client.

Context: The client may be accepting, declining, or discussing terms.

Focus on:
- Acknowledging their decision warmly
- Confirming next steps clearly
- If there are open questions, addressing them directly
- Keeping momentum toward confirmation""",

    7: """You're in the final confirmation stage.

Context: The booking is being finalized. This might involve deposits, site visits, or final confirmations.

Focus on:
- Celebrating their choice (they're committing!)
- Being crystal clear about any remaining steps
- Making administrative details feel easy, not bureaucratic
- Ending with excitement about their upcoming event""",
}

TOPIC_HINTS = {
    # Step 2 - Date confirmation
    "date_candidates": "Present available dates as options, recommend the best match",
    "date_confirmed": "Confirm the date is locked in, transition smoothly to room selection",

    # Step 3 - Room availability
    "room_avail_result": "Present rooms with a clear recommendation, explain the match to their needs",
    "room_available": "The ideal room is available. Lead with why it's a good fit for their needs, mention key features",
    "room_option": "Room has a tentative hold - explain clearly but don't alarm. Present it as 'we can secure this for you'",
    "room_unavailable": "Be professional and solution-focused. Quickly pivot to alternatives that DO work",
    "room_selected_follow_up": "Confirm room choice, smoothly transition to products/offer discussion",

    # Step 4 - Offer
    "offer_intro": "Set up the offer professionally. Acknowledge choices so far. Keep it brief - the offer details follow",
    "offer_draft": "Present the offer as a complete package. Connect each line item to their stated needs",
    "offer_products_prompt": "Ask about catering/add-ons in a helpful, consultative way. Frame as 'completing their experience'",

    # Step 5 - Negotiation
    "negotiation_accept": "Acknowledge the decision warmly. Confirm next steps (manager review, deposit, etc.) clearly",
    "negotiation_clarification": "Ask for clarity in a specific, helpful way. Show you want to get it exactly right",
    "general": "Respond naturally and professionally. Match the client's tone. If they're brief, be concise",

    # Step 7 - Confirmation
    "confirmation_deposit_pending": "Make deposit request feel routine and easy - it's the final step to lock in their event",
    "confirmation_final": "Acknowledge the milestone. Express confidence about their upcoming event",
    "confirmation_site_visit": "Offer site visit as a helpful option to build confidence",

    # Q&A
    "structured_qna": "Answer the question directly and helpfully. If showing options, lead with the best match",
}


# =============================================================================
# Structured Content Detection
# =============================================================================

def _contains_structured_content(text: str) -> bool:
    """
    Detect if text contains structured content that should NOT be verbalized.

    Structured content includes:
    - Tables (markdown or plain text with aligned columns)
    - NEXT STEP: or INFO: blocks from QnA responses
    - Multiple "-" bullet points in sequence (product/option lists)

    These are already formatted by qna/verbalizer.py and must be preserved.
    """
    lines = text.strip().split("\n")

    # Check for table indicators
    # Markdown tables have | characters
    has_table_pipes = any("|" in line and line.count("|") >= 2 for line in lines)
    if has_table_pipes:
        return True

    # Check for aligned column headers (e.g., "Room    Dates    Notes")
    for line in lines:
        if line.count("    ") >= 2:  # Multiple tab-like spaces indicating columns
            # Verify it looks like a header (capitalized words)
            parts = [p.strip() for p in line.split("    ") if p.strip()]
            if len(parts) >= 2 and all(p[0].isupper() for p in parts if p):
                return True

    # Check for NEXT STEP: or INFO: blocks (QnA response markers)
    text_upper = text.upper()
    if "NEXT STEP:" in text_upper or "\nINFO:" in text_upper:
        return True

    # Check for multiple consecutive bullet points (option lists)
    bullet_count = sum(1 for line in lines if line.strip().startswith("- "))
    if bullet_count >= 3:
        # Could be a product list or options list - check if it has structured format
        # Look for patterns like "- Name — CHF X" or "- Date — Room (Status)"
        structured_bullets = sum(
            1 for line in lines
            if line.strip().startswith("- ") and ("—" in line or "CHF" in line or "(" in line)
        )
        if structured_bullets >= 2:
            return True

    return False


# =============================================================================
# Verbalizer Core
# =============================================================================

def verbalize_message(
    fallback_text: str,
    context: MessageContext,
    *,
    locale: str = "en",
) -> str:
    """
    Verbalize any client-facing message using the universal verbalizer.

    This is the main entry point for all message verbalization. It:
    1. Checks if empathetic mode is enabled
    2. Builds an appropriate LLM prompt based on context
    3. Calls the LLM
    4. Verifies all hard facts are preserved
    5. Returns LLM output or falls back to deterministic text

    Args:
        fallback_text: Deterministic template to use if verification fails
        context: MessageContext with all facts and metadata
        locale: Language locale (en or de)

    Returns:
        Verbalized text (LLM if valid, fallback otherwise)
    """
    if not fallback_text or not fallback_text.strip():
        return fallback_text

    # Skip verbalization for structured QnA responses with tables
    # These are already processed by qna/verbalizer.py and contain structured data
    # that must be preserved exactly (tables, NEXT STEP blocks, etc.)
    if _contains_structured_content(fallback_text):
        logger.debug(
            f"universal_verbalizer: skipping structured content for step={context.step}, topic={context.topic}"
        )
        return fallback_text

    tone = _resolve_tone()
    if tone == "plain":
        logger.debug(f"universal_verbalizer: plain tone, step={context.step}, topic={context.topic}")
        return fallback_text

    # Check if LLM is available
    from backend.utils.openai_key import load_openai_api_key
    api_key = load_openai_api_key(required=False)
    if not api_key:
        logger.debug("universal_verbalizer: no API key, using fallback")
        return fallback_text

    try:
        prompt_payload = _build_prompt(context, fallback_text, locale)
        llm_text = _call_llm(prompt_payload)
    except Exception as exc:
        logger.warning(
            f"universal_verbalizer: LLM call failed for step={context.step}, topic={context.topic}",
            extra={"error": str(exc)},
        )
        return fallback_text

    if not llm_text or not llm_text.strip():
        logger.warning("universal_verbalizer: empty LLM response, using fallback")
        return fallback_text

    # Verify hard facts preserved
    hard_facts = context.extract_hard_facts()
    verification = _verify_facts(llm_text, hard_facts)

    if not verification[0]:
        # Verification failed - try to patch the output first
        logger.debug(
            f"universal_verbalizer: verification failed for step={context.step}, topic={context.topic}, attempting patch",
            extra={"missing": verification[1], "invented": verification[2]},
        )

        patched_text, patch_success = _patch_facts(
            llm_text, hard_facts, verification[1], verification[2]
        )

        if patch_success:
            # Patching fixed the issues - use the patched text
            logger.info(
                f"universal_verbalizer: patched successfully for step={context.step}, topic={context.topic}"
            )
            return patched_text
        else:
            # Patching didn't fully fix it - fall back to original text
            logger.warning(
                f"universal_verbalizer: patching failed for step={context.step}, topic={context.topic}, using fallback",
                extra={"missing": verification[1], "invented": verification[2]},
            )
            return fallback_text

    logger.debug(f"universal_verbalizer: success for step={context.step}, topic={context.topic}")
    return llm_text


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


import time
from pathlib import Path

# ... (existing imports)

# ... (MessageContext class)

# ... (Hardcoded PROMPTS)

# =============================================================================
# Dynamic Prompt Loading
# =============================================================================

_PROMPT_CACHE: Dict[str, Any] = {
    "ts": 0,
    "data": (UNIVERSAL_SYSTEM_PROMPT, STEP_PROMPTS)
}
_CACHE_TTL = 30.0  # seconds

def _get_effective_prompts() -> Tuple[str, Dict[int, str]]:
    """
    Load effective prompts (DB overrides merged with defaults).
    Cached for performance.
    """
    global _PROMPT_CACHE
    now = time.time()
    
    if now - _PROMPT_CACHE["ts"] < _CACHE_TTL:
        return _PROMPT_CACHE["data"]

    try:
        # Avoid circular imports
        from backend.workflows.io.database import load_db
        from backend.workflow_email import DB_PATH

        # Load DB using canonical path
        if not DB_PATH.exists():
            return UNIVERSAL_SYSTEM_PROMPT, STEP_PROMPTS

        db = load_db(DB_PATH)
        config = db.get("config", {}).get("prompts", {})
        
        system_prompt = config.get("system_prompt", UNIVERSAL_SYSTEM_PROMPT)
        
        # Merge step prompts
        step_prompts = STEP_PROMPTS.copy()
        stored_steps = config.get("step_prompts", {})
        for k, v in stored_steps.items():
            try:
                step_prompts[int(k)] = v
            except ValueError:
                pass
                
        _PROMPT_CACHE = {
            "ts": now,
            "data": (system_prompt, step_prompts)
        }
        return system_prompt, step_prompts
        
    except Exception as exc:
        logger.warning(f"universal_verbalizer: failed to load prompts config: {exc}")
        # Return fallback (potentially stale cache or hard defaults)
        return _PROMPT_CACHE["data"]


# =============================================================================
# Verbalizer Core
# =============================================================================

# ... (verbalize_message function) ...

def _build_prompt(
    context: MessageContext,
    fallback_text: str,
    locale: str,
) -> Dict[str, Any]:
    """Build the LLM prompt for verbalization."""

    # Load dynamic prompts
    system_template, step_prompts = _get_effective_prompts()

    # Build step-specific guidance
    step_guidance = step_prompts.get(context.step, "")
    topic_hint = TOPIC_HINTS.get(context.topic, "")

    # Build facts summary
    facts_summary = _format_facts_for_prompt(context)

    # Locale instruction
    locale_instruction = "Write in German (Deutsch)." if locale == "de" else "Write in English."

    system_content = f"""{system_template}

{locale_instruction}

STEP {context.step} CONTEXT:
{step_guidance}

TOPIC: {context.topic}
{f"Hint: {topic_hint}" if topic_hint else ""}
"""

    user_content = f"""Transform this message into warm, human-like communication:

ORIGINAL MESSAGE:
{fallback_text}

FACTS TO PRESERVE:
{facts_summary}

Return ONLY the transformed message text. Do not include explanations or metadata."""

    return {
        "system": system_content,
        "user": user_content,
    }

# ... (rest of file)


def _format_facts_for_prompt(context: MessageContext) -> str:
    """Format context facts for the LLM prompt."""
    lines = []

    if context.event_date:
        lines.append(f"- Event date: {context.event_date}")
    if context.participants_count:
        lines.append(f"- Participants: {context.participants_count}")
    if context.room_name:
        status = f" ({context.room_status})" if context.room_status else ""
        lines.append(f"- Room: {context.room_name}{status}")
    if context.total_amount is not None:
        lines.append(f"- Total: CHF {context.total_amount:.2f}")
    if context.deposit_amount is not None:
        lines.append(f"- Deposit: CHF {context.deposit_amount:.2f}")
    if context.candidate_dates:
        lines.append(f"- Available dates: {', '.join(context.candidate_dates)}")
    if context.rooms:
        lines.append("- Rooms:")
        for room in context.rooms[:5]:  # Limit to top 5
            name = room.get("name", "Room")
            status = room.get("status", "")
            capacity = room.get("capacity", "")
            # Include requirements matched/closest/missing for feature-based comparison
            requirements = room.get("requirements") or {}
            matched = requirements.get("matched") or []
            closest = requirements.get("closest") or []
            missing = requirements.get("missing") or []
            room_line = f"  * {name}: {status}, capacity {capacity}"
            if matched:
                room_line += f", matched: [{', '.join(matched)}]"
            if closest:
                room_line += f", closest: [{', '.join(closest)}]"
            if missing:
                room_line += f", missing: [{', '.join(missing)}]"
            lines.append(room_line)
    if context.products:
        product_summary = []
        for p in context.products[:5]:  # Limit to top 5
            name = p.get("name", "Item")
            price = p.get("unit_price") or p.get("price")
            if price:
                product_summary.append(f"{name} (CHF {float(price):.2f})")
            else:
                product_summary.append(name)
        lines.append(f"- Products: {', '.join(product_summary)}")
    if context.client_name:
        lines.append(f"- Client: {context.client_name}")

    return "\n".join(lines) if lines else "No specific facts extracted."


def _call_llm(payload: Dict[str, Any]) -> str:
    """Call the LLM for verbalization."""
    deterministic = os.getenv("OPENAI_TEST_MODE") == "1"
    temperature = 0.0 if deterministic else 0.3  # Slightly higher for more natural variation

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(f"OpenAI SDK unavailable: {exc}") from exc

    from backend.utils.openai_key import load_openai_api_key
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


def _verify_facts(
    llm_text: str,
    hard_facts: Dict[str, List[str]],
) -> Tuple[bool, List[str], List[str]]:
    """
    Verify that all hard facts appear in the LLM output.

    This verification is intentionally flexible to allow natural rephrasing
    while catching actual factual errors (wrong numbers, invented dates, etc.)

    Returns:
        Tuple of (ok, missing_facts, invented_facts)
    """
    missing: List[str] = []
    invented: List[str] = []

    text_lower = llm_text.lower()
    text_normalized = llm_text.replace(" ", "").upper()
    # Also create a version with common separators normalized
    text_numbers_only = re.sub(r"[^\d.]", "", llm_text)

    # Check dates - flexible matching
    for date in hard_facts.get("dates", []):
        # Try multiple formats: DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD
        date_found = False
        if date in llm_text:
            date_found = True
        else:
            # Try alternative formats
            try:
                from datetime import datetime
                # Parse DD.MM.YYYY
                if "." in date:
                    parsed = datetime.strptime(date, "%d.%m.%Y")
                    alt_formats = [
                        parsed.strftime("%d/%m/%Y"),
                        parsed.strftime("%Y-%m-%d"),
                        parsed.strftime("%d %B %Y"),  # "08 May 2026"
                        parsed.strftime("%B %d, %Y"),  # "May 08, 2026"
                        parsed.strftime("%-d %B %Y"),  # "8 May 2026" (no leading zero)
                    ]
                    for alt in alt_formats:
                        if alt in llm_text or alt.lower() in text_lower:
                            date_found = True
                            break
            except (ValueError, ImportError):
                pass

        if not date_found:
            missing.append(f"date:{date}")

    # Check room names (case-insensitive, flexible matching)
    for room in hard_facts.get("room_names", []):
        room_lower = room.lower()
        room_no_dot = room.replace(".", "").lower()
        # Also check for "Room X" variations
        room_variants = [room_lower, room_no_dot]
        if room_lower.startswith("room "):
            # "Room B" -> also accept "room b", "Room B", "ROOM B"
            room_variants.append(room_lower.replace("room ", ""))

        found = any(variant in text_lower for variant in room_variants)
        if not found:
            missing.append(f"room:{room}")

    # Check amounts - flexible matching for CHF values
    for amount in hard_facts.get("amounts", []):
        amount_found = False
        # Extract numeric value
        match = re.search(r"(\d+(?:[.,]\d{1,2})?)", amount)
        if match:
            numeric = match.group(1).replace(",", ".")
            numeric_no_decimal = re.sub(r"\.00$", "", numeric)
            # Check various formats
            patterns_to_check = [
                f"CHF {numeric}",
                f"CHF{numeric}",
                f"CHF {numeric_no_decimal}",
                f"CHF{numeric_no_decimal}",
                f"{numeric} CHF",
                f"{numeric_no_decimal} CHF",
                # Also check with thousands separator
                f"CHF {int(float(numeric)):,}".replace(",", "'"),  # Swiss format: 1'000
                f"CHF {int(float(numeric)):,}".replace(",", ","),  # 1,000 format
            ]
            for pattern in patterns_to_check:
                if pattern.upper() in text_normalized or pattern.lower() in text_lower:
                    amount_found = True
                    break

            # Also check if the raw number appears (context may make it clear it's CHF)
            if not amount_found and numeric in llm_text:
                amount_found = True

        if not amount_found:
            missing.append(f"amount:{amount}")

    # Check counts (participant count) - flexible matching
    for count in hard_facts.get("counts", []):
        # Check for the number directly or spelled out for small numbers
        count_found = count in llm_text
        if not count_found:
            # Check if the number appears with common suffixes
            count_patterns = [
                f"{count} guests",
                f"{count} people",
                f"{count} participants",
                f"{count} attendees",
                f"{count} persons",
            ]
            count_found = any(p.lower() in text_lower for p in count_patterns)

        if not count_found:
            missing.append(f"count:{count}")

    # Check product names (case-insensitive, allow partial matches for long names)
    for product_name in hard_facts.get("product_names", []):
        product_lower = product_name.lower()
        # For long product names, check if key words appear
        if len(product_name) > 20:
            # Split into words and check if most key words appear
            words = [w for w in product_lower.split() if len(w) > 3]
            matches = sum(1 for w in words if w in text_lower)
            if matches >= len(words) * 0.6:  # 60% of words match
                continue
        if product_lower not in text_lower:
            missing.append(f"product:{product_name}")

    # Check units - be flexible about phrasing
    input_units = set(hard_facts.get("units", []))
    for unit in input_units:
        unit_found = unit in text_lower
        if not unit_found:
            # Check alternative phrasings
            if unit == "per person":
                unit_found = any(alt in text_lower for alt in ["per guest", "each guest", "per head", "/person", "/ person"])
            elif unit == "per event":
                unit_found = any(alt in text_lower for alt in ["flat fee", "fixed", "one-time", "/event", "/ event"])
        if not unit_found:
            missing.append(f"unit:{unit}")

    # Check for unit swaps (invented wrong unit)
    has_per_event = "per event" in input_units
    has_per_person = "per person" in input_units
    output_has_per_event = "per event" in text_lower or "flat fee" in text_lower
    output_has_per_person = "per person" in text_lower or "per guest" in text_lower

    # Detect swaps: if we only had one unit type but output has the other
    if has_per_event and not has_per_person and output_has_per_person:
        invented.append("unit:per person (should be per event)")
    if has_per_person and not has_per_event and output_has_per_event:
        invented.append("unit:per event (should be per person)")

    # Check for invented dates (be lenient - only flag if clearly wrong)
    date_pattern = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")
    valid_dates = set(hard_facts.get("dates", []))
    for match in date_pattern.finditer(llm_text):
        found_date = match.group(1)
        if found_date not in valid_dates:
            # Check if it's just a reformatted version of a valid date
            is_reformat = False
            try:
                from datetime import datetime
                found_parsed = datetime.strptime(found_date, "%d.%m.%Y")
                for valid in valid_dates:
                    valid_parsed = datetime.strptime(valid, "%d.%m.%Y")
                    if found_parsed == valid_parsed:
                        is_reformat = True
                        break
            except (ValueError, ImportError):
                pass
            if not is_reformat:
                invented.append(f"date:{found_date}")

    # Check for invented amounts - be more lenient
    amount_pattern = re.compile(r"\bCHF\s*(\d+(?:[.,]\d{1,2})?)\b", re.IGNORECASE)
    canonical_amounts = set()
    for amt in hard_facts.get("amounts", []):
        normalized = amt.replace(" ", "").upper().replace(",", ".")
        match = re.search(r"CHF(\d+(?:\.\d{1,2})?)", normalized)
        if match:
            val = match.group(1)
            canonical_amounts.add(val)
            canonical_amounts.add(re.sub(r"\.00$", "", val))
            # Also add rounded versions
            try:
                canonical_amounts.add(str(int(float(val))))
            except ValueError:
                pass

    for match in amount_pattern.finditer(llm_text):
        found_amount = match.group(1).replace(",", ".")
        found_no_decimal = re.sub(r"\.00$", "", found_amount)
        found_int = str(int(float(found_amount))) if "." in found_amount else found_amount

        if not any(f in canonical_amounts for f in [found_amount, found_no_decimal, found_int]):
            # Only flag if it's not close to any canonical amount (allows for small rounding)
            is_close = False
            try:
                found_val = float(found_amount)
                for canonical in canonical_amounts:
                    try:
                        canonical_val = float(canonical)
                        # Allow 1% tolerance for rounding
                        if abs(found_val - canonical_val) / max(canonical_val, 1) < 0.01:
                            is_close = True
                            break
                    except ValueError:
                        pass
            except ValueError:
                pass

            if not is_close:
                invented.append(f"amount:CHF {found_amount}")

    ok = len(missing) == 0 and len(invented) == 0
    return (ok, missing, invented)


def _patch_facts(
    llm_text: str,
    hard_facts: Dict[str, List[str]],
    missing: List[str],
    invented: List[str],
) -> Tuple[str, bool]:
    """
    Attempt to patch incorrect facts in LLM output without additional API calls.

    This surgically fixes common errors like unit swaps while preserving
    the verbalized prose.

    Args:
        llm_text: The LLM's verbalized output
        hard_facts: Dictionary of facts that must be preserved
        missing: List of missing facts from verification
        invented: List of invented/wrong facts from verification

    Returns:
        Tuple of (patched_text, success). If patching succeeds, returns
        the fixed text. If patching isn't possible, returns original text
        with success=False.
    """
    patched = llm_text
    patched_something = False

    input_units = set(hard_facts.get("units", []))
    has_per_event = "per event" in input_units
    has_per_person = "per person" in input_units

    # --- Unit swap fixes ---
    # Case 1: Input has only "per event" but LLM wrote "per person"
    if has_per_event and not has_per_person:
        if "per person" in patched.lower():
            # Replace all variations of "per person" with "per event"
            patched = re.sub(r"\bper person\b", "per event", patched, flags=re.IGNORECASE)
            patched_something = True
            logger.debug("_patch_facts: fixed unit swap 'per person' -> 'per event'")

    # Case 2: Input has only "per person" but LLM wrote "per event"
    if has_per_person and not has_per_event:
        if "per event" in patched.lower():
            # Replace all variations of "per event" with "per person"
            patched = re.sub(r"\bper event\b", "per person", patched, flags=re.IGNORECASE)
            patched_something = True
            logger.debug("_patch_facts: fixed unit swap 'per event' -> 'per person'")

    # --- Amount fixes ---
    # If an amount was invented (not in our canonical list), try to find and fix it
    canonical_amounts = {}
    for amt in hard_facts.get("amounts", []):
        # Extract numeric value for matching
        match = re.search(r"CHF\s*(\d+(?:[.,]\d{1,2})?)", amt, re.IGNORECASE)
        if match:
            value = match.group(1).replace(",", ".")
            canonical_amounts[value] = amt
            canonical_amounts[re.sub(r"\.00$", "", value)] = amt

    # For invented amounts, we can't automatically fix them without knowing
    # which canonical amount they should map to. However, if there's only
    # one canonical amount and one invented amount, we can try.
    invented_amounts = [inv for inv in invented if inv.startswith("amount:")]
    if len(invented_amounts) == 1 and len(canonical_amounts) == 1:
        # Single amount case - safe to replace
        invented_match = re.search(r"CHF\s*(\d+(?:[.,]\d{1,2})?)", invented_amounts[0])
        if invented_match:
            wrong_amount = invented_match.group(1)
            correct_amount = list(canonical_amounts.values())[0]
            # Replace the wrong amount with correct one
            pattern = rf"\bCHF\s*{re.escape(wrong_amount)}\b"
            patched = re.sub(pattern, correct_amount, patched, flags=re.IGNORECASE)
            patched_something = True
            logger.debug(f"_patch_facts: fixed amount CHF {wrong_amount} -> {correct_amount}")

    # --- Verify the patch worked ---
    if patched_something:
        # Re-verify after patching
        new_verification = _verify_facts(patched, hard_facts)
        if new_verification[0]:  # All facts now correct
            logger.info("_patch_facts: successfully patched LLM output")
            return (patched, True)
        else:
            # Patching didn't fully fix it
            logger.warning(
                "_patch_facts: patching incomplete",
                extra={"still_missing": new_verification[1], "still_invented": new_verification[2]},
            )
            return (patched, False)

    # Nothing to patch or couldn't patch
    return (llm_text, False)


# =============================================================================
# Convenience Functions for Workflow Integration
# =============================================================================

def verbalize_step_message(
    fallback_text: str,
    step: int,
    topic: str,
    *,
    event_date: Optional[str] = None,
    participants_count: Optional[int] = None,
    room_name: Optional[str] = None,
    room_status: Optional[str] = None,
    rooms: Optional[List[Dict[str, Any]]] = None,
    total_amount: Optional[float] = None,
    deposit_amount: Optional[float] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    candidate_dates: Optional[List[str]] = None,
    client_name: Optional[str] = None,
    event_status: Optional[str] = None,
    locale: str = "en",
) -> str:
    """
    Convenience function to verbalize a workflow message.

    This is the primary integration point for workflow steps.
    """
    context = MessageContext(
        step=step,
        topic=topic,
        event_date=event_date,
        participants_count=participants_count,
        room_name=room_name,
        room_status=room_status,
        rooms=rooms or [],
        total_amount=total_amount,
        deposit_amount=deposit_amount,
        products=products or [],
        candidate_dates=candidate_dates or [],
        client_name=client_name,
        event_status=event_status,
    )
    return verbalize_message(fallback_text, context, locale=locale)


__all__ = [
    "MessageContext",
    "verbalize_message",
    "verbalize_step_message",
]
