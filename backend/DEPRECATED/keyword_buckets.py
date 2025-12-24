"""
DEPRECATED: This module has been moved to backend/detection/keywords/buckets.py

Please update your imports:
    OLD: from backend.workflows.nlu.keyword_buckets import ...
    NEW: from backend.detection.keywords.buckets import ...

This file will be removed in a future version.

---

Keyword Buckets for Detour/Change Detection (EN/DE)

This module contains all regex patterns for detecting change intent, revision signals,
and target-specific patterns. Patterns are organized by language and function.

Based on UX analysis for comprehensive coverage of venue booking change scenarios.

Usage:
    from backend.detection.keywords.buckets import (
        CHANGE_VERBS_EN, CHANGE_VERBS_DE,
        REVISION_MARKERS_EN, REVISION_MARKERS_DE,
        TARGET_PATTERNS, PURE_QA_SIGNALS,
        has_revision_signal, has_bound_target, compute_change_intent_score
    )
"""

import warnings
warnings.warn(
    "backend.workflows.nlu.keyword_buckets is deprecated. "
    "Use backend.detection.keywords.buckets instead.",
    DeprecationWarning,
    stacklevel=2
)

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


# =============================================================================
# DETOUR MODE (how the change was initiated)
# =============================================================================

class DetourMode(Enum):
    """How the client initiated the change request."""
    LONG = "long"          # Revision signal + no new value provided -> ask for value
    FAST = "fast"          # Revision signal + new value provided -> validate & proceed
    EXPLICIT = "explicit"  # Old value + new value both mentioned -> validate & proceed


# =============================================================================
# MULTI-CLASS INTENT (what the message actually is)
# =============================================================================

class MessageIntent(Enum):
    """Multi-class intent classification result."""
    # Detour types (route to owning step with caller_step set)
    DETOUR_DATE = "detour_date"              # -> Step 2
    DETOUR_ROOM = "detour_room"              # -> Step 3
    DETOUR_REQUIREMENTS = "detour_req"       # -> Step 3
    DETOUR_PRODUCTS = "detour_products"      # -> Step 4

    # Non-detour types (route directly, no LLM re-call needed)
    CONFIRMATION = "confirmation"             # Client confirms/accepts
    GENERAL_QA = "general_qa"                # Pure question, no change
    SPECIAL_HIL_REQUEST = "special_hil"      # Needs manager approval
    NEGOTIATION = "negotiation"              # Price/terms discussion
    DECLINE = "decline"                      # Client declines/cancels
    UNCLEAR = "unclear"                      # Needs clarification


# =============================================================================
# ENGLISH KEYWORD BUCKETS
# =============================================================================

# Change verbs - grouped by confidence level
CHANGE_VERBS_EN = {
    # Very common, direct (high confidence)
    "strong": [
        r"\bchange\b",
        r"\breschedul\w*\b",      # reschedule, rescheduled, rescheduling
        r"\bmove\b",
        r"\bswitch\b",
        r"\bupdate\b",
        r"\bmodify\b",
        r"\badjust\b",
        r"\brevis\w*\b",          # revise, revised, revision
        r"\bupgrad\w*\b",         # upgrade, upgrading
        r"\bdowngrad\w*\b",       # downgrade, downgrading
    ],
    # Rescheduling idioms
    "reschedule": [
        r"\bpostpone\b",
        r"\bpush\s+\w*\s*(back|out)\b",  # "push back", "push it back", "push things back"
        r"\bbring\s+\w*\s*forward\b",     # "bring forward", "bring it forward"
        r"\bmove\s+\w*\s*(forward|up)\b", # "move forward", "move it up"
        r"\brearrange\b",
        r"\bbump\b",
        r"\bshift\b",
    ],
    # Booking-style terms
    "booking": [
        r"\bre-?book\b",
        r"\btransfer\b",
        r"\bmove\s+(the\s+)?reservation\b",
    ],
    # Product modification verbs
    "product_mod": [
        r"\badd\b",               # "add prosecco"
        r"\bremove\b",            # "remove the coffee"
        r"\bdrop\b",              # "drop the wine"
        r"\binclude\b",           # "include vegetarian options"
        r"\bexclude\b",           # "exclude alcohol"
    ],
}

