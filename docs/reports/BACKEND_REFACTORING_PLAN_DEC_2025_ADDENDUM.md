# Backend Refactoring Addendum — Production Hardening + LLM Hygiene (Post Plan)

**Date:** 2025-12-27  
**Scope:** Items *not covered* (or not explicit) in `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025.md`  
**Goal:** Production-ready, agent-debuggable, maintainable backend that does not “look LLM-generated”.

This addendum focuses on **cross-cutting hygiene**: logging/error handling, production defaults, LLM integration consolidation, repo hygiene, and a few remaining “god files” outside the step refactor plan.

---

## Key Gaps Found (Not Explicitly Planned in the Main Sheet)

### 1) Production-hostile runtime behavior
- `backend/main.py` performs import-time cache deletion (`__pycache__`) and includes dev-only behaviors (port killing, auto-launch frontend) that should not live in production import paths.
- `backend/workflow_email.py` still contains CLI I/O (`task_cli_loop`) and `print`-driven samples.

### 2) Debug output and fallbacks leaking into user-facing surfaces
- Many non-script modules use `print(...)` (API routes, workflow modules, models), making logs noisy and hard to triage with agents.
- Two overlapping “fallback diagnostics” systems exist:
  - `backend/core/fallback.py`
  - `backend/workflows/common/fallback_reason.py`
  These are partially redundant and both default to showing diagnostics (`OE_FALLBACK_DIAGNOSTICS=true`), which is risky in production.

### 3) “Error infrastructure” exists but is incomplete / under-used
- `backend/core/errors.py:safe_operation(...)` reads like a policy cornerstone but currently **does not implement** the documented fallback signaling (no `SafeOperationFallback`, no return path, no trace emission).
- The codebase contains multiple `except Exception: pass` sites that suppress useful debugging signal (even in non-debug code).

### 4) LLM integration is fragmented
Direct OpenAI SDK usage coexists with the `AgentAdapter` and `backend/llm/provider_registry.py` patterns:
- Direct OpenAI calls in `backend/ux/universal_verbalizer.py`, `backend/detection/qna/general_qna.py`, and others.
- Provider registry exists but is not the single gateway.
This makes timeouts/retries, tracing/redaction, model selection, and deterministic test behavior inconsistent.

### 5) Repo + runtime artifacts tracked in git
The repo currently contains/updates runtime or local artifacts (e.g., `backend/events_database.json`, pid files, tmp caches). This makes code review, CI, and agent-driven debugging harder.

---

## Recommended Tooling (LSP-Style) to Find Smells Faster

Use these as part of PR hygiene (no behavior changes required to start):

- **Pyright** (LSP-grade typechecking): catch `Optional`/`Any` leaks and missing branches early.
- **Ruff**: detect dead code, exception anti-patterns, unused imports, and “LLM-ish” redundancy patterns (too many `Any`, complex branching).
- **Vulture** (optional): detect unused functions/modules after refactors.
- **Bandit** (optional): quick security lint (especially for “dangerous endpoints”, env defaults, and subprocess usage).

If you standardize on these tools, agents (Codex/Claude/Gemini) can quickly narrow root causes from CI output instead of reading the whole codebase.

---

## Addendum Backlog (New PR Ladder)

### WF0 — Post-refactor workflow correctness blockers (P0)

These are *workflow logic* issues (or validation gaps) that should be resolved before spending cycles on new MVP features (Supabase wiring, frontend polish, cost optimizations).

**WF0.1 — Detour execution must never yield an empty workflow reply**
- Symptom pattern: detour is detected (action set) but execution returns no `draft_messages`, triggering an `empty_workflow_reply` fallback.
- Evidence in docs/tests:
  - Playwright detour runs: `tests/playwright/e2e/05_core_detours/test_date_change_room_available.md`, `tests/playwright/e2e/05_core_detours/test_date_change_room_unavailable.md`, `tests/playwright/e2e/05_core_detours/test_room_change_from_step4.md`, `tests/playwright/e2e/05_core_detours/test_requirements_change_from_step4.md`
  - Failing change-propagation suites: `tests/TEST_INVENTORY.md` (see `tests/specs/dag/` failures)
