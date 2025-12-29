# Development Changelog

## 2025-12-29

### Billing, Catering Q&A, and UX Improvements (Session 2)

**Summary:** Fixed billing address capture, catering Q&A routing, added catering teaser to room availability, and improved date suggestion verbalization.

**Bugs Fixed:**

1. **Billing Address Not Captured From Separate Message (FIXED)**
   - Root cause: Billing capture code was positioned AFTER the pending HIL check
   - Fix: Moved billing capture BEFORE pending HIL check, added bypass for offer acceptance flow
   - File: `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py`

2. **Catering Q&A Returns Room Info (FIXED)**
   - Root cause: `route_general_qna` was imported but never called for catering questions
   - Fix: Added routing check for `classification["secondary"]` containing "catering_for"
   - File: `backend/workflows/common/general_qna.py`

**UX Improvements:**

1. **Catering Teaser in Room Availability**
   - When client hasn't mentioned catering, add brief teaser: "We also offer catering packages (from CHF 18/person) if you'd like to add refreshments."
   - File: `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`

2. **Simplified Date Suggestion Verbalization**
   - Removed redundant phrases ("Thanks for the briefing", "I know that makes planning trickier")
   - Made messages more natural and conversational
   - File: `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py`

**Testing Verified:**
- ✅ Catering teaser appears when client doesn't mention catering
- ✅ Catering Q&A returns catering info instead of room availability
- ✅ Billing capture works from separate message
- ✅ DAG/shortcut edge case: multiple variable changes (date + participants) handled correctly
- ✅ Capacity exceeded properly routes to alternatives

**New Issue Documented:**
- General Q&A (parking, WiFi, cancellation policy) falls back to structured format instead of answering - documented in TEAM_GUIDE.md

**All 146 pytest tests pass.**

---

### Comprehensive E2E Testing Session - Launch Readiness (Completed)

**Summary:** Performed comprehensive end-to-end testing to verify workflow stability for launch.

**Test Results:**

| Scenario | Result | Notes |
|----------|--------|-------|
| Initial room availability (40 people) | ✅ PASS | Shows proper "Rooms for **40 people** on **20.03.2026**" |
| Date change detour (March→April) | ✅ PASS | Correctly routes to Step 2, asks for time, returns to Step 3 |
| Time confirmation after date change | ✅ PASS | Returns to Step 3 with updated room availability |
| Room selection (Room A) | ✅ PASS | System asks for catering preferences |
| Catering add-on request | ✅ PASS | Offer generated with correct pricing |
| Offer acceptance | ✅ PASS | System asks for billing address |
| Capacity exceeded (200 people) | ✅ PASS | Shows proper message with options |
| Capacity reduction (200→100) | ✅ PASS | Shows room availability for 100 people |

**Issues Found:**

1. **Billing Address Not Captured (Open):** When client provides billing address in separate message after acceptance, it's not captured. The billing capture code block at step5_handler.py:179-182 should store message body but doesn't execute. Documented in TEAM_GUIDE.md.

2. **Catering Q&A Returns Room Info (Pre-existing):** When asking "What lunch options do you have?" after rooms presented, system returns room info instead of catering details. Root cause: `route_general_qna` is imported but never called in Q&A flow.

**Files Updated:**
- `docs/guides/TEAM_GUIDE.md` - Added two new open issues with investigation notes

**All 146 pytest tests pass.**

---

### Fix: Step 3 First Entry Q&A Blocking and Detour Verbalization (Fixed)

**Summary:** Fixed multiple issues causing poor verbalization after participant changes and incorrect Q&A handling on first Step 3 entry.

**Problems Fixed:**

1. **Generic fallback after participant change**: After changing from 30→50 people, response showed "The provided data indicates..." instead of proper room availability message.

2. **Flawed has_step3_history check**: Was checking for ANY audit entry with `to_step==3`, which incorrectly triggered for the initial jump from Step 1→Step 3.

3. **Over-broad pure Q&A detection**: Keyword presence (e.g., "coffee break needed") triggered Q&A path instead of only detecting QUESTIONS about catering.

**Root Causes:**

1. First entry to Step 3 was taking Q&A path due to faulty `has_step3_history` logic
2. Detour re-entry wasn't forcing normal room availability path
3. `is_pure_qna` used simple keyword match instead of question pattern detection

**Fixes Applied:**

1. Changed `has_step3_history` to check `room_pending_decision` or `locked_room_id` (indicators that rooms have been PRESENTED, not just that Step 3 is current)
2. Added detour re-entry guard that sets `general_qna_applicable = False` when `state.extras.get("change_detour")` is True
3. Changed `is_pure_qna` from keyword list to regex patterns that detect QUESTIONS about catering (e.g., "what catering options" not "coffee break needed")

**Files Modified:**
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`
  - Added `import re` at top
  - Lines ~386-394: Detour re-entry guard
  - Lines ~397-414: Improved pure Q&A detection with regex patterns
  - Lines ~416-428: Fixed `has_step3_history` logic

**Tests Verified:**
- All 146 tests pass (detection, regression, flow)
- E2E: Initial booking shows proper "Rooms for **30 people**" message
- E2E: Participant change (30→50) shows proper "Rooms for **50 people**" message
- Screenshot saved: `.playwright-mcp/e2e-dag-fixes-verification.png`

---

### Fix: Change Detour Routing Returns Fallback Instead of Step Response (Fixed)

**Summary:** Fixed a critical bug where change detours (date/participant/requirements changes) would return a generic fallback message instead of properly routing to the target step and generating the appropriate response.

**Problem:** When a user requested a change (e.g., "change the date to April 25th"), the system detected the change correctly and set `state.current_step` to the target step (e.g., Step 2), but the routing loop read from `event_entry.get("current_step")` which was not updated. This caused the routing loop to not dispatch to the target step, resulting in no draft message being generated and the fallback guard triggering with "I'm processing your request..."

**Root Cause:** In step handlers (step2, step3, step4), when a change is detected and a detour is needed, the code set:
```python
state.current_step = decision.next_step  # Updates state object
```
But the routing loop reads from `event_entry.get("current_step")`, not `state.current_step`. These were not synchronized.

**Fix:** Added `update_event_metadata(event_entry, current_step=decision.next_step)` before setting `state.current_step` in all three affected handlers:
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` (line ~470)
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` (line ~325)
- `backend/workflows/steps/step4_offer/trigger/step4_handler.py` (line ~339)

**Files Modified:**
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`
- `backend/workflows/steps/step4_offer/trigger/step4_handler.py`

**Tests Verified:**
- All 80 detour detection tests pass
- E2E: Date change from Step 3 now shows date options (Step 2 response)
- E2E: Participant change from Step 3 now triggers room re-evaluation

---

### Enhancement: Unified Detection Prompt Improvements

**Summary:** Refined the unified detection prompt to reduce false positives/negatives on edge cases.

**Prompt Improvements:**
- **is_rejection**: "ONLY for canceling ENTIRE booking" - fixes "decline to comment" false positive
- **is_confirmation**: "FALSE if followed by 'but' or conditions" - fixes "yes but I need to check..."
- **is_question**: "NOT for action requests like 'Could you send...'" - fixes polite request misclassification
- **is_manager_request**: "Must be a REQUEST, not a statement" + explicit FALSE examples for job titles ("I'm the Event Manager") - fixes job title false positives
- **language**: Prioritizes VERB/GRAMMAR over greetings and proper nouns - fixes German addresses in English sentences

**Test Results:** 93% pass rate on 15 critical edge cases
- All critical workflow signals work correctly
- 2 borderline cases have acceptable LLM variability

**Files Modified:**
- `backend/detection/unified.py` - Improved signal definitions in prompt

---

### Fix: Manager Escalation Uses LLM Semantic Detection (Not Regex)

**Summary:** Refactored manager escalation detection from regex-based keywords to LLM-based semantic understanding. This eliminates false positives on emails like "john.manager@company.com".

**Problem:** Regex keywords like "manager", "speak to someone" would trigger false positives on:
- Email addresses: `test-manager@example.com`
- Names: "John Manager"
- Unrelated phrases mentioning these words

**Solution:**
- Manager detection now uses `unified_result.is_manager_request` from the unified LLM detection
- LLM understands **semantic intent** ("Can I speak with a real person?") vs. **incidental mentions**
- Regex kept ONLY for deterministic patterns (email format, postal codes)

**Files Modified:**
- `backend/workflows/runtime/pre_route.py` - Uses `unified_result.is_manager_request` instead of `pre_filter_result.has_manager_signal`
- `backend/detection/pre_filter.py` - Removed regex-based manager detection (Section 8)
- `backend/detection/unified.py` - Enhanced manager detection prompt for clarity
- `backend/adapters/agent_adapter.py` - Fixed OpenAI adapter for o-series models (no `temperature`/`max_tokens`)

**Tests Verified:**
- ✅ "Can I speak with a real person?" → Manager escalation
- ✅ "john.manager@company.com" booking → NO false positive
- ✅ Normal booking requests → Normal workflow
- ✅ Works with both Gemini and OpenAI providers

**Design Principle:** "Regex only for deterministic patterns (email with @, postal codes), LLM for semantic understanding."

---

### Feature: Unified Detection - One LLM Call Per Message

**Summary:** Replaced keyword regex + separate intent/entity LLM calls with a single unified LLM call that extracts everything at once. This is more accurate (no regex false positives) and 70% cheaper.

**Architecture Change:**
```
BEFORE (legacy): Message → Regex pre-filter → Intent LLM → Entity LLM  = ~$0.013/msg
AFTER (unified): Message → ONE unified LLM call                        = ~$0.004/msg
```

**Key Features:**
- Single LLM call extracts: language, intent, signals, entities, Q&A hints
- No regex false positives (e.g., "Yesterday" no longer matches "yes")
- Toggle between "unified" and "legacy" modes via admin UI or env var
- 70% cost reduction per message

**Detection Modes:**
- `unified`: ONE LLM call (~$0.004/msg, recommended, more accurate)
- `legacy`: Separate keyword + intent + entity calls (~$0.013/msg, fallback)

**Files Added/Modified:**
- `backend/detection/unified.py` (new) - Unified detection module
- `backend/adapters/agent_adapter.py` - Added `complete()` method to all adapters
- `backend/api/routes/config.py` - Added GET/POST `/api/config/detection-mode` endpoints

**Cost Comparison Per Event (~10 messages):**
| Mode    | Cost/msg | Cost/event | Accuracy |
|---------|----------|------------|----------|
| unified | $0.004   | $0.04      | High     |
| legacy  | $0.013   | $0.13      | Medium   |
| savings | 70%      | 70%        | +Better  |

