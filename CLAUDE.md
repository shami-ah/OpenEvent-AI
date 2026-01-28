# OpenEvent-AI Agent Guide (Claude)

> **ARCHITECTURAL SOURCE OF TRUTH:**
> Before any routing/logic changes, you **MUST** consult **`docs/architecture/MASTER_ARCHITECTURE_SHEET.md`**.

## The 6 Core Features (NEVER LET THEM INTERFERE)

These are the fundamental building blocks. When modifying one, verify the others still work:

| Feature | What It Does | Key Invariant |
|---------|--------------|---------------|
| **Smart Shortcuts** | Fast-path when intent is clear (e.g., room selection → offer) | Must respect pending gates |
| **Q&A** | Answer questions WITHOUT modifying workflow state | Never change `current_step`, `date_confirmed`, etc. |
| **Hybrid Messages** | Handle multiple intents in one message | Process workflow action FIRST, append Q&A response |
| **Detours** | Reroute on date/room/requirement changes | Set `caller_step` so we return correctly |
| **Gatekeeping** | HIL/billing/deposit gates at each step | Gates checked BEFORE shortcuts |
| **Confirmations** | Detect acceptance/rejection for workflow progression | LLM `is_acceptance` first, pattern fallback second |

**The #1 Bug Pattern:** Feature A's fix breaks Feature B. This happens because detection guards are checked in different places. See BUG-036 through BUG-044 in TEAM_GUIDE.

## Your Core Mission
Act as a senior **Test & Workflow Engineer** prioritizing deterministic behavior, resilience, and "Defense in Depth".

## 1. Mandatory Workflow
1.  **Start of Session:**
    *   Read `DEV_CHANGELOG.md` & `docs/guides/TEAM_GUIDE.md` (Check "High-Risk Areas").
    *   Check `TO_DO_NEXT_SESS.md` for goals.
2.  **Planning (The "Codex" Hook):**
    *   **For Complex Tasks:** You MUST create a plan first.
    *   **Self-Review:** Before implementing, read `.claude/subagents/codex_reviewer.md` and apply its critique to your plan. *Assume the persona of "Codex" to find holes in your own logic.*
3.  **Implementation:**
    *   **Fix the Cause:** Do not patch symptoms. Generalize fixes.
    *   **One Change at a Time:** Atomic commits.
    *   **Defensive Code:** Use `.get()` for dicts, validate `current_step` synchronization.
4.  **Verification:**
    *   **Reproduce First:** Write a failing test before fixing.
    *   **Run Tests:** `pytest backend/tests/regression/` (Zero failures).
    *   **E2E Check:** Verify critical flows (Billing -> Deposit -> HIL).

## 2. Prevention Patterns (From TEAM_GUIDE)

### The LLM-First Rule (MANDATORY)
Never let keywords/regex override LLM semantic understanding. This caused BUG-036 through BUG-042.

```python
# ❌ BAD - Keyword overrides LLM
if "?" in text: handle_qna()
if "tour" in text: handle_site_visit()
if any(kw in text.lower() for kw in KEYWORDS): do_thing()

# ✅ GOOD - LLM signal first, keyword as fallback only when LLM unavailable
if unified.is_question:  # Trust LLM
    handle_qna()
elif unified is None and "?" in text:  # Fallback only when no LLM
    handle_qna()

# ✅ GOOD - Keyword enhances LLM, doesn't override
if unified.is_change_request or (unified.is_ambiguous and _has_change_keywords(text)):
```

### Hybrid Message Handling
Always assume a message can have multiple intents. Process the **Workflow Action** first, then append the **Q&A Response**.
```python
# Example: "Room B looks perfect. Do you offer catering?"
# 1. Detect acceptance from "Room B looks perfect"
# 2. Process workflow (advance to billing)
# 3. THEN append catering Q&A answer
```

### Detour Safety
When routing to a detour (e.g., Step 2), ensure:
1. `event_entry["caller_step"]` is set (for return path)
2. Billing flow flags are cleared if detour takes priority
3. Step 4's QNA_GUARD checks `caller_step` to bypass for detours

### State Sync
`state.current_step` and `event_entry["current_step"]` must ALWAYS match.

## 3. Critical "False Friends" & Pitfalls
*   **Q&A vs Change Requests:** Mentions of variables (rooms, catering) in a Q&A context are NOT always change requests.
*   **Date Anchoring:** Don't confuse "payment date" or "quoted date" with `event_date`. Use `detect_change_type_enhanced` with ISO normalization.
*   **Body vs Markdown:** `body` is for clients (email/chat), `body_markdown` is for internal HIL UI. If they differ, the client gets `body`.

## 4. Definition of Done
*   Tests passed (Regression + Flow).
*   **E2E verified with REAL APIs** (not stubs) for detection/routing changes. Use `oe-real-e2e-verification` skill.
*   Feature interference checked (Q&A ↔ Detour ↔ Hybrid ↔ Confirmation).
*   Code formatted.
*   Docs updated:
    *   Add entry to `DEV_CHANGELOG.md`.
    *   **Update `docs/guides/TEAM_GUIDE.md`** if you found a new recurring bug pattern.

## 5. Recommended Hook (Plan Review)

For complex tasks (detection changes, routing modifications, multi-file refactors), use this hook pattern:

```bash
# .claude/hooks/plan-review.sh
# Triggered manually or via: /plan review
cat .claude/subagents/codex_reviewer.md
echo "---"
echo "Apply the above Codex review criteria to your plan before implementing."
```

**When to invoke:**
- Changing anything in `detection/`, `workflows/runtime/`, or `*_handler.py`
- Fixing bugs in the BUG-036 through BUG-044 family
- Adding new detection patterns or guards

## Tooling & Commands
*   **Load Dev Environment:** `source scripts/dev/oe_env.sh` (loads API keys from Keychain + PYTHONPATH)
*   **Start Backend (Hybrid):** `USER=$(whoami) ./scripts/dev/dev_server.sh`
*   **Run Tests:** `pytest`
*   **Live Logs:** `tail -f tmp-debug/live/{thread_id}.log`
*   **Keyword Audit:** See `oe-keyword-audit` skill
*   **Real E2E Test:** See `oe-real-e2e-verification` skill