# E2E Test: Event-Relative Deposit Due Date

**Date:** 2026-01-14
**Variant Type:** Close event date with deposit due date calculation
**Status:** PASSED

## Test Summary

This test verifies that when an event is scheduled close to today, the deposit due date is calculated relative to the event date (not just "today + X days"). This prevents the deposit due date from being AFTER the event.

## Key Calculation

```
due_date = min(today + deadline_days, event_date - min_days_before_event)
```

With minimum enforcement of 1 day from today.

## Conversation Sequence

### 1. Initial Inquiry (Client → Shami)
```
Subject: Urgent Booking

Hi,

I need to book Room B for 25 guests on January 21, 2026 (next week).

Thanks,
Emma
test-jan21@example.com
```

### 2. Offer Response (Shami → Client)
- HIL Task: `offer message` at Step 4
- Manager Action: **Approve & Send**
- Offer details:
  - Date: **21.01.2026** (only 7 days from today!)
  - Room: Room B
  - Total: CHF 750.00
  - Deposit: CHF 225.00
  - **Deposit due by: 15 January 2026** ✅ (NOT 24 January which would be AFTER the event!)

### 3. Offer Acceptance (Client → Shami)
```
I accept the offer!
```

### 4. Billing Request (Shami → Client)
```
Thanks for confirming. I need the billing address before I can send this for approval...
```
- Pay Deposit button appears

### 5. Billing Address (Client → Shami)
```
My billing address is: Emma's Events, Bahnhofstrasse 10, 8001 Zurich, Switzerland
```

### 6. Deposit Payment
- Client clicks "Pay Deposit" button
- Alert: "Deposit of CHF 225.00 marked as paid"

### 7. Site Visit Prompt (Shami → Client)
- HIL Task: `confirmation message` at Step 7
- Manager Action: **Approve & Send**
```
We're thrilled to confirm your booking for Room B on 21.01.2026. Your deposit of CHF 225 has been successfully received.

Would you like to schedule a site visit before we finalize the details?
```

## Deposit Due Date Calculation

| Scenario | Today | Event | Option 1 (today + 10) | Option 2 (event - 14) | Result |
|----------|-------|-------|----------------------|----------------------|--------|
| Close event | Jan 14 | Jan 21 | Jan 24 | Jan 7 (past) | Jan 15* |
| Far event | Jan 14 | Jun 14 | Jan 24 | May 31 | Jan 24 |

*Minimum 1 day from today enforced

## Key Verifications

1. **Deposit Due Date NOT After Event**: For Jan 21 event, due date is Jan 15 (before event), not Jan 24 (after event)
2. **Date Format Parsing**: Code correctly parses DD.MM.YYYY format (stored) and YYYY-MM-DD (ISO)
3. **Full Flow Works**: Inquiry → Offer → Accept → Billing → Deposit → Site Visit ✅
4. **Room Availability Checked**: Step 3 verifies room is available on the requested date

## Files Involved

- `workflows/common/pricing.py` - `calculate_deposit_due_date()`, `build_deposit_info()`
- `workflows/steps/step4_offer/trigger/step4_handler.py` - Pass event date to deposit calculation

## Bug Fixed

**Date Format Parsing Bug:** The code was trying to parse dates with YYYY-MM-DD format, but dates are stored as DD.MM.YYYY. This caused the event_date to always be None, so the deposit due date was always calculated without considering the event date.

Fixed by trying multiple date formats:
```python
for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
    try:
        event_date_dt = datetime.strptime(chosen_date_str, fmt)
        break
    except (ValueError, TypeError):
        continue
```

## Screenshot

See: `.playwright-mcp/e2e-deposit-due-date-fix.png`
