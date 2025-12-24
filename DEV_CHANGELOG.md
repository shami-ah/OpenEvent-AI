# Development Changelog

## 2025-12-24

### Fix: Verbalizer Not Mentioning Closest Preference Matches

**Problem:** When a client mentioned "dinner" in their inquiry, the preference extraction and room scoring worked correctly (showing `closest: ['Classic Apéro (closest to dinner)']`), but the AI response never mentioned this preference match to the client.

**Root Cause:** The `_format_facts_section()` function in `universal_verbalizer.py` extracted `matched` and `missing` from room requirements, but **not `closest`**. This meant the LLM never saw the closest match data in its prompt.

**Solution:** Added `closest` extraction and formatting alongside `matched` and `missing` in the room data section.

**Files Modified:**
- `backend/ux/universal_verbalizer.py:597-603` - Added `closest` field extraction and formatting

**Result:** AI responses now correctly mention preference matches, e.g., "While we don't have a dedicated dinner package, our Classic Apéro comes closest to what you're looking for."

---

### Fix: Event Type Priority Order for Preference Extraction

**Problem:** "dinner party" was extracting as "party" instead of "dinner" because generic event types (party) appeared before food types (dinner) in the extraction list.

**Solution:** Reordered event_types list to prioritize food/catering types first (dinner, lunch, breakfast...) before generic types (party, celebration).

**Files Modified:**
- `backend/adapters/agent_adapter.py:173-188` - Reordered event types with food types first

**Result:** "dinner party" now correctly extracts as "dinner".

---

### Enhancement: Add Closest Matches to Verbalizer Room Payload

**Problem:** The Step 3 handler was calculating closest preference matches but not passing them to the verbalizer.

**Solution:** Added `closest` field to the requirements dict in `_verbalizer_rooms_payload()` and updated `_derive_hint()` to show closest matches when no exact matches exist.

**Files Modified:**
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1183-1188, 1248` - Added closest to payload and hint derivation

**Result:** Room buttons now show hints like "Classic Apéro" for closest matches when no exact match exists.

---

## 2025-12-23

### Fix: Event Type Extraction for Preference Matching (dinner, banquet, etc.)

**Problem:** When a client mentioned "dinner event" in their inquiry, the event type was not being extracted, so preference matching couldn't recommend rooms with relevant catering options.

**Root Cause:** The `StubAgentAdapter._extract_entities()` only recognized a limited set of event types: workshop, meeting, conference, seminar, wedding, party, training. Food/catering event types like "dinner", "banquet", "cocktail" were missing.

**Solution:** Expanded the event type list to include: dinner, lunch, breakfast, brunch, reception, cocktail, apéro, aperitif, banquet, gala, birthday, celebration, presentation, lecture, talk.

**Files Modified:**
- `backend/adapters/agent_adapter.py:173-183` - Expanded event_types list

**Result:** "dinner event" now extracts `type: dinner`, which flows to `wish_products: ['dinner']`, enabling room preference matching with catering options.

---

### Fix: Room Preference Matching for Layout Types (workshop, theatre, etc.)

**Problem:** When a client mentioned "workshop" in their inquiry, the preference extraction worked but room matching returned 0.0 score for all rooms. Rooms with "workshop" layout capability were shown as `missing: ["workshop"]` instead of `matched: ["Workshop"]`.

**Root Cause:** The `_score_rooms_by_products` function in `preferences.py` only checked `features` and `services` from room data, but `capacity_by_layout` keys (like "workshop", "theatre", "u_shape") were not included in matchable features.

**Solution:** Updated both `_room_catalog()` and `_score_rooms_by_products()` to include layout types from `capacity_by_layout` as matchable room features.

**Files Modified:**
- `backend/workflows/nlu/preferences.py:391-404` - Include layout keys in `_room_catalog()`
- `backend/workflows/nlu/preferences.py:219-221` - Include layout keys in `_score_rooms_by_products()`

**Result:** Rooms A, B, C, D, F now correctly match "workshop" preference with score 1.0.

---

### Fix: Acceptance Messages Triggering False Positive Room Change Detection

**Problem:** During the offer acceptance flow, "Yes, I accept" messages were incorrectly triggering room change detection, causing infinite loops between Step 5 → Step 3 with `structural_change_detour` action.

**Root Cause:** The `_detect_structural_change` function in Step 5 ran LLM extraction on all messages, including acceptance messages. The LLM sometimes extracted spurious "room" values from acceptance phrases, triggering false positive room change detection.

**Symptom:** Audit log showed repeated `Step 5 → 3 (negotiation_changed_room)` entries. Event stuck at `current_step: 3` with `caller_step: 5`.

**Solution:** Added acceptance guard at the start of `_detect_structural_change`:
```python
if message_text:
    is_acceptance, confidence, _ = matches_acceptance_pattern(message_text.lower())
    if is_acceptance and confidence >= 0.7:
        return None  # Skip change detection for acceptance messages
```

**Files Modified:**
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:665-674` - Added acceptance guard

**Tests:** E2E frontend flow verified: inquiry → room selection → offer → acceptance → billing → deposit → HIL task appears.

---

### Fix: HIL Task Shows in Tasks Panel, Not Chat (Deposit Flow)

**Problem:** After paying the deposit, the HIL message was appearing directly in chat instead of the Manager Tasks panel. The correct flow is: deposit payment → HIL task in Tasks panel → manager clicks Approve → message appears in chat.

**Root Causes:**
1. **Frontend:** Previous fix incorrectly added `appendMessage()` to `handlePayDeposit`, which bypassed the HIL flow and sent messages directly to chat
2. **Backend:** Event entries didn't have `thread_id` stored, so tasks filtered by `task.payload?.thread_id === sessionId` didn't match, hiding tasks from the panel

**Solution:**
1. Frontend (page.tsx): Removed `appendMessage()` from `handlePayDeposit` - HIL tasks should stay in Tasks panel
2. Backend (step1_handler.py): Added `thread_id` to event entries in 4 places when created/updated

**Files Modified:**
- `atelier-ai-frontend/app/page.tsx:886-907` - Removed appendMessage from deposit handler
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py:1293-1403` - Added thread_id to events

**Tests:** E2E frontend flow verified - deposit payment → HIL in Tasks panel → Approve → site visit message in chat.

---

## 2025-12-22

### Fix: Billing Address Routing to Wrong Step

**Problem:** After accepting an offer and providing a billing address, the system responded with a generic fallback message instead of routing to HIL for final approval. The billing address was sometimes captured as the original greeting message.

**Root Causes:**
1. **Duplicate message detection** blocked billing flow messages
2. **Change detection** during billing triggered room/date changes
3. **Step corruption** wasn't corrected when entering billing flow
4. **Response key mismatch** in `_handle_accept()` return value

**Solution:**
1. Added billing flow bypass to duplicate message detection
2. Added `in_billing_flow` guards to skip all change detection in step1_handler
3. Added step correction to force `current_step=5` when in billing flow
4. Fixed Step 5 to access `response["draft"]["body"]` instead of `response["body"]`

**Files Modified:**
- `backend/workflow_email.py` - Duplicate bypass + step correction
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Change detection guards
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` - Response key fix

---

### Feature: Dev Server Script

**Purpose:** Reliable backend server management with automatic cleanup.

**Usage:**
```bash
./scripts/dev_server.sh         # Start backend
./scripts/dev_server.sh stop    # Stop backend
./scripts/dev_server.sh restart # Restart backend
./scripts/dev_server.sh status  # Check status
./scripts/dev_server.sh cleanup # Kill all dev processes
```

**Features:**
- Automatically kills zombie processes on port 8000
- Loads OpenAI API key from macOS Keychain
- PID tracking for reliable process management
- Color-coded output for easy debugging

---

### Feature: Dev Test Mode (Continue/Reset Choice)

**Purpose:** When testing with an existing event, offers choice to continue at current step or reset to a new event.

**How it works:**
- When a message matches an existing event AND the event is past Step 1
- System shows a choice prompt: "Continue" or "Reset"
- "Continue" resumes at the current step with all existing data
- "Reset" creates a new event from scratch

**API Endpoints:**
- `POST /api/client/{client_id}/continue` - Continue workflow at current step
- Response includes `dev_choice` object when choice is needed

**Skip the choice:**
- Pass `skip_dev_choice: true` in the message payload to auto-continue

---

### Feature: Unified Confirmation Gate

**Purpose:** Order-independent prerequisite checking for offer confirmation.

**Location:** `backend/workflows/common/confirmation_gate.py`

**Checks:**
1. `offer_accepted` - Has client accepted?
2. `billing_complete` - Is billing address complete?
3. `deposit_required` - Is deposit needed per policy?
4. `deposit_paid` - Has deposit been paid?

**Usage:**
```python
from backend.workflows.common.confirmation_gate import check_confirmation_gate

gate_status = check_confirmation_gate(event_entry)
if gate_status.ready_for_hil:
    # All prerequisites met - continue to HIL
```

---

## 2025-12-21

### Fix: Step 4 HIL Approval Continuation

**Problem:** When approving a Step 4 offer task (after deposit was paid), clicking "Approve" did nothing - the workflow didn't continue to site visit.

**Root Cause:** The `approve_task_and_send` function only had special continuation handling for Step 5 tasks. Step 4 approvals just marked the task as approved without continuing the workflow.

**Solution:** Added Step 4 handling in `backend/workflow_email.py`:
- Check if `offer_accepted = True` and deposit is paid (or not required)
- If so, apply the same negotiation decision logic as Step 5
- Set `site_visit_state.status = "proposed"` to continue to site visit

---

### Fix: Deposit Payment Workflow Continuation

**Problem:** After clicking "pay deposit" button, the workflow stopped instead of continuing to send the offer for HIL approval. The deposit was marked as paid in the database, but no further processing occurred.

**Root Cause:** The `/api/event/deposit/pay` endpoint only marked the deposit as paid without triggering workflow continuation. Additionally, the step4_handler didn't track that the offer was already accepted.

**Solution:**
1. **`backend/api/routes/events.py`**:
   - After marking deposit paid, check if prerequisites are met (billing address + offer accepted)
   - If yes, send synthetic message to trigger workflow continuation
   - If no, return success but don't continue (missing prerequisites)

2. **`backend/workflows/steps/step4_offer/trigger/step4_handler.py`**:
   - Set `offer_accepted = True` on event_entry when acceptance is detected
   - Added `_check_deposit_payment_continuation()` helper function
   - When offer_accepted + billing complete + deposit paid → route directly to HIL

**Flow After Fix:**
1. Client says "all good" → `offer_accepted = True`
2. System asks for billing address
3. Client provides billing → billing stored
4. System shows deposit reminder → halts
5. Client clicks "pay deposit" → deposit marked paid
6. Synthetic message triggers workflow continuation
7. `_check_deposit_payment_continuation()` detects all conditions met
8. Routes to HIL for final approval

---

### Feature: Room Lock Preservation on Date Change Detours

**Goal:** When a client changes the date from the offer/negotiation stage (Steps 4/5) and the locked room is still available on the new date, skip room selection and return directly to Step 4.

**Problem:** Previously, when a client changed the date, `locked_room_id` was cleared unconditionally in multiple code paths. This forced the client to re-select the room even when it was still available on the new date—unnecessary friction in the workflow.

**Expected Behavior (per Workflow v4 DAG):**
1. Client changes date → detour to Step 2 for date confirmation
2. After date confirmed, return to Step 3
3. Step 3 checks: is the locked room still available on the new date?
   - YES → update `room_eval_hash` and return to caller step (Step 4)
   - NO → clear lock and present room options

**Changes Made:**

1. **`backend/workflows/steps/step4_offer/trigger/step4_handler.py`**:
   - Modified date change handling to only clear `room_eval_hash=None` (trigger re-verification)
   - Keep `locked_room_id` intact so Step 3 can check availability
   - Requirements changes still clear the lock (room may no longer fit)

2. **`backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py`**:
   - Modified date change detection (~L881-897) to preserve `locked_room_id`
   - Modified date confirmation flow (~L2384-2393) to preserve `locked_room_id`
   - Only clear `room_eval_hash` to trigger Step 3 re-verification

3. **`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`**:
   - Modified date change detection (~L291-307) to preserve `locked_room_id`
   - Added fast-skip logic (~L438-489) to check if locked room is still available:
     ```python
     if locked_room_id and not explicit_room_change:
         locked_room_status = status_map.get(locked_room_id, "").lower()
         if locked_room_status in ("available", "option"):
             update_event_metadata(event_entry, room_eval_hash=current_req_hash)
             return _skip_room_evaluation(state, event_entry)  # Return to caller
         else:
             update_event_metadata(event_entry, locked_room_id=None, room_eval_hash=None)
     ```

**Testing Status:** Partial fix applied; additional testing needed to verify all code paths.

---

## 2025-12-18

### Fix: New Event Creation When Existing Event in Site Visit State

**Problem:** New event inquiries from the same email were being matched to existing events instead of creating new ones. When an existing event had `site_visit_state.status = "proposed"`, new inquiries would trigger site visit routing and return fallback messages instead of proper room availability.

