# Production Readiness TODOs - 2026-01-07

## Scope
- Backend only (frontend excluded).
- Consolidates remaining TODOs after the 2026-01-03 and 2026-01-05 reports.
- Focused on production hardening, security, stability, and complexity risks.

Please ignore anything requiring supabase or new frontend for now. First focus on the core backend readiness.

---

## Additions Found During Full Sweep (07.01.26)

- High: Site visit and response-type workflow groups are stubbed (no implementation), so those flows are incomplete if triggered (`workflows/groups/site_visit.py`, `workflows/groups/response_type.py`).
- High: Calendar integration is still stubbed (availability uses local fixture JSON; event creation logs to file). Replace with real calendar API integration (`adapters/calendar_adapter.py`, `services/availability.py`, `utils/calendar_events.py`).
- High: Deposit pay endpoint is a mock test hook; should be webhook-only with signature validation or disabled in production (`api/routes/events.py`).
- High: Step 3 availability workflow calls an interactive `input()` review in a web request path, which can block the server (triggered from `api/routes/messages.py` into `workflows/steps/step3_room_availability/db_pers/room_availability_pipeline.py`).
- Medium: Snapshot endpoints are not allowlisted; with `AUTH_ENABLED=1`, public info links may break unless you add signed access or an allowlist (`api/routes/snapshots.py`, `api/middleware/auth.py`).
- Medium: Local snapshot JSON has no file locking; concurrent writes can corrupt snapshot storage (use lock or Supabase) (`utils/page_snapshots.py`).
- Medium: Room/product catalogs are static JSON files; production should move these to DB/config to avoid stale data (`services/rooms.py`, `services/products.py`).
- Medium: Frontend base URL defaults to localhost; must be set in prod or emails/links point to localhost (`utils/pseudolinks.py`, `workflows/io/config_store.py`, `services/hil_email_notification.py`).
- Medium: Supabase client creation on missing IDs is unimplemented; integration may fail to auto-create clients (`workflows/io/integration/uuid_adapter.py`).
- Medium: Client GUI adapter is a stub that only logs payloads; if production expects GUI pushes, implement the actual integration or rely on polling (`adapters/client_gui_adapter.py`).
- Low: Test email endpoints can send arbitrary emails; should be dev-only or tightly restricted even with auth (`api/routes/emails.py`, `api/routes/config.py`).
- Low: Logging includes client emails and message excerpts; consider PII redaction or ensure prod log level excludes these (`api/routes/clients.py`, `api/routes/events.py`, `workflows/steps/step1_intake/trigger/step1_handler.py`).
- Low: Client memory feature is still placeholder-level (rule-based summary, no retention policy); if enabled, add proper summarization + data retention/erase controls (`services/client_memory.py`).
- Low: HIL tasks remain in the JSON DB unless `/api/tasks/cleanup` is called; add retention/auto-clean to avoid unbounded growth (`workflows/runtime/hil_tasks.py`, `api/routes/tasks.py`).

---

## Critical / High Priority TODOs

1) Stop leaking internal exception details to clients.
   - Current pattern returns `detail=f"... {exc}"` in multiple routes.
   - Replace with generic messages; log the exception server-side.
   - Example references: `api/routes/config.py`, `api/routes/events.py`, `api/routes/clients.py`, `api/routes/tasks.py`, `api/routes/emails.py`, `api/agent_router.py`.

2) Make request size limiting effective for unknown or chunked request bodies.
   - Middleware currently only enforces when Content-Length is present.
   - Implement streaming body size enforcement or enforce via gateway.
   - Reference: `api/middleware/request_limits.py`.

3) Add rate limiting or API gateway throttling.
   - No rate limiting present; size limits alone are not enough.
   - Protect public endpoints (messages, events, tasks, config).

4) Replace in-memory session state for production use.
   - `active_conversations` and Step 3 caches are process-local and unbounded.
   - Not safe for multi-worker or restarts; risk of memory growth and lost sessions.
   - References: `legacy/session_store.py`, `api/routes/messages.py`.

5) Replace local JSON DB for production or fully gate it.
   - JSON storage is single-host, single-process friendly only.
   - Multi-worker or multi-instance deployments will diverge.
   - Use Supabase (or real DB) as the authoritative store.

6) Complete Supabase snapshot table migration and enable storage.
   - Snapshot adapter exists but is blocked by missing table/migration.
   - Reference: `workflows/io/integration/supabase_snapshots.py`.

