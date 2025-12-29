from __future__ import annotations

from typing import List, Sequence


_STEP_NAMES = {
    1: "Intake",
    2: "Date Confirmation",
    3: "Room Selection",
    4: "Offer Review",
    5: "Negotiation",
    6: "Transition",
    7: "Booking Confirmation",
}

_DEFAULT_NEXT = {
    2: "share your preferred date or choose from AVAILABLE DATES.",
    3: "confirm which room you'd like me to secure.",
    4: "let me know which products or catering to add, or say you're ready for the offer.",
    5: "share any adjustments you'd like so I can update the proposal.",
    6: "confirm the handover details so I can brief the onsite team.",
    7: "confirm the booking so I can prepare the final paperwork.",
}

_MISSING_DESCRIPTIONS = {
    "date": "share your preferred date",
    "time": "confirm the start and end times",
    "room": "select the room you'd like to lock",
    "attendees": "confirm the attendee count",
    "layout": "let me know the seating layout",
    "products": "pick the products you'd like to add",
    "catering": "choose the catering you'd like",
}


def _step_index(step: int | str | None) -> int | None:
    if isinstance(step, int):
        return step
    if isinstance(step, str):
        normalized = step.strip().lower()
        for idx, label in _STEP_NAMES.items():
            if label.lower() == normalized:
                return idx
    return None


def _step_label(step: int | str | None) -> str:
    if isinstance(step, int):
        return _STEP_NAMES.get(step, f"Step {step}")
    if isinstance(step, str):
        normalized = step.strip().lower()
        for label in _STEP_NAMES.values():
            if label.lower() == normalized:
                return label
        return step.strip() or "Next Step"
    return "Next Step"


def _missing_prompt(step: int | str | None, missing: Sequence[str]) -> str:
    if not missing:
        maybe_idx = _step_index(step)
        if maybe_idx is not None:
            return _DEFAULT_NEXT.get(maybe_idx, "let me know when you're ready to continue.")
        return "let me know when you're ready to continue."
    descriptions: List[str] = []
    for token in missing:
        desc = _MISSING_DESCRIPTIONS.get(token)
        if desc and desc not in descriptions:
            descriptions.append(desc)
    if not descriptions:
        maybe_idx = _step_index(step)
        if maybe_idx is not None:
            return _DEFAULT_NEXT.get(maybe_idx, "let me know when you're ready to continue.")
        return "let me know when you're ready to continue."
    if len(descriptions) == 1:
        return descriptions[0]
    return ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"


def build_info_block(lines: List[str]) -> str:
    """Construct an info block with bullet lines (more conversational)."""

    block: List[str] = []
    if not lines:
        block.append("I don't have additional details on that right now.")
        return "\n".join(block)

    for line in lines:
        clean = (line or "").strip()
        if not clean:
            continue
        if clean.startswith("- "):
            block.append(clean)
        else:
            block.append(f"- {clean}")
    if not block:
        block.append("I don't have additional details on that right now.")
    return "\n".join(block)


def build_next_step_line(step: int | str | None, missing_fields: Sequence[str]) -> str:
    """Construct a conversational prompt for continuing the workflow."""

    label = _step_label(step)
    prompt = _missing_prompt(step, missing_fields)
    lead = prompt[:1].upper() + prompt[1:] if prompt else prompt
    # More natural phrasing instead of "NEXT STEP:"
    return f"To continue with {label.lower()}, please {prompt}."


def build_qna_info_and_next_step(info_lines: List[str], current_step: int, missing: Sequence[str]) -> str:
    """
    Compose the deterministic INFO/NEXT STEP block used for capability Q&A replies.
    """

    info_block = build_info_block(info_lines)
    next_step_block = build_next_step_line(current_step, missing)
    return "\n\n".join([info_block, next_step_block])


__all__ = ["build_info_block", "build_next_step_line", "build_qna_info_and_next_step"]
