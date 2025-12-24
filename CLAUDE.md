# CLAUDE.md

This file provides guidance to Claude (Opus 4.5) working on the OpenEvent-AI repository.

## Current Stage: Testing / Pre-Production (December 2025)

**The application is feature-complete for core workflow (Steps 1-7) and in active testing phase.**

Goals for this phase:
- Make the system **resilient against diverse client inputs** (multiple languages, edge cases)
- Achieve **production stability** with comprehensive regression tests
- Eliminate circular bugs and ensure all code paths are covered
- Complete integration with Supabase/Hostinger for production deployment

**Key metrics to watch:**
- No silent fallback messages reaching clients
- All HIL tasks route correctly
- Special flows (billing, deposit, site visit) work end-to-end
- LLM outputs fact-checked via "safety sandwich" validation

## Your Role

- Act as a senior test- and workflow-focused engineer
- Keep the system aligned with the management plan "Lindy" and Workflow v3/v4 specifications
- Prioritize deterministic backend behaviour and strong automated tests over ad-hoc changes
- Maintain clear documentation of bugs in `docs/TEAM_GUIDE.md` and new features/changes in `DEV_CHANGELOG.md`. **You must automatically update these files without being asked.**
- **CRITICAL:** Before fixing ANY bug, you **MUST** consult `docs/TEAM_GUIDE.md` to see if it's a known issue or if there are specific handling instructions.
- **Session Startup:** At the start of EVERY new session, you **MUST** read:
  1. `git log` (last few commits) to understand recent context.
  2. `DEV_CHANGELOG.md` to see high-level changes.
  3. `docs/TEAM_GUIDE.md` to be aware of current bugs and guidelines.
  4. Workflow v4 specs in `backend/workflow/specs/` if relevant to the task.
- For new ideas collected in the chat (often too big to implement in the same task, happy accidents/ideas that happened while fixing another problem) write them to new_features.md in root so we can discuss them later. 

## NO-TOUCH ZONES (Requires Explicit Permission)

**NEVER modify these files/directories without explicit user permission:**

- `backend/workflows/specs/` (These are the "Source of Truth" definitions; do not change the law to fit the code)
- `configs/llm_profiles.json` (LLM Configuration)
- `backend/config.py` (Core backend configuration)
- `backend/utils/openai_key.py` (Authentication logic)
- `.env` / `.env.example` (Environment configuration)
- `atelier-ai-frontend/package.json` / `backend/requirements.txt` (Dependency definitions - ask before adding deps)

## QUALITY GATES (Run Before Committing)

**Before ANY commit, ensure these pass:**

1. **Backend Tests:**
   ```bash
   pytest
   ```
   *Must pass with zero failures.*

2. **Frontend Check:**
   ```bash
   cd atelier-ai-frontend && npm run build
   # and if applicable:
   npm test
   ```
   *Must build without errors.*

3. **Type/Lint Checks (if applicable):**
   - Check for obvious syntax errors or type mismatches before finalizing.

## REGRESSION PREVENTION & WORKFLOW

1. **ONE change at a time**
   - Do not combine refactors with bug fixes.
   - Do not combine multiple feature implementations. Rather write them to new_features.md for later.

2. **List affected files BEFORE writing code**
   - Explicitly state: "I plan to modify X, Y, and Z."

3. **Scope Guard**
   - If a task requires touching more than 3 files, **STOP and ask for confirmation**.
   - Do not "cleanup" unrelated code while fixing a bug.

4. **Verify Tests First**
   - Before fixing a bug, run the test that reproduces it.
   - If no test exists, write one.

## Canonical Vocabulary and Concepts

**Use these exact terms (do not invent new ones):**
- Core entities: `msg`, `user_info`, `client_id`, `event_id`, `intent`, `res`, `task`
- Workflow components:
  - OpenEvent Action (light-blue)
  - LLM step (green)
  - OpenEvent Database (dark-blue)
  - Condition (purple)
- Event statuses: `Lead` → `Option` → `Confirmed`
- Workflow steps: Follow documented Workflow v3/v4, all Steps 1–7 and their detours

## Primary References

**Always open/re-read relevant ones before major changes:**

**Living documents (check frequently):**
- `DEV_CHANGELOG.md` - Recent changes, fixes, new features (check at session start!)
- `docs/TEAM_GUIDE.md` - Bugs, open issues, heuristics, prevention patterns
- `backend/workflow/specs/` - V4 workflow specifications (authoritative)