# Revision markers - indicate "we're changing our mind"
REVISION_MARKERS_EN = [
    r"\bagain\b",                           # "change the date again"
    r"\binstead\b",                         # "instead of Friday"
    r"\brather(\s+than)?\b",               # "rather do it on the 14th"
    r"\bafter\s+all\b",                    # "we'll do Friday after all"
    r"\bactually\b",                       # "actually we'd prefer"
    r"\b(any\s*more|anymore)\b",           # "doesn't work anymore"
    r"\bno\s+longer\b",                    # "no longer able to"
    r"\bon\s+second\s+thought(s)?\b",
    r"\bturns?\s+out\b",                   # "turns out we can't"
    r"\bended\s+up\b",                     # "ended up with more people"
    r"\bin\s+the\s+end\b",                 # "in the end we'll need to"
    r"\bsorry\b",                          # apology signal
    r"\bapolog\w*\b",                      # apologize, apologies
    r"\boops\b",
    r"\bmy\s+bad\b",
    r"\bmistake\b",
    r"\berror\b",
    r"\bwrong\b",
    r"\bincorrect\b",
    r"\bmeant\s+to\b",                     # "I meant to say"
    r"\bdidn'?t\s+mean\b",                 # "didn't mean that"
    r"\bnot\s+what\s+i\b",                 # "not what I wanted"
    r"\bdouble-?booked\b",                 # "I'm double-booked"
    r"\bconflict\b",                       # "have a conflict"
    r"\bsomething'?s?\s+come\s+up\b",      # "something's come up"
    r"\bmixed\s+up\b",                     # "I mixed up my dates"
    # Preference indicators (imply choosing differently)
    r"\bprefer\b",                         # "we prefer", "we'd prefer"
    r"\b(a\s+)?different\b",               # "a different room"
    r"\banother\b",                        # "another date"
    r"\bgone\s+(up|down)\b",               # "numbers have gone up"
    r"\b(more|fewer|less)\s+than\b",       # "more than expected"
]

# Polite request patterns (boosters)
REQUEST_MODIFIERS_EN = [
    r"\b(can|could|would|may)\s+(i|we|you)\b.*\b(change|switch|update|move)\b",
    r"\b(is\s+it\s+possible|would\s+it\s+be\s+possible)\b",
    r"\bi'?d\s+like\s+to\b.*\b(change|update|switch|move)\b",
    r"\bi\s+want\s+to\b.*\b(change|update|switch|move)\b",
    r"\bi\s+need\s+to\b.*\b(change|update|switch|move)\b",
    r"\bplease\b.*\b(change|update|switch|use)\b",
    r"\bif\s+it'?s?\s+not\s+too\s+late\b",
]

# Pure Q&A signals - negative filter (if these match WITHOUT change verbs, it's Q&A)
PURE_QA_SIGNALS_EN = [
    r"^(what|which|where|when|how|do\s+you\s+have|is\s+there|are\s+there)\b",
    r"\bwhat\s+(rooms?|dates?|options?)\s+(are|is)\s+(free|available)\b",
    r"\bdo\s+you\s+(have|offer)\b",
    r"\bwhat'?s?\s+(the\s+)?(price|cost|rate)\b",
    r"\bhow\s+much\b",
    r"\bwhat\s+(do|does|can)\b",
    r"\bcan\s+you\s+tell\s+me\b",
    r"\bi\s+(was\s+)?wondering\b",
]

# Confirmation signals
CONFIRMATION_SIGNALS_EN = [
    r"^(yes|ok|okay|sure|perfect|great|sounds?\s+good)\b",
    r"\blet'?s?\s+(do\s+it|proceed|go\s+ahead)\b",
    r"\bplease\s+proceed\b",
    r"\bthat\s+works?\b",
    r"\bconfirm(ed)?\b",
    r"\bagree(d)?\b",
    r"\baccept(ed)?\b",
    r"\bbook\s+it\b",
    r"\bgo\s+ahead\b",
]

# Decline signals
DECLINE_SIGNALS_EN = [
    r"\bcancel\b",
    r"\bno\s+longer\s+interested\b",
    r"\bwon'?t\s+be\s+(needing|proceeding)\b",
    r"\bdecline\b",
    r"\bpass\s+on\b",
    r"\bnot\s+interested\b",
    r"\bwithdr(aw|ew)\b",
]


# =============================================================================
# GERMAN KEYWORD BUCKETS
# =============================================================================

CHANGE_VERBS_DE = {
    "strong": [
        r"\bändern\b",
        r"\bverschieben\b",
        r"\bverlegen\b",
        r"\bumbuchen\b",
        r"\banpassen\b",
        r"\bwechseln\b",
        r"\btauschen\b",
    ],
    "reschedule": [
        r"\bvorziehen\b",
        r"\bnach\s+hinten\s+schieben\b",
        r"\bzurückverschieben\b",
    ],
}