- Work items:
  - Reproduce deterministically (prefer a script/trace) and ensure *every* detour path returns at least one draft or an explicit “waiting” reply (never silent).
  - Add/restore characterization tests for: date-change detour, room-change detour, requirements-change detour, and products-change update.

**WF0.2 — Fix date corruption / wrong-date regressions**
- Evidence in docs:
  - `docs/guides/TEAM_GUIDE.md` (“Date Mismatch: Feb 7 becomes Feb 20 (Open - Investigating)”)
  - `tests/playwright/e2e/04_core_step_gating/test_room_before_date.md` (date drift + wrong day)
- Work items:
  - Identify the format boundary (YYYY-MM-DD vs DD.MM.YYYY) where corruption occurs and enforce a single canonical normalization layer.
  - Add a regression test covering the exact “07.02 → 20.02” corruption pattern.

**WF0.3 — Frontend → backend billing capture intermittent failure**
- Evidence in docs:
  - `docs/guides/TEAM_GUIDE.md` (“Frontend Billing Capture Intermittent Failure (Investigating - 2025-12-23)”)
- Work items:
  - Confirm whether this is a session/thread_id mismatch, request payload issue, or a silent exception in `/api/send-message`.
  - Add an end-to-end reproduction (Playwright preferred) for the full flow: accept → billing → deposit → HIL task visible in manager panel.

**WF0.4 — Make the test suite reflect current v4 behavior (get to “green”)**
- Source of truth for what’s currently failing: `tests/TEST_INVENTORY.md` (multiple FAIL blocks across Q&A, DAG/change propagation, YAML flows, and a few workflow-unit suites).
- Work items:
  - Triage each failure as either “bug” vs “expectation drift”; fix accordingly.
  - Keep the “workflow correctness” lanes green before adding new capability work.

**Acceptance criteria**
- No workflow path produces `empty_workflow_reply` in normal operation.
- `tests/TEST_INVENTORY.md` failure list is actively shrinking (or updated if it’s stale), and the detour + Q&A suites are stable.
- The two open TEAM_GUIDE investigations (date mismatch + billing capture) are either fixed with regressions or explicitly scoped with a minimal repro and owner.

---

### PH0 — Repo Hygiene + Production Defaults (highest leverage)

**PH0.1 — Stop tracking runtime/local artifacts**
- Move runtime DB and tmp artifacts out of git:
  - `backend/events_database.json` (tracked + mutated)
  - `.dev/*.pid`, `tmp-*/*`, `tmp-cache/*`, page snapshots, etc.
- Update `.gitignore` and provide a **sample** DB fixture under `tests/fixtures/` (or `backend/data/`) instead.

**PH0.2 — Default dangerous endpoints OFF**
- `backend/api/routes/clients.py`: change `ENABLE_DANGEROUS_ENDPOINTS` default from `"true"` to `"false"`.
- Add a single, consistent “dev-only guard” helper used by all dev/test endpoints.
- Add a lightweight test asserting these endpoints 403 by default (no env set).

**PH0.3 — Consolidate static “DB” JSONs (rooms/products) into one canonical data directory**

Problem: the repo currently has multiple overlapping JSON sources for “reference data”:
- Rooms: `backend/rooms.json` (operational) and `backend/room_info.json` (descriptive/pricing)
- Products/menus: `backend/data/catalog/catering.json` (logic/pricing) and `backend/catering_menu.json` (details/menus)
- Additional per-room calendar JSON stubs: `backend/adapters/calendar_data/*.json`

This makes behavior harder to reason about and is the opposite of the Supabase target (single schema, single source of truth).

Plan reference (already drafted): `docs/plans/active/DATABASE_CONSOLIDATION_PLAN.md`.