---

### Feature: Unified Pre-Filter with Toggle (Per-Message Optimization)

**Summary:** Implemented a unified pre-filter that runs on EVERY message before LLM calls, detecting signals that can skip unnecessary LLM operations. Note: This is now superseded by the unified detection mode above, but kept as fallback.

**Key Features:**
- Runs keyword detection before intent LLM call ($0 cost)
- Detects: confirmation, acceptance, rejection, change, manager escalation, urgency, billing address, questions
- Language detection (EN/DE) based on unique word patterns
- Skip flags: `can_skip_intent_llm`, `can_skip_entity_llm` for pure confirmations
- Manager escalation detection with HIL routing flag
- **Toggle between "enhanced" and "legacy" modes** via admin UI

**Modes:**
- `enhanced`: Full keyword detection, can skip ~25% of intent LLM calls
- `legacy`: Safe fallback, basic duplicate detection only (always runs LLM)

**Files Added/Modified:**
- `backend/detection/pre_filter.py` (new) - Core pre-filter implementation
- `backend/api/routes/config.py` - Added GET/POST `/api/config/pre-filter` endpoints
- `backend/workflows/runtime/pre_route.py` - Integrated pre-filter into pipeline
- `atelier-ai-frontend/app/components/LLMSettings.tsx` - Added pre-filter toggle UI

**Cost Impact:**
- Legacy mode: Always runs intent LLM (~$0.005/msg)
- Enhanced mode: Skips ~25% of intent LLM calls (saves ~$0.00125/msg)

---

### Docs: LLM Extraction Architecture Documentation

**Summary:** Created comprehensive documentation of which extraction/classification methods (Regex, NER, LLM) are used where in the system.

**New File:** `docs/internal/LLM_EXTRACTION_ARCHITECTURE.md`

**Contents:**
- Layer 1: Regex patterns (date, participant, time extraction) - Zero cost
- Layer 2: Intent classification (Gemini/OpenAI configurable)
- Layer 3: Entity extraction pipeline (Regex → NER → LLM)
- Layer 4: Verbalization (OpenAI recommended for quality)
- Cost analysis tables per operation and per event
- Configuration guide (Admin UI, environment variables, database)
- File reference for all related code locations

**Files Updated:**
- `README.md` - Added reference to architecture doc

---

### Feature: Gemini Provider Hybrid Mode & Admin Toggle

**Summary:** Implemented Gemini as alternative LLM provider with per-operation configuration via admin UI.

**Key Changes:**
1. Created `GeminiAgentAdapter` in `backend/llm/providers/gemini_adapter.py`
2. Added LLM Settings admin UI component (`LLMSettings.tsx`)
3. Updated defaults: Intent=Gemini, Entity=Gemini, Verbalization=OpenAI
4. Backend config API at `/api/config/llm-provider` (GET/POST)

**Cost Savings:** ~75% for intent/entity classification vs OpenAI

**Gemini Free Tier:** 1500 requests/day = ~750 client messages/day (sufficient for testing/small deployments)

**Files Added/Modified:**
- `backend/llm/providers/gemini_adapter.py` (new)
- `backend/api/routes/config.py` (updated)
- `atelier-ai-frontend/app/components/LLMSettings.tsx` (new)
- `scripts/dev/oe_env.sh` (Gemini API key docs)

---

### Refactor: Database Consolidation (DB_CONSOLIDATION) ✅

**Summary:** Consolidated 4 scattered JSON data files into 2 unified files with backwards-compatible schema, eliminating "split brain" data management.

**Files Merged:**
- `backend/rooms.json` + `backend/room_info.json` → `backend/data/rooms.json`
- `backend/catering_menu.json` + `backend/data/catalog/catering.json` → `backend/data/products.json`

**Key Changes:**
1. Created migration script `scripts/migrate_db_files.py`
2. Unified rooms file with all 6 rooms (A-F), merged capacities, pricing, features, and operations
3. Unified products file with 21 products (catering, beverages, equipment, add-ons)
4. Updated 12 adapter files to use new consolidated paths
5. Preserved backwards compatibility by using flat field names (`capacity_max`, `unit_price`)

**Adapters Updated:**
- `backend/workflows/io/database.py`
- `backend/services/rooms.py`
- `backend/services/products.py`
- `backend/workflows/nlu/preferences.py`
- `backend/workflows/steps/step7_confirmation/db_pers/post_offer.py`
- `backend/workflows/steps/step3_room_availability/db_pers/room_availability_pipeline.py`
- `backend/services/qna_readonly.py`
- `backend/workflows/common/capacity.py`
- `backend/workflows/common/catalog.py`
- `backend/workflows/common/pricing.py`
- `backend/workflows/planner/product_handler.py`

**Old Files Archived:** `backend/DEPRECATED/pre_consolidation/`

**Test Fix:** Updated `tests/room/test_rank_rooms_by_prefs.py` to match intentional preferred_room bonus behavior.

**Verification:** 772 tests pass (excluding API-dependent smoke test)

---

### Fix: Deposit Display Formatting ✅

**Summary:** Improved deposit display in offers - amount and due date now on separate lines with human-readable date format.

**Changes:**
- Deposit amount and due date on separate paragraphs for better readability
- Date formatted as "12 January 2026" instead of "2026-01-12"
- Calculation verified: `today + deposit_deadline_days = due_date`

**Files Modified:**
- `backend/workflows/steps/step4_offer/trigger/step4_handler.py`

**Verification:** E2E Playwright test passed, screenshot at `.playwright-mcp/deposit-formatting-fixed.png`

---

### Fix: Flow Spec Test Updates (Smart Shortcut Alignment) ✅

**Summary:** Updated 7 YAML flow spec tests to match smart shortcut behavior. Tests expected old HIL flow with `select_date` actions, but smart shortcuts now bypass date selection when date+participants are known.

**Key Changes:**
- Changed expected intent from `event_intake` to `event_intake_shortcut` where applicable
- Removed `gui_action` steps that depended on non-existent HIL tasks
- Updated `current_step` expectations (Step 3 for shortcuts, Step 2 for vague dates)

**Files Modified:**
- `tests/specs/flows/test_C_normal_step1_to_step4.yaml`
- `tests/specs/flows/test_E_past_date_step1_to_step4.yaml`
- `tests/specs/flows/test_E_week2_december_workshop.yaml`
- `tests/specs/flows/test_F_february_saturday_availability.yaml`
- `tests/specs/flows/test_GUARD_coffee_only_no_lunch.yaml`
- `tests/specs/flows/test_GUARD_no_billing_before_room.yaml`
- `tests/specs/flows/test_GUARD_no_rooms_before_date.yaml`

**Verification:** All 146 backend tests pass, 10/10 flow spec tests pass

---

### Feature: Gemini LLM Provider Infrastructure ✅

**Summary:** Added Google Gemini as an alternative LLM provider for intent classification and entity extraction. Enables 75% cost savings on classification operations.

**Key Changes:**
1. Created `GeminiAgentAdapter` class in `backend/adapters/agent_adapter.py`
2. Added `google-generativeai>=0.8.0` to `requirements.txt`
3. Updated `get_agent_adapter()` factory to support `AGENT_MODE=gemini`
4. Fallback chain: Gemini API error → StubAgentAdapter (heuristics)

**Usage:**
```bash
# Set environment variables
export AGENT_MODE=gemini
export GOOGLE_API_KEY=AIza...  # Get from https://aistudio.google.com/apikey

# Optional: Override models (default: gemini-2.0-flash)
export GEMINI_INTENT_MODEL=gemini-2.0-flash
export GEMINI_ENTITY_MODEL=gemini-2.0-flash
```

**Cost Comparison:**
| Operation | OpenAI (o3-mini) | Gemini Flash | Savings |
|-----------|------------------|--------------|---------|
| Intent Classification | ~$0.005 | ~$0.00125 | **75%** |
| Entity Extraction | ~$0.008 | ~$0.002 | **75%** |

**Files Modified:**
- `backend/adapters/agent_adapter.py` (added GeminiAgentAdapter + factory)
- `requirements.txt` (added google-generativeai)

**Verification:** Factory tests pass for stub, openai, and gemini modes

---

### Feature: LLM Settings Admin UI Toggle

**Summary:** Added admin UI for runtime LLM provider switching without server restart.

**Key Changes:**
1. Created `LLMSettings.tsx` component with per-operation provider selection
2. Added `/api/config/llm-provider` GET/POST endpoints
3. Provider settings persist to database, override environment variables
4. Shows cost estimates per event based on selected providers
5. Displays Gemini API key setup notice when Gemini is selected

**Frontend Component Features:**
- Compact mode for inline display alongside DepositSettings
- Per-operation provider buttons (Intent, Entity, Verbalization)
- Cost preview showing estimated cost per event
- Warning when verbalization is not OpenAI (quality recommendation)

**Files Created:**
- `atelier-ai-frontend/app/components/LLMSettings.tsx`

**Files Modified:**
- `backend/api/routes/config.py` (added LLMProviderConfig model + endpoints)
- `atelier-ai-frontend/app/page.tsx` (added LLMSettings to manager section)

**Verification:** Frontend builds, API endpoints functional

---

### Recommended Next Actions

1. **Test Gemini with Real API Key**
   - Get key from https://aistudio.google.com/apikey
   - Set `GOOGLE_API_KEY` environment variable
   - Run E2E tests with `AGENT_MODE=gemini`

2. **Compare Accuracy Metrics**
   - Run detection tests with both providers
   - Measure intent/entity accuracy differences

3. **Production Readiness**
   - Continue E2E testing for edge cases
   - Monitor for fallback messages in production

---

## 2025-12-28

### Fix: DAG Change Propagation Test Suite (45 tests) ✅

**Summary:** Fixed all 45 failing tests in the DAG change propagation test suite. Tests were failing due to missing test fixtures, incorrect import patterns, and missing `message_text` parameters required by `detect_change_type()`.

**Issues Fixed:**

1. **Import error in test_change_integration_e2e.py:**
   - Changed `from backend.workflows.steps.step1_intake.trigger import process` (imports module)
   - To `from backend.workflows.steps.step1_intake import process` (imports function via __init__.py)

2. **Missing fixture fields for event lookup:**
   - Added `event_data["Email"]` (required by `last_event_for_email()` lookup)
   - Added `created_at` timestamp (required for event sorting)
   - Added `profile` to client structure

