# TIMEVAL-001: Time Slot Validation + Room Unavailability Detour

**Test ID:** TIMEVAL-001
**Category:** Feature - Time Validation
**Flow:** 1 (outside hours) -> 2 -> 3 (room select) -> date change -> room unavailable detour -> 4
**Pass Criteria:** Time validation warns about operating hours, room detour handles unavailability

---

## Overview

This test verifies two features working together:

1. **Time Slot Validation**: When client requests times outside operating hours (08:00-23:00), system should:
   - Detect the issue during intake
   - Store warning for display in offer
   - Continue workflow (non-blocking warning)

2. **Room Unavailability Detour**: When client changes date and room becomes unavailable:
   - System detects date change
   - Checks room availability on new date
   - Routes to room re-selection if unavailable
   - Presents alternatives

---

## Test Scenarios

### Scenario A: Intake with Times Outside Operating Hours

```
ACTION: Send initial email requesting 7pm to 1am event
INPUT: "Hi, I'm looking to book a party room for 40 people on February 15, 2026.
        We'd like to have it from 7pm until 1am."

EXPECTED:
- System extracts times (7pm = 19:00, 1am = 01:00)
- Detects 1am crosses midnight (past 23:00 closing)
- Stores time_validation warning
- Continues with room recommendations

VERIFY:
- [ ] No fallback message
- [ ] Workflow progresses (room recommendations shown)
- [ ] time_validation stored in event_entry
```

### Scenario B: Date Change with Room Unavailable

```
SETUP: Event at Step 4/5 with Room A locked for Feb 15

ACTION: Request date change where Room A is unavailable
INPUT: "Actually, we need to change the date to February 20, 2026 instead."

EXPECTED:
- System detects date change request
- Routes through date confirmation (Step 2)
- Checks room availability on new date
- If Room A unavailable on Feb 20, presents alternatives

VERIFY:
- [ ] Date change acknowledged
- [ ] Room availability checked on new date
- [ ] Alternatives presented if room unavailable
- [ ] No fallback message
```

### Scenario C: Combined Flow (Full E2E)

```
FLOW:
1. Send intake with 7pm-1am times -> warning stored
2. System shows room options, select Room A
3. Progress to offer
4. Change date to Feb 20 (where Room A unavailable)
5. Room alternatives presented

EXPECTED:
- Time warning persists through date change
- Room detour handles unavailability correctly
- Both warnings and alternatives shown appropriately
```

---

## Pass Criteria

- [ ] Time validation detects hours outside 08:00-23:00
- [ ] Warning is non-blocking (workflow continues)
- [ ] Warning stored in event_entry.time_validation
- [ ] Warning displayed in offer body (Step 4)
- [ ] Date change triggers room availability check
- [ ] Room unavailability presents alternatives
- [ ] No fallback messages at any step

---

## Test Run Results

### Run 1: 2026-01-28

**Environment:**
- AGENT_MODE=openai
- Operating Hours: 08:00-23:00
- Test Framework: pytest + E2ETestHarness

**Results:**

| Test | Status | Notes |
|------|--------|-------|
| `test_intake_with_late_hours_progresses_to_offer` | PASS | Workflow progresses, warning persisted |
| `test_offer_includes_hours_warning` | PASS | Warning visible in offer |
| `test_date_change_triggers_room_check` | PASS | Date change processed correctly |
| `test_room_unavailable_presents_alternatives` | PASS | Alternatives shown |
| `test_full_flow_with_time_warning_and_room_detour` | PASS | Combined flow works |
| `test_time_validation_persists_through_detour` | PASS | Warning persists |
| Infrastructure tests (3) | PASS | All infrastructure checks pass |

**Overall: 9/9 PASS** (141.70s)

**Observations:**
1. Time validation correctly identifies 7pm-1am as outside hours (1am crosses midnight)
2. Warning is stored in `event_entry.time_validation` for traceability
3. Warning is displayed as suffix in Step 4 offer body
4. Date change properly routes through Step 2 -> Step 3 check
5. Room unavailability mock works correctly with `mock_room_availability` fixture
6. No fallback messages observed in any scenario

---

## Implementation Details

### Files Modified
- `workflows/common/time_validation.py` - Core validation module
- `workflows/steps/step1_intake/trigger/step1_handler.py` - Intake integration
- `workflows/steps/step2_date_confirmation/trigger/confirmation_flow.py` - Date confirmation integration
- `workflows/steps/step4_offer/trigger/step4_handler.py` - Offer display
- `activity/persistence.py` - Activity logging (time_outside_hours)

### Key Design Decisions
1. **LLM-First**: Uses unified_detection times, never re-parses from text
2. **Non-blocking**: Warning stored for display, doesn't halt workflow
3. **Defense in Depth**: Validated at Step 1, Step 2, displayed at Step 4
4. **Site Visit Bypass**: `is_site_visit=True` skips validation

### Activity Tracking
Time validation issues are logged via:
```python
log_activity(event_entry, "time_outside_hours", {"issue": "...", "start": "...", "end": "..."})
```

---

## Related Tests

- `tests_root/specs/e2e_comprehensive/test_time_validation_and_room_detour.py`
- `tests/unit/test_time_validation.py` (19 unit tests)
- `05_core_detours/test_date_change_room_unavailable.md` (related detour test)

---

## Notes for Manual Testing

To manually verify via Playwright/browser:

1. Navigate to chat interface
2. Send: "Hi, I'd like to book for 40 people on Feb 15, 2026, from 7pm to 1am"
3. Verify room recommendations appear (no error)
4. Select Room A
5. Request offer: "Please send the offer"
6. Verify offer includes "23:00" or "closing" mention
7. Change date: "Actually, change to Feb 20 please"
8. Verify room alternatives shown if Room A unavailable on Feb 20