**Architecture & workflow:**
- `docs/workflow_rules.md` - Core workflow rules
- Openevent - Workflow v3 TO TEXT (MAIN).pdf - Main workflow reference
- `docs/internal/step4_step5_requirements.md` - Offer/negotiation requirements

**Legacy (for context only):**
- AI-Powered Event Management Platform.pdf
- Workflow v3.pdf
- Technical Workflow v2.pdf

## Environment and API Keys

**Never hard-code API keys:**
- Assume OPENAI_API_KEY is provided via environment, possibly sourced from macOS Keychain item "openevent-api-test-key"
- Python code and tests must obtain the key via `backend/utils/openai_key.load_openai_api_key()`, not `os.getenv` directly

**Before running any tests or scripts that call OpenAI:**
1. Use the dev server script (preferred) or activate manually:
   ```bash
   ./scripts/dev_server.sh   # Handles everything including API key
   # OR manually:
   source scripts/oe_env.sh
   ```

2. Run tests (API key loaded automatically):
   ```bash
   # Primary test suites
   pytest backend/tests/detection/ -v    # Detection tests
   pytest backend/tests/regression/ -v   # Regression tests
   pytest backend/tests/flow/ -v         # Workflow flow tests
   ```

## Debugger and Conversation Traces

**The OpenEvent debugger provides real-time tracing of all workflow activity. Use it to understand what happened during any conversation thread.**

### Enabling Debug Traces

Debug tracing is enabled by default. Control via environment variable:
```bash
DEBUG_TRACE=1  # Enable (default)
DEBUG_TRACE=0  # Disable
```

### Live Log Files (Recommended for AI Agents)

**The fastest way to see what's happening in a conversation** is to tail the live log file:

```bash
# Watch a specific thread in real-time
tail -f tmp-debug/live/{thread_id}.log

# List all active threads with live logs
curl http://localhost:8000/api/debug/live

# Get live log content via API
curl http://localhost:8000/api/debug/threads/{thread_id}/live
```

Live logs are:
- **Human-readable** — Simple timestamp + event format
- **Real-time** — Written as events happen
- **Auto-cleaned** — Deleted when thread closes

Example live log output:
```
[14:23:01] >> ENTER Step1_Intake
[14:23:01] Step1_Intake | LLM IN (classify_intent): Subject: Private Dinner...
[14:23:02] Step1_Intake | LLM OUT (classify_intent): {"intent": "event_request"...
[14:23:02] Step1_Intake | GATE PASS: email_present (1/2)
[14:23:02] Step1_Intake | CAPTURED: participants=30
[14:23:02] Step1_Intake | STATE: date=2026-02-14, date_confirmed=True
[14:23:02] << EXIT Step1_Intake
```

### Debug API Endpoints

When debugging issues, access conversation traces via these endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/api/debug/live` | **List active threads with live logs** |
| `/api/debug/threads/{thread_id}/live` | **Get live log content** |
| `/api/debug/threads/{thread_id}` | Full trace with state, signals, timeline |
| `/api/debug/threads/{thread_id}/timeline` | Timeline events only |
| `/api/debug/threads/{thread_id}/report` | Human-readable debug report |
| `/api/debug/threads/{thread_id}/llm-diagnosis` | LLM-optimized diagnosis |
| `/api/debug/threads/{thread_id}/timeline/download` | Download JSON export |
| `/api/debug/threads/{thread_id}/timeline/text` | Download text export |

### LLM Diagnosis Endpoint

**Most important for AI debugging:** The `/api/debug/threads/{thread_id}/llm-diagnosis` endpoint returns a structured, LLM-optimized format including:
- Quick status (date, room, hash, offer confirmation)
- Problem indicators (hash mismatches, detour loops, gate failures)
- Last 5 events with summaries
- Key state values

Example usage:
```bash
curl http://localhost:8000/api/debug/threads/{thread_id}/llm-diagnosis
```

### Frontend Debugger

Access the visual debugger at `http://localhost:3000/debug` which provides:
- Thread selection and status overview
- Detection view (intent classification, entity extraction)
- Agents view (LLM prompts and responses)
- Errors view (auto-detected problems)
- Timeline view (full event timeline)
- Dates view (date value transformations)
- HIL view (human-in-the-loop tasks)