**Root Cause:** `_ensure_event_record()` in step1_handler.py always reused the most recent event for the same email via `last_event_for_email()`, regardless of whether the existing event was in a terminal/mid-process state.

**Changes Made:**
- **`backend/workflows/steps/step1_intake/trigger/step1_handler.py`**: Added logic in `_ensure_event_record()` to create a NEW event when:
  - New message has DIFFERENT event date than existing event (ONLY if date is an actual date, not "Not specified")
  - Existing event status is "confirmed", "completed", or "cancelled"
  - Existing event has `site_visit_state.status` in ("proposed", "scheduled")

**Bug Fix (follow-up):** Initial version triggered on `new_event_date != existing_event_date` but `new_event_date` could be "Not specified" for follow-up messages without dates (like "Room E"), causing false positives. Fixed by checking `new_date_is_actual = new_event_date not in ("Not specified", None, "")`.

- **`backend/api/routes/messages.py`**: Added diagnostic logging when fallback message is triggered, showing `wf_res.action`, `draft_messages` count, and `event_id` for debugging.

---

### Fix: Site Visit Routing from Steps 3 and 4

**Problem:** When an event at Step 3 or 4 had `site_visit_state.status = "proposed"`, client messages would go through normal step processing (including date change detection) instead of routing to Step 7 for site visit handling.

**Changes Made:**
- **`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`**: Added site visit check early in `process()` - routes to Step 7 when `site_visit_state.status == "proposed"`
- **`backend/workflows/steps/step4_offer/trigger/step4_handler.py`**: Added same site visit routing check

---

### Feature: Site Visit Booking Implementation (Phase 1)

**Goal:** Fix site visit date handling so client preferences for visit dates don't trigger event date change detours.

**Problem:** After offer approval, when the manager proposes site visits and the client responds with a date preference like "what about April, preferably on a Wednesday afternoon around 4 pm", the system:
1. Extracted the April date via LLM
2. `_detect_structural_change()` saw this differed from `chosen_date` (08.05.2026)
3. Triggered a detour to Step 2 (date confirmation)
4. Showed room availability for April instead of site visit options

**Root Cause:** The system didn't distinguish between site visit date preferences (when `site_visit_state.status == "proposed"`) and event date change requests. Additionally, `site_visit_state.status` wasn't being set to "proposed" when the offer was approved and the site visit prompt was shown.

**Changes Made:**

1. **`backend/workflow_email.py`**:
   - When step 5 (negotiation/offer) is approved, now sets `site_visit_state.status = "proposed"` so subsequent client messages are recognized as site visit context

2. **`backend/workflows/steps/step5_negotiation/trigger/step5_handler.py`**:
   - Added site visit mode check to `_detect_structural_change()` - skip date detection when `site_visit_state.status == "proposed"`
   - Added routing to Step 7 when site visit is in progress (status == "proposed")

3. **`backend/workflows/steps/step7_confirmation/trigger/step7_handler.py`**:
   - Modified `_detect_structural_change()` to skip date change detection when `site_visit_state.status == "proposed"`
   - Added site visit handling block in `process()` after structural change detection
   - Added `_extract_site_visit_preference()` - parses time (4 pm → 16:00), weekday (Wednesday → 2), month (April → 4)
   - Added `_generate_preferred_visit_slots()` - generates slots matching client preference, before event date
   - Added `_handle_site_visit_preference()` - presents refined slot options to client
   - Added `_handle_site_visit_confirmation()` - confirms selected slot with direct confirm (no HIL)
   - Added `_parse_slot_selection()` - parses ordinals (first/second), dates, or generic confirmations

**Database Schema (Supabase-compatible):**
```python
"site_visit_state": {
    "status": "idle|proposed|scheduled|completed|cancelled",
    "requested_date": "2026-04-15",     # ISO date (client preference)
    "requested_time": "16:00",          # Time preference
    "requested_weekday": 2,             # 0-6 Mon-Sun
    "proposed_slots": [...],            # Generated options
    "confirmed_date": "2026-04-15",     # Final confirmed date
    "confirmed_time": "16:00",          # Final confirmed time
    "notes": None,                      # Optional notes
}
```

**Expected Flow (Fixed):**
```
Manager: "Let's continue with site visit bookings..."
Client: "what about april preferably on a wednesday afternoon (around 4 pm)?"
System: "Here are available times matching your preference:
         - 15.04.2026 at 16:00
         - 22.04.2026 at 16:00
         - 29.04.2026 at 16:00
         Which would work best for you?"
Client: "yes please proceed"
System: "Your site visit is confirmed for 15.04.2026 at 16:00. We look forward to showing you Room E!"
```

**Files Changed:**
- `backend/workflow_email.py` (lines 615-622)
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (lines 185-203, 543-558)
- `backend/workflows/steps/step7_confirmation/trigger/step7_handler.py` (lines 120-135, 201-212, 559-815)

**Tests:** 146 passed

---

### Feature: Room Availability Feature-Based Comparison

**Goal:** Enhance room availability comparison to show how room features match client preferences, not just capacity.

**Problem:** Room comparisons only mentioned capacity (e.g., "Room A fits your 60 guests"). They didn't explain WHY a room was recommended based on client-requested features like sound systems, cocktail bars, etc.

**Changes Made:**

1. **`backend/workflows/nlu/preferences.py`** - Enhanced feature matching:
   - Added `_match_against_features()` function for fuzzy matching against room features/services
   - Modified `_score_rooms_by_products()` to match client wishes against native room features (sound_system, bar_area, etc.) from rooms.json
   - Now properly populates `room_match_breakdown.matched/missing` for all client wishes

2. **`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`** - Added client preferences to snapshot:
   - Snapshot now includes `client_preferences` with wish_products, keywords, and special_requirements
   - Info page can now show feature comparison per-room cards

3. **`backend/ux/universal_verbalizer.py`** - Enhanced verbalization:
   - Updated Step 3 prompt to explicitly use `requirements.matched/missing` data
   - Modified `_format_facts_for_prompt()` to include matched/missing features per room
   - LLM now receives context like: `Room A: Available, capacity 40, matched: [sound system, coffee service]`

**Expected Result:**
- Before: "Room A is available for your 60 guests on 08.05.2026."
- After: "Room A has everything you asked for - the sound system and coffee service are both included. Room E also has the sound system, though the cocktail bar setup would need to be arranged separately."

**Files Changed:**
- `backend/workflows/nlu/preferences.py` (added _match_against_features, modified _score_rooms_by_products)
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` (lines 547-563)
- `backend/ux/universal_verbalizer.py` (lines 177-204, 585-600)

**Tests:** 146 passed

---

### Fix: Initial Event Inquiries Returning Generic/Wrong Responses

**Problem:** Initial event inquiries with questions (e.g., "Could you confirm availability?") were returning generic fallback messages or hallucinated content like "Room S" (which doesn't exist).

**Root Causes:**
1. Questions in messages triggered `is_general=True` via heuristic detection (question marks, interrogative patterns)
2. Step 3 took the Q&A path for initial inquiries instead of showing room availability
3. Q&A extraction classified inquiries as `qna_subtype: "non_event_info"`
4. `_execute_query()` had no handler for `non_event_info`, returning empty `db_summary`
5. Empty data caused LLM verbalizer to hallucinate room names

**Fixes Applied:**

1. **`backend/workflows/qna/engine.py`** - Added fallback for `non_event_info` subtype:
   - Uses captured context (date/attendees) to query room availability
   - Falls back to listing all rooms by capacity if no context available
   - Added helpful notes for users

2. **`backend/workflows/qna/context_builder.py`** - Updated `_resolve_*` functions:
   - `_resolve_attendees()`: Now uses captured attendees for `non_event_info`
   - `_resolve_date()`: Now uses captured date for `non_event_info`
   - `_resolve_room()`: Now uses captured/locked room for `non_event_info`

3. **`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`** - Skip Q&A for first entry:
   - Added check for `has_step3_history` (room_pending_decision or audit_log entries)
   - Initial inquiries now go through normal room availability path, not Q&A
   - Q&A path reserved for follow-up questions after rooms have been presented

**Files Changed:**
- `backend/workflows/qna/engine.py` (lines 191-229)
- `backend/workflows/qna/context_builder.py` (lines 139-143, 238-242, 321-325)
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` (lines 334-346)

**Tests:** 146 passed

---

### Refactoring: Phase C - Extract Routes from main.py (Continued)

**Task: Modularize main.py by extracting route handlers into separate files**

Continued the Phase C refactoring by extracting route handlers from `backend/main.py` into domain-specific files in `backend/api/routes/`.

**Progress:**
- **main.py reduced from 2188 → 1573 lines** (28% reduction, 615 lines removed)

**Route Files Created:**

| File | Routes | Lines |
|------|--------|-------|
| `tasks.py` | `/api/tasks/*` (pending, approve, reject, cleanup) | ~230 |
| `events.py` | `/api/events/*`, `/api/event/*/deposit` | ~180 |
| `config.py` | `/api/config/global-deposit` | ~175 |
| `clients.py` | `/api/client/reset` | ~135 |

**Structure:**
```
backend/api/routes/
├── __init__.py     # Exports all routers
├── tasks.py        # HIL task management
├── events.py       # Event CRUD + deposits
├── config.py       # Global deposit config
└── clients.py      # Client reset (testing)
```

**Still Remaining in main.py (~1573 lines):**
- Message routes (`/api/send-message`, `/api/start-conversation`, etc.)
- Debug routes (conditionally loaded)
- Test data routes (`/api/test-data/*`, `/api/qna`, `/api/snapshots/*`)
- Workflow routes (`/api/workflow/*`)
- Helper functions (port management, frontend launch, etc.)
- App setup and lifecycle

**Tests:** 146 passed

**Commits:**
- `73cb07f` refactor(api): extract routes from main.py into modular route files
- `20f7901` refactor(api): extract debug, snapshots, test_data, workflow routes

### Refactoring: Phase C - Extract More Routes from main.py

**Task: Continue route extraction to further modularize main.py**

Extracted 4 more route modules from `backend/main.py`:

**Progress:**
- **main.py reduced from 1573 → 1170 lines** (26% further reduction)
- **Total reduction: 2188 → 1170 lines** (47% reduction, 1018 lines removed)

**Additional Route Files Created:**

| File | Routes | Lines |
|------|--------|-------|
| `debug.py` | `/api/debug/*` (trace, timeline, report, live logs) | ~190 |
| `snapshots.py` | `/api/snapshots/*` (get, list, data) | ~60 |
| `test_data.py` | `/api/test-data/*`, `/api/qna` | ~160 |
| `workflow.py` | `/api/workflow/*` (health, hil-status) | ~35 |

**Complete Route Structure:**
```
backend/api/routes/
├── __init__.py     # Exports all routers
├── tasks.py        # HIL task management
├── events.py       # Event CRUD + deposits
├── config.py       # Global deposit config
├── clients.py      # Client reset (testing)
├── debug.py        # Debug and tracing
├── snapshots.py    # Snapshot storage
├── test_data.py    # Test data and Q&A
└── workflow.py     # Workflow status
```

**Still Remaining in main.py (~1170 lines):**
- Message routes (`/api/send-message`, `/api/start-conversation`)
- Conversation routes (`/api/conversation/*`, `/api/accept-booking`, `/api/reject-booking`)
- Helper functions (port management, frontend launch)
- App setup and lifecycle

**Tests:** 146 passed

### Refactoring: Phase C Complete - Message Routes Extracted

**Task: Extract final routes from main.py to complete modularization**

Extracted message/conversation routes to `backend/api/routes/messages.py`:

**Final Progress:**
- **main.py: 2188 → 468 lines (79% reduction, 1720 lines removed)**

**Final Route Structure:**
```
backend/api/routes/
├── __init__.py     # Exports all routers
├── tasks.py        # HIL task management (~230 lines)
├── events.py       # Event CRUD + deposits (~180 lines)
├── config.py       # Global deposit config (~175 lines)
├── clients.py      # Client reset (~135 lines)
├── debug.py        # Debug and tracing (~190 lines)
├── snapshots.py    # Snapshot storage (~60 lines)
├── test_data.py    # Test data and Q&A (~160 lines)
├── workflow.py     # Workflow status (~35 lines)
└── messages.py     # Message/conversation handling (~700 lines)
```

**What remains in main.py (~468 lines):**
- FastAPI app creation and lifespan
- CORS middleware configuration
- Router includes (9 routers)
- Port management functions
- Frontend launch functions
- Process cleanup functions
- Root endpoint

**Tests:** 146 passed

**Commits:**
- `23e5903` refactor(api): extract message routes from main.py (Phase C complete)

---

## 2025-12-17

### Fix: Stale negotiation_pending_decision blocking room selection flow

**Bug**: After room selection ("Room B"), system incorrectly showed "sent to manager for approval" instead of generating offer.

**Root cause**: When requirements changed or detours happened (step 5 → step 3), the `negotiation_pending_decision` was not cleared. Step 4 then saw this stale state and returned `offer_waiting_hil` instead of generating a new offer.

