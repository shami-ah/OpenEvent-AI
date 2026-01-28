# E2E Scenario: Hybrid Q&A + Date Detour + Second Offer + Site Visit

**Date:** 2026-01-21
**Variant:** Hybrid (I:ope / E:gem / V:ope) with date-change detour and second offer confirmation
**Status:** PASSED ✅

## Test Summary

This test verifies that:
1. Hybrid acceptance + Q&A works (acceptance progresses workflow and Q&A is answered).
2. Date-change detour triggers Step 2 suggestions and Step 3 room availability check.
3. Second offer is generated for the new date and can be accepted with billing address.
4. Deposit capture works and Step 7 site visit prompt appears.

## Conversation Sequence

### 1. Initial Inquiry
**Client:**
```
Hello, I'd like to book Room B for 50 guests on April 15, 2026. Ref 1301.
```

### 2. First Offer (Room B)
**Shami:**
```
Offer draft for 15.04.2026 · Room B
Deposit due by: 05 April 2026
```

### 3. Hybrid Acceptance + Q&A
**Client:**
```
Room B looks perfect. Do you offer catering services?
```

**Shami:**
```
Thank you for wanting to confirm! Before I can proceed, please complete the deposit payment...
[Answers catering options]
```

### 4. Date Change Request (Detour)
**Client:**
```
Actually, can we change the date to January 14, 2026 from 10:00 to 12:00 instead?
```

**Shami:**
```
Availability overview
The only available Wednesday in January 2026 is 21.01.2026 from 10:00 to 12:00.
```

### 5. Date + Room Confirmation (Same Message)
**Client:**
```
Yes, 21.01.2026 from 10:00 to 12:00 works. Please proceed with Room B.
```

**Shami:**
```
Offer draft for 21.01.2026 · Room B
Deposit due by: 22 January 2026
```

### 6. Accept Second Offer + Billing
**Client:**
```
We accept the updated offer. Billing address: Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland.
```

**Shami:**
```
Please complete the deposit payment of CHF 225.00...
```

### 7. Deposit Paid (Button)
*Client clicks "Pay Deposit"*

### 8. Site Visit Prompt
**Shami:**
```
We’re thrilled to move forward with your booking for Room B on 21.01.2026.
Would you like to arrange a site visit before we finalize everything?
```

## Key Verifications

- [x] Hybrid acceptance + Q&A works (acceptance advances workflow and Q&A answered).
- [x] Date-change detour triggered (Step 2 suggestions shown).
- [x] Step 3 room availability ran on the new date.
- [x] Second offer generated with updated date and deposit due date.
- [x] Detour smart shortcut works for date + room confirmation in one message.
- [x] Billing address captured after second offer acceptance.
- [x] Deposit payment flow works.
- [x] Site visit prompt appears after deposit payment.

## Resolution Note: Detour Smart Shortcut

**Status:** Resolved in this run. The combined date + room confirmation message led directly to the updated offer without re-running the availability overview.

## Environment

- Hybrid providers: I:ope / E:gem / V:ope
- Backend: dev server (port 8000)
- Frontend: Next dev server (port 3000)

## Files Involved

- `workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
- `workflows/steps/step3_room_availability/trigger/step3_handler.py`
- `workflows/steps/step4_offer/trigger/step4_handler.py`
- `workflows/steps/step5_negotiation/trigger/step5_handler.py`
- `workflows/steps/step7_confirmation/trigger/step7_handler.py`

## Screenshot

`/var/folders/l9/5h85_cxd4zjcjkjhwpqvpkz40000gn/T/playwright-mcp-output/1768994280526/e2e_hybrid_detour_second_offer_site_visit_fixed.png`
