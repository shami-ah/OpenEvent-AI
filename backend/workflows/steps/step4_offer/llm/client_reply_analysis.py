from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import LLMNode

__all__ = ["AnalyzeClientReply"]


_CONFIRM_KEYWORDS: Tuple[str, ...] = (
    "confirm",
    "accepted",
    "accept",
    "book",
    "go ahead",
    "lock it in",
    "we are in",
    "good to proceed",
    "ready to proceed",
)

_RESERVE_KEYWORDS: Tuple[str, ...] = (
    "reserve",
    "hold",
    "pencil",
    "tentative",
    "keep the date",
    "block the date",
)

_VISIT_KEYWORDS: Tuple[str, ...] = (
    "visit",
    "tour",
    "viewing",
    "view the",
    "view ",
    "come by",
    "stop by",
    "walk through",
    "walkthrough",
    "see the space",
    "see the venue",
    "site visit",
)

_CHANGE_KEYWORDS: Tuple[str, ...] = (
    "change",
    "update",
    "modify",
    "adjust",
    "different",
    "switch",
    "move",
    "reschedule",
    "increase",
    "decrease",
    "reduce",
    "add more",
    "change the",
    "instead of",
)

_DECLINE_KEYWORDS: Tuple[str, ...] = (
    "cancel",
    "cancelling",
    "not interested",
    "no longer interested",
    "won't move forward",
    "will not move forward",
    "going with another",
    "decline",
    "pass on",
    "drop out",
    "not proceed",
    "do not proceed",
)