**Files fixed**:
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py:1152-1153` - Clear pending decision when requirements change
- `backend/workflows/steps/step4_offer/trigger/step4_handler.py:604-606` - Clear pending decision when routing to step 2/3
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:162-164` - Clear pending decision when structural change detours to step 2/3

**Tests**: 146 passed

---

### Refactoring: AI Agent Optimization - Phase D (Error Handling)

**Completed Phase D: Standardize error handling**

Verified and enhanced the `backend/core/` module with standardized error handling utilities:

**`backend/core/errors.py`** - Already existed, provides:
- `OpenEventError`, `DetectionError`, `WorkflowError`, `LLMError` - Typed exception classes
- `safe_operation()` - Context manager for safe exception handling
- `log_exception()` - Standardized error logging

**`backend/core/fallback.py`** - Already existed, provides:
- `FallbackContext` - Structured diagnostic data for fallbacks
- `wrap_fallback()` - Wraps messages with diagnostic info
- `is_likely_fallback()` - Detects fallback patterns
- Pre-built factories: `llm_disabled_fallback()`, `llm_exception_fallback()`, etc.

**`backend/core/__init__.py`** - Updated to properly export all utilities

**Silent exception handlers fixed in:**
- `backend/conversation_manager.py` - 3 bare `except:` blocks converted to specific types

**Tests**: 146 passed

---

### Refactoring: Phase C Deferred (High Risk)

**Decision**: Large file splitting deferred due to high risk

Files analyzed but NOT split:
- `date_confirmation/trigger/process.py` (3664 lines)
- `main.py` (2188 lines)
- `smart_shortcuts.py` (2196 lines)
- `general_qna.py` (1490 lines)

**Rationale**: Heavy interdependencies, shared state, conditional logic - splitting risks breaking functionality. See `docs/internal/OPEN_DECISIONS.md` DECISION-006.

---

### Refactoring: AI Agent Optimization - Phase B Complete

**All detection modules migrated to `backend/detection/`**

Completed migration of all detection logic:

1. **B.1**: `keyword_buckets.py` → `detection/keywords/buckets.py`
2. **B.2**: `sequential_workflow.py` → `detection/qna/sequential_workflow.py`
3. **B.3**: `confidence.py` → `detection/intent/confidence.py`
4. **B.4**: `general_qna_classifier.py` → `detection/qna/general_qna.py`
5. **B.5**: `semantic_matchers.py` → `detection/response/matchers.py`
6. **B.6**: `conflict.py` → `detection/special/room_conflict.py`
7. **B.7**: `intent_classifier.py` → `detection/intent/classifier.py`

**Pre-existing test failures documented**: See `docs/internal/OPEN_DECISIONS.md` DECISION-005

**Tests**: 380 passed, 2 pre-existing failures (unrelated to migration)

---

### Refactoring: AI Agent Optimization - Phase B (keyword_buckets migration)

**First detection module migrated to new location**

Migrated `keyword_buckets.py` (source of truth for all detection patterns) to new location:
- **OLD**: `backend/workflows/nlu/keyword_buckets.py`
- **NEW**: `backend/detection/keywords/buckets.py`

**Files updated with new import paths:**
- `backend/llm/intent_classifier.py`
- `backend/workflows/nlu/__init__.py`
- `backend/workflows/nlu/semantic_matchers.py`
- `backend/workflows/nlu/general_qna_classifier.py`
- `backend/workflows/change_propagation.py`
- `backend/tests/detection/test_detour_detection.py`

**Old file marked deprecated** with warning pointing to new location.

**Tests**: 381 passed (1 pre-existing failure unrelated to migration)

---

### Refactoring: AI Agent Optimization - Phase A (Preparation)

**Task: Reorganize codebase for better AI agent comprehension and bug prevention**

Created folder structure and documentation for a comprehensive refactoring effort. This is preparation only - no existing code has been moved yet.

**New Modules Created:**

1. **`backend/detection/`** - Will consolidate all detection logic
   - `intent/` - Intent classification and confidence scoring
   - `response/` - Acceptance, decline, counter, confirmation detection
   - `change/` - Detour and change request detection
   - `qna/` - Q&A and sequential workflow detection
   - `special/` - Manager request, room conflict, nonsense gate
   - `keywords/` - Single source of truth for all keyword patterns

2. **`backend/core/`** - Core infrastructure
   - `errors.py` - Standardized error handling (replaces silent `except: pass`)
   - `fallback.py` - Mandatory fallback message wrapping with diagnostics

3. **`backend/api/routes/`** - Prepared for main.py split

**Documentation Created:**
- `docs/DEPENDENCY_GRAPH.md` - Maps dependencies between modules
- All `__init__.py` files have detailed module documentation

**Files Created:**
- `backend/detection/__init__.py` + 6 submodule `__init__.py` files
- `backend/core/__init__.py`, `errors.py`, `fallback.py`
- `backend/api/routes/__init__.py`, `middleware/__init__.py`
- `docs/DEPENDENCY_GRAPH.md`

**Plan Reference:**
- Full refactoring plan at `/Users/nico/.claude/plans/wild-enchanting-eagle.md`

**Next Phases:**
- Phase B: Migrate detection logic to `backend/detection/`
- Phase C: Split large files (main.py, date_confirmation/process.py, etc.)
- Phase D: Standardize error handling (replace 50+ silent exception handlers)
- Phase E: Rename folders (groups → steps, common → shared)
- Phase F: Rename ambiguous files (process.py → step2_orchestrator.py)

---

### Feature: International Format Support for Entity Extraction

**Problem:** Shortcut workflow detection failed for international date, time, and participant formats. Users writing "May 8, 2026" (US format), "30 pax" (hospitality), or "18h30" (French) weren't getting their entities extracted.

**Solution:** Expanded regex patterns in `StubAgentAdapter` to support worldwide conventions based on web research of hospitality industry standards and international notation.

**Participants — Added formats:**
| Language | Terms |
|----------|-------|
| Hospitality | pax, covers, heads |
| German | Personen, Gäste, Teilnehmer, Leute, Besucher |
| French | personnes, invités, convives |
| Italian | persone, ospiti, partecipanti, invitati |
| Spanish | personas, invitados, asistentes, huéspedes |
| Labels | "Attendees: X", "Expected: X", "headcount: X" |
| Phrases | "party of X", "group of X", "team of X" |

**Dates — Added formats:**
- US format: "May 8, 2026", "December 25, 2025" (Month DD, YYYY)

**Times — Added formats:**
- 12-hour: "6:30 PM", "9am"
- German: "18 Uhr", "18h"
- French: "18h30", "14h45"

**Files Modified:**
- `backend/adapters/agent_adapter.py` — `_extract_entities()`, `_extract_times()`, `_extract_date()`

**Commits:**
- `e356fca` feat(intake): add international format support for entity extraction
- `31ed17c` feat(intake): expand international format support based on web research

---

### Feature: Centralized Fallback Diagnostics

**Problem:** Fallback messages like "It appears there is no specific information available" were frustrating because they:
1. Didn't indicate they ARE fallback messages
2. Didn't explain WHY the fallback was triggered
3. Didn't help debug what went wrong

**Solution:** Created a centralized fallback diagnostic system that marks all fallback messages with structured information about:
- Source (which module triggered the fallback)
- Trigger reason (llm_disabled, llm_exception, empty_results, etc.)
- Failed conditions
- Context (room/date/product counts, query parameters)
- Original error message if applicable

**Files Created:**
- `backend/workflows/common/fallback_reason.py` — Centralized `FallbackReason` dataclass and helper functions

**Files Modified:**
- `backend/workflows/qna/verbalizer.py` — Added fallback diagnostics to `_fallback_answer()`
- `backend/workflows/qna/extraction.py` — Added `_fallback_reason` and `_fallback_error` fields
- `backend/workflows/common/general_qna.py` — Added diagnostics to `_fallback_structured_body()`
- `backend/workflows/llm/adapter.py` — Added diagnostics to `_fallback_analysis()`

**Environment Variable:**
```bash
# Show fallback diagnostics (default: true for dev/staging)
OE_FALLBACK_DIAGNOSTICS=true

# Hide diagnostics in production
OE_FALLBACK_DIAGNOSTICS=false
```

**Example Output:**
```
*Intent*: select_static · *Subtype*: non_event_info

---
[FALLBACK MESSAGE]
Source: qna_verbalizer
Trigger: llm_disabled
Context: rooms_count=0, dates_count=0, products_count=0, intent=select_static
```

---

### Fix: Sequential Workflow vs General Q&A Detection

**Problem:** When a client confirms the current workflow step AND asks about the next step (e.g., "Please confirm May 8 and show me available rooms"), the system incorrectly classified this as "general Q&A" instead of natural workflow continuation.

**Solution:** Added `detect_sequential_workflow_request()` function that identifies when a message contains both:
- An action/confirmation for the current step (e.g., confirm date, select room, accept offer)
- A question/request about the immediate next step (e.g., show rooms, what catering?, site visit?)

When both are detected, `is_general` is set to `False` and the workflow proceeds naturally.

**Files Added:**
- `backend/workflows/nlu/sequential_workflow.py` - New module with sequential workflow detection logic
- `backend/tests/detection/test_sequential_workflow.py` - 64 test cases for sequential detection

**Files Modified:**
- `backend/workflows/nlu/__init__.py` - Export `detect_sequential_workflow_request`
- `backend/workflows/groups/date_confirmation/trigger/process.py` - Integrated Step 2→3 detection
- `backend/workflows/groups/room_availability/trigger/process.py` - Integrated Step 3→4 detection, added classification caching
- `backend/workflows/groups/offer/trigger/process.py` - Integrated Step 4→5/7 detection
- `docs/TEAM_GUIDE.md` - Added bug documentation under "Known Issues & Fixes"

**Follow-up Fix: Classification Persistence Between Steps**

When Step 2 auto-runs Step 3 after date confirmation, Step 3 was re-classifying the same message, potentially overwriting the sequential workflow detection from Step 2. Fixed by having Step 3 check for and reuse a cached classification that has `workflow_lookahead` set.

```python
# In room_availability/trigger/process.py
cached_classification = state.extras.get("_general_qna_classification")
if cached_classification and cached_classification.get("workflow_lookahead"):
    classification = cached_classification  # Reuse Step 2's detection
else:
    classification = detect_general_room_query(message_text, state)
```

**Step Progression Patterns:**
| Current Step | Action Example | Next Step | Lookahead Example |
|--------------|----------------|-----------|-------------------|
| 2 (Date) | "confirm May 8" | 3 (Room) | "show me available rooms" |
| 3 (Room) | "Room A looks good" | 4 (Offer) | "what catering options?" |
| 4 (Offer) | "accept the offer" | 5/7 | "when can we do a site visit?" |

---

## 2025-12-15

### Fix: Router Q&A Info Link Integration

**Task: Add info link to catering Q&A when appended to workflow response**

**Fix 1: Secondary Q&A Type Detection**
- Added `_detect_qna_types()` import to `general_qna_classifier.py`
- Modified `detect_general_room_query()` to include `secondary` types (e.g., `catering_for`) in classification result
- This allows downstream code to know which Q&A types are present in the message

