"""Adapters that expose agent capabilities for the workflow.

Tests can call `reset_agent_adapter()` to clear the shared singleton between runs.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.domain import IntentLabel
from backend.utils.openai_key import load_openai_api_key

try:  # pragma: no cover - optional dependency resolved at runtime
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - library may be unavailable in tests
    OpenAI = None  # type: ignore

try:  # pragma: no cover - optional dependency resolved at runtime
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - library may be unavailable in tests
    genai = None  # type: ignore


class AgentAdapter:
    """Base adapter defining the agent interface for intent routing and entity extraction."""

    def analyze_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a combined payload containing intent, confidence, and extracted fields."""

        raise NotImplementedError("analyze_message must be implemented by subclasses.")

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        """Classify an inbound email into intent labels understood by the workflow."""

        analysis = self.analyze_message(msg)
        intent = analysis.get("intent") if isinstance(analysis, dict) else None
        confidence = analysis.get("confidence") if isinstance(analysis, dict) else None
        if intent is None:
            raise NotImplementedError("route_intent must be implemented by subclasses.")
        try:
            conf = float(confidence) if confidence is not None else 0.0
        except (TypeError, ValueError):
            conf = 0.0
        return str(intent), conf

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalized entities for the event workflow."""

        analysis = self.analyze_message(msg)
        if isinstance(analysis, dict):
            fields = analysis.get("fields")
            if isinstance(fields, dict):
                return fields
        raise NotImplementedError("extract_entities must be implemented by subclasses.")

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = True,
    ) -> str:
        """Run a raw completion with a custom prompt.

        This is the generic entrypoint for unified detection and other
        custom LLM operations that don't fit the intent/entity pattern.

        Args:
            prompt: The prompt to send to the LLM
            system_prompt: Optional system prompt
            temperature: Sampling temperature (default 0.1 for consistency)
            max_tokens: Max tokens in response
            json_mode: Whether to request JSON output

        Returns:
            Raw text response from the LLM
        """
        raise NotImplementedError("complete must be implemented by subclasses.")


class StubAgentAdapter(AgentAdapter):
    """Deterministic heuristic stub replicating the pre-agent workflow behaviour."""

    KEYWORDS = {
        "event",
        "booking",
        "request",
        "date",
        "guests",
        "people",
        "catering",
        "venue",
        "offer",
        "quotation",
        "availability",
        "participants",
        "room",
        "schedule",
    }

    MONTHS = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    def analyze_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        intent, confidence = self._classify_intent(msg)
        fields = self._extract_entities(msg)
        return {"intent": intent, "confidence": confidence, "fields": fields}

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        return self._classify_intent(msg)

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        return self._extract_entities(msg)

    def _classify_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        subject = (msg.get("subject") or "").lower()
        body = (msg.get("body") or "").lower()
        score = 0.0
        for kw in self.KEYWORDS:
            if kw in subject:
                score += 1.5
            if kw in body:
                score += 1.0
        if "?" in (msg.get("subject") or ""):
            score += 0.1
        if score >= 2.0:
            conf = min(1.0, 0.4 + 0.15 * score)
            return IntentLabel.EVENT_REQUEST.value, conf
        conf = min(1.0, 0.2 + 0.1 * score)
        return IntentLabel.NON_EVENT.value, conf

    def _extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        body = msg.get("body") or ""
        lower_body = body.lower()
        entities: Dict[str, Any] = {
            "date": self._extract_date(body),
            "start_time": None,
            "end_time": None,
            "city": None,
            "participants": None,
            "room": None,
            "type": None,
            "catering": None,
            "phone": None,
            "company": None,
            "language": None,
            "notes": None,
        }

        times = self._extract_times(body)
        if times:
            entities["start_time"] = times[0]
            if len(times) > 1:
                entities["end_time"] = times[1]

        # Participants: support multiple formats and languages
        participants_patterns = [
            # English: "60 people/guests/participants/attendees/persons"
            r"(?:~|approx(?:\.|imately)?|about|around|ca\.?)?\s*(\d{1,4})\s*(?:\+)?\s*(?:ppl|people|guests|participants|attendees|persons|visitors)\b",
            # Hospitality industry: "30 pax" / "50 covers" / "30 heads"
            r"(?:~|approx(?:\.|imately)?|about|around|ca\.?)?\s*(\d{1,4})\s*(?:pax|covers|heads)\b",
            # English: "party/group of 60"
            r"(?:party|group|team)\s+of\s+(\d{1,4})",
            # English: "Attendees: 60" / "Expected: 60" / "Attendance: 60"
            r"(?:attendees|expected|attendance|capacity|headcount)[:\s]+(\d{1,4})\b",
            # German: "60 Personen/Gäste/Teilnehmer/Leute"
            r"(?:~|ca\.?|etwa|ungefähr|rund)?\s*(\d{1,4})\s*(?:personen|gäste|teilnehmer|leute|besucher)\b",
            # French: "60 personnes/invités/participants/convives"
            r"(?:~|environ|à peu près)?\s*(\d{1,4})\s*(?:personnes|invités|convives)\b",
            # Italian: "60 persone/ospiti/partecipanti"
            r"(?:~|circa|approssimativamente)?\s*(\d{1,4})\s*(?:persone|ospiti|partecipanti|invitati)\b",
            # Spanish: "60 personas/invitados/asistentes"
            r"(?:~|aproximadamente|alrededor de)?\s*(\d{1,4})\s*(?:personas|invitados|asistentes|huéspedes)\b",
        ]
        for pattern in participants_patterns:
            participants_match = re.search(pattern, lower_body, re.IGNORECASE)
            if participants_match:
                entities["participants"] = int(participants_match.group(1))
                break

        room_match = re.search(r"\b(room\s*[a-z0-9]+|punkt\.?null)\b", body, re.IGNORECASE)
        if room_match:
            entities["room"] = room_match.group(0).strip()

        # Event types that affect room/catering preferences
        # Prioritize food/catering types (affect product matching) over generic event types
        event_types = [
            # Food/catering types first - these drive product matching
            "dinner", "lunch", "breakfast", "brunch", "banquet", "gala",
            "cocktail", "apéro", "apero", "aperitif", "reception",
            # Event format types
            "workshop", "training", "seminar", "conference", "meeting",
            "presentation", "lecture", "talk",
            # Celebration types (often have catering implications)
            "wedding", "birthday", "celebration", "party",
        ]
        for evt_type in event_types:
            if evt_type in lower_body:
                entities["type"] = evt_type
                break

        catering_match = re.search(r"catering(?:\s*(?:preference|option|request)?)?:\s*([^\n\r]+)", body, re.IGNORECASE)
        if catering_match:
            entities["catering"] = catering_match.group(1)
        else:
            inline_match = re.search(r"catering\s+(?:is|to|with|for)\s+([^\n\r.]+)", body, re.IGNORECASE)
            if inline_match:
                entities["catering"] = inline_match.group(1)

        phone_match = re.search(r"\+?\d[\d\s\-]{6,}\d", body)
        if phone_match:
            entities["phone"] = phone_match.group(0)

        company_match = re.search(r"company[:\-\s]+([^\n\r,]+)", body, re.IGNORECASE)
        if not company_match:
            company_match = re.search(r"\bfrom\s+([A-Z][A-Za-z0-9 &]+)", body)
        if company_match:
            entities["company"] = company_match.group(1)

        language_label = re.search(r"language[:\-\s]+([^\n\r,]+)", body, re.IGNORECASE)
        if language_label:
            entities["language"] = language_label.group(1)
        language_inline = re.search(r"\bin\s+(english|german|french|italian|spanish|en|de|fr|it|es)\b", lower_body)
        if language_inline:
            entities["language"] = language_inline.group(1)

        city_match = re.search(r"\bin\s+([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)\b", body)
        if city_match:
            entities["city"] = city_match.group(1)

        notes_section = re.search(r"(?:notes?|details?)[:\-]\s*([^\n]+)", body, re.IGNORECASE)
        if notes_section:
            entities["notes"] = notes_section.group(1)

        if "shortcut" in lower_body and "capacity" in lower_body:
            entities["shortcut_capacity_ok"] = True

        return entities

    def _extract_times(self, text: str) -> List[str]:
        results: List[str] = []

        # Pattern 1: "6:30 PM" / "9:00 AM" (12h with minutes and AM/PM) - check first!
        for match in re.finditer(r"\b(\d{1,2})[:.](\d{2})\s*(pm|am)\b", text, re.IGNORECASE):
            hours, minutes = int(match.group(1)), int(match.group(2))
            suffix = match.group(3).lower()
            if suffix == "pm" and hours < 12:
                hours += 12
            elif suffix == "am" and hours == 12:
                hours = 0
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                results.append(f"{hours:02d}:{minutes:02d}")

        # Pattern 2: HH:MM or HH.MM with optional Uhr/h suffix (24h format)
        # Skip if followed by AM/PM (already handled above)
        # BUG FIX: Add negative lookahead (?!\.\d{2,4}) to avoid matching dates like "07.02.2026"
        for match in re.finditer(r"\b(\d{1,2})[:.](\d{2})(?!\.\d{2,4})(?:\s*(?:uhr|h))?(?!\s*(?:am|pm))\b", text, re.IGNORECASE):
            hours, minutes = int(match.group(1)), int(match.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                time_str = f"{hours:02d}:{minutes:02d}"
                if time_str not in results:
                    results.append(time_str)

        # Pattern 3: French format "18h30" / "14h45" (hours + h + minutes)
        for match in re.finditer(r"\b(\d{1,2})h(\d{2})\b", text, re.IGNORECASE):
            hours, minutes = int(match.group(1)), int(match.group(2))
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                time_str = f"{hours:02d}:{minutes:02d}"
                if time_str not in results:
                    results.append(time_str)

        # Pattern 4: "6pm" / "6 pm" / "18h" / "18 Uhr" (without minutes)
        # Must have valid hour (not 00)
        for match in re.finditer(r"\b(\d{1,2})\s*(pm|am|h|uhr)\b", text, re.IGNORECASE):
            hours = int(match.group(1))
            if hours == 0:  # Skip "00 Uhr" type false matches
                continue
            suffix = match.group(2).lower()
            if suffix == "pm" and hours < 12:
                hours += 12
            elif suffix == "am" and hours == 12:
                hours = 0
            if 0 <= hours <= 23:
                time_str = f"{hours:02d}:00"
                if time_str not in results:
                    results.append(time_str)

        return results

    def _extract_date(self, text: str) -> Optional[str]:
        # Pattern types: (1) EU numeric, (2) ISO, (3) DD Month YYYY, (4) Month DD, YYYY, (5) Month DD-DD, YYYY (range)
        patterns = [
            (r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", "eu"),           # DD.MM.YYYY
            (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "iso"),            # YYYY-MM-DD
            (r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{4})\b", "dmy"),  # DD Month YYYY
            # Month DD-DD, YYYY (date range) - captures first day
            (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{1,2})[\-–—]\d{1,2},?\s+(\d{4})\b", "mdy"),
            (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b", "mdy"),  # Month DD, YYYY (US format)
        ]
        for pattern, ptype in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                try:
                    if ptype == "eu":
                        day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                    elif ptype == "iso":
                        year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    elif ptype == "dmy":
                        day = int(groups[0])
                        month = self.MONTHS.get(groups[1][:3].lower())
                        year = int(groups[2])
                    elif ptype == "mdy":
                        month = self.MONTHS.get(groups[0][:3].lower())
                        day = int(groups[1])
                        year = int(groups[2])
                    else:
                        continue
                    parsed = date(year, month, day)
                    return parsed.isoformat()
                except (ValueError, TypeError):
                    continue
        return None

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = True,
    ) -> str:
        """Stub implementation returns a minimal JSON response for testing."""
        # For unified detection, return a basic structure
        return json.dumps({
            "language": "en",
            "intent": "general_qna",
            "intent_confidence": 0.5,
            "signals": {
                "is_confirmation": False,
                "is_acceptance": False,
                "is_rejection": False,
                "is_change_request": False,
                "is_manager_request": False,
                "is_question": "?" in prompt,
                "has_urgency": False,
            },
            "entities": {
                "date": None,
                "date_text": None,
                "participants": None,
                "duration_hours": None,
                "room_preference": None,
                "products": [],
                "billing_address": None,
            },
            "qna_types": [],
            "step_anchor": None,
        })


class OpenAIAgentAdapter(AgentAdapter):
    """Adapter backed by OpenAI chat completions for intent/entity tasks."""

    _INTENT_PROMPT = (
        "Classify the email below. Respond with JSON object {\"intent\": <event_request|other>, "
        "\"confidence\": <0-1 float>}."
    )
    _ENTITY_PROMPT_TEMPLATE = (
        "Today is {today}. Extract booking details from the email. "
        "Return JSON with keys: date (YYYY-MM-DD or null), "
        "start_time, end_time, city, participants, room, name, email, type, catering, phone, company, "
        "language, notes, billing_address, products_add (array of {{name, quantity}} for items to add), "
        "products_remove (array of product names to remove). Use null when unknown. "
        "IMPORTANT: When a year is explicitly mentioned (e.g., '2026'), use that exact year. "
        "For vague dates like 'late spring' or 'next month', return null for date. "
        "For 'add another X' or 'one more X', include {{\"name\": \"X\", \"quantity\": 1}} in products_add."
    )

    _ENTITY_KEYS = [
        "date",
        "start_time",
        "end_time",
        "city",
        "participants",
        "room",
        "name",
        "email",
        "type",
        "catering",
        "phone",
        "company",
        "language",
        "notes",
        "billing_address",
        "products_add",
        "products_remove",
    ]

    def __init__(self) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package is required when AGENT_MODE=openai")
        api_key = load_openai_api_key()
        self._client = OpenAI(api_key=api_key)
        # TODO: Consider changing default from o3-mini to gpt-4o-mini
        # o3-mini is a reasoning model that sometimes returns malformed JSON
        # gpt-4o-mini is 7x cheaper and more reliable for JSON extraction
        # Need to verify gpt-4o-mini reliability before switching default
        model = os.getenv("OPENAI_AGENT_MODEL", "o3-mini")
        self._intent_model = os.getenv("OPENAI_INTENT_MODEL", model)
        self._entity_model = os.getenv("OPENAI_ENTITY_MODEL", model)
        self._fallback = StubAgentAdapter()

    def _run_completion(self, *, prompt: str, body: str, subject: str, model: str) -> Dict[str, Any]:
        message = f"Subject: {subject}\n\nBody:\n{body}"
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content if response.choices else "{}"
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError:
            return {}

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            payload = self._run_completion(
                prompt=self._INTENT_PROMPT,
                body=body,
                subject=subject,
                model=self._intent_model,
            )
            intent = str(payload.get("intent") or "").strip().lower()
            if intent not in {IntentLabel.EVENT_REQUEST.value, IntentLabel.NON_EVENT.value}:
                intent = IntentLabel.NON_EVENT.value
            confidence_raw = payload.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            return intent or IntentLabel.NON_EVENT.value, confidence
        except Exception:
            return self._fallback.route_intent(msg)

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            # Build prompt with today's date for accurate year extraction
            today_str = date.today().strftime("%Y-%m-%d")
            prompt = self._ENTITY_PROMPT_TEMPLATE.format(today=today_str)
            payload = self._run_completion(
                prompt=prompt,
                body=body,
                subject=subject,
                model=self._entity_model,
            )
            entities: Dict[str, Any] = {}
            for key in self._ENTITY_KEYS:
                entities[key] = payload.get(key)
            return entities
        except Exception:
            return self._fallback.extract_entities(msg)

    def extract_user_information(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        return self.extract_entities(msg)

    def analyze_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Combine intent classification and entity extraction into a single response."""
        intent, confidence = self.route_intent(msg)
        fields = self.extract_entities(msg)
        return {"intent": intent, "confidence": confidence, "fields": fields}

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = True,
    ) -> str:
        """Run a raw completion with OpenAI."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            kwargs: Dict[str, Any] = {
                "model": self._intent_model,
                "messages": messages,
            }
            # o-series models don't support temperature and use max_completion_tokens
            if self._intent_model.startswith("o"):
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["temperature"] = temperature
                kwargs["max_tokens"] = max_tokens
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or "{}"
        except Exception as e:
            print(f"[OpenAIAgentAdapter] complete error: {e}")
            return self._fallback.complete(prompt, system_prompt=system_prompt, json_mode=json_mode)


class GeminiAgentAdapter(AgentAdapter):
    """Adapter backed by Google Gemini for intent/entity tasks.

    Uses Gemini Flash 2.0 by default for fast, cost-effective classification.
    Falls back to StubAgentAdapter on API errors for resilience.
    """

    _INTENT_PROMPT = (
        "Classify the email below as either an event booking request or something else. "
        "Respond with ONLY a JSON object: {\"intent\": \"event_request\" or \"other\", "
        "\"confidence\": 0.0 to 1.0}. No other text."
    )

    _ENTITY_PROMPT_TEMPLATE = (
        "Today is {today}. Extract booking details from this email. "
        "Return ONLY a JSON object with these keys (use null when unknown): "
        "date (YYYY-MM-DD), start_time, end_time, city, participants (integer), "
        "room, name, email, type, catering, phone, company, language, notes, "
        "billing_address, products_add (array of {{name, quantity}}), "
        "products_remove (array of product names). "
        "IMPORTANT: Use the exact year mentioned (e.g., '2026'). "
        "For vague dates like 'late spring', return null for date."
    )

    _ENTITY_KEYS = [
        "date", "start_time", "end_time", "city", "participants", "room",
        "name", "email", "type", "catering", "phone", "company", "language",
        "notes", "billing_address", "products_add", "products_remove",
    ]

    def __init__(self) -> None:
        if genai is None:
            raise RuntimeError("google-generativeai package is required when AGENT_MODE=gemini")

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY environment variable is required for Gemini")

        genai.configure(api_key=api_key)

        # Model selection - Flash 2.0 for speed/cost, Pro 2.0 for quality
        self._intent_model = os.getenv("GEMINI_INTENT_MODEL", "gemini-2.0-flash")
        self._entity_model = os.getenv("GEMINI_ENTITY_MODEL", "gemini-2.0-flash")
        self._fallback = StubAgentAdapter()

    def _run_completion(self, *, prompt: str, body: str, subject: str, model_name: str) -> Dict[str, Any]:
        """Run a Gemini completion and parse JSON response."""
        message = f"Subject: {subject}\n\nBody:\n{body}"

        model = genai.GenerativeModel(
            model_name,
            generation_config=genai.GenerationConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )

        response = model.generate_content([
            {"role": "user", "parts": [f"{prompt}\n\n{message}"]},
        ])

        content = response.text if response else "{}"
        try:
            return json.loads(content or "{}")
        except json.JSONDecodeError:
            return {}

    def _select_fallback_strategy(self, error: Exception, operation: str) -> str:
        """Determine fallback behavior when Gemini fails.

        This method controls what happens when the Gemini API call fails.
        Returns: "stub" to use heuristics, "raise" to propagate error.

        TODO: User to implement - see CONTRIBUTING note below.
        """
        # Default: always fall back to stub for resilience
        return "stub"

    def route_intent(self, msg: Dict[str, Any]) -> Tuple[str, float]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            payload = self._run_completion(
                prompt=self._INTENT_PROMPT,
                body=body,
                subject=subject,
                model_name=self._intent_model,
            )
            intent = str(payload.get("intent") or "").strip().lower()
            if intent not in {IntentLabel.EVENT_REQUEST.value, IntentLabel.NON_EVENT.value}:
                intent = IntentLabel.NON_EVENT.value
            confidence_raw = payload.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            return intent or IntentLabel.NON_EVENT.value, confidence
        except Exception as e:
            strategy = self._select_fallback_strategy(e, "intent")
            if strategy == "stub":
                return self._fallback.route_intent(msg)
            raise

    def extract_entities(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        subject = msg.get("subject") or ""
        body = msg.get("body") or ""
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            prompt = self._ENTITY_PROMPT_TEMPLATE.format(today=today_str)
            payload = self._run_completion(
                prompt=prompt,
                body=body,
                subject=subject,
                model_name=self._entity_model,
            )
            entities: Dict[str, Any] = {}
            for key in self._ENTITY_KEYS:
                entities[key] = payload.get(key)
            return entities
        except Exception as e:
            strategy = self._select_fallback_strategy(e, "entity")
            if strategy == "stub":
                return self._fallback.extract_entities(msg)
            raise

    def analyze_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Combine intent classification and entity extraction into a single response."""
        intent, confidence = self.route_intent(msg)
        fields = self.extract_entities(msg)
        return {"intent": intent, "confidence": confidence, "fields": fields}

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = True,
    ) -> str:
        """Run a raw completion with Gemini."""
        try:
            # Prepend system prompt if provided
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            generation_config = genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            if json_mode:
                generation_config.response_mime_type = "application/json"

            model = genai.GenerativeModel(
                self._intent_model,
                generation_config=generation_config,
            )

            response = model.generate_content([
                {"role": "user", "parts": [full_prompt]},
            ])

            return response.text if response else "{}"
        except Exception as e:
            strategy = self._select_fallback_strategy(e, "complete")
            if strategy == "stub":
                return self._fallback.complete(prompt, system_prompt=system_prompt, json_mode=json_mode)
            raise