REVISION_MARKERS_DE = [
    r"\bdoch\b",                           # "doch lieber", "doch nicht"
    r"\bdoch\s+lieber\b",                  # "doch lieber am 14."
    r"\bstattdessen\b",                    # "stattdessen am 14.?"
    r"\blieber\b",                         # "lieber den kleineren Raum"
    r"\bim\s+Endeffekt\b",                 # "im Endeffekt doch im März"
    r"\bam\s+Ende\s+doch\b",
    r"\bklappt\s+(doch\s+)?nicht\s+mehr\b", # "klappt doch nicht mehr"
    r"\bgeht\s+(doch\s+)?nicht\b",         # "geht doch nicht"
    r"\bdazwischengekommen\b",             # "ist was dazwischengekommen"
    r"\bvertan\b",                         # "habe mich im Datum vertan"
    r"\beigentlich\b",                     # "eigentlich meinten wir"
    r"\bdoch\s+eher\b",
    r"\bletztendlich\b",
    r"\bschlussendlich\b",
    r"\bfehler\b",                         # "Fehler gemacht"
    r"\bfalsch\b",                         # "falsch gewählt"
    r"\btut\s+mir\s+leid\b",              # apology
    r"\bentschuldig\w*\b",                 # entschuldigung, entschuldigen
]

REQUEST_MODIFIERS_DE = [
    r"\b(können|könnten|würden|dürfen)\s+(wir|Sie)\b.*\b(ändern|verschieben|wechseln)\b",
    r"\bwäre\s+es\s+möglich\b",
    r"\bich\s+(möchte|würde)\s+gerne\b.*\b(ändern|verschieben|wechseln)\b",
    r"\bbitte\b.*\b(ändern|verschieben|umbuchen)\b",
]

PURE_QA_SIGNALS_DE = [
    r"^(was|welche[rs]?|wo|wann|wie|gibt\s+es|haben\s+Sie)\b",
    r"\bgibt\s+es\s+(einen?\s+)?(freien?\s+)?(termin|raum)\b",
    r"\bhaben\s+Sie\b",
    r"\bwas\s+kostet\b",
    r"\bwie\s+viel\b",
    r"\bkönnen\s+Sie\s+mir\s+sagen\b",
]

CONFIRMATION_SIGNALS_DE = [
    r"^(ja|ok|okay|perfekt|super|passt|einverstanden)\b",
    r"\bklingt\s+gut\b",
    r"\bmachen\s+wir\s+so\b",
    r"\bbestätigt\b",
    r"\beinverstanden\b",
    r"\bakzeptiert\b",
    r"\bbuchen\s+Sie\b",
]

DECLINE_SIGNALS_DE = [
    r"\bstornieren\b",
    r"\babsagen\b",
    r"\bkein\s+interesse\s+mehr\b",
    r"\babbrechen\b",
    r"\bzurückziehen\b",
]


# =============================================================================
# TARGET-SPECIFIC PATTERNS (what are they trying to change?)
# =============================================================================