**Fix 2: Router Q&A Integration in Date Options Flow**
- Added router Q&A integration in `_present_candidate_dates()` (date_options_proposed path)
- When message contains secondary Q&A types (catering_for, products_for, etc.), router content is appended
- Fixed `load_db()` error by passing `None` instead (router doesn't need db for catering/products)

**Fix 3: Info Link Generation for Catering Q&A**
- Added `create_snapshot()` and `generate_qna_link()` calls when appending catering Q&A
- Creates a snapshot with catering data and generates pseudolink for "Full menu details"
- Link format: `<a href="http://localhost:3000/info/qna?snapshot_id=...">View Catering information</a>`

**Files Modified:**
- `backend/workflows/nlu/general_qna_classifier.py` - Added secondary types to classification
- `backend/workflows/groups/date_confirmation/trigger/process.py` - Router Q&A integration with info links

---

### Fix: Backend Startup & Infrastructure Issues

**Task: Fix multiple issues preventing backend from starting reliably**

**Fix 1: Python Bytecode Cache Causing Startup Failures**
- Added `_clear_python_cache()` function to automatically clear `__pycache__` directories on startup
- Prevents stale bytecode from causing `unexpected keyword argument` errors when dataclasses are modified
- Documented in TEAM_GUIDE.md with quick fix instructions

**Fix 2: Date Range Parsing (2025 → 2026)**
- Added `_DATE_RANGE_MDY` and `_DATE_RANGE_DMY` patterns in `backend/workflows/common/datetime_parse.py`
- Correctly parses "June 11–12, 2026" format where year follows second day
- Previously parsed as 2025 because the year regex couldn't capture year after day range

**Fix 3: Q&A Detection for "package options"**
- Added "package", "packages", "package options" to `catering_for` patterns in `backend/llm/intent_classifier.py`
- Questions about packages/package options now trigger Q&A detection

**Fix 4: Enable Development Endpoints by Default**
- Changed `ENABLE_DANGEROUS_ENDPOINTS` default to `true` for development
- Reset client functionality now works without manual env var

**Fix 5: Catering/Package Q&A Returning Fallback Message**
- Root cause: Structured Q&A engine doesn't handle `catering_for` Q&A type
- When structured engine can't handle a Q&A type, now falls back to `route_general_qna()` for types it CAN handle
- Router-handled types: `catering_for`, `products_for`, `rooms_by_feature`, `room_features`, `free_dates`, `parking_policy`, `site_visit_overview`
- This ensures catering Q&A goes through the proper verbalizer infrastructure instead of returning empty fallback
- Fixed `_catering_response()` to filter by category when user asks about "package", "menu", or "catering"
- Now shows actual catering packages instead of add-ons when user asks "What package options do you recommend?"

**Fix 6: ACTION_REQUEST_PATTERNS Too Broad**
- Pattern `\bprovide\s+(me\s+with\s+)?` was matching questions like "do you provide X"
- Fixed to require "me" or "us" after "provide": `\bprovide\s+(me|us)\s+(with\s+)?`
- "Do you provide coffee breaks?" now correctly detected as `catering_for` Q&A

**Files Modified:**
- `backend/main.py` - Cache clearing on startup, dangerous endpoints default
- `backend/workflows/common/datetime_parse.py` - Date range patterns
- `backend/llm/intent_classifier.py` - Package Q&A patterns
- `backend/workflows/groups/date_confirmation/trigger/process.py` - Router Q&A integration
- `backend/workflows/qna/router.py` - Category filtering for packages
- `backend/workflows/nlu/keyword_buckets.py` - Fixed ACTION_REQUEST_PATTERNS
- `docs/TEAM_GUIDE.md` - Documented bytecode cache bug and prevention

**Tests Added:**
- `backend/tests/smoke/test_backend_startup.py` - 14 smoke tests for imports and basic workflow

---

### Feature: Multi-Variable Q&A Handling - Part 2: Verbalizer & Preference Extraction

**Task: Address 3 gaps in Q&A implementation - verbalizer integration, qna_requirements usage, mid-workflow preference capture**

Completed fixes for robust Q&A handling with proper fact verification and context-aware preference persistence.

**Fix 1: Verbalizer Integration (Feed the Sandwich)**
- Added `_build_verbalize_context()` in `backend/workflows/common/general_qna.py`
- Updated `render_general_qna_reply()` to pass `topic` and `verbalize_context` to `append_footer()`
- Enables the existing verbalizer "sandwich" pattern to verify facts are preserved in LLM output

**Fix 2: qna_requirements Preservation (Use LLM-Extracted Data)**
- Updated `_normalize_qna_extraction()` to preserve `qna_requirements` instead of dropping it
- Added generic accessor `get_qna_requirements()` in router.py
- Updated extraction functions to prefer LLM-extracted data over regex fallbacks
- Generic pattern: dict access works for any field (attendees, dietary, features, layout, etc.)

**Fix 3: Mid-Workflow Preference Capture (Sentence-Level Parsing)**
- Added `split_statement_vs_question()` in `backend/workflows/common/capture.py`
- Added `capture_workflow_requirements()` for context-aware persistence
- **Key Rule:** Statement sentences → PERSIST; Question sentences → DON'T persist (Q&A only)
- Integrated into date_confirmation and room_availability processors

**Files Modified:**
- `backend/workflows/qna/extraction.py` - Include qna_requirements in normalized output
- `backend/workflows/qna/router.py` - Generic accessor, updated extraction functions
- `backend/workflows/common/general_qna.py` - Verbalize context building
- `backend/workflows/common/capture.py` - Sentence parsing, workflow requirement capture
- `backend/workflows/groups/date_confirmation/trigger/process.py` - Integration
- `backend/workflows/groups/room_availability/trigger/process.py` - Integration

**Tests Added:**
- `backend/tests/detection/test_qna_requirements_and_capture.py` - 24 tests covering:
  - qna_requirements preservation in extraction
  - Sentence-level parsing (split_statement_vs_question)
  - capture_workflow_requirements integration
  - Integration scenarios (statement+question, pure Q&A, etc.)

---

### Feature: Multi-Variable Q&A Handling (Task 1 of 2)

**Task: Handle conjuncted Q&A questions that span multiple workflow steps**

Added support for multi-variable Q&A detection and response composition. When a client asks about multiple topics in one message (e.g., "What dates are available and what packages do you offer?"), the system now properly handles all parts instead of only answering the first.

**Three Conjunction Cases Supported:**
- **Case A (Independent):** Different selects → separate answer sections
  - Example: "What rooms are free in January and what menus are available in October?"
- **Case B (AND Combined):** Same select, compatible conditions → single combined answer
  - Example: "What rooms are available in December and which include vegetarian options?"
- **Case C (OR Union):** Same select, conflicting conditions → ranked results (both first)
  - Example: "What rooms have background music and what rooms have a kitchen?"

**Key Design Decisions:**
- Q&A requirements mentioned are NOT persisted (only used for that specific query)
- Hybrid responses: workflow part first, then Q&A part
- Zero additional LLM cost (extends existing extraction schema)

**Files Created:**
- `backend/workflows/qna/conjunction.py` - Q&A conjunction analysis (Case A/B/C)
- `backend/workflows/common/qna_composer.py` - Multi-variable response composition
- `tests/specs/ux/test_multi_variable_qna.py` - 22 test cases

**Files Modified:**
- `backend/llm/intent_classifier.py` - Added `spans_multiple_steps()`, `get_qna_steps()`, `QNA_TYPE_TO_STEP`
- `backend/workflows/qna/extraction.py` - Extended schema for temporary Q&A requirements
- `backend/workflows/qna/router.py` - Added `route_multi_variable_qna()` for conjunction-aware routing

**Tests Added:** 24 tests covering all conjunction cases and integration scenarios

### Fix: Per-Segment Condition Extraction

**Issue:** Conjuncted Q&A with different months per part (e.g., "What menus in January and what rooms in February?") was extracting the same month for all parts.

**Fix:** Updated `conjunction.py` to:
1. Split text into segments based on conjunctions ("and what", "and which", etc.) and sentence boundaries
2. Match each Q&A type to its relevant segment using keyword matching
3. Extract conditions per-segment instead of globally
4. Track used segments to handle duplicate Q&A types (e.g., "rooms in Jan and rooms in Feb")

**Files Modified:**
- `backend/workflows/qna/conjunction.py` - Added `_split_into_segments()`, updated `_find_matching_segment()` with segment tracking

**New Tests Added:**
- `test_different_months_per_segment` - Verifies menus→January, rooms→February
- `test_same_select_different_months_is_union` - Verifies Case C (or_union) detection

---

## 2025-12-11

### Enhancement: Debugger UI Typography & Visual Polish

**Task: Make debugger GUI more professional, readable, and modern**

Comprehensive visual overhaul of the debugger dashboard with better typography, spacing, and modern styling.

**Typography Changes:**
- Added Inter font from Google Fonts for modern, clean appearance
- Increased font sizes: titles 30→36px, body 14→15-16px, labels 10→13px
- Better font weights and letter-spacing for improved readability

**Layout Improvements:**
- Increased padding throughout (24→32px containers)
- More gap between elements (12→16-24px)
- Larger rounded corners (8→12-16px)
- Better visual hierarchy with proper spacing between sections

**Components Updated:**
- `layout.tsx` - Added Inter font from Google Fonts
- `globals.css` - Set Inter as default, added debug-page scrollbar styles
- `page.tsx` (landing) - Larger text, better spacing
- `NavCard.tsx` - Bigger icons (28px), larger titles (18px)
- `StatusBadges.tsx` - Larger badges with more padding
- `QuickDiagnosis.tsx` - Better visual hierarchy, larger buttons
- `ThreadSelector.tsx` - Cleaner input fields, proper sizing
- `StepFilter.tsx` - Better button sizing and spacing
- `DebugHeader.tsx` - Larger titles, better icon sizing
- `DetectionView.tsx` - Much better spacing, readable legend
- All subpage files - Consistent styling with inline fallbacks

**Technical:** All components use inline style fallbacks to ensure proper rendering even if Tailwind CSS fails to load (prevents SVG sizing issues seen in earlier version).

**Files Modified:**
- `atelier-ai-frontend/app/layout.tsx`
- `atelier-ai-frontend/app/globals.css`
- `atelier-ai-frontend/app/debug/page.tsx`
- `atelier-ai-frontend/app/debug/detection/page.tsx`
- `atelier-ai-frontend/app/components/debug/*.tsx` (8 component files)

---

### Feature: Duplicate Message Detection (UX)

**Task: Prevent confusing duplicate responses when client accidentally resends the same message**

Added detection for identical consecutive messages from clients. When a client sends the exact same message twice in a row (e.g., accidentally pasting the same email), the system now responds with a friendly clarification instead of processing the duplicate.

**Response:**
> "I notice this is the same message as before. Is there something specific you'd like to add or clarify? I'm happy to help with any questions or changes."

**Exclusions:** Duplicate detection is skipped for:
- Detours (when `caller_step` is set)
- Step 1 (intake - new events)

**Files Modified:**
- `backend/workflow_email.py:889-925` - Added duplicate detection logic after intake processing

---

### Enhancement: Offer Formatting - Deposit on Separate Lines

**Task: Improve readability of deposit information in offer emails**

Added visual separator between total and deposit info for clearer presentation:

```
Total: CHF 680.00
---
Deposit to reserve: CHF 204.00 (required before confirmation)
Deposit due by: 2025-12-24
```

**Files Modified:**
- `backend/workflows/groups/offer/trigger/process.py:1269-1274` - Added `---` separator between total and deposit

---

## 2025-12-10

### Enhancement: Room Search Intent Detection System (NLU)

**Task: Improve detection precision, eliminate overlap, and add missing intent categories**

Consolidated duplicate patterns from multiple modules into `keyword_buckets.py` (single source of truth) and added 5 new room search intent categories based on industry best practices.

**Files Modified:**

1. **`backend/workflows/nlu/keyword_buckets.py`** (lines 751-930)
   - Added `ACTION_REQUEST_PATTERNS`, `AVAILABILITY_TOKENS`, `RESUME_PHRASES` (consolidated)
   - Added `RoomSearchIntent` enum with 6 intent types
   - Added `OPTION_KEYWORDS` (EN/DE) - soft holds, tentative bookings
   - Added `CAPACITY_KEYWORDS` (EN/DE) - capacity/fit questions
   - Added `ALTERNATIVE_KEYWORDS` (EN/DE) - waitlist, alternatives
   - Added `ENHANCED_CONFIRMATION_KEYWORDS` (EN/DE) - strong confirmations
   - Added `AVAILABILITY_KEYWORDS` (EN/DE) - availability checks

2. **`backend/llm/intent_classifier.py`**
   - Updated imports to use consolidated patterns from keyword_buckets
   - Added 5 new Q&A types: `check_availability`, `request_option`, `check_capacity`, `check_alternatives`, `confirm_booking`
   - Updated `_step_anchor_from_qna()` routing for new types

3. **`backend/workflows/nlu/general_qna_classifier.py`** (line 38)
   - Updated import to use `ACTION_REQUEST_PATTERNS` from keyword_buckets

4. **`backend/workflows/nlu/__init__.py`**
   - Added exports for all new shared patterns

**Tests Added:**

- **`backend/tests/detection/test_room_search_intents.py`** (NEW - 44 tests)
  - `TestRequestOptionDetection` (7 tests)
  - `TestConfirmBookingDetection` (7 tests)
  - `TestCheckCapacityDetection` (7 tests)
  - `TestCheckAlternativesDetection` (8 tests)
  - `TestCheckAvailabilityDetection` (4 tests)
  - `TestStepAnchorRouting` (5 tests)
  - `TestIntentDisambiguation` (3 tests)
  - `TestNoFalsePositives` (3 tests)

**Files Deleted:**

- `backend/workflows/nlu/room_search_keywords.py` - content merged into keyword_buckets.py

**Why Each Change Improves Detection:**

| Change | Improvement |
|--------|-------------|
| Consolidate `_ACTION_PATTERNS` | Single source, no drift between modules |
| Add `REQUEST_OPTION` | Distinguishes "hold it" from "is it free?" |
| Add `CHECK_CAPACITY` | Direct capacity queries don't go through generic Q&A |
| Add `CHECK_ALTERNATIVES` | Waitlist/fallback requests get proper handling |
| Add `CONFIRM_BOOKING` | Strong signals like "green light" boost confidence |
| Fix `_step_anchor_from_qna` | New types route to correct workflow steps |
| Bilingual keywords (EN/DE) | German clients get same precision as English |

---

### Feature: Client Deposit Payment Button (Frontend + Backend)

**Task: Allow clients to pay deposits directly from the chat interface**

Added a "Pay Deposit" button that appears in the client chat UI when a deposit is required and unpaid. The button only appears at Step 4+ (after room selection and offer generation) since the deposit amount is calculated relative to the room price.

**Backend Changes (`backend/main.py`):**

1. **New Endpoint: `POST /api/event/deposit/pay`**
   - Accepts `event_id` from request body
   - Validates event exists and is at Step 4 or 5
   - Sets `deposit_info.deposit_paid = True` in the event record
   - Returns success message with amount paid

2. **Deposit Info in `/api/send-message` Response**
   - Added `deposit_info` field to response payload
   - **Step validation**: Only sends `deposit_info` when `current_step >= 4`
   - This prevents the Pay Deposit button from appearing before the offer is generated
   - Fields: `deposit_required`, `deposit_amount`, `deposit_due_date`, `deposit_paid`, `event_id`

**Frontend Changes (`atelier-ai-frontend/app/page.tsx`):**

1. **`sessionDepositInfo` State**
   - New state to track deposit info from workflow response
   - Updated in `handleSendMessage` when backend returns `deposit_info`

2. **`unpaidDepositInfo` Memo**
   - Combines deposit info from two sources:
     - HIL tasks (`task.payload.event_summary.deposit_info`)
     - Workflow response (`sessionDepositInfo`)
   - Step validation: Only shows button when `currentStep >= 4`
   - Returns null if deposit is paid or not required

3. **Pay Deposit Button**
   - Yellow/amber button in chat footer area
   - Shows amount (e.g., "Pay Deposit: CHF 204.00")
   - Includes due date if available
   - Calls `POST /api/event/deposit/pay` on click
   - Updates UI state on success

**Files Modified:**
- `backend/main.py:735-767` (deposit_info in send-message response)
- `backend/main.py:1655-1720` (deposit payment endpoint)
- `atelier-ai-frontend/app/page.tsx:228-232` (sessionDepositInfo state)
- `atelier-ai-frontend/app/page.tsx:864-890` (unpaidDepositInfo memo)
- `atelier-ai-frontend/app/page.tsx:1050-1100` (Pay Deposit button UI)

---

### Fix: Deposit Payment Endpoint 500 Error (List vs Dict)

**Bug:** Clicking "Pay Deposit" returned 500 Internal Server Error.

**Root Cause:** The deposit payment endpoint tried to call `.get(event_id)` on the events collection, but events are stored as a list, not a dictionary.

**Fix:** Changed to iterate through the list to find the event by `event_id`:
```python
# Before (broken)
event_entry = events.get(request.event_id)

# After (fixed)
events = db.get("events") or []
event_entry = None
for idx, event in enumerate(events):
    if event.get("event_id") == request.event_id:
        event_entry = event
        event_index = idx
        break
```

**Files Modified:**
- `backend/main.py:1668-1675`

---

### Fix: Deposit Payment Endpoint 400 Error (Step Validation)

**Bug:** After fixing the 500 error, clicking "Pay Deposit" returned 400 Bad Request.

**Root Cause:** The endpoint only allowed deposit payment at Step 4, but after offer acceptance the event advances to Step 5.

**Fix:** Changed step validation to allow both Step 4 and Step 5:
```python
# Before (too strict)
if current_step != 4:
    raise HTTPException(status_code=400, ...)

# After (correct)
if current_step not in (4, 5):
    raise HTTPException(status_code=400, ...)
```

**Files Modified:**
- `backend/main.py:1681`

---

### Fix: Pay Deposit Button Showing Too Early (Step 2)

**Bug:** The "Pay Deposit" button appeared at Step 2 (date selection), before any offer or pricing was calculated.

**Root Cause:** Backend was sending `deposit_info` in the `/api/send-message` response regardless of the current step, as long as it existed in the event record.

**Fix:** Added step validation to only send `deposit_info` at Step 4+:
```python
current_step = event.get("current_step", 1)
# Only include deposit info at Step 4+ (after room selection and offer generation)
if current_step >= 4:
    # ... include deposit_info
```

**Files Modified:**
- `backend/main.py:743-757`
- `atelier-ai-frontend/app/page.tsx:870-878` (additional frontend validation for tasks)

---

### Fix: Deposit Config Not Persisting in Database

**Root Cause:** The `save_db()` function in `backend/workflows/io/database.py` was explicitly constructing the output dict with only `events`, `clients`, and `tasks`, discarding the `config` section. When the API set the deposit config via POST `/api/config/global-deposit`, it was saved initially, but any subsequent workflow database save would overwrite it without the config.

**Fix:** Added `config` key to the `out_db` dictionary in `save_db()`:
```python
out_db = {
    "events": db.get("events", []),
    "clients": db.get("clients", {}),
    "tasks": db.get("tasks", []),
    "config": db.get("config", {}),  # NEW: preserve config section
}
```

**Files Modified:**
- `backend/workflows/io/database.py:117-122`

**Verified with E2E Test:**
- Full Laura workflow (Steps 1-5) with 30% deposit configured
- Deposit info now correctly attached to event: CHF 204.00 (30% of CHF 680.00)
- Config persists across workflow saves
- HIL task contains full message with products and pricing

---

### Fix: Frontend HIL Task Using Wrong Field Name

**Issue:** Frontend was looking for `draft_msg` but backend sends `draft_body` for full message content.

**Fix:** Changed priority in `page.tsx:1183-1184`:
```typescript
const draftMsg = task.payload?.draft_body || (task.payload as any)?.draft_msg || task.payload?.snippet || '';
```

**Files Modified:**
- `atelier-ai-frontend/app/page.tsx:1183-1184`

---

### Fix: Step 2 Date Confirmation Unconditionally Requiring HIL

**Root Cause:** Commit b59100ce (Nov 17, 2025) introduced `requires_approval = True` unconditionally for date confirmation drafts, while the intent was only to escalate to HIL after ≥3 failed attempts. The `thread_state` was correctly conditional on `escalate_to_hil`, but `requires_approval` was not.

**Fix:** Changed line 1595 in `backend/workflows/groups/date_confirmation/trigger/process.py`:
- Before: `draft_message["requires_approval"] = True`
- After: `draft_message["requires_approval"] = escalate_to_hil`

**Files Modified:**
- `backend/workflows/groups/date_confirmation/trigger/process.py:1595-1597`
- `docs/TEAM_GUIDE.md` (added bug documentation)

### Fix: Frontend HIL Task Display (Full Messages)

**Issue:** HIL task messages were truncated with collapsible UI, making it hard to review full drafts.

**Fix:** Changed frontend to show full `draft_msg` instead of truncated `snippet`:
- Priority changed from `snippet || draft_msg` to `draft_msg || snippet`
- Removed collapsible `<details>` element
- Removed `max-h-40` height limit

**Files Modified:**
- `atelier-ai-frontend/app/page.tsx:~1183`

### Feature: HIL Toggle for All LLM Replies

**Task: Implement optional HIL approval for every AI-generated outbound reply**

Added a toggle that, when enabled, routes ALL AI-generated replies through a separate "AI Reply Approval" HIL queue before being sent to clients. This is separate from existing HIL flows (offers, dates) which handle client-initiated actions.

**Toggle Configuration:**
- Environment variable: `OE_HIL_ALL_LLM_REPLIES=true|false`
- Default: `false` (current behavior unchanged)
- Set to `true` when integrating with frontend for full manager control

**Files Modified:**

1. **`backend/workflows/io/integration/config.py`**
   - Added `hil_all_llm_replies` config field
   - Added `is_hil_all_replies_enabled()` helper function

2. **`backend/domain/vocabulary.py`**
   - Added `AI_REPLY_APPROVAL` TaskType enum value

3. **`backend/workflows/io/integration/hil_tasks.py`**
   - Added `AI_REPLY_TASKS = "AI Reply Approval"` category (separate GUI section)
   - Added `HILAction.APPROVE_AI_REPLY` action type
   - Added `create_ai_reply_approval_task()` builder function
   - Fixed: Changed from `pytz` to `zoneinfo.ZoneInfo` for timezone handling

4. **`backend/workflow_email.py`**
   - Modified `_build_return_payload()` to check toggle
   - When ON: creates `hil_ai_reply_approval` action instead of `send_reply`
   - Added `edited_message` parameter to `approve_task_and_send()`

5. **`backend/main.py`**
   - Added `edited_message` field to `TaskDecisionRequest` model
   - Updated `/api/tasks/{task_id}/approve` endpoint to pass `edited_message`

**Key Architectural Decisions:**
- **Separate category**: AI replies go to "AI Reply Approval" category, NOT mixed with client tasks (offers, dates)
- **Editable**: Manager can edit AI draft before approving
- **Backwards compatible**: Toggle OFF = exact current behavior
- **Two-tier HIL**: Step-specific tasks (Tier 1) ALWAYS run via `_enqueue_hil_tasks()`. AI reply approval (Tier 2) is ADDITIONAL when toggle ON. Never skip Tier 1 for Tier 2.

**Frontend Changes:**
- AI Reply Approval section (green, right column): Only visible when toggle ON
- Client HIL Tasks section (purple, below chat): Always visible when step-specific tasks exist

**Documentation:**
- Added "HIL Toggle System" section to `docs/TEAM_GUIDE.md`

---

## 2025-12-09

### Feature: Supabase Integration Layer (Toggle-Based)

**Task: Prepare codebase for frontend/Supabase integration without breaking current functionality**

Created a complete integration layer that can be toggled on/off via environment variable. Current JSON-based workflow continues to work unchanged.

**New Files (`backend/workflows/io/integration/`):**

1. **`config.py`** — Toggle configuration
   - `OE_INTEGRATION_MODE=json` (default) or `supabase`
   - Environment-based config for team_id, user_id, Supabase credentials
   - Feature flags for gradual rollout

2. **`field_mapping.py`** — Column name translations
   - `organization` → `company`
   - `chosen_date` → `event_date`
   - `number_of_participants` → `attendees`
   - Layout capacity mappings (theatre → theater_capacity)

3. **`uuid_adapter.py`** — UUID handling
   - Client lookup by email → UUID
   - Room/product slug → UUID registry
   - Caching for performance

4. **`status_utils.py`** — Status normalization
   - `Lead` ↔ `lead` bidirectional conversion
   - Covers events, clients, offers, tasks

5. **`offer_utils.py`** — Offer formatting
   - `generate_offer_number()` → `OE-2025-12-XXXX` format
   - Line item creation helpers
   - Deposit calculations

6. **`hil_tasks.py`** — HIL task templates
   - Message approval tasks (MVP requirement)
   - Offer approval tasks
   - Room/date confirmation tasks

7. **`supabase_adapter.py`** — Supabase operations
   - Same interface as `database.py`
   - Translates internal ↔ Supabase schemas

8. **`adapter.py`** — Main switcher
   - Routes to JSON or Supabase based on config
   - `db` proxy for easy usage

**How to Use:**

```bash
# Current behavior (default)
export OE_INTEGRATION_MODE=json
# or just don't set it

# Switch to Supabase
export OE_INTEGRATION_MODE=supabase
export OE_SUPABASE_URL=https://xxx.supabase.co
export OE_SUPABASE_KEY=your-key
export OE_TEAM_ID=your-team-uuid
export OE_SYSTEM_USER_ID=your-system-user-uuid
```

**No changes to existing code required** — integration layer is additive only.

---

### Change: Room Selection Now Sets Status to Option

**Task: Set event status to Option when room is selected (Step 3)**

Previously, events stayed as "Lead" all the way through offer sending, only becoming "Option" when client explicitly confirmed. This made conflict detection impossible until very late.

**New Behavior:**
- Step 1-2 (Intake, Date): Status = **Lead**
- Step 3 (Room selected): Status = **Option** ← Calendar blocked!
- Step 5-7 (Confirmation): Status = **Confirmed**

**Files Modified:**
- `backend/workflows/planner/smart_shortcuts.py` — `_apply_room_selection()` now sets `status="Option"`
- `backend/workflows/groups/room_availability/trigger/process.py` — Two room selection paths now set `status="Option"`

**Impact:**
- Conflict detection now works at room selection time (not just confirmation)
- Calendar shows "Option" blocks earlier in the booking process
- Soft conflicts can be detected between two clients both selecting same room

---

### Feature: Room Conflict Detection and Resolution

**Task: Implement conflict handling for room reservations between multiple clients**

Implemented a comprehensive conflict detection system that handles two scenarios:
1. **Soft Conflict (Option + Option)**: Two clients both have Option status on same room/date
2. **Hard Conflict (Option + Confirm)**: Client tries to confirm when another has Option

**New Files:**

1. **Conflict Detection Module** (`backend/workflows/common/conflict.py`)
   - `ConflictType` enum: NONE, SOFT, HARD
   - `detect_room_conflict()` — Check if another event has same room locked on same date
   - `detect_conflict_type()` — Distinguish soft vs hard conflicts based on action
   - `get_available_rooms_on_date()` — Get rooms NOT locked by other events
   - `compose_soft_conflict_warning()` — Warning for Option + Option scenario
   - `compose_hard_conflict_block()` — Block message for Option + Confirm scenario
   - `compose_conflict_warning_message()` — General conflict warning
   - `compose_conflict_hil_task()` — Create HIL task for conflict resolution
   - `handle_soft_conflict()` — Proceed with warning, create HIL notification
   - `handle_hard_conflict()` — Block or create HIL task based on client reason
   - `handle_loser_event()` — Redirect loser to Step 2 or 3
   - `notify_conflict_resolution()` — Resolve and notify both clients
   - `compose_winner_message()` — Message for winning client

2. **Conflict Tests** (`backend/tests/flow/test_room_conflict.py`)
   - 26 tests covering: detection, soft/hard handling, HIL tasks, loser paths, full flows
   - Tests for both scenarios (Option+Option, Option+Confirm)

**Backend Integration:**

1. **Room Availability (Step 3)** (`backend/workflows/groups/room_availability/trigger/process.py`)
   - Added soft conflict detection in `handle_select_room_action()`
   - When conflict detected: creates `soft_room_conflict_notification` HIL task
   - Neither client is notified — manager just gets visibility
   - Client still becomes Option (proceeds with warning flag)

2. **Offer Confirmation (Step 4/5)** (`backend/workflows/groups/event_confirmation/db_pers/post_offer.py`)
   - Added hard conflict detection in `_handle_confirm()`
   - If conflict found: blocks confirmation, asks for reason
   - If client insists with reason: creates `room_conflict_resolution` HIL task
   - Client waits for manager decision before confirmation can proceed

**Documentation Updates:**

1. **MANAGER_INTEGRATION_GUIDE.md** — Updated Decision 8 with:
   - Two conflict scenarios (Soft vs Hard)
   - Detailed flowchart showing conflict resolution
   - Open questions for soft conflict handling:
     - A) Keep current (HIL notify only)
     - B) Suggest alternative room
     - C) Block Client 2
     - D) Manager chooses response
   - Open question for manager manual input form