**PH0.3.0 — Inventory all current file-path call sites (must be first)**

Before moving files or changing schemas, inventory every place that reads these JSONs so the refactor is mechanical and testable:

```bash
rg -n "rooms\\.json|room_info\\.json|catering_menu\\.json|data/catalog/catering\\.json|calendar_data" backend scripts tests docs
```

Known current readers (non-exhaustive; re-run the grep above to confirm):
- Rooms JSON:
  - `backend/services/rooms.py` (loads `rooms.json`)
  - `backend/workflows/io/database.py` (loads `rooms.json`)
  - `backend/workflows/nlu/preferences.py` (reads `rooms.json`)
  - `backend/workflows/steps/step3_room_availability/db_pers/room_availability_pipeline.py` (ROOMS_PATH)
  - `backend/workflows/steps/step7_confirmation/db_pers/post_offer.py` (rooms path + calendar_data path)
- Room info JSON:
  - `backend/services/qna_readonly.py`
  - `backend/workflows/common/catalog.py`
  - `backend/workflows/common/capacity.py`
  - `backend/workflows/common/pricing.py`
  - `backend/DEPRECATED/conversation_manager_v0.py` (legacy; still references `../room_info.json`)
- Catering/menu JSON:
  - `backend/workflows/common/catalog.py` (catering_menu)
  - `backend/workflows/planner/smart_shortcuts.py` (catering_menu)
- Calendar busy fixtures:
  - `backend/adapters/calendar_adapter.py` (calendar_data directory)
  - `scripts/tools/generate_future_calendar.py` (calendar_data directory)
  - plus doc/test references (Playwright checks, backend README)

Work items (refactor ladder):
- Introduce a single canonical `backend/data/` source for rooms and products (unified schema + unified IDs).
- Centralize file paths in one place (e.g., `backend/data/paths.py` or `backend/workflows/common/data_paths.py`) so future migrations are single-edit.
- Add a migration script (one-shot) to generate the new canonical files from the old ones.
- Update loaders to read *only* from the unified files and remove ad-hoc ID mapping/duplication.
- Decide what to do with `backend/adapters/calendar_data/*.json`:
  - either treat as generated artifacts (not tracked), or
  - migrate into the unified room schema (as `calendar_id` / operations metadata).
  - update all calendar-data readers to use the same resolved directory (no per-module `parents[...]` path math).
 - Update documentation that references old paths (at minimum `backend/README.md`, `docs/plans/active/DATABASE_CONSOLIDATION_PLAN.md`, and any integration plans that mention `rooms.json` / `catering_menu.json`).

**Acceptance criteria**
- There is exactly one authoritative rooms file and one authoritative products file in `backend/data/`.
- Room/product IDs match what Supabase integration expects (no “split brain” like `room_a` vs `atelier-room-a`).
- All “room/product lookup” code paths load from the same schema (agent-debuggable and testable).

**Acceptance criteria**
- Clean `git status` after normal dev runs (no DB/pid/tmp churn).
- Dev-only endpoints are locked down unless explicitly enabled.

---

### PH1 — Logging + Error Handling Standardization (agent-debuggable)

**PH1.1 — Remove `print(...)` from non-scripts**
Replace prints with `logging` (or trace bus) in runtime modules, especially:
- `backend/api/routes/messages.py`
- `backend/workflow_email.py` (router final line, CLI loop, samples)
- `backend/workflows/change_propagation.py`
- `backend/domain/models.py`

Rules:
- User-facing responses: never include internal tags like `[WF][FALLBACK_DIAGNOSTIC]`.
- Internal logs: include structured context (`event_id`, `thread_id`, `step`, `msg_id`).

**PH1.2 — Fix and adopt `backend/core/errors.py`**
- Finish `safe_operation(...)` so it matches the docstring contract:
  - implement a `SafeOperationFallback(Exception)` carrying `fallback_value`, OR return a typed `Result` object.
  - optionally emit a trace event on failure (hook into `backend/debug/trace.py`).
