# E2E Scenario: Detour Date Change (Room Unavailable -> Re-select Room)

**Date:** 2026-01-13
**Variant:** Smart shortcut + date change detour + room unavailable + room re-selection + offer regen + deposit + site visit
**Status:** PASSED

---

## Test Summary

This test verifies that a **date change detour** properly re-runs room availability when the locked room becomes unavailable on the new date:

1. **Smart shortcut** triggers the initial offer
2. **Date detour** routes back to Step 2 and Step 3
3. **Room availability** is re-run because the new date conflicts with an existing confirmed event
4. **Room selection** is required, then a new offer is generated
5. **Deposit + site visit flow** completes successfully

---

## Preconditions

- `events_database.json` contains a confirmed event for **Room B** on **12.05.2026**
  - Email: `fixture-room-b-20260512@example.com`
  - This fixture ensures Room B is unavailable on the new date.

---

## Conversation Sequence

### Message 1: Client Initial Request
**Sender:** Client
**Text:**
```
Hi, I'd like to book Room B for May 7, 2026 from 10:00 to 16:00 for 25 people. My email is detour-smart-2@example.com
```

**Expected Behavior:**
- Smart shortcut triggers (skip Steps 2-3)
- Step 4 offer drafted for 07.05.2026, Room B

---

### Message 2: Shami Offer Response
**Sender:** Shami (via smart shortcut to Step 4)
**Text:**
```
Offer draft for 07.05.2026 · Room B

Client: detour-smart-2@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

No optional products selected yet.

---

**Total: CHF 750.00**

**Deposit to reserve: CHF 225.00** (required before confirmation)

**Deposit due by:** 23 January 2026
```

---

### Message 3: Client Date Change (Detour)
**Sender:** Client
**Text:**
```
Can we change the date to May 12, 2026 instead?
```

**Expected Behavior:**
- Detour to Step 2 for date update
- Step 3 rechecks availability for Room B
- Room B unavailable -> provide room availability overview

---

### Message 4: Shami Room Availability Overview
**Sender:** Shami
**Text:**
```
Availability overview

For your event on 12.05.2026 with 25 guests, I recommend Room D. If you're considering alternatives, Room F has a capacity of 45, and Room A can hold 40 guests.

Let me know which room you'd prefer, and I'll prepare the offer.
```

**Key Verifications:**
- ✅ Room B not offered (blocked by confirmed fixture)
- ✅ Alternatives provided (Room D, Room F, Room A)

---

### Message 5: Client Room Selection
**Sender:** Client
**Text:**
```
Let's go with Room A.
```

---

### Message 6: Shami Updated Offer
**Sender:** Shami
**Text:**
```
Offer draft for 12.05.2026 · Room A

Client: detour-smart-2@example.com
Billing address: Not Specified

**Room booking**
- Room A · CHF 750.00

No optional products selected yet.

---

**Total: CHF 750.00**

**Deposit to reserve: CHF 225.00** (required before confirmation)

**Deposit due by:** 23 January 2026
```

**Key Verifications:**
- ✅ Offer regenerated with new date and new room
- ✅ Room A selected from availability overview

---

### Message 7: Client Acceptance with Billing
**Sender:** Client
**Text:**
```
I accept this offer. Billing address: Detour Two AG, Exampleweg 2, 8000 Zurich, Switzerland.
```

---

### Message 8: Shami Deposit Request
**Sender:** Shami
**Text:**
```
Thank you for wanting to confirm! Before I can proceed with your booking, please complete the deposit payment of CHF 225.00.
```

**Frontend State:**
- Deposit prompt visible: "💰 Deposit Required: CHF 225.00"
- "Pay Deposit" button displayed

---

### Action: Pay Deposit
**User Action:** Click "Pay Deposit" button
**Dialog:** "Deposit of CHF 225.00 marked as paid. You can now proceed with the confirmation."
**Result:** Dialog accepted

---

### HIL Task: Confirmation Message (Step 7)
**Task Type:** confirmation message
**Step:** 7
**Details:**
- Email: detour-smart-2@example.com
- Date: 12.05.2026
- Room: Room A
- Billing: Detour Two AG, Exampleweg 2, 8000 Zurich, Switzerland
- Deposit: CHF 225.00 ✅ Paid

**Draft Message:**
```
We're thrilled to confirm your booking for Room A on 12.05.2026. Your deposit of CHF 225 has been successfully received. Would you like to schedule a site visit before we finalize the details?
```

**Action:** Click "✅ Approve & Send"

---

### Message 9: Shami Site Visit Offer
**Sender:** Shami
**Text:**
```
We're thrilled to confirm your booking for Room A on 12.05.2026. Your deposit of CHF 225 has been successfully received.

Would you like to schedule a site visit before we finalize the details?
```

**Key Verifications:**
- ✅ Booking confirmation for new date and new room
- ✅ Deposit receipt acknowledged
- ✅ Site visit option offered
- ✅ No fallback/generic messages

---

## Actions Sequence

| # | Action | Actor | Result |
|---|--------|-------|--------|
| 1 | Send initial booking request | Client | Smart shortcut triggered |
| 2 | Approve & send initial offer | Manager | Offer delivered |
| 3 | Request date change | Client | Detour triggered |
| 4 | Availability overview | System | Room B unavailable, alternatives provided |
| 5 | Select Room A | Client | Room selection captured |
| 6 | Approve & send updated offer | Manager | Offer regenerated for Room A |
| 7 | Accept offer with billing | Client | Billing captured, deposit prompt shown |
| 8 | Click "Pay Deposit" | User | Deposit marked as paid |
| 9 | Approve & send Step 7 confirmation | Manager | Site visit message sent |

---

## Key Verifications

| Verification | Expected | Actual | Status |
|--------------|----------|--------|--------|
| Smart shortcut activation | Yes | Yes | ✅ PASS |
| Date detour triggers | Yes | Yes | ✅ PASS |
| Room B unavailable on new date | Yes | Yes | ✅ PASS |
| Room availability overview shown | Yes | Yes | ✅ PASS |
| Offer regenerated with new room | Yes | Yes (Room A) | ✅ PASS |
| Deposit prompt appears | Yes | Yes | ✅ PASS |
| Pay Deposit works | Yes | Yes | ✅ PASS |
| Site visit message generated | Yes | Yes | ✅ PASS |

---

## Files Exercised

| File | Purpose |
|------|---------|
| `workflows/change_propagation.py` | Date change detection + detour routing |
| `workflows/steps/step2_date_confirmation/trigger/step2_handler.py` | Date detour confirmation path |
| `workflows/steps/step3_room_availability/trigger/step3_handler.py` | Room recheck + room selection |
| `workflows/steps/step4_offer/trigger/step4_handler.py` | Offer regeneration |
| `workflows/common/confirmation_gate.py` | Billing/deposit gate |
| `workflows/steps/step7_confirmation/trigger/process.py` | Site visit message |

---

## Distinguishing Characteristics

This variant tests:
1. **Date-only detour** with a pre-existing room conflict
2. **Room availability re-run** when locked room is no longer available
3. **Room re-selection** before offer regeneration
4. **End-to-end confirmation** through deposit and site visit

---

## Notes

- Fixture event in `events_database.json` is required to force Room B unavailable on 12.05.2026.
- Global deposit config set to 30% with 10-day deadline.
