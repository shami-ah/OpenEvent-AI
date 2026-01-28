# To-Do Next Session

This file tracks active implementation goals and planned roadmap items. **Check this file at the start of every session.**

## 🎯 Primary Focus for Tomorrow
1.  **Finalize Phase 1 Stability:** Ensure all 7 steps pass happy-path and edge-case regression tests.
2.  ~~**Begin Database Consolidation:**~~ ✅ **DONE** - See `DEV_CHANGELOG.md` for 2025-12-29.
3.  **Initiate Gemini Strategy:** Start implementing the dual-engine LLM provider.

---

## 1. Active Implementation Phase (Current Session / Immediate)
*Must be stabilized before moving to full roadmap implementation.*

| Date Identified | Task | Goal | Priority |
| :--- | :--- | :--- | :--- |
| ~~2026-01-23~~ | ~~**Step 1 Handler Refactoring**~~ | ✅ **DONE 2026-01-24** - Reduced step1_handler.py from 1916 → 799 lines (58% reduction). Extracted 3 modules: classification_extraction.py, change_application.py, requirements_fallback.py. See `docs/plans/active/ARCHITECTURE_IMPLEMENTATION_PLAN_2026_01_23.md` and `DEV_CHANGELOG.md` for details. | ~~**High**~~ |
| 2026-01-21 | **Detour Date Confirmation Regression** | Add/verify Step 2 → Step 3 recheck after date-change confirmation (`tests/specs/dag/test_change_scenarios_e2e.py`) | **High** |
| 2026-01-28 | **Offer Q&A Refinement** | Refine `ACTIONS_THAT_ANSWER_QNA` logic: only skip Q&A about products for the *currently selected room*. Q&A asking about products on a *different room* should still be answered. Currently blanket-skips all Q&A for `offer_generated`. | **Medium** |
| 2025-12-24 | **System Resilience** | Handle diverse client inputs (languages, edge cases) | **Urgent** |
| 2025-12-24 | **Production Stability** | Verified via zero-failure regression runs | **Urgent** |
| 2025-12-24 | **Circular Bug Elimination** | Audit routing loops and special flow guards | **Urgent** |
| 2026-01-13 | **LLM Site Visit Detection** | Replace regex/keyword detection in `router.py` with LLM-based NLU | **Medium** |
| 2025-12-24 | **Integration Completion** | Supabase/Hostinger production readiness | **High** |
| ~~2025-12-24~~ | ~~**Billing Flow Robustness**~~ | ✅ **IMPROVED 2026-01-13** - Fixed 4-part BUG-015 (deposit → Step 7): halt flag, out-of-context bypass, deposit_just_paid check in step7_handler, frontend canAction list. See `DEV_CHANGELOG.md`. | ~~**High**~~ |
| ~~2025-12-28~~ | ~~**Documentation Hygiene**~~ | ✅ **DONE 2025-12-28** - Refreshed `tests/TEST_INVENTORY.md`, closed stale checklist items, and updated this roadmap. | ~~**Medium**~~ |
| ~~2025-12-28~~ | ~~**DCON1 – Detection Import Cleanup**~~ | ✅ **DONE 2025-12-28** - Updated tests to import from stable detection/workflow surfaces; verified pytest collect-only and targeted suites. | ~~**High**~~ |
| ~~2025-12-27~~ | ~~**Product Change Mid-Flow (WF0.1)**~~ | ✅ **FIXED 2025-12-28** - Added empty reply safety net in `workflow_email.py` after routing loop. When routing completes with no drafts, a context-aware fallback message is added. | ~~**Medium**~~ |
| ~~2025-12-27~~ | ~~**Billing Address Capture Failure**~~ | ✅ **FIXED 2025-12-28** - Root cause was step corruption (step=3 instead of step=5) due to missing `offer_accepted=True` in step5_handler + guards forcing step during billing flow. See `test_billing_step_preservation.py`. | ~~**High**~~ |
| ~~2025-12-28~~ | ~~**WF0.1: Empty Detour Replies**~~ | ✅ **FIXED 2025-12-28** - Same as above: empty reply safety net in `workflow_email.py`. See `DEV_CHANGELOG.md`. | ~~**High**~~ |

---

## 2. Planned Roadmap (Pending Implementations)
*Detailed plans located in `docs/plans/`.*

| Date Added | Task / Plan | Reference | Priority |
| :--- | :--- | :--- | :--- |
| ~~2025-12-24~~ | ~~**Database Consolidation**~~ | ✅ **DONE 2025-12-29** - Merged 4 JSON files into 2 unified files (`backend/data/rooms.json`, `backend/data/products.json`). Updated 12 adapters. See `DEV_CHANGELOG.md`. | ~~Medium~~ |
| 2025-12-22 | **Dual-Engine (Gemini)** | `docs/plans/completed/MIGRATION_TO_GEMINI_STRATEGY.md` | Medium |
| 2025-12-20 | **Detection Improvement** | `docs/plans/completed/DONE__DETECTION_IMPROVEMENT_PLAN.md` | Medium |
| 2025-12-18 | **Multi-Variable Q&A** | `docs/plans/active/MULTI_VARIABLE_QNA_PLAN.md` | Medium |
| 2025-12-15 | **Site Visit Sub-flow** | `docs/plans/active/site_visit_implementation_plan.md` | Medium |
| 2025-12-12 | **Junior Dev Links** | `docs/plans/completed/DONE__JUNIOR_DEV_LINKS_IMPLEMENTATION_GUIDE.md` | Low |
| 2025-12-10 | **Multi-Tenant Expansion** | `docs/plans/active/MULTI_TENANT_EXPANSION_PLAN.md` | Low |
| 2025-12-08 | **Test Pages/Links** | `docs/plans/active/test_pages_and_links_integration.md` | Low |
| 2025-12-05 | **Pseudo-links Calendar** | `docs/plans/active/pseudolinks_calendar_integration.md` | Low |
| 2025-12-01 | **Hostinger Logic Update** | `docs/plans/completed/HOSTINGER_UPDATE_PLAN.md` | Medium |