TARGET_PATTERNS = {
    "date": {
        "en": [
            r"\b(date|day|time|when|schedule)\b",
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
            r"\b\d{1,2}[./\-]\d{1,2}([./\-]\d{2,4})?\b",  # 12.03, 12/03, 12-03-2026
            r"\b\d{4}[./\-]\d{1,2}[./\-]\d{1,2}\b",       # 2026-03-12
            r"\b(that\s+day|this\s+day|the\s+booking|that\s+date)\b",  # anaphoric
            r"\b(earlier|later)\s+(date|day|time)\b",
            r"\b(next|previous|following)\s+(week|month|day)\b",
        ],
        "de": [
            r"\b(termin|datum|tag|uhrzeit|zeit)\b",
            r"\b(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
            r"\b(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
            r"\b(früher|später)\b",
            r"\b(nächste|vorherige)[rns]?\s+(woche|monat|tag)\b",
            r"\b(der|den|am)\s+\d{1,2}\.",  # "der 21.", "den 28.", "am 15." (no word boundary after dot)
            r"\b\d{1,2}\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
        ],
    },
    "room": {
        "en": [
            r"\b(room|space|venue|hall|location)\b",
            r"\broom\s+[a-z]\b",  # Room A, Room B
            r"\b(bigger|smaller|larger|different)\s+(room|space|venue)\b",
            r"\b(that\s+room|this\s+room|the\s+other\s+room|another\s+room)\b",
            r"\b(main|conference|meeting|event)\s+(room|hall|space)\b",
        ],
        "de": [
            r"\b(raum|saal|räumlichkeit|location|zimmer)\b",
            r"\b(größer|kleiner|ander)\w*\s+(raum|saal)\b",
            r"\b(den\s+anderen|einen\s+anderen)\s+(raum|saal)\b",
            r"\b(konferenz|meeting|veranstaltungs)(raum|saal)\b",
        ],
    },
    "requirements": {
        "en": [
            r"\b(people|persons?|guests?|attendees?|participants?|pax)\b",
            r"\b(layout|setup|seating|arrangement)\b",
            r"\b(theatre|u-?shape|classroom|boardroom|banquet|cabaret)\b",
            r"\b(extend|shorten|longer|shorter)\b.*\b(hours?|time|duration)\b",
            r"\b(more|fewer|less)\s+(people|guests|space|time)\b",
            r"\b\d+\s+(people|persons?|guests?|pax|attendees?)\b",
            r"\b(numbers?\s+have|we('re|'ll\s+be))\s+(gone\s+)?(up|down)\b",
            r"\b(breakout|additional|extra)\s+(room|space)\b",
            r"\b(tech|av|audio|video|equipment)\b",
        ],
        "de": [
            r"\b(personen?|gäste?|teilnehmer|leute)\b",
            r"\b(bestuhlung|aufstellung|anordnung)\b",
            r"\b(theater|u-form|klassenzimmer|boardroom)\b",
            r"\b(verlängern|verkürzen|länger|kürzer)\b",
            r"\b(mehr|weniger)\s+(personen?|platz|gäste|zeit)\b",
            r"\b\d+\s+(personen?|gäste?|teilnehmer)\b",
            r"\b(technik|av|audio|video|ausstattung)\b",
        ],
    },
    "products": {
        "en": [
            r"\b(menu|package|catering|food|drinks?|beverages?)\b",
            r"\b(coffee|tea|wine|prosecco|champagne|snacks?|lunch|dinner|breakfast)\b",
            r"\b(appetizer|dessert|apéro|aperitif)\b",
            r"\b(add|remove|drop|include|exclude)\b.*\b(package|menu|catering|option)\b",
            r"\b(vegetarian|vegan|dietary|allerg\w*|gluten)\b",
            r"\b(projector|microphone|flipchart|av|screen|beamer)\b",
            r"\b(cheaper|premium|upgrade|downgrade)\s+(package|menu|option)\b",
        ],
        "de": [
            r"\b(menü|paket|catering|essen|getränke?)\b",
            r"\b(kaffee|tee|wein|prosecco|champagner|snacks?|mittagessen|abendessen|frühstück)\b",
            r"\b(vorspeise|dessert|apéro|aperitif)\b",
            r"\b(vegetarisch|vegan|diät\w*|allerg\w*|gluten)\b",
            r"\b(beamer|mikrofon|flipchart|leinwand)\b",
            r"\b(günstiger|premium|upgrade|downgrade)\b",
        ],
    },
}

# Anaphoric references to current booking (bound target without explicit value)
ANAPHORIC_REFERENCES = {
    "en": [
        r"\b(the|that|this)\s+(date|day|time|booking|reservation|event)\b",
        r"\b(the|that|this)\s+(room|space|venue|location)\b",
        r"\b(the|that|this)\s+(menu|package|catering|option)\b",
        r"\b(our|the)\s+(current|confirmed|selected|chosen)\b",
        r"\b(what\s+we\s+(agreed|chose|picked|selected))\b",
    ],
    "de": [
        r"\b(der|die|das|den)\s+(termin|tag|datum|buchung|reservierung)\b",
        r"\b(der|die|das|den)\s+(raum|saal|location)\b",
        r"\b(das|die)\s+(menü|paket|catering)\b",
        r"\b(unser[en]?|der|die|das)\s+(aktuelle[rns]?|bestätigte[rns]?|gewählte[rns]?)\b",
    ],
}


# =============================================================================
# DETECTION RESULT
# =============================================================================

@dataclass
class ChangeIntentResult:
    """Result of change intent detection."""
    has_change_intent: bool
    score: float                           # 0.0-1.0 confidence
    revision_signals: List[str]            # Which revision markers matched
    target_type: Optional[str]             # date/room/requirements/products
    target_matches: List[str]              # Which target patterns matched
    mode: Optional[DetourMode]             # LONG/FAST/EXPLICIT if has_change_intent
    preliminary_intent: Optional[MessageIntent]  # Best guess if not a detour
    language: str                          # "en", "de", or "mixed"

    def __str__(self) -> str:
        if self.has_change_intent:
            return f"ChangeIntent(score={self.score:.2f}, target={self.target_type}, mode={self.mode})"
        return f"NoChange(score={self.score:.2f}, intent={self.preliminary_intent})"


# =============================================================================
# DETECTION FUNCTIONS
# =============================================================================

def detect_language(text: str) -> str:
    """Detect if text is primarily English, German, or mixed."""
    text_lower = text.lower()

    # German-specific markers
    de_markers = [
        r"\b(und|oder|aber|für|mit|bei|können|möchten|gerne|bitte)\b",
        r"\b(der|die|das|den|dem|des)\b",
        r"\b(ich|wir|Sie|uns|Ihnen)\b",
    ]
    # English-specific markers
    en_markers = [
        r"\b(and|or|but|for|with|can|could|would|please)\b",
        r"\b(the|a|an)\b",
        r"\b(I|we|you|us|them)\b",
    ]

    de_count = sum(1 for pattern in de_markers if re.search(pattern, text_lower))
    en_count = sum(1 for pattern in en_markers if re.search(pattern, text_lower))

    if de_count > en_count + 2:
        return "de"
    elif en_count > de_count + 2:
        return "en"
    return "mixed"


