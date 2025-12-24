# Pending Refactoring Tasks

## Phase C - Large File Splitting (COMPLETE)

### main.py Route Extraction - COMPLETE

**Status:** ✅ Complete (79% reduction - 1720 lines removed)

| Route Group | Status | Target File | Lines |
|-------------|--------|-------------|-------|
| Tasks (`/api/tasks/*`) | ✅ Done | `routes/tasks.py` | ~230 |
| Events (`/api/events/*`) | ✅ Done | `routes/events.py` | ~180 |
| Config (`/api/config/*`) | ✅ Done | `routes/config.py` | ~175 |
| Clients (`/api/client/*`) | ✅ Done | `routes/clients.py` | ~135 |
| Debug (`/api/debug/*`) | ✅ Done | `routes/debug.py` | ~190 |
| Snapshots (`/api/snapshots/*`) | ✅ Done | `routes/snapshots.py` | ~60 |
| Test Data (`/api/test-data/*`, `/api/qna`) | ✅ Done | `routes/test_data.py` | ~160 |
| Workflow (`/api/workflow/*`) | ✅ Done | `routes/workflow.py` | ~35 |
| Messages (`/api/send-message`, etc.) | ✅ Done | `routes/messages.py` | ~700 |

**Final state:** main.py reduced from 2188 → 468 lines (79% reduction)

**What remains in main.py (~468 lines):**
- FastAPI app creation and lifespan
- CORS middleware configuration
- Router includes (9 routers)
- Port management functions
- Frontend launch functions
- Process cleanup functions
- Root endpoint

### Other Large Files (Deferred)

These files were analyzed but deferred due to high risk of breaking functionality:

| File | Lines | Status | Notes |
|------|-------|--------|-------|
| `step2_handler.py` | 3665 | ⏳ Deferred | Date confirmation - heavy interdependencies |
| `smart_shortcuts.py` | 2196 | ⏳ Deferred | Shortcut detection - shared state |
| `general_qna.py` | ~1350 | ✅ Partial | Constants/utils extracted to `qna/` |

**Rationale:** Heavy interdependencies, shared state, conditional logic - splitting risks breaking functionality. See `docs/internal/OPEN_DECISIONS.md` DECISION-006.

## Future Refactoring Opportunities

### Potential Phase D - Handler Consolidation

If handler files become too large, consider:

1. **step2_handler.py** (3665 lines) - Could split into:
   - `step2_date_parsing.py` - Date extraction logic
   - `step2_proposals.py` - Date proposal generation
   - `step2_versioning.py` - Version history management
   - `step2_handler.py` - Main handler (orchestration only)

2. **smart_shortcuts.py** (2196 lines) - Could split into:
   - `shortcut_patterns.py` - Pattern definitions
   - `shortcut_detection.py` - Detection logic
   - `shortcut_handlers.py` - Action handlers

**Recommendation:** Only pursue if specific issues arise with these files.

## Completed Phases

| Phase | Status | Commits | Result |
|-------|--------|---------|--------|
| A (prep) | ✅ Complete | - | - |
| B (detection) | ✅ Complete | - | - |
| C (large files) | ✅ Complete | `57651b8`, `73cb07f`, `20f7901`, `23e5903` | main.py: 2188 → 468 lines |
| D (error handling) | ✅ Complete | - | - |
| E (folder renaming) | ✅ Complete | `65e7ddc` | - |
| F (file renaming) | ✅ Complete | `366e465` | - |

## Known Issues from Refactoring

### Missing re-exports (Fixed in `361888e`)
- Re-export shims need ALL symbols that are imported from the original files
- Watch for dynamic imports via `getattr()` and `# type: ignore` imports
- Fixed: step2, step3, step4 process.py shims

### Import path updates needed
- Files inside `steps/` should import from canonical `steps/` paths, not deprecated `groups/` paths
- Fixed: step4_handler.py → imports from step5_negotiation (not negotiation_close)

---
Last updated: 2025-12-18
