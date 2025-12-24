# Architecture Findings - December 2025

## CRITICAL: Multiple Code Path Interference

The billing/deposit→HIL flow has **multiple interception points** that can prevent correct behavior:

```
Message arrives at /api/send-message
    │
    ├── 1. conversation_manager.extract_information_incremental (LEGACY)
    │       - Makes EXTRA gpt-4o-mini API call
    │       - Updates ConversationState.event_info (NOT database!)
    │       - Logs "✅ Updating billing_address" but DOESN'T PERSIST
    │       - CREATES CONFUSING LOGS that make it look like billing was captured
    │
    ├── 2. workflow_email.process_msg starts
    │       └── intake.process()
    │       └── if last_result.halt → EARLY RETURN
    │
    ├── 3. guards.evaluate()
    │       - Can force step to 2/3/4 based on offer_status, requirements hash
    │       - Runs BEFORE billing flow correction
    │       - Now has deposit signal bypass (added today)
    │
    ├── 4. smart_shortcuts.maybe_run_smart_shortcuts()
    │       - Can intercept messages at step >= 3
    │       - Now has billing flow bypass (added today)
    │       - Enabled by SMART_SHORTCUTS env var (default: false)
    │
    ├── 5. Billing flow correction (line ~1029-1040)
    │       - Forces step=5 when in billing flow
    │       - Works correctly (we see the log output)
    │
    └── 6. Step routing loop
            - Routes to step 2/3/4/5/6/7 based on current_step
            - Step 5 has billing capture code
            - Step 5 has confirmation gate check

            *** PROBLEM: Step 5 not running despite step=5 ***
```

## Files Analyzed

### 1. `backend/conversation_manager.py` - LEGACY, SHOULD BE REMOVED

**Status**: Marked as DEPRECATED in header but still actively used

**What it does**:
- `extract_information_incremental()` - Makes gpt-4o-mini API call to extract fields
- `active_conversations` - In-memory state for demo
- `render_step3_reply()`, `pop_step3_payload()` - Step 3 helpers

**Problems**:
1. Redundant with `backend/detection/` extraction
2. Updates `ConversationState.event_info` NOT the workflow database
3. Logs extraction results that DON'T persist
4. Creates false confidence that billing was captured

**Imported by**:
- `backend/main.py` - uses `active_conversations`
- `backend/api/routes/messages.py` - uses `extract_information_incremental`

**Recommendation**: Remove `extract_information_incremental` call from messages.py

### 2. `backend/workflows/planner/smart_shortcuts.py` - PLANNER, NOT DETECTION

**Status**: Active, controlled by `SMART_SHORTCUTS` env var (default: false)

**What it does**:
- Multi-step planning when client provides date+room+participants upfront
- Combines steps 2+3+4 into single response
- Handles budget capture, upselling, product selection
- Creates HIL requests

**NOT the same as "Shortcut Detection"**:
- Shortcut detection = recognizing multi-variable confirmations (in `backend/detection/`)
- Smart shortcuts = planning multi-step responses (in `backend/workflows/planner/`)

**Location**: Correct - it's a planner, not a detector

**Today's fix**: Added billing flow bypass in `_shortcuts_allowed()`

### 3. `backend/workflow/guards.py` - STEP ROUTER

**What it does**:
- Evaluates prerequisites for steps 2-4
- Forces step changes based on date_confirmed, locked_room_id, offer_status
- Runs on EVERY message

**Today's fix**: Added deposit signal bypass

## Bug Pattern: Why This Keeps Recurring

Each code path can cause the same symptom (billing not captured), but they're fixed independently:

| Date | Code Path Fixed | Symptom Returns? |
|------|-----------------|------------------|
| Week 1 | Step 4 billing capture | Yes - guards route to wrong step |
| Week 2 | Guards bypass | Yes - smart shortcuts intercept |
| Week 3 | Smart shortcuts bypass | Yes - intake halts early? |
| Week 4 | ??? | ??? |

**The fundamental issue**: Too many interception points, each with its own conditions

## Current State (Dec 23, 2025)

### What's Working:
- Billing fix logs correctly: `[WF][BILLING_FIX] Correcting step from 4 to 5`
- Tests pass (87 regression, 90 detection/flow)

### What's NOT Working:
- Step 5 is not being reached despite step=5 being set
- No `[Step5][DEBUG]` output in logs
- Billing address remains "Not Specified" in database
- HIL task not created

### Debug Output Added:
1. `[Step5][DEBUG]` - Traces billing capture in step5_handler.py
2. `[WF][ROUTE][n]` - Traces routing loop iterations
3. `[WF][PRE_ROUTE]` - Traces state before routing loop

## Legacy Code Analysis (Dec 23, 2025)

### `backend/conversation_manager.py` - LEGACY, SHOULD BE REMOVED

**Status**: Marked as DEPRECATED in header but still actively used

