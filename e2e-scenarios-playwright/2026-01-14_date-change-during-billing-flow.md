# E2E Test: Date Change During Billing Flow

**Date:** 2026-01-14
**Variant Type:** Date change detour during billing capture
**Status:** PASSED

## Test Summary

This test verifies that when a client requests a date change AFTER accepting an offer (during billing capture flow), the system correctly:
1. Clears the billing flow state (`awaiting_billing_for_accept`, `offer_accepted`)
2. Triggers a detour to Step 2 (date re-confirmation)
3. Proceeds through Step 3 (room availability check)
4. Generates a NEW offer (Step 4) with the updated date

## Conversation Sequence

### 1. Initial Inquiry (Client → Shami)
```
Subject: Private Dinner Party

Hi,

I am looking to host a private dinner party for 25 guests on June 14, 2026.
Could you please let me know if Room B is available?

Best regards,
Emma
test-detour-e2e@example.com
```

### 2. Offer Response (Shami → Client)
- HIL Task: `offer message` at Step 4
- Manager Action: **Approve & Send**
- Offer details:
  - Date: **14.06.2026**
  - Room: Room B
  - Total: CHF 750.00
  - Deposit: CHF 225.00

### 3. Offer Acceptance (Client → Shami)
```
I accept the offer, thank you!
```

### 4. Billing Request (Shami → Client)
```
Thanks for confirming. I need the billing address before I can send this for approval.
Before I finalise, could you share the street address, postal code, and city?
Example: "Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland".
As soon as I have it, I'll forward the offer automatically.
```
- Pay Deposit button appears

### 5. Date Change Request (Client → Shami)
```
Actually I need to change the date to June 25, 2026
```

### 6. NEW Offer (Shami → Client)
- HIL Task: `offer message` at Step 4 (regenerated)
- Manager Action: **Approve & Send**
- Offer details:
  - Date: **25.06.2026** (NEW DATE!)
  - Room: Room B
  - Total: CHF 750.00
  - Deposit: CHF 225.00

## Actions Sequence

| Step | Actor | Action | Result |
|------|-------|--------|--------|
| 1 | Client | Send inquiry | Event created, Step 1 |
| 2 | System | Process inquiry | Auto-advanced to Step 4 (offer) |
| 3 | Manager | Approve offer | Offer sent to client |
| 4 | Client | Accept offer | Billing flow started |
| 5 | Client | Request date change | **Detour triggered** |
| 6 | System | Clear billing flags | `awaiting_billing_for_accept=False`, `offer_accepted=False` |
| 7 | System | Route to Step 2 | Date re-confirmation |
| 8 | System | Auto-confirm date | Extracted June 25, 2026 |
| 9 | System | Check room availability | Room B still available |
| 10 | System | Generate new offer | Step 4 with new date |
| 11 | Manager | Approve new offer | New offer sent to client |

## Key Verifications

1. **Date Change Detection**: System correctly detected date change intent despite being in billing flow
2. **Billing Flow Cleared**: `awaiting_billing_for_accept` and `offer_accepted` both set to `False`
3. **Detour Routing**: System routed through Step 2 → Step 3 → Step 4
4. **New Offer Generated**: Offer shows new date (25.06.2026) instead of original (14.06.2026)
5. **No Fallback Messages**: All responses were workflow-generated, no generic fallbacks

## Files Involved

- `workflows/steps/step1_intake/trigger/step1_handler.py` - Date change detection and billing flow clearing
- `workflows/runtime/pre_route.py` - `correct_billing_flow_step()` now respects cleared flags
- `workflows/change_propagation.py` - `detect_change_type_enhanced()` and `route_change_on_updated_variable()`
- `workflows/steps/step5_negotiation/trigger/step5_handler.py` - `_looks_like_date_change()` heuristic

## Distinguishing Characteristics

This variant tests the critical edge case where a client changes their mind about the date AFTER accepting an offer but BEFORE providing billing information. The fix ensures:

1. The billing flow is properly interrupted (not just paused)
2. A completely new offer is generated with the new date
3. The `correct_billing_flow_step()` function doesn't force the step back to 5

## Bug Reference

This test validates the fix for the issue where `correct_billing_flow_step()` was overriding detour routing during billing flow. The fix (in step1_handler.py lines 1258-1268) clears the billing flow flags when a date change is detected.

## Screenshot

See: `.playwright-mcp/e2e-date-change-detour-success.png`
