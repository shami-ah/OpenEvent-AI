# Hardcoded/Mocked Data Audit + DB Connection Plan

Scope: runtime backend + frontend usage (excluding tests/docs unless referenced by runtime routes). This is a snapshot of hardcoded data, mock behaviors, or environment-specific assumptions that should be data-driven. All proposed wiring should first target the current JSON DB (events_database.json) and later swap to Supabase via the integration adapter.

---

## Findings (runtime code)

### A) File-based/fixture data used instead of DB
- JSON DB default persists to a local file:
  - backend/workflow_email.py:219 (DB_PATH = events_database.json)
  - backend/workflows/io/database.py (load_db/save_db)
  - backend/workflows/io/integration/config.py:37 (default mode json)
- Room catalog is file-based:
  - backend/services/rooms.py:60 (backend/data/rooms.json)
  - backend/workflows/common/catalog.py:18 (rooms.json)
  - backend/services/qna_readonly.py:460 (rooms.json)
- Product catalog is file-based:
  - backend/services/products.py:24 (backend/data/products.json)
  - backend/workflows/common/catalog.py:34 (products.json)
- Calendar availability is fixture-based:
  - backend/adapters/calendar_adapter.py:22 (backend/adapters/calendar_data/*.json)

### B) Fully hardcoded catalogs / content
- Hardcoded product catalog (not sourced from DB or JSON):
  - backend/workflows/common/catalog.py:122 (_PRODUCT_CATALOG)
- Hardcoded menu catalog (not sourced from DB or JSON):
  - backend/workflows/common/menu_options.py:38 (DINNER_MENU_OPTIONS)
- Hardcoded Q&A content used by /api/test-data routes:
  - backend/utils/test_data_providers.py:141 (all_items)
  - backend/api/routes/test_data.py (exposes these)

### C) Mocked endpoints / synthetic data
- Deposit endpoint is explicitly mock:
  - backend/api/routes/events.py:53
  - It creates synthetic message body "I have paid the deposit." and sender "Client (GUI)"
- Frontend triggers deposit mock:
  - atelier-ai-frontend/app/page.tsx:871

### D) Environment-specific hardcoding (venue/currency/timezone)
- Timezone and operating hours:
  - backend/services/availability.py:9 (Europe/Zurich, 08:00–23:00)
  - backend/services/hil_email_notification.py:29 (Europe/Zurich)
- Venue name + city in prompts:
  - backend/ux/universal_verbalizer.py:135 (The Atelier, Zurich)
  - backend/agents/openevent_agent.py:24 (The Atelier)
- Currency assumptions (CHF-only):
  - backend/ux/verbalizer_safety.py:51 (CHF regex)
  - backend/llm/verbalizer_agent.py:349 (CHF output rule)
- Fallback emails/URLs:
  - backend/services/hil_email_notification.py:57 (openevent@atelier.ch)
  - backend/services/hil_email_notification.py:108 (http://localhost:3000)
  - atelier-ai-frontend/app/page.tsx:167 (unknown@example.com)

### E) TODOs indicating missing config plumbing
- Manager name list not loaded from config:
  - backend/workflows/runtime/pre_route.py:87
- Site visit configuration not loaded:
  - backend/workflows/common/site_visit_handler.py:501, 542, 559
- Offer similarity threshold hardcoded:
  - backend/workflows/steps/step4_offer/trigger/step4_handler.py:521

---

## DB Connection Plan (JSON now, Supabase later)

### Guiding principle
All runtime configuration should be read from the database abstraction, not hardcoded in modules. Start by storing configuration in the JSON DB under a `config` key (events_database.json), then later implement equivalent columns/tables in Supabase via the integration adapter.

### Phase 0: Define a DB-backed config schema (JSON DB)
Add a canonical config structure in the JSON DB, e.g.:

- db["config"]["venue"]
  - name ("The Atelier")
  - city ("Zurich")
  - timezone ("Europe/Zurich")
  - currency ("CHF")
  - operating_hours (start_hour, end_hour)
- db["config"]["catalogs"]
  - rooms_source ("db" | "json")
  - products_source
  - menus_source
  - qna_source
- db["config"]["site_visit"]
  - blocked_dates
  - default_slots
  - weekday_rules
- db["config"]["branding"]
  - from_email
  - from_name
  - frontend_url

For now, populate defaults in `events_database.json` or in `get_default_db()` so existing behavior remains stable.

### Phase 1: Add a small configuration accessor layer
Create a lightweight accessor module (example `backend/workflows/io/config_store.py`) that:
- Reads config from `workflow_email.load_db()` (JSON)
- Provides `get_venue_settings()`, `get_currency()`, `get_timezone()`, etc.
- Falls back to current hardcoded defaults if values are missing

Later: route these through `backend/workflows/io/integration/adapter.py` to support Supabase.

### Phase 2: Wire modules to config accessors
Replace hardcoded values in runtime modules:
- availability.py: use venue timezone + operating hours from config
- universal_verbalizer.py / openevent_agent.py: use venue name and city
- verbalizer_safety.py / verbalizer_agent.py: use currency code from config (and pattern)
- hil_email_notification.py: use config for from_email/from_name/frontend_url
- pre_route.py: use configured manager names
- site_visit_handler.py: use site visit config
- step4_handler.py: make similarity threshold configurable

### Phase 3: Replace hardcoded catalogs with DB-backed sources
- rooms/products: keep existing JSON loaders as fallback, but allow config to point to DB-backed tables in JSON/Supabase
- menus/Q&A: move DINNER_MENU_OPTIONS and test Q&A content into DB config or dedicated tables
- calendar: replace calendar_data fixtures with a calendar adapter that queries DB or external calendar

### Phase 4: Replace mock endpoints
- /api/event/deposit/pay: swap to real payment webhook or DB state update triggered by payment provider
- frontend mock deposit action: replace with payment status polling or webhook confirmation

### Phase 5: Supabase integration
- Map JSON config into Supabase tables:
  - venue_settings, site_visit_settings, catalogs, qna_items, menus, rooms, products
- Update the adapter (`backend/workflows/io/integration/adapter.py`) to read/write these tables

---

## Recommended execution order
1) Config accessor module + JSON DB defaults
2) Swap time/currency/branding strings first (lowest risk)
3) Wire site visit + manager names config
4) Migrate menus/Q&A/products/rooms catalogs
5) Replace calendar fixtures
6) Replace deposit mock and frontend flow
7) Supabase-specific adapter work

---

## Notes
- This file intentionally focuses on runtime usage. Tests and docs still contain hardcoded data for fixtures; these are acceptable unless they leak into runtime paths.
- Current integration adapter already exists; the plan above should leverage it, not duplicate it.
