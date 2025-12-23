"""
MODULE: backend/detection/__init__.py
PURPOSE: Central registry for all message classification and detection logic.

This module provides a centralized location for all detection functions used
throughout the OpenEvent workflow. Each submodule handles a specific detection domain.

STRUCTURE:
    detection/
    ├── intent/          # Intent classification and confidence scoring
    ├── response/        # Client response detection (accept, decline, counter, confirm)
    ├── change/          # Detour and change request detection
    ├── qna/             # Q&A and sequential workflow detection
    ├── special/         # Special cases (manager request, room conflict, nonsense)
    └── keywords/        # Source of truth for all keyword patterns (EN/DE)

QUICK REFERENCE:

    Intent Classification:
        from backend.detection import classify_intent, is_gibberish, check_confidence

    Response Detection:
        from backend.detection import (
            matches_acceptance_pattern,
            matches_decline_pattern,
            matches_counter_pattern,
            is_confirmation
        )

    Change/Detour Detection:
        from backend.detection import (
            detect_change_type,
            detect_change_type_enhanced,
            has_revision_signal,
            has_bound_target
        )

    Q&A Detection:
        from backend.detection import (
            detect_general_room_query,
            detect_sequential_workflow_request
        )

    Special Detection:
        from backend.detection import (
            looks_like_manager_request,
            detect_room_conflict,
            check_nonsense_gate
        )

    Keywords (source of truth):
        from backend.detection.keywords import (
            CONFIRMATION_SIGNALS_EN, CONFIRMATION_SIGNALS_DE,
            CHANGE_VERBS_EN, CHANGE_VERBS_DE,
            REVISION_MARKERS_EN, REVISION_MARKERS_DE,
            # ... etc
        )

MIGRATION STATUS:
    This module is being populated as part of the AI Agent Optimization refactoring.
    See /Users/nico/.claude/plans/wild-enchanting-eagle.md for details.

    Files to migrate here:
    - backend/llm/intent_classifier.py -> detection/intent/classifier.py
    - backend/workflows/nlu/keyword_buckets.py -> detection/keywords/buckets.py
    - backend/workflows/nlu/semantic_matchers.py -> detection/response/*
    - backend/workflows/nlu/general_qna_classifier.py -> detection/qna/general_qna.py
    - backend/workflows/nlu/sequential_workflow.py -> detection/qna/sequential_workflow.py
    - backend/workflows/change_propagation.py -> detection/change/detour.py
    - backend/workflows/common/confidence.py -> detection/intent/confidence.py
    - backend/workflows/common/conflict.py -> detection/special/room_conflict.py
"""

# Exports will be added as modules are migrated
# Example future exports:
# from backend.detection.intent.classifier import classify_intent
# from backend.detection.response.acceptance import matches_acceptance_pattern
# etc.

__all__ = [
    # Will be populated during migration
]
