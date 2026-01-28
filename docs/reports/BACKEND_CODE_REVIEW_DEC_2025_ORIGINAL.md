# Backend Code Review (Quality & LLM-Agent Smells) — Dec 2025

Date: 2025-12-24
Scope: `backend/` (FastAPI API layer + workflow engine + detection + adapters + debug tooling)
Context: Builds on `docs/plans/completed/DONE__ARCHITECTURE_FINDINGS_DEC_2025.md` (major cleanup already done). Another agent may be actively editing core workflow behavior; line numbers below reflect the repo state at the time of this review.

Note on "deprecated" code:
- `backend/DEPRECATED/` appears **not imported by runtime backend code** (no `backend.DEPRECATED` references outside that folder). It can be ignored for application behavior as long as that remains true.
- `backend/workflows/groups/` is mostly a **compat layer** (tests/scripts/docs still import it), but runtime workflow routing is currently step-based (`backend/workflow_email.py` imports from `backend/workflows/steps`).

## Executive Summary

The backend has **solid foundational pieces** (atomic JSON DB writes with locking, a step-based workflow engine, meaningful regression tests, and a coherent debug/trace system). However, the codebase still shows several **common agent/LLM failure modes**:

- **Multiple overlapping abstractions** (legacy vs new, `groups/` vs `steps/`, `workflow_email.py` vs newer packages) that increase change risk.
- **Import-time side effects** and "dev convenience" behaviors in production-path modules.
- **Very large, multi-responsibility files** (2k–3.7k LOC) that are hard to reason about and are prone to regressions.
- **Type-safety erosion** via dynamic attributes, loose `Dict[str, Any]` payloads, and broad exception handling.

The most important outcome of this review: there is at least **one concrete runtime bug** (unbound local) and a handful of **high-risk architectural hazards** that are typical of agent-generated code.

---

## Most Critical Findings (Prioritized)

### 1) Runtime bug: unbound local `request` (will raise `UnboundLocalError`)

- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1365`
  - `request` is only set in a specific branch (`else: request = extract_menu_request(...)`), but later referenced unconditionally in the "query params" section.
  - When `payload` already has `rows`, that branch is skipped and `request` is never defined.
  - This is a **true crash bug**, not just a typing issue. It is also reported by `pyright` as "possibly unbound".

Related context:
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1290` (function start for `_general_qna_lines`) and the branch where `request` is assigned.

### 2) Import-time side effects in core modules (brittle startup, hidden coupling)

Import-time side effects are a frequent agent smell because they "work locally" but create hard-to-debug failures in tests, reloaders, and production.

- `backend/conversation_manager.py:23`
  - Creates an `OpenAI` client at import time: `client = OpenAI(api_key=load_openai_api_key())`.
  - Because `backend/api/routes/messages.py` imports `active_conversations` from `conversation_manager`, this makes **API startup dependent on OpenAI key availability**, even when the legacy client is not used.

- `backend/main.py:1`
  - Deletes all `__pycache__` directories at import time.
  - Also repeats a similar cache deletion in FastAPI lifespan (`backend/main.py:64`).
  - This is highly unusual for a server module and can surprise `uvicorn --reload`, tests, or any importers.

### 3) Unconditional debug prints in the hot path (log noise + performance risk)

The code still contains "temporary debug" print statements that run for every inbound message.

- `backend/workflow_email.py:1046` / `backend/workflow_email.py:1056`
  - `[WF][PRE_ROUTE]` and `[WF][ROUTE]` debug prints appear unconditional, not gated by `WF_DEBUG_STATE` or trace flags.
  - These were likely added during the Step-5 routing incident and never properly guarded.

### 4) Duplicate / transitional workflow namespaces (`groups/` vs `steps/`) increase divergence risk

This is a classic "agent refactor halfway done" smell: both namespaces exist and are partially shims, partially real logic.

- `backend/workflows/groups/intake/billing_flow.py:1` and `backend/workflows/steps/step1_intake/billing_flow.py:1`
  - These files are identical today. That is safe **only until the next change**; then they will drift.
  - Recommended: pick a canonical location and re-export from the other, or remove one.

