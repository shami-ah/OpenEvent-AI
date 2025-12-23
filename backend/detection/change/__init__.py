"""
MODULE: backend/detection/change/__init__.py
PURPOSE: Detour and change request detection.

Detects when a client wants to change/modify something already established,
triggering a "detour" back to an earlier workflow step.

CONTAINS:
    - detour.py              Main detour detection (from change_propagation.py)
    - date_change.py         Date-specific change detection
    - room_change.py         Room-specific change detection
    - requirements_change.py Requirements change detection (participants, layout, etc.)

DETECTION LOGIC (Dual-Condition):
    A change is detected when BOTH conditions are met:
    1. REVISION SIGNAL: "change", "instead", "actually", "reschedule", etc.
    2. BOUND TARGET: Explicit value (date, room name) OR anaphoric reference

    Examples:
    - "I'd like to change the date to May 15" -> revision + bound target (date)
    - "What dates are free?" -> NO revision signal, this is Q&A not a change

DEPENDS ON:
    - backend/detection/keywords/buckets.py  # CHANGE_VERBS_*, REVISION_MARKERS_*

USED BY:
    - backend/workflows/steps/step2_date_confirmation/
    - backend/workflows/steps/step3_room_availability/
    - backend/workflows/steps/step4_offer/
    - backend/workflows/steps/step5_negotiation/

EXPORTS:
    - detect_change_type(message, state) -> ChangeType
    - detect_change_type_enhanced(message, state) -> EnhancedChangeResult
    - has_revision_signal(text) -> bool
    - has_bound_target(text) -> bool
    - resolve_ambiguous_target(change_result, state) -> ResolvedChange

RELATED TESTS:
    - backend/tests/detection/test_detour_detection.py
    - backend/tests/detection/test_change_detection.py
"""

# Exports will be added as modules are migrated
