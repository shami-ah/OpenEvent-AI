# Time Slot Validation Against Operating Hours

**Status:** IMPLEMENTED (2026-01-28)

## Problem Statement

When a client requests event times outside operating hours (e.g., "7pm to 1am" when venue closes at 23:00), the AI:
1. Extracts the times correctly
2. Proceeds to room recommendations WITHOUT validating
3. Only validates in Step 2 (too late - after room selection)

**Expected behavior:** Validate times in Step 1 and inform client with alternatives.

---

## Solution Overview

Add **defense-in-depth time validation** at multiple points:
- **Step 1**: Validate on initial intake (primary)
- **Step 2**: Validate when times are finalized in confirmation flow
- **Step 4**: Display warning in offer if times are outside hours
- Uses existing `get_operating_hours()` from config_store (default 8:00-23:00)
- Non-blocking: stores warning in `state.extras`, appends to response
- **LLM-First**: Uses `unified_detection.start_time`/`end_time` (never re-parse from text)

---

## Codex Review Status: APPROVED

Key refinements from Codex review:
1. Added Step 2 and detour coverage
2. Use unified detection as time source (LLM-first)
3. Activity type set to "detailed" granularity
4. Step 4 consumes warning for offer verbalization
5. Guard against site visit times

---

## Files Modified

| File | Action | Purpose |
|------|--------|---------|
| `workflows/common/time_validation.py` | **CREATED** | Shared validation logic (called from multiple steps) |
| `workflows/steps/step1_intake/trigger/step1_handler.py` | Modified | Integrate after entity extraction |
| `workflows/steps/step2_date_confirmation/trigger/confirmation_flow.py` | Modified | Validate when times finalized |
| `workflows/steps/step4_offer/trigger/step4_handler.py` | Modified | Read warning for offer verbalization |
| `activity/persistence.py` | Modified | Add `time_outside_hours` activity type (detailed) |
| `tests/unit/test_time_validation.py` | **CREATED** | Unit tests (19 test cases) |

---

## Implementation Details

### 1. Shared Module: `workflows/common/time_validation.py`

```python
@dataclass
class TimeValidationResult:
    is_valid: bool
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    issue: Optional[str] = None  # "start_too_early", "end_too_late", "both"
    friendly_message: Optional[str] = None

def validate_event_times(
    start_time: Optional[str],
    end_time: Optional[str],
    is_site_visit: bool = False,
) -> TimeValidationResult:
    """
    Validate times against venue operating hours.

    IMPORTANT: Times should come from unified_detection (LLM-extracted),
    NOT re-parsed from message body text.
    """
```

### 2. Integration Points

**Step 1 (line ~197):**
```python
from workflows.common.time_validation import validate_event_times
time_validation = validate_event_times(
    start_time=unified_detection.start_time if unified_detection else None,
    end_time=unified_detection.end_time if unified_detection else None,
    is_site_visit=False,
)
if not time_validation.is_valid:
    state.extras["time_warning"] = time_validation.friendly_message
    state.extras["time_warning_issue"] = time_validation.issue
```

**Step 2 (finalize_confirmation):**
```python
time_validation = validate_event_times(window.start_time, window.end_time)
if not time_validation.is_valid:
    state.extras["time_warning"] = time_validation.friendly_message
```

**Step 4 (offer generation):**
```python
time_warning = state.extras.get("time_warning")
if time_warning:
    log_workflow_activity(event_entry, "time_outside_hours", ...)
    time_warning_suffix = f"\n\n---\n**Note:** {time_warning}"
```

---

## Feature Interference Assessment

| Feature | Impact | Risk | Mitigation |
|---------|--------|------|------------|
| **Smart Shortcuts** | MEDIUM | Warning in extras may not surface | Step 4 consumer reads `state.extras["time_warning"]` |
| **Q&A** | LOW | Q&A is read-only | No change needed |
| **Hybrid Messages** | MEDIUM | Time warning must not block | Non-blocking: stores in extras only |
| **Detours** | MEDIUM | Times may arrive via detours | Detours route through Step 1/2 where validation exists |
| **Gatekeeping** | LOW | HIL/billing gates separate | No change needed |
| **Confirmations** | LOW | Confirmation before validation | No change needed |

**Key Safety Measures:**
1. **LLM-First**: Uses `unified_detection.start_time`/`end_time` (never regex re-parsing)
2. **Non-blocking**: Stores warning in `state.extras`, doesn't halt workflow
3. **Site visit guard**: `is_site_visit=True` bypasses validation
4. **Defense in depth**: Validation at Step 1, Step 2, and Step 4 display

---

## Test Coverage

| Scenario | Input | Expected Output | Status |
|----------|-------|-----------------|--------|
| Valid times | "14:00 to 18:00" | `is_valid=True` | PASS |
| Start too early | "07:00 to 12:00" | `is_valid=False`, `issue="start_too_early"` | PASS |
| End too late | "19:00 to 01:00" | `is_valid=False`, `issue="end_too_late"` | PASS |
| Both invalid | "06:00 to 02:00" | `is_valid=False`, `issue="start_too_early_and_end_too_late"` | PASS |
| No times | None | `is_valid=True` (not an error) | PASS |
| Exact boundary | "08:00 to 23:00" | `is_valid=True` | PASS |
| Site visit time | "10:00" (site visit) | `is_valid=True` (bypassed) | PASS |
| Custom hours | Mock 9-22 | Validates against custom config | PASS |

**Test Results:** 19 passed, 0 failed

---

## Verification Completed

1. Unit tests: `pytest tests/unit/test_time_validation.py -v` - 19 passed
2. Regression tests: `pytest tests/regression/` - 177 passed, 1 skipped
3. Full test suite: 336 passed, 1 skipped, 2 xfailed
4. Activity log: `time_outside_hours` activity type registered (detailed granularity)

---

## Future Enhancements (Not in Scope)

- Integration with calendar blocking for operating hours
- Time zone handling for international clients
- Configurable grace periods (e.g., allow 15 min before/after)
- Multi-day event time validation
