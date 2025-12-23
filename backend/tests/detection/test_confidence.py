# MIGRATED: from backend.workflows.common.confidence -> backend.detection.intent.confidence
from backend.detection.intent.confidence import (
    CONFIDENCE_NONSENSE,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    confidence_level,
    should_defer_to_human,
    should_seek_clarification,
)


def test_should_defer_below_threshold():
    assert should_defer_to_human(CONFIDENCE_NONSENSE - 0.01)


def test_should_not_defer_at_threshold():
    assert not should_defer_to_human(CONFIDENCE_NONSENSE)


def test_should_seek_clarification_below_low():
    assert should_seek_clarification(CONFIDENCE_LOW - 0.01)


def test_should_not_seek_clarification_above_low():
    assert not should_seek_clarification(CONFIDENCE_LOW + 0.01)


def test_confidence_level_high():
    assert confidence_level(CONFIDENCE_HIGH) == "high"


def test_confidence_level_medium():
    mid = (CONFIDENCE_MEDIUM + CONFIDENCE_HIGH) / 2
    assert confidence_level(mid) == "medium"


def test_confidence_level_low():
    low_mid = (CONFIDENCE_LOW + CONFIDENCE_MEDIUM) / 2
    assert confidence_level(low_mid) == "low"


def test_confidence_level_very_low():
    assert confidence_level(CONFIDENCE_LOW - 0.1) == "very_low"