**Conflict Flow Summary:**

```
SOFT (Option + Option):
Client 2 selects room → HIL notification sent → Client 2 becomes Option → No blocking

HARD (Option + Confirm):
Client 2 confirms → Blocked → Ask for reason → HIL task created → Manager decides →
Winner proceeds / Loser redirected to Step 2 or 3
```

### Enhancement: Deposit Integration at Step 4

**Task: Attach deposit_info to events when offers are created**

**Backend Changes:**

1. **Offer Processing** (`backend/workflows/groups/offer/trigger/process.py`)
   - Import `build_deposit_info` from pricing module
   - After offer is recorded, call `build_deposit_info()` with global deposit config
   - Attach `deposit_info` to event entry at Step 4

---

## 2025-12-08

### Feature: Deposit Payment Workflow Integration

**Task: Complete deposit payment flow with mock payment and confirmation blocking**

Extended the deposit feature to include client-side payment flow, deposit status tracking, and confirmation gatekeeping. The system now requires deposit payment before allowing offer confirmation.

**Backend Changes:**

1. **Deposit Payment Endpoints** (`backend/main.py`)
   - `POST /api/event/deposit/pay` — Mark deposit as paid (mock payment for testing)
     - Only works at Step 4 (offer step)
     - Validates event exists and is at correct step
     - Updates event's `deposit_info.deposit_paid` and `deposit_info.deposit_paid_at`
   - `GET /api/event/{event_id}/deposit` — Get deposit status for an event
   - `DepositPaymentRequest` Pydantic model for payment requests

