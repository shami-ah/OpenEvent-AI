# E2E Scenario: Date Change Detour During Billing Flow with Deposit Recalculation

**Date:** 2026-01-14
**Variant:** Date change during billing capture with deposit due date recalculation
**Status:** PASSED ✅

## Test Summary

This test verifies that:
1. Date change detection works correctly when client is in billing capture mode
2. The workflow correctly detours through Step 2 → Step 3 → Step 4 to generate a new offer
3. Deposit due date is recalculated based on the NEW event date (event_date - 10 days)
4. Flow continues correctly to Step 7 site visit after deposit payment

## Conversation Sequence

### 1. Initial Inquiry
**Client:**
```
Subject: Private Dinner

Hi,
I'd like to book Room B for 25 guests on June 14, 2026.

Best, Test
test-deposit-verify@example.com
```

### 2. First Offer (HIL Approved)
**Shami:**
```
Here is your offer for Room B, which is suitable for 25 participants.

Offer draft for 14.06.2026 · Room B
Client: Test · test-deposit-verify@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

---
**Total: CHF 750.00**
**Deposit to reserve: CHF 225.00** (required before confirmation)
**Deposit due by: 04 June 2026**  ← Original due date (June 14 - 10 = June 4)
```

### 3. Client Accepts
**Client:**
```
I accept the offer!
```

### 4. Billing Capture Request
**Shami:**
```
Thanks for confirming. I need the billing address before I can send this for approval.
Before I finalise, could you share the street address, postal code, and city?
Example: "Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland".
As soon as I have it, I'll forward the offer automatically.
```

### 5. Date Change Request (Triggers Detour)
**Client:**
```
Actually, I need to change the date to June 25, 2026
```

### 6. New Offer Generated (HIL Approved)
**Shami:**
```
Here's your offer for Room B, which is ideal for your gathering of 25 participants.

Offer draft for 25.06.2026 · Room B  ← NEW DATE
Client: Test · test-deposit-verify@example.com
Billing address: Not Specified

**Room booking**
- Room B · CHF 750.00

---
**Total: CHF 750.00**
**Deposit to reserve: CHF 225.00** (required before confirmation)
**Deposit due by: 15 June 2026**  ← RECALCULATED (June 25 - 10 = June 15)
```

### 7. Client Accepts New Offer
**Client:**
```
I accept the offer!
```

### 8. Billing Capture Request (Again)
**Shami:**
```
Thanks for confirming. I need the billing address before I can send this for approval...
```

### 9. Client Provides Billing
**Client:**
```
Test Company, Teststrasse 123, 8001 Zurich, Switzerland
```

### 10. Billing Captured + Deposit Request
**Shami:**
```
I've updated your event to 25.06.2026. Thank you for providing your billing details!
Before I can proceed with your booking, please complete the deposit payment of CHF 225.00.
Once the deposit is received, I'll finalize your booking.
```

### 11. Deposit Paid (Button Click)
*Client clicks "Pay Deposit" button*

### 12. Site Visit Message (HIL Approved)
**Shami:**
```
We're thrilled to confirm your booking for Room B on 25.06.2026.
Your deposit of CHF 225 has been successfully received.

Would you like to schedule a site visit before we finalize the details?
```

## Actions Sequence

| # | Action | Actor | Result |
|---|--------|-------|--------|
| 1 | Send initial inquiry | Client | Event created at Step 1 |
| 2 | Approve offer | Manager (HIL) | Offer sent to client |
| 3 | Accept offer | Client | Billing capture mode entered |
| 4 | Request date change | Client | **Detour triggered** |
| 5 | Approve new offer | Manager (HIL) | New offer with updated date sent |
| 6 | Accept new offer | Client | Billing capture mode re-entered |
| 7 | Provide billing | Client | Billing captured |
| 8 | Pay deposit | Client (button) | Deposit marked as paid |
| 9 | Approve confirmation | Manager (HIL) | Site visit message sent |

## Key Verifications

- [x] Date change detected during billing capture mode
- [x] Billing flow state cleared before detour (`awaiting_billing_for_accept=False`)
- [x] New offer generated with correct date (25.06.2026)
- [x] **Deposit due date recalculated: June 4 → June 15** (formula: event_date - 10 days)
- [x] Billing address captured after accepting new offer
- [x] Deposit payment flow works correctly
- [x] Step 7 site visit message appears

## Files Involved

- `workflows/steps/step1_intake/trigger/step1_handler.py` - Date change detection + billing state clearing
- `workflows/steps/step2_date_confirmation/trigger/step2_handler.py` - Date confirmation
- `workflows/steps/step3_room_availability/trigger/step3_handler.py` - Room re-evaluation
- `workflows/steps/step4_offer/trigger/step4_handler.py` - New offer generation
- `workflows/steps/step5_negotiation/trigger/step5_handler.py` - Billing capture
- `workflows/steps/step7_confirmation/trigger/step7_handler.py` - Site visit message
- `workflows/common/pricing.py` - Deposit due date calculation

## Distinguishing Characteristics

1. **Date change during billing flow** - Tests BUG-025 fix
2. **Deposit recalculation** - Verifies deposit due date uses `event_date - deadline_days`
3. **Full detour cycle** - Step 5 (billing) → Step 2 → Step 3 → Step 4 → Step 5 → Step 7

## Related Bug Fixes

- BUG-023: Billing capture mode interference with detection
- BUG-024: Date change acknowledgment missing
- BUG-025: Date change detour not triggering during billing flow
- Deposit due date formula fix: Changed from `min(today + X, event - Y)` to `event_date - deadline_days`

## Screenshot

`.playwright-mcp/.playwright-mcp/e2e-date-change-detour-to-site-visit.png`
