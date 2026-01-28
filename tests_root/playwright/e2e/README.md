# Production Readiness Test Suite

## Test Priority Tiers

Tests are organized in priority order. If a higher-tier test fails, lower-tier tests may be unreliable or moot.

---

### 🔴 TIER 1: CRITICAL (01-03)
**If these fail: System is fundamentally broken**

| Folder | Tests | What Breaks |
|--------|-------|-------------|
| `01_critical_database` | 3 | Events not created, rooms not locked, HIL invisible |
| `02_critical_llm_accuracy` | 3 | Hallucinated rooms/dates/prices, client sees wrong data |
| `03_critical_happy_path` | 1 | Basic flow doesn't complete end-to-end |

**Run first. Stop if any fail.**

---

### 🟠 TIER 2: CORE WORKFLOW (04-06)
**If these fail: Workflow breaks on common scenarios**

| Folder | Tests | What Breaks |
|--------|-------|-------------|
| `04_core_step_gating` | 2 | Steps can be skipped illegally |
| `05_core_detours` | 5 | Date/room changes mid-flow fail |
| `06_core_shortcuts` | 3 | Multi-confirmation messages fail |

**Core workflow integrity tests.**

---

### 🟡 TIER 3: FEATURES (07-10, 16)
**If these fail: Specific features don't work**

| Folder | Tests | What Breaks |
|--------|-------|-------------|
| `07_feature_products` | 2 | Can't add/remove products |
| `08_feature_deposit` | 2 | Deposit calculation wrong |
| `09_feature_persistence` | 3 | Billing/preferences not saved |
| `10_feature_hil` | 3 | Manager requests don't route |
| `16_feature_time_validation` | 1 | Times outside operating hours not warned |

**Feature completeness tests.**

---

### 🟢 TIER 4: INPUT HANDLING (11-13)
**If these fail: Diverse client inputs not handled**

| Folder | Tests | What Breaks |
|--------|-------|-------------|
| `11_input_qna` | 3 | Q&A doesn't work or blocks workflow |
| `12_input_hybrid` | 2 | Combined messages parsed wrong |
| `13_input_nonsense` | 3 | Gibberish crashes system or blocks |

**Input diversity tests.**

---

### 🔵 TIER 5: UX POLISH (14-15)
**If these fail: System works but UX is suboptimal**

| Folder | Tests | What Breaks |
|--------|-------|-------------|
| `14_ux_preferences` | 3 | Room ranking, verbalizer match not shown |
| `15_ux_recovery` | 3 | Transitions feel clunky, not smooth |

**Nice-to-have UX polish.**

---

## Test Execution Order

```bash
# Run in order - stop on first tier failure
1. 01_critical_database  → STOP if fails
2. 02_critical_llm_accuracy → STOP if fails
3. 03_critical_happy_path → STOP if fails
4-6. Core workflow tests
7-10. Feature tests
11-13. Input handling tests
14-15. UX tests
```

## Pass Criteria (All Tests)

Every test verifies:
- ✅ Specific functionality works
- ✅ **NO fallback messages** (no `[FALLBACK:...]`)
- ✅ Flow reaches at least Step 4 (offer)
- ✅ Full E2E tests reach site visit

## Test Format

Each `.md` file contains:
- Test ID and category
- Flow path (e.g., `1 -> 2 -> 3 -> 4`)
- Step-by-step instructions with `ACTION:` and `VERIFY:`
- Pass criteria checklist

## Running Tests

Tests are designed for Claude MCP Playwright execution:
1. Open each test file
2. Follow instructions step-by-step in browser
3. Mark pass criteria checkboxes
4. Record any failures

---

## Quick Reference

| Tier | Prefix | Focus | Count |
|------|--------|-------|-------|
| Critical | 01-03 | Foundation | 7 |
| Core | 04-06 | Workflow | 10 |
| Features | 07-10, 16 | Completeness | 11 |
| Input | 11-13 | Diversity | 8 |
| UX | 14-15 | Polish | 6 |
| **Total** | | | **42** |
