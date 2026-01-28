# E2E Test: Site Visit Detour with Scheduled Acknowledgment

**Date:** 2026-01-14
**Variant:** Site visit with blocked date detour + final message acknowledges scheduled visit
**Status:** PASSED

## Test Summary

This test verifies:
1. Site visit flow starts early in the workflow (at intake)
2. **Site visit detour**: Client requests blocked date (event day) → system rejects → offers alternatives
3. Client selects valid alternative date → site visit confirmed
4. Normal workflow continues: Room selection → Offer → Accept → Billing → Deposit
5. **Critical fix verification**: Final confirmation message acknowledges the already-scheduled site visit instead of asking "Would you like to schedule a site visit?"

## Conversation Sequence

### Message 1: Client Inquiry (with site visit request)
**From:** Client
**Content:**
```
Subject: Private Dinner Inquiry

Hi,

I'm planning a private dinner for 20 guests on August 20th, 2026. We're interested in Room A for the evening.

Before we proceed, I'd like to arrange a site visit to see the venue.

Best regards,
Sarah Mitchell
sarah.e2e-sitevisit-detour@example.com
```

### Message 2: Shami offers site visit dates
**From:** Shami
**Content:**
```
I'm glad to help arrange a site visit for you. Here are the available dates and time slots:

**13.08.2026**: 10:00, 14:00, 16:00
**14.08.2026**: 10:00, 14:00, 16:00
**17.08.2026**: 10:00, 14:00, 16:00

Please let me know which date and time works best for you, for example, 'August 13th at 14:00'.
```

**Key verification:** August 20th (event day) is NOT offered as a site visit date.

### Message 3: Client requests blocked date (DETOUR TRIGGER)
**From:** Client
**Content:**
```
I'd prefer to visit on August 20th around 10am if possible.
```

### Message 4: Shami rejects blocked date + offers alternatives
**From:** Shami
**Content:**
```
Unfortunately, **20.08.2026** is already booked for an event, so site visits won't be possible on that date.

However, I can offer you some alternative dates: **13.08.2026**, **14.08.2026**, and **17.08.2026**.

Which of these dates works best for you? Once you choose a date, I can provide the available time slots.
```

**Key verification:** Site visit detour works - system correctly rejects event day and offers alternatives.

### Message 5: Client selects valid date
**From:** Client
**Content:**
```
August 13th at 10:00 works for me.
```

### Message 6: Site visit confirmed
**From:** Shami
**Content:**
```
Your site visit is confirmed for **13.08.2026** at 10:00. We look forward to welcoming you and showcasing our venue!
```

### Message 7: Client proceeds with room booking
**From:** Client
**Content:**
```
Great, thanks! Now let's proceed with booking Room A for the dinner.
```

### Message 8: Offer generated
**From:** Shami
**Content:**
```
Offer

Here is your offer for **Room A**, which is perfect for your gathering of **20 participants**.

Offer draft for **20.08.2026** · **Room A**
Client: Sarah Mitchell · sarah.e2e-sitevisit-detour@example.com
Billing address: Not Specified

**Room booking**
- **Room A** · **CHF 500.00**

No optional products selected yet.

---
**Total: CHF 500.00**
**Deposit to reserve: CHF 150.00** (required before confirmation)
**Deposit due by:** 10 August 2026

[Menu options listed...]

Please review and approve to confirm.
```

### Message 9: Client accepts with billing
**From:** Client
**Content:**
```
I accept this offer. My billing address is: Sarah Mitchell, Bahnhofstrasse 45, 8001 Zurich, Switzerland
```

### Message 10: Deposit request
**From:** Shami
**Content:**
```
Thank you for wanting to confirm! Before I can proceed with your booking, please complete the deposit payment of **CHF 150.00**. Once the deposit is received, I'll finalize your booking.
```

### Action: Pay Deposit Button Clicked
**UI Action:** Client clicks "Pay Deposit" button
**Result:** Dialog "Deposit of CHF 150.00 marked as paid. You can now proceed with the confirmation."

### Message 11: Final confirmation (HIL approved)
**From:** Shami
**Content:**
```
We're thrilled to confirm your booking for **Room A** on **20.08.2026**. Your deposit of CHF 150 has been successfully received.

Your site visit is scheduled for **13.08.2026** at 10:00. We'll finalize all the details as we get closer to your event date.

---
Step: 7 Event Confirmation · Next: Finalize booking · State: Awaiting Client
```

**CRITICAL VERIFICATION:** The message says "Your site visit is scheduled for **13.08.2026** at 10:00" instead of "Would you like to schedule a site visit?"

## Actions Sequence

| Step | Action | Result |
|------|--------|--------|
| 1 | Send initial inquiry | Site visit dates offered (excluding event day) |
| 2 | Request blocked date (Aug 20) | **DETOUR**: Rejected with alternatives |
| 3 | Select Aug 13 at 10:00 | Site visit confirmed |
| 4 | Request Room A booking | Offer generated |
| 5 | Accept with billing address | Deposit request shown |
| 6 | Click "Pay Deposit" | Deposit marked as paid |
| 7 | HIL Approve | Confirmation sent with site visit acknowledgment |

## Key Verifications

1. **Event day blocking**: August 20th (event day) was correctly excluded from site visit options
2. **Site visit detour**: When client requested Aug 20th, system rejected and offered alternatives
3. **Site visit confirmation**: Aug 13 at 10:00 was confirmed and stored in `site_visit_state`
4. **Final message fix**: Instead of asking "Would you like to schedule a site visit?", the system shows "Your site visit is scheduled for 13.08.2026 at 10:00"

## Files Involved

- `workflows/steps/step7_confirmation/trigger/step7_handler.py` - `_prepare_confirmation()` now checks `is_site_visit_scheduled()`
- `workflows/steps/step7_confirmation/trigger/site_visit.py` - `handle_site_visit()` now checks for already-scheduled visits
- `workflows/steps/step4_offer/trigger/step4_handler.py` - `_auto_confirm_without_hil()` checks site visit status
- `workflows/common/site_visit_handler.py` - Handles site visit detour (blocked date → alternatives)
- `workflows/common/site_visit_state.py` - `is_site_visit_scheduled()` helper function

## Distinguishing Characteristics

This test variant is unique because it:
1. Tests site visit initiated EARLY (at intake, before room selection)
2. Tests site visit DETOUR (blocked date rejection)
3. Verifies the FIX where final confirmation acknowledges scheduled site visit instead of prompting for one

## Screenshot

See: `.playwright-mcp/e2e-site-visit-detour-complete.png`