_AGENT_SINGLETON: Optional[AgentAdapter] = None

# Per-provider singletons for hybrid mode
_PROVIDER_ADAPTERS: Dict[str, AgentAdapter] = {}


def get_adapter_for_provider(provider: str) -> AgentAdapter:
    """
    Get an adapter for a specific provider (hybrid mode support).

    This allows using different providers for different tasks:
    - Gemini for intent/entity extraction (cheaper)
    - OpenAI for verbalization (better quality)

    Args:
        provider: One of "openai", "gemini", "stub"

    Returns:
        AgentAdapter for the specified provider
    """
    provider = provider.lower()

    if provider in _PROVIDER_ADAPTERS:
        return _PROVIDER_ADAPTERS[provider]

    if provider == "stub":
        _PROVIDER_ADAPTERS[provider] = StubAgentAdapter()
    elif provider == "openai":
        _PROVIDER_ADAPTERS[provider] = OpenAIAgentAdapter()
    elif provider == "gemini":
        _PROVIDER_ADAPTERS[provider] = GeminiAgentAdapter()
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")

    return _PROVIDER_ADAPTERS[provider]


def get_agent_adapter() -> AgentAdapter:
    """Factory selecting the adapter implementation based on AGENT_MODE."""

    global _AGENT_SINGLETON
    if _AGENT_SINGLETON is not None:
        return _AGENT_SINGLETON

    mode = os.environ.get("AGENT_MODE", "stub").lower()
    if mode == "stub":
        _AGENT_SINGLETON = StubAgentAdapter()
        return _AGENT_SINGLETON
    if mode == "openai":
        _AGENT_SINGLETON = OpenAIAgentAdapter()
        return _AGENT_SINGLETON
    if mode == "gemini":
        _AGENT_SINGLETON = GeminiAgentAdapter()
        return _AGENT_SINGLETON
    raise RuntimeError(f"Unsupported AGENT_MODE: {mode}")


def reset_agent_adapter() -> None:
    """Reset the cached adapter instance (used by tests)."""

    global _AGENT_SINGLETON
    _AGENT_SINGLETON = None
