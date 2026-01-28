# E2E Scenario: Detour Date Change (Room Still Available)

**Date:** 2026-01-13
**Variant:** Smart shortcut + date change detour + room still available + offer regen + deposit + site visit
**Status:** PASSED

---

## Test Summary

This test verifies that a **date change detour** from a smart shortcut offer:

1. **Triggers smart shortcut** on the initial message (room + date + capacity)
2. **Detours to Step 2** when the client changes only the date
3. **Rechecks the locked room** and fast-skips back to Step 4 when still available
4. **Regenerates the offer** with the new date (same room)
5. **Completes deposit + site visit flow** successfully

---

## Conversation Sequence

### Message 1: Client Initial Request
**Sender:** Client
**Text:**
```
Hi, I want to book Room B for May 7, 2026 from 10:00 to 16:00 for 25 people. My email is detour-smart-1@example.com
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

Client: detour-smart-1@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

No optional products selected yet.

---

**Total: CHF 750.00**

**Deposit to reserve: CHF 225.00** (required before confirmation)

**Deposit due by:** 23 January 2026
```

**Key Verifications:**
- ✅ Smart shortcut offer sent (no date/room follow-up questions)
- ✅ Date is 07.05.2026
- ✅ Room B and deposit details present

---

### Message 3: Client Date Change (Detour)
**Sender:** Client
**Text:**
```
Actually, can we move the date to May 15, 2026? Same room please.
```

**Expected Behavior:**
- Detour to Step 2 for date update
- Step 3 re-checks room availability on new date
- Room still available -> fast-skip back to Step 4
- Offer regenerated with new date

---

### Message 4: Shami Updated Offer
**Sender:** Shami
**Text:**
```
Offer draft for 15.05.2026 · Room B

Client: detour-smart-1@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

No optional products selected yet.

---

**Total: CHF 750.00**

**Deposit to reserve: CHF 225.00** (required before confirmation)

**Deposit due by:** 23 January 2026
```

**Key Verifications:**
- ✅ Offer date updated to 15.05.2026
- ✅ Room B retained (no room re-selection)
- ✅ Deposit recalculated and still required

---

### Message 5: Client Acceptance with Billing
**Sender:** Client
**Text:**
```
I accept this offer. Billing address: Detour Co, Teststrasse 1, 8000 Zurich, Switzerland.
```

---

### Message 6: Shami Deposit Request
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
- Email: detour-smart-1@example.com
- Date: 15.05.2026
- Room: Room B
- Billing: Detour Co, Teststrasse 1, 8000 Zurich, Switzerland
- Deposit: CHF 225.00 ✅ Paid

**Draft Message:**
```
We're thrilled to confirm your booking for Room B on 15.05.2026. Your deposit of CHF 225 has been successfully received. Would you like to schedule a site visit before we finalize the details?
```

**Action:** Click "✅ Approve & Send"

---

### Message 7: Shami Site Visit Offer
**Sender:** Shami
**Text:**
```
We're thrilled to confirm your booking for Room B on 15.05.2026. Your deposit of CHF 225 has been successfully received.

Would you like to schedule a site visit before we finalize the details?
```

**Key Verifications:**
- ✅ Booking confirmation for new date
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
| 4 | Approve & send updated offer | Manager | Offer regenerated for 15.05.2026 |
| 5 | Accept offer with billing | Client | Billing captured, deposit prompt shown |
| 6 | Click "Pay Deposit" | User | Deposit marked as paid |
| 7 | Approve & send Step 7 confirmation | Manager | Site visit message sent |

---

## Key Verifications

| Verification | Expected | Actual | Status |
|--------------|----------|--------|--------|
| Smart shortcut activation | Yes | Yes | ✅ PASS |
| Date detour triggers | Yes | Yes | ✅ PASS |
| Room still available | Yes | Yes (Room B) | ✅ PASS |
| Offer regenerated with new date | Yes | Yes | ✅ PASS |
| Deposit prompt appears | Yes | Yes | ✅ PASS |
| Pay Deposit works | Yes | Yes | ✅ PASS |
| HIL task created | Yes | Yes | ✅ PASS |
| Site visit message generated | Yes | Yes | ✅ PASS |

---

## Files Exercised

| File | Purpose |
|------|---------|
| `workflows/change_propagation.py` | Date change detection + detour routing |
| `workflows/steps/step2_date_confirmation/trigger/step2_handler.py` | Date detour confirmation path |
| `workflows/steps/step3_room_availability/trigger/step3_handler.py` | Room recheck + fast-skip logic |
| `workflows/steps/step4_offer/trigger/step4_handler.py` | Offer regeneration |
| `workflows/common/confirmation_gate.py` | Billing/deposit gate |
| `workflows/steps/step7_confirmation/trigger/process.py` | Site visit message |

---

## Distinguishing Characteristics

This variant tests:
1. **Smart shortcut** with full initial details (room + date + capacity)
2. **Date-only detour** that keeps the room lock
3. **Fast-skip back to Step 4** when the room is still available
4. **Offer regeneration** with updated date and unchanged room

---

## Notes

- Global deposit config set to 30% with 10-day deadline.
- Room availability fast-skip requires locked room to remain available on new date.