class AnalyzeClientReply(LLMNode):
    """Interpret the client's follow-up message after the offer is delivered."""

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_text = (payload.get("client_msg_text") or "").strip()
        visit_allowed = bool(payload.get("visit_allowed", False))

        classification = self._classify_message(message_text, visit_allowed)
        return {
            "response_type": classification["response_type"],
            "post_offer_classification": classification,
        }

    # --------------------------------------------------------------------- #
    # Classification helpers
    # --------------------------------------------------------------------- #

    def _classify_message(self, message_text: str, visit_allowed: bool) -> Dict[str, Any]:
        lowered = message_text.lower()

        mentions_deposit, wants_to_pay_now = self._detect_deposit_intent(lowered)
        reserve_dates = self._extract_reserve_dates(message_text)
        visit_datetimes = self._extract_visit_datetimes(message_text)
        time_snippets = self._extract_times(message_text)

        response_type, match_note = self._determine_response_type(lowered, reserve_dates, visit_datetimes)
        confidence = self._estimate_confidence(response_type, match_note, bool(message_text.strip()))

        change_patch = {}
        if response_type == "change_request":
            change_patch = self._build_change_patch(message_text)
        proposed_visits: List[str] = []
        if response_type == "site_visit":
            proposed_visits = list(visit_datetimes)
            if not proposed_visits and time_snippets:
                proposed_visits = time_snippets[:5]

        extracted_fields: Dict[str, Any] = {
            "proposed_visit_datetimes": proposed_visits,
            "mentions_deposit": mentions_deposit,
            "wants_to_pay_deposit_now": wants_to_pay_now,
            "requested_reserve_dates": reserve_dates if response_type == "reserve_date" else [],
            "change_request_patch": change_patch if response_type == "change_request" else {},
            "user_question_text": message_text if response_type == "general_question" else None,
        }

        explanation = self._build_explanation(
            response_type=response_type,
            match_note=match_note,
            mentions_deposit=mentions_deposit,
            wants_to_pay_now=wants_to_pay_now,
            visit_allowed=visit_allowed,
            has_dates=bool(reserve_dates or visit_datetimes),
        )

        classification = {
            "response_type": response_type,
            "classification_confidence": confidence,
            "classification_explanation": explanation,
            "extracted_fields": extracted_fields,
        }
        return classification

    def _determine_response_type(
        self,
        lowered: str,
        reserve_dates: Sequence[str],
        visit_datetimes: Sequence[str],
    ) -> Tuple[str, Optional[str]]:
        def _keyword_hit(keywords: Tuple[str, ...]) -> Optional[str]:
            for keyword in keywords:
                if keyword in lowered:
                    return keyword
            return None

        decline_hit = _keyword_hit(_DECLINE_KEYWORDS)
        if decline_hit:
            return "not_interested", decline_hit

        change_hit = _keyword_hit(_CHANGE_KEYWORDS)
        if change_hit:
            return "change_request", change_hit

        visit_hit = _keyword_hit(_VISIT_KEYWORDS)
        if visit_hit or visit_datetimes:
            return "site_visit", visit_hit or (visit_datetimes[0] if visit_datetimes else None)

        reserve_hit = _keyword_hit(_RESERVE_KEYWORDS)
        if reserve_hit or reserve_dates:
            return "reserve_date", reserve_hit or (reserve_dates[0] if reserve_dates else None)

        confirm_hit = _keyword_hit(_CONFIRM_KEYWORDS)
        if confirm_hit or ("deposit" in lowered and ("pay" in lowered or "paid" in lowered)):
            return "confirm_booking", confirm_hit or "deposit"

        if "?" in lowered or lowered.startswith(("can", "could", "would", "do you")):
            return "general_question", "question_mark"

        if lowered.strip():
            return "general_question", None

        return "general_question", "empty"

    @staticmethod
    def _estimate_confidence(response_type: str, match_note: Optional[str], has_text: bool) -> float:
        if not has_text:
            return 0.2
        base = 0.55
        if match_note in {"question_mark", "empty", None}:
            return base
        strong_types = {"confirm_booking", "site_visit", "change_request", "not_interested"}
        if response_type in strong_types:
            return 0.85
        if response_type == "reserve_date":
            return 0.75
        return base

    @staticmethod
    def _detect_deposit_intent(lowered: str) -> Tuple[bool, bool]:
        mentions = bool(
            re.search(
                r"\b(deposit|down payment|advance payment|retainer)\b",
                lowered,
            )
        )
        wants_now = bool(
            re.search(
                r"(paid|have paid|already paid|will pay|ready to pay|transfer|transferred|wire|sent).{0,20}\bdeposit\b",
                lowered,
            )
        ) or "deposit is paid" in lowered or "deposit paid" in lowered
        return mentions, wants_now

    @staticmethod
    def _extract_reserve_dates(text: str) -> List[str]:
        dates: List[str] = []
        seen: set[str] = set()

        iso_pattern = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
        for year, month, day in iso_pattern.findall(text):
            iso = AnalyzeClientReply._safe_date(int(year), int(month), int(day))
            if iso and iso not in seen:
                seen.add(iso)
                dates.append(iso)

        euro_pattern = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
        for day, month, year in euro_pattern.findall(text):
            year_int = int(year) if len(year) == 4 else 2000 + int(year)
            iso = AnalyzeClientReply._safe_date(year_int, int(month), int(day))
            if iso and iso not in seen:
                seen.add(iso)
                dates.append(iso)

        return dates[:5]

    @staticmethod
    def _extract_visit_datetimes(text: str) -> List[str]:
        datetimes: List[str] = []
        seen: set[str] = set()

        iso_dt_pattern = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})\b")
        for year, month, day, hour, minute in iso_dt_pattern.findall(text):
            iso_dt = AnalyzeClientReply._safe_datetime(
                int(year), int(month), int(day), int(hour), int(minute)
            )
            if iso_dt and iso_dt not in seen:
                seen.add(iso_dt)
                datetimes.append(iso_dt)

        euro_dt_pattern = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})[ ,T]*(\d{1,2}):(\d{2})\b")
        for day, month, year, hour, minute in euro_dt_pattern.findall(text):
            year_int = int(year) if len(year) == 4 else 2000 + int(year)
            iso_dt = AnalyzeClientReply._safe_datetime(
                year_int, int(month), int(day), int(hour), int(minute)
            )
            if iso_dt and iso_dt not in seen:
                seen.add(iso_dt)
                datetimes.append(iso_dt)

        return datetimes[:5]

    @staticmethod
    def _build_change_patch(message_text: str) -> Dict[str, Any]:
        lowered = message_text.lower()
        dates = AnalyzeClientReply._extract_reserve_dates(message_text)
        times = AnalyzeClientReply._extract_times(message_text)
        guest_count = AnalyzeClientReply._extract_guest_count(lowered)
        room_label = AnalyzeClientReply._extract_room_label(message_text)
        catering_notes = message_text if "catering" in lowered or "menu" in lowered else None

        patch: Dict[str, Any] = {}
        if dates:
            patch["new_event_date"] = dates[0]
        if times:
            patch["new_start_time"] = times[0]
            if len(times) > 1:
                patch["new_end_time"] = times[1]
        if room_label:
            patch["new_room_label"] = room_label
        if guest_count is not None:
            patch["new_guest_count"] = guest_count
        if catering_notes:
            patch["new_catering_notes"] = catering_notes

        patch["additional_change_notes"] = message_text
        return patch

    @staticmethod
    def _extract_times(text: str) -> List[str]:
        pattern = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
        times: List[str] = []
        seen: set[str] = set()
        for hour, minute in pattern.findall(text):
            normalized = f"{int(hour):02d}:{int(minute):02d}"
            if normalized not in seen:
                seen.add(normalized)
                times.append(normalized)
        return times[:4]

    @staticmethod
    def _extract_guest_count(lowered: str) -> Optional[int]:
        pattern = re.compile(r"\b(\d{1,4})\s+(guests|people|attendees|persons|participants)\b")
        match = pattern.search(lowered)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_room_label(text: str) -> Optional[str]:
        match = re.search(r"room\s+([A-Za-z0-9 ]{1,40})", text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().rstrip(".,")

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> Optional[str]:
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _safe_datetime(year: int, month: int, day: int, hour: int, minute: int) -> Optional[str]:
        try:
            return datetime(year, month, day, hour, minute).isoformat(timespec="minutes")
        except ValueError:
            return None

    def _build_explanation(
        self,
        response_type: str,
        match_note: Optional[str],
        mentions_deposit: bool,
        wants_to_pay_now: bool,
        visit_allowed: bool,
        has_dates: bool,
    ) -> str:
        if response_type == "confirm_booking":
            bits = ["Client confirms the booking"]
            if match_note:
                bits.append(f"via phrase '{match_note}'")
            if wants_to_pay_now:
                bits.append("and states the deposit is paid/being paid")
            elif mentions_deposit:
                bits.append("and references the deposit")
            return ", ".join(bits)

        if response_type == "site_visit":
            bits = ["Client requests a site visit"]
            if match_note:
                bits.append(f"mentioning '{match_note}'")
            if has_dates:
                bits.append("and proposes specific times")
            if not visit_allowed:
                bits.append("even though visit_allowed is false")
            return ", ".join(bits)

        if response_type == "change_request":
            reason = match_note or "explicit change wording"
            return f"Client asks to adjust details ({reason})"

        if response_type == "reserve_date":
            bits = ["Client asks to reserve the date"]
            if match_note:
                bits.append(f"with '{match_note}'")
            if has_dates:
                bits.append("and supplies dates")
            return ", ".join(bits)

        if response_type == "not_interested":
            return "Client indicates they are no longer moving forward"

        if response_type == "general_question":
            if match_note == "question_mark":
                return "Client asks a question without giving a decision"
            if match_note == "empty":
                return "No content provided; defaulting to general question"
            return "Client message does not fit booking/visit/reservation patterns"

        return "Client follow-up categorized as general question"