2. **Event Summary Enhancement** (`backend/main.py`)
   - Updated `/api/tasks/pending` to include `deposit_info` and `current_step` in event_summary
   - Deposit info includes: amount, VAT, due date, paid status, payment timestamp

3. **Pricing Module** (`backend/workflows/common/pricing.py`)
   - `SWISS_VAT_RATE = 0.081` constant
   - `calculate_deposit_amount()` — Compute deposit from total based on config
   - `calculate_deposit_due_date()` — Compute due date from deadline days
   - `build_deposit_info()` — Build complete deposit info dict
   - `format_deposit_for_offer()` — Format deposit for offer text

**Frontend Changes:**

1. **Interfaces** (`atelier-ai-frontend/app/page.tsx`)
   - `DepositInfo` interface with all deposit fields
   - Updated `PendingTaskPayload` to include `deposit_info` and `current_step`

2. **Pay Deposit Button** (`atelier-ai-frontend/app/page.tsx`)
   - Appears in Tasks panel when deposit is required
   - Only enabled at Step 4 (offer step)
   - Greyed out on detour (not at Step 4)
   - Shows deposit amount, due date, and payment status
   - Calls `POST /api/event/deposit/pay` on click
   - State transitions: Pending → Processing → Paid

3. **Confirmation Blocking** (`atelier-ai-frontend/app/page.tsx`)
   - `unpaidDepositInfo` computed value checks all tasks for unpaid deposits
   - `canConfirmBooking` gate prevents Accept button if deposit unpaid
   - Shows template-based reminder message (not LLM) per DECISION-002
   - Accept button disabled with tooltip when deposit required

4. **Deposit Status Display** (`atelier-ai-frontend/app/page.tsx`)
   - Yellow box (pending) / Green box (paid) in task cards
   - Shows deposit amount, due date, and status
   - Updates in real-time after payment

**Template Message (per DECISION-002):**
```
To confirm your booking, please complete the deposit payment first.
Once your deposit of {amount} is received, you can proceed with the confirmation.

If you have any questions about the payment process, please let us know.
```

**Decision Tracking:**
- Created `OPEN_DECISIONS.md` with:
  - DECISION-001: Deposit changes after payment (open)
  - DECISION-002: LLM vs template for reminders (decided: template)
  - DECISION-003: Payment verification in production (open)
  - DECISION-004: Deposit display format (decided)

**Workflow Rules:**
- Deposit button only visible when `deposit_info.deposit_required = true`
- Button only enabled at Step 4 (offer step)
- On detour (step changes), button is greyed out (payment status persists but re-payment may be needed)
- Accept button blocked until deposit marked as paid

**Files touched:**
- `backend/main.py` (deposit endpoints, event summary)
- `backend/workflows/common/pricing.py` (deposit calculations)
- `atelier-ai-frontend/app/page.tsx` (Pay Deposit button, confirmation blocking)
- `OPEN_DECISIONS.md` (new file for decision tracking)

---

### Feature: Global Deposit Configuration for Manager

**Task: Add deposit settings to manager section for integration readiness**

Implemented a global deposit configuration system that allows managers to set default deposit requirements for all offers. The feature is designed to integrate seamlessly with the main OpenEvent frontend.

**Frontend Changes:**

1. **DepositSettings Component** (`atelier-ai-frontend/app/components/DepositSettings.tsx`) - NEW
   - Toggle to enable/disable deposit requirement
   - Deposit type selection: Percentage or Fixed Amount
   - Percentage input (1-100%) or Fixed CHF amount
   - Payment deadline selector (7/10/14/30 days)
   - Preview box showing calculated deposit
   - Compact mode for inline display
   - Full edit mode with save/cancel

2. **Main Page Integration** (`atelier-ai-frontend/app/page.tsx`)
   - Added DepositSettings component in manager section
   - Displays above the Tasks panel in compact mode

3. **RoomDepositSettings Component** (`atelier-ai-frontend/app/components/RoomDepositSettings.tsx`) - NEW (INACTIVE)
   - Prepared for future integration with room-specific deposits
   - Inline and full display modes
   - Not imported anywhere (inactive) with integration comments

**Backend Changes:**

1. **Pydantic Model** (`backend/main.py`)
   - `GlobalDepositConfig` model with deposit_enabled, deposit_type, deposit_percentage, deposit_fixed_amount, deposit_deadline_days

2. **API Endpoints** (`backend/main.py`)
   - `GET /api/config/global-deposit` — Get current deposit config
   - `POST /api/config/global-deposit` — Save deposit config

3. **Room-Specific Endpoints** (INACTIVE - commented out)
   - `GET /api/config/room-deposit/{room_id}` — Prepared for integration
   - `POST /api/config/room-deposit/{room_id}` — Prepared for integration

**Data Format (matches real frontend):**
```typescript
{
  deposit_enabled: boolean,
  deposit_type: "percentage" | "fixed",
  deposit_percentage: number,      // 1-100
  deposit_fixed_amount: number,    // CHF
  deposit_deadline_days: number    // days until payment due
}
```

**Storage:**
- Global deposit stored in workflow database under `config.global_deposit`
- Room-specific deposits (future) under `config.room_deposits[room_id]`

**Integration Notes:**
- All components include detailed comments for frontend integrators
- Data formats match the real OpenEvent frontend's deposit structure
- Room-specific deposits can override global setting when activated
- Search for "INTEGRATION NOTE" or "RoomDepositSettings" when ready to integrate

**Files touched:**
- `atelier-ai-frontend/app/components/DepositSettings.tsx` (NEW)
- `atelier-ai-frontend/app/components/RoomDepositSettings.tsx` (NEW - inactive)
- `atelier-ai-frontend/app/page.tsx`
- `backend/main.py`

---

## 2025-12-03

### Fix: Step 5 (Negotiation) Now Detects Date Changes from Message Text

**Problem:** When a client at Step 5 (after offer shown) requested a date change (e.g., "sorry made a mistake, wanted 2026-02-28 instead"), the workflow would return a generic fallback message instead of routing back to Step 2.

**Root Cause:** Step 5's `_detect_structural_change()` only checked `state.user_info.get("date")` but this field wasn't populated because:
1. The LLM extraction found the new date
2. But it was skipped because `event_date` already had a value
3. So `state.user_info` never received the new date

**Solution:** Updated `_detect_structural_change()` to also parse dates directly from the message text (same pattern as Steps 2/3/4). If any date in the message differs from `chosen_date`, it triggers a detour to Step 2.

**Files:**
- `backend/workflows/groups/negotiation_close.py` (added message_text parameter and direct date parsing)

---

### Fix: Skip Duplicate Date Detour - Multi-Date Matching

**Problem:** The skip-duplicate-detour logic in Step 3 was checking only `message_dates[0]` which could be today's date (parsed erroneously), causing the skip to fail even when the correct date was in the message.

**Solution:** Changed the check from `message_dates[0] == chosen_date` to `chosen_date in message_dates`. This correctly handles cases where multiple dates are parsed from the message.

**Files:**
- `backend/workflows/groups/room_availability/trigger/process.py` (improved date matching logic)

---

### Fix: Client Reset Now Matches Events by event_data.Email

**Problem:** The client reset endpoint wasn't deleting all events because it only checked `client_id` but events store the email in `event_data.Email`, not at the top level.

**Solution:** Updated reset endpoint to match events by BOTH `client_id` AND `event_data.Email`.

**Files:**
- `backend/main.py` (improved `reset_client` event matching logic)

---

### Testing: Reset Client Data Button

**Task:** Add ability to reset all database entries for a client during testing

Added a "Reset Client" button to the frontend (in the Tasks panel) that allows testers to clear all data for the current client's email address. This is useful for re-running test scenarios without stale data (like `date_proposal_attempts` counter).

**Backend:** `POST /api/client/reset`
- Takes `email` parameter
- Deletes: client entry, all events, all tasks for that email
- Returns count of deleted items

**Frontend:** Red "Reset Client" button in Tasks panel
- Shows confirmation dialog before deleting
- Clears frontend state after successful reset
- Disabled until a conversation is started

**Files:**
- `backend/main.py` (new `ClientResetRequest` model + `/api/client/reset` endpoint)
- `atelier-ai-frontend/app/page.tsx` (new button + `resetClientData` function)

---

### Silent Ignore for Nonsense & Off-Topic Messages (No Reply Mechanism)

**Task: Prevent agent from replying to messages with zero workflow relevance throughout the entire workflow**

Implemented a cost-efficient two-layer nonsense/off-topic detection system that works throughout all workflow steps without adding extra LLM calls. The system reuses existing classification confidence scores from step handlers.

**Architecture (No Extra LLM Calls):**
```
LAYER 1: Regex gate (FREE) - in classify_intent()
├── is_gibberish(msg)? → IGNORE immediately (no LLM ever runs)

LAYER 2: Reuse existing step confidence (no extra LLM)
├── Each step handler already classifies → use that confidence
├── Low conf + no workflow signal → IGNORE or HIL
```

**Decision Matrix:**
| Confidence | Workflow Signal | Action |
|------------|-----------------|--------|
| Any        | YES             | Proceed normally |
| < 0.15     | NO              | IGNORE (silent, no reply) |
| 0.15-0.25  | NO              | Defer to HIL (borderline) |
| >= 0.25    | NO              | Proceed |

**Examples - IGNORED (no reply):**
- `"asdfghjkl"` → gibberish, no workflow signal
- `"I love Darth Vader"` → off-topic, no workflow signal
- `"hahahaha"` → no workflow signal

**Examples - PROCESSED (has workflow signal):**
- `"hahahaha. ok confirm date"` → has "confirm" signal
- `"yes"` → has "yes" signal
- `"what rooms are free?"` → has "rooms" + "free" signals

