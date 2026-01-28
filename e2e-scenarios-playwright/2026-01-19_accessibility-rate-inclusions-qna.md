# E2E Scenario: Accessibility & Rate Inclusions Q&A

**Date:** 2026-01-19
**Feature:** Q&A extraction for accessibility and rate inclusion questions
**Status:** PASSED

## Summary

This E2E test validates the new Q&A feature that properly answers questions about:
1. Room accessibility (wheelchair access, elevator, step-free entry, accessible bathrooms)
2. Rate inclusions (what's included in the room rate)

Previously, these questions returned generic room features instead of the specific information requested.

## Test Flow

### Step 1: Initial Inquiry
**Client:**
```
From: sarah.jones@techcorp.com
Subject: Training Room Booking Request

Hi,

I'd like to book a room for a corporate training session with 25 attendees on April 15, 2026.
We need a room with good facilities.

Thanks,
Sarah Jones
```

**System Response:** Room recommendations (Room A recommended, with alternatives Room D and Room F)

### Step 2: Accessibility & Rate Inclusions Q&A (NEW FEATURE)
**Client:**
```
Room A sounds good. But I have an important question - is Room A wheelchair accessible?
And what's included in the room rate?
```

**System Response:**
```
**Accessibility Information:**

Yes, Room A is fully accessible: wheelchair accessible, elevator access, step-free entry,
accessible bathroom on-site.

Ground floor access with wide doorways. Accessible bathroom on the same floor.

---

**What's Included:**

The Room A rate includes: WiFi, Basic AV equipment (projector, screen), Whiteboard and markers,
Water station, Climate control, Standard furniture setup.
```

### Step 3: Detour - Room Change
**Client:**
```
Actually, I'd like to change to Room B instead. Can you tell me about that room?
```

**System Response:** Room B details with features (capacity 60, parking, background music, screen and projector, WiFi, sound system, etc.)

### Step 4: Confirmation
**Client:**
```
Room B sounds perfect. Please proceed with Room B for April 15, 2026.
```

**System Response:** Offer generated with:
- Room B: CHF 750.00
- Deposit: CHF 225.00
- Deposit due by: 05 April 2026

## Implementation Details

### Files Modified

1. **`workflows/qna/router.py`**
   - Added `accessibility_inquiry` and `rate_inclusions` to `pure_qna_types` set
   - Added `_accessibility_response()` function to handle wheelchair/accessibility questions
   - Added `_rate_inclusions_response()` function to handle "what's included" questions
   - Added import for `load_room_static` from `services.qna_readonly`

2. **`workflows/qna/extraction.py`**
   - Updated `SYSTEM_PROMPT` with topic-specific guidance for accessibility and rate inclusion questions

3. **`workflows/qna/verbalizer.py`**
   - Updated `SYSTEM_PROMPT` with available data fields (accessibility, rate_inclusions, features, equipment, services)

4. **`services/qna_readonly.py`**
   - Fixed `load_room_static()` to look up room info by both `room_id` and `room_name` (was only looking up by room_id which didn't match the data keyed by name)

5. **`detection/intent/classifier.py`**
   - Already had `accessibility_inquiry` and `rate_inclusions` qna_types defined with appropriate keywords

### Data Source

Room accessibility and rate_inclusions data is stored in `data/rooms.json`:
```json
{
  "name": "Room A",
  "accessibility": {
    "wheelchair_accessible": true,
    "elevator_access": true,
    "accessible_bathroom": true,
    "step_free_entry": true,
    "notes": "Ground floor access with wide doorways. Accessible bathroom on the same floor."
  },
  "rate_inclusions": [
    "WiFi",
    "Basic AV equipment (projector, screen)",
    "Whiteboard and markers",
    "Water station",
    "Climate control",
    "Standard furniture setup"
  ]
}
```

## Test Results

| Step | Description | Result |
|------|-------------|--------|
| 1 | Initial inquiry | PASSED - Room recommendations shown |
| 2 | Accessibility Q&A | PASSED - Shows wheelchair access, elevator, step-free entry, accessible bathroom |
| 3 | Rate inclusions Q&A | PASSED - Lists WiFi, AV equipment, whiteboard, water station, climate control |
| 4 | Room change detour | PASSED - Successfully switched to Room B |
| 5 | Booking confirmation | PASSED - Offer generated with correct pricing |

## Verification Commands

```bash
# Run regression tests
pytest tests/regression/ -v --tb=short

# Run Q&A tests
pytest tests/ -v --tb=short -k "qna"

# Run with live LLM (requires AGENT_MODE=openai)
AGENT_MODE=openai pytest tests_root/specs/e2e_comprehensive/test_qna_from_all_steps.py -v --tb=short -k "relevant_info"
```

## Screenshot

See `.playwright-mcp/e2e_accessibility_rate_inclusions.png` for full conversation screenshot.
