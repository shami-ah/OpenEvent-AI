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

        for evt_type in ["workshop", "meeting", "conference", "seminar", "wedding", "party", "training"]:
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
        for match in re.finditer(r"\b(\d{1,2})[:.](\d{2})(?:\s*(?:uhr|h))?(?!\s*(?:am|pm))\b", text, re.IGNORECASE):
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


class OpenAIAgentAdapter(AgentAdapter):
    """Adapter backed by OpenAI chat completions for intent/entity tasks."""

    _INTENT_PROMPT = (
        "Classify the email below. Respond with JSON object {\"intent\": <event_request|other>, "
        "\"confidence\": <0-1 float>}."
    )
    _ENTITY_PROMPT = (
        "Extract booking details from the email. Return JSON with keys: date (YYYY-MM-DD or null), "
        "start_time, end_time, city, participants, room, name, email, type, catering, phone, company, "
        "language, notes, billing_address, products_add (array of {name, quantity} for items to add), "
        "products_remove (array of product names to remove). Use null when unknown. "
        "For 'add another X' or 'one more X', include {\"name\": \"X\", \"quantity\": 1} in products_add."
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
            payload = self._run_completion(
                prompt=self._ENTITY_PROMPT,
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


_AGENT_SINGLETON: Optional[AgentAdapter] = None


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
    raise RuntimeError(f"Unsupported AGENT_MODE: {mode}")


def reset_agent_adapter() -> None:
    """Reset the cached adapter instance (used by tests)."""

    global _AGENT_SINGLETON
    _AGENT_SINGLETON = None
