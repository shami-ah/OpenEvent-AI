man# Production Readiness Plan (Backend-First, No Supabase) — 2026-01-07

## Scope / Constraints
- Backend-only hardening and readiness work.
- Explicitly de-prioritize anything that requires Supabase or new frontend work for now.
- Goal: a PR-ladder of small, high-impact changes that reduce production risk quickly.

Source of truth for the raw gap list: `docs/reports/PROD_READINESS_TODO_2026_01_07.md`.

---

## PR Ladder (Most Impactful First)

### PR-01 — Stop leaking internals in API errors (client-safe errors)
**Why:** current API responses include raw exception strings / tracebacks in multiple places; this is a security + ops risk.

**Work items**
- Add a single “safe internal error” helper for routes (generic `detail`, server-side `logger.exception`).
- Remove `detail=f"... {exc}"` / `detail=str(exc)` patterns in routes; replace with generic messages.
- Ensure `api/routes/test_data.py:/api/qna` never returns tracebacks to clients (even in dev; if needed, hide behind `ENV=dev` + explicit flag).

**Primary files**
- `api/routes/config.py`
- `api/routes/events.py`
- `api/routes/clients.py`
- `api/routes/tasks.py`
- `api/routes/emails.py`
- `api/routes/test_data.py`

**Acceptance criteria**
- No API response contains raw exception text or tracebacks by default.
- Errors are logged server-side with stack traces (`logger.exception`) for debugging.

---

### PR-02 — Fix request size limiting for missing/invalid Content-Length
**Why:** current middleware only blocks when `Content-Length` exists; chunked/unknown-length requests bypass the limit.

**Work items**
- Implement a Starlette receive-wrapper that counts bytes as the body streams in and returns `413` when exceeding the configured limit.
- Add focused tests for:
  - Content-Length present and too large
  - Content-Length missing with large body
  - Invalid Content-Length

**Primary files**
- `api/middleware/request_limits.py`
- `backend/tests/...` (where existing middleware tests live)

**Acceptance criteria**
- Requests without Content-Length are still capped.
- Middleware remains transparent to normal-sized requests.

---

### PR-03 — Add rate limiting (minimal viable, backend-only)
**Why:** size limits do not prevent abuse; rate limiting is the next biggest protection layer.

**Work items**
- Add lightweight, in-memory per-IP rate limiting middleware (token bucket or fixed window).
- Apply it to high-risk endpoints:
  - `POST /api/send-message`
  - `POST /api/start-conversation`
  - any email-sending endpoints
- Make it configurable via env vars (`RATE_LIMIT_RPS`, `RATE_LIMIT_BURST`, allowlist for health/docs).
- Document multi-worker limitation (per-process limits) and recommended front-door enforcement (reverse proxy) as follow-up (no implementation).

**Primary files**
- `main.py` (middleware wiring)
- new `api/middleware/rate_limit.py`

**Acceptance criteria**
- Bursty clients get `429` with a consistent error body.
- Defaults are safe but not overly strict for normal use.

---

### PR-04 — Remove request-path blockers: interactive `input()` in Step 3 availability flow
**Why:** `run_availability_workflow` is called from an API request path but enters an interactive console review (`input()`), which can hang the server process.

**Work items**
- Split “interactive console review” into a CLI-only path, never reachable from API.
- Make API-triggered availability workflow non-interactive and always produce a draft + HIL task instead.
- Remove `print()` usage in this path (see PR-07).

**Primary files**
- `workflows/steps/step3_room_availability/db_pers/room_availability_pipeline.py`
- `api/routes/messages.py`

**Acceptance criteria**
- No code reachable from HTTP requests can call `input()`.
- Triggering Step 3 availability from the API completes without blocking.

---

### PR-05 — Production-safe environment gating (make “prod” safe by default)
**Why:** `ENV` defaults to `dev`. If a deploy forgets to set `ENV=prod`, dev-only routers and behaviors can enable unexpectedly.