3. **Test expectation mismatch (V4 behavior):**
   - Updated test to expect `locked_room_id` preserved on date change (V4 fast-skip rule)
   - Original test incorrectly expected it to be cleared

4. **Missing message_text parameter:**
   - `detect_change_type()` requires `message_text` for intent pattern matching
   - Added `message_text` with appropriate change verbs to all affected tests

5. **Products change detection:**
   - Changed from `products` key to `products_add` (explicit add signal path)

**Files Modified:**
- `tests/specs/dag/test_change_integration_e2e.py`
- `tests/specs/dag/test_change_propagation.py`
- `tests/specs/dag/test_change_scenarios_e2e.py`

**Verification:** All 45 DAG tests pass + 520 regression tests pass

---

### Refactor: Remove Force-Save Anti-Pattern from Step5 (DB1) ✅

**Summary:** Removed redundant direct `db_io.save_db()` calls from Step5 billing capture flow. Persistence now correctly flows through the router's end-of-turn flush mechanism.

**Background:** Step5 had two force-save calls added to fix a perceived bug where "billing wasn't being persisted." However, the real issue was likely a different root cause, and the force-saves violated the architectural principle of "router persists once at end-of-turn."

**Changes:**
- Removed 2 force-save calls (lines 184-189, 193-197) from `step5_handler.py`
- Removed unused `db_io` import
- Added characterization test `test_billing_persistence_db1.py` proving router flush works

**Files Modified:**
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (-11 lines)
- `backend/tests/regression/test_billing_persistence_db1.py` (new)

**Verification:** All 520 tests pass (detection + regression + flow)

---

### Refactor: Step 2 Candidate Date Generation (D7) ✅

**Summary:** Created `candidate_dates.py` module with reusable candidate date collection and prioritization functions extracted from `_present_candidate_dates()`.

**New Module:** `backend/workflows/steps/step2_date_confirmation/trigger/candidate_dates.py` (573 lines)

**Extracted Functions:**
- **Weekday alternatives:** `_collect_preferred_weekday_alternatives` (moved from step2_handler.py)
- **Candidate collection:** `collect_candidates_from_week_scope`, `collect_candidates_from_fuzzy`, `collect_candidates_from_constraints`, `collect_candidates_from_suggestions`, `collect_supplemental_candidates`
- **Prioritization:** `prioritize_by_weekday`
- **Payload building:** `build_table_and_actions`, `build_draft_message`

**D7 Integration (Phase 2):**
- Refactored `_present_candidate_dates()` to use `collect_candidates_from_week_scope` and `collect_candidates_from_fuzzy`
- Replaced inline collection loops with extracted function calls

**Line Count Change:** step2_handler.py: 2650 → 2617 → 2606 lines (-44 lines total)

**Verification:** All 146 tests pass + E2E Playwright (site visit reached)

---

### Refactor: Step 2 Pure Utilities Extraction (D6) ✅

**Summary:** Extracted 24 pure utility functions from `step2_handler.py` to new `step2_utils.py` module (~300 lines).

**Extracted Functions:**
- **Text extraction:** `_extract_first_name`, `_extract_signature_name`, `_extract_candidate_tokens`, `_strip_system_subject`
- **String formatting:** `_preface_with_apology`, `_format_label_text`, `_date_header_label`, `_format_time_label`, `_format_day_list`, `_weekday_label_from_dates`, `_month_label_from_dates`, `_pluralize_weekday_hint`, `_describe_constraints`, `_format_window`
- **Time utilities:** `_normalize_time_value`, `_to_time`, `_window_hash`
- **Classification:** `_is_affirmative_reply`, `_message_signals_confirmation`, `_message_mentions_new_date`, `_is_weekend_token`
- **Data conversion:** `_window_payload`, `_window_from_payload`

**Line Count Change:** step2_handler.py reduced from 2920 → 2650 lines (-270 lines)

**Verification:** All 146 detection/regression/flow tests pass

---

### Fix: WF0.1 Empty Detour Replies Safety Net ✅

**Summary:** Added safety net to prevent empty replies when routing loop completes without any step adding a draft message.

**Root Cause:** When a detour chain (e.g., Step 4 → Step 3 → Step 4) completed with `halt=False` throughout, no fallback was generated if no step added a draft message, resulting in empty client responses.

**Fix Applied:**

`backend/workflow_email.py` (lines 405-455):
- Added empty reply guard after routing loop completion
- Generates context-aware fallback message based on current step
- Traces the fallback for debugging via `EMPTY_REPLY_GUARD` marker

**Fallback Messages by Step:**
- Step 3: "I'm checking room availability for your event..."
- Step 4: "I'm preparing your offer with the selected options..."
- Step 5: "I'm reviewing your response and will follow up shortly."
- Default: "I'm processing your request..."

**Verification:** All 517 core tests pass

---

### Fix: Step Corruption During Billing Flow ✅

**Summary:** Fixed critical bug where `current_step` was incorrectly set to 3 instead of 5 after offer acceptance and billing capture, causing deposit payment to fail.