def _match_patterns(text: str, patterns: List[str]) -> List[str]:
    """Return list of patterns that matched."""
    text_lower = text.lower()
    return [p for p in patterns if re.search(p, text_lower)]


def _match_verb_groups(text: str, verb_groups: Dict[str, List[str]]) -> Tuple[List[str], float]:
    """Match change verbs and return matches with confidence boost."""
    text_lower = text.lower()
    matches = []
    boost = 0.0

    for group, patterns in verb_groups.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                matches.append(pattern)
                if group == "strong":
                    boost = max(boost, 0.3)
                elif group == "reschedule":
                    boost = max(boost, 0.25)
                elif group == "booking":
                    boost = max(boost, 0.2)
                elif group == "product_mod":
                    boost = max(boost, 0.25)  # Product modifications are clear change signals

    return matches, boost


def has_revision_signal(text: str, language: str = "mixed") -> Tuple[bool, List[str], float]:
    """
    Check if text contains revision signals (change verbs or revision markers).

    Returns:
        (has_signal, matched_patterns, confidence_score)
    """
    matches = []
    score = 0.0

    # Check change verbs
    if language in ("en", "mixed"):
        verb_matches, boost = _match_verb_groups(text, CHANGE_VERBS_EN)
        matches.extend(verb_matches)
        score += boost

    if language in ("de", "mixed"):
        verb_matches, boost = _match_verb_groups(text, CHANGE_VERBS_DE)
        matches.extend(verb_matches)
        score += boost

    # Check revision markers
    if language in ("en", "mixed"):
        rev_matches = _match_patterns(text, REVISION_MARKERS_EN)
        matches.extend(rev_matches)
        score += 0.2 * min(len(rev_matches), 2)  # Up to 0.4 for markers

    if language in ("de", "mixed"):
        rev_matches = _match_patterns(text, REVISION_MARKERS_DE)
        matches.extend(rev_matches)
        score += 0.2 * min(len(rev_matches), 2)

    # Check request modifiers (boosters)
    if language in ("en", "mixed"):
        req_matches = _match_patterns(text, REQUEST_MODIFIERS_EN)
        if req_matches:
            score += 0.15
            matches.extend(req_matches)

    if language in ("de", "mixed"):
        req_matches = _match_patterns(text, REQUEST_MODIFIERS_DE)
        if req_matches:
            score += 0.15
            matches.extend(req_matches)

    return bool(matches), matches, min(score, 1.0)