### Trace Event Types

The tracer captures these event types:
- `STEP_ENTER`/`STEP_EXIT` — Step transitions
- `GATE_PASS`/`GATE_FAIL` — Gate evaluations with inputs
- `DB_READ`/`DB_WRITE` — Database operations
- `ENTITY_CAPTURE`/`ENTITY_SUPERSEDED` — Entity lifecycle
- `DETOUR` — Step detours with reasons
- `QA_ENTER`/`QA_EXIT`/`GENERAL_QA` — Q&A flow
- `DRAFT_SEND` — Draft messages
- `AGENT_PROMPT_IN`/`AGENT_PROMPT_OUT` — LLM prompts and responses

### Key Files

| File | Purpose |
|------|---------|
| `backend/debug/live_log.py` | **Human-readable live logs** (recommended for AI agents) |
| `backend/debug/trace.py` | Core trace event bus and emit functions |
| `backend/debug/hooks.py` | Trace decorators and helpers |
| `backend/debug/reporting.py` | Report generation and LLM diagnosis |
| `backend/debug/timeline.py` | Timeline persistence (JSONL format) |
| `backend/debug/state_store.py` | State snapshot store |

## Behaviour Around Bugs and Features

### Before Fixing a Bug

1. **Read TEAM_GUIDE.md** and search for a matching bug description
2. If it exists, update that entry with:
   - Current status (open / investigating / fixed)
   - File(s) touched
   - Test(s) covering it (paths and test names)
3. If it does not exist, add a new entry under "Bugs and Known Issues" with:
   - Short title
   - Description
   - Minimal reproduction scenario

### After Fixing a Bug

1. Add or update automated tests so the bug cannot silently reappear
2. Mark the bug as fixed in TEAM_GUIDE.md, referencing the tests that now cover it

### For New Features, Refactors and Changes

Maintain a lightweight log in DEV_CHANGELOG.md at repo root:
- Date (YYYY-MM-DD)
- Short description
- Files touched
- Tests added/updated

newest entries at the top.

## Bug Prevention Patterns (CRITICAL)

**These patterns prevent the most common circular bugs. Check ALL of them before implementing any fix.**

### Pattern 1: Special Flow State Detection

When the workflow is in a special state (billing capture, deposit waiting, site visit), **ALL code paths must check for it** and bypass normal detection.

**The Billing Flow Pattern (model for all special flows):**
```python
# Check BEFORE any change detection or routing
in_billing_flow = (
    event_entry.get("offer_accepted")
    and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
)

if in_billing_flow:
    # Skip date change detection
    # Skip room change detection
    # Skip requirements change detection
    # Skip duplicate message detection
    # Route directly to billing handler
```

**Checklist for any special flow state:**
1. ✅ `workflow_email.py` - Duplicate message detection
2. ✅ `workflow_email.py` - Step routing loop
3. ✅ `step1_handler.py` - Change detection (date, room, requirements)
4. ✅ Step handlers (step4/step5) - Confirmation gate checks

### Pattern 2: Step Corruption Prevention

**Problem:** Event gets stored at wrong step, causing wrong routing on next message.

**Solution:** Force correct step BEFORE the routing loop, not after:
```python
# In workflow_email.py, BEFORE the main routing loop:
if in_billing_flow and stored_step != 5:
    print(f"[WF][BILLING_FIX] Correcting step from {stored_step} to 5")
    state.event_entry["current_step"] = 5
    state.extras["persist"] = True
```

### Pattern 3: Response Key Access

**Problem:** Different handlers return different response structures, causing KeyError.

**Solution:** Always use defensive `.get()` with defaults:
```python
# BAD - will crash if structure differs
body = response["draft"]["body"]

# GOOD - handles missing keys gracefully
draft = response.get("draft") or {}
body = draft.get("body", "Default message")
```

### Pattern 4: The "Detection Bypass" Rule