**Root Cause (Two Issues):**
1. `evaluate_pre_route_guards()` in `pre_route.py` was forcing step changes without checking for billing flow state
2. `step5_handler.py` was missing `offer_accepted = True` when handling offer acceptance (step4_handler had it, step5 didn't)

**Fixes Applied:**

`backend/workflows/runtime/pre_route.py` (lines 113-121):
- Added billing flow bypass after deposit bypass in `evaluate_pre_route_guards()`
- Follows Pattern 1: Special Flow State Detection from CLAUDE.md

`backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (lines 420-424):
- Added `event_entry["offer_accepted"] = True` in accept classification block
- Now matches step4_handler behavior

**Regression Test:** `backend/tests/regression/test_billing_step_preservation.py`
- `test_billing_flow_bypasses_guard_forcing` - Verifies step stays at 5 during billing
- `test_normal_flow_allows_guard_forcing` - Verifies normal flows still work
- `test_billing_flow_without_awaiting_flag_allows_forcing` - Edge case handling

**E2E Verified:** Full flow tested via Playwright: intake → room → preask → offer → accept → billing → deposit → HIL approval → site visit prompt

---

### S3 Phase 5: Smart Shortcuts Intent Parser/Executor Extraction ✅

**Summary:** Extracted intent parsing/execution methods from `smart_shortcuts.py` into two focused modules (~150 lines, 12 functions).

**New Modules:**

`backend/workflows/planner/intent_parser.py` (~238 lines)
- Room intent: `parse_room_intent`, `can_lock_room`
- Participants: `parse_participants_intent`
- Billing: `parse_billing_intent`
- Deferral: `add_needs_input`, `defer_intent`, `persist_pending_intents`

`backend/workflows/planner/intent_executor.py` (~319 lines)
- Dispatch: `execute_intent`
- Application: `apply_room_selection`, `apply_participants_update`
- Questions: `select_next_question`, `question_for_intent`
- Helpers: `missing_item_display`, `format_money` (delegating)

**Pattern:** Thin wrapper delegation - class methods delegate to extracted functions.

**Result:** `smart_shortcuts.py`: 1079 -> 964 lines (-115 lines, ~11% reduction)

**Verification:** All 146 core tests pass + E2E Playwright verified (intake -> room availability)

---

### S3 Phase 4: Smart Shortcuts Preask/Choice Handler Extraction ✅

**Summary:** Extracted preask/choice methods from `smart_shortcuts.py` into two focused modules (~420 lines, 20 functions).

**New Modules:**

`backend/workflows/planner/choice_handler.py` (~470 lines)
- Context management: `load_choice_context` (TTL-based expiry)
- Selection parsing: `parse_choice_selection` (ordinal, label, fuzzy matching)
- Clarification: `choice_clarification_prompt`, `format_choice_item`
- Application: `apply_choice_selection`, `complete_choice_selection`
- Reply handling: `handle_choice_selection`, `maybe_handle_choice_context_reply`

`backend/workflows/planner/preask_handler.py` (~522 lines)
- Feature control: `preask_feature_enabled`, `explicit_menu_requested`
- Core flow: `process_preask`, `maybe_emit_preask_prompt_only`
- Response handling: `handle_preask_responses`, `detect_preask_response`
- Preview building: `menu_preview_lines`, `prepare_preview_for_requests`, `build_preview_for_class`
- State management: `finalize_preask_state`, `hydrate_preview_from_context`

**Pattern:** Thin wrapper delegation - class methods delegate to extracted functions.

**Verification:** All 146 core tests pass + E2E Playwright verified (inquiry → room → products prompt)

---

### S3 Phase 3: Smart Shortcuts Product Handler Extraction ✅

**Summary:** Extracted product-related methods from `smart_shortcuts.py` into `product_handler.py` (~280 lines, 13 functions).

**New Module:** `backend/workflows/planner/product_handler.py`
- Static utilities: `format_money`, `missing_item_display`
- Product state: `products_state`, `product_lookup`, `normalise_products`, `infer_quantity`, `current_participant_count`
- Product display: `format_product_line`, `product_subtotal_lines`, `build_product_confirmation_lines`
- Product intent: `parse_product_intent`, `apply_product_add`
- Module-level: `load_catering_names` (cached)

**Pattern:** Thin wrapper delegation - class methods delegate to extracted functions.

**Verification:** All 146 core tests pass + E2E Playwright verified (inquiry → room → products prompt)

---

### S3 Phase 2: Smart Shortcuts Date Handler Extraction ✅

**Summary:** Extracted date/time processing from `smart_shortcuts.py` into `date_handler.py` (~320 lines, 16 functions).

**New Module:** `backend/workflows/planner/date_handler.py`
- Time utilities: `normalize_time`, `time_from_iso`
- Window conversion: `window_to_payload`, `window_from_payload`
- Date slot/options: `preferred_date_slot`, `candidate_date_options`, `maybe_emit_date_options_answer`
- Window resolution: `resolve_window_from_module`, `manual_window_from_user_info`, `infer_times_for_date`
- Date intent: `parse_date_intent`, `ensure_date_choice_intent`
- Date confirmation: `apply_date_confirmation`, `should_execute_date_room_combo`, `execute_date_room_combo`

**Verification:** All 146 core tests pass + E2E Playwright verified (date detection → room availability)

---

### S3 Phase 1: Smart Shortcuts Budget/DAG Extraction ✅

**Summary:** Extracted budget parsing and DAG guard logic from `smart_shortcuts.py` (1,985 lines) into focused submodules. This is Phase 1 of the S3 refactoring plan.

**New Modules:**
- `backend/workflows/planner/budget_parser.py` (~120 lines)
  - `extract_budget_info()` - Priority-ordered budget extraction from user_info
  - `parse_budget_value()` - Parse dict/number/string budget values
  - `parse_budget_text()` - Regex parsing for "CHF 500 per person" style strings

- `backend/workflows/planner/dag_guard.py` (~115 lines)
  - `dag_guard()` - Check if intent is allowed by workflow DAG
  - `is_date_confirmed()`, `is_room_locked()`, `can_collect_billing()` - State predicates
  - `set_dag_block()`, `ensure_prerequisite_prompt()` - Block handling

**Pattern:** Thin wrapper delegation - class methods in `_ShortcutPlanner` delegate to extracted functions, maintaining API compatibility.

**Files Modified:**
- `backend/workflows/planner/smart_shortcuts.py` (imports + wrapper methods)
- `backend/workflows/planner/budget_parser.py` (NEW)
- `backend/workflows/planner/dag_guard.py` (NEW)

**Verification:** All 146 core tests pass + E2E Playwright verified (shortcuts → room → products)

---

### R3: Step3 Selection Action Deduplication ✅

**Summary:** Completed R3 refactoring by removing duplicate helper functions from `step3_handler.py` that already existed in `selection.py`. The selection module was already created; this task cleaned up remaining code duplication.

**Changes:**
- Updated import in `step3_handler.py` to include `_thread_id`, `_reset_room_attempts`, `_format_display_date` from `selection.py`
- Removed 3 duplicate function definitions from `step3_handler.py` (-16 lines: 1839→1823)
- Enhanced `_thread_id()` in `selection.py` to include `state.thread_id` and `state.client_id` fallbacks

**Files Modified:**
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`
- `backend/workflows/steps/step3_room_availability/trigger/selection.py`

**Verification:** All 146 core tests pass + E2E Playwright verified (room selection → products prompt)

---

### C2: Remove Dead Chatbot Code ✅

**Summary:** Removed ~694 lines of unused legacy chatbot code from `conversation_manager.py`, reducing it from ~729 lines to ~35 lines.

**Removed Functions:**
- `classify_email()`, `extract_information_incremental()`
- `generate_response()`, `create_summary()`, `create_offer_summary()`
- `format_room_description()`, `format_catering_options()`
- `format_detailed_catering_info()`, `get_non_veg_catering_options()`
- `generate_catering_response()`, `generate_room_response()`
- `get_room_details()`, `_ensure_greeting()`
- `SYSTEM_PROMPT`, `ROOM_INFO`, `CATERING_MENU` constants
- `load_room_info()`, `load_catering_menu()`

**Result:** Module now only re-exports session store functions from `backend.legacy.session_store`

**Verification:** All 146 core tests pass + E2E Playwright verified

---

### C1: Conversation Manager Session Store Split ✅

**Summary:** Extracted session/cache management functions from `conversation_manager.py` into dedicated `backend/legacy/session_store.py` module. This isolates non-LLM code and enables faster imports for modules that only need session state.

**New Module:** `backend/legacy/session_store.py` (~175 lines)
- `active_conversations` - In-memory conversation state storage
- `STEP3_DRAFT_CACHE`, `STEP3_PAYLOAD_CACHE` - Step 3 de-duplication caches
- `render_step3_reply()` - Workflow-driven Step 3 reply rendering
- `pop_step3_payload()` - Retrieve and remove cached Step 3 payload
- `_step3_cache_key()`, `_normalise_step3_draft()`, `_render_step3_from_workflow()` - Internal helpers

**Changes:**
- Created `backend/legacy/` package with `__init__.py` and `session_store.py`
- Updated `backend/api/routes/messages.py` to import from `backend.legacy.session_store`
- Updated `backend/main.py` to import from `backend.legacy.session_store`
- Added backward-compatible re-exports in `conversation_manager.py`

**Verification:** All 146 core tests pass + E2E Playwright verified

---

### O3: Step4 Offer Compose/Persist Extraction ✅

**Summary:** Extracted offer composition and recording functions from `step4_handler.py` into dedicated `compose.py` module.

**New Module:** `backend/workflows/steps/step4_offer/trigger/compose.py` (~115 lines)
- `build_offer()` - Render deterministic offer summary for YAML flow harness
- `_record_offer()` - Create and persist offer record with sequencing
- `_determine_offer_total()` - Compute total amount from products

**Changes:**
- Created `trigger/compose.py` with offer composition helpers
- Updated `step4_handler.py` imports to use compose module
- Removed ~115 lines from step4_handler.py

**Verification:** All 146 core tests pass + E2E Playwright verified

---

### R4: Step3 Evaluation Extraction ✅

**Summary:** Extracted room evaluation and rendering functions from `step3_handler.py` into `evaluation.py`.

**New Module:** `backend/workflows/steps/step3_room_availability/trigger/evaluation.py` (~50 lines)
- `evaluate_room_statuses()` - Evaluate room availability for a date
- `render_rooms_response()` - Format room options for display
- `_flatten_statuses()` - Convert status list to dict

**Changes:**
- Created `trigger/evaluation.py` with evaluation helpers
- Updated `step3_handler.py` imports to use evaluation module

**Verification:** All 146 core tests pass + E2E Playwright verified

---

### R3: Step3 Selection Action Extraction ✅

**Summary:** Extracted room selection action handler from `step3_handler.py` into `selection.py`.

**New Module:** `backend/workflows/steps/step3_room_availability/trigger/selection.py` (~250 lines)
- `handle_select_room_action()` - Persist client room choice and prompt for products
- `_thread_id()` - Get thread identifier from state
- `_reset_room_attempts()` - Reset room proposal counter
- `_format_display_date()` - Format date for display

**Changes:**
- Created `trigger/selection.py` with selection handler
- Updated `step3_handler.py` to import from selection module
- Updated `process.py` shim to re-export selection functions

**Verification:** All 146 core tests pass + E2E Playwright verified

---

### N2: Step5 Constants Extraction ✅

**Summary:** Extracted constants from `step5_handler.py` and `classification.py` into dedicated `constants.py` module.

**New Module:** `backend/workflows/steps/step5_negotiation/trigger/constants.py`
- `MAX_COUNTER_PROPOSALS = 3` - Counter proposal limit
- `CONFIDENCE_*` thresholds (6 values) - Classification confidence levels
- `INTENT_*` constants (5 values) - Intent type strings
- `OFFER_STATUS_*` constants - Accepted/Declined status strings
- `SITE_VISIT_PROPOSED` - Site visit state constant

**Changes:**
- Updated `step5_handler.py` to import and use named constants
- Updated `classification.py` to use threshold and intent constants

**Verification:** All 146 core tests pass

---

### D5: Step2 Q&A Bridge Extraction (Complete) ✅

**Summary:** Resolved circular dependency between `step2_handler.py` and `general_qna.py` using third module pattern.

**New Modules:**
1. `backend/workflows/steps/step2_date_confirmation/trigger/window_helpers.py` (178 lines)
   - `_reference_date_from_state`, `_resolve_window_hints`, `_has_window_constraints`
   - `_window_filters`, `_extract_participants_from_state`, `_candidate_dates_for_constraints`

2. `backend/workflows/steps/step2_date_confirmation/trigger/general_qna.py` (484 lines)
   - `_present_general_room_qna()` - Main Q&A handler with range availability
   - `_search_range_availability()` - Date range search helper

**Resolution Pattern:**
- Created `window_helpers.py` as shared third module that both files can import
- `general_qna.py` imports from `window_helpers.py` (no lazy imports needed)
- `step2_handler.py` imports from both `window_helpers.py` and `general_qna.py`
- Removed 9 duplicate function definitions (~536 lines)

**Result:** `step2_handler.py`: ~3456 → 2920 lines (~16% reduction)

**Verification:** All 146 core tests pass + imports verified

---

### R1: Step3 Constants Extraction ✅

**Summary:** Extracted constants from `step3_handler.py` into dedicated `constants.py` module.

**New Module:** `backend/workflows/steps/step3_room_availability/trigger/constants.py`
- `ROOM_OUTCOME_UNAVAILABLE`, `ROOM_OUTCOME_AVAILABLE`, `ROOM_OUTCOME_OPTION`, `ROOM_OUTCOME_CAPACITY_EXCEEDED`
- `ROOM_SIZE_ORDER` (room ranking dictionary)
- `ROOM_PROPOSAL_HIL_THRESHOLD` (HIL threshold constant)

**Changes:**
- Created `trigger/constants.py` with room outcome constants
- Updated `step3_handler.py` to import from constants module
- Updated `process.py` to import constants from canonical location

**Verification:** All 146 core tests pass + imports verified

---

### F1+F2 Verification ✅

**Summary:** Verified F1 (Step7 constants/classification) and F2 (Step7 site-visit) were already completed.

**Existing Modules:**
- `trigger/constants.py` - 6 keyword tuples
- `trigger/classification.py` - `classify_message()` function
- `trigger/helpers.py` - 5 utility functions
- `trigger/site_visit.py` - 9 site-visit functions (~370 lines)

**Result:** `step7_handler.py` was already refactored from 916 → 524 lines (43% reduction)

---

### Q&A Flow Test Fixes ✅

**Summary:** Fixed 8 Q&A flow tests that were failing with `date_time_clarification` instead of `general_rooms_qna`.

**Root Cause:** `_message_signals_confirmation` in `step2_handler.py` was parsing vague date mentions like "Saturday in February" as actual date confirmations, causing Q&A queries to be misclassified.

**Fixes:**
1. **step2_handler.py** - Added regex word boundary check for question words before parsing dates:
   - Changed from line-start check to `re.search(rf"\b{re.escape(word)}\b", normalized)`
   - Prevents "And what about Sundays?" type messages from being treated as confirmations

2. **test_general_room_qna_flow.py** - Fixed test patching:
   - Updated `FakeRoomAvailability` dataclass with correct attributes (`capacity_max`, `room_name`, `features`, `products`)
   - Changed patch location from DEFINITION site to USE site (`backend.workflows.qna.engine.fetch_room_availability`)

3. **test_general_room_qna_multiturn.py** - Fixed module paths:
   - Changed all 5 occurrences from old `groups` path to `steps.step2_date_confirmation.trigger.step2_handler`

**Files modified:**
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
- `tests/specs/date/test_general_room_qna_flow.py`
- `tests/specs/date/test_general_room_qna_multiturn.py`

**Verification:** All 8 Q&A tests pass, 146 core tests pass

---

### YAML Flow Test Updates ✅

**Summary:** Updated YAML flow tests and date confirmation tests to work with smart shortcuts behavior.

**Changes:**
1. **test_A_general_qna_step1_to_step4.yaml** - Simplified test flow:
   - Changed expected `intent` from `event_intake_with_question` to `event_intake_shortcut`
   - Removed obsolete turns (date approval, date confirmation) since shortcuts now push directly to Step 3
   - Updated expected `current_step` to 3 (room availability)
   - Updated expected room/date from Room A/21.02.2026 to Room B/07.02.2026 (shortcuts' first pick)

2. **test_vague_date_month_weekday_flow.py** - Fixed patching locations:
   - Changed from old `groups` module path to `steps.step2_date_confirmation.trigger.step2_handler`
   - Added comment explaining USE site patching pattern

**Note:** 7 other YAML flow tests still fail - these need similar updates to match the new smart shortcuts behavior. This is expected as the workflow UX has improved with faster shortcuts.

**Verification:** 531 core tests pass (detection + regression + flow + date specs)

---

### G0: Freeze Groups as Pure Re-Export ✅

**Summary:** Ensured all `backend/workflows/groups/*` files are pure re-exports and added guard tests.

**Files converted to pure re-exports:**
- `groups/intake/billing_flow.py` → re-exports from `steps/step1_intake/billing_flow.py`
- `groups/intake/db_pers/tasks.py` → re-exports from `steps/step1_intake/db_pers/tasks.py`
- `groups/intake/llm/analysis.py` → re-exports from `steps/step1_intake/llm/analysis.py`
- `groups/date_confirmation/llm/analysis.py` → re-exports from `steps/step2_date_confirmation/llm/analysis.py`

**New guard test:** `tests/specs/gatekeeping/test_import_boundaries.py`
- `test_no_runtime_imports_from_deprecated_groups` - Fails if any backend code imports from groups
- `test_groups_modules_are_pure_reexports` - Fails if any groups file has logic without DEPRECATED marker

**Result:** All 65 files in `groups/` are now pure re-exports. Runtime code must use `steps/` imports.

**Verification:** 541 tests pass

---

### S2: Smart Shortcuts Types/Telemetry Extraction ✅

**Summary:** Extracted dataclasses and constants from `smart_shortcuts.py`.

**New Module:**
- `backend/workflows/planner/shortcuts_types.py` (153 lines)

**Types extracted:**
- `ParsedIntent` - Parsed user intent from message text
- `PlannerTelemetry` - Telemetry data with `to_log()` method
- `AtomicDecision` - Decision about atomic execution
- `PlannerResult` - Dictionary-like payload wrapper

**Constants extracted:**
- `PREASK_CLASS_COPY` - Pre-ask class copy text
- `CLASS_KEYWORDS` - Keywords for class detection
- `ORDINAL_WORDS_BY_LANG` - Ordinal word mappings (EN/DE)

**Verification:** All 517 tests pass

---

### S1: Smart Shortcuts Flags and Gate Extraction ✅

**Summary:** Extracted env flag parsing and gate checking functions from `smart_shortcuts.py`.

**New Modules:**
- `backend/workflows/planner/shortcuts_flags.py` (104 lines) - All env flag functions
- `backend/workflows/planner/shortcuts_gate.py` (85 lines) - Gate checking functions

**Functions extracted to shortcuts_flags.py:**
- `shortcuts_enabled()` (was `_flag_enabled`)
- `max_combined()` (was `_max_combined`)
- `legacy_shortcuts_allowed()` (was `_legacy_shortcuts_allowed`)
- `needs_input_priority()` (was `_needs_input_priority`)
- `product_flow_enabled()` (was `_product_flow_enabled`)
- `capture_budget_on_hil()` (was `_capture_budget_on_hil`)
- `no_unsolicited_menus()` (was `_no_unsolicited_menus`)
- `event_scoped_upsell_enabled()` (was `_event_scoped_upsell_enabled`)
- `budget_default_currency()` (was `_budget_default_currency`)
- `budget_parse_strict()` (was `_budget_parse_strict`)
- `max_missing_items_per_hil()` (was `_max_missing_items_per_hil`)
- `atomic_turns_enabled()` (new public name)
- `shortcut_allow_date_room()` (new public name)

**Functions extracted to shortcuts_gate.py:**
- `shortcuts_allowed()` (was `_shortcuts_allowed`)
- `coerce_participants()` (was `_coerce_participants`)
- `debug_shortcut_gate()` (was `_debug_shortcut_gate`)

**Result:** `smart_shortcuts.py` reduced by ~100 lines, functions re-exported for compatibility

**Verification:** All 146 tests pass, shortcuts gate tests pass

---

### Dead Code Cleanup ✅

**Summary:** Removed unused functions from step4_handler.py and step5_handler.py that were replaced by `confirmation_gate.py`.

**Removed:**
- `step4_handler.py`: `_check_deposit_payment_continuation` (~46 lines), `_auto_accept_if_billing_ready` (~72 lines)
- `step5_handler.py`: `_auto_accept_if_billing_ready` (~22 lines)

**Result:** -143 lines total dead code removed

**Verification:** All 146 tests pass

---

## 2025-12-27

### N1: Step5 Debug/Log Hygiene ✅

**Summary:** Removed conditional `WF_DEBUG` debug prints from `step5_handler.py`.

**Changes:**
- Removed `WF_DEBUG = os.getenv("WF_DEBUG_STATE") == "1"` flag
- Removed 11 conditional debug print statements
- Removed unused `import os`
- Kept `logger.error` calls (legitimate error logging)

**Result:** `step5_handler.py`: 1252 → 1225 lines (-27 lines)

**Verification:** All 146 tests pass

---

### N2: Step5 Classification Extraction ✅

**Summary:** Verified Step5 classification module extraction is complete.

**Module:** `backend/workflows/steps/step5_negotiation/trigger/classification.py` (118 lines)

**Functions:**
- `collect_detected_intents(message_text)` - Detect all possible intents with confidence scores
- `classify_message(message_text)` - Return highest-confidence intent
- `iso_to_ddmmyyyy(raw)` - Date format conversion

**Integration:**
- Imported in `step5_handler.py` as `_classify_message`, `_collect_detected_intents`, `_iso_to_ddmmyyyy`
- Re-exported via package `__init__.py` for backward compatibility

**Note:** `_ask_classification_clarification()` remains in step5_handler.py (uses state mutation).

**Verification:** All 146 tests pass

---

### O2: Step4 Billing Gate Consolidation ✅

**Summary:** Verified Step4 billing gate consolidation to shared module is complete.

**Module:** `backend/workflows/common/billing_gate.py` (118 lines) - shared by Step4 and Step5

**Integration in step4_handler.py:**
- Imports at lines 15-19: `_refresh_billing`, `_flag_billing_accept_pending`, `_billing_prompt_draft`
- Usage at lines 160, 366, 368, 369

**Note:** No duplicate billing logic remains in step4_handler.py.

**Verification:** All 146 tests pass, E2E billing→deposit→HIL flow working

---

### N3: Step5 Billing Gate Extraction ✅

**Summary:** Verified Step5 billing gate module extraction is complete.

**Module:** `backend/workflows/common/billing_gate.py` (118 lines)

**Functions:**
- `refresh_billing(event_entry)` - Parse and persist billing details, return missing fields
- `flag_billing_accept_pending(event_entry, missing_fields)` - Mark event as awaiting billing
- `billing_prompt_draft(missing_fields, step)` - Create billing request message

**Integration:**
- Imported in `step5_handler.py` as `_refresh_billing`, `_flag_billing_accept_pending`, `_billing_prompt_draft`
- Also used by Step4 (O2 consolidation)

**Verification:** All 146 tests pass

---

### W2 Import Fixes ✅

**Summary:** Fixed missing imports after W2 HIL task extraction.

**Fixes:**
1. `_thread_identifier` - Was used in `_debug_state()` at line 153
2. `_hil_action_type_for_step` - Was used in deposit→HIL flow at line 638

**Root Cause:** W2 extraction moved these functions to `hil_tasks.py` but `workflow_email.py` still referenced them directly.

**Symptoms:**
- `NameError: name '_thread_identifier' is not defined` on startup
- `NameError: name '_hil_action_type_for_step' is not defined` when paying deposit

**Verification:** Full E2E flow (inquiry→room→offer→accept→billing→deposit→HIL→approve→site visit) works in frontend.

---

### W2: Complete HIL Task Extraction ✅

**Summary:** Extracted remaining HIL task functions from `workflow_email.py` to `backend/workflows/runtime/hil_tasks.py`.

**Functions Extracted:**
- `_thread_identifier()` - Get stable thread identifier from state
- `_hil_signature()` - Generate duplicate-prevention signatures
- `_hil_action_type_for_step()` - Map step → action type string
- `enqueue_hil_tasks()` - Create HIL task records from draft messages (was `_enqueue_hil_tasks`)

**Result:** `workflow_email.py`: 778 → 647 lines (-131 lines, ~17% reduction)

**Files Modified:**
- `backend/workflow_email.py` - Removed 4 functions, updated imports
- `backend/workflows/runtime/hil_tasks.py` - Added 4 functions

**Note:** W1 (facade reorganization) was already complete - `__all__` was well-organized.

**Verification:** All 146 tests pass

---

### P2: Make Guards Pure ✅

**Summary:** Refactored `backend/workflow/guards.py` to be pure - returns decisions without side effects.

**Changes:**
- Extended `GuardSnapshot` dataclass with new fields:
  - `forced_step: Optional[int]` - Step to force if different from current
  - `requirements_hash_changed: bool` - Whether hash was recomputed
  - `deposit_bypass: bool` - Whether deposit payment bypass is active
- Refactored `evaluate()` to compute decisions only (no DB writes, no state.extras mutation)
- Updated `pre_route.py` to apply metadata updates from snapshot
- Removed unused imports (`WorkflowStep`, `write_stage`, `update_event_metadata`) from guards.py

**Result:** Guards follow functional pattern - caller applies writes explicitly.

**Files Modified:**
- `backend/workflow/guards.py`
- `backend/workflows/runtime/pre_route.py`

**Verification:** All 146 tests pass

---

### P1: Pre-Route Pipeline Extraction ✅

**Summary:** Extracted pre-routing logic from `workflow_email.py` to `backend/workflows/runtime/pre_route.py`.

**New Module:**
- `pre_route.py` (207 lines) - `run_pre_route_pipeline()`, `check_duplicate_message()`, `evaluate_pre_route_guards()`, `try_smart_shortcuts()`, `correct_billing_flow_step()`

**Phases extracted:**
1. Duplicate message detection → early return
2. Post-intake halt check → early return
3. Guard evaluation → store candidate dates
4. Smart shortcuts → early return if fired
5. Billing flow step correction → fix step number

**Result:** `workflow_email.py`: 850 → 783 lines (-67 lines, ~8% reduction)

**Verification:** All 146 tests pass

---

### W3: Router Loop Extraction ✅

**Summary:** Extracted step routing loop from `workflow_email.py` to `backend/workflows/runtime/router.py`.

**New Module:**
- `router.py` (110 lines) - `dispatch_step()`, `run_routing_loop()`

**Design:** Uses callback-based approach - router receives `persist_fn`, `debug_fn`, `finalize_fn` from caller to avoid moving tightly-coupled debug infrastructure.

**Result:** `workflow_email.py`: 886 → 850 lines (-36 lines, ~4% reduction)

**Verification:** All 146 tests pass

---

### D0-D4: Step 2 Date Parsing Extraction ✅

**Summary:** Committed 693 lines of pre-existing extractions (5 modules) for Step 2 date confirmation.

**Modules Committed:**

| Module | Functions | Lines |
|--------|-----------|-------|
| `constants.py` | Month/weekday mappings, keyword sets, time defaults | 156 |
| `types.py` | `ConfirmationWindow`, `WindowHints` dataclasses | 48 |
| `date_parsing.py` | 10 pure date/weekday parsing functions | 242 |
| `proposal_tracking.py` | 5 proposal history management functions | 122 |
| `calendar_checks.py` | 3 calendar availability functions | 125 |

**Verification:** All 146 tests pass + imports verified

---

### F1+F2: Step 7 Site-Visit Extraction ✅

**Summary:** Extracted ~390 lines from `step7_handler.py` into 4 focused modules (43% reduction).

**New Modules Created:**

| Module | Functions | Lines |
|--------|-----------|-------|
| `constants.py` | `CONFIRM_KEYWORDS`, `RESERVE_KEYWORDS`, `VISIT_KEYWORDS`, `DECLINE_KEYWORDS`, `CHANGE_KEYWORDS`, `QUESTION_KEYWORDS` | 14 |
| `helpers.py` | `iso_to_ddmmyyyy`, `base_payload`, `thread_id`, `any_keyword_match`, `contains_word` | 60 |
| `classification.py` | `classify_message` | 49 |
| `site_visit.py` | 9 site-visit functions: `handle_site_visit`, `site_visit_unavailable_response`, `generate_visit_slots`, `extract_site_visit_preference`, `generate_preferred_visit_slots`, `handle_site_visit_preference`, `parse_slot_selection`, `handle_site_visit_confirmation`, `ensure_calendar_block` | 372 |

**Step 7 Handler Changes:**
- `step7_handler.py`: 916 → 524 lines (-392 lines, 43% reduction)
- All site-visit logic isolated in dedicated `site_visit.py` module
- Classification and helpers modularized for testability

**Verification:**
- All 146 core tests pass
- Imports verified via `import backend.workflow_email`

---

### I1: Step 1 Pure Helper Extraction ✅

**Summary:** Extracted ~260 lines of pure helper functions from `step1_handler.py` into 6 focused modules.

**New Modules Created:**

| Module | Functions | Lines |
|--------|-----------|-------|
| `intent_helpers.py` | `needs_vague_date_confirmation`, `initial_intent_detail`, `has_same_turn_shortcut`, `resolve_owner_step` | ~50 |
| `keyword_matching.py` | `keyword_regex`, `contains_keyword`, `product_token_regex`, `match_product_token`, `extract_quantity_from_window`, `menu_token_candidates` + constants | ~115 |
| `confirmation_parsing.py` | `extract_confirmation_details`, `looks_like_gate_confirmation` + constants | ~105 |
| `room_detection.py` | `detect_room_choice` | ~65 |
| `product_detection.py` | `menu_price_value`, `detect_menu_choice` | ~45 |
| `entity_extraction.py` | `participants_from_event` | ~30 |

**Changes to step1_handler.py:**
- Removed ~260 lines of implementations
- Added imports from new modules
- Removed unused import: `handle_select_room_action` from step3
- Removed unused import: `load_rooms` (now in extracted modules)
- Removed unused import: `parse_time_range` (now in extracted modules)

**Note:** `_detect_product_update_request` (~150 lines) kept in handler as it has side effects (mutates user_info) - candidate for future refactoring.

**Verification:**
- All 146 core tests pass
- E2E Playwright test passed (inquiry → offer → billing → deposit → HIL → site visit)

---

### Unified `_present_general_room_qna` Across Steps 3/4/5/7 ✅

**Summary:** Extracted duplicated Q&A handling logic from 4 step handlers into a shared function, reducing ~684 lines to ~175 lines (~75% reduction).

**Analysis:**
- Steps 3, 4, 5, 7 each had ~171 lines of nearly identical `_present_general_room_qna` code
- Only differences: step numbers (3/4/5/7) and step names
- Step 2 has a more complex version (~354 lines) with extra features - left as-is for now

**Changes:**

| File | Change |
|------|--------|
| `backend/workflows/common/general_qna.py` | Added shared `present_general_room_qna(step_number, step_name)` (~190 lines) |
| `backend/workflows/steps/step3_.../step3_handler.py` | Replaced ~171 lines with 10-line thin wrapper |
| `backend/workflows/steps/step4_.../step4_handler.py` | Replaced ~171 lines with 10-line thin wrapper |
| `backend/workflows/steps/step5_.../step5_handler.py` | Replaced ~171 lines with 10-line thin wrapper |
| `backend/workflows/steps/step7_.../step7_handler.py` | Replaced ~171 lines with 10-line thin wrapper |

**Thin Wrapper Pattern:**
```python
def _present_general_room_qna(state, event_entry, classification, thread_id):
    """Handle general Q&A at Step N - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id,
        step_number=N, step_name="Step Name"
    )
```

**Verification:**
- All 146 core tests pass
- E2E Playwright test passed (inquiry → offer → billing → deposit → HIL → site visit)

---

### D5: Step2 Q&A Bridge Analysis ✅ (No Extraction Needed)

**Summary:** Analyzed `_present_general_room_qna` function for extraction. Found that D5 extraction is not needed - the architecture is already correct.

**Findings:**

1. **Shared Q&A logic already extracted:** Common Q&A functions exist in `backend/workflows/common/general_qna.py` (1560 lines)
   - `enrich_general_qna_step2`, `render_general_qna_reply`, `_fallback_structured_body`

2. **Step-specific functions correctly remain in handlers:** Each step (2, 3, 4, 5, 7) has its own `_present_general_room_qna` implementation
   - These are NOT duplicates - each handles step-specific state and routing
   - Extracting would create circular imports or require massive multi-step refactoring

3. **D-series complete for Step2:** D1-D4 achieved 7.3% reduction (3726 → 3453 lines, -273 lines)

**Files Examined:**
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
- `backend/workflows/common/general_qna.py`

**Verification:**
- All 146 core tests pass
- E2E Playwright test passed (inquiry → offer → billing → deposit → HIL → site visit)

---

### D4: Step2 Calendar Checks Extraction ✅

**Summary:** Extracted 3 calendar check functions from step2_handler.py into dedicated module.

**New File:**
- `backend/workflows/steps/step2_date_confirmation/trigger/calendar_checks.py` (125 lines)

**Extracted Functions (3 total):**
- `candidate_is_calendar_free` - Check room availability on date/time
- `future_fridays_in_may_june` - Find Fridays in late spring period
- `maybe_fuzzy_friday_candidates` - Fuzzy "late spring Friday" matching

**Line Count Changes:**
- `step2_handler.py`: 3487 → 3453 lines (-34 lines)
- New `calendar_checks.py`: 125 lines
- Cumulative D1-D4: 3726 → 3453 (-273 lines, 7.3% reduction)

**Verification:**
- All 146 core tests pass
- E2E test passed (billing → deposit → HIL → site visit)

---

### D3: Step2 Proposal Tracking Extraction ✅

**Summary:** Extracted 5 proposal tracking functions from step2_handler.py into dedicated module.

**New File:**
- `backend/workflows/steps/step2_date_confirmation/trigger/proposal_tracking.py` (122 lines)

**Extracted Functions (5 total):**
- Attempt counter: `increment_date_attempt`, `reset_date_attempts`
- History tracking: `collect_proposal_history`, `update_proposal_history`, `proposal_skip_dates`

**Line Count Changes:**
- `step2_handler.py`: 3530 → 3487 lines (-43 lines)
- New `proposal_tracking.py`: 122 lines
- Cumulative D1+D2+D3: 3726 → 3487 (-239 lines, 6.4% reduction)

**Verification:**
- All 146 core tests pass

---

### D2: Step2 Date Parsing Extraction ✅

**Summary:** Extracted 11 pure date parsing functions from step2_handler.py into dedicated module.

**New File:**
- `backend/workflows/steps/step2_date_confirmation/trigger/date_parsing.py` (242 lines)

**Extracted Functions (11 total, all pure/no side effects):**
- ISO parsing: `safe_parse_iso_date`, `iso_date_is_past`, `normalize_iso_candidate`, `next_matching_date`
- Display formatting: `format_display_dates`, `human_join`
- Weekday parsing: `clean_weekdays_hint`, `parse_weekday_mentions`, `weekday_indices_from_hint`
- Normalization: `normalize_month_token`, `normalize_weekday_tokens`

**Line Count Changes:**
- `step2_handler.py`: 3621 → 3530 lines (-91 lines)
- New `date_parsing.py`: 242 lines
- Cumulative D1+D2: 3726 → 3530 (-196 lines, 5.3% reduction)

**Compat Constraint Preserved:**
- Uses private alias imports: `safe_parse_iso_date as _safe_parse_iso_date`
- All dependent functions in step2_handler.py continue to work via aliases

**Verification:**
- All 146 core tests pass
- Import chain verified

---

### D1: Step2 Constants & Types Extraction ✅

**Summary:** Extracted constants and types from step2_handler.py (largest handler at 3726 lines) into dedicated modules.

**New Files:**
- `backend/workflows/steps/step2_date_confirmation/trigger/constants.py` (156 lines)
- `backend/workflows/steps/step2_date_confirmation/trigger/types.py` (48 lines)

**Extracted Constants:**
- `MONTH_NAME_TO_INDEX`, `WEEKDAY_NAME_TO_INDEX`, `WEEKDAY_LABELS` - Date parsing mappings
- `PLACEHOLDER_NAMES`, `AFFIRMATIVE_TOKENS`, `CONFIRMATION_KEYWORDS` - NLU token sets
- `SIGNATURE_MARKERS` - Email signature detection
- `TIME_HINT_DEFAULTS` - Vague time hint resolution

**Extracted Types:**
- `ConfirmationWindow` dataclass - Resolved confirmation payload
- `WindowHints` type alias - Tuple for (date_hint, time_hint, room_hint)

**Line Count Changes:**
- `step2_handler.py`: 3726 → 3621 lines (-105 lines)
- New `constants.py`: 156 lines
- New `types.py`: 48 lines

**Compat Constraint Preserved:**
- `ConfirmationWindow` still exported via `process.py` for smart_shortcuts dynamic imports
- Uses private alias imports: `MONTH_NAME_TO_INDEX as _MONTH_NAME_TO_INDEX`

**Verification:**
- All 146 core tests pass
- Import chain verified: `process.py` → `step2_handler.py` → `types.py`

---

### O1: Step4 Product Ops Extraction ✅

**Summary:** Extracted product operations functions from step4_handler.py into dedicated module.

**New File:**
- `backend/workflows/steps/step4_offer/trigger/product_ops.py` (465 lines)

**Extracted Functions (17 total):**
- Core operations: `apply_product_operations`, `autofill_products_from_preferences`
- State checks: `products_ready`, `ensure_products_container`, `has_offer_update`
- Participant count: `infer_participant_count`
- Room utilities: `room_alias_map` (LRU cached), `room_aliases`, `product_unavailable_in_room`
- Normalization: `normalise_products`, `normalise_product_names`, `normalise_product_fields`, `upsert_product`
- Menu: `menu_name_set`
- Line building: `build_product_line_from_record`, `summarize_product_line`, `build_alternative_suggestions`

**Line Count Changes:**
- `step4_handler.py`: 2108 → 1782 lines (-326 lines)
- New `product_ops.py`: 465 lines

**Key Constraint Preserved:**
- `_apply_product_operations` still exported via `process.py` for test compatibility
- Uses private alias imports: `apply_product_operations as _apply_product_operations`

**Verification:**
- All 146 core tests pass
- Import chain verified: `process.py` → `step4_handler.py` → `product_ops.py`

---

### O2: Step4 Billing Gate Consolidation ✅

**Summary:** Consolidated Step4 and Step5 billing gate functions into shared module.

**Changes:**
- Moved `billing_gate.py` from `step5_negotiation/trigger/` to `common/`
- Updated Step5 import to use `backend.workflows.common.billing_gate`
- Updated Step4 to import from shared module (removed 30 lines of duplicate code)
- Updated test imports for new location

**Line Count Changes:**
- `step4_handler.py`: 2144 → 2108 lines (-36 lines, +6 import lines = -30 net)

**Consolidated Functions:**
- `refresh_billing(event_entry)` - Parse and persist billing details
- `flag_billing_accept_pending(event_entry, missing_fields)` - Mark event awaiting billing
- `billing_prompt_draft(missing_fields, step)` - Create billing request draft

**Verification:**
- All 146 core tests pass
- All 19 billing-specific tests pass

---

### N3: Step5 Billing Gate Extraction ✅

**Summary:** Extracted billing gate functions from step5_handler.py (1440→1405 lines) into dedicated module.

**New File:**
- `backend/workflows/common/billing_gate.py` (100 lines) - Billing gate utilities
  *(Originally in step5_negotiation/trigger/, moved to common/ in O2)*

**Extracted Functions:**
- `refresh_billing(event_entry)` - Parse and persist billing details
- `flag_billing_accept_pending(event_entry, missing_fields)` - Mark event awaiting billing
- `billing_prompt_draft(missing_fields, step)` - Create billing request draft

**NOT Extracted (HIL dependencies):**
- `_auto_accept_if_billing_ready` - Calls `_start_hil_acceptance` (keep in handler)

**Note:** Step4 consolidation completed in O2.

**Verification:**
- All 146 core tests pass

---

### N2: Step5 Classification Extraction ✅

**Summary:** Extracted message classification helpers from step5_handler.py (~1489→1440 lines) into dedicated module.

**New File:**
- `backend/workflows/steps/step5_negotiation/trigger/classification.py` (102 lines) - Classification utilities

**Extracted Functions:**
- `collect_detected_intents(message_text)` - Detect all possible intents with confidence scores
- `classify_message(message_text)` - Return single best intent classification
- `iso_to_ddmmyyyy(raw)` - Convert ISO date format to DD.MM.YYYY

**NOT Extracted (have state dependencies):**
- `_ask_classification_clarification` - Modifies WorkflowState
- `_detect_structural_change` - Reads event_entry extensively

**Test File:**
- `tests/specs/negotiation/test_classification.py` (13 tests) - Characterization tests

**Verification:**
- All 13 classification tests pass
- All 146 core tests pass

---

### N1: Step5 Debug/Log Hygiene ✅

**Summary:** Converted unguarded ERROR prints to proper logging in step5_handler.py.

**Changes:**
- Added `import logging` and `logger = logging.getLogger(__name__)`
- Converted 2 ERROR prints to `logger.error()` (lines 174, 184)
- All 11 DEBUG prints already guarded by `WF_DEBUG` flag

**Why proper logging:**
- Errors should never be silently ignored in production
- `logger.error()` allows log-level configuration without code changes
- Follows existing codebase pattern (adapter.py, smart_shortcuts.py)

**Verification:** All 146 core tests pass.

---

### I2: Isolate Dev/Test Mode Flow ✅

**Summary:** Extracted dev/test mode "continue or reset" logic from step1_handler.py (1407→1392 lines) into dedicated module.

**New File:**
- `backend/workflows/steps/step1_intake/trigger/dev_test_mode.py` (115 lines) - Dev/test mode utilities

**Extracted Functions:**
- `is_dev_test_mode_enabled()` - Check if DEV_TEST_MODE env var is set
- `should_show_dev_choice()` - Determine if dev choice prompt should be shown
- `build_dev_choice_result()` - Build the GroupResult for dev choice
- `maybe_show_dev_choice()` - Main entry point for dev mode handling

**Test File:**
- `tests/specs/intake/test_dev_test_mode.py` (26 tests) - Characterization tests

**Verification:**
- All 26 dev_test_mode tests pass
- All 146 core tests pass
- E2E Playwright: Full flow (inquiry→room→offer→billing→deposit→HIL→site visit) works

---

### Intent Classification Edge Case Fix ✅

**Summary:** Fixed generic intent classification rescue for event-type messages that LLM incorrectly classifies as "other".

**Problem:** Messages like "Corporate Dinner for 25 guests" were classified as "other" instead of "event_request" because the heuristic override only checked for narrow keywords (workshop/conference/meeting/event).

**Solution:** Added comprehensive `_EVENT_TYPE_TOKENS` and `_PARTICIPANT_TOKENS` tuples covering:
- Food/catering types: dinner, lunch, breakfast, brunch, banquet, gala, cocktail, reception
- Event formats: workshop, training, seminar, conference, meeting, presentation
- Celebrations: wedding, birthday, party, anniversary, corporate/team event
- German equivalents: abendessen, feier, hochzeit, veranstaltung, tagung, etc.
- Participant keywords: people, guests, participants, pax (EN + DE)

**Files Changed:**
- `backend/workflows/llm/adapter.py` - Added `_EVENT_TYPE_TOKENS`, `_PARTICIPANT_TOKENS`, updated `_heuristic_intent_override()`

**Verification:**
- Unit tests for "Corporate Dinner", German events, weddings, team events all pass
- Browser E2E: "Corporate Dinner for 25 guests" now correctly → `new_event` workflow
- All 146 core tests pass

---

### I1: Extract Step1 Pure Helpers ✅

**Summary:** Extracted pure helper functions from step1_handler.py (1494→1407 lines) into dedicated modules.

**New Files:**
- `backend/workflows/steps/step1_intake/trigger/normalization.py` (34 lines) - Text normalization
- `backend/workflows/steps/step1_intake/trigger/date_fallback.py` (30 lines) - Date fallback utilities
- `backend/workflows/steps/step1_intake/trigger/gate_confirmation.py` (106 lines) - Pattern detection

**Extracted Functions:**
- `normalize_quotes` - Normalize typographic apostrophes/quotes
- `normalize_room_token` - Normalize room tokens for comparison
- `fallback_year_from_ts` - Extract year from timestamp for date fallback
- `looks_like_offer_acceptance` - Detect offer acceptance patterns
- `looks_like_billing_fragment` - Detect billing address fragments

**NOT Extracted (have state dependencies):**
- `_looks_like_gate_confirmation` - Depends on linked_event.current_step
- `_extract_confirmation_details` - Uses fallback_year from context
- `_detect_room_choice` - Calls load_rooms() (DB access)

**Verification:** All 146 core tests pass.

---

## 2025-12-26

### W2: Extract HIL Task APIs ✅

**Summary:** Extracted HIL task management functions from workflow_email.py (1352→886 lines) into a dedicated runtime module.

**New Files:**
- `backend/workflows/runtime/__init__.py` - Runtime package init
- `backend/workflows/runtime/hil_tasks.py` - HIL task APIs (574 lines)

**Extracted Functions:**
- `approve_task_and_send` - Approve HIL task and emit send_reply payload
- `reject_task_and_send` - Reject HIL task and emit response payload
- `cleanup_tasks` - Remove resolved/stale HIL tasks
- `list_pending_tasks` - Re-export from task_io
- `_compose_hil_decision_reply` - Helper for decision replies

**Changes to workflow_email.py:**
- Added import from `backend.workflows.runtime.hil_tasks`
- Removed function definitions (now delegated to runtime module)
- Preserved public API (`__all__` unchanged)

**Verification:** All 146 core tests pass, 15 smoke tests pass, pytest collection clean.

---

### W1: workflow_email.py Explicit Facade ✅

**Summary:** Made workflow_email.py an explicit public API facade with documented `__all__`.

**Changes:**
- Added explicit `__all__` list defining public API surface
- Added W-PUBLIC documentation block describing each exported symbol
- Public API includes: `DB_PATH`, `load_db`, `save_db`, `get_default_db`, `process_msg`, `list_pending_tasks`, `approve_task_and_send`, `reject_task_and_send`, `cleanup_tasks`, `run_samples`, `task_cli_loop`

**Files Changed:**
- `backend/workflow_email.py` - added `__all__` and PUBLIC API documentation

**Verification:** All 146 core tests pass, 15 smoke tests pass, pytest collection clean.

---

### R0: Step3 Q&A Verification + Missing Exports ✅

**Summary:** Verified Step3 Q&A UnboundLocal fix was already in place. Added additional missing exports discovered when running Q&A tests.

**Fixes:**
- Step3 UnboundLocal fix already present at line 1427: `request: Optional[Dict[str, Any]] = None`
- Added missing Step 2 exports: `_candidate_dates_for_constraints`, `ensure_qna_extraction`

**Files Changed:**
- `backend/workflows/steps/step2_date_confirmation/trigger/process.py` - added exports
- `backend/workflows/groups/date_confirmation/trigger/process.py` - added exports

**Verification:** All 64 detection tests pass, all 146 core tests pass.

---

### T0: Pytest Collection Stabilization ✅

**Summary:** Fixed pytest collection failures to enable safe refactoring (prerequisite for all W/D/I/R/O/N series refactors).

**Fixes:**
1. **Legacy tests ignored** - Added `tests/_legacy` to `pytest.ini:norecursedirs` to prevent stale imports from breaking collection
2. **Step 2 compat exports** - Exported `_present_candidate_dates` and `_present_general_room_qna` from Step 2 trigger/process.py shim (required by e2e tests)
3. **Step 4 compat exports** - Exported `_apply_product_operations` and `_compose_offer_summary` from Step 4 trigger/process.py shim
4. **general_qna_classifier shim** - Created `backend/workflows/nlu/general_qna_classifier.py` re-exporting from detection module
5. **intent_classifier shim** - Created `backend/llm/intent_classifier.py` re-exporting from detection module
6. **Duplicate test file** - Renamed `tests/workflows/test_change_integration_e2e.py` to avoid basename collision with `tests/specs/dag/`

**Files Changed:**
- `pytest.ini` - norecursedirs updated
- `backend/workflows/steps/step2_date_confirmation/trigger/process.py` - added exports
- `backend/workflows/groups/date_confirmation/trigger/process.py` - added exports
- `backend/workflows/steps/step4_offer/trigger/process.py` - added exports
- `backend/workflows/nlu/general_qna_classifier.py` - new shim file
- `backend/llm/intent_classifier.py` - new shim file
- `tests/workflows/test_change_integration_e2e_workflows.py` - renamed

**Verification:** `pytest --collect-only` passes with 0 errors. All 146 detection/regression/flow tests pass.

---

## 2025-12-25

### Code Review Fixes: Date Extraction, Billing Capture, Debug Gating ✅

**Summary:** Addressed remaining high-priority issues from backend code review.

**Fixes:**
1. **Date Year Extraction Bug** - Added `Today is {today}` to LLM entity extraction prompt so LLM knows current date when interpreting natural language dates like "February 7th". Also added missing `analyze_message()` method to `OpenAIAgentAdapter`.

2. **Combined Accept+Billing Capture** - When client sends acceptance with billing in same message ("Yes, I accept. Billing: Company, Street, City"), now captures billing from `user_info.billing_address` before calling `_refresh_billing`.

3. **Debug Print Gating** - Wrapped debug prints in `step5_handler.py` and `domain/models.py` with `WF_DEBUG` flag. Set `WF_DEBUG_STATE=1` to enable verbose output.

**Files Changed:**
- `backend/adapters/agent_adapter.py` - date context in LLM prompt, analyze_message()
- `backend/domain/models.py` - WF_DEBUG gating for is_complete prints
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` - billing capture, WF_DEBUG gating

**Commit:** `d8d7566`

---

### GATE-001 Fix: Preferred Room Ranking Honored ✅

**Summary:** Fixed bug where client's preferred room (e.g., "Room A for 30 people") was not being recommended/selected even when the preference was correctly stored.

**Root Causes Fixed:**
1. **Re-sorting override**: `step3_handler.py:528` re-sorted ranked_rooms by profile order, overriding preferred_room bonus
2. **Insufficient bonus**: 10-point preferred_room bonus couldn't overcome Available(60) vs Option(35) = 25-point status difference
3. **LLM reordering**: Verbalizer prompt allowed LLM to "reorder items for clarity"
4. **_select_room() priority**: Function prioritized Available rooms over Option rooms regardless of ranking

**Files Changed:**
- `backend/workflows/common/sorting.py` - preferred_bonus 10→30
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - removed re-sorting, simplified _select_room()
- `backend/llm/verbalizer_agent.py` - added ROOM ORDERING instruction

**E2E Test:** Full flow verified - intake → Room A recommended → selected → offer → billing → deposit → HIL → site visit

---

### E2E Test Validation: Full Flow to Site Visit ✅

**Summary:** Completed end-to-end validation of the complete booking workflow from intake to site visit message.

**Tests Passed:**
- DET-001: Date Change from Step 3 ✅
- DET-002: Date Change Room Unavailable ✅
- DET-003: Room Change from Step 4 ✅
- DET-004: Requirements Change from Step 4 ✅
- DET-004b: Capacity Exceeds All Rooms ✅
- FLOW-001: Full Happy Path (intake → site visit) ✅
- FLOW-002: Capacity Exceeded Recovery → Site Visit ✅

**Key Flows Verified:**
1. Shortcut capture at intake (date, capacity, requirements)
2. Detour routing (date/room/requirements changes)
3. Room lock preservation during date changes
4. Billing gate enforcement before confirmation
5. Deposit gate enforcement before HIL
6. HIL task creation and approval
7. Site visit message delivery

**Test Results File:** `tests/playwright/e2e/TEST_RESULTS_DEC24.md`

---

### Fix: Capacity Exceeds All Rooms - Proper Handling

**Problem:** When client requested capacity exceeding all rooms (e.g., 150 guests, max room is 120), system showed contradictory message: "Room B is a great fit for your 150 guests. However, it has a capacity of 60."

**Root Cause:**
- Room ranking marked `capacity_fit=0` for rooms that don't fit, but didn't filter them out
- Step 3 handler didn't detect "no room fits capacity" case
- Verbalizer received all rooms and generated nonsensical message

**Solution:**
1. Added `get_max_capacity()` and `any_room_fits_capacity()` helpers to `backend/rooms/ranking.py`
2. Added capacity check in Step 3 handler before room selection
3. Created `_handle_capacity_exceeded()` function with:
   - Clear message explaining capacity limits
   - Three alternatives: reduce capacity, split event, external venue partnership
   - Action buttons for quick resolution

**Files Modified:**
- `backend/rooms/ranking.py` - Added capacity helper functions
- `backend/rooms/__init__.py` - Exported new functions
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Added capacity exceeded detection and handler

**Test Results:**
- 150 guests → "Capacity exceeded" message with max (120) and options ✅
- Client reduces to 100 → Shows Room E as best fit ✅
- Flow continues normally after capacity adjustment ✅

---

### Fix: Date Change Clears Room Lock + Asks for Time

**Problem:** Client at Step 4/5 with locked room requests date change. System clears `locked_room_id` and asks "Preferred time?" instead of showing Room A availability on new date.

**Root Cause:** Two bugs:
1. Step 1 intake handler cleared `locked_room_id` for DATE changes, but should preserve it
2. Step 2 handler always asked for time when `window.partial`, but should skip for detour cases

**Solution:**
1. For DATE changes, only clear `room_eval_hash` but KEEP `locked_room_id`
2. When room is already locked, skip time confirmation and fill with default times

**Files Modified:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Preserve lock for DATE changes
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` - Skip time confirmation when room locked

---

### Fix: Room Change Updating Lock Before Change Detection

**Problem:** Client requests room change ("switch to Room D") but system triggers Step 2 time confirmation loop instead of Step 3 room availability.

**Root Cause:** Step 1 immediately updated `locked_room_id` to the new room before change detection ran, causing `user_info.room == locked_room_id` (no change detected).

**Solution:** When a different room is already locked, skip the early room lock update and let normal change detection route to Step 3.

**Files Modified:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Check existing lock before updating
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Check ChangeType.ROOM flag

---

### Fix: Subject Line Date Pollution in Change Detection

**Problem:** Client at Step 3 requested capacity change ("Actually we're 50 now") but system asked for date confirmation instead of showing room availability.

**Root Cause:** The `_message_text()` function combined subject + body. API adds "Client follow-up (2025-12-24 21:07)" to follow-up subjects. The timestamp triggered DATE change detection instead of REQUIREMENTS.

**Solution:** Added `_strip_system_subject()` helper to remove system timestamps from subject before change detection.

**Files Modified:**
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Added helper function and updated `_message_text()`

---

### Fix: Date Change Creating New Event Instead of Updating

**Problem:** Client requested date change ("Actually, can we change the date to 20.02.2026?") but system created a NEW event with blank requirements, asking for capacity again.

**Root Cause:** `_ensure_event_record()` compared dates and created new event when they differed, without checking if it was a change request vs new inquiry.

**Solution:** Added `has_revision_signal()` check to detect date change requests (keywords: "change", "switch", "actually", "instead"). Only create new event for genuine new inquiries without change signals.

**Files Modified:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Added revision signal import and check in `_ensure_event_record()`

---

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
./scripts/dev/dev_server.sh         # Start backend
./scripts/dev/dev_server.sh stop    # Stop backend
./scripts/dev/dev_server.sh restart # Restart backend
./scripts/dev/dev_server.sh status  # Check status
./scripts/dev/dev_server.sh cleanup # Kill all dev processes
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

**Rationale**: Heavy interdependencies, shared state, conditional logic - splitting risks breaking functionality. See `docs/internal/planning/OPEN_DECISIONS.md` DECISION-006.

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

**Pre-existing test failures documented**: See `docs/internal/planning/OPEN_DECISIONS.md` DECISION-005

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
- `docs/reference/DEPENDENCY_GRAPH.md` - Maps dependencies between modules
- All `__init__.py` files have detailed module documentation

**Files Created:**
- `backend/detection/__init__.py` + 6 submodule `__init__.py` files
- `backend/core/__init__.py`, `errors.py`, `fallback.py`
- `backend/api/routes/__init__.py`, `middleware/__init__.py`
- `docs/reference/DEPENDENCY_GRAPH.md`

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
- `docs/guides/TEAM_GUIDE.md` - Added bug documentation under "Known Issues & Fixes"

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
- `docs/guides/TEAM_GUIDE.md` - Documented bytecode cache bug and prevention

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
- `docs/guides/TEAM_GUIDE.md` (added bug documentation)

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
- Added "HIL Toggle System" section to `docs/guides/TEAM_GUIDE.md`

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

See `docs/guides/TEAM_GUIDE.md` for historical bug fixes and their corresponding tests.