**File Header:**
```python
"""Legacy conversation helpers for the deprecated UI flow."""
# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
```

**What's Still Used:**
| Function | Called From | Purpose | Should Remove? |
|----------|-------------|---------|----------------|
| `active_conversations` | messages.py | In-memory session state | Keep (but could move) |
| `extract_information_incremental` | messages.py:559 | **REDUNDANT** gpt-4o-mini extraction | **YES - Remove** |
| `render_step3_reply` | messages.py | Step 3 payload cache | Keep for now |
| `pop_step3_payload` | messages.py | Step 3 payload cache | Keep for now |

**Problem with `extract_information_incremental`:**
1. Makes a **separate** gpt-4o-mini API call (lines 378-451)
2. Updates `ConversationState.event_info` (in-memory) NOT the workflow database
3. Logs "✅ Updating billing_address" but **DOESN'T PERSIST**
4. Creates false confidence that billing was captured
5. Workflow's own detection in `step1_handler.py` does the SAME extraction

**Functions That Are COMPLETELY DEAD:**
- `generate_response()` (lines 453-693) - Full legacy chatbot, never called
- `classify_email()` (lines 360-376) - Legacy classifier, never called
- `create_summary()` (lines 774-832) - Legacy summary, never called
- `generate_catering_response()` (lines 703-722) - Never called
- `generate_room_response()` (lines 725-772) - Never called

**Recommendation:**
1. Remove `extract_information_incremental` call from `messages.py:559`
2. Delete all dead functions from `conversation_manager.py`
3. Move `active_conversations` to `messages.py` directly

---

## Fallback Message Diagnostics (Fixed Dec 23, 2025)

**Problem:** Three fallback messages in `messages.py` gave no diagnostic info about WHY they were triggered.

**Solution:** Updated all three to use `backend/core/fallback.py` infrastructure:

| Location | Trigger | Diagnostic Info Added |
|----------|---------|----------------------|
| `start_conversation` empty reply | `empty_workflow_reply` | action, draft_count, event_id |
| `send_message` exception | `workflow_exception` | error type/message, message preview |
| `send_message` empty reply | `empty_workflow_reply` | action, draft_count, current_step |

**Example Output (with `OE_FALLBACK_DIAGNOSTICS=true`):**
```
[FALLBACK: api.routes.messages.send_message]
Trigger: empty_workflow_reply
Context: action=None, draft_count=0, current_step=3
---

Thanks for the update. I'll keep you posted as I gather the details.
```

**Control:** Set `OE_FALLBACK_DIAGNOSTICS=false` in production to hide diagnostics.

---

## Pyright Static Analysis (Dec 23, 2025)

Ran `pyright` on all workflow files. Results:

### Fixed Bugs:
1. **`TaskStatus.COMPLETED` → `TaskStatus.DONE`** (workflow_email.py:1205)
   - The `TaskStatus` enum has `DONE`, not `COMPLETED`
   - This was in the debug CLI menu (dead code but still wrong)
   - Commit: `e5567b6`

2. **`_determine_offer_total` broken import** (tasks.py)
   - Imported from deprecated shim that didn't export this function
   - Wrapped in try/except so silently failed, returning None
   - Fixed to import from correct location: `step5_handler.py`
   - Commit: `cc4fc89`

### Dead Code (Not Fixed):
1. **`JSONDatabaseAdapter.create_task`** (adapter.py:208-230)
   - Imports non-existent `create_task` from tasks.py
   - Never called externally (only from `create_message_approval` which is never called on JSON adapter)
   - Would crash if ever used, but harmless since it's dead code

### Type Safety Issues (Not Bugs):
- Many "None is not assignable to str" warnings
- These are strict type checking issues, not runtime bugs
- The code handles None properly at runtime

### Files Moved to DEPRECATED:
- `backend/models.py` (shim with zero imports)
- `backend/llm/intent_classifier.py` (migrated to detection/)
- `backend/workflows/nlu/general_qna_classifier.py` (migrated)
- `backend/workflows/nlu/keyword_buckets.py` (migrated)
- `backend/workflows/nlu/semantic_matchers.py` (migrated)
- `backend/workflows/nlu/sequential_workflow.py` (migrated)

Total: ~130K of dead code consolidated in `backend/DEPRECATED/`

---

## Recommended Actions

1. **Immediate**: ~~Continue debugging why step 5 isn't reached~~ ✅ Fixed (thread_id issue)
2. **Short-term**: ~~Remove `extract_information_incremental` from messages.py~~ ✅ Removed (commit `21f08e1`)
3. **Medium-term**: Consolidate billing capture to ONE location
4. **Long-term**: Refactor to single entry point for all special flows
5. **Cleanup**: Update ~40 files with `from backend.workflows.groups` imports to use `backend.workflows.steps` (Step 2 refactor)
6. **Cleanup**: Delete `backend/DEPRECATED/` folder after step 2 refactor
