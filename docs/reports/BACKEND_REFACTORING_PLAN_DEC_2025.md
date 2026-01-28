# Backend Refactoring Planning Sheet — Workflow + Steps 1–5 + Shortcuts

**Date:** 2025-12-24  
**Status:** Planning only (no code changes made as part of this plan)  
**Related docs:** `docs/internal/backend/BACKEND_CODE_REVIEW_DEC_2025.md`, `docs/plans/completed/DONE__ARCHITECTURE_FINDINGS_DEC_2025.md`, `docs/plans/completed/DONE__PENDING_REFACTORING_TASKS.md`

This document translates the existing backend review findings into **junior-dev-executable refactoring steps**, with explicit **dependency/import guardrails** so we can refactor "god files" without breaking runtime or tests.

---

## Completed Refactoring ✅

### Q&A Unification (Steps 3/4/5/7) — 2025-12-27

**Summary:** Unified `_present_general_room_qna` across steps 3, 4, 5, 7 into a shared helper function.

| Before | After | Reduction |
|--------|-------|-----------|
| 4 × ~171 lines (~684 total) | ~190 shared + 4 × 10-line wrappers | ~75% |

**Changes:**
- Added `present_general_room_qna(state, event_entry, classification, thread_id, step_number, step_name)` to `backend/workflows/common/general_qna.py`
- Replaced implementations in step3/4/5/7 handlers with thin wrappers delegating to shared function
- Step 2 left as-is (has ~354 lines with extra features: range availability, router Q&A)

**Verification:** All 146 tests pass + E2E Playwright test (full flow through site visit)

### I1: Step 1 Pure Helper Extraction — 2025-12-27

**Summary:** Extracted ~260 lines of pure helpers from `step1_handler.py` into 6 focused modules.

**New Modules:**
- `intent_helpers.py` (4 functions)
- `keyword_matching.py` (6 functions + constants)
- `confirmation_parsing.py` (2 functions + constants)
- `room_detection.py` (1 function)
- `product_detection.py` (2 functions)
- `entity_extraction.py` (1 function)

**Verification:** All 146 tests pass + E2E Playwright test

### F1+F2: Step 7 Site-Visit Extraction — 2025-12-27

**Summary:** Extracted ~390 lines from `step7_handler.py` into 4 focused modules (43% reduction).

**New Modules:**
- `constants.py` (6 keyword tuples)
- `helpers.py` (5 utility functions)
- `classification.py` (message classification)
- `site_visit.py` (9 site-visit functions)

**Result:** `step7_handler.py`: 916 → 524 lines (-392 lines, 43% reduction)

**Verification:** All 146 tests pass + imports verified

### D0-D4: Step 2 Date Parsing Extraction — 2025-12-27

**Summary:** Committed 693 lines of pre-existing extractions for Step 2 date confirmation.

**Modules:**
- `constants.py` (156 lines) - month/weekday mappings, keyword sets
- `types.py` (48 lines) - ConfirmationWindow, WindowHints
- `date_parsing.py` (242 lines) - 10 pure parsing functions
- `proposal_tracking.py` (122 lines) - 5 history management functions
- `calendar_checks.py` (125 lines) - 3 calendar availability functions

**Verification:** All 146 tests pass + imports verified

### W3: Router Loop Extraction — 2025-12-27

**Summary:** Extracted step routing loop from `workflow_email.py` to `backend/workflows/runtime/router.py`.

**New Module:**
- `router.py` (110 lines) - `dispatch_step()`, `run_routing_loop()`

**Result:** `workflow_email.py`: 886 → 850 lines (-36 lines, ~4% reduction)

**Design:** Uses callback-based approach - router receives `persist_fn`, `debug_fn`, `finalize_fn` from caller to avoid moving tightly-coupled debug infrastructure.

**Verification:** All 146 tests pass

### P1: Pre-Route Pipeline Extraction — 2025-12-27

**Summary:** Extracted pre-routing logic from `workflow_email.py` to `backend/workflows/runtime/pre_route.py`.

**New Module:**
- `pre_route.py` (207 lines) - 5 functions for pre-routing pipeline

**Phases extracted:**
1. Duplicate message detection
2. Post-intake halt check
3. Guard evaluation
4. Smart shortcuts
5. Billing flow step correction

**Result:** `workflow_email.py`: 850 → 783 lines (-67 lines, ~8% reduction)

**Verification:** All 146 tests pass

### P2: Make Guards Pure — 2025-12-27

**Summary:** Refactored `backend/workflow/guards.py` to be pure - no metadata writes.

**Changes:**
- Extended `GuardSnapshot` dataclass with new fields:
  - `forced_step: Optional[int]` - Step to force if different from current
  - `requirements_hash_changed: bool` - Whether hash was recomputed
  - `deposit_bypass: bool` - Whether deposit payment bypass is active
- Refactored `evaluate()` to return decisions without side effects
- Updated `pre_route.py` to apply metadata updates from snapshot
- Removed unused imports from guards.py

**Result:** Guards now follow functional programming pattern - compute decisions, return snapshot, caller applies writes.

**Verification:** All 146 tests pass

### W2: Complete HIL Task Extraction — 2025-12-27

**Summary:** Extracted remaining HIL functions from `workflow_email.py` to `backend/workflows/runtime/hil_tasks.py`.

**Functions Moved:**
- `_thread_identifier()` - Get stable thread identifier from state
- `_hil_signature()` - Generate signature to prevent duplicate HIL tasks
- `_hil_action_type_for_step()` - Map workflow step to action type string
- `enqueue_hil_tasks()` (was `_enqueue_hil_tasks`) - Create HIL task records from drafts

**Result:** `workflow_email.py`: 778 → 647 lines (-131 lines, ~17% reduction)

**Verification:** All 146 tests pass + imports verified

### D5: Step 2 Q&A Bridge Extraction — 2025-12-28

**Summary:** Resolved circular dependency between `step2_handler.py` and `general_qna.py` via third module pattern.

**New Modules:**
- `window_helpers.py` (178 lines) - Shared functions for date constraint handling:
  - `_reference_date_from_state`
  - `_resolve_window_hints`
  - `_has_window_constraints`
  - `_window_filters`
  - `_extract_participants_from_state`
  - `_candidate_dates_for_constraints`
- `general_qna.py` (484 lines) - Step 2-specific Q&A bridge:
  - `_search_range_availability`
  - `_present_general_room_qna`

**Result:** `step2_handler.py`: ~3456 → 2920 lines (-536 lines, ~16% reduction)

**Note:** Step 2's Q&A implementation remains separate from the unified `common/general_qna.py` due to its extra features (range availability, router Q&A integration), but circular dependencies are now properly resolved.

**Verification:** All 146 tests pass + imports verified

### C1: Conversation Manager Session Store Split — 2025-12-28

**Summary:** Extracted session/cache management functions from `conversation_manager.py` into dedicated `backend/legacy/session_store.py` module.

**New Module:** `backend/legacy/session_store.py` (~175 lines)
- `active_conversations` - In-memory conversation state storage
- `STEP3_DRAFT_CACHE`, `STEP3_PAYLOAD_CACHE` - Step 3 de-duplication caches
- `render_step3_reply()` - Workflow-driven Step 3 reply rendering
- `pop_step3_payload()` - Retrieve and remove cached Step 3 payload
- Internal helpers: `_step3_cache_key()`, `_normalise_step3_draft()`, `_render_step3_from_workflow()`

**Changes:**
- Created `backend/legacy/` package with `__init__.py` and `session_store.py`
- Updated `backend/api/routes/messages.py` to import from `backend.legacy.session_store`
- Updated `backend/main.py` to import from `backend.legacy.session_store`
- Added backward-compatible re-exports in `conversation_manager.py`

**Verification:** All 146 tests pass + E2E Playwright verified

### C2: Remove Dead Chatbot Code — 2025-12-28

**Summary:** Removed ~694 lines of unused legacy chatbot code from `conversation_manager.py`.

**Removed:**
- `classify_email()`, `extract_information_incremental()`, `generate_response()`
- `create_summary()`, `create_offer_summary()`
- Format/response helpers (`format_room_description()`, `generate_catering_response()`, etc.)
- `SYSTEM_PROMPT`, `ROOM_INFO`, `CATERING_MENU` constants
- `load_room_info()`, `load_catering_menu()`

**Result:** `conversation_manager.py`: ~729 → ~35 lines (-694 lines, 95% reduction)

**Verification:** All 146 tests pass + E2E Playwright verified

---

## Scope (What We're Planning)

Primary targets (big/confusing public surfaces + highest blast radius):

