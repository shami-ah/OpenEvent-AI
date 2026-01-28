# E2E Scenario: Date Change Room Conflict Detection

**Date:** 2026-01-22
**Variant:** Hybrid (I:ope / E:gem / V:ope)
**Status:** ✅ BUG FIXED (BUG-045) - Verified 2026-01-22

## Test Summary

This test attempted to verify that:
1. When Client A has a CONFIRMED booking (deposit paid) for Room X on Date Y
2. And Client B changes their date TO Date Y
3. Then Room X should be marked UNAVAILABLE and an alternative room suggested

**RESULT:** The room conflict detection does NOT work. Double booking occurred.

## Conversation Sequence

### Setup: Client 1 - Create Confirmed Booking

**Client 1 (client1@test.com):**
```
I'd like to book Room B for 50 guests on January 25, 2026 from 10:00 to 14:00.
```

**Shami:**
```
Offer draft for 25.01.2026 · Room B
Total: CHF 750.00
Deposit to reserve: CHF 225.00
```

**Client 1:**
```
We accept the offer. Billing: Test Company, Test Street 1, 8000 Zurich.
```

**Shami:**
```
Please complete the deposit payment of CHF 225.00
```

*Client 1 clicks "Pay Deposit"*

**Shami:**
```
We're thrilled to confirm your booking for Room B on 25.01.2026.
Your deposit of CHF 225 has been successfully received.
Would you like to schedule a site visit?
```

**Status:** Client 1 has CONFIRMED booking - Room B on Jan 25, 2026

---

### Test: Client 2 - Date Change Should Trigger Conflict

**Client 2 (client2@test.com):**
```
I'd like to book Room B for 35 guests on January 30, 2026 from 14:00 to 18:00.
```

**Shami:**
```
Offer draft for 30.01.2026 · Room B
```

**Client 2:**
```
Actually, can we change the date to January 25, 2026 instead? Same time 14:00-18:00.
```

### EXPECTED Behavior:
```
Room B is not available on 25.01.2026 (already confirmed).
Available alternatives for your event:
- Room A (capacity: 80)
- Room C (capacity: 120)
```

### ACTUAL Behavior:
```
Here's your offer for Room B, accommodating 35 participants.
Offer draft for 25.01.2026 · Room B
```

**BUG:** System generated offer for SAME room on SAME date without detecting conflict!

---

### Continuation: Double Booking Completed

**Client 2:**
```
We accept. Billing: Second Company, Main Street 5, 8000 Zurich.
```

**Shami:**
```
Please complete the deposit payment of CHF 225.00
```

*Client 2 clicks "Pay Deposit"*

**Shami:**
```
We're thrilled to confirm your booking for Room B on 25.01.2026.
Your deposit of CHF 225 has been successfully received.
```

**RESULT:** Both Client 1 AND Client 2 have confirmed bookings for Room B on January 25, 2026.

## Key Findings

- [x] **FIXED:** Cross-client room conflict detection now works
- [x] Room evaluation now checks `event["status"]` (canonical) with fallback to `event_data["Status"]` (legacy)
- [x] Calendar status (Option/Confirmed) properly detected for other clients
- [x] Status sync added to `update_event_metadata` for backward compatibility
- [x] **NEW:** `exclude_event_id` parameter prevents self-conflict when re-evaluating rooms

## Root Cause Analysis

**Issue 1: Status Field Duality**

Two separate status fields existed:
- `event["status"]` - Canonical booking status (Lead/Option/Confirmed), set by `update_event_metadata`
- `event_data["Status"]` - Legacy field, only updated in Step 7's `post_offer.py`

The `room_status_checker.py` only checked `event_data["Status"]`, ignoring the canonical field.

**Issue 2: Self-Conflict in Room Evaluation**

When Client B changed their date, `evaluate_room_statuses` was called to check room availability.
However, it didn't exclude Client B's own event from the check, which caused incorrect status
detection when Client B's own "Lead" status was on a different date than the target.

### Complete Fix Applied

1. `room_status_checker.py` - Now accepts `exclude_event_id` parameter and checks both status fields:
   ```python
   def room_status_on_date(db, date, room, *, exclude_event_id=None):
       # Skip the current client's event to prevent self-conflict
       if exclude_event_id and event.get("event_id") == exclude_event_id:
           continue
       # Use canonical event["status"], fall back to event_data["Status"]
       status = event.get("status") or data.get("Status") or ""
   ```

2. `evaluation.py` - Now passes `exclude_event_id` through to `room_status_on_date`

3. `step3_handler.py` - Now passes `state.event_id` when evaluating room statuses:
   ```python
   room_statuses = evaluate_room_statuses(
       state.db, chosen_date, exclude_event_id=state.event_id
   )
   ```

4. `services/availability.py` - Same dual-field pattern applied
5. `workflows/io/database.py` - Added sync in `update_event_metadata` to keep both fields updated

## Environment

- Hybrid providers: I:ope / E:gem / V:ope
- Backend: dev server (port 8000)
- Frontend: Next dev server (port 3000)

## Screenshot

`/Users/nico/PycharmProjects/OpenEvent-AI/.playwright-mcp/e2e_room_conflict_double_booking_bug.png`

## Fix Applied

**Priority:** HIGH - Critical business logic bug - **NOW FIXED**

### Changes Made:
1. `room_status_checker.py` - Added `exclude_event_id` parameter, checks canonical status first
2. `evaluation.py` - Passes `exclude_event_id` to `room_status_on_date`
3. `step3_handler.py` - Passes `state.event_id` to `evaluate_room_statuses`
4. `services/availability.py` - Updated with same dual-field pattern
5. `update_event_metadata` - Syncs status to `event_data["Status"]` for backward compatibility
6. **`post_offer.py`** - Updated `_ensure_status` to sync to both `event["status"]` (canonical) AND `event_data["Status"]` (legacy)
7. **`step7_handler.py`** - Added status update to "Confirmed" in `_prepare_confirmation` when deposit is paid

### Root Cause (Final):
The status wasn't being set to "Confirmed" at all! When the deposit was paid:
- `deposit_info["deposit_paid"]` was set to `True` ✓
- But `event["status"]` and `event_data["Status"]` remained "Lead"
- The conflict checker looked for "Confirmed" status but never found it

### Test Coverage:
- `tests/flow/test_room_conflict.py` - 30 tests pass (26 original + 4 new for exclude_event_id)
- `tests/characterization/` - 28 tests pass
- New tests: `TestCrossClientConflictDetection` class covers all edge cases
- **E2E verified**: Client 1 confirms Room B on Feb 15 → Client 2 tries to change to Feb 15 → Room B shown as unavailable ✓