**Work items**
- Normalize `ENV` values: treat `prod|production|staging` as non-dev.
- Ensure debug/test-data routers are never mounted unless explicitly dev.
- Add a startup log that clearly states effective mode + which risky routers are mounted.
- Option (recommended): if `ENV` is missing, default to prod-safe when process looks like a server deploy (explicit env flag, or an allowlist of known dev run scripts).

**Primary files**
- `main.py`
- `api/routes/workflow.py`
- `debug/settings.py`

**Acceptance criteria**
- “Accidental dev mode in production” becomes hard to do.
- Debug and test-data routes cannot be exposed unless deliberately enabled.

---

### PR-06 — Disable or gate test/mocked production endpoints
**Why:** several endpoints are explicitly “testing only” or “mock” but are still normal API routes.

**Work items**
- Gate “mock deposit paid” behind a dev-only flag or disable entirely in prod:
  - `POST /api/event/deposit/pay`
- Gate test email endpoints behind explicit dev-only flag:
  - `POST /api/emails/test`
  - `POST /api/config/hil-email/test`
- Ensure error bodies are generic (ties back to PR-01).

**Primary files**
- `api/routes/events.py`
- `api/routes/emails.py`
- `api/routes/config.py`

**Acceptance criteria**
- In prod mode, these endpoints return `403` or `404` consistently.

---

### PR-07 — Logging hygiene: remove `print()` + reduce PII in logs
**Why:** `print()` is noisy/unstructured; some logs dump payloads/emails; this increases PII risk and log cost.

**Work items**
- Replace remaining `print()` statements in production paths with `logger.*`.
- Remove/guard logs that dump full payloads (notably GUI adapter logs JSON payloads).
- Add a small redaction helper for emails/tokens (e.g., `a***@domain.com`) and use it in warning/error logs.

**Primary files**
- `adapters/agent_adapter.py`
- `workflows/steps/step3_room_availability/trigger/step3_handler.py`
- `workflows/planner/smart_shortcuts.py`
- `workflows/planner/shortcuts_gate.py`
- `adapters/client_gui_adapter.py`
- `services/hil_email_notification.py`

**Acceptance criteria**
- No `print()` in production code paths.
- No logs dump full client message bodies or large payloads at info/warn levels.

---

### PR-08 — Reduce silent failures (`except Exception: pass`) in production paths
**Why:** silent exception swallowing makes production incidents hard to diagnose and can hide partial failures.

**Work items**
- Replace `except Exception: pass` with either:
  - `logger.warning(..., exc_info=True)` + continue, or
  - `safe_operation(...)` from `core/errors.py` where appropriate.
- Focus on code paths that run in production (not CLI scripts).

**Primary files (examples)**
- `api/routes/messages.py`
- `main.py`
- `workflows/runtime/hil_tasks.py`
- `services/hil_email_notification.py`

**Acceptance criteria**
- Silent exception swallowing is eliminated from production request paths.

---

### PR-09 — Bound in-memory state (session store) for production
**Why:** `active_conversations` and caches are unbounded; memory grows with traffic and restarts lose state.

**Work items**
- Add TTL + max-size eviction for `active_conversations` and Step 3 caches.
- Add periodic cleanup (lazy cleanup on access is fine).
- Add metrics/logging for evictions.

**Primary files**
- `legacy/session_store.py`
- `api/routes/messages.py`

**Acceptance criteria**
- Memory growth from long-running processes is bounded.

---

## Deferred (Explicitly Out of Scope For This Phase)
- Supabase integration completion (tables/migrations, adapters).
- New frontend work (UI changes, signed snapshot links, etc.).
- Real calendar provider integration (Google/Microsoft APIs) beyond removing blockers/stubs.

---

## Recommended Execution Order
1. PR-01 (error leakage) + PR-02 (request sizing) — security baseline
2. PR-04 (remove `input()` blockers) — stability baseline
3. PR-05 + PR-06 — reduce misconfig + test endpoint risk
4. PR-03 (rate limiting) — abuse protection
5. PR-07 + PR-08 + PR-09 — operational hardening