1. `backend/workflow_email.py` (workflow orchestrator / router)
2. `backend/workflows/steps/step1_intake/trigger/step1_handler.py` (Step 1 intake trigger)
3. `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` (Step 2 date confirmation trigger)
4. `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` (Step 3 room availability trigger)
5. `backend/workflows/steps/step4_offer/trigger/step4_handler.py` (Step 4 offer trigger)
6. `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (Step 5 negotiation trigger)
7. `backend/workflows/planner/smart_shortcuts.py` (multi-step shortcut planner, dynamic imports)
8. `backend/conversation_manager.py` (legacy API helper imported by routes)
9. `backend/workflows/steps/step7_confirmation/trigger/step7_handler.py` (Step 7 confirmation + deposit/site visit)

Out of scope for *implementation* in this session:
- Any code changes (today is planning only).
- Anything under `backend/DEPRECATED/` (assumed not part of runtime workflow; confirm with dependency scan before deleting later).

---

## “Preserve Sets” (Contracts We Must Not Break)

Refactoring must preserve these entrypoints/exports first, then improve internals behind them. The code must work fully end to end using playwright in the browser after each major refactoring step: No change in logic or functionality , only refactoring. 

### `W-PUBLIC` — `backend/workflow_email.py`

These are imported by API routes, agents, scripts, and tests:

- `backend/workflow_email.py:170` `DB_PATH`
- `backend/workflow_email.py:934` `process_msg(msg: Dict[str, Any], db_path: Path = DB_PATH) -> Dict[str, Any]`
- `load_db`, `save_db`, `get_default_db`, `run_samples`
- HIL task APIs used by `/api/tasks/*`:
  - `list_pending_tasks`, `approve_task_and_send`, `reject_task_and_send`, `cleanup_tasks`
- **Temporary compatibility**: `backend/workflow_email.py:196` `_ensure_general_qna_classification` (imported by `tests/workflows/qna/test_extraction.py`)

### `I-PUBLIC` — Step 1 Intake

Stable entrypoints used by router/tests:

- `backend/workflows/steps/step1_intake/trigger/process.py:1` exports `process` (re-export shim)
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py:620` `process(state: WorkflowState) -> GroupResult`
- Keep package surface stable: `backend/workflows/steps/step1_intake/__init__.py:1` exports `process`, `classify_intent`, etc.

### `D-COMPAT` — Step 2 Date Confirmation compatibility exports

Today, multiple call sites import from the **compat module**:

- `backend/workflows/steps/step2_date_confirmation/trigger/process.py:1`
- `backend/workflows/groups/date_confirmation/trigger/process.py:1` (shim -> steps)

Must keep:
- `process`
- `ConfirmationWindow`
- `_finalize_confirmation`
- `_resolve_confirmation_window`

Additionally, tests currently expect:
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py:1081` `_present_candidate_dates`
- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py:3330` `_present_general_room_qna`

And `backend/workflows/planner/smart_shortcuts.py` uses dynamic import/getattr:
- `backend/workflows/planner/smart_shortcuts.py:23` imports `...step2...trigger.process`
- `backend/workflows/planner/smart_shortcuts.py:935` looks up `_finalize_confirmation`
- `backend/workflows/planner/smart_shortcuts.py:1074` looks up `_resolve_confirmation_window`

### `O-COMPAT` — Step 4 Offer compatibility export (test expectation)

Pytest collection currently fails because `backend/workflows/steps/step4_offer/trigger/process.py` does **not** export `_apply_product_operations`, but a test imports it:
- `tests/workflows/test_offer_product_operations.py:3` imports `_apply_product_operations` from `backend/workflows/steps/step4_offer/trigger/process`

This is a refactor-adjacent “compat break” that should be handled as part of **test collection stabilization** (see T0).

### `R-PUBLIC` — Step 3 Room Availability public surface

Imported by workflow router, agents/tools, and tests:

- `backend/workflows/steps/step3_room_availability/trigger/process.py:1` (compat re-export shim)
  - `process`, `handle_select_room_action`, `evaluate_room_statuses`, `render_rooms_response`
  - `_flatten_statuses`, `ROOM_OUTCOME_AVAILABLE`, `ROOM_OUTCOME_OPTION`
- `backend/workflows/steps/step3_room_availability/__init__.py:1`
  - `run_availability_workflow` (used by `backend/api/routes/messages.py`)

Additional coupling:
- Tests import `backend.workflows.steps.step3_room_availability.trigger.process` via `importlib.import_module` (string-based); treat these names as stable.

### `O-PUBLIC` — Step 4 Offer public surface

Imported by workflow router, agent tools, tests:

- `backend/workflows/steps/step4_offer/trigger/process.py:1` exports (current):
  - `process`, `build_offer`, `_record_offer`, `ComposeOffer`
- Compatibility must include `_apply_product_operations` (see `O-COMPAT` above).

### `N-PUBLIC` — Step 5 Negotiation public surface

Imported by workflow router, offer step, API routes, tests:

- Step entrypoint:
  - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:90` `process(state)`
- Used by Step 4:
  - `backend/workflows/steps/step5_negotiation/__init__.py:1` exports `_handle_accept`, `_offer_summary_lines` (Step4 imports these)
- Used by API/tasks + tests (direct file import):
  - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:828` `_refresh_billing`
  - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:1220` `_determine_offer_total`

### `S-PUBLIC` — Smart Shortcuts surface

Imported by workflow router and tests:

- `backend/workflows/planner/__init__.py:1` exports `maybe_run_smart_shortcuts`
- Tests also import `backend/workflows/planner/smart_shortcuts.py:_shortcuts_allowed` directly:
  - `tests/specs/gatekeeping/test_shortcuts_block_without_gates.py:6`

### `C-PUBLIC` — Conversation Manager surface (runtime import)

Imported by API routes:

- `backend/api/routes/messages.py:27` imports from `backend/conversation_manager.py`:
  - `active_conversations`, `render_step3_reply`, `pop_step3_payload`

Critical constraint:
- `backend/conversation_manager.py:23` creates an OpenAI client at import time; refactors must remove import-time side effects.

### `F-PUBLIC` — Step 7 Confirmation public surface

Imported by workflow router and group shims:

- `backend/workflows/steps/step7_confirmation/trigger/process.py:1` exports `process` (re-export shim)
- `backend/workflows/steps/step7_confirmation/trigger/step7_handler.py:34` `process(state)`
- `backend/workflows/groups/event_confirmation/*` depends on Step 7 via shims

---

## Dependency Map (Who Imports What)

### `backend/workflow_email.py` importers (high blast radius)

Upstream importers found via ripgrep:
- API routes: `backend/api/routes/messages.py`, `backend/api/routes/tasks.py`, `backend/api/routes/events.py`, `backend/api/routes/clients.py`, `backend/api/routes/config.py`, `backend/api/routes/test_data.py`, `backend/api/routes/workflow.py`
- Agents/tools: `backend/agents/openevent_agent.py`, `backend/agents/tools/*.py`, `backend/agents/chatkit_runner.py`
- Other backend modules: `backend/workflows/advance.py`, `backend/conversation_manager.py`
- Scripts: `scripts/manual_*`, `scripts/tools/measure_offer_step.py`, `scripts/tests/verify_refactor.py`
- Tests: `backend/tests/*`, `tests/flows/run_yaml_flow.py`, plus a few `_legacy` tests

Practical implication:
- Treat `workflow_email.py` as a **public API facade**; split internally but keep imports stable.

### Step 1 Intake importers (medium blast radius)

- Router: `backend/workflow_email.py` calls `backend.workflows.steps.step1_intake.process`
- Planner/guards: import `suggest_dates` from step1 condition module
- Tests import `backend.workflows.steps.step1_intake.trigger.process` or `backend.workflows.steps.step1_intake.trigger`

Practical implication:
- You can refactor `step1_handler.py` relatively safely if `trigger/process.py` remains stable.

### Step 2 Date Confirmation importers (high blast radius in tests + planner)

- `backend/workflow_email.py` calls `backend.workflows.steps.step2_date_confirmation.process`
- `backend/workflows/planner/smart_shortcuts.py` dynamic-imports `trigger/process.py` and reaches into “private” helpers
- Tests import from `backend.workflows.steps.step2_date_confirmation.trigger.process` (including private helpers)

Practical implication:
- Step 2 must maintain **compat exports**, and refactoring should start by creating a stable “Step2 public helper API” (even if only for internal/test use).

### Step 3 Room Availability importers (high blast radius in tests + agents)

- Router: `backend/workflow_email.py` routes to Step 3 via `backend.workflows.steps.step3_room_availability.process`
- API route: `backend/api/routes/messages.py` imports `run_availability_workflow` from Step 3 package
- Agents/tools: `backend/agents/tools/rooms.py` imports `evaluate_room_statuses`, `_flatten_statuses`, and constants from `trigger/process.py`
- Tests: many import `backend.workflows.steps.step3_room_availability.trigger.process` and also `backend.workflows.groups.room_availability.trigger.process` (shim)

Practical implication:
- Step 3 must keep its trigger/process shim stable and preserve `evaluate_room_statuses` + `_flatten_statuses` for tooling/tests.

### Step 4 Offer importers (high blast radius in agents + tests)

- Router: `backend/workflow_email.py` imports `backend.workflows.steps.step4_offer.trigger.process:process`
- Agents/tools: `backend/agents/tools/offer.py` imports `ComposeOffer` and `_record_offer` from trigger/process shim
- Tests: import `process` and `build_offer` from trigger/process shim; one test imports `_apply_product_operations` (compat needed)

Practical implication:
- Treat `backend/workflows/steps/step4_offer/trigger/process.py` as the stable offer API surface, with compat exports.

### Step 5 Negotiation importers (medium-high blast radius)

- Router: `backend/workflow_email.py` routes Step 5 via `backend.workflows.steps.step5_negotiation.process`
- Step 4 imports `_handle_accept` and `_offer_summary_lines` from Step 5 package
- API tasks route imports `_determine_offer_total` directly from `backend.workflows.steps.step5_negotiation.trigger.step5_handler`
- Tests import Step 5 helpers directly (e.g., `_refresh_billing`)

Practical implication:
- Step 5 refactors should keep “public private helpers” stable until all importers migrate.

### Smart Shortcuts importers (critical interception point)

- Router: `backend/workflow_email.py` calls `maybe_run_smart_shortcuts(state)` before entering the routing loop
- Tests import `_shortcuts_allowed` directly from `smart_shortcuts.py`

Practical implication:
- Any smart_shortcuts refactor must preserve behaviour and the `maybe_run_smart_shortcuts` + `_shortcuts_allowed` interfaces.

### Conversation Manager importers (runtime import path)

- `backend/api/routes/messages.py` imports `active_conversations`, `render_step3_reply`, `pop_step3_payload`
- `backend/main.py` imports `active_conversations` for root endpoint

Practical implication:
- Remove import-time OpenAI initialization without breaking these lightweight helpers.

---

## Import/Dependency Guardrails (How to Refactor Without Breaking Things)

Use this checklist before and after each refactor PR.

### 1) Inventory current importers (before moving anything)

```bash
rg -n "from backend\\.workflow_email import" backend tests scripts
rg -n "backend\\.workflow_email\\b" backend tests scripts

rg -n "step2_date_confirmation\\.trigger\\.process" backend tests scripts
rg -n "importlib\\.import_module\\(" backend | rg "step2_date_confirmation"
```

Save the output into the PR description so reviewers see the blast radius.

Also inventory Step 3/4/5 and shortcut importers when refactoring those:

```bash
rg -n "step3_room_availability\\.trigger\\.process" backend tests scripts
rg -n "step4_offer\\.trigger\\.process" backend tests scripts
rg -n "step5_negotiation\\.trigger\\.step5_handler" backend tests scripts
rg -n "maybe_run_smart_shortcuts|smart_shortcuts" backend tests
rg -n "from backend\\.conversation_manager import" backend
```

### 2) Identify “dynamic imports” explicitly

Search for `importlib.import_module`, `__import__`, `getattr(module, "name")`, string-based lookups.

Example hotspot:
- `backend/workflows/planner/smart_shortcuts.py` imports Step 2 trigger dynamically and calls `_finalize_confirmation`/`_resolve_confirmation_window` via `getattr`.

Rule:
- **Don’t rename those symbols until smart_shortcuts no longer relies on them.**

### 3) Make refactors “shim-first”

When splitting files:
- Create the new module(s)
- Move code
- Keep the original file exporting the same names (re-export or thin wrappers)
- Only then migrate importers

### 4) Require “collection clean” before refactors

Before any serious refactor PR:
- `pytest --collect-only` must pass
- Otherwise you’ll confuse “refactor broke it” with “tests already broken”

Suggested command (minimize filesystem writes):
```bash
PYTHONDONTWRITEBYTECODE=1 pytest --collect-only -q -p no:cacheprovider
```

---

## T0 — Stabilize Pytest Collection (Precondition for Safe Refactors)

**Why:** Right now pytest fails during test collection due to stale imports and missing compat exports, so refactors will be risky to validate.

Current collection errors include:
- Missing compat exports:
  - Step 2: `_present_candidate_dates`, `_present_general_room_qna` missing from `backend/workflows/steps/step2_date_confirmation/trigger/process.py`
  - Step 4: `_apply_product_operations` missing from `backend/workflows/steps/step4_offer/trigger/process.py`
- Stale imports in tests:
  - `backend.llm.intent_classifier` no longer exists (migrated)
  - `backend.workflows.nlu.general_qna_classifier` no longer exists (migrated)
- Duplicate test module name causing import mismatch:
  - `tests/specs/dag/test_change_integration_e2e.py`
  - `tests/workflows/test_change_integration_e2e.py`

**Plan (do these in separate small PRs):**

0. **Stop importing `tests/_legacy/*` during collection** (prevents “deselected but still crashing”):
   - Add `tests/_legacy` to `pytest.ini:norecursedirs`, OR add `--ignore=tests/_legacy` to `pytest.ini:addopts`

1. **Restore/extend compat exports** in “DEPRECATED re-export modules” so existing tests can import:
   - Update `backend/workflows/steps/step2_date_confirmation/trigger/process.py`
   - Update `backend/workflows/groups/date_confirmation/trigger/process.py`
   - Update `backend/workflows/steps/step4_offer/trigger/process.py` (or migrate that test to new canonical module)

2. **Fix/replace stale test imports**:
   - Migrate tests from `backend.llm.intent_classifier` to the new canonical module(s) (likely `backend.detection.intent.classifier` or step1’s LLM module, depending on what they need).
   - Replace `backend.workflows.nlu.general_qna_classifier` imports with exports from `backend.workflows.nlu` (package) or `backend.detection.qna.general_qna`.
   - Prefer fixing tests (truth) over resurrecting old modules (shims), unless you need shims temporarily.

3. **Resolve duplicate test module basename**:
   - Rename one test file to a unique name (preferred)
   - OR make test dirs packages with `__init__.py` (more invasive; can have side effects)

**Definition of Done for T0:**
- `PYTHONDONTWRITEBYTECODE=1 pytest --collect-only -q -p no:cacheprovider` passes.

---

## Refactor Strategy (General)

Principles:

1. **Characterize first**: If behavior is unclear, write a characterization test before moving logic.
2. **Move pure code first**: Extract constants, parsing helpers, formatting helpers before moving orchestration.
3. **One PR = one boundary**: Avoid “move 30 functions into 10 files” PRs.
4. **Keep the facade stable**: `workflow_email.py` stays as public entrypoint; internals can move.

---

## Refactor Plan — `backend/workflow_email.py` (Orchestrator / Router)

**Current role:** A “god orchestrator” + task actions + debug/tracing + DB IO coordination.  
**Key entrypoint:** `backend/workflow_email.py:934` `process_msg(...)`

### Target end-state (incremental, shim-first)

Keep `backend/workflow_email.py` as a thin facade that delegates to:
- `backend/workflows/runtime/router.py` (routing loop + step dispatch)
- `backend/workflows/runtime/persistence.py` (load/save + lock path helpers)
- `backend/workflows/runtime/hil_tasks.py` (task listing/approval/rejection/cleanup)
- `backend/workflows/runtime/debug.py` (debug snapshot + trace integration)

### PR sequence (W-series)

**W1 — Make `workflow_email.py` an explicit facade (no behavior change)**
- Add/verify explicit `__all__` for public surface (`W-PUBLIC`)
- Centralize “public API” definitions at top/bottom of file so devs know what not to touch
- Replace ad-hoc prints with `logger` behind flags *later* (don’t mix concerns here)
- Run: `pytest --collect-only` + smoke tests importing `process_msg`

**W2 — Extract HIL task APIs**
- Move `list_pending_tasks`, `approve_task_and_send`, `reject_task_and_send`, `cleanup_tasks` into `backend/workflows/runtime/hil_tasks.py`
- Keep re-exports in `workflow_email.py` to preserve `W-PUBLIC`
- Run: `tests/specs/gatekeeping/test_hil_gates.py`, `tests/workflows/test_hil_progression.py`

**W3 — Extract routing loop**
- Move the `for iteration in range(6): ...` loop into `backend/workflows/runtime/router.py`
- Make router accept a “step dispatcher map” so it’s testable without importing all steps eagerly
- Keep `process_msg` signature stable and delegate
- Run: `tests/e2e_v4/test_full_flow_stubbed.py` + smoke scripts (optional)

**W4 — Debug + logging hygiene**
- Replace unconditional `print(...)` in router with:
  - `logger.debug(...)` guarded by `WF_DEBUG_STATE` (or unified debug flag)
  - or a single `trace_marker` call when trace is enabled
- Ensure routing has consistent structured debug records

---

## Refactor Plan — Step 1 Intake (`step1_handler.py`)

**Current role:** intent classification + extraction + event creation/update + dev-mode UX + gate confirmations + some routing signals.  
**Key entrypoint:** `backend/workflows/steps/step1_intake/trigger/step1_handler.py:620` `process(state)`

### Target end-state (incremental)

Keep `process(state)` as orchestrator, but move helpers into cohesive modules:

- `.../trigger/dev_test_mode.py` (the “continue vs reset” prompt and payload)
- `.../trigger/normalization.py` (quote normalization, acceptance normalization helpers)
- `.../trigger/date_fallback.py` (regex fallback extraction + fallback year)
- `.../trigger/gate_confirmation.py` (detect/parse “confirm date” messages)
- `.../trigger/persistence.py` (small, focused DB write helpers)

### PR sequence (I-series)

**I1 — Extract pure helpers (no behavior change)**
- Move only functions that:
  - don’t touch DB
  - don’t mutate state
  - don’t import heavy step modules
- Keep original names; update imports within Step1 only
- Run: `tests/specs/intake/*`, `tests/workflows/intake/*`

**I2 — Separate dev/test-mode behavior**
- Isolate `DEV_TEST_MODE` logic behind a single helper so it can’t pollute production flows
- Add a minimal unit test for the helper logic (characterization)

**I3 — Reduce cross-step coupling**
- Remove/avoid Step1 importing Step3 actions directly unless it’s part of a formally documented interface
- If Step1 must trigger Step3 actions, route via a dedicated “actions” module (so imports are explicit and testable)

---

## Refactor Plan — Step 2 Date Confirmation (`step2_handler.py`)

**Current role:** parsing + candidate generation + confirmation window resolution + Q&A integration + HIL + change propagation.  
**Key entrypoint:** `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py:757` `process(state)`

### Step 2 refactor must start with compatibility (D0)

Before any file splitting:

**D0 — Restore compat exports (no logic change)**
- Ensure `backend/workflows/steps/step2_date_confirmation/trigger/process.py` exports:
  - `process`
  - `ConfirmationWindow`
  - `_finalize_confirmation`
  - `_resolve_confirmation_window`
  - `_present_candidate_dates`
  - `_present_general_room_qna`
- Mirror the same export list in `backend/workflows/groups/date_confirmation/trigger/process.py`
- Run: Step2-focused tests (see “Golden tests” below)

### Target end-state modules (incremental)

Extract by “cohesive cluster” (start with pure code):

- `.../trigger/types.py`: `ConfirmationWindow`, type aliases, small dataclasses
- `.../trigger/constants.py`: month/weekday maps, regex tokens, thresholds
- `.../trigger/parsing.py`: all “text → date/time hints” helpers
- `.../trigger/candidates.py`: generating next5/candidate windows and ranking
- `.../trigger/presentation.py`: `_present_candidate_dates` and related rendering helpers
- `.../trigger/confirmation.py`: `_resolve_confirmation_window`, `_finalize_confirmation`
- `.../trigger/general_qna.py`: `_present_general_room_qna` + general Q&A bridge
- `.../trigger/change_routing.py`: change propagation branch (detect + route decision application)

### PR sequence (D-series)

**D1 — Extract constants/types**
- Move only constant dicts, regex patterns, dataclasses
- Zero behavior change, minimal import changes

**D2 — Extract parsing helpers**
- Move “pure parsing” functions that accept `(text, anchor)` and return values
- Add 2–3 unit tests per parsing module for date edge cases (characterization)

**D3 — Extract candidate presentation helpers**
- Move `_present_candidate_dates` cluster into `presentation.py`
- Keep compat re-exports working (tests still import from trigger/process)

**D4 — Extract confirmation resolution**
- Move `_resolve_confirmation_window` and `_finalize_confirmation` into `confirmation.py`
- Ensure `smart_shortcuts.py` continues to work (getattr names preserved)

**D5 — Extract Q&A bridge**
- Move `_present_general_room_qna` into `general_qna.py`
- Keep structured output/links logic together (snapshots, pseudo links, menu payload)

---

## Refactor Plan — Step 3 Room Availability (`step3_handler.py`)

**Current role:** gate checks (date/participants) + room evaluation + room selection action + general Q&A bridge + change propagation.  
**Key entrypoint:** `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:74` `process(state)`

### Known critical correctness fix (plan only)

**R0 — Fix UnboundLocal crash in menu Q&A fallback**
- Bug source: `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1293` `_general_qna_lines`
  - `request` is only defined in the `else:` branch, but later read unconditionally (`if request:`).
- Minimal fix approach:
  - Initialize `request: Optional[Dict[str, Any]] = None` near the start of `_general_qna_lines`.
- Tests to use as regression:
  - `tests/specs/date/test_general_room_qna_flow.py`
  - `tests/specs/date/test_general_room_qna_multiturn.py`

### Target end-state (incremental)

Keep Step 3’s `process(state)` as orchestrator and split cohesive clusters:

- `.../trigger/constants.py`: ROOM_OUTCOME values, thresholds, ordering
- `.../trigger/types.py`: Ranked payload types (if needed)
- `.../trigger/detours.py`: `_detour_to_date`, `_detour_for_capacity`, `_skip_room_evaluation`
- `.../trigger/evaluation.py`: `evaluate_room_statuses`, `_flatten_statuses`, ranking + alternative dates
- `.../trigger/selection.py`: `handle_select_room_action` and DB updates
- `.../trigger/presentation.py`: `render_rooms_response`, payload formatting, pseudo-links
- `.../trigger/general_qna.py`: `_general_qna_lines`, `_present_general_room_qna`, snapshot creation
- `.../trigger/change_routing.py`: change detection + routing decision application

### PR sequence (R-series)

**R1 — Extract constants/types (no behaviour change)**
- Move constant dicts + static thresholds out of `step3_handler.py`
- Keep trigger/process shim exports stable

**R2 — Extract general Q&A bridge**
- Move `_general_qna_lines` + `_present_general_room_qna` into `general_qna.py`
- Keep signature stable and keep trigger/process exports intact

**R3 — Extract selection action**
- Move `handle_select_room_action` into `selection.py`
- Preserve external imports (agents/tools import this via trigger/process shim)

**R4 — Extract evaluation/presentation clusters**
- Move `evaluate_room_statuses`, `render_rooms_response`, and formatting helpers into cohesive modules
- Add characterization tests for:
  - “room_status remains unselected until action”
  - “room selection advances to step 4”

---

## Refactor Plan — Step 4 Offer (`step4_handler.py`)

**Current role:** offer readiness checks + product ops + offer compose/persist + billing gate prompts + Q&A bridge + change propagation + HIL transitions.  
**Key entrypoint:** `backend/workflows/steps/step4_offer/trigger/step4_handler.py:58` `process(state)`

### Compatibility prerequisite (plan only)

**O0 — Restore `_apply_product_operations` export**
- Update `backend/workflows/steps/step4_offer/trigger/process.py` to re-export `_apply_product_operations` from `step4_handler.py`
- Keep `ComposeOffer`, `_record_offer`, `build_offer`, `process` stable
- Tests impacted: `tests/workflows/test_offer_product_operations.py`

### Target end-state (incremental)

Split into modules that match the function clusters already visible in the file:

- `.../trigger/preconditions.py`: `_evaluate_preconditions`, `_route_to_owner_step`, “is offer ready?”
- `.../trigger/product_ops.py`: `_apply_product_operations`, normalisation, upsert helpers
- `.../trigger/compose.py`: `_record_offer`, `_compose_offer_summary`, and any “build_offer payload” helpers
- `.../trigger/billing_gate.py`: billing refresh + “awaiting billing” prompts + continuation gate helpers
- `.../trigger/general_qna.py`: `_present_general_room_qna` + deferred Q&A append logic
- `.../trigger/change_routing.py`: detours / `route_change_on_updated_variable` application

### PR sequence (O-series)

**O1 — Extract product ops cluster**
- Move `_apply_product_operations` + normalization helpers into `product_ops.py`
- Keep trigger/process shim re-exporting `_apply_product_operations`

**O2 — Extract billing gate cluster**
- Move `_refresh_billing`, `_flag_billing_accept_pending`, and billing prompt draft functions
- Coordinate with Step 5 (same concepts duplicated there) but refactor one step at a time

**O3 — Extract offer compose/persist cluster**
- Move `_record_offer` and “compose summary lines” helpers into `compose.py`
- Keep agent tool imports working (`backend/agents/tools/offer.py` imports `_record_offer` and `ComposeOffer`)

---

## Refactor Plan — Step 5 Negotiation (`step5_handler.py`)

**Current role:** classify client reply to offer + billing capture for acceptance + HIL negotiation loop + confirmation gate continuation.  
**Key entrypoint:** `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:90` `process(state)`

### Target end-state (incremental)

Split around the major function clusters:

- `.../trigger/classification.py`: `_collect_detected_intents`, `_classify_message`, clarification prompt
- `.../trigger/billing_gate.py`: `_refresh_billing`, `_flag_billing_accept_pending`, billing prompt draft
- `.../trigger/hil.py`: `_apply_hil_negotiation_decision`, `_start_hil_acceptance`, stale request clearing
- `.../trigger/summary.py`: `_offer_summary_lines`, `_determine_offer_total`, formatting helpers
- `.../trigger/general_qna.py`: `_present_general_room_qna`, deferred Q&A append

### PR sequence (N-series)

**N1 — Isolate debug prints behind a flag**
- Replace unconditional `print` with `logger.debug` gated behind an env flag (align with `WF_DEBUG_STATE`)
- Keep debug signal available for testing but silent by default

**N2 — Extract classification cluster**
- Move message classification helpers into `classification.py`
- Preserve external imports via Step 5 package `__init__.py` until all call sites migrate

**N3 — Extract billing gate cluster**
- Move billing functions into `billing_gate.py`
- Coordinate with Step 4 after Step 5 is stable (avoid two moving targets in one PR)

---

## Refactor Plan — Smart Shortcuts (`smart_shortcuts.py`)

**Current role:** intercept at step >= 3, combine multi-step confirmations, create HIL tasks, and short-circuit the routing loop.  
**Key entrypoint:** `backend/workflows/planner/smart_shortcuts.py:274` `maybe_run_smart_shortcuts(state)`

### Non-negotiable constraints

- Must preserve `maybe_run_smart_shortcuts` signature and return shape (router depends on it).
- Must preserve `_shortcuts_allowed` signature (tests import it).
- Must preserve Step 2 dependency names until decoupled:
  - `ConfirmationWindow`, `_finalize_confirmation`, `_resolve_confirmation_window` are accessed via `getattr` on `backend.workflows.steps.step2_date_confirmation.trigger.process`.

### Target end-state (incremental)

Split the file into “leafy” modules first (low coupling):

- `planner/shortcuts_flags.py`: env flag parsing + policy defaults
- `planner/shortcuts_types.py`: dataclasses/telemetry/result payload structures
- `planner/shortcuts_gate.py`: `_shortcuts_allowed`, `_coerce_participants`, debug gate logging
- `planner/shortcuts_planner.py`: `_ShortcutPlanner` class (event snapshot + plan)
- `planner/shortcuts_render.py`: message composition / summary lines / pre-asks

Then reduce dynamic imports by creating a stable Step 2 helper API (later):
- `backend/workflows/steps/step2_date_confirmation/public_api.py` (or similar) with explicit exports used by smart_shortcuts

### PR sequence (S-series)

**S1 — Extract env flags + gating**
- Move `_flag_enabled`, `_shortcuts_allowed`, and related helpers into `shortcuts_gate.py` + `shortcuts_flags.py`
- Keep old names re-exported from `smart_shortcuts.py` for compatibility

**S2 — Extract types/telemetry**
- Move dataclasses and telemetry payload objects into `shortcuts_types.py`

**S3 — Extract planner core** (COMPLETE ✅ All 5 phases done 2025-12-28)

Phase 1 (complete):
- Created `budget_parser.py` (~120 lines): `extract_budget_info`, `parse_budget_value`, `parse_budget_text`
- Created `dag_guard.py` (~115 lines): `dag_guard`, `is_date_confirmed`, `is_room_locked`, `can_collect_billing`, `set_dag_block`, `ensure_prerequisite_prompt`

Phase 2 (complete):
- Created `date_handler.py` (~320 lines, 16 functions): time utilities, window conversion, date slot/options, window resolution, date intent parsing, date confirmation, combo execution
- Updated `smart_shortcuts.py` with thin wrapper delegation pattern

Phase 3 (complete):
- Created `product_handler.py` (~280 lines, 13 functions): format_money, missing_item_display, products_state, product_lookup, normalise_products, infer_quantity, current_participant_count, format_product_line, product_subtotal_lines, build_product_confirmation_lines, parse_product_intent, apply_product_add, load_catering_names
- Continued thin wrapper delegation pattern

Phase 4 (complete):
- Created `choice_handler.py` (~470 lines, 8 functions): load_choice_context (TTL-based), parse_choice_selection (ordinal/label/fuzzy), choice_clarification_prompt, format_choice_item, apply_choice_selection, complete_choice_selection, handle_choice_selection, maybe_handle_choice_context_reply
- Created `preask_handler.py` (~522 lines, 12 functions): preask_feature_enabled, menu_preview_lines, explicit_menu_requested, process_preask, maybe_emit_preask_prompt_only, handle_preask_responses, detect_preask_response, single_pending_class, prepare_preview_for_requests, hydrate_preview_from_context, build_preview_for_class, maybe_preask_lines, finalize_preask_state
- Net reduction: ~467 lines from smart_shortcuts.py

Phase 5 (complete):
- Created `intent_parser.py` (~238 lines, 7 functions): parse_room_intent, can_lock_room, parse_participants_intent, parse_billing_intent, add_needs_input, defer_intent, persist_pending_intents
- Created `intent_executor.py` (~319 lines, 7 functions): execute_intent, apply_room_selection, apply_participants_update, select_next_question, question_for_intent, missing_item_display (delegating), format_money (delegating)
- Net reduction: ~115 lines from smart_shortcuts.py (1079 -> 964 lines)

**S3 Final Result:** `smart_shortcuts.py` reduced from 1,985 lines to 964 lines (~51% reduction)

---

## Refactor Plan — Conversation Manager (`conversation_manager.py`)

**Current role:** legacy UI glue for API routes, plus a large amount of dead/legacy chatbot logic.  
**Key constraints:** `backend/api/routes/messages.py` imports `active_conversations`, `render_step3_reply`, `pop_step3_payload`.

### Immediate safety prerequisite (plan only)

**C0 — Remove import-time OpenAI initialization**
- Current issue: `backend/conversation_manager.py:23` creates OpenAI client at import.
- Minimal safe approach:
  - Lazily initialize OpenAI client inside `extract_information_incremental` only (it is no longer called by routes).
- Better medium-term approach:
  - Split module into a “safe to import” session/cache module and an “LLM extraction” module.

### Target end-state (incremental)

- `backend/legacy/session_store.py`: `active_conversations`, Step3 draft/payload caches, `render_step3_reply`, `pop_step3_payload` (no OpenAI)
- `backend/legacy/extraction.py`: (optional) `extract_information_incremental` and any OpenAI usage (lazy)
- Keep `backend/conversation_manager.py` as a thin re-export shim until importers migrate

### PR sequence (C-series)

**C1 — Extract session store ✅** (2025-12-28)
- Created `backend/legacy/session_store.py` with ~175 lines: `active_conversations`, Step3 caches, `render_step3_reply`, `pop_step3_payload`
- Updated `backend/api/routes/messages.py` and `backend/main.py` to import from new location
- Added backward-compatible re-exports in `conversation_manager.py`
- Verified: All 146 tests pass + E2E Playwright verified

**C2 — Delete/move dead chatbot functions ✅** (2025-12-28)
- Removed ~694 lines of unused legacy chatbot code from `conversation_manager.py`
- Reduced file from ~729 lines to ~35 lines (minimal re-export shim)
- Deleted: `classify_email`, `extract_information_incremental`, `generate_response`, `create_summary`, `create_offer_summary`, format/response helpers, SYSTEM_PROMPT, ROOM_INFO, CATERING_MENU
- Historical copy preserved at `backend/DEPRECATED/conversation_manager_v0.py`
- Verified: All 146 tests pass + E2E Playwright verified

---

## Refactor Plan — Step 6 Transition (`step6_handler.py`)

**Current role:** small deterministic checkpoint that verifies “ready to confirm” invariants.  
**Key entrypoint:** `backend/workflows/steps/step6_transition/trigger/step6_handler.py:16` `process(state)`

Planning note:
- Step 6 is already small and cohesive; treat it as a “leaf step” and avoid refactors unless we change Step 7/confirmation gates.
- If Step 6 logic grows, split `_collect_blockers` into `common/gates/transition.py` and keep `process` thin.

---

## Refactor Plan — Step 7 Confirmation (`step7_handler.py`)

**Current role:** final confirmation, with deposit + site visit subflows, plus general Q&A bridge and structural-change detours.  
**Key entrypoint:** `backend/workflows/steps/step7_confirmation/trigger/step7_handler.py:34` `process(state)`

### Target end-state (incremental)

Split into modules that match the function clusters:

- `.../trigger/constants.py`: keyword lists (confirm/reserve/visit/decline/change/question)
- `.../trigger/classification.py`: `_classify_message`, keyword matching helpers
- `.../trigger/structural_change.py`: `_detect_structural_change` and detour payload composition
- `.../trigger/site_visit.py`: visit slot generation + preference parsing + slot confirmation
- `.../trigger/confirmation.py`: `_prepare_confirmation`, `_handle_deposit_paid`, `_handle_reserve`, `_handle_decline`
- `.../trigger/hil.py`: `_process_hil_confirmation`
- `.../trigger/general_qna.py`: `_present_general_room_qna`, `_append_deferred_general_qna`

### PR sequence (F-series)

**F1 — Extract constants + classification helpers**
- Move keyword lists + `_classify_message` helpers into `constants.py` / `classification.py`
- Keep `process` unchanged and keep trigger/process shim stable

**F2 — Extract site visit subflow**
- Move `_generate_visit_slots`, `_extract_site_visit_preference`, `_handle_site_visit_preference`, `_parse_slot_selection`, `_handle_site_visit_confirmation`, `_ensure_calendar_block`
- This reduces “largest risk surface” because site visit has distinct state machine (`site_visit_state`)

**F3 — Extract general Q&A bridge**
- Move `_present_general_room_qna` + deferred append into `general_qna.py`
- Align interface shape with Step 2/3/4/5 Q&A bridges so it’s predictable

---

## Test Shim Migration — `backend/workflows/groups/*` vs `steps/*`

Current state:
- Runtime imports mostly use `steps/*`.
- Tests still import `groups/*` heavily (string-based imports).

Policy proposal:

1. **Freeze `groups/*` as pure re-export only** (no new logic, no new dependencies).
2. Add a lightweight guard (test or lint) that fails if new code imports `backend.workflows.groups.*` outside tests.
3. Migrate tests gradually:
   - Start with Step 2 + Step 3 tests that use `importlib.import_module("backend.workflows.groups...")`
   - Then migrate intake tests
4. Once tests no longer rely on groups, delete groups tree (optional, later).

---

## Import Boundary Enforcement (Prevent Future Entropy)

Goal: prevent cycles and “agent-coded” cross-layer imports that make refactors fragile.

Proposed boundaries:

- API routes (`backend/api/routes/*`) must not be imported by workflow steps
- Workflow steps (`backend/workflows/steps/*`) may import `backend/workflows/common/*`, `backend/workflows/io/*`, `backend/detection/*`, `backend/services/*`
- `backend/workflow_email.py` is the only orchestrator entrypoint used by API routes/agents

Implementation options:

1. **Custom pytest gatekeeping test** (AST-based import scan; no third-party deps)
2. **import-linter** (more powerful, but adds a dependency and config)

Start small: implement a gatekeeping test that asserts `backend/workflows/steps/**` doesn’t import `backend/api/**` or `backend/main.py`.

---

## Routing Pipeline Consolidation (Guards + Detours + Shortcuts)

This is the “make detours/shortcuts safer” track.

### Problem summary

Multiple interception points can mutate `current_step` and/or short-circuit routing:
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` can set step and halt early
- `backend/workflow/guards.py:evaluate` can force steps 2–4 and currently mutates event metadata
- `backend/workflows/planner/smart_shortcuts.py:maybe_run_smart_shortcuts` can intercept at step >= 3
- `backend/workflow_email.py` does ad-hoc “billing flow correction” and then loops routing
- Steps 2/3/4/5/7 each implement their own “change detection then Q&A” ordering

Result:
- It’s easy to introduce “step says 5 but step5 never runs” style bugs because state changes happen in multiple places.

### Target end-state (incremental)

Create a single, explicit “pre-route pipeline” that:

1. Reads state and computes a decision (no side effects)
2. Applies state changes (step updates, caller_step updates) in one place
3. Produces one of:
   - “halt with reply”
   - “route to step X”
   - “run smart shortcut”

Practical shape:
- `backend/workflows/runtime/pre_route.py`:
  - `compute_guard_snapshot(state) -> GuardSnapshot`
  - `compute_shortcut_decision(state) -> Optional[GroupResult]`
  - `compute_forced_step(state) -> Optional[int]` (billing/deposit overrides)
- Router applies `update_event_metadata(...)` exactly once per transition.

### Implementation plan (later PRs)

- Make `backend/workflow/guards.py:evaluate` pure (no `update_event_metadata`), returning only `GuardSnapshot`
- Move billing/deposit overrides into the same pre-route stage (so ordering is deterministic)
- Ensure smart shortcuts never run when billing/deposit flows are active (already partially done via `_shortcuts_allowed`)
- Keep “change detection before Q&A” inside steps for now, but extract shared helper:
  - `backend/workflows/change_propagation.py:apply_change_detour_if_any(state, from_step)` (thin wrapper around detect+route+metadata)

### Acceptance Criteria (What “Correct Routing” Means)

These criteria define what the new pre-route pipeline must guarantee. They also define the minimum tests juniors should write when refactoring routing logic.

#### Ordering / precedence rules

Pre-route decisions must be applied in this precedence order (highest first):

1. **Hard overrides (must win over guards + shortcuts)**
   - **Site-visit in progress**: if `event_entry.site_visit_state.status == "proposed"`, force `current_step=7`.
   - **Billing capture in progress**: if `offer_accepted` and `billing_requirements.awaiting_billing_for_accept`, force `current_step=5`.
   - **Deposit GUI continuation**: if `message.extras.deposit_just_paid == True` and `offer_accepted`, force `current_step=5` and bypass guard forcing.

2. **Deterministic guards (Steps 2–4 only)**
   - Guards may force `current_step` only to {2, 3, 4} and only when no hard override is active.
   - Guards must not mutate the DB in the “pure guards” target end-state (they return `GuardSnapshot`; the router applies updates).

3. **Smart shortcuts**
   - Smart shortcuts may run only when:
     - `SMART_SHORTCUTS=true`
     - `current_step >= 3`
     - not in billing flow
     - not in site-visit proposed mode
     - not a deposit_just_paid continuation

4. **Step routing loop**
   - Once `current_step` is decided, the router must call exactly that step handler next.

#### Invariants (must always be true)

- If `current_step == 5` **before entering the routing loop**, Step 5 must run (unless Step 1 halted the turn with a user-facing reply).
- “Deposit just paid” synthetic messages must never:
  - overwrite billing address, or
  - be intercepted by smart shortcuts, or
  - be diverted to Steps 2–4 by guards.
- If `site_visit_state.status == "proposed"`, date/time mentions must not detour to Step 2 date confirmation.
- The router must flush persistence once at end-of-turn (coalesced), not from inside steps.

#### Verification tests to add (characterization)

Create router-level tests that monkeypatch step handlers to prove order/precedence without relying on LLM calls:

- `test_router_forces_step7_when_site_visit_proposed()`
  - Arrange: event has `site_visit_state.status="proposed"` but `current_step != 7`
  - Assert: router routes to Step 7 next (no Step 2 detour)
- `test_router_forces_step5_when_awaiting_billing()`
  - Arrange: event has `offer_accepted=True` and `awaiting_billing_for_accept=True`
  - Assert: smart shortcuts are not called; Step 5 is called
- `test_router_deposit_just_paid_bypasses_guards_and_shortcuts()`
  - Arrange: message has `deposit_just_paid=True`, event has `offer_accepted=True`
  - Assert: guards don’t force Steps 2–4; Step 5 is called

Implementation tip for juniors:
- Patch `backend.workflows.steps.step5_negotiation.process` (or the router’s dispatcher map) to increment a counter so you can assert “Step 5 ran”.

---

## Workflow DB IO Consolidation (DB_PATH + Persistence Discipline)

Goals:
- One DB path source of truth.
- One persistence mechanism (file lock + atomic write).
- Steps mutate `event_entry` only; router persists once (avoid “force save” inside steps).

### Current state

- Canonical DB IO lives in `backend/workflows/io/database.py` (`load_db`, `save_db`, locking, schema defaults).
- `backend/workflow_email.py` wraps DB IO and sets `DB_PATH = Path(__file__).with_name("events_database.json")`.
- Some code still has “local constants” like `EVENTS_FILE = "events_database.json"` in routes (even if unused).
- Step 5 imports `backend.workflows.io.database as db_io` and has “force save” patterns (risk: inconsistent persistence expectations).

### Plan (later PRs)

1. Make `backend/workflow_email.py:DB_PATH` the sole “DB path constant” used by routes and scripts.
2. Forbid direct disk writes from step handlers:
   - Steps set `state.extras["persist"] = True`
   - Router (`process_msg`) calls persistence helpers once per stage
3. Remove/avoid duplicate DB path constants in API routes; routes should call `wf_load_db()` / `wf_save_db()`.
4. Add a tiny guard test that fails if a step module calls `save_db` directly (AST scan).

### Audit Findings (Current Direct Writes Outside Router)

These are the concrete places that violate (or partially violate) “router persists once” discipline today:

- Step 5 “force save” (should be removed once characterization proves router flush is sufficient):
  - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:159` `db_io.save_db(state.db, state.db_path)`
  - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py:168` `db_io.save_db(state.db, state.db_path)`
- Step 3 standalone workflow (separate from email router; decide whether it remains an exception):
  - `backend/workflows/steps/step3_room_availability/db_pers/room_availability_pipeline.py:619` `_save_workflow_db(db)`
- Legacy/UI helper persistence (not step handler, but still a non-router writer):
  - `backend/conversation_manager.py:130` `wf_save_db(db)` (inside Step 3 render helper)

### DB1 Plan (How to Remove Step-Level “Force Save” Safely)

1. Add a characterization test that reproduces the historical bug (“billing captured but not persisted”):
   - Use `backend/workflow_email.py:934` `process_msg(..., db_path=tmp_path / "events.json")`
   - Arrange an event in the DB at Step 5 with `awaiting_billing_for_accept=True`
   - Send a billing address message
   - Assert: persisted DB file contains parsed `billing_details` after the call returns
2. Remove Step 5’s direct `db_io.save_db(...)` calls and rely on:
   - `state.extras["persist"] = True`
   - router `_flush_pending_save(...)` at end-of-turn
3. Re-run the characterization test + `tests/specs/ux/test_billing_captured_vs_saved_chip.py`.

---

## Detection vs Workflow Contracts (Stable Interfaces)

Problem:
- Imports have been migrated (e.g., intent classifier, general Q&A classifier), but tests and some code still reference old paths.
- Refactors break easily when call sites import deep internal modules instead of stable facades.

Target end-state:
- “Stable import surfaces” for detection and NLU:
  - `backend/detection/__init__.py` exports canonical classifiers/matchers
  - `backend/workflows/nlu/__init__.py` re-exports workflow-facing NLU helpers
- Steps import only from these stable surfaces (not `backend/detection/.../internal_file.py`).

Migration plan:
1. Fix pytest collection by migrating tests off old import paths (preferred).
2. If needed, add temporary shims:
   - `backend/workflows/nlu/general_qna_classifier.py` re-exporting from `backend/workflows/nlu` / `backend/detection/qna/general_qna`
   - `backend/llm/intent_classifier.py` shim re-exporting from `backend/detection/intent/classifier`
3. Once tests are migrated, delete shims and enforce boundaries with a gatekeeping test.

---

## Shim Deprecation Timeline (Tests + Imports)

Goal: stop tests (and any runtime code) from importing unstable/old paths, without creating long-lived “compat forever” debt.

### Phase 0 — Stop the bleeding (T0)

Make `pytest --collect-only` succeed:

- Ignore legacy test directory during collection:
  - Add `tests/_legacy` to `pytest.ini:norecursedirs` (or `--ignore=tests/_legacy`)
- Fix missing compat exports:
  - Step 2: extend `backend/workflows/steps/step2_date_confirmation/trigger/process.py` exports
  - Step 4: export `_apply_product_operations` from `backend/workflows/steps/step4_offer/trigger/process.py`
- Resolve the duplicate test module basename conflict:
  - `tests/specs/dag/test_change_integration_e2e.py`
  - `tests/workflows/test_change_integration_e2e.py`

### Phase 1 — Temporary shims (fastest to unblock)

Create shims only for **paths referenced by v4 tests** (not for legacy tests):

- `backend/llm/intent_classifier.py` → re-export from `backend/detection/intent/classifier.py`
  - Needed because `tests/specs/ux/test_multi_variable_qna.py` imports `backend.llm.intent_classifier`.
- `backend/workflows/nlu/general_qna_classifier.py` → re-export from `backend/workflows/nlu/__init__.py`
  - Needed because `tests/specs/nlu/test_general_qna_classifier.py` imports it.

Rules:
- Put a clear “DEPRECATED” module docstring.
- Keep shim modules **thin re-exports only** (no logic).

### Phase 2 — Migrate tests to canonical imports (preferred long-term)

In a follow-up PR, update tests to import stable surfaces directly:

- Replace `from backend.llm.intent_classifier import ...` with:
  - `from backend.detection.intent.classifier import ...` (or `from backend.detection.intent import ...`)
- Replace `from backend.workflows.nlu.general_qna_classifier import ...` with:
  - `from backend.workflows.nlu import detect_general_room_query, reset_general_qna_cache`
- Migrate “groups” imports in tests to “steps” imports gradually:
  - `backend.workflows.groups.intake.*` → `backend.workflows.steps.step1_intake.*`
  - `backend.workflows.groups.date_confirmation.*` → `backend.workflows.steps.step2_date_confirmation.*`
  - `backend.workflows.groups.room_availability.*` → `backend.workflows.steps.step3_room_availability.*`
  - `backend.workflows.groups.offer.*` → `backend.workflows.steps.step4_offer.*`

### Phase 3 — Remove shims + enforce boundaries

Once tests no longer import old paths:
- Delete shim modules.
- Add a gatekeeping test that fails if new code imports:
  - `backend.workflows.groups.*` outside tests
  - deleted “old path” shims

---

## Characterization Tests (Deposit + Site Visit)

These tests lock down Step 7’s state machine without depending on LLM behavior.

### Where to add

- `tests/specs/confirmation/test_step7_deposit_and_site_visit.py` (new)
- `tests/specs/transition/test_step6_transition_blockers.py` (optional, new)

### Deposit flow tests (Step 7)

1. `test_step7_confirm_requires_deposit_when_required_and_unpaid()`
   - Arrange: `deposit_info.deposit_required=True`, `deposit_info.deposit_paid=False`
   - Act: call `backend/workflows/steps/step7_confirmation/trigger/process.py:process`
   - Assert:
     - `action == "confirmation_deposit_requested"`
     - `event_entry.deposit_state.status == "requested"`
     - `thread_state == "Awaiting Client"`
2. `test_step7_deposit_paid_message_advances_to_hil_confirmation()`
   - Arrange: same event, plus `event_entry.deposit_state.status="requested"`
   - Act: message text contains “deposit … paid”
   - Assert:
     - `action == "confirmation_draft"`
     - `thread_state == "Waiting on HIL"`
     - `event_entry.confirmation_state.pending.kind == "final_confirmation"`
3. `test_step7_hil_callback_finalizes_confirmation()`
   - Arrange: `confirmation_state.pending.kind == "final_confirmation"`, `state.user_info={"hil_approve_step": 7}`
   - Assert:
     - `action == "confirmation_finalized"`
     - `event_entry.event_data.Status == "Confirmed"`

### Site visit flow tests (Step 7)

1. `test_step7_site_visit_proposes_slots_and_sets_state()`
   - Patch `site_visit_allowed` to `True`
   - Patch `_generate_visit_slots` to deterministic output
   - Assert:
     - `action == "confirmation_site_visit"`
     - `site_visit_state.status == "proposed"`
     - `confirmation_state.pending.kind == "site_visit"`
2. `test_step7_hil_callback_sends_site_visit_proposal()`
   - Arrange: pending kind `site_visit`, `state.user_info={"hil_approve_step": 7}`
   - Assert: `action == "confirmation_site_visit_sent"`
3. `test_step7_client_selects_slot_confirms_visit()`
   - Arrange: `site_visit_state.status == "proposed"` with slots
   - Use message text **without numeric date tokens** (e.g., “the first one works”)
   - Assert:
     - `action == "site_visit_confirmed"`
     - `site_visit_state.status == "scheduled"`

### Known fragility to capture (expected future bugfix)

`backend/workflows/steps/step7_confirmation/trigger/step7_handler.py:_extract_site_visit_preference` currently treats any digits as a “time preference”.
That can mis-handle messages like “1st option please” or “17.07.2026 works”.

Plan:
- Add `test_step7_site_visit_numeric_selection_prefers_slot_selection_over_time_preference()` as `xfail` until fixed.

---

## Dependency Detection Toolkit (How Juniors Can Avoid Breaking Imports)

Recommended “no new tooling” workflow:

1. Find importers before moving anything:
   - `rg -n "from X import" backend tests scripts`
   - `rg -n "X\\b" backend tests scripts`
2. Detect dynamic imports:
   - `rg -n "importlib\\.import_module\\(|__import__\\(" backend`
3. Validate collection + minimal suites:
   - `PYTHONDONTWRITEBYTECODE=1 pytest --collect-only -q -p no:cacheprovider`
   - Run the “Golden tests” for the area you changed

Optional (later) tooling ideas:
- Add a small AST script (no deps) that outputs “module → importers” mapping for a given package.

---

## “Golden Tests” to Run Per PR (Minimal Suites)

Use these to reduce time while maintaining confidence:

### Router / workflow_email PRs
- `backend/tests/smoke/test_backend_startup.py`
- `tests/e2e_v4/test_full_flow_stubbed.py`
- `tests/workflows/test_hil_progression.py`

### Step 1 PRs
- `tests/specs/intake/test_intake_loops.py`
- `tests/specs/intake/test_entity_capture_shortcuts.py`
- `tests/workflows/intake/*`

### Step 2 PRs
- `tests/specs/date/test_general_room_qna_flow.py`
- `tests/specs/date/test_general_room_qna_multiturn.py`
- `tests/specs/date/test_vague_date_month_weekday_flow.py`
- `tests/workflows/date/test_confirmation_window_recovery.py`
- `tests/specs/ux/test_message_hygiene_and_continuations.py`

### Step 3 PRs
- `tests/specs/room/test_room_availability.py`
- `tests/specs/room/test_room_status_unselected_until_selection.py`
- `tests/gatekeeping/test_room_selection_advances_to_step4.py`
- `tests/specs/ux/test_message_hygiene_and_continuations.py`

### Step 4 PRs
- `tests/workflows/test_offer_product_operations.py`
- `tests/specs/products_offer/test_offer_compose_send.py`
- `tests/specs/ux/test_message_hygiene_and_continuations.py`

### Step 5 PRs
- `tests/specs/gatekeeping/test_hil_gates.py`
- `tests/workflows/test_hil_progression.py`
- `backend/tests/regression/test_deposit_to_hil_flow.py` (if/when included in default lane)

### Smart Shortcuts PRs
- `tests/specs/gatekeeping/test_shortcuts_block_without_gates.py`
- `tests/specs/detours/test_no_redundant_asks_with_shortcuts.py`

### Conversation Manager PRs
- `backend/tests/smoke/test_backend_startup.py` (ensures importing API routes doesn’t require an OpenAI key)

### Step 7 PRs
- `tests/specs/ux/test_timeline_export.py` (touches multi-step flow and should reveal state machine regressions)
- Add a dedicated characterization test for site visit state machine (new test; plan only)

---

## PR Queue (Jira-style Backlog)

Estimates are rough (single developer, with tests).

| ID | Title | Files (primary) | Depends On | Risk | Est. |
|---:|-------|------------------|------------|------|------|
| T0 | ✅ Fix pytest collection (compat + stale imports + dup test name) | tests/*, Step2/Step4 compat shims (2025-12-27) | - | - | DONE |
| W1 | ✅ Make `workflow_email.py` explicit facade | `__all__` organized with semantic groups (2025-12-27) | T0 | - | DONE |
| W2 | ✅ Extract HIL task APIs (keep re-exports) | `hil_tasks.py` + facade (-131 lines) (2025-12-27) | W1 | - | DONE |
| W3 | ✅ Extract router loop (keep `process_msg`) | `backend/workflows/runtime/router.py` (2025-12-27) | W2 | - | DONE |
| I1 | ✅ Extract Step1 pure helpers | 6 modules extracted (2025-12-27) | - | - | DONE |
| I2 | ✅ Isolate dev/test mode flow | `dev_test_mode.py` already exists | - | - | DONE |
| D0 | ✅ Restore Step2 compat exports | Committed 2025-12-27 | - | - | DONE |
| D1 | ✅ Step2 constants/types extraction | `constants.py`, `types.py` (2025-12-27) | - | - | DONE |
| D2 | ✅ Step2 parsing extraction + tests | `date_parsing.py` (2025-12-27) | - | - | DONE |
| D3 | ✅ Step2 candidate presentation extraction | `proposal_tracking.py` (2025-12-27) | - | - | DONE |
| D4 | ✅ Step2 confirmation resolution extraction | `calendar_checks.py` (2025-12-27) | - | - | DONE |
| D5 | ✅ Step2 Q&A bridge extraction | `general_qna.py` created (2025-12-28) | D4 | - | DONE |
| R0 | ✅ Fix Step3 Q&A request crash | Already fixed (line 1431 init) | T0 | - | DONE |
| R1 | ✅ Step3 constants/types extraction | `trigger/constants.py` (2025-12-28) | R0 | - | DONE |
| R2 | ✅ Step3 Q&A bridge extraction | Unified in `common/general_qna.py` (2025-12-27) | - | - | DONE |
| R3 | ✅ Step3 selection action extraction | `selection.py` (256 lines) + dedup cleanup (2025-12-28) | R2 | - | DONE |
| O0 | ✅ Step4 compat export (verified working) | process.py compat shim intact (2025-12-27) | - | - | DONE |
| O1 | ✅ Step4 product ops extraction | `product_ops.py` (465 lines) committed 2025-12-27 | O0 | - | DONE |
| O2 | ✅ Step4 billing gate consolidation | `common/billing_gate.py` shared by Step4+5 (2025-12-27) | O1 | - | DONE |
| N1 | ✅ Step5 debug/log hygiene | Removed WF_DEBUG prints (-27 lines) (2025-12-27) | - | - | DONE |
| N2 | ✅ Step5 classification extraction | `classification.py` (118 lines) verified 2025-12-27 | N1 | - | DONE |
| N3 | ✅ Step5 billing gate extraction | `common/billing_gate.py` (118 lines) verified 2025-12-27 | N2 | - | DONE |
| S1 | ✅ Smart shortcuts gate/flags extraction | `shortcuts_flags.py` + `shortcuts_gate.py` (2025-12-28) | T0 | - | DONE |
| S2 | ✅ Smart shortcuts types/telemetry extraction | `shortcuts_types.py` (153 lines) (2025-12-28) | S1 | - | DONE |
| S3 | Smart shortcuts planner extraction | planner submodules + facade | S2 | High | 4–10h |
| C0 | ✅ Conversation manager: lazy OpenAI init | Already fixed (_get_openai_client) | T0 | - | DONE |
| C1 | ✅ Conversation manager session store split | `backend/legacy/session_store.py` (175 lines) (2025-12-28) | C0 | - | DONE |
| C2 | ✅ Conversation manager dead code removal | Removed 694 lines dead code (729→35) (2025-12-28) | C1 | - | DONE |
| G0 | ✅ Freeze groups as pure re-export | All 65 files verified + guard tests (2025-12-28) | T0 | - | DONE |
| B0 | ✅ Import boundary enforcement test | `test_import_boundaries.py` (2025-12-28) | T0 | - | DONE |
| F1 | ✅ Step7 constants/classification extraction | `constants.py`, `classification.py`, `helpers.py` (2025-12-27) | T0 | - | DONE |
| F2 | ✅ Step7 site-visit extraction | `site_visit.py` (370 lines) (2025-12-27) | F1 | - | DONE |
| F3 | ✅ Step7 Q&A bridge extraction | Unified in `common/general_qna.py` (2025-12-27) | - | - | DONE |
| P1 | ✅ Introduce pre-route pipeline module | `runtime/pre_route.py` (207 lines) 2025-12-27 | W3 | - | DONE |
| P2 | ✅ Make guards pure (no metadata writes) | `guards.py` pure + `pre_route.py` applies (2025-12-27) | - | - | DONE |
| DB1 | Remove step-level force-save patterns | Step5 (and any others) | P1 | Medium | 2–6h |
| DCON1 | Detection import surface cleanup | tests + optional shims | T0 | Medium | 2–6h |

---

## What’s Still Left to Plan (After This Document)

These areas still need the same “planning sheet” treatment (dependency map + safe PR ladder + golden tests):

1. **Site-visit parsing spec**: decide the intended precedence between “slot selection” vs “time preference” when messages contain digits (e.g., “1st option”, “17.07.2026 works”) and encode it in tests.
2. **Pre-route module API + trace contract**: define the exact return shape and trace markers for `runtime/pre_route.py` so step routing is observable and debuggable without ad-hoc prints.
3. **Exception policy for non-router DB writes**: decide whether `run_availability_workflow` (Step 3 pipeline) and `conversation_manager` caching are allowed to write DB directly or must go through a single persistence facade.
4. **Deposit schema convergence**: decide whether `deposit_info` or `deposit_state` is canonical, and define a migration plan so Step 4/5/7 don’t maintain two competing representations.

---

## Quick Commands (For Future Refactor Sessions)

```bash
# Fast import sanity (avoid writing .pyc)
PYTHONDONTWRITEBYTECODE=1 python3 -c "import backend.workflow_email; print('ok')"

# Inventory importers
rg -n "from backend\\.workflow_email import" backend tests scripts
rg -n "step2_date_confirmation\\.trigger\\.process" backend tests scripts

# Ensure collection is healthy
PYTHONDONTWRITEBYTECODE=1 pytest --collect-only -q -p no:cacheprovider
```