**Changes:**

1. **Confidence Module** (`backend/workflows/common/confidence.py`)
   - `NONSENSE_IGNORE_THRESHOLD = 0.15` - below this: silent ignore
   - `NONSENSE_HIL_THRESHOLD = 0.25` - below this but above ignore: defer to HIL
   - `check_nonsense_gate(confidence, message_text)` - returns: proceed/ignore/hil
   - `WORKFLOW_SIGNALS` - comprehensive EN/DE regex patterns for workflow-relevant content
   - `has_workflow_signal(text)` - returns True if ANY workflow pattern matches
   - `is_gibberish(text)` - heuristics for keyboard mashing, repeated chars

2. **Intent Classifier** (`backend/llm/intent_classifier.py`)
   - Added early gate in `classify_intent()` before `_agent_route()` LLM call
   - Gibberish caught by regex → returns `"nonsense"` immediately (saves LLM cost)

3. **Step Handlers** (all updated with nonsense gate):
   - `backend/workflows/groups/date_confirmation/trigger/process.py` (Step 2)
   - `backend/workflows/groups/room_availability/trigger/process.py` (Step 3)
   - `backend/workflows/groups/offer/trigger/process.py` (Step 4)
   - `backend/workflows/groups/negotiation_close.py` (Step 5)
   - `backend/workflows/groups/event_confirmation/trigger/process.py` (Step 7)
   - Each step now calls `check_nonsense_gate()` using its existing confidence score
   - Returns `GroupResult(action="nonsense_ignored")` for silent ignore
   - Returns `GroupResult(action="nonsense_hil_deferred")` for borderline cases

4. **Tests** (`backend/tests/detection/test_low_confidence_handling.py`)
   - `TestWorkflowSignalDetection` - 7 tests for workflow pattern matching
   - `TestGibberishDetection` - 5 tests for keyboard mash detection
   - `TestSilentIgnore` - 8 tests for ignore logic
   - `TestCheckNonsenseGate` - 7 tests for step handler decision function

**Cost Savings:**
- Gibberish: **100% LLM cost saved** (regex catches early in classify_intent)
- Off-topic: **0% extra LLM** (uses existing step handler confidence)

**Files touched:**
- `backend/workflows/common/confidence.py`
- `backend/llm/intent_classifier.py`
- `backend/workflows/groups/date_confirmation/trigger/process.py`
- `backend/workflows/groups/room_availability/trigger/process.py`
- `backend/workflows/groups/offer/trigger/process.py`
- `backend/workflows/groups/negotiation_close.py`
- `backend/workflows/groups/event_confirmation/trigger/process.py`
- `backend/tests/detection/test_low_confidence_handling.py`

---

### Fix: Date Change from Step 3 Now Confirms Explicit Date

**Bug:** When client was at Step 3 (room availability) and said "id like to change to 2026-02-28", the system would:
1. Correctly detect the date change and route to Step 2
2. But then show date proposals instead of confirming the explicit date

**Root Cause:** `_range_query_pending()` was returning True because the original request had range tokens ("Wednesdays & Saturdays in February"), which forced `window = None` and triggered showing proposals.

**Fix:** Check if the **current message** contains an explicit date (`requested_client_dates`) BEFORE checking range_pending. If yes, skip range_pending and try to confirm the explicit date directly.

**File:** `backend/workflows/groups/date_confirmation/trigger/process.py` (line 941-944)

---

### Enhanced Detour Detection with Dual-Condition Logic

**Task: Reduce false positives in change/detour detection and add comprehensive EN/DE support**

Implemented a robust two-stage detection system that requires BOTH a revision signal (change verb OR revision marker) AND a bound target (explicit value OR anaphoric reference) before triggering a detour. This prevents pure Q&A questions from being misclassified as change requests.

**Problem Solved:**
- Client messages like "What rooms are free?" were sometimes triggering detours
- No support for German change patterns
- No disambiguation when client provides a value without specifying the type (e.g., "change to 2026-02-14" - is it event date or site visit date?)
- No way to handle implicit targets (value without explicit type mention)

**Changes:**

1. **New Keyword Buckets Module** (`backend/workflows/nlu/keyword_buckets.py`)
   - Comprehensive EN/DE keyword patterns from UX analysis
   - `DetourMode` enum (LONG/FAST/EXPLICIT) for three detour initiation modes
   - `MessageIntent` enum for multi-class intent classification
   - `compute_change_intent_score()` - main dual-condition detection
   - `has_revision_signal()`, `has_bound_target()`, `is_pure_qa()` helpers

2. **Enhanced Change Propagation** (`backend/workflows/change_propagation.py`)
   - `EnhancedChangeResult` dataclass with rich detection info
   - `detect_change_type_enhanced()` - dual-condition detection
   - `AmbiguousTargetResult` for handling implicit targets
   - `resolve_ambiguous_target()` - recency-based disambiguation
   - `detect_change_type_enhanced_with_disambiguation()` - full detection with disambiguation

3. **Updated Semantic Matchers** (`backend/workflows/nlu/semantic_matchers.py`)
   - `matches_change_pattern_enhanced()` - new detection function
   - `is_pure_qa_message()` - Q&A filter helper

4. **Integrated into Workflow Triggers**
   - `backend/workflows/groups/date_confirmation/trigger/process.py`
   - `backend/workflows/groups/room_availability/trigger/process.py`
   - `backend/workflows/groups/offer/trigger/process.py`
   - `backend/workflows/groups/intake/trigger/process.py`

5. **Comprehensive Tests** (`backend/tests/detection/test_detour_detection.py`)
   - 56 test cases covering dual-condition, EN/DE, modes, Q&A filtering, ambiguity

**Detection Flow:**
```
Client Message
    ↓
Stage 1: Regex Pattern Scoring
├── Pure Q&A signals? → Route to Q&A (skip LLM)
├── Confirmation signals? → Route to confirm (skip LLM)
└── Dual condition met? (revision + target)
     ├── NO → Use preliminary intent
     └── YES → Check for ambiguity
              ├── Single target → Proceed with detour
              └── Multiple targets → Infer + add disambiguation message
```

**Disambiguation Logic:**
- If only ONE variable of a type exists → use it (no disambiguation)
- If MULTIPLE exist:
  - Check last step/Q&A context → infer from context
  - Check recency (which was confirmed more recently) → use closest
  - If still ambiguous → ask for clarification
- When inferring, append: "If you meant the **site visit date** instead, please write 'change site visit date'"

**Critical Fix: Skip Manual Review for Existing Events**

Fixed `intake/trigger/process.py` to skip the "is this an event request?" check when there's already an active event at step > 1. Previously, messages like "sorry - made a mistake. i wanted to book for 2026-02-28" were being sent to manual review because:
1. The "is this an event?" classification runs on ALL messages (wrong!)
2. Short messages got low confidence and triggered manual review

The fix is simple: the "is this an event?" check should ONLY apply to first messages (intake). Once an event exists at step 2+, messages should flow through to the step-specific handlers which have their own logic for detours, Q&A, confirmations, etc.

```python
# Line 767-771 in intake/trigger/process.py
skip_manual_review_check = linked_event and linked_event.get("current_step", 1) > 1

if not skip_manual_review_check and (not is_event_request(intent) or confidence < 0.85):
    # Only do manual review check for NEW events (intake)
```

**Files touched:**
- `backend/workflows/nlu/keyword_buckets.py` (NEW)
- `backend/workflows/change_propagation.py`
- `backend/workflows/nlu/semantic_matchers.py`
- `backend/workflows/groups/*/trigger/process.py` (4 files - including critical fix in intake)
- `backend/tests/detection/test_detour_detection.py` (NEW)

**Tests added/updated:**
- `test_detour_detection.py`: 56 new tests including:
  - `DET_DETOUR_DUAL_*`: Dual-condition logic tests
  - `DET_DETOUR_EN_*`: English change detection
  - `DET_DETOUR_DE_*`: German change detection
  - `DET_DETOUR_MODE_*`: Three detour modes
  - `DET_DETOUR_QA_*`: Q&A negative filter
  - `DET_DETOUR_AMBIG_*`: Ambiguous target resolution

---

### Verbalizer Safety Sandwich & Offer Structure Fix

**Task: Preserve structured offer data through verbalization**

Fixed the offer composition to only verbalize the introduction text while keeping line items, prices, and totals as structured content. Added a "safety sandwich" verification system that detects and patches fact errors without additional API calls.

**Problem Solved:**
- Offer was being fully verbalized, turning structured price lists into prose
- LLM could swap units ("per event" → "per person") corrupting pricing data
- No mechanism to catch or fix these errors

**Changes:**

1. **Offer Composition** (`backend/workflows/groups/offer/trigger/process.py`)
   - Split offer into verbalized intro + structured body
   - Only intro text goes through verbalizer
   - Line items, prices, total calculation remain as-is

2. **Hard Facts Extraction** (`backend/ux/universal_verbalizer.py`)
   - Added `units` extraction (per person, per event)
   - Added `product_names` extraction
   - Enhanced `extract_hard_facts()` to capture all pricing-critical data

3. **Fact Verification** (`backend/ux/universal_verbalizer.py`)
   - Added unit verification in `_verify_facts()`
   - Detects unit swaps (per person ↔ per event)
   - Detects missing/invented product names

4. **Fact Patching** (`backend/ux/universal_verbalizer.py`) - NEW
   - `_patch_facts()` surgically fixes LLM errors without API calls
   - Fixes unit swaps via regex replacement
   - Fixes single-amount errors when unambiguous
   - Re-verifies after patching to ensure correctness

5. **System Prompt Update** (`backend/ux/universal_verbalizer.py`)
   - Added rules 5-8 forbidding unit changes and requiring exact product names

**Flow:**
```
LLM Output → Verify Facts → [OK] → Return LLM text
                 ↓ FAIL
            Patch Facts → [OK] → Return patched text (no extra API call)
                 ↓ FAIL
            Return original fallback text
```

**Files touched:**
- `backend/workflows/groups/offer/trigger/process.py`
- `backend/ux/universal_verbalizer.py`

---

## 2025-12-02

### Snapshot-Based Info Page Links

**Task: Persistent links that don't overwrite each other**

Implemented a snapshot system so that info page links capture data at a specific point in time, allowing clients to revisit older links in the conversation.

**Problem Solved:**
- Previously, links used query params to re-fetch live data
- If workflow progressed, older links would show different (current) data
- Clients couldn't review earlier room options or offers

**Architecture:**
```
Workflow Step (e.g., room_availability)
    ↓
Build room data (same functions as verbalizer)
    ↓
├── Pass to Verbalizer → Abbreviated chat message
└── Create Snapshot → Store full data with unique ID
    ↓
Generate link: /info/rooms?snapshot_id=abc123
    ↓
Client clicks → Fetch snapshot → Display full table
```

**Implementation:**

1. **Snapshot Storage** (`backend/utils/page_snapshots.py`) - NEW
   - `create_snapshot(type, data, event_id, params)` → returns snapshot_id
   - `get_snapshot(snapshot_id)` → returns stored data
   - `list_snapshots(type, event_id)` → list available snapshots
   - Storage in `tmp-cache/page_snapshots/snapshots.json`
   - TTL-based expiration (7 days default)

2. **API Endpoints** (`backend/main.py`)
   - `GET /api/snapshots/{snapshot_id}` → full snapshot with metadata
   - `GET /api/snapshots/{snapshot_id}/data` → just the data payload
   - `GET /api/snapshots` → list snapshots with filters

3. **Pseudolinks Update** (`backend/utils/pseudolinks.py`)
   - Added `snapshot_id` parameter to `generate_room_details_link()`
   - Added `snapshot_id` parameter to `generate_qna_link()`
   - If snapshot_id provided: `/info/rooms?snapshot_id=X`
   - If not provided: falls back to query params

4. **Room Availability Integration** (`backend/workflows/groups/room_availability/trigger/process.py`)
   - Creates snapshot with `verbalizer_rooms`, `table_rows`, context
   - Passes snapshot_id to `generate_room_details_link()`
   - Same data source as verbalizer ensures consistency

5. **Frontend Update** (`atelier-ai-frontend/app/info/rooms/page.tsx`)
   - Checks for `snapshot_id` in query params first
   - If present: fetch from `/api/snapshots/{id}`
   - If not: fall back to current query-based fetch
   - Shows snapshot context (created timestamp, recommended room)

**Key Benefits:**
- Links are persistent - each has unique ID
- Client can revisit older links in chat
- Same data source as verbalizer (consistency)
- Reuses existing ranking/filtering functions

**Key Files Changed:**
- `backend/utils/page_snapshots.py` (new)
- `backend/main.py` (snapshot endpoints)
- `backend/utils/pseudolinks.py` (snapshot_id param)
- `backend/workflows/groups/room_availability/trigger/process.py`
- `atelier-ai-frontend/app/info/rooms/page.tsx`

---

### Dynamic Content Abbreviation for Non-Q&A Paths

**Task: Generalize content abbreviation for menu/catering display**

