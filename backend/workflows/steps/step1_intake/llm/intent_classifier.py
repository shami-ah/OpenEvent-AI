from __future__ import annotations

from typing import Any, Dict, Tuple

from backend.workflows.llm.adapter import (
    classify_intent as _classify_intent,
    extract_user_information as _extract_user_information,
    sanitize_user_info as _sanitize_user_info,
)

__workflow_role__ = "llm"


def classify_intent(payload: Dict[str, Any]) -> Tuple[Any, float]:
    """[LLM] Run the classifier to determine the workflow intent."""

    return _classify_intent(payload)


def extract_user_information(payload: Dict[str, Any]) -> Dict[str, Any]:
    """[LLM] Extract structured fields such as date, time, and room."""

    return _extract_user_information(payload)


def sanitize_user_info(raw: Dict[str, Any]) -> Dict[str, Any]:
    """[LLM] Normalize user information into canonical workflow fields."""

    return _sanitize_user_info(raw)