def has_bound_target(
    text: str,
    event_state: Optional[Dict[str, Any]] = None,
    language: str = "mixed"
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Check if text references a bound target (explicit value or anaphoric reference).

    NOTE: Always checks BOTH English and German patterns for targets,
    since mixed-language messages are common (e.g., German text with
    English loanwords like "date", "room", "meeting").

    Returns:
        (has_target, target_type, matched_patterns)
    """
    text_lower = text.lower()

    # Check each target type - ALWAYS check both EN and DE patterns
    # Mixed-language usage is common in business contexts
    for target_type, lang_patterns in TARGET_PATTERNS.items():
        patterns = []
        # Always include both languages for target detection
        patterns.extend(lang_patterns.get("en", []))
        patterns.extend(lang_patterns.get("de", []))

        matches = _match_patterns(text, patterns)
        if matches:
            return True, target_type, matches

    # Check anaphoric references
    anaphoric_patterns = []
    if language in ("en", "mixed"):
        anaphoric_patterns.extend(ANAPHORIC_REFERENCES.get("en", []))
    if language in ("de", "mixed"):
        anaphoric_patterns.extend(ANAPHORIC_REFERENCES.get("de", []))

    anaphoric_matches = _match_patterns(text, anaphoric_patterns)
    if anaphoric_matches:
        # Try to infer target type from anaphoric reference
        if any("date" in m or "day" in m or "termin" in m or "tag" in m for m in anaphoric_matches):
            return True, "date", anaphoric_matches
        if any("room" in m or "space" in m or "raum" in m for m in anaphoric_matches):
            return True, "room", anaphoric_matches
        if any("menu" in m or "package" in m or "menü" in m or "paket" in m for m in anaphoric_matches):
            return True, "products", anaphoric_matches
        # Default to generic bound target
        return True, None, anaphoric_matches

    # Check if event_state has confirmed values that are mentioned
    if event_state:
        chosen_date = event_state.get("chosen_date")
        if chosen_date and chosen_date.replace("-", ".") in text_lower:
            return True, "date", [chosen_date]

        locked_room = event_state.get("locked_room_id")
        if locked_room and locked_room.lower() in text_lower:
            return True, "room", [locked_room]

    return False, None, []


def is_pure_qa(text: str, language: str = "mixed") -> bool:
    """
    Check if text is a pure Q&A question without change intent.

    This is a NEGATIVE filter - if True, likely NOT a detour.
    """
    text_lower = text.lower()

    qa_patterns = []
    if language in ("en", "mixed"):
        qa_patterns.extend(PURE_QA_SIGNALS_EN)
    if language in ("de", "mixed"):
        qa_patterns.extend(PURE_QA_SIGNALS_DE)

    has_qa_signal = any(re.search(p, text_lower) for p in qa_patterns)

    if not has_qa_signal:
        return False

    # Check if there's also a change verb - if so, not pure Q&A
    change_patterns = []
    if language in ("en", "mixed"):
        for group in CHANGE_VERBS_EN.values():
            change_patterns.extend(group)
    if language in ("de", "mixed"):
        for group in CHANGE_VERBS_DE.values():
            change_patterns.extend(group)

    has_change_verb = any(re.search(p, text_lower) for p in change_patterns)

    # Pure Q&A = has Q&A signal but no change verb
    return has_qa_signal and not has_change_verb


def is_confirmation(text: str, language: str = "mixed") -> bool:
    """Check if text is a confirmation/acceptance."""
    patterns = []
    if language in ("en", "mixed"):
        patterns.extend(CONFIRMATION_SIGNALS_EN)
    if language in ("de", "mixed"):
        patterns.extend(CONFIRMATION_SIGNALS_DE)

    return any(re.search(p, text.lower()) for p in patterns)


def is_decline(text: str, language: str = "mixed") -> bool:
    """Check if text is a decline/cancellation."""
    patterns = []
    if language in ("en", "mixed"):
        patterns.extend(DECLINE_SIGNALS_EN)
    if language in ("de", "mixed"):
        patterns.extend(DECLINE_SIGNALS_DE)

    return any(re.search(p, text.lower()) for p in patterns)


def compute_change_intent_score(
    text: str,
    event_state: Optional[Dict[str, Any]] = None,
) -> ChangeIntentResult:
    """
    Compute comprehensive change intent score with dual-condition logic.

    A message is considered a CHANGE only when BOTH are true:
    1. Has revision signal (change verb OR revision marker)
    2. Has bound target (explicit value OR anaphoric reference)

    Args:
        text: Client message text
        event_state: Current event state (for checking mentioned confirmed values)

    Returns:
        ChangeIntentResult with all detection details
    """
    language = detect_language(text)

    # Quick filters first
    if is_pure_qa(text, language):
        return ChangeIntentResult(
            has_change_intent=False,
            score=0.0,
            revision_signals=[],
            target_type=None,
            target_matches=[],
            mode=None,
            preliminary_intent=MessageIntent.GENERAL_QA,
            language=language,
        )

    if is_confirmation(text, language):
        # Could still be a change if revision markers present
        pass  # Continue checking

    if is_decline(text, language):
        return ChangeIntentResult(
            has_change_intent=False,
            score=0.0,
            revision_signals=[],
            target_type=None,
            target_matches=[],
            mode=None,
            preliminary_intent=MessageIntent.DECLINE,
            language=language,
        )

    # Dual condition check
    has_revision, revision_matches, revision_score = has_revision_signal(text, language)
    has_target, target_type, target_matches = has_bound_target(text, event_state, language)

    # Both conditions must be met
    if has_revision and has_target:
        # Determine mode based on whether new value is extractable
        # (This is a heuristic - LLM will refine)
        mode = DetourMode.LONG  # Default to asking for value

        # Check for explicit new value patterns
        # Date patterns
        if target_type == "date":
            date_patterns = [
                r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",  # ISO date
                r"\d{1,2}[-./]\d{1,2}[-./]\d{4}",  # DD.MM.YYYY
                r"\d{1,2}[-./]\d{1,2}\b",          # DD.MM
            ]
            if any(re.search(p, text) for p in date_patterns):
                mode = DetourMode.FAST

        # Room name patterns
        elif target_type == "room":
            if re.search(r"\broom\s+[a-z]\b", text.lower()):
                mode = DetourMode.FAST

        # Number patterns for requirements
        elif target_type == "requirements":
            if re.search(r"\b\d+\s+(people|persons?|guests?|pax)\b", text.lower()):
                mode = DetourMode.FAST

        # Check for explicit old+new pattern (explicit mode)
        if re.search(r"(instead\s+of|not|rather\s+than)\s+.{1,30}\s+(but|,)\s+", text.lower()):
            mode = DetourMode.EXPLICIT

        return ChangeIntentResult(
            has_change_intent=True,
            score=min(revision_score + 0.3, 1.0),  # Boost for meeting dual condition
            revision_signals=revision_matches,
            target_type=target_type,
            target_matches=target_matches,
            mode=mode,
            preliminary_intent=None,
            language=language,
        )

    # Only one condition met - not a change, but note the signals
    preliminary_intent = MessageIntent.UNCLEAR
    if is_confirmation(text, language):
        preliminary_intent = MessageIntent.CONFIRMATION
    elif has_revision and not has_target:
        # Has change language but no specific target - might need clarification
        preliminary_intent = MessageIntent.UNCLEAR

    return ChangeIntentResult(
        has_change_intent=False,
        score=revision_score * 0.5,  # Partial score
        revision_signals=revision_matches,
        target_type=target_type,
        target_matches=target_matches,
        mode=None,
        preliminary_intent=preliminary_intent,
        language=language,
    )


# =============================================================================
# CONVENIENCE: Get all patterns for a language
# =============================================================================

def get_all_change_verbs(language: str = "mixed") -> List[str]:
    """Get all change verb patterns for the specified language."""
    patterns = []
    if language in ("en", "mixed"):
        for group in CHANGE_VERBS_EN.values():
            patterns.extend(group)
    if language in ("de", "mixed"):
        for group in CHANGE_VERBS_DE.values():
            patterns.extend(group)
    return patterns


def get_all_revision_markers(language: str = "mixed") -> List[str]:
    """Get all revision marker patterns for the specified language."""
    patterns = []
    if language in ("en", "mixed"):
        patterns.extend(REVISION_MARKERS_EN)
    if language in ("de", "mixed"):
        patterns.extend(REVISION_MARKERS_DE)
    return patterns


# =============================================================================
# SHARED DETECTION PATTERNS (Consolidated from multiple modules)
# =============================================================================

# Action request patterns - prevents "send me X" from triggering Q&A
# Consolidated from intent_classifier.py and general_qna_classifier.py
# NOTE: Patterns must require explicit recipient (me/us) to avoid matching questions
# e.g., "do you provide X" is a question, not an action request
ACTION_REQUEST_PATTERNS = (
    r"\bsend\s+(me\s+)?(the\s+|a\s+)?",
    r"\bprovide\s+(me|us)\s+(with\s+)?",  # Fixed: requires "me" or "us" after "provide"
    r"\bgive\s+(me|us)\b",
    r"\bemail\s+(me|us)\b",
    r"\bforward\s+(me|us)\b",
)

# Availability tokens - fast string matching for common availability queries
AVAILABILITY_TOKENS = (
    "availability",
    "available",
    "slot",
    "slots",
    "free on",
    "open on",
    "still open",
    "still free",
)

# Resume/confirmation phrases - exact match set for quick confirmations
RESUME_PHRASES = {
    "yes",
    "yes please",
    "yes thanks",
    "yes, please",
    "yes we can",
    "ok",
    "okay",
    "sure",
    "sounds good",
    "let's do it",
    "proceed",
    "continue",
    "please continue",
    "go ahead",
    "sounds good to me",
    "please proceed",
}


# =============================================================================
# ROOM SEARCH INTENTS (Industry best practices)
# Provides granular detection for room booking scenarios beyond generic Q&A
# =============================================================================

class RoomSearchIntent(Enum):
    """Specific room search intents for precise routing."""
    CHECK_AVAILABILITY = "check_availability"
    REQUEST_OPTION = "request_option"
    CHECK_CAPACITY = "check_capacity"
    CHECK_ALTERNATIVES = "check_alternatives"
    CONFIRM_BOOKING = "confirm_booking"
    UNKNOWN = "unknown"


# Option/hold request patterns - distinguishes "hold it" from "is it free?"
OPTION_KEYWORDS = {
    "en": [
        r"\b(can|could)\s+(i|we)\s+(option|hold|reserve)\b",
        r"\bput\s+(it|me|us\s+)?on\s+(hold|option)\b",  # "put it on hold" OR "put on hold"
        r"\bmake\s+an\s+option\b",
        r"\btentative\s+(booking|reservation)\b",
        r"\bprovisional\s+(booking|reservation)\b",
        r"\bsoft\s+hold\b",
        r"\bsubject\s+to\s+release\b",
        r"\bfirst\s+option\b",
        r"\bhold\s+the\s+space\b",
    ],
    "de": [
        r"\b(können|könnten)\s+(sie|wir)\s+(optionieren|reservieren)\b",
        r"\beine\s+option\s+(machen|setzen|eintragen)\b",
        r"\bprovisorisch\s+(buchen|reservieren)\b",
        r"\b(datum|raum|termin)\s+(blocken|festhalten)\b",
        r"\boption\s+auf\b",
    ],
}

# Capacity check patterns - direct capacity queries
CAPACITY_KEYWORDS = {
    "en": [
        r"\b(capacity|cap)\b",
        r"\bhow\s+many\s+(people|guests|pax)\b",
        r"\b(does|will)\s+it\s+fit\b",
        r"\bfits?\s+\d+\s*(people|guests|pax)?\b",
        r"\b(enough|sufficient)\s+(space|room)\b",
        r"\bstanding\s+capacity\b",
        r"\btheat(er|re)\s+style\s+for\s+\d+\b",
        r"\bmax(imum)?\s+(capacity|guests|people)\b",
        r"\bseated\s+capacity\b",
    ],
    "de": [
        r"\b(kapazität|platzangebot)\b",
        r"\bwie\s+viele\s+(personen|gäste|leute)\b",
        r"\b(passt|passen)\s+(das|es|wir)\b",
        r"\b(genug|ausreichend)\s+platz\b",
        r"\bplatz\s+für\s+\d+\b",
        r"\bmax(imale)?\s+(anzahl|kapazität)\b",
        r"\bbestuhlt\b",
        r"\bstehend\b",
    ],
}

# Alternative/waitlist patterns - handles "what else?" and fallback requests
ALTERNATIVE_KEYWORDS = {
    "en": [
        r"\b(waitlist|waiting\s+list)\b",
        r"\b(other|alternative|different)\s+(dates?|days?|times?|options?)\b",
        r"\b(next|nearest)\s+available\b",
        r"\bwhat\s+else\s+do\s+you\s+have\b",
        r"\bany\s+other\s+rooms?\b",
        r"\bnext\s+opening\b",
        r"\bbackup\s+option\b",
        r"\bif\s+not\b",
        r"\bin\s+case\s+it'?s?\s+(full|booked)\b",
    ],
    "de": [
        r"\b(warteliste)\b",
        r"\b(andere|alternative)\s+(daten|termine|tage|optionen)\b",
        r"\b(nächste|nächster)\s+freie[rn]?\b",
        r"\bwas\s+haben\s+sie\s+sonst\b",
        r"\bausweich(termin|datum|raum)\b",
        r"\bfalls\s+(nicht|voll|belegt)\b",
    ],
}

# Enhanced confirmation - stronger signals than generic "yes"
ENHANCED_CONFIRMATION_KEYWORDS = {
    "en": [
        r"\blooks\s+(correct|right|good|perfect)\b",
        r"\b(i|we)\s+approve\b",
        r"\bgreen\s+light\b",
        r"\bsign\s+(me|us)\s+up\b",
        r"\b(it's|that's)\s+a\s+deal\b",
        r"\bready\s+to\s+(book|sign|pay)\b",
        r"\bsend\s+(the\s+)?(contract|invoice)\b",
        r"\block\s+it\s+in\b",
        r"\bsecure\s+the\s+date\b",
        r"\bbinding\s+booking\b",
        r"\bfirm\s+commitment\b",
    ],
    "de": [
        r"\bsieht\s+(gut|richtig|korrekt)\s+aus\b",
        r"\b(ich|wir)\s+bestätigen\b",
        r"\bgrünes\s+licht\b",
        r"\b(wir|ich)\s+bin\s+dabei\b",
        r"\babgemacht\b",
        r"\bbereit\s+zu(m)?\s+(buchen|unterschreiben|zahlen)\b",
        r"\bbitte\s+(vertrag|rechnung)\s+senden\b",
        r"\bfest\s+buchen\b",
        r"\bdatum\s+sichern\b",
    ],
}

# Availability check patterns - refined from room_search_keywords.py
AVAILABILITY_KEYWORDS = {
    "en": [
        r"\b(is|are)\s+(it|they|the\s+room|the\s+space)\s+(available|free|open|vacant)\b",
        r"\b(do|can)\s+you\s+(have|offer)\s+availability\b",
        r"\b(is|are)\s+(it|they)\s+booked\b",
        r"\bstatus\s+of\b",
        r"\bcan\s+we\s+book\b",
        r"\bopen\s+for\s+booking\b",
    ],
    "de": [
        r"\b(ist|sind)\s+(es|sie|der\s+raum)\s+(frei|verfügbar|noch\s+zu\s+haben)\b",
        r"\b(haben|hätten)\s+sie\s+(noch\s+)?(platz|kapazität)\b",
        r"\b(ist|sind)\s+(es|sie)\s+belegt\b",
        r"\bwie\s+sieht\s+es\s+aus\s+mit\b",
        r"\bkann\s+man\s+(noch\s+)?buchen\b",
    ],
}