- Replace top-priority `except Exception: pass` sites with either:
  - `safe_operation(source=..., ...)`, or
  - `logger.exception(...)` + re-raise when it should not be suppressed.

Suggested starting targets (small + high value):
- `backend/debug/lifecycle.py`
- `backend/debug/timeline.py`
- `backend/debug/live_log.py`
- `backend/workflows/change_propagation.py` (suppressed parsing exceptions)

**PH1.3 — Consolidate fallback diagnostics**
- Pick one canonical mechanism:
  - either `backend/core/fallback.py` (preferred, already used by routes),
  - or `backend/workflows/common/fallback_reason.py` (remove duplication).
- Make production-safe defaults:
  - diagnostics OFF unless explicitly enabled (or tied to a `OE_ENV=dev` concept).
- Ensure diagnostics never leak into client-visible messages unless intentionally in a debug UI.

**Acceptance criteria**
- Grep for `print(` in `backend/` only returns scripts/dev utilities.
- Suppressed exceptions still create a triage trail (logs or trace events) with context.
- Fallback diagnostics are off by default in production.

---

### PH2 — LLM Integration Consolidation (reduce drift + improve debuggability)

**PH2.1 — Single “LLM gateway” for the whole backend**
Make one canonical path that all OpenAI/LLM calls go through:
- standardize model selection, deterministic mode, retries/timeouts, response parsing, and redaction/tracing.

Inventory + migration targets (direct OpenAI usage today):
- `backend/ux/universal_verbalizer.py`
- `backend/detection/qna/general_qna.py`
- `backend/workflows/qna/*` (extraction/verbalizer)
- `backend/conversation_manager.py` (if still used)

**PH2.2 — Normalize error mapping**
- Map provider/SDK exceptions to `LLMError` (from `backend/core/errors.py`) with:
  - `source`, `model`, `phase`, `thread_id`, `event_id`, request timing, retry count.
- Ensure errors appear in trace/logs without leaking prompt content.

**PH2.3 — Prompt/template hygiene**
- Separate long prompt templates from orchestration code (move to `backend/**/prompts.py` modules or templates).
- Add “prompt preview” redaction rules once, not per module (reuse `backend/debug/hooks.py`).

**Acceptance criteria**
- `rg "from openai import OpenAI" backend` yields only the gateway (and optional dev-only code).
- A single place controls timeouts/retries/determinism.
- LLM failures produce actionable logs for agents (what failed + where + which model + which phase).

---

### PH3 — Separate Dev Server Concerns from Production App

**PH3.1 — Split `backend/main.py`**
- Create a minimal production app module (e.g., `backend/app.py`) that:
  - constructs the FastAPI app,
  - registers routers,
  - configures middleware/logging,
  - has no subprocess/port-killing/frontend-launch logic.
- Move dev-only behaviors to `scripts/` (or a separate dev entrypoint module).

**PH3.2 — Remove import-time side effects**
- No module should delete caches, write files, or mutate environment variables at import time.
- Gate dev-only conveniences behind `if __name__ == "__main__"` or explicit CLI scripts.

**Acceptance criteria**
- Importing `backend.app` has no side effects.
- Production startup path is predictable and minimal.

---

### PH4 — Remaining Large Files Not Covered by Step Refactor Plan

These are large surfaces where “LLM-ish” code patterns still show up (prints, mixed concerns, global state).

**PH4.1 — `backend/workflows/change_propagation.py`**
- Replace debug prints with structured logging.
- Extract “hallucination guard” into a pure helper with tests.
- Remove nested imports inside hot paths (or isolate them behind a small adapter).

**PH4.2 — `backend/workflows/llm/adapter.py`**
- Split by responsibility:
  - payload normalization
  - adapter calls + retry policy
  - post-processing / canonicalization
  - caching (bounded LRU/TTL; avoid unbounded global dicts)
