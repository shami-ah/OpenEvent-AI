# E2E Scenario: Smart Shortcut with Date Without Year

**Date:** 2026-01-13
**Variant:** Smart shortcut flow + date inference (no year specified) + deposit + site visit
**Status:** PASSED

---

## Test Summary

This test verifies the **smart shortcut flow** when the client provides room, date (without year), and capacity in a single message. Key aspects tested:

1. **Date without year** - "March 25" correctly inferred as 25.03.2026
2. **Smart shortcut activation** - Bypasses Steps 2-3, goes directly to Step 4 offer
3. **Full deposit flow** - Deposit prompt → payment → continuation
4. **Site visit message** - Step 7 generates proper site visit offer after HIL approval

---

## Conversation Sequence

### Message 1: Client Initial Request
**Sender:** Client
**Text:**
```
Hello, I want to book Room B for March 25 for 20 people. My email is e2e-no-year@example.com
```

**Expected Behavior:** System should:
- Parse "March 25" as 25.03.2026 (infer current year)
- Trigger smart shortcut (room + date + capacity provided)
- Skip directly to Step 4 offer

---

### Message 2: Shami Offer Response
**Sender:** Shami (via smart shortcut to Step 4)
**Text:**
```
Here is your offer for Room B, which is suitable for 20 participants.

Let me know if you have any questions or need further details!

Offer draft for 25.03.2026 · Room B

Client: e2e-no-year@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

No optional products selected yet.

---

**Total: CHF 750.00**

**Deposit to reserve: CHF 225.00** (required before confirmation)

## Deposit due by: 23 January 2026

[View Catering information]

Menu options you can add:
- Seasonal Garden Trio · CHF 92.00 per event
- Alpine Roots Degustation · CHF 105.00 per event
- Lakeview Signature Journey · CHF 118.00 per event

Please review and approve to confirm.
```

**Key Verifications:**
- ✅ Date correctly shown as 25.03.2026 (year inferred)
- ✅ Room B at CHF 750.00
- ✅ Deposit amount: CHF 225.00 (30% of total)
- ✅ Deposit deadline: 10 days from today

---

### Message 3: Client Acceptance with Billing
**Sender:** Client
**Text:**
```
I accept this offer. My billing address is: NoYear AG, Testweg 10, 8000 Zurich, Switzerland
```

**Expected Behavior:** System should:
- Detect offer acceptance
- Capture billing address
- Show deposit prompt (deposit not yet paid)

---

### Message 4: Shami Deposit Request
**Sender:** Shami
**Text:**
```
Thank you for wanting to confirm! Before I can proceed with your booking, please complete the deposit payment of CHF 225.00. Once the deposit is received, I'll finalize your booking. You can pay the deposit using the payment option shown in the offer.
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
- Contact: Client (GUI)
- Email: e2e-no-year@example.com
- Date: 25.03.2026
- Room: Room B
- Billing: NoYear AG, Testweg 10, 8000 Zurich, Switzerland
- Deposit: CHF 225.00 ✅ Paid

**Draft Message:**
```
We're thrilled to confirm your booking for **Room B** on **25.03.2026**. Your deposit of CHF 225 has been received. Would you like to schedule a site visit before we finalize the details?
```

**Action:** Click "✅ Approve & Send"

---

### Message 5: Shami Site Visit Offer
**Sender:** Shami
**Text:**
```
We're thrilled to confirm your booking for Room B on 25.03.2026. Your deposit of CHF 225 has been received.

Would you like to schedule a site visit before we finalize the details?
```

**Key Verifications:**
- ✅ Booking confirmation for correct room and date
- ✅ Deposit receipt acknowledged
- ✅ Site visit option offered
- ✅ No fallback/generic messages

---

## Actions Sequence

| # | Action | Actor | Result |
|---|--------|-------|--------|
| 1 | Send initial booking request | Client | Smart shortcut triggered |
| 2 | Offer automatically generated | System | Step 4 offer displayed |
| 3 | Accept offer with billing address | Client | Billing captured, deposit prompt shown |
| 4 | Click "Pay Deposit" button | User | Deposit marked as paid |
| 5 | Accept deposit dialog | User | HIL task created for Step 7 |
| 6 | Click "Approve & Send" on HIL task | Manager | Site visit message sent |

---

## Key Verifications

| Verification | Expected | Actual | Status |
|--------------|----------|--------|--------|
| Date inference | 25.03.2026 | 25.03.2026 | ✅ PASS |
| Smart shortcut activation | Yes | Yes | ✅ PASS |
| Offer total | CHF 750.00 | CHF 750.00 | ✅ PASS |
| Deposit amount (30%) | CHF 225.00 | CHF 225.00 | ✅ PASS |
| Deposit prompt appears | Yes | Yes | ✅ PASS |
| Pay Deposit button works | Yes | Yes | ✅ PASS |
| HIL task created | Yes | Yes | ✅ PASS |
| Site visit message generated | Yes | Yes | ✅ PASS |
| No fallback messages | None | None | ✅ PASS |

---

## Files Exercised

| File | Purpose |
|------|---------|
| `workflows/steps/step1_intake/trigger/step1_handler.py` | Initial intake and date parsing |
| `workflows/steps/step4_offer/trigger/step4_handler.py` | Smart shortcut and offer generation |
| `workflows/steps/step5_negotiation/trigger/step5_handler.py` | Acceptance detection and billing capture |
| `workflows/runtime/hil_tasks.py` | HIL task creation and approval |
| `workflows/common/confirmation_gate.py` | Gate check for billing/deposit |
| `workflows/steps/step7_confirmation/trigger/process.py` | Site visit message generation |

---

## Distinguishing Characteristics

This variant tests:
1. **Date inference** - "March 25" without year → correctly inferred as 2026
2. **Smart shortcut** - Room + date + capacity triggers direct offer
3. **Deposit flow** - Full deposit prompt → payment → continuation
4. **Site visit offer** - Step 7 generates proper site visit message after deposit

**Differs from standard flow by:**
- Testing date parsing edge case (missing year)
- Validating smart shortcut bypass of Steps 2-3
- Full deposit payment integration

---

## Notes

- Global deposit config required in `events_team-shami.json`: 30% deposit, 10 days deadline
- `offer_accepted = True` flag critical for confirmation gate to trigger
- Smart shortcut requires: room specified + date parseable + capacity provided