Also present:
- Multiple `groups/*` modules are now "DEPRECATED re-export shims", but many are still "real code" or placeholders.

### 5) Data model bug: `created_at` default is evaluated at import time

- `backend/domain/models.py:177`
  - `created_at: datetime = datetime.now()` is executed once when the module loads, so all instances share the same timestamp.
  - If `ConversationState.created_at` is used for any ordering or TTL logic, this becomes a silent correctness bug.

### 6) "Dynamic attribute injection" into typed state object (`state.flags`)

- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1723`
  - Code dynamically adds `state.flags` even though `WorkflowState` doesn't define it.
  - This bypasses static tooling, makes state shape unclear, and tends to proliferate.
  - `WorkflowState` is a dataclass (`backend/workflows/common/types.py:165`) and currently allows adding new attributes, which hides mistakes.

### 7) Mixed and inconsistent DB file paths (`events_database.json`)

There are multiple "database file" concepts:

- Canonical workflow DB path is `backend/events_database.json` via `backend/workflow_email.py:211` (`DB_PATH = Path(__file__).with_name("events_database.json")`).
- Some API helpers still use a CWD-relative `"events_database.json"`:
  - `backend/api/routes/messages.py:52` and `backend/api/routes/messages.py:115`
  - `backend/main.py:126` and `backend/main.py:356`

Risk:
- When running `uvicorn` from repo root (common), the CWD-relative path is **not the same file** as `backend/events_database.json`.
- Some code paths may read/write the wrong DB or create a second DB file silently.

### 8) Placeholder/unfinished modules left in-tree (confusing, dead weight)

- `backend/workflows/groups/site_visit.py:1` (class stub with `pass`)
- `backend/workflows/groups/response_type.py:1` (class stub with `pass`)
- `backend/relay_trigger.py:1` (empty file)
- `backend/api/debug_backup.py:1` (appears to be a redundant variant of `backend/api/debug.py`)

Even if unused, these raise maintenance cost and confuse readers about what's "real".

---

## Critical Files / Hotspots (High Change Risk)

Largest modules (LOC) are typically where agent-generated code becomes fragile, because it's hard to preserve invariants:

- `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` (~3677 LOC)
- `backend/workflows/planner/smart_shortcuts.py` (~2203 LOC)
- `backend/workflows/steps/step4_offer/trigger/step4_handler.py` (~2141 LOC)
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` (~2083 LOC)
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (~1455 LOC)
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` (~1445 LOC)
- `backend/workflows/steps/step7_confirmation/db_pers/post_offer.py` (~1397 LOC)
- `backend/workflows/change_propagation.py` (~1379 LOC)
- `backend/workflow_email.py` (~1352 LOC)

Recommendation:
- Treat these as **"critical files"** for review discipline: require manual review for changes, add targeted tests, and refactor incrementally (extract helpers with stable contracts).

---

## Findings By Category

### A) Architecture & Module Boundaries

**What's good**
- The "steps" directory structure is a strong direction: `backend/workflows/steps/step{N}_*/{condition,trigger,db_pers,llm}` is a sensible, scalable organization.
- The workflow DB abstraction (`backend/workflows/io/database.py`) has atomic writes + locking and centralizes schema defaults.

**Issues / LLM smells**
- **Parallel architectures** still exist:
  - Legacy conversation UI logic (`backend/conversation_manager.py`) is still imported by production routes.
  - Transitional `groups/` vs `steps/` duplication increases the chance of "fix in one place but not the other".
- **`workflow_email.py` is still the orchestration "god module"**, pulling in many concerns (routing, guards, shortcuts, Q&A extraction, HIL queues, debug tracing).
  - This is workable, but it's high-risk: changes in one feature can accidentally affect others.

### B) API Layer (FastAPI routes)

**Main concerns**
- In-memory session storage (`active_conversations`) is a demo-friendly choice but it is **not production-safe** (multi-worker, restarts, scaling).
  - `backend/api/routes/messages.py:567`
- Type-safety mismatch in `_update_event_info_from_db`:
  - `backend/api/routes/messages.py:198` and `backend/api/routes/messages.py:203` (pyright errors).
  - Runtime may be fine, but the types don't express the invariant "these fields are always non-null".
- Some endpoints still look like "legacy leftovers" (e.g., accept/reject booking writing its own DB) and bypass the DB lock:
  - `backend/api/routes/messages.py:115` and `backend/api/routes/messages.py:123`

### C) Persistence & Concurrency

**What's good**
- Locking + atomic persistence is implemented in `backend/workflows/io/database.py:14` and used by workflow accessors (`backend/workflow_email.py:247`).

**Risks**
- Direct file IO bypasses locks in older helpers (see "Mixed DB file paths" above).
- DB file is checked into the repo (`backend/events_database.json`), which makes merges noisy and can hide regressions via stateful fixtures.

### D) Error Handling, Logging, and "Debug Debt"

Common agent smell: broad `except Exception` + `print` + silent `pass`, especially in core paths.

Examples:
- `backend/main.py:13` (swallows errors while deleting caches)
- `backend/api/routes/messages.py:189` (prints warning, returns partial info)
- `backend/workflow_email.py:1046` (unconditional debug prints in router)
- `backend/api/routes/messages.py:723` (broad `except Exception: pass` for deposit_info)

Recommendation:
- Replace persistent `print(...)` with `logging` (or `structlog`) and gate noisy debug output behind flags.

### E) Type Safety & "Any"-driven design

The codebase contains many well-intentioned type hints, but the actual data flow relies heavily on untyped dictionaries.

Symptoms:
- Lots of `Dict[str, Any]` payloads and "optional everywhere" semantics.
- Dynamic attributes (`state.flags`) and dict mutations (event entries) reduce static guarantees.
- `pyright backend --level error` reports many errors; most are "optional narrowing" issues, but some are real correctness hazards (like the unbound `request`).

Recommendation:
- Identify a small set of **core persistent schemas** (event entry shape, task payload shape, draft message shape) and represent them with `TypedDict` or dataclasses.

### F) Dependencies & Drift

The repo's runtime deps include packages that appear unused by the current backend code:

- `requirements.txt:23` includes `filelock>=3.12.0`, but the backend implements its own lock (`backend/workflows/io/database.py:20`).
- `requirements.txt:32` includes `structlog>=23.1.0`, but there are no `structlog` imports in `backend/` right now.

This is not harmful, but it's a maintenance smell: dependencies should match actual runtime needs.

---

## Suggested Remediation Roadmap (High ROI)

### "Stop the bleeding" (1–2 short PRs)

1) Fix the unbound-local crash in Step 3 Q&A flow
   - `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1365`
2) Gate router debug prints behind `WF_DEBUG_STATE` or trace flag
   - `backend/workflow_email.py:1046`
3) Remove import-time OpenAI client initialization from legacy conversation module
   - `backend/conversation_manager.py:23` (lazy-init or delete if no longer needed)

### "Reduce divergence risk"

4) Decide canonical workflow namespace: keep only `steps/` (recommended) and turn `groups/` into pure re-export shims (or remove it).
   - Start with duplicates like `billing_flow.py` mentioned above.
5) Normalize database file path usage everywhere to a single source of truth (`workflow_email.DB_PATH` or `db_io`).

### "Make changes safer"

6) Break 2k–3.7k LOC step handlers into smaller modules with explicit contracts (pure functions + small orchestrators).
7) Promote a few persistent shapes to `TypedDict` so `pyright` catches real regressions.

---

## Appendix: Static Scan Notes

- `pyright backend/api/routes/messages.py` reports 2 type errors (`backend/api/routes/messages.py:198`, `backend/api/routes/messages.py:203`).
- `pyright backend/workflows --level error` includes at least one **true correctness issue**: unbound `request` (`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py:1365`).