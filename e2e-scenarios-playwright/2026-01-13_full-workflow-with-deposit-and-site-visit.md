# E2E Test: Full Workflow with Deposit and Site Visit

**Date:** 2026-01-13
**Variant Type:** Full workflow with deposit requirement, billing capture, and site visit subflow
**Status:** ✅ PASSED

## Test Summary

This test verifies the complete happy-path workflow from initial inquiry through to site visit offering, including:
- Step 1: Intake with date and capacity
- Step 3: Room availability and selection
- Step 4: Offer creation with deposit requirement
- Step 5: Offer acceptance with billing capture
- Step 7: Confirmation with deposit payment and site visit

## Conversation Sequence

### 1. Initial Inquiry (Client → System)
```
Hi, I would like to book a room for **30 people** on February 14, 2026.
```

### 2. Room Availability Response (Shami → Client)
```
Availability overview

For your event on **14.02.2026** with **30 guests**, I recommend **Room A** because it
accommodates up to **40 guests**. Alternatives: **Room B** (capacity 60); **Room C** (capacity 80).

Would you like to add catering? Our Classic Apéro (**CHF 18.00**/person) and Coffee & Tea Bar
(**CHF 7.50**/person) are popular choices.

[View all available rooms](link)

Let me know which room you'd prefer and I'll prepare the offer.
```

### 3. Room Selection (Client → System)
```
**Room A** please
```

### 4. Offer Presentation (Shami → Client)
**⚡ Action Required: HIL Approval for Offer**

```
Here is your offer for **Room A**, accommodating **30 participants**.

Let me know if you have any questions or need further details!

Offer draft for **14.02.2026** · **Room A**
Client: unknown@example.com
Billing address: Not Specified

**Room booking**
- **Room A** · **CHF 500.00**

No optional products selected yet.

---
**Total:** **CHF 500.00**
**Deposit to reserve:** **CHF 150.00** (required before confirmation)
**Deposit due by:** 23 January 2026

[View Catering information](link)

Menu options you can add:
- Seasonal Garden Trio · **CHF 92.00** per event
- Alpine Roots Degustation · **CHF 105.00** per event
- Lakeview Signature Journey · **CHF 118.00** per event

Please review and approve to confirm.
```

**Manager Action:** ✅ Approve & Send

### 5. Offer Acceptance (Client → System)
```
thats fine
```

### 6. Billing Request (Shami → Client)
```
Thanks for confirming. I need the billing address before I can send this for approval.
Before I finalise, could you share the street address, postal code, and city?
Example: "Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland".
As soon as I have it, I'll forward the offer automatically.
```

### 7. Billing Address Provided (Client → System)
```
Test Company, Bahnhofstrasse 1, 8001 Zurich, Switzerland
```

### 8. Deposit Reminder (Shami → Client)
```
Thank you for providing your billing details! Before I can proceed with your booking,
please complete the deposit payment of **CHF 150.00**. Once the deposit is received,
I'll finalize your booking.
```

### 9. Deposit Payment
**⚡ Action Required: Pay Deposit Button Click**

**User Action:** Click "Pay Deposit" button → Confirm dialog

### 10. Step 7 HIL Confirmation Task
**⚡ Action Required: HIL Approval for Confirmation**

HIL Task shows:
- Contact: Client (GUI)
- Email: unknown@example.com
- Date: 14.02.2026
- Room: Room A
- Billing: Test Company, Bahnhofstrasse 1, 8001 Zurich, Switzerland
- Deposit: CHF 150.00 ✅ Paid

Draft Message:
```
We're thrilled to confirm your booking for **Room A** on **14.02.2026**.
Your deposit of CHF 150 has been successfully received.
Would you like to schedule a site visit before we finalize the details?
Let me know what works for you!
```

**Manager Action:** ✅ Approve & Send

### 11. Confirmation with Site Visit Offer (Shami → Client)
```
We're thrilled to confirm your booking for **Room A** on **14.02.2026**.
Your deposit of CHF 150 has been successfully received.

Would you like to schedule a site visit before we finalize the details?
Let me know what works for you!
```

### 12. Site Visit Request (Client → System)
```
yes
```

### 13. Site Visit Time Slots (Shami → Client)
```
Availability overview

Date options

I have a Tuesday available in January 2026: **13.01.2026** from 18:00 to 22:00.

Please let me know if this date works for you, and I will check room availability.
```

## Actions Sequence

| # | Actor | Action | Result |
|---|-------|--------|--------|
| 1 | Client | Send initial inquiry | Step 1 processes, moves to Step 3 |
| 2 | Client | Select "Room A please" | Step 4 offer created |
| 3 | Manager | Approve offer HIL task | Offer sent to client |
| 4 | Client | Accept with "thats fine" | Billing capture triggered |
| 5 | Client | Provide billing address | Deposit reminder shown |
| 6 | Client | Click "Pay Deposit" button | Step 7 HIL task created |
| 7 | Manager | Approve confirmation HIL task | Confirmation with site visit offer sent |
| 8 | Client | Respond "yes" to site visit | Site visit time slots offered |

## Key Verifications

- ✅ No "final approval" language shown to client (UX fix verified)
- ✅ Billing address captured correctly
- ✅ Deposit payment triggers Step 7 HIL task
- ✅ Confirmation message asks about site visit
- ✅ Client "yes" triggers site visit time slots
- ✅ No fallback or generic messages

## Files Involved

- `workflows/steps/step1_intake/` - Initial inquiry processing
- `workflows/steps/step3_room_availability/` - Room availability
- `workflows/steps/step4_offer/` - Offer creation
- `workflows/steps/step5_negotiation/` - Offer acceptance, billing capture
- `workflows/steps/step7_confirmation/` - Confirmation and site visit
- `workflows/common/confirmation_gate.py` - Deposit and billing gate
- `workflows/runtime/hil_tasks.py` - HIL task processing

## Distinguishing Characteristics

This variant includes:
1. **Deposit requirement** - Deposit must be paid before confirmation
2. **Billing capture** - Billing address collected after offer acceptance
3. **Site visit subflow** - Client chooses to schedule site visit
4. **Full HIL cycle** - Two HIL approvals (offer + confirmation)