Extended the content abbreviation system (previously only in room_availability for Q&A) to work for all workflow steps that display detailed menu/catering information.

**Problem Solved:**
- Date confirmation step was showing full menu descriptions (640+ chars) directly in chat
- Only room_availability had threshold-based abbreviation with links
- No way to build link parameters from workflow state (only from Q&A q_values)

**Implementation:**

1. **Shared Short Format** (`backend/workflows/common/menu_options.py`)
   - Added `format_menu_line_short()` — abbreviated format (name + price only, no description)
   - Added `MENU_CONTENT_CHAR_THRESHOLD = 400` — UX standard threshold
   - Exported in `__all__` for reuse across workflow steps

2. **Date Confirmation Update** (`backend/workflows/groups/date_confirmation/trigger/process.py`)
   - Updated `_append_menu_options_if_requested()` to:
     - Check content length against threshold
     - Build link params from workflow state (event_entry, user_info, menu_request)
     - Use abbreviated format when exceeding threshold
     - Always include catering info page link for reference

3. **Room Availability Refactor** (`backend/workflows/groups/room_availability/trigger/process.py`)
   - Removed local `_short_menu_line()` function
   - Now uses shared `format_menu_line_short()` from menu_options
   - `QNA_SUMMARY_CHAR_THRESHOLD` now references shared constant

**Link Parameter Sources (non-Q&A path):**
- `event_entry.chosen_date` or `month_hint` → date/month
- `requirements.number_of_participants` → capacity
- `menu_request.vegetarian/wine_pairing/three_course` → dietary/course filters

**New Tests:**
- `tests/workflows/test_menu_abbreviation.py` — 14 tests covering:
  - Short format output validation
  - Threshold behavior (full exceeds, short stays under)
  - Link generation with query params
  - Menu request extraction

**Key Files Changed:**
- `backend/workflows/common/menu_options.py`
- `backend/workflows/groups/date_confirmation/trigger/process.py`
- `backend/workflows/groups/room_availability/trigger/process.py`
- `tests/workflows/test_menu_abbreviation.py` (new)

---

### Site Visit Implementation with Change Management

**Task: Enhanced site visit implementation plan with update/change/detour logic**

Extended the site visit functionality to support comprehensive change management:

**Key Enhancements:**
1. **Change Detection System**
   - Pattern-based detection for "change site visit", "reschedule", "cancel" requests
   - Change type classification: date, room, both, or cancel
   - Distinguishes changes from new requests

2. **Dependency Validation**
   - Room changes: validates new room on current date
   - Date changes: validates current room on new date
   - Both changes: suggests changing one at a time if conflict
   - Enforces constraint: site visit must be before main event

3. **Fallback Suggestions**
   - When requested change invalid, provides alternatives
   - Shows available dates for requested room
   - Shows available rooms for requested date

4. **Calendar Updates**
   - Updates existing calendar entry on changes
   - Cancels calendar entry on cancellation
   - Maintains change history for audit

**New/Updated Documentation:**
- `implementation_plans/site_visit_implementation_plan.md` — Phases 7-9 added for change management
- `backend/workflows/specs/site_visit_dag.md` — Created comprehensive DAG documentation

**Implementation Additions:**
- Site visit change detector patterns
- Dependency validation matrix
- Change application with conflict resolution
- Test cases for all change scenarios

**Frontend:**
- Created `/atelier-ai-frontend/app/info/site-visits/page.tsx` — Site visit information page
- Updated `backend/utils/pseudolinks.py` — Added site visit link generators

---

### Links, Test Pages, and Q&A Shortcuts

**Implemented**
- Added pseudolink utilities plus calendar logging stubs, and exposed `/api/test-data/*` endpoints with room, catering, and Q&A payloads (including full menus for long-form references).
- Built info pages for rooms, catering catalog/detail, and FAQ; rooms now show manager-configured items, prices, and room-specific catering menus (placeholder: all menus) with working links.
- Updated room-availability workflow to prepend a rooms-page link and to instruct the verbalizer to summarize long Q&A payloads with a shortcut link once text exceeds a 400-character threshold (tracked in `state.extras`, also embedded as a verbalizer note). Catering Q&A always includes the full-menu page link.

**UX**
- Dates on room pages now use month abbreviations (e.g., Sept).
- Q&A page renders full catering menus for Catering category requests so long answers can be offloaded to the page.

**Open TODO / Testing**
- Verbalizer still needs a dedicated path to honor the Q&A shortcut hint beyond inline instructions.
- Mapping of menus to rooms is currently a placeholder (all menus on all rooms) until manager-driven assignments are surfaced from the DB.
- Tests not run in this change set.

## 2025-12-01

### Site Visit Implementation Planning

**Task: Created implementation plan for site visit functionality**

Designed a comprehensive system for handling venue site visits as a Q&A-like thread that branches off from the main workflow:

**Key Features:**
1. **Detection System**
   - Pattern-based detection for "site visit", "venue tour", "viewing" requests
   - Distinguishes actual requests from Q&A about visits
   - Confidence scoring with room/date extraction

2. **Thread Architecture**
   - Site visits work like Q&A threads - branch off, complete, return to main flow
   - Gatekeeping: requires room (default from main flow) and date
   - Date constraints: before main event if date confirmed, otherwise any future date

3. **Smart Defaults**
   - Uses locked room from main flow if available
   - Client can override with explicit room mention
   - Proposes available weekday slots

4. **Calendar Integration**
   - Creates separate calendar entries with status="Option"
   - Tracks site visits independently from main event

**New Documentation:**
- `implementation_plans/site_visit_implementation_plan.md` — Complete implementation guide

**Proposed Architecture:**
- Site visit detector: `/backend/workflows/nlu/site_visit_detector.py`
- Thread manager: `/backend/workflows/threads/site_visit_thread.py`
- Frontend info page: `/app/info/site-visits/page.tsx`
- Integration with all workflow steps

**Key Design Decisions:**
- Site visit detection happens BEFORE general Q&A (no conflicts)
- Clear separation of visit dates/rooms from main event
- Seamless return to main flow with confirmation message
- Shortcuts allowed (confirm directly from proposed options)

**Implementation Phases:**
1. Detection & classification system
2. Thread management with gatekeeping
3. Workflow integration (all steps)
4. Frontend information pages
5. Testing suite

---

### Pseudolinks & Calendar Integration Planning

**Task: Created implementation plans for links/pages and calendar event integration**

Created comprehensive implementation plans for OpenEvent platform integration with two approaches:

1. **Approach 1: Pseudolinks** (Original plan)
   - Designed pseudolink structure with parameter passing (date, room, capacity)
   - Links to be added before existing detailed messages in agent replies
   - Easily replaceable with real platform URLs when ready

2. **Approach 2: Test Pages** (Enhanced plan - RECOMMENDED)
   - Create actual test pages to display room availability, catering menus, and Q&A
   - Build frontend pages that show raw data tables and detailed information
   - LLM verbalizer summarizes and reasons about this data in chat
   - Provides complete user experience for testing before platform integration

3. **Calendar Event Creation** (Both approaches)
   - Calendar events to be created when event reaches Lead status (Step 1)
   - Events updated when date confirmed (Step 2)
   - Status transitions tracked: Lead → Option → Confirmed

**New Documentation:**
- `implementation_plans/pseudolinks_calendar_integration.md` — Original pseudolinks approach
- `implementation_plans/test_pages_and_links_integration.md` — Enhanced test pages approach (recommended)

**Key Architecture (Test Pages Approach):**
- Chat messages show LLM reasoning and summaries (via verbalizer)
- Links lead to test pages with complete raw data
- Clear separation: reasoning (chat) vs. raw data (pages)
- Users get both concise summaries and detailed information

**Proposed Implementation:**
- Frontend pages: `/info/rooms`, `/info/catering/[menu]`, `/info/qna`
- Backend endpoints: `/api/test-data/rooms`, `/api/test-data/catering`, `/api/test-data/qna`
- Link generator: `backend/utils/pseudolinks.py` (generates real test page URLs)
- Calendar manager: `backend/utils/calendar_events.py`

**Benefits of Test Pages Approach:**
- Complete end-to-end testing of user experience
- Validates verbalizer properly summarizes complex data
- Working links improve testing and demos
- Easy migration to production platform

---

## 2025-11-27

### Safety Sandwich LLM Verbalizer

**New Feature: LLM-powered verbalization with fact verification**

The Safety Sandwich pattern enables warm, empathetic responses while guaranteeing hard facts (dates, prices, room names) are never altered or invented.

**Architecture:**
1. Deterministic engine builds `RoomOfferFacts` bundle (transient, not persisted)
2. LLM rewrites for tone while preserving facts
3. Deterministic verifier checks all facts present, none invented
4. On failure, falls back to deterministic template

**New Files:**
- `backend/ux/verbalizer_payloads.py` — Facts bundle types (RoomFact, MenuFact, RoomOfferFacts)
- `backend/ux/verbalizer_safety.py` — Verifier (extract_hard_facts, verify_output)
- `backend/ux/safety_sandwich_wiring.py` — Workflow integration helpers
- `backend/tests/verbalizer/test_safety_sandwich_room_offer.py` — 19 tests
- `backend/tests/verbalizer/test_safety_sandwich_wiring.py` — 10 tests

**Modified Files:**
- `backend/llm/verbalizer_agent.py` — Added `verbalize_room_offer()` entry point
- `backend/workflows/groups/room_availability/trigger/process.py:412-421` — Wired Safety Sandwich
- `backend/workflows/groups/offer/trigger/process.py:280-290` — Wired Safety Sandwich

**Test Results:** 29 Safety Sandwich tests pass, 161 detection/flow tests still pass

**Tone Control:**
```bash
VERBALIZER_TONE=empathetic # Human-like UX (NEW DEFAULT)
VERBALIZER_TONE=plain      # Deterministic only (for CI/testing)
```

### Universal Verbalizer (Human-Like UX)

**Enhancement: All client messages now go through the Universal Verbalizer**

The verbalization system was extended to transform ALL client-facing messages into warm, human-like communication:

**New Files:**
- `backend/ux/universal_verbalizer.py` — Core verbalizer with step-aware UX prompts
- `backend/tests/verbalizer/test_universal_verbalizer.py` — 19 tests

**Modified Files:**
- `backend/workflows/common/prompts.py` — Added `verbalize_draft_body()`, updated `append_footer()` with auto-verbalization

**Design Principles:**
1. Sound like a helpful human (conversational, not robotic)
2. Help clients decide (highlight recommendations with reasons)
3. Complete & correct (all facts preserved)
4. Show empathy (acknowledge needs)
5. Guide next steps clearly

**Test Results:** 209 tests pass (48 verbalizer tests + 161 detection/flow tests)

---

### Agent Tools Parity Tests

**New Test Module: `backend/tests/agents/`**
- Added `test_agent_tools_parity.py` — 25 tests validating tool allowlist enforcement, schema validation, and scenario parity
- Added `test_manager_approve_path.py` — 11 tests for HIL approval/rejection flows

**Test Coverage:**
- `PARITY_TOOL_001`: Tool allowlist enforced per step (Steps 2, 3, 4, 5, 7)
- `PARITY_TOOL_002`: Schema validation for required fields and formats
- `PARITY_TOOL_003`: Step policy consistency and idempotency
- `PARITY_SCENARIO_A`: Happy path Steps 1-4 tool execution
- `PARITY_SCENARIO_B`: Q&A tool triggering by step
- `PARITY_SCENARIO_C`: Detour scenario (requirements change)
- `APPROVE_HIL_001-004`: Manager approval/rejection flows

**Key Files:**
- `backend/agents/chatkit_runner.py` — Contains `ENGINE_TOOL_ALLOWLIST`, `TOOL_DEFINITIONS`, `execute_tool_call`
- `backend/agents/tools/` — Tool implementations (dates, rooms, offer, negotiation, transition, confirmation)

---

### Detection Logic Fixes

**Manager Request Detection — "real person" variant**
- Adjusted `_looks_like_manager_request` to capture "real person" variants (e.g., "I'd like to speak with a real person")
- Added regex pattern: `r"\b(speak|talk|chat)\s+(to|with)\s+(a\s+)?real\s+person\b"`
- File: `backend/llm/intent_classifier.py:229`
- Test: `test_DET_MGR_002_real_person` in `backend/tests/detection/test_manager_request.py`

**Parking Q&A Detection**
- Aligned parking Q&A detection with canonical `parking_policy` type
- Added keywords `" park"` (with leading space to avoid false positives) and `"park?"` to match "where can guests park?"
- File: `backend/llm/intent_classifier.py:157-158`
- Test: `test_DET_QNA_006_parking_question` in `backend/tests/detection/test_qna_detection.py`

### Test Results

All 161 detection and flow tests pass:
- `backend/tests/detection/` — 120 tests
- `backend/tests/flow/` — 19 tests
- `backend/tests/regression/` — 22 tests

---

## Prior Changes

See `docs/TEAM_GUIDE.md` for historical bug fixes and their corresponding tests.
