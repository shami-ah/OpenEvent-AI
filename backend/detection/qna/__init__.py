"""
MODULE: backend/detection/qna/__init__.py
PURPOSE: Q&A and sequential workflow detection.

Detects general questions that should be answered without advancing the workflow,
and sequential workflow requests where client confirms current step + asks about next.

CONTAINS:
    - general_qna.py         detect_general_room_query() - from nlu/general_qna_classifier.py
    - sequential_workflow.py detect_sequential_workflow_request() - from nlu/sequential_workflow.py
    - qna_types.py           _detect_qna_types() - specific Q&A categorization

Q&A TYPES DETECTED:
    - rooms_by_feature      "What rooms have a projector?"
    - catering_for          "What catering options for 30 people?"
    - products_for          "What add-ons are available?"
    - free_dates            "What dates are available in February?"
    - check_availability    "Is Room A free on May 15?"
    - check_alternatives    "What if Room A is taken?"
    - confirm_booking       "I want to confirm"
    - request_option        "Can you hold the room?"
    - check_capacity        "Does Room B fit 50 people?"

SEQUENTIAL WORKFLOW DETECTION:
    Identifies messages that combine:
    1. Action/confirmation for CURRENT step (e.g., "confirm May 8")
    2. Question about NEXT step (e.g., "show me available rooms")

    Result: is_general=False, proceed with workflow, don't treat as pure Q&A

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # Q&A signal patterns
    - backend/detection/intent/classifier.py # Intent classification

USED BY:
    - backend/workflows/steps/step2_date_confirmation/  # Date Q&A
    - backend/workflows/steps/step3_room_availability/  # Room Q&A
    - backend/workflows/steps/step4_offer/              # Product Q&A

EXPORTS:
    - detect_general_room_query(message, state) -> GeneralQnaClassification
    - detect_sequential_workflow_request(message, current_step) -> SequentialWorkflowResult
    - _detect_qna_types(message) -> List[str]

RELATED TESTS:
    - backend/tests/detection/test_qna_detection.py
    - backend/tests/detection/test_sequential_workflow.py
"""

# Sequential workflow detection (migrated from nlu/sequential_workflow.py)
from .sequential_workflow import detect_sequential_workflow_request

# General Q&A detection (migrated from nlu/general_qna_classifier.py)
from .general_qna import (
    detect_general_room_query,
    empty_general_qna_detection,
    heuristic_flags,
    parse_constraints,
    quick_general_qna_scan,
    should_call_llm,
    reset_general_qna_cache,
)

__all__ = [
    # Sequential workflow
    "detect_sequential_workflow_request",
    # General Q&A
    "detect_general_room_query",
    "empty_general_qna_detection",
    "heuristic_flags",
    "parse_constraints",
    "quick_general_qna_scan",
    "should_call_llm",
    "reset_general_qna_cache",
]