- Make telemetry collection explicit (no hidden globals like `_LAST_CALL_METADATA` unless strictly bounded).

**PH4.3 — `backend/ux/universal_verbalizer.py`**
- Route LLM calls through the canonical gateway.
- Split prompt building, LLM calling, and fact verification into separate modules.
- Ensure failure paths do not leak internal diagnostics to clients by default.

**PH4.4 — `backend/workflows/steps/step7_confirmation/db_pers/post_offer.py`**
- Split site-visit scheduling/calendar persistence from routing/task logic.
- Decide whether `calendar_data/` JSON persistence is acceptable in production; otherwise replace with the canonical DB/persistence facade.
- Add characterization tests for “post-offer routing” and “site-visit hold” invariants.

**Acceptance criteria**
- Each file has a narrow responsibility and clear public surface.
- Error messages include the minimum context needed for fast agent triage.

---

### PH5 — Type-Checking Baseline + Contracts (Pyright-driven)

Goal: make the codebase “agent-debuggable” by letting Pyright catch contract breaks (wrong optionals, missing keys, wrong shapes) before runtime.

**PH5.1 — Adopt a real Pyright baseline**
- Add `pyrightconfig.json` (or equivalent) with:
  - explicit `include` / `exclude` (exclude `tmp-*`, snapshots, generated artifacts)
  - a staged strictness approach (start permissive, ratchet up)
- Add a CI check (or local “golden” command) that runs Pyright over `backend/` and `tests/`.

**PH5.2 — Fix “unknown attribute” issues via Protocols / base-class contracts**
Pyright currently reports “unknown attribute” access in the agent/adapter layer (indicates missing interface definitions):
- `backend/workflows/llm/adapter.py` calls methods not declared on `AgentAdapter`:
  - `match_catalog_items`
  - `describe`
- Plan:
  - define a `Protocol` (or extend the base adapter type) that includes these optional capabilities
  - use `typing.cast` (or feature flags) when switching between `StubAgentAdapter` and real adapters
  - avoid `hasattr`-only patterns as the sole contract (agents need typed contracts).

**PH5.3 — Remove Optional leaks at boundaries (API + workflow state)**
Examples of Pyright-detected “Optional misuse” that should be addressed:
- `backend/api/routes/messages.py` assigns `str | None` into non-optional Pydantic fields (`EventInformation.status`, `EventInformation.email`).
  - Fix by ensuring merge helpers never return `None` for required fields, or make those fields Optional in the model (choose one).
- `backend/workflows/change_propagation.py` accesses `.value` on a possibly-`None` enum (potential runtime crash).
- `backend/conversation_manager.py` has multiple optional member accesses (`.lower()`, `.strip()`, `json.loads(None)`) indicating weak input normalization.

**PH5.4 — Introduce TypedDicts for high-traffic dict shapes**
Create typed “schemas” for:
- event entries (`event_entry` dict)
- workflow result payload (`process_msg` return shape)
- draft message dicts (`draft_messages[]`)
- `state.extras` keys

This reduces “stringly-typed” drift and makes refactors safer for humans and coding agents.

**Acceptance criteria**
- Pyright can run on the repo and produces a stable, triageable report (no flood of “unknown/Any” from core surfaces).
- Top-level workflow/public surfaces have explicit typed contracts (Protocol/TypedDict), not only implicit dict usage.

---

## Quick “Smell Scan” Commands (for Agents/Devs)

```bash
# Where prints still exist (should converge to scripts-only)
rg -n "print\\(" backend

# Exception swallowing / suppression patterns
rg -n "except Exception\\s*:\\s*(pass)?$" backend

# Direct OpenAI usage (should converge to one gateway)
rg -n "from openai import OpenAI" backend

# Fallback diagnostics leakage points
rg -n "FALLBACK|OE_FALLBACK_DIAGNOSTICS" backend

# Pyright baseline (once pyrightconfig.json exists)
pyright
```
