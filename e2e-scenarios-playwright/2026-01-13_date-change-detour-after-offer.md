# E2E Test: Date Change Detour After Offer Acceptance

**Date:** 2026-01-13
**Variant Type:** Date change (detour) triggered after offer acceptance and billing capture
**Status:** PASS (all bugs fixed and verified)

## Test Summary

This test verifies that a date change request after offer acceptance:
1. Correctly updates the event date (detour to Step 2)
2. Does NOT cause an infinite Step2 ↔ Step4 loop (BUG-020 fix)
3. Maintains workflow continuity

## Key Findings

### Verified Working (BUG-020 Fix)
- **Date was updated**: 05.03.2026 → 20.03.2026
- **No infinite loop**: The workflow processed the date change without getting stuck in a detour loop
- **Deposit UI timing**: Deposit card appeared only AFTER offer acceptance (BUG-022 fix verified)

### Issue Discovered and Fixed (BUG-023)
- **Billing capture interference**: When in billing capture mode, a date change message was incorrectly captured as billing address instead of triggering proper date change detection
- First message "Actually, I need to change the date to March 20, 2026 instead" was stored as billing
- Second message "Wait, I need to reschedule. Can we move the event to March 20, 2026?" correctly updated the date
- **FIX APPLIED**: Added `_looks_like_date_change()` guard in `step5_handler.py` that checks for date change intent before capturing billing
- **FIX VERIFIED**: Re-test on 2026-01-13 confirmed date change messages are now correctly detected (not captured as billing)

## Conversation Sequence

### 1. Initial Inquiry (Client → System)
```
Hi, I would like to book a room for 25 people on March 5, 2026. My email is detour-e2e-test@example.com
```

### 2. Room Availability Response (Shami → Client)
```
Availability overview

For your event on **05.03.2026** with **25 guests**, I recommend **Room A**.
It comfortably accommodates up to **40 guests**, making it a great fit for your needs.

As alternatives, you could consider **Room D**, which has a capacity of 26, or
**Room F**, which can hold up to **45 guests**.

Would you like to include catering? Our Classic Apéro is a popular choice at
**CHF 18.00 per person**, and the Coffee & Tea Bar is available for **CHF 7.50 per person**.

Let me know which room you'd prefer, and I'll prepare the offer.
```

### 3. Room Selection (Client → System)
```
Room A please
```

### 4. Offer Presentation (HIL Task Created)
**Manager Action:** ✅ Approve & Send

### 5. Offer Sent (Shami → Client)
```
Here's your offer for **Room A**, accommodating **25 participants**.

Offer draft for **05.03.2026** · **Room A**
...
**Total: CHF 500.00**
**Deposit to reserve: CHF 150.00** (required before confirmation)
**Deposit due by:** 23 January 2026
```

### 6. Offer Acceptance (Client → System)
```
That looks good, I accept the offer
```

### 7. Billing Request + Deposit UI Appears (Shami → Client)
```
Thanks for confirming. I need the billing address before I can send this for approval.
Before I finalise, could you share the street address, postal code, and city?
```
**UI State:** Deposit card with "Pay Deposit" button appeared (BUG-022 fix verified)

### 8. Billing Provided (Client → System)
```
Detour Test GmbH, Teststrasse 123, 8000 Zurich, Switzerland
```

### 9. First Date Change Attempt (Client → System)
```
Actually, I need to change the date to March 20, 2026 instead
```
**Result:** Message incorrectly captured as billing address (interference bug)

### 10. Second Date Change Request (Client → System)
```
Wait, I need to reschedule. Can we move the event to March 20, 2026?
```
**Result:** Date successfully updated to 20.03.2026 in HIL panel

## Actions Sequence

| # | Actor | Action | Result |
|---|-------|--------|--------|
| 1 | Client | Send initial inquiry | Step 1 processes, moves to Step 3 |
| 2 | Client | Select "Room A please" | Step 4 offer created, HIL task |
| 3 | Manager | Approve offer HIL task | Offer sent to client |
| 4 | Client | Accept with "That looks good, I accept" | Billing capture triggered, deposit UI appeared |
| 5 | Client | Provide billing address | Billing captured |
| 6 | Client | Request date change (first attempt) | **BUG:** Captured as billing instead |
| 7 | Client | Request date change (second attempt) | Date updated 05.03 → 20.03 successfully |

## Key Verifications

- ✅ **BUG-020 Fixed**: No infinite Step2 ↔ Step4 detour loop
- ✅ **BUG-022 Fixed**: Deposit UI only appears after offer acceptance
- ✅ Date change was detected and applied (20.03.2026)
- ✅ **BUG-023 Fixed**: Date change during billing capture mode is now correctly detected (verified 2026-01-13)

## Files Involved

- `workflows/change_propagation.py` - Date normalization and change detection (BUG-020 fix)
- `workflows/runtime/router.py` - Site visit keyword detection (BUG-021 fix)
- `api/routes/messages.py` - `offer_accepted` in deposit_info (BUG-022 fix)
- `api/routes/tasks.py` - `offer_accepted` in event_summary
- `atelier-ai-frontend/app/page.tsx` - Deposit UI gating on `offer_accepted`
- `workflows/steps/step5_negotiation/trigger/step5_handler.py` - Date change guard in billing capture (BUG-023 fix)

## Distinguishing Characteristics

This variant tests:
1. **Date change after offer acceptance** - Not before offer
2. **Detour loop prevention** - Core BUG-020 fix verification
3. **Billing flow interference** - Discovered new issue where billing capture mode can intercept date change messages

## Follow-up (BUG-023) - COMPLETED

~~Add guard in billing capture mode to detect date change intent BEFORE treating message as billing address. The date change detection should have higher priority than billing capture.~~

**Implemented 2026-01-13**: Added `_looks_like_date_change()` helper in `step5_handler.py` that checks for date change intent (verbs like "change", "reschedule", "move" + date keywords or patterns) before capturing message as billing address. Verified working via E2E test.