**When fixing detection issues:** If a message should NOT trigger detection (e.g., billing address shouldn't trigger room change), add an **early return** guard, not a late filter:

```python
# At the TOP of detection function
if in_special_flow:
    return None  # Skip detection entirely

# NOT at the bottom filtering results
```

### Pattern 5: Hash Guard Verification

Before modifying room/date/requirements state, verify hash guards:
```python
# If room_eval_hash exists and matches requirements_hash, room is still valid
# If offer_hash exists and matches current state, offer is still valid
# Only clear hashes when the underlying data actually changes
```

### Common Circular Bug Patterns (From Recent History)

| Pattern | Symptom | Cause | Fix |
|---------|---------|-------|-----|
| **Wrong step routing** | Event at Step 3 instead of Step 5 | Previous flow set step incorrectly | Force correct step before routing |
| **Duplicate detection blocks flow** | `action=duplicate_message` | Special flow not exempted | Add `in_special_flow` bypass |
| **Change detection during special flow** | Date/room change triggered when providing billing | Detection runs on all messages | Add `in_special_flow` guard |
| **Response key mismatch** | KeyError on `response["body"]` | Handler returns `{"draft": {"body": ...}}` | Use `.get()` chains |
| **HIL task not created** | Workflow completes but no task | Missing `actions` in response | Check return structure |

### Testing Special Flows

Always test with:
1. **Fresh event** - New inquiry through full flow
2. **Existing event at mid-step** - Continue from specific state
3. **Corrupted state** - Event with wrong step value
4. **Edge case inputs** - Empty strings, unicode, multilingual

### Frontend End-to-End Testing Protocol (CRITICAL)

**For billing→deposit→HIL flow and other critical workflows, ALWAYS verify in the actual frontend UI, not just via API/Python tests.** Some issues only manifest in the frontend session flow due to session/thread_id handling.

**Protocol for Frontend Testing:**

1. **Use fresh client data:**
   - Use a new email address (e.g., `test-YYYYMMDD@example.com`), OR
   - Click "Reset Client" button to clear existing client data

2. **Run complete flow in frontend:**
   - Start conversation with initial inquiry
   - Go through each step (date → room → offer)
   - Accept offer → Provide billing → Pay deposit
   - Verify HIL task appears in "📋 Manager Tasks" section

3. **Verify database state after each critical step:**
   ```bash
   python3 -c "
   import json
   with open('backend/events_database.json') as f:
       db = json.load(f)
   for e in db.get('events', []):
       if 'YOUR_EMAIL' in json.dumps(e):
           print(f'Step: {e.get(\"current_step\")}')
           print(f'Billing: {(e.get(\"billing_details\") or {}).get(\"street\")}')
           print(f'HIL Tasks: {len(e.get(\"pending_hil_requests\", []))}')
   "
   ```

4. **Expected outcomes for billing→HIL flow:**
   - `billing_details.street` populated after billing message
   - `awaiting_billing_for_accept=False` after billing captured
   - `deposit_paid=True` after Pay Deposit clicked
   - `pending_hil_requests` contains offer_message task
   - "📋 Manager Tasks" section visible with Approve/Reject buttons

**Why frontend testing matters:** The frontend uses `/api/send-message` which has different session handling than direct `process_msg()` calls. Issues like billing not being captured can occur in frontend but not in API tests.

## Testing Principles (High Priority)

**The test suite is the main guardrail; keep it clean, well-structured and focused on high-value behaviours.**

- Prefer pytest with clear naming and structure
- Tests should be organized for easy discovery:
  - Detection tests (Q&A, confirmation, shortcuts, special manager request, detours)
  - Workflow tests (Steps 1–4, Status Lead/Option/Confirmed, gatekeeping)
  - Q&A and general shortcuts
  - GUI/frontend/chat integration where applicable

**For each major detection type in the workflow, strive to have:**
- A happy-path test
- One or more edge-case tests

**Always add tests for:**
- Regressions mentioned in TEAM_GUIDE.md
- Known fallback/stub issues
- Detours and conflict logic

## Fallback and "Old Default" Behaviour

**Main goal: Prevent the system from silently falling back to old stub responses or generic defaults.**

When you see code paths that:
- Emit very generic messages ("sorry, cannot handle this request" or old templates)
- Or bypass the current Workflow v3/v4 logic

Add assertions or tests so that such paths are detectable and fail loudly in tests.

**When writing or updating tests:** Add expectations so that if a fallback/stub message appears in a flow that should be handled deterministically, the test fails.

## Working Style

- Always explain in plain language what you are doing and why, but keep responses concise
- Use the existing workflow files and terminology exactly; do not invent new step names or statuses
- Prefer minimal, targeted changes over large refactors

**For any non-trivial change to tests or workflow logic:**
- State the relevant workflow rule or document you are following
- Outline the tests you will add/update
- Ensure that running pytest under scripts/oe_env.sh will validate your work

## When in Doubt

- **Check TEAM_GUIDE.md** first - the bug may already be documented with a fix
- **Check DEV_CHANGELOG.md** - recent changes may explain unexpected behavior
- **Re-read Bug Prevention Patterns** (above) before implementing any fix
- Prefer adding or strengthening tests before changing logic

## Project Overview

OpenEvent is an AI-powered venue booking workflow system for The Atelier. It automates the end-to-end booking flow from client email intake through event confirmation, maintaining deterministic state across a 7-step workflow with human-in-the-loop (HIL) approvals.

**Architecture:** Monorepo with Python FastAPI backend + Next.js frontend, driven by a deterministic workflow engine that gates AI responses through HIL checkpoints.

## Development Commands

### Backend (Python FastAPI)

**Preferred: Use the dev server script (handles cleanup, API keys, PID tracking):**
```bash
./scripts/dev_server.sh         # Start backend (with auto-cleanup)
./scripts/dev_server.sh stop    # Stop backend
./scripts/dev_server.sh restart # Restart backend
./scripts/dev_server.sh status  # Check if running
./scripts/dev_server.sh cleanup # Kill all dev processes (backend + frontend)
```

**Manual startup (if dev_server.sh unavailable):**
```bash
# Start backend server (from repo root)
export PYTHONDONTWRITEBYTECODE=1  # prevents .pyc permission issues on macOS
source scripts/oe_env.sh  # loads API key from Keychain
uvicorn backend.main:app --reload --port 8000
```

**Run specific workflow step manually:**
Deprecated. Please use the dev server or run tests.

### Frontend (Next.js)
```bash
# Start frontend dev server (from repo root)
npm run dev
# Opens at http://localhost:3000

# In atelier-ai-frontend directory
npm run dev      # dev with turbopack
npm run build    # production build
npm run start    # production server
npm test         # vitest
```

### Testing

**Primary test suites:**
```bash
# Run all tests
pytest

# Run by category
pytest backend/tests/detection/ -v    # Intent/entity detection
pytest backend/tests/regression/ -v   # Regression tests (critical!)
pytest backend/tests/flow/ -v         # Workflow flow tests

# Run single test with verbose output
pytest backend/tests/regression/test_billing_flow.py -v

# Run with live OpenAI (not stubbed)
AGENT_MODE=openai pytest backend/tests/flow/ -v
```

**Quick validation command:**
```bash
# Recommended: Run detection + regression + flow tests
pytest backend/tests/detection/ backend/tests/regression/ backend/tests/flow/ -v --tb=short
```

### Dependencies
```bash
# Python (backend)
pip install -r requirements-dev.txt  # test dependencies
# Main dependencies are inferred from imports (fastapi, uvicorn, pydantic)

# Frontend
cd atelier-ai-frontend && npm install
```

## Workflow Architecture (V3/V4 Authoritative)

**Sources of Truth:**
- Workflow v3 documents (see Primary References above)
- `backend/workflow/specs/` contains v4 workflow specifications:
  - `v4_dag_and_change_rules.md` - Dependency graph and minimal re-run matrix
  - `no_shortcut_way_v4.md` - Complete state machine with entry guards
  - `v4_shortcuts_and_ux.md` - Shortcut capture policy and UX guarantees
  - `v4_actions_payloads.md` - Action/payload contracts

### Canonical State Variables

The workflow maintains these core variables:
- `chosen_date` and `date_confirmed` (boolean)
- `requirements = {participants, seating_layout, duration(start-end), special_requirements}`
- `requirements_hash` (SHA256 of requirements)
- `locked_room_id` (null until room confirmed)
- `room_eval_hash` (snapshot of requirements_hash used for last room check)
- `selected_products` (catering/add-ons)
- `offer_hash` (snapshot of accepted commercial terms)
- `caller_step` (who requested the detour)

### Dependency DAG

```
participants ┐
seating_layout ┼──► requirements ──► requirements_hash
duration ┘
special_requirements ┘
        │
        ▼
chosen_date ───────────────────────────► Room Evaluation ──► locked_room_id
        │                                    │
        │                                    └────────► room_eval_hash
        ▼
Offer Composition ──► selected_products ──► offer_hash
        ▼
Confirmation / Deposit
```

**Key Insight:** Room evaluation depends on confirmed date AND current requirements. Offer depends on room decision (unchanged room_eval_hash) plus products. Confirmation depends on accepted offer. This drives the "detour and return" logic with hash guards to prevent redundant re-checks.

### 7-Step Pipeline (Implementation Locations)

1. **Step 1 - Intake** (`backend/workflows/steps/step1_intake/`):
   - [LLM-Classify] intent, [LLM-Extract] entities (Regex→NER→LLM)
   - Loops: ensure email present, date complete (Y-M-D), capacity present (int)
   - Captures `wish_products` for ranking (non-gating)
   - **Never re-runs post-creation** (HIL edits only)

2. **Step 2 - Date Confirmation** (`backend/workflows/steps/step2_date_confirmation/`):
   - Calls `db.dates.next5` with **TODAY (Europe/Zurich)** ≥ TODAY, blackout/buffer rules
   - Presents none/one/many-feasible flows via [LLM-Verb] → [HIL] → send
   - Parses client reply [LLM-Extract] → ISO date
   - On confirmation: `db.events.update_date`, sets `date_confirmed=true`

3. **Step 3 - Room Availability** (`backend/workflows/steps/step3_room_availability/`):
   - Entry guards: A (no room), B (room change request), C (requirements change)
   - Calls `db.rooms.search(chosen_date, requirements)` → branches:
     - Available: [LLM-Verb] → [HIL] → on "proceed" → `db.events.lock_room(locked_room_id, room_eval_hash=requirements_hash)`
     - Option: explain option → [HIL] → accept option or detour to Step 2
     - Unavailable: propose date/capacity change → detour to Step 2 (caller_step=3) or loop on req change

4. **Step 4 - Offer** (`backend/workflows/steps/step4_offer/`):
   - Validates P1-P4; detours if any fail
   - Compose: [LLM-Verb] professional offer + totals → [HIL] approve
   - Handles billing address capture and deposit requirements
   - Send: `db.offers.create(status=Lead)` → `offer_id`

5. **Step 5 - Negotiation** (`backend/workflows/steps/step5_negotiation/`):
   - Interprets accept/decline/counter/clarification
   - Handles billing flow when offer accepted
   - Structural changes route back to Steps 2/3/4 via detours
   - Accept → hands off to Step 7

6. **Step 6 - Transition Checkpoint** (deprecated - logic merged into Steps 5/7):
   - Validates all prerequisites before Step 7
   - Sets `transition_ready` flag

7. **Step 7 - Confirmation** (`backend/workflows/steps/step7_confirmation/`):
   - Manages site visits, deposits, reserves, declines, final confirmations
   - Option/deposit branches via `db.policy.read`, `db.options.create_hold`
   - All transitions audited through HIL gates

### Deterministic Detour Rules

1. **Always set `caller_step` before jumping**
2. **Jump to the owner step** of the changed variable:
   - Date → Step 2
   - Room/Requirements → Step 3
   - Products/Offer consistency → Step 4
3. **On completion, return to `caller_step`**, unless hash check proves nothing changed (fast-skip)
4. **Hashes prevent churn:**
   - If `requirements_hash` unchanged, skip room re-evaluation
   - If `offer_hash` still matches, skip transition repairs

```
[ c a l l e r ] ──(change detected)──► [ owner step ]
▲                                           │
└──────────(resolved + hashes)──────────────┘
```

### Database & Persistence

**Primary Database:** `backend/events_database.json` (FileLock-protected JSON store)

Schema managed by `backend/workflows/io/database.py`:
- `clients`: Client profiles keyed by lowercased email
- `events`: Event records with metadata, requirements, thread_state, audit logs
- `tasks`: HIL approval tasks (date confirmation, room approval, offer review, etc.)

**DB Adapter Surface (Engine Only; NEVER LLM)**

The workflow engine calls these adapters. **LLM never touches DB directly:**

```python
# Event lifecycle
db.events.create(intake)                              # [DB-WRITE] → event_id
db.events.update_date(event_id, date)                 # [DB-WRITE]
db.events.lock_room(event_id, room_id, room_eval_hash) # [DB-WRITE]
db.events.sync_lock(event_id)                         # [DB-READ/WRITE]
db.events.set_lost(event_id)                          # [DB-WRITE]
db.events.set_confirmed(event_id)                     # [DB-WRITE]

# Date & room operations
db.dates.next5(base_or_today, rules)                  # [DB-READ]
db.rooms.search(date, requirements)                   # [DB-READ]

# Product & offer operations
db.products.rank(rooms, wish_list)                    # [DB-READ]
db.offers.create(event_id, payload)                   # [DB-WRITE]

# Options & policy
db.options.create_hold(event_id, expiry)              # [DB-WRITE]
db.policy.read(event_id)                              # [DB-READ]
```

### LLM Integration

**Adapters:** `backend/workflows/llm/adapter.py` routes to providers in `backend/llm/providers/`
- Intent classification, entity extraction, draft composition all pass curated JSON
- Drafts remain HIL-gated before outbound send
- Profile selection via `backend/config.py` reading `configs/llm_profiles.json`

**LLM Role Separation:**

The workflow uses three distinct LLM roles, each with strict boundaries:

1. **[LLM-Classify]** - Intent classification
   - Determines message intent (inquiry, accept, counter, etc.)
   - Returns structured classification result
   - Used at intake and throughout negotiation

2. **[LLM-Extract]** - Entity extraction (Regex→NER→LLM pipeline)
   - First attempt: Regex patterns for common formats
   - Fallback: NER (Named Entity Recognition)
   - Final refinement: LLM extraction with validation
   - Examples: dates (ISO Y-M-D), capacity (positive int), products, special requirements
   - **NEVER directly accesses database** - only processes text

3. **[LLM-Verb]** - Verbalization/draft composition
   - Composes professional client-facing messages
   - Takes structured data from workflow engine as input
   - Outputs draft messages for HIL approval
   - Examples: date options, room availability, offer composition
   - All drafts go through HIL gate before sending (except tight products loop)

**Critical Boundary:** LLM adapters receive curated JSON payloads from the workflow engine and NEVER call database functions directly. All DB operations flow through the engine's adapter surface.

**Environment Variables:**
- `AGENT_MODE`: `openai` (live) or `stub` (testing) - controls LLM behavior
- `OE_DEV_TEST_MODE`: `true` (show continue/reset choice) or `false` (auto-continue)
- `OE_HIL_ALL_LLM_REPLIES`: `true` to require HIL approval for ALL AI responses
- `OPENAI_API_KEY`: Set via environment or macOS Keychain
- `VERBALIZER_TONE`: `professional` (default) or `plain` for testing

**Testing Philosophy:**
- Tests should use real OpenAI when possible to catch LLM behavior changes
- Always test end-to-end flows (not just unit tests) mimicking real client interactions
- The system must handle diverse inputs without hardcoding specific scenarios
- Current languages: German and English (multilingual expansion planned)

## Important Implementation Notes

**Thread Safety:** Database operations use `FileLock` (in `backend/workflows/io/database.py`). Always use provided helpers (`load_db`, `save_db`) rather than direct JSON access.

**Idempotency:** Re-confirming the same date or re-running availability checks is safe. System checks latest audit log entries to avoid duplicate work.

**Hash Invalidation:** When requirements change (participants, duration, room preference), `requirements_hash` updates, invalidating `room_eval_hash`. Step 3 must re-run for HIL approval.

**Time Handling:** All dates use Europe/Zurich timezone. Tests use `freezegun` for deterministic time (`tests/utils/timezone.py`).

**Detour Recovery:** After detour (e.g., Step 3 → Step 2 for new date → Step 3), system preserves all prior metadata and only re-runs dependent steps.

**Open Decisions:** Write questions which arent clear regarding logic, UX into docs/internal/OPEN_DECISIONS.md and docs/integration_to_frontend_and_database/MANAGER_INTEGRATION_GUIDE.md 

**Git Commits:** For longer sessions with multiple subtasks, **commit frequently** (more than once per session). Commit after every logical step or fully completed subtask. Do not wait until the very end of a long session to commit. This helps track progress and allows for easier rollbacks. I will push the commits later.

**Summaries after completed task** Always provide a short summary referencing every point (completeness!) I mentioned in the beginning of this document after you completed a task. This helps me track your progress and understand what you did. If there are still open points cause there was too much to do pls list them

## Common Gotchas

1. **macOS .pyc Permission Issues:** Run with `python -B` or set `PYTHONDONTWRITEBYTECODE=1`
2. **Missing Calendar Data:** Missing `calendar_data/<id>.json` means room is always free
3. **Step Skipping:** Workflow enforces strict prerequisites; cannot skip to Step 5 without completing Steps 1-4
4. **Hash Mismatches:** If `room_eval_hash` doesn't match `requirements_hash`, Step 3 blocks until re-approved
5. **Pytest Test Selection:** Default runs `v4` tests only; use `-m "v4 or legacy"` to include all
6. **LLM Stub vs Live:** Tests in `tests/stubs/` use stubbed LLM responses; always validate critical flows with live OpenAI key mimicking real client interactions from workflow start to end (offer confirmation).

## General Techniques for Resilient Code

### Defensive State Access

Always assume event_entry fields may be missing or malformed:
```python
# BAD - crashes if billing_requirements is None
billing = event_entry["billing_requirements"]["address"]

# GOOD - handles all missing cases
billing_req = event_entry.get("billing_requirements") or {}
address = billing_req.get("address", "")
```

### Unified Gate Checking

Use the confirmation gate pattern for any multi-prerequisite check:
```python
from backend.workflows.common.confirmation_gate import check_confirmation_gate

gate = check_confirmation_gate(event_entry)
if gate.ready_for_hil:
    # All prerequisites met
elif gate.missing_billing:
    # Request billing
elif gate.missing_deposit:
    # Show deposit button
```

### Detection Pipeline Order

Follow this order to avoid false positives:
1. **Special flow guards** (billing, deposit, site visit) - return early
2. **Duplicate message check** - return early if duplicate
3. **Intent classification** - determine message type
4. **Entity extraction** - Regex → NER → LLM pipeline
5. **Change detection** - only if not in special flow

### Safety Sandwich Pattern

All client-facing LLM output must go through verification:
```python
# 1. Build facts from database (deterministic)
facts = build_room_offer_facts(event_entry)

# 2. Generate LLM draft
draft = llm_verbalize(facts)

# 3. Verify/correct the draft
verified = correct_output(facts, draft)  # Fixes hallucinations

# 4. Only then send to client (via HIL)
```

### Multilingual Resilience

The system handles German and English. When adding detection patterns:
```python
# Include both languages in keyword lists
ACCEPTANCE_KEYWORDS = [
    "yes", "ok", "agree", "accept",  # English
    "ja", "einverstanden", "akzeptiert",  # German
]

# Use case-insensitive matching
if any(kw in message.lower() for kw in ACCEPTANCE_KEYWORDS):
    ...
```

## Dev Test Mode

When testing with existing events, the system offers a continue/reset choice:

**Enable/disable:**
```bash
export OE_DEV_TEST_MODE=true   # Enable choice (default)
export OE_DEV_TEST_MODE=false  # Auto-continue always
```

**Skip programmatically:**
```bash
curl -X POST http://localhost:8000/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"email_body": "...", "skip_dev_choice": true}'
```

## Production Readiness Checklist

Before deploying to production:

### Core Workflow
- [ ] All 7 steps complete happy-path test
- [ ] Detour and return flows work (date change → Step 2 → return)
- [ ] Room lock preservation on date change
- [ ] Site visit flow end-to-end
- [ ] Deposit payment continuation

### HIL Integration
- [ ] All HIL tasks created at correct moments
- [ ] Approve/reject buttons functional
- [ ] Task persistence across server restarts
- [ ] No orphaned tasks (completed events with pending tasks)

### Error Handling
- [ ] No silent fallback messages reaching clients
- [ ] All LLM outputs fact-checked
- [ ] Graceful handling of API timeouts
- [ ] Database lock contention handled

### Security
- [ ] API keys never in code or logs
- [ ] Input sanitization on all client messages
- [ ] Rate limiting on public endpoints

### Observability
- [ ] Debug traces enabled for all flows
- [ ] Error logging with context
- [ ] Performance metrics for LLM calls

## Quick Reference: Key Files

| Purpose | Location |
|---------|----------|
| Main orchestrator | `backend/workflow_email.py` |
| Step handlers | `backend/workflows/steps/step{N}_{name}/trigger/` |
| Confirmation gate | `backend/workflows/common/confirmation_gate.py` |
| Safety sandwich | `backend/ux/verbalizer_safety.py` |
| Database adapter | `backend/workflows/io/database.py` |
| Debug traces | `backend/debug/trace.py` |
| Dev server script | `scripts/dev_server.sh` |
| Test suite | `backend/tests/` |
| Workflow specs | `backend/workflow/specs/` |
