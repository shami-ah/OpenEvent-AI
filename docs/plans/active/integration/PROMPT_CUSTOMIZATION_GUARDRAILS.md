# Prompt Customization Guardrails (Tone/Format Only)

## Goal
Allow a non-technical manager to adjust AI tone, style, and formatting across workflow steps without changing functional behavior (routing, extraction, gating, or facts).

## Scope (Safe to change)
These are the ONLY recommended surfaces for edits. They influence tone/format and do not alter workflow logic.

- Config endpoints:
  - `GET/POST /api/config/prompts`
  - `GET /api/config/prompts/history`
  - `POST /api/config/prompts/revert/{index}`
- Verbalizer defaults (only if needed for initial seed values):
  - `ux/universal_verbalizer.py` (`_SYSTEM_PROMPT_BODY`, `STEP_PROMPTS`)
- Frontend editor (already wired):
  - `atelier-ai-frontend/app/components/admin/PromptsEditor.tsx`
  - `atelier-ai-frontend/app/admin/prompts/page.tsx`

### What these change
- Global system prompt for the universal verbalizer (tone, banned words, formatting rules).
- Per-step guidance for Steps 2/3/4/5/7 (tone and structure suggestions only).

### What these do NOT change
- Extraction/intent/entity logic (Gemini/OpenAI parsing).
- Business rules (dates, availability, pricing, deposits, site visits).
- Structured Q&A tables or deterministic workflow copy.


## Avoid Changing (High Risk)
Editing these can change behavior, break structured outputs, or violate fact-preservation safeguards.

- Q&A pipeline (structured responses and routing):
  - `workflows/qna/verbalizer.py`
  - `workflows/qna/router.py`
  - `workflows/qna/templates.py`
  - `workflows/common/general_qna.py`
- Safety sandwich (fact verification for offers/rooms):
  - `llm/verbalizer_agent.py`
  - `ux/verbalizer_safety.py`
  - `ux/verbalizer_payloads.py`
- Core message assembly and footers:
  - `workflows/common/prompts.py`
  - `workflows/common/types.py`
- Step handlers and gating prompts (logic + copy interleaved):
  - `workflows/steps/**/trigger/*.py`
  - `workflows/common/billing_gate.py`
  - `workflows/common/site_visit_handler.py`


## Quick Implementation Plan (Low Risk)
1) Expose the existing Prompts Editor in the main frontend.
   - Reuse `PromptsEditor` component or route `/admin/prompts`.
   - Set `NEXT_PUBLIC_BACKEND_BASE` to the Hostinger backend URL.
2) Add auth/role guard to the page + API calls.
   - Enforce admin-only access server-side.
3) Keep defaults intact; store only overrides in the DB.
   - This preserves functional behavior while allowing tone tweaks.
4) If backend runs on Vercel:
   - Persist `config.prompts` to a durable store (Supabase) instead of `/tmp/events_database.json`.


## Editing Rules for Managers (Safe Policy)
- Allowed: tone, phrasing, formatting guidance, banned words list, greeting style.
- Not allowed: any instruction that changes what facts to include, how to calculate, or which dates/rooms/prices to show.
- Never remove these hard rules from the system prompt:
  - Dates/prices/room names/units must be preserved exactly.
  - Do not invent facts.
  - Do not change numeric values or units.


## Risk Checklist (Before Enabling)
- [ ] Confirm edits are only stored via `/api/config/prompts`.
- [ ] Confirm no changes in Q&A or safety-sandwich prompts.
- [ ] Confirm caching TTL (30s) is acceptable or reduced for faster iteration.
- [ ] Confirm prompt history + revert works in staging.
- [ ] Confirm persistence is durable (non-ephemeral storage).


## Validation (Fast Sanity Checks)
- Run one deterministic flow per step (2,3,4,5,7) and confirm:
  - Dates/prices/room names preserved.
  - No routing changes or missing prompts.
  - Tone changes are visible.
- Use `/api/config/prompts/history` to confirm versioning and quick rollback.


## Rollback Plan
- Revert to previous prompt version via:
  - `POST /api/config/prompts/revert/{index}`
- If needed, delete overrides in DB: `config.prompts`.