7) Ensure ENV defaults are safe for production.
   - `ENV` default is `dev`; if not explicitly set, dev-only routers and behavior are enabled.
   - Treat `production`/`staging` as prod and fail-safe to prod in server envs.
   - References: `main.py`, `api/routes/workflow.py`, `debug/settings.py`.

---

## Medium Priority TODOs

8) Remove remaining debug `print()` logging and replace with structured logs.
   - Prints are still in workflow paths and adapters; may leak PII or flood logs.
   - References: `adapters/agent_adapter.py`, `workflows/planner/*`, `workflows/steps/step3_room_availability/trigger/step3_handler.py`.

9) Replace silent `except Exception: pass` with warning logs.
   - Silent failures hide operational problems (cleanup, HIL tasks, config fallbacks).
   - References: `main.py`, `api/routes/messages.py`, `workflows/runtime/hil_tasks.py`, `services/hil_email_notification.py`.

10) Tighten CORS for production.
    - Default allows all Lovable domains and any localhost; should be explicit in prod.
    - Reference: `main.py`.

11) Decide whether `/docs`, `/openapi.json` should be public in production.
    - Currently allowlisted when auth is enabled.
    - Reference: `api/middleware/auth.py`.

12) Decide whether `/api/qna` should be public.
    - Currently allowlisted; if `ENV` is accidentally dev, test-data router becomes public.
    - Reference: `api/middleware/auth.py` + `api/routes/test_data.py`.

13) Decide production behavior for LLM fallback to stub heuristics.
    - Gemini/OpenAI adapters fall back to stub on failure.
    - Risk: silent quality regression; consider 503 or hard fail in prod.
    - Reference: `adapters/agent_adapter.py`.

14) Implement Supabase JWT auth if required for launch.
    - `AUTH_MODE=supabase_jwt` is not implemented; will always 401.
    - Reference: `api/middleware/auth.py`.

---

## Low Priority TODOs / Cleanups

15) Gate dev-only endpoints and scripts explicitly in prod.
    - `/api/client/reset` and `/api/client/continue` depend on `ENABLE_DANGEROUS_ENDPOINTS`.
    - Ensure prod env never sets this flag.
    - Reference: `api/routes/clients.py`.

16) Keep debug trace persistence off in production unless explicitly needed.
    - `DEBUG_TRACE_PERSIST_ON_EXIT` should remain disabled in prod.
    - Reference: `main.py`, `debug/settings.py`.

17) Consider removing dev harness logic from prod entrypoint.
    - Auto port killing, auto-frontend launch, browser open, pycache clearing are dev-only concerns.
    - Currently disabled by default in prod, but still in prod path complexity.
    - Reference: `main.py`.

---

## Production Config Checklist (must be set explicitly)

- `ENV=prod` (and treat `production` / `staging` as prod-safe).
- `AUTH_ENABLED=1`, `AUTH_MODE=api_key`, `API_KEY=...` (or implement JWT).
- `TENANT_HEADER_ENABLED=0` (tenant context should come from auth, not headers).
- `ENABLE_DANGEROUS_ENDPOINTS=false`.
- `ALLOWED_ORIGINS=...` set to exact production domains.
- `DEBUG_TRACE_DEFAULT=0`, `DEBUG_TRACE_PERSIST_ON_EXIT=0`.
- `OE_INTEGRATION_MODE=supabase` only after table migrations are applied.
- `FRONTEND_BASE_URL` and venue `frontend_url` set to production domain (used for links in emails and info pages).
- Venue config defaults overridden as needed (`from_email`, `from_name`, `timezone`, `currency_code`).

---

## Complexity / Overengineering Notes

- ( not an issue for now: The prod entrypoint still contains dev automation (auto-kill ports, auto frontend launch, auto browser open, pycache wipes). It is safe when `ENV=prod` is set, but it increases complexity and makes the production startup path harder to reason about. ) 
- Multi-mode toggles (ENV/AUTH/TENANT/INTEGRATION) are powerful but easy to misconfigure; missing any single flag can re-enable dev behaviors.

---

## Summary

The backend is close, but the remaining blockers are mostly production-hardening: error leakage, request/rate limits, safe ENV defaults, in-memory session state, and the Supabase snapshot table migration. Tightening these, plus reducing noisy logging/silent exceptions, will get the service to a safer, production-grade baseline.
