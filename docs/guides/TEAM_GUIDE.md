# OpenEvent Workflow Team Guide

## Overview
- **Actors & responsibilities**
  - *Trigger nodes* (purple) parse incoming client messages and orchestrate state transitions for each workflow group.【F:backend/workflows/steps/step1_intake/trigger/process.py†L30-L207】【F:backend/workflow_email.py†L86-L145】
  - *LLM nodes* (green/orange) classify intent, extract structured details, and draft contextual replies while keeping deterministic inputs such as product lists and pricing stable.【F:backend/workflows/steps/step1_intake/llm/analysis.py†L10-L20】【F:backend/workflows/steps/step4_offer/trigger/process.py†L39-L93】
  - *OpenEvent Actions / HIL gates* (light-blue) capture manager approvals, enqueue manual reviews, and persist audited decisions before messages can be released to clients.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L246-L316】【F:backend/workflows/steps/step4_offer/trigger/process.py†L46-L78】【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L293-L360】
- **Lifecycle statuses** progress from **Lead → Option → Confirmed**, with cancellations tracked explicitly; these values are stored in both `event.status` metadata and the legacy `event_data` mirror.【F:backend/domain/models.py†L24-L60】【F:backend/workflows/io/database.py†L242-L259】【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L260-L318】
- **Context snapshots** are bounded to the current user: the last five history entries plus the newest event, redacted to previews, and hashed via `context_hash` for cache safety.【F:backend/workflows/io/database.py†L190-L206】【F:backend/workflows/common/types.py†L47-L80】

## How control flows (Steps 1–7)
Each step applies an entry guard, deterministic actions, and explicit exits/detours.

### Step 1 — Intake & Data Capture
- **Entry guard:** Incoming mail is classified; anything below 0.85 confidence or non-event intent is routed to manual review with a draft holding response.【F:backend/workflows/steps/step1_intake/trigger/process.py†L33-L100】
- **Primary actions:** Upsert client by email, append history, capture bounded context, create or refresh the event record, merge profile updates, and compute `requirements_hash` for caching.【F:backend/workflows/steps/step1_intake/trigger/process.py†L41-L205】
- **Detours & exits:** Missing or updated dates/requirements trigger `caller_step` bookkeeping and reroute to Step 2 or 3 while logging audit entries.【F:backend/workflows/steps/step1_intake/trigger/process.py†L122-L184】
- **Persistence:** Event metadata stores requirements, hashes, chosen date, and resets room evaluation locks as needed.【F:backend/workflows/steps/step1_intake/trigger/process.py†L111-L168】

### Step 2 — Date Confirmation
- **Entry guard:** Requires an event record; otherwise halts with `date_invalid`. If no confirmed date, proposes deterministic slots via `suggest_dates`.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L21-L90】
- **Actions:** Resolve the confirmed date from user info (ISO or DD.MM.YYYY), tag the source message, update `chosen_date/date_confirmed`, and link the event back to the client profile.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L92-L158】
- **Reminder:** Clients often reply with just a timestamp (e.g. `2027-01-28 18:00–22:00`) when a thread is already escalated. `_message_signals_confirmation` explicitly treats these bare date/time strings as confirmations; keep this heuristic in place whenever adjusting Step 2 detection so we don’t re-open manual-review loops for simple confirmations.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1417-L1449】
- **Guardrail:** `_resolve_confirmation_window` normalizes parsed times, drops invalid `end <= start`, backfills a missing end-time by scanning the message, and now maps relative replies such as “Thursday works”, “Friday next week”, or “Friday in the first October week” onto the proposed candidate list before validation. Preserve this cleanup so confirmations don’t regress into “end time before start time” loops or re-trigger HIL drafts.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1527-L1676】
- **Parser upgrade:** `parse_first_date` falls back to `resolve_relative_date`, so relative phrasing (next week, next month, ordinal weeks) is converted to ISO dates before downstream checks. Pass `allow_relative=False` only when you deliberately need raw numeric parsing, as `_determine_date` does prior to candidate matching.【F:backend/workflows/common/datetime_parse.py†L102-L143】【F:backend/workflows/common/relative_dates.py†L18-L126】
- **Exits:** Returns to caller if invoked from a detour, otherwise advances to Step 3 with in-progress thread state and an approval-ready confirmation draft.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L125-L159】

#### Regression trap: quoted confirmations triggering General Q&A
- **Root cause:** Email clients quote the entire intake brief beneath short replies such as `2026-11-20 15:00–22:00`. `detect_general_room_query` sees that quoted text, flags `is_general=True`, we dive into `_present_general_room_qna`, emit the “It appears there is no specific information available” fallback, and Step 3 never autoloads even though the client just confirmed the slot.
- **Guardrail:** After parsing `state.user_info`, Step 2 now forces `classification["is_general"]=False` whenever we already extracted `date/event_date` or `_message_signals_confirmation` matched the reply, so `_resolve_confirmation_window` executes immediately regardless of the quoted text.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L721-L741】
- **Backfill:** When the extractor misses the ISO string entirely, Step 1 now re-parses `YYYY-MM-DD HH:MM–HH:MM` replies before classification and populates `date/event_date/start_time/end_time` so Step 2 can auto-confirm and trigger Step 3 instead of falling into the “Next step” stub.【F:backend/workflows/steps/step1_intake/trigger/process.py†L208-L321】
- **Rule:** Do **not** resurrect that fallback to mask missing structured payloads—if Step 3 fails, surface a clear error instead of looping managers on the “Next step” stub.

### Step 3 — Room Availability (no HIL)
- **Entry guard:** Requires a chosen date; otherwise detours to Step 2 and records caller provenance.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L51-L121】
- **Actions:** Re-evaluate inventory when requirements change, select the best room, draft outcome messaging, compute alternatives. No manager review is enqueued at this step; drafts are always `requires_approval=False` and stale step-3 HIL requests are cleared on entry.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L120-L205】【F:backend/workflow_email.py†L280-L360】
- **Caching:** If the locked room and requirement hash already match, Step 3 short-circuits and returns control to the caller without recomputing availability.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L60-L205】
- **Regression Guard:** If you ever see a Step-3 task in the manager panel, it’s a bug. Clear `pending_hil_requests` for step=3 and ensure the room draft leaves `requires_approval` false.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L120-L205】

### Step 4 — Offer Preparation
- **Entry guard:** Requires an event entry populated by prior steps; otherwise halts with `offer_missing_event`.【F:backend/workflows/steps/step4_offer/trigger/process.py†L21-L33】
- **Actions:** Normalize product operations, rebuild pricing inputs, call `ComposeOffer` to generate totals, version offers, and queue a draft email for approval.【F:backend/workflows/steps/step4_offer/trigger/process.py†L39-L93】【F:backend/workflows/steps/step4_offer/trigger/process.py†L154-L233】
- **State updates:** Resets negotiation counters when returning from Step 5, sets `transition_ready=False`, and moves to Step 5 while clearing `caller_step`.【F:backend/workflows/steps/step4_offer/trigger/process.py†L59-L92】
- **Heuristic guard:** Short replies like “OK add Wireless Microphone” no longer drop into manual review; Step 1 now auto-detects catalog items, injects `products_add`, and re-flags the intent as an event request so the offer loop keeps iterating instead of stalling at HIL.【F:backend/workflows/steps/step1_intake/trigger/process.py†L201-L357】

### Step 5 — Negotiation Close
- **Entry guard:** Requires an event; otherwise halts with `negotiation_missing_event`.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L27-L38】
- **Actions:** Classify reply intent (accept, decline, counter, clarification), detect structural changes (date, room, participants, products), and manage counter limits with manual-review escalations.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L47-L200】
- **Detours:** Structural changes push to Steps 2–4 with `caller_step=5` recorded; counters beyond three enqueue a manual review task and hold at Step 5.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L51-L175】
- **Exits:** Acceptances advance to Step 6; declines advance to Step 7 with draft messaging awaiting approval.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L75-L117】

### Step 6 — Transition Checkpoint
- **Entry guard:** Requires an event; otherwise halts with `transition_missing_event`.【F:backend/workflows/steps/step6_transition/trigger/process.py†L16-L26】
- **Actions:** Collect blockers (confirmed date, locked room, requirements hash alignment, accepted offer, deposit state) and draft clarifications if anything is outstanding.【F:backend/workflows/steps/step6_transition/trigger/process.py†L28-L88】
- **Exit:** When blockers are clear, marks `transition_ready=True`, advances to Step 7, and records the audit trail.【F:backend/workflows/steps/step6_transition/trigger/process.py†L54-L70】

### Step 7 — Event Confirmation & Post-Offer Handling
- **Entry guard:** Requires the current event; otherwise halts with `confirmation_missing_event`.【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L29-L39】
- **Actions:** Classify confirmation intent (confirm, reserve, deposit paid, site visit, decline, question) and manage deposit/site-visit subflows while tracking `confirmation_state` and optional calendar blocks.【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L71-L358】
- **HIL gate:** `hil_approve_step==7` routes through `_process_hil_confirmation`, ensuring final drafts, declines, deposits, and site-visit notices are human-approved before sending and updating status to Confirmed.【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L47-L360】

## Detour, caller_step & hash rules
- `caller_step` captures the prior workflow position before detouring (e.g., Step 1 pushing to Step 2/3, Step 5 returning to Step 4) and is cleared once the caller regains control.【F:backend/workflows/steps/step1_intake/trigger/process.py†L122-L205】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L51-L176】
- `requirements_hash` snapshots requirement changes; Step 3 updates `room_eval_hash` only after HIL approval to prove the lock matches the latest requirements.【F:backend/workflows/steps/step1_intake/trigger/process.py†L111-L175】【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L287-L315】
- `room_pending_decision` stores the proposed room, status, summary, and hash so HIL can approve deterministically.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L95-L115】
- `offer_sequence` and `offer_status` track versioned drafts to prevent duplicate sends; each new offer supersedes prior drafts before Step 5 negotiation resumes.【F:backend/workflows/steps/step4_offer/trigger/process.py†L201-L233】
- `context_hash` stabilizes bounded client context for caching and audit; every snapshot is hashed before storage or reuse.【F:backend/workflows/io/database.py†L190-L206】

## Privacy & Data Access Model
- Clients are keyed by lowercased email; all lookups and event associations respect this scoped identifier.【F:backend/workflows/io/database.py†L131-L173】【F:backend/workflows/steps/step1_intake/trigger/process.py†L41-L205】
- Context sent to downstream logic only includes the client's profile, last five history previews, the most recent event, and the derived `context_hash`; no cross-client data is exposed.【F:backend/workflows/io/database.py†L190-L206】
- Message history stores intent labels, confidence, and trimmed body previews (160 chars) to avoid leaking full correspondence while preserving auditability.【F:backend/workflows/io/database.py†L149-L164】
- Site visits and deposits honor venue policy and locked-room constraints before offering sensitive scheduling details.【F:backend/workflows/common/room_rules.py†L142-L200】【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L200-L358】
- Draft messages default to `requires_approval=True` ensuring HIL review before any client-facing output is sent.【F:backend/workflows/common/types.py†L75-L80】

## Where to debug each step
| Step | File(s) | Key entry point |
| --- | --- | --- |
| 1 – Intake | `backend/workflows/steps/step1_intake/trigger/process.py` | `process`【F:backend/workflows/steps/step1_intake/trigger/process.py†L30-L207】 |
| 2 – Date Confirmation | `backend/workflows/steps/step2_date_confirmation/trigger/process.py` | `process`【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L17-L159】 |
| 3 – Room Availability | `backend/workflows/steps/step3_room_availability/trigger/process.py` | `process` & `_apply_hil_decision`【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L28-L316】 |
| 4 – Offer | `backend/workflows/steps/step4_offer/trigger/process.py` | `process`【F:backend/workflows/steps/step4_offer/trigger/process.py†L17-L93】 |
| 5 – Negotiation | `backend/workflows/steps/step5_negotiation/trigger/process.py` | `process`【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L23-L200】 |
| 6 – Transition | `backend/workflows/steps/step6_transition/trigger/process.py` | `process`【F:backend/workflows/steps/step6_transition/trigger/process.py†L12-L70】 |
| 7 – Confirmation | `backend/workflows/steps/step7_confirmation/trigger/process.py` | `process` & `_process_hil_confirmation`【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L25-L360】 |
| Router | `backend/workflow_email.py` | `process_msg` loop【F:backend/workflow_email.py†L86-L145】 |

## HIL Toggle System (AI Reply Approval)

**Last Updated:** 2025-12-10

The system supports two tiers of Human-in-the-Loop (HIL) approval for client-facing messages:

### Two-Tier HIL Architecture

| Tier | Task Type | When Created | Purpose |
|------|-----------|--------------|---------|
| **1. Step-Specific HIL** | `date_confirmation_message`, `room_availability_message`, `offer_message`, `special_request`, `too_many_attempts` | **ALWAYS** (via `_enqueue_hil_tasks`) | Original workflow gates: offer confirmation, special manager requests, >3 failed attempts |
| **2. AI Reply Approval** | `ai_reply_approval` | **ONLY when `OE_HIL_ALL_LLM_REPLIES=true`** | NEW optional gate: approve ALL AI-generated messages before sending |

### Environment Variable

```bash
# Enable AI reply approval for all messages (Tier 2)
export OE_HIL_ALL_LLM_REPLIES=true

# Disable (default) - only step-specific HIL gates active (Tier 1)
unset OE_HIL_ALL_LLM_REPLIES
```

### Important Distinction

**Toggle OFF** (`OE_HIL_ALL_LLM_REPLIES` unset/false):
- AI messages go directly to clients (no extra approval step)
- Step-specific HIL tasks STILL work (offer confirmation, special requests, too many attempts)
- This is the **original behavior** - nothing new

**Toggle ON** (`OE_HIL_ALL_LLM_REPLIES=true`):
- EVERY AI-generated message goes to manager approval queue first
- Step-specific HIL tasks ALSO work (both tiers active)
- Adds an EXTRA approval layer on top of existing workflow

### Frontend UI

| Section | Color | Visibility |
|---------|-------|------------|
| Manager AI Reply Approval | Green | Only when `OE_HIL_ALL_LLM_REPLIES=true` |
| Client HIL Tasks (step-specific) | Purple | Always (when tasks exist) |

### Key Code Paths

| Logic | Location |
|-------|----------|
| Step-specific task creation | `backend/workflow_email.py:_enqueue_hil_tasks()` — ALWAYS runs |
| AI reply approval task creation | `backend/workflow_email.py:1130-1188` — only when toggle ON |
| Task deduplication | Checks for existing PENDING `ai_reply_approval` task for same thread |

### Common Gotcha

Never skip `_enqueue_hil_tasks()` when the AI reply toggle is ON. Both task creation paths must run independently:
1. `_enqueue_hil_tasks()` for step-specific HIL tasks (always)
2. `ai_reply_approval` task creation for the toggle (when enabled)

---

## Fallback Diagnostic System

**Last Updated:** 2025-12-17

When the system cannot use the LLM (API key missing, exception, empty results), it falls back to deterministic responses. These fallback messages now include diagnostic information to help understand WHY the fallback was triggered.

### Environment Variable

```bash
# Show fallback diagnostics (default: true for dev/staging)
export OE_FALLBACK_DIAGNOSTICS=true

# Hide diagnostics in production
export OE_FALLBACK_DIAGNOSTICS=false
```

### Fallback Sources

| Source | File | Trigger Scenarios |
|--------|------|-------------------|
| `qna_verbalizer` | `backend/workflows/qna/verbalizer.py` | LLM disabled, LLM exception, empty DB results |
| `qna_extraction` | `backend/workflows/qna/extraction.py` | LLM disabled, LLM exception, JSON decode error |
| `structured_qna_body` | `backend/workflows/common/general_qna.py` | No rooms/dates/products from DB query |
| `intent_adapter` | `backend/workflows/llm/adapter.py` | Provider unavailable, stub failed |

### Diagnostic Output Format

When `OE_FALLBACK_DIAGNOSTICS=true`, fallback messages include:

```
---
[FALLBACK MESSAGE]
Source: qna_verbalizer
Trigger: llm_disabled
Failed checks: no_data_from_db_query
Context: rooms_count=0, dates_count=0, products_count=0, intent=select_static
Error: <original exception message if applicable>
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/workflows/common/fallback_reason.py` | Centralized `FallbackReason` dataclass and helpers |
| `backend/workflows/qna/verbalizer.py` | Q&A verbalization fallback |
| `backend/workflows/qna/extraction.py` | Q&A extraction fallback |
| `backend/workflows/common/general_qna.py` | Structured Q&A body fallback |
| `backend/workflows/llm/adapter.py` | Intent classification fallback |

### Common Triggers

| Trigger | Meaning |
|---------|---------|
| `llm_disabled` | OpenAI API key not available or OpenAI library not installed |
| `llm_exception` | LLM call threw an exception (network, rate limit, etc.) |
| `empty_results` | Q&A query returned no rooms/dates/products |
| `json_decode_error` | LLM returned invalid JSON |
| `provider_unavailable` | LLM provider not initialized |

### Debugging Fallback Messages

When you see a fallback message:

1. **Check the source** — Which module triggered it?
2. **Check the trigger** — Why did it fall back?
3. **Check the context** — What data was (or wasn't) available?
4. **Check the error** — If an exception, what was the message?

This information helps distinguish between:
- Configuration issues (LLM disabled)
- Runtime issues (LLM exceptions)
- Data issues (empty results from DB)

---

## Agent Tools Layer (AGENT_MODE=openai)

When `AGENT_MODE=openai` is set, the system uses OpenAI function-calling for tool execution instead of the deterministic workflow. Tools are bounded per step to enforce the same workflow constraints as the deterministic path.

### Tool Allowlist by Step

| Step | Allowed Tools |
| --- | --- |
| 2 – Date | `tool_suggest_dates`, `tool_parse_date_intent` |
| 3 – Room | `tool_room_status_on_date`, `tool_capacity_check`, `tool_evaluate_rooms` |
| 4 – Offer | `tool_build_offer_draft`, `tool_persist_offer`, `tool_list_products`, `tool_list_catering`, `tool_add_product_to_offer`, `tool_remove_product_from_offer`, `tool_send_offer` |
| 5 – Negotiation | `tool_negotiate_offer`, `tool_transition_sync` |
| 7 – Confirmation | `tool_follow_up_suggest`, `tool_classify_confirmation` |

### Key Files

| File | Description |
| --- | --- |
| `backend/agents/chatkit_runner.py` | `ENGINE_TOOL_ALLOWLIST`, `TOOL_DEFINITIONS`, `execute_tool_call`, schema validation |
| `backend/agents/tools/dates.py` | Date suggestion and parsing tools |
| `backend/agents/tools/rooms.py` | Room status and capacity tools |
| `backend/agents/tools/offer.py` | Offer composition, products, and catering tools |
| `backend/agents/tools/negotiation.py` | Negotiation handling |
| `backend/agents/tools/transition.py` | Transition sync |
| `backend/agents/tools/confirmation.py` | Confirmation classification |

### Testing

```bash
# Run all agent tools tests (parity + approve path)
pytest backend/tests/agents/ -m "" -v

# Run parity tests only
pytest backend/tests/agents/test_agent_tools_parity.py -m "" -v

# Run approve path tests only
pytest backend/tests/agents/test_manager_approve_path.py -m "" -v
```

## Common user messages → expected reactions
| User message | System reaction | Notes |
| --- | --- | --- |
| “Hi, just saying hello” | Manual review task + holding draft | Low-confidence intent routes to HIL queue.【F:backend/workflows/steps/step1_intake/trigger/process.py†L53-L100】 |
| “What dates are available?” | Draft listing five deterministic slots, waits at Step 2 | Candidate dates pulled via `suggest_dates`.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L44-L90】 |
| “Let’s switch to Room B” (during negotiation) | Detour to Step 3 with `caller_step=5` | Structural change resets negotiation counter.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L51-L176】 |
| “Can you lower the price?” (4th time) | Manual review escalation, draft escalation note | Counter threshold triggers task creation.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L118-L159】 |
| "Please confirm the booking" | Confirmation draft queued; awaits HIL sign-off | Deposit/site-visit logic handled before final send.【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L75-L318】 |
| "Deposit has been paid" | Deposit marked paid, confirmation draft regenerated | Ensures status before final confirmation.【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L175-L238】
| "pls add another wireless microphone" | Extracts products_add, increments quantity, regenerates offer | LLM extraction now includes products_add/products_remove fields.【F:backend/adapters/agent_adapter.py†L239-L244】【F:backend/workflows/steps/step4_offer/trigger/process.py†L626-L634】 |

## Known Issues & Fixes

### Product Addition Not Updating Total (Fixed)
**Root Causes:**
1. **Missing LLM extraction fields:** The OpenAI adapter's extraction prompt didn't include `products_add` or `products_remove` fields, causing the LLM to return `null` for these fields even when users requested product additions.【F:backend/adapters/agent_adapter.py†L239-L244】
2. **No quantity semantics:** The system didn't understand that "another" means "+1 to existing quantity".
3. **Wrong merge logic:** `_upsert_product` was replacing quantity instead of incrementing it. When a user said "add another wireless microphone", the system would set quantity to 1 instead of adding 1 to the existing quantity.【F:backend/workflows/steps/step4_offer/trigger/process.py†L626-L634】

**Fixes Applied:**
1. Updated `_ENTITY_PROMPT` to include: `products_add (array of {name, quantity} for items to add), products_remove (array of product names to remove). Use null when unknown. For 'add another X' or 'one more X', include {"name": "X", "quantity": 1} in products_add.`【F:backend/adapters/agent_adapter.py†L239-L244】
2. Added `products_add` and `products_remove` to `_ENTITY_KEYS` list so the extraction results are properly captured.【F:backend/adapters/agent_adapter.py†L247-L265】
3. Fixed `_upsert_product` to increment quantity: `existing["quantity"] = existing["quantity"] + item["quantity"]` instead of `existing["quantity"] = item["quantity"]`.【F:backend/workflows/steps/step4_offer/trigger/process.py†L626-L634】

**Testing Approach:**
- Create a test event with 1 wireless microphone (quantity: 1, unit_price: 25.0)
- Simulate user message: "pls add another wireless microphone"
- Verify extraction returns: `products_add: [{"name": "Wireless Microphone", "quantity": 1}]`
- Verify `_upsert_product` increments quantity from 1 to 2
- Verify total updates from CHF 1,965.00 to CHF 1,990.00

### Product Additions Causing Duplicates (Fixed)
**Root Cause:**
When a user requests a product addition (e.g., "add a wireless microphone"), two logic paths were triggered simultaneously:
1. The `_detect_product_update_request` heuristic in Step 1 correctly identified the request and added the product to the `user_info.products_add` list.
2. The `_autofill_products_from_preferences` function in Step 4 also ran, saw that "wireless microphone" was a suggested item in the original preferences, and added it *again*. This resulted in the quantity increasing by two instead of one.

**Fix:**
The `_autofill_products_from_preferences` function in `backend/workflows/steps/step4_offer/trigger/process.py` was updated to prevent it from running if products have already been manually modified in the same turn. It now checks `_has_offer_update(user_info)` before proceeding, ensuring that explicit user requests always take precedence over automated suggestions.【F:backend/workflows/steps/step4_offer/trigger/process.py†L405-L410】

### Offer Acceptance Stuck / Not Reaching HIL (Fixed)
**Symptoms:** Client replies “ok that’s fine / approved / continue / please send” but the workflow stays at Step 4 (Awaiting Client) or routes to manual review; manager/HIL never sees the offer to approve; Approve button in GUI does nothing.

**Root Causes:**
1. Acceptance phrases were classified as `other`, so Step 5 (negotiation) never ran and no HIL task was created.
2. Even when acceptance was detected later, HIL didn’t have a compact offer summary to review and approve.
3. GUI Approve relied on `hil_approve_step=5` but the state sometimes remained at Step 4.

**Fixes Applied:**
1. Intake now force-upgrades short acceptance replies to `event_request`, stamps `intent_detail=event_intake_negotiation_accept`, sets `hil_approve_step=5`, and pins the event on Step 5 with `Waiting on HIL` so negotiation close can run immediately.【F:backend/workflows/steps/step1_intake/trigger/process.py†L538-L559】
2. Negotiation accept flow now sends a HIL-ready summary (line items + total) and keeps the thread in `Waiting on HIL` until the manager approves; HIL approval sets the offer to Accepted and advances to Step 6 automatically; rejection prompts to adjust and resend.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L23-L47】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L98-L170】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L341-L394】
3. Acceptance keywords expanded to include “continue / please send / go ahead / ok that’s fine / approved” and we normalize curly apostrophes so short “that’s fine” replies are caught.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L23-L47】【F:backend/workflows/steps/step1_intake/trigger/process.py†L149-L167】【F:backend/workflows/steps/step1_intake/trigger/process.py†L518-L559】
4. HIL Approve now applies the decision to the pending negotiation and runs the transition checkpoint so the workflow moves past Step 5 as soon as the manager clicks Approve (no more stuck buttons).【F:backend/workflow_email.py†L306-L359】
5. Step 4 now also recognizes acceptance phrases (with normalized quotes) and short-circuits straight to HIL with a pending decision, avoiding repeated offer drafts when clients reply “approved/continue/that’s fine” on the offer thread.【F:backend/workflows/steps/step4_offer/trigger/process.py†L52-L123】【F:backend/workflows/steps/step4_offer/trigger/process.py†L1115-L1131】

### Duplicate HIL sends after offer acceptance (Fixed)
**Symptoms:** Client says “that’s fine” → placeholder “sent to manager” is shown, but the full offer is re-posted to the client and multiple HIL tasks are created.

**Fixes Applied:**
1. Step 5 now detects if a negotiation decision is already pending or a step-5 HIL task exists and returns a `negotiation_hil_waiting` action without re-enqueuing tasks or re-sending the offer draft.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L37-L61】
2. Client-facing replies for `negotiation_hil_waiting` are collapsed to a single “sent to manager” notice (no offer body) so the chat isn’t spammed while HIL is open.【F:backend/main.py†L80-L86】

**Regression Guard:** If a client restates acceptance while HIL is open, you should see one HIL task and a single waiting message; no new drafts should reach the chat.

### Spurious unavailable-date apologies on month-only requests (Fixed)
**Symptoms:** A month-only ask (“February 2026, Saturday evening”) produced “Sorry, we don't have free rooms on 20.02.2026” even though the client never mentioned that date, and the suggested list collapsed to a single date.

**Fixes Applied:**
1. `_client_requested_dates` now ignores month-only hints unless an explicit day appears in the message (dd.mm.yyyy, yyyy-mm-dd, or “12 Feb 2026”), preventing phantom “unavailable” notices.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L270-L296】
2. Window hints now sanitize `weekdays_hint` to 1–7, so mis-parsed numbers (e.g., participant counts) can’t force a single “Week 1” view and truncate the date list.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L2462-L2474】
3. When a client asks for menus alongside dates, the date proposal now includes a menu block filtered to the requested month so the hybrid question is answered in one message.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1302-L1319】【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L2123-L2143】

**Regression Guard:** Month-only requests should return up to five valid options in that month (e.g., February Saturdays) with no apology about dates the client never mentioned.

### Offer re-sent while waiting on HIL (Fixed)
**Symptoms:** After a client accepts, the “sent to manager” note is shown but the offer body is posted again and multiple HIL tasks appear.

**Fixes Applied:**
1. Step 4 now short-circuits when a Step 5 HIL decision is already pending, returning `offer_waiting_hil` so no new drafts/tasks are emitted.【F:backend/workflows/steps/step4_offer/trigger/process.py†L33-L49】
2. Client-facing replies for `offer_waiting_hil` reuse the waiting message (no offer body) to avoid spam.【F:backend/main.py†L80-L88】
3. Older HIL requests are cleaned up automatically: new reviews replace prior tasks, and Step 5 acceptance clears Step 4 offer tasks so only one manager action remains.【F:backend/workflow_email.py†L296-L320】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L25-L66】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L467-L489】

**Regression Guard:** With `negotiation_pending_decision` present, any client reply should only see the waiting note; the offer should not reappear and only one HIL task should exist.

**Playbook:** If a client acceptance seems ignored, check `hil_open` and `current_step`—they should be `True` and `5`. If not, re-run intake on the acceptance email; the new heuristic forces the HIL acceptance path with the offer summary attached.

### Billing address required before offer submission (New)
**Symptoms:** Clients could confirm offers without a billing address; the manager/HIL view sometimes lacked billing context alongside the line items.

**Fixes Applied:**
1. Offer drafts and HIL summaries now include the billing address (formatted leniently) plus all line items so the manager sees the full offer payload.【F:backend/workflows/steps/step4_offer/trigger/process.py†L200-L260】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L430-L520】
2. Acceptance in Steps 4–5 is gated on a complete billing address (name/company, street, postal code, city, country). If a client confirms before sharing it, we prompt for the missing pieces, keep the thread on “Awaiting Client,” and auto-submit the offer for HIL as soon as the address is provided—no second confirmation needed.【F:backend/workflows/steps/step4_offer/trigger/process.py†L70-L140】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L85-L190】

**UX:** When billing is missing, the assistant politely lists the missing fields and waits; once the address is captured, the offer confirmation resumes automatically and the HIL view includes the full billing line.

### Step 2 Date Confirmation Unconditionally Requiring HIL (Fixed)
**Symptoms:** Every date option message in Step 2 went to HIL for manager approval, even when the client hadn't reached 3 failed attempts. All date confirmation drafts showed up in the manager panel regardless of escalation status.

**Root Cause:** In commit b59100ce (Nov 17, 2025 - "enforce hybrid Q&A + gatekeeping confirmations"), the code added HIL escalation logic for Step 2 after 3 failed attempts. However, line 1595 was set to `requires_approval = True` unconditionally, while the thread_state was correctly conditional on `escalate_to_hil`. This mismatch meant all date drafts had `requires_approval=True` even when not escalating.

**Fix Applied:**
Changed `draft_message["requires_approval"] = True` to `draft_message["requires_approval"] = escalate_to_hil` so that only escalation cases (≥3 attempts) route to HIL.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1595-L1597】

**Regression Guard:** Step 2 date options should go directly to the client (no HIL task created) unless `date_proposal_attempts >= 3`. If you see a Step-2 date task in the manager panel before 3 attempts, check that `requires_approval` is tied to `escalate_to_hil`.

**Regression watchouts (Nov 25):**
- Address fragments (e.g., “Postal code: 8000; Country: Switzerland”) are now treated as billing updates on an existing event, so we stay on Step 4/5 instead of manual review. Room-choice replies stay room choices; we no longer overwrite billing with room labels, and we only display billing once at least some required fields are present.【F:backend/workflows/steps/step1_intake/trigger/process.py†L600-L666】【F:backend/workflows/steps/step4_offer/trigger/process.py†L60-L120】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L70-L140】
- Billing prompts now include a concrete example (“Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland”). Partial replies won’t duplicate room prompts or trigger manual review detours.【F:backend/workflows/steps/step4_offer/trigger/process.py†L130-L190】【F:backend/workflows/steps/step1_intake/trigger/process.py†L610-L666】

**Pending risk:** Empty or single-word replies still won't capture billing; real-world replies should include at least one of street/postal/city/country.

### Raw Table Fallback Overwriting Verbalized Content (Fixed)
**Symptoms:** Client asks about availability and receives ugly raw table markdown like "Room A | Status: available; Capacity up to 40..." instead of properly verbalized prose like "I'd be happy to help you check availability..."

**Root Cause:** The `enrich_general_qna_step2()` function in `backend/workflows/common/general_qna.py` was unconditionally overwriting `draft["body_markdown"]` with raw table data, even when the LLM verbalizer had already generated proper prose. The enrichment function runs AFTER the verbalizer, destroying the verbalized content.

**Fix Applied:**
Added `_is_verbalized_content()` detection function that checks for conversational markers (e.g., "I'd be happy to", "Let me check", "Here's what I found") vs raw table markers (e.g., "Status: available", "Capacity up to"). When verbalized content is detected, the function preserves it and only sets `table_blocks` for frontend structured rendering.【F:backend/workflows/common/general_qna.py†L1183-L1275】

**Regression Guard:** Any availability Q&A response should contain conversational prose, not raw table markdown. If you see "Room | Status:" patterns in client-facing messages, the verbalization preservation is failing.

### Order-Dependent Prerequisites / Stale State Bug (Fixed)
**Symptoms:** After client accepts offer and provides billing, deposit is requested. Client pays deposit via frontend "Pay Deposit" button, but:
1. Workflow asks for deposit AGAIN (ignoring that it was just paid)
2. Nothing is sent to HIL after deposit payment
3. Workflow gets stuck in a loop

**Root Cause:** The `event_entry` dict was loaded once at workflow start and never refreshed. When the frontend API marked the deposit as paid (via `/api/events/{id}/deposit`), the in-memory `event_entry` still had `deposit_paid=False`. The workflow checked the stale dict instead of reloading from database.

**Fix Applied:**
Created `backend/workflows/common/confirmation_gate.py` - a unified, order-independent prerequisites gate that:
1. Reloads event from database to get fresh state (catches API changes)
2. Checks all prerequisites in one place: `offer_accepted`, `billing_complete`, `deposit_paid`
3. Returns `ready_for_hil=True` when all conditions are met
4. Provides `get_next_prompt()` for appropriate prompting when not ready

Wired the unified gate into both `step4_handler.py` and `step5_handler.py`, replacing the separate `_auto_accept_if_billing_ready` and `_check_deposit_payment_continuation` functions.【F:backend/workflows/common/confirmation_gate.py】【F:backend/workflows/steps/step4_offer/trigger/step4_handler.py†L129-L165】【F:backend/workflows/steps/step5_negotiation/trigger/step5_handler.py†L150-L203】

**Regression Guard:** After paying deposit via frontend, workflow should immediately continue to HIL without asking for deposit again. Test by: accept offer → provide billing → pay deposit via frontend → verify HIL task is created.

### Billing Address Creating New Event Instead of Continuing (Fixed)
**Symptoms:** After client accepts offer and is asked for billing address, providing the address (e.g., "JLabs AG, Bahnhofstrasse 15, 8001 Zurich") triggers:
1. A NEW event being created instead of continuing the existing one
2. Wrong message sent ("Noted 22.12.2025. Preferred time?" - Step 2 date confirmation)
3. Duplicate messages being sent

**Root Cause:** The `_ensure_event_record` function in `step1_handler.py` checked `if last_event.get("offer_accepted")` and always created a new event when True, without checking if the client was still providing billing/deposit info for the accepted offer.

**Fix Applied:**
Added smart detection in `_ensure_event_record` that checks before creating new event:
1. `awaiting_billing_for_accept=True` in `billing_requirements` → continue existing
2. `deposit_state.required=True` and not paid → continue existing
3. Message looks like billing info (postal codes, street names via `_looks_like_billing_fragment()`) → continue existing

Only creates new event when: none of the above, indicating a truly new inquiry from the same client.【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1297-L1326】

**Regression Guard:** After accepting offer and being asked for billing, providing an address should show "offer_accepted_continue" in debug log, NOT "new_event_decision" or "db.events.create". Only one event should exist per client's accepted offer.

### HIL Approval Not Routing to Site Visit (Fixed)
**Symptoms:** After manager approves offer via HIL, the workflow went to room availability instead of site visit proposal. Client's next message was handled incorrectly.

**Root Cause:** In `workflow_email.py`, Step 4 HIL approval correctly set `site_visit_state.status="proposed"` but Step 5 HIL approval was missing this same logic. When the approval came from Step 5, the site_visit_state wasn't set, causing wrong routing.

**Fix Applied:**
Added site_visit_state initialization to Step 5 HIL approval path (mirroring Step 4 logic):
```python
target_event.setdefault("site_visit_state", {
    "status": "idle",
    "proposed_slots": [],
    "confirmed_date": None,
    "confirmed_time": None,
})["status"] = "proposed"
```
【F:backend/workflow_email.py†L640-L647】

**Regression Guard:** After HIL approval (either Step 4 or 5), `site_visit_state.status` should be "proposed". Client's next message should route to Step 7 site visit handling, not back to room availability.

### Frontend Zombie Process / Stuck Loading (Operational)
**Symptoms:** Frontend at localhost:3000 shows blank white page or stuck loading spinner indefinitely. Port 3000 appears occupied but page never loads.

**Root Cause:** A Node.js process is listening on port 3000 but has become unresponsive (zombie process). This typically happens after abrupt termination or when the dev server crashes without cleanup.

**Fix:**
```bash
# Kill zombie process
kill -9 $(lsof -nP -iTCP:3000 -sTCP:LISTEN -t)
# Restart frontend
npm run dev
```

**Prevention:** Use the `scripts/dev/dev_server.sh` script which cleans up stale processes before starting.

### Date Range Not Parsed (Fixed)
**Symptoms:** Client specifies "June 11–12, 2026" but system shows December 2025 dates. Date extraction returns null for range formats like "Month DD-DD, YYYY".

**Root Cause:** The `_extract_date` regex in `agent_adapter.py` didn't have a pattern for date ranges with en-dash/hyphen between days (e.g., "June 11–12, 2026").

**Fix Applied:**
Added new regex pattern to handle date ranges:
```python
(r"\b(jan|feb|...)[a-z]*\s+(\d{1,2})[\-–—]\d{1,2},?\s+(\d{4})\b", "mdy")
```
This captures the first day of the range (e.g., June 11 from "June 11–12, 2026").【F:backend/adapters/agent_adapter.py†L271-L272】

**Regression Guard:** Date ranges like "June 11–12, 2026" or "January 5-7, 2026" should extract the first day correctly.

### HIL Approve Button Fails - Missing Export (Fixed)
**Symptoms:** Clicking "Approve" in HIL panel shows error: `module 'backend.workflows.groups.negotiation_close' has no attribute '_apply_hil_negotiation_decision'`

**Root Cause:** The deprecated `negotiation_close.py` wrapper didn't re-export `_apply_hil_negotiation_decision` from `step5_negotiation`.

**Fix Applied:**
Added `_apply_hil_negotiation_decision` to exports in:
- `backend/workflows/steps/step5_negotiation/__init__.py`
- `backend/workflows/steps/step5_negotiation/trigger/process.py`

**Regression Guard:** HIL approve/reject buttons should work. If this error reappears, check that all functions called by `workflow_email.py` are properly exported.

### Confirmation Gate ImportError (Fixed)
**Symptoms:** Workflow crashes with `ImportError: cannot import name 'DB_PATH'` when billing/deposit gate is checked.

**Root Cause:** `confirmation_gate.py` tried to import `DB_PATH` from `database.py` but that constant doesn't exist.

**Fix Applied:** Changed to compute the path directly: `Path(__file__).resolve().parents[2] / "events_database.json"`【F:backend/workflows/common/confirmation_gate.py†L127】

### Billing Not Recognized After Capture (Fixed)
**Symptoms:** Client provides billing address but system keeps asking for it in a loop.

**Root Cause:** The confirmation gate was reloading from database to check billing status, but the billing had just been captured in memory and wasn't persisted yet. The database check saw old data without billing.

**Fix Applied:** Gate now uses in-memory `event_entry` for billing check (which has latest captured data), and only reloads from database to check deposit status (for frontend API updates).【F:backend/workflows/steps/step4_offer/trigger/step4_handler.py†L138-L149】【F:backend/workflows/steps/step5_negotiation/trigger/step5_handler.py†L159-L170】

### Billing Address Routing to Wrong Step (Fixed - 2025-12-22)
**Symptoms:** After accepting an offer and providing billing address, the system responded with a generic fallback message instead of routing to HIL for final approval. Billing address was sometimes captured as the original greeting message instead of the actual address.

**Root Causes:**
1. **Duplicate message detection:** The duplicate message check didn't account for billing flow, blocking repeated messages during billing capture.
2. **Change detection during billing:** The billing address message triggered room/date change detection, causing the workflow to route to Step 3 instead of Step 5.
3. **Step corruption:** If step was incorrectly set before billing flow started, it wasn't corrected.
4. **Response key mismatch:** `_handle_accept()` returns `{"draft": {"body": ...}}` but the code expected `response["body"]`.

**Fixes Applied:**
1. **Duplicate bypass:** Added billing flow check to duplicate message detection - messages during `offer_accepted + awaiting_billing_for_accept` bypass duplicate detection.【F:backend/workflow_email.py†L975-L981】
2. **Change detection guards:** Added `in_billing_flow` guards to skip:
   - Enhanced change detection (date/room/requirements)
   - Vague date confirmation check
   - Legacy date change fallback
   - Room change detection
   【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1093-L1105】【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1156-L1160】【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1215-L1222】
3. **Step correction:** Before the routing loop, force `current_step=5` when in billing flow regardless of stored value.【F:backend/workflow_email.py†L1031-L1042】
4. **Response key fix:** Fixed Step 5 to access `response["draft"]["body"]` instead of `response["body"]`.【F:backend/workflows/steps/step5_negotiation/trigger/step5_handler.py†L179-L181】

**Regression Guard:** After providing a billing address during accepted offer flow, the system should:
- NOT trigger duplicate message detection
- NOT route to Step 3 or any step other than Step 5
- Correctly capture the billing address
- Route to HIL for final approval with "sent to manager" message

### Frontend Billing Capture / Step Corruption (Fixed - 2025-12-28)
**Symptoms:** When running the full billing→deposit→HIL flow through the frontend UI, deposit payment failed with "Deposit can only be paid at Step 4 or Step 5" even though offer was accepted. Event was at Step 3 instead of Step 5. `offer_accepted` was `None` even though the offer was accepted.

**Root Cause (Two Issues Found):**
1. **Missing `offer_accepted` flag:** `step5_handler.py` did NOT set `event_entry["offer_accepted"] = True` when handling offer acceptance. Step4 had this, but step5 didn't. This broke the billing flow bypass condition which requires BOTH `offer_accepted=True` AND `awaiting_billing_for_accept=True`.
2. **Guard forcing during billing:** `evaluate_pre_route_guards()` in `pre_route.py` was forcing step changes (to 3) even during billing flow because the billing flow bypass didn't work (due to issue #1).

**Fixes Applied:**
1. **Added `offer_accepted=True`:** Added `event_entry["offer_accepted"] = True` in step5_handler.py accept classification block to match step4 behavior.【F:backend/workflows/steps/step5_negotiation/trigger/step5_handler.py†L420-L424】
2. **Added billing flow bypass:** Added billing flow check in `evaluate_pre_route_guards()` to skip guard forcing during billing flow, following Pattern 1: Special Flow State Detection.【F:backend/workflows/runtime/pre_route.py†L113-L121】

**Regression Test:** `backend/tests/regression/test_billing_step_preservation.py`
- `test_billing_flow_bypasses_guard_forcing`
- `test_normal_flow_allows_guard_forcing`
- `test_billing_flow_without_awaiting_flag_allows_forcing`

**E2E Verified:** Full Playwright test: intake → room → preask → offer → accept → billing → deposit → HIL approval → site visit prompt

**Regression Guard:** After the complete frontend flow (accept offer → provide billing → pay deposit), verify:
1. `current_step = 5` (not 3)
2. `offer_accepted = True` (not None)
3. `billing_details.street` is populated in database
4. `pending_hil_requests` contains the HIL task
5. The "📋 Manager Tasks" section appears in the frontend with approve/reject buttons

### HIL Task Not Appearing in Tasks Panel After Deposit Payment (Fixed - 2025-12-23)
**Symptoms:** After paying deposit via the frontend "Pay Deposit" button, the HIL message appeared directly in the chat instead of in the Manager Tasks panel. The expected flow is: deposit payment → HIL task in Tasks panel → manager clicks Approve → site visit message appears in chat.

**Root Cause:** Two issues combined:
1. **Frontend:** `handlePayDeposit` in `page.tsx` was calling `appendMessage()` to add the API response directly to chat, bypassing the HIL flow entirely.
2. **Backend:** Event entries didn't have `thread_id` stored, so when tasks were filtered by `task.payload?.thread_id === sessionId`, the task's `thread_id` (defaulting to `event_id`) didn't match the frontend's `sessionId`, hiding the task from the panel.

**Fixes Applied:**
1. **Frontend:** Removed `appendMessage()` from `handlePayDeposit` - HIL tasks should appear in Tasks panel for manager approval, not in chat.【F:atelier-ai-frontend/app/page.tsx†L886-L907】
2. **Backend:** Added `thread_id = _thread_id(state)` to event entries in 4 places in step1_handler.py when events are created/updated.【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1293-L1403】

**Regression Guard:** After paying deposit:
1. HIL task should appear in the "📋 Manager Tasks" section (NOT in chat)
2. Task should be visible because `thread_id` matches `sessionId`
3. Clicking Approve should send the site visit message to chat
4. Test with fresh session to ensure `thread_id` is set correctly on new events

### Billing Address Not Captured From Separate Message (Fixed - 2025-12-29)
**Symptoms:** When the client accepts an offer and the system asks for billing address, the client provides a proper billing address in a follow-up message (e.g., "Schmidt Industries GmbH, Bahnhofstrasse 42, 8001 Zurich, Switzerland"), but it is not captured. The billing_details in the database shows null for all fields, and `awaiting_billing_for_accept` remains True.

**Root Cause:**
The billing capture code at `step5_handler.py:179-182` was positioned AFTER the pending HIL check at lines 152-168. When the client sends a billing address, a pending HIL task exists from the offer acceptance, causing an early return before billing capture could execute.

**Fix Applied:**
1. Moved billing capture code BEFORE the pending HIL check in `step5_handler.py`
2. Modified the pending HIL check to skip when `offer_accepted=True` (billing flow)
3. The billing address is now captured immediately when `awaiting_billing_for_accept=True`

**Files Modified:**
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` (lines 113-175)

**Verified:** E2E test confirms "Thank you for providing your billing details!" response after separate billing message

### Catering Q&A Returns Room Info Instead of Catering Details (Fixed - 2025-12-29)
**Symptoms:** When asking catering questions like "What lunch options do you have?" after rooms are presented, the system returns another room availability message instead of catering/menu information.

**Root Cause:**
- `route_general_qna` was imported in `general_qna.py` but never called in `present_general_room_qna`
- The function only used `build_structured_qna_result` which focuses on room/date queries
- Catering questions were detected correctly (`classification["secondary"]` = "catering_for") but not routed properly

**Fix Applied:**
1. Added catering-specific routing check in `present_general_room_qna`
2. When `classification["secondary"]` contains "catering_for" or "products_for", route to `route_general_qna`
3. `route_general_qna` has proper catering handling via `_catering_response()` in `qna/router.py`

**Files Modified:**
- `backend/workflows/common/general_qna.py` (lines 218-260)

**Verified:** E2E test confirms "Here are our catering packages" response instead of room availability

### General Q&A Falls Back to Structured Format (Open - 2025-12-29)
**Symptoms:** When asking general questions like "What's included with the room rental?", "Do you have parking?", "What's your cancellation policy?", or "Do you have WiFi?", the system returns a generic structured response instead of actually answering the question.

**Observed Behavior:**
- Questions are detected as Q&A (classification works)
- However, response falls back to structured format showing event details (date, attendees, room, price)
- The actual question is not answered

**Example Response (Wrong):**
```
- Event Date: **June 1, 2026**
- Number of Attendees: **100**
- Room: **Room B**
- Price: Not specified
```

**Expected Behavior:**
- General questions should be routed to the appropriate Q&A handler
- Room inclusions, parking, WiFi, cancellation policy should return relevant information

**Root Cause (Suspected):**
- Q&A routing in Step 3 may not be handling non-catering general questions
- The `build_structured_qna_result` function may be used instead of proper Q&A handlers

**Priority:** Medium - UX issue, not a workflow blocker

**Investigation Needed:** Check Q&A routing in `step3_handler.py` and `general_qna.py` for how non-catering questions are handled.

### Room choice repeats / manual-review detours (Ongoing Fix)
**Symptoms:** After a client types a room name (e.g., “Room E”), the workflow dropped back to Step 3, showed another room list, or enqueued manual review; sometimes the room label was mistaken for a billing address (“Billing Address: Room E”).

**Fixes Applied:**
- Early room-choice detection now runs for any confidence level and locks the room at Step 4 (thread stays “Awaiting Client”) instead of rerunning Step 3.【F:backend/workflows/steps/step1_intake/trigger/process.py†L120-L155】【F:backend/workflows/steps/step1_intake/trigger/process.py†L760-L815】
- Billing updates while awaiting address only trigger when the reply looks like an address; “Room …” or other short replies no longer overwrite billing or send to manual review.【F:backend/workflows/steps/step1_intake/trigger/process.py†L650-L676】

**Regression Guard:** After a client types a room name, the next message should be the Step 4 offer/products prompt (no duplicate room list, no manual-review task, no “Billing Address: Room …”). If confidence is low, the room should still be accepted.

### Manager approval now opt-in (New)
**Symptoms:** Offers were sent to HIL/manager even when the client didn’t ask for manager review.

**Fixes Applied:** Acceptance now only opens HIL when the client explicitly mentions the manager; otherwise the offer is confirmed directly and we continue to site-visit prep.【F:backend/workflows/steps/step4_offer/trigger/process.py†L180-L250】【F:backend/workflows/steps/step4_offer/trigger/process.py†L1190-L1245】

**Regression Guard:** A plain “that’s fine” acceptance now always opens the manager approval task (Step 5) so the manager sees the approve/decline buttons in the UI before the client-facing confirmation is released. GUI Approve/Reject calls `/api/tasks/{task_id}/approve|reject`, which applies the pending Step‑5 decision and sends the assistant reply; if it doesn’t fire, check that the task is `offer_message` (not room/date/manual) and that `pending_hil_requests` contains only step=5 entries.【F:backend/main.py†L760-L860】【F:backend/workflow_email.py†L422-L540】

### Menu selection alongside room choice (New)
**Symptoms:** When a client replies “Room E with Seasonal Garden Trio,” the menu wasn’t captured, menus weren’t shown with room options, and the offer totals ignored catering.

**Fixes Applied:**
- Menu choices are detected in the room-selection turn; we add the menu as a catering line item (per-event by default) and store the choice.【F:backend/workflows/steps/step1_intake/trigger/process.py†L150-L190】
- Room-availability messages now surface concise menu bullets with per-event pricing (rooms: all) so the client can decide in one go.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L980-L1030】
- Offer/HIL summaries respect manager opt-in and keep CTA text aligned (confirm vs manager approval).【F:backend/workflows/steps/step4_offer/trigger/process.py†L1000-L1105】【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L570-L610】
- If no menu was chosen before the offer, the offer body includes a short “Menu options you can add” block; when a menu was already selected, the list is omitted to avoid repetition.【F:backend/workflows/steps/step4_offer/trigger/process.py†L1065-L1115】
- Coffee badges in room cards are suppressed unless the client asked for coffee/tea/drinks, so unrelated “Coffee ✓” no longer appears by default.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L900-L960】
- The “Great — <room> … ready for review” intro is now only shown when the client explicitly asked for manager review; normal confirmations start directly with the offer draft line.【F:backend/workflows/steps/step4_offer/trigger/process.py†L1000-L1010】

**Regression Guard:** A reply like "Room B with Seasonal Garden Trio" should lock the room, add the menu (priced per guest) to the offer, and show a confirmation CTA without defaulting to manager approval.

### Room selections misread as acceptances (New)
**Symptoms:** When clients clicked/typed room-action labels such as "Proceed with Room E", Step 4 treated the message as an offer acceptance, sent the thread to HIL, and blocked normal offer iteration.

**Fix:** Offer acceptance now ignores messages that include a detected room choice (`_room_choice_detected`) or the phrase "proceed with room…", so these stay in the normal offer loop instead of triggering manager review.【F:backend/workflows/steps/step4_offer/trigger/process.py†L185-L204】

**Regression Guard:** Room selections should keep the thread in "Awaiting Client" with `action=offer_draft_prepared` and no pending HIL requests unless the client explicitly accepts the offer.

### Stale negotiation_pending_decision after detours (Fixed - 2025-12-17)
**Symptoms:** After selecting a room ("Room B"), the system showed "sent to manager for approval" instead of generating an offer. This happened even though no offer had been accepted yet.

**Root Cause:** When a client previously accepted an offer (triggering `negotiation_pending_decision`), then changed requirements (causing detour from step 5 → step 3), the `negotiation_pending_decision` was NEVER cleared. When the client selected a room and flow returned to step 4, it saw the stale pending decision and returned `offer_waiting_hil` instead of generating a fresh offer.

**Fixes Applied:**
1. **Step 1:** Clear `negotiation_pending_decision` when requirements hash changes (triggering requirements_updated detour).【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1152-L1153】
2. **Step 4:** Clear `negotiation_pending_decision` when `_route_to_owner_step` detours to step 2 or 3.【F:backend/workflows/steps/step4_offer/trigger/step4_handler.py†L604-L606】
3. **Step 5:** Clear `negotiation_pending_decision` when structural change detour goes to step 2 or 3.【F:backend/workflows/steps/step5_negotiation/trigger/step5_handler.py†L162-L164】

**Regression Guard:** After any detour back to step 2 or 3, `negotiation_pending_decision` should be `null`. Room selections should generate a fresh offer, not show "sent to manager".

### Initial Event Inquiries Return Generic Fallback Instead of Room Availability (Fixed - 2025-12-18)
**Status: FIXED** - Root cause identified and fixed.

⚠️ **CRITICAL: Event Reuse Logic Bug** ⚠️
This bug caused multiple cascading failures when `_ensure_event_record()` created NEW events incorrectly OR reused OLD events incorrectly. Key lessons:
1. **Never compare dates if new message has no date** - "Not specified" ≠ "08.05.2026" triggers false positives
2. **Follow-up messages (like "Room E") have NO date** - must skip date comparison
3. **Site visit routing affects ALL steps** - routing to Step 7 mid-flow causes no draft_messages → fallback

**Symptoms:** Initial event inquiries like "We'd like to organize a networking event for 60 guests on 08.05.2026, 18:00-22:00" returned generic fallback messages like "Thanks for your message. I'll follow up shortly with availability details." instead of proper room availability with specific rooms.

**Root Cause (NEW - 2025-12-18):**
The system was REUSING existing events for the same email instead of creating new ones. When a client had an existing event with `site_visit_state.status = "proposed"`, new inquiries would:
1. Match to the old event via `last_event_for_email()`
2. Trigger site visit routing (detour to Step 7)
3. Return no draft messages → fallback triggered

**Secondary Bug:** The initial fix triggered false positives for follow-up messages like "Room E":
- Message has no date → `event_data["Event Date"] = "Not specified"`
- Comparison: "Not specified" != "08.05.2026" → creates NEW event
- New event at Step 2 asking for time → wrong response

**Diagnostic Added (messages.py:503-510):**
```python
if not assistant_reply and not hil_pending:
    print(f"[WF][FALLBACK_DIAGNOSTIC] start_conversation returned empty reply")
    print(f"[WF][FALLBACK_DIAGNOSTIC] wf_res.action={wf_res.get('action')}")
    ...
```

**Fix Applied (step1_handler.py `_ensure_event_record()`):**
Added checks to create a NEW event instead of reusing existing when:
1. New message has DIFFERENT event date than existing event (**ONLY if new date is actual, not "Not specified"**)
2. Existing event status is "confirmed", "completed", or "cancelled"
3. Existing event has `site_visit_state.status` in ("proposed", "scheduled")

**Critical Check Added:**
```python
new_date_is_actual = new_event_date not in ("Not specified", "not specified", None, "")
if new_date_is_actual and existing_event_date and new_event_date != existing_event_date:
    should_create_new = True
```

**Root Cause (Three Issues):**
1. **Q&A engine missing `non_event_info` handler:** When Q&A classification returned `qna_subtype: "non_event_info"`, the `_execute_query()` function in `engine.py` had no handler for this subtype, returning empty `db_summary` (0 rooms, 0 dates, 0 products).
2. **Context builder not using captured state:** The `_resolve_*` functions in `context_builder.py` returned `source="UNUSED"` for `non_event_info` subtype instead of using captured state from Step 1.
3. **Initial inquiries misrouted to Q&A path:** Step 3 handler detected questions in messages (via heuristic `is_general=True`) and routed initial inquiries through the Q&A path instead of the normal room availability flow. This happened because the Q&A path is designed for follow-up questions after rooms have been presented, not initial inquiries.

**Chain of Failure:**
```
Initial inquiry with questions → is_general=True (heuristic detected "?")
→ Q&A extraction returns qna_subtype: "non_event_info"
→ _execute_query() has no handler → empty db_summary
→ QnA verbalizer gets 0 rooms → LLM hallucinates or returns fallback
→ Generic "Thanks for your message" shown to client
```

**Fixes Applied:**
1. **`backend/workflows/qna/engine.py`** (lines 191-229): Added fallback handler for `non_event_info` subtype that uses captured state (date, attendees) to query room availability.
2. **`backend/workflows/qna/context_builder.py`** (lines 139-143, 238-242, 321-325): Updated `_resolve_attendees`, `_resolve_date`, `_resolve_room` to use captured state for `non_event_info` subtype.
3. **`backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`** (lines 334-346): Added check to skip Q&A path for first entry to Step 3 by detecting `has_step3_history` (looks for `room_pending_decision` or audit_log entries for Step 3).

**Regression Guard:** Initial event inquiries (first message to Step 3) should always show room availability with specific room names and features. If you see generic fallback messages for initial inquiries, check:
1. Q&A classification subtype (should be handled even if `non_event_info`)
2. `has_step3_history` check (should be False for initial inquiries, skipping Q&A path)
3. `db_summary` in Q&A engine (should have rooms from captured state)

---

### Date Change Detours from Steps 3/4/5 (Fixed - 2025-12-03)
**Symptoms:** When a client at Step 3 (Room Availability), Step 4 (Offer), or Step 5 (Negotiation) requested a date change (e.g., "sorry made a mistake, wanted 2026-02-28 instead"), the workflow would:
- Return generic fallback message "Thanks for the update. I'll keep you posted..."
- Not route back to Step 2 to confirm the new date
- In some cases, enter an infinite detour loop with no proper response

**Root Causes:**
1. **Step 5 - No message text parsing:** `_detect_structural_change()` only checked `state.user_info.get("date")` but this field wasn't populated because the LLM extraction skipped it (event_date already had a value).
2. **Step 3 - Duplicate detour loop:** When Step 2's `finalize_confirmation` internally called Step 3, Step 3 would detect the same message as a date change again (pattern-based detection) and try to detour back to Step 2, creating an infinite loop.
3. **Step 3 - Multi-date parsing bug:** The skip-duplicate-detour logic checked only `message_dates[0]` which could be today's date (parsed erroneously), causing the skip to fail.

**Fixes Applied:**
1. **Step 5:** Updated `_detect_structural_change()` to parse dates directly from message text using `parse_all_dates()`. If any date differs from `chosen_date`, triggers detour to Step 2.【F:backend/workflows/steps/step5_negotiation/trigger/process.py†L532-L558】
2. **Step 3:** Added skip-duplicate-detour check that compares message dates with `chosen_date`. If the just-confirmed date is in the message, it's not a new change request.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L197-L223】
3. **Step 3:** Changed date matching from `message_dates[0] == chosen_date` to `chosen_date in message_dates` to handle cases where multiple dates are parsed.

**Regression Guard:** After a client at any step (3/4/5) says "sorry, I meant [new date]", the workflow should:
- Detect the date change
- Route back to Step 2 to confirm the new date
- Re-evaluate room availability for the new date
- Return to the caller step (or proceed forward)

### Date Mismatch: Feb 7 becomes Feb 20 (Open - Investigating)
**Symptoms:** Client confirms "2026-02-07 18:00–22:00" in Step 2, but Step 3 room availability message shows "Rooms for 30 people on 20.02.2026" instead of 07.02.2026.

**Observed:**
- Client input: "2026-02-07 18:00–22:00"
- System output: "Rooms for 30 people on 20.02.2026" and "Room B on None" in offer title
- Three separate issues: wrong day (7 → 20), wrong format in some places, "None" appearing in offer title

**Suspected Cause:** Date parsing or storage corruption somewhere in the Step 2 → Step 3 transition. Possibly:
1. Date extraction parsing error (confusing day/month)
2. DD.MM.YYYY vs YYYY-MM-DD format conversion issue
3. `chosen_date` getting corrupted during step transition

**Files to investigate:**
- `backend/workflows/steps/step2_date_confirmation/trigger/process.py` - date parsing and storage
- `backend/workflows/common/datetime_parse.py` - date format conversions
- `backend/workflows/steps/step3_room_availability/trigger/process.py` - date retrieval for room search

**Reproduction:** Start new event → provide dates in February → confirm "2026-02-07" → check if Step 3 shows correct date.

### Q&A Detection Not Working in Step 3 (Open - Dec 29, 2025)
**Symptoms:** Client asks a general question ("What catering options do you have available?") while in Step 3 (Room Availability), but instead of getting a Q&A response about catering, the system re-generates a room availability message.

**Observed:**
- Client input: "What catering options do you have available?"
- Expected: Q&A response about catering menu options
- Actual: Room availability message repeating the same room info

**Suspected Cause:** Q&A detection is either:
1. Not being triggered in Step 3 handler
2. Being overridden by room availability logic
3. Intent classification not detecting the question as Q&A

**Files to investigate:**
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Q&A handling logic in Step 3
- `backend/workflows/common/general_qna.py` - General Q&A detection and response
- `backend/detection/unified.py` - `is_question` signal detection

**Reproduction:** Start new event → go through date confirmation → at Step 3 room options, ask "What catering options do you have?" → verify Q&A response is generated

**Priority:** Medium - affects user experience but doesn't block workflow

### Capacity Exceeds All Rooms - No Filtering/Routing (Fixed Dec 25)
**Symptoms:** Client requests capacity that exceeds ALL available rooms (e.g., 150 people when max room is 120). Previously showed contradictory message: "Room B is a great fit for your 150 guests. However, it has a capacity of 60."

**Fix Applied:**
1. Added `get_max_capacity()` and `any_room_fits_capacity()` helpers to `backend/rooms/ranking.py`
2. Added capacity check in Step 3 handler before room selection
3. Created `_handle_capacity_exceeded()` function with:
   - Clear message explaining capacity limits
   - Three alternatives: reduce capacity, split event, external venue partnership
   - Action buttons for quick resolution

**Files Modified:**
- `backend/rooms/ranking.py` - Added capacity helper functions
- `backend/rooms/__init__.py` - Exported new functions
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Added capacity exceeded detection and handler

**Regression Guard:** Request 150 people → should see "Capacity exceeded" message with max (120) and three alternatives. Client reduces to 100 → should see Room E as best fit.

---

### Python Bytecode Cache Causing Startup Failures (Fixed)
**Symptoms:** First API request after restarting the backend fails with `__init__() got an unexpected keyword argument 'draft'` (500 Internal Server Error). Subsequent requests succeed. Frontend shows "Error connecting to backend" even though the backend is running.

**Root Cause:** Stale Python bytecode cache (`.pyc` files) contained old versions of dataclasses (e.g., `TraceEvent` without the `draft` field). When the code was updated to pass `draft=draft` to `TraceEvent()`, the cached bytecode still had the old class definition without that field.

**Fix Applied:**
1. Clear all Python bytecode caches before starting: `find backend -type d -name "__pycache__" -exec rm -rf {} +`
2. Use `PYTHONDONTWRITEBYTECODE=1` when starting the backend to prevent cache creation
3. The startup script now clears caches automatically

**Prevention:**
- Always run with `PYTHONDONTWRITEBYTECODE=1` during development
- After pulling new code or modifying dataclasses, run: `find backend -name "*.pyc" -delete && find backend -type d -name "__pycache__" -exec rm -rf {} +`
- If you see `unexpected keyword argument` errors on first request, clear caches and restart

**Quick Fix:**
```bash
# Clear caches and restart
find backend -type d -name "__pycache__" -exec rm -rf {} +
lsof -nP -tiTCP:8000 -sTCP:LISTEN | xargs kill -9
PYTHONDONTWRITEBYTECODE=1 python3 backend/main.py
```

### load_db() Signature Mismatch (Fixed)
**Symptoms:** `load_db() missing 1 required positional argument: 'path'` when making API calls. Backend starts but requests fail with 500 Internal Server Error.

**Root Cause:** There are two `load_db` functions in the codebase:
1. `backend/workflow_email.py:load_db(path: Path = DB_PATH)` — has default path
2. `backend/workflows/io/database.py:load_db(path: Path, lock_path: Optional[Path] = None)` — requires path argument

Code in `backend/workflows/steps/step2_date_confirmation/trigger/process.py` imported from `database.py` but called `load_db()` without arguments.

**Fix Applied:**
For router Q&A integration, the `db` parameter is optional (`None` is acceptable) since `route_general_qna()` doesn't need the database for catering/products responses. Changed `db_snapshot = load_db()` to pass `None` directly.

**Prevention:**
- When using `load_db`, check which version you're importing
- If you don't need the database, pass `None` to functions that accept `Optional[Dict]`
- Prefer `WF_DB_PATH` from `workflow_email.py` if you need the default path

### Catering Q&A Not Appearing with Multi-Day Requests (Fixed - 2025-12-16)
**Symptoms:** Client asks "What package options do you recommend?" alongside a multi-day date request (e.g., "June 11–12, 2026"). The workflow correctly proposes dates and the structured room availability table, but the catering Q&A content disappeared from the final response—even though it was being appended earlier in the code flow.

**Investigation Log (systematic debugging):**
1. ✗ Checked if router Q&A integration was missing from `general_rooms_qna` path — Found integration present at lines 3429-3469
2. ✗ Checked if `secondary_types` was empty — Found it correctly had `['catering_for']`
3. ✗ Checked if `route_general_qna()` returned empty — Found it correctly returned catering packages
4. ✗ Checked if body wasn't being appended — Found body WAS being appended (body_len=920)
5. ✓ **Found root cause:** After `add_draft_message()`, the body_len was 872, but in `main.py` it was 913 with DIFFERENT content. The draft was being **OVERWRITTEN** downstream.

**Root Cause:** The `enrich_general_qna_step2()` function in `backend/workflows/common/general_qna.py` (lines 1187-1189) was unconditionally overwriting `draft["body_markdown"]` and `draft["body"]` when rebuilding the structured room table. This function is called at line 931 in `process.py` AFTER the router Q&A integration code appended catering content, causing that content to be lost.

**Files Involved:**
- `backend/workflows/steps/step2_date_confirmation/trigger/process.py` — Router Q&A integration at lines 3429-3469
- `backend/workflows/common/general_qna.py` — `enrich_general_qna_step2()` overwrite at lines 1187-1198

**Fix Applied:**
Modified `enrich_general_qna_step2()` in `general_qna.py` to preserve router Q&A content:
```python
# Preserve router Q&A content (catering, products, etc.) that was appended earlier
if draft.get("router_qna_appended"):
    old_body_markdown = draft.get("body_markdown", "")
    # Extract the router Q&A section (everything after "---\n\nINFO:")
    if "\n\n---\n\nINFO:" in old_body_markdown:
        router_section = old_body_markdown.split("\n\n---\n\nINFO:", 1)[1]
        body_markdown = f"{body_markdown}\n\n---\n\nINFO:{router_section}"
```

**Test Verification:**
- Multi-day request with catering question now correctly shows:
  - Structured room availability table (from verbalizer)
  - Catering packages list
  - Info link with snapshot_id: `<a href="http://localhost:3000/info/qna?snapshot_id=...">View Catering information</a>`
- Example test: "Training Workshop – 2-Day Booking Request in June" with "June 11–12, 2026" and "what package options you recommend?"

**Regression Guard:** If catering content disappears from multi-variable Q&A responses, check if:
1. `router_qna_appended` flag is set on the draft
2. `enrich_general_qna_step2()` or similar functions preserve that flag's content

### GroupResult Missing `draft` Field (Fixed - 2025-12-16)
**Symptoms:** 500 Internal Server Error with `__init__() got an unexpected keyword argument 'draft'` when processing messages.

**Root Cause:** In `backend/workflow_email.py` line 904-914, the duplicate message detection code was calling `GroupResult(draft={...})` but the `GroupResult` dataclass (defined in `backend/workflows/common/types.py:281`) doesn't have a `draft` field - only `action`, `payload`, and `halt`.

**Fix Applied:** Changed the code to pass `draft` inside `payload` instead of as a separate argument:
```python
duplicate_response = GroupResult(
    action="duplicate_message",
    halt=True,
    payload={
        "draft": {...}  # Now inside payload, not a separate argument
    },
)
```

Also added missing import for `trace_marker`:
```python
from backend.debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel
```

**Regression Guard:** If you add new fields to `GroupResult`, update all callers. Check `GroupResult.__dataclass_fields__` for available fields.

### Python Bytecode Cache Persistence (Ongoing)
**Symptoms:** After editing dataclass definitions, `__init__() got an unexpected keyword argument` errors persist even after clearing `__pycache__` directories.

**Root Cause:** Python's module cache (`sys.modules`) keeps old class definitions in memory even after bytecode cache is cleared. When uvicorn reloads, modules that were imported before the reload retain stale definitions.

**Mitigation Applied:**
- Added cache clearing at the top of `backend/main.py` (runs before any imports)
- Set `sys.dont_write_bytecode = True` to prevent new cache creation
- Call `importlib.invalidate_caches()` to invalidate import caches

**Prevention:**
- Always run with `PYTHONDONTWRITEBYTECODE=1`
- When editing dataclasses, restart the server completely (not just reload)
- Clear caches before starting: `find backend -type d -name "__pycache__" -exec rm -rf {} +`

### Sequential Workflow vs General Q&A Misclassification (Fixed - 2025-12-17)
**Symptoms:** When a client confirms the current workflow step AND asks about the next step in the same message (e.g., "Please confirm May 8 and show me available rooms"), the system incorrectly classified this as "general Q&A" instead of recognizing it as natural workflow continuation.

**Root Cause:** The `detect_general_room_query()` function set `is_general=True` when it detected room-related questions, without considering that asking about the immediate next step while completing the current step is natural workflow progression. This caused:
1. Messages like "Confirm May 8 and show rooms" to trigger Q&A handling instead of normal step progression
2. The workflow to display informational Q&A responses instead of advancing from date confirmation to room availability

**The Distinction:**
- **Natural workflow continuation (NOT Q&A):** Confirming step N and asking about step N+1
  - Example at Step 2: "Confirm May 8 and show available rooms" → Confirm date, proceed to Step 3
  - Example at Step 3: "Room A looks good, what catering options?" → Confirm room, proceed to Step 4
  - Example at Step 4: "Accept the offer, when can we do a site visit?" → Accept offer, proceed to Step 7
- **General Q&A:** Asking about a step without being at the prerequisite step
  - Example at Step 2 (no date yet): "What rooms do you have?" → Q&A about Step 3 content
  - Example at Step 2: "Tell me about your catering" → Q&A about Step 4 content (out of order)

**Fixes Applied:**
1. Created `detect_sequential_workflow_request()` function in `backend/workflows/nlu/sequential_workflow.py` that detects when a message contains both:
   - An action/confirmation for the current step (patterns for steps 2, 3, 4)
   - A question/request about the immediate next step (steps 3, 4, 5, 7)【F:backend/workflows/nlu/sequential_workflow.py†L115-L170】

2. Integrated sequential detection in Step 2 (Date Confirmation) to suppress `is_general` when the client is confirming a date AND asking about rooms.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L920-L940】

3. Integrated sequential detection in Step 3 (Room Availability) to suppress `is_general` when the client is selecting a room AND asking about catering/offers.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L300-L320】

4. Integrated sequential detection in Step 4 (Offer) to suppress `is_general` when the client is accepting an offer AND asking about next steps (site visit, deposit, etc.).【F:backend/workflows/steps/step4_offer/trigger/process.py†L333-L353】

**Testing:** Added comprehensive test suite at `backend/tests/detection/test_sequential_workflow.py` with 64 test cases covering:
- Step 2→3 sequential patterns (date + room)
- Step 3→4 sequential patterns (room + catering)
- Step 4→5/7 sequential patterns (offer + next steps)
- Edge cases and negative tests to ensure pure Q&A is not suppressed

5. **Classification Persistence Fix:** When Step 2 auto-runs Step 3 after date confirmation, Step 3 was re-classifying the same message and potentially overwriting the sequential workflow detection from Step 2. Fixed by having Step 3 check for and reuse a cached classification that has `workflow_lookahead` set.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L178-L185】

**Regression Guard:** When a client message combines current step action + next step inquiry, the workflow should proceed naturally to the next step. The trace log should show `SEQUENTIAL_WORKFLOW` marker, and `is_general` should be `False`. If Q&A handling triggers for such messages, check that `detect_sequential_workflow_request()` is being called and that the patterns match the message.

### Room Lock Cleared Unconditionally on Date Change (In Progress - 2025-12-21)
**Status: PARTIAL FIX** - Multiple code paths identified and patched; further testing needed.

**Symptoms:** When a client changes the date from the offer/negotiation stage (Steps 4/5), the system clears `locked_room_id` unconditionally. This forces the client to re-select the room even when the same room is still available on the new date. Expected behavior: if the locked room is still available, skip room selection and return directly to Step 4.

**Root Cause:**
Multiple code paths were clearing `locked_room_id=None` when a date change was detected:
1. `step4_handler.py:220-250` — Date change detection in Step 4
2. `step2_handler.py:881-897` — Date change detection in Step 2
3. `step2_handler.py:2384-2393` — Date confirmation flow (main culprit)
4. `step3_handler.py:291-307` — Date change detection in Step 3

All four locations used `update_event_metadata(event_entry, locked_room_id=None, ...)` which erased the room lock before Step 3 could verify if the room was still available.

**Fixes Applied:**
1. **Preserve room lock on date changes:** Changed all four locations to only clear `room_eval_hash=None` (to trigger re-verification) while keeping `locked_room_id` intact.【F:backend/workflows/steps/step4_offer/trigger/step4_handler.py†L220-L250】【F:backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py†L881-L897】【F:backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py†L2384-L2393】【F:backend/workflows/steps/step3_room_availability/trigger/step3_handler.py†L291-L307】

2. **Fast-skip logic in Step 3:** Added code to check if the locked room is still available on the new date. If available, update `room_eval_hash` and return to caller step (usually Step 4) without presenting room options again. If unavailable, clear the lock and proceed with normal room selection.【F:backend/workflows/steps/step3_room_availability/trigger/step3_handler.py†L438-L489】

```python
# FAST-SKIP: If room is already locked and still available on new date
if locked_room_id and not explicit_room_change:
    locked_room_status = status_map.get(locked_room_id, "").lower()
    room_still_available = locked_room_status in ("available", "option")
    if room_still_available:
        update_event_metadata(event_entry, room_eval_hash=current_req_hash)
        return _skip_room_evaluation(state, event_entry)  # Return to caller
    else:
        update_event_metadata(event_entry, locked_room_id=None, room_eval_hash=None)
```

3. **Requirements changes still clear lock:** When `change_type == "requirements"`, the lock IS cleared since the room may no longer fit the new capacity/duration.【F:backend/workflows/steps/step4_offer/trigger/step4_handler.py†L235-L245】

**Testing Status:**
- Initial test showed room lock still being cleared; additional code paths in step2_handler.py identified and fixed
- Need to verify all code paths are covered with live API testing
- Server reload timing may affect test results

**Regression Guard:** When a client changes the date from Step 4/5:
1. If the locked room is available on the new date → Step 3 should skip room selection and return to Step 4
2. If the locked room is NOT available → Step 3 should clear the lock and present room options
3. `locked_room_id` should only be `None` after Step 3 explicitly clears it due to unavailability

### Event Reuse Bug - Stale offer_accepted Causing Wrong Flow (Fixed - 2025-12-22)
**Symptoms:** New event inquiry from existing client gets routed to HIL confirmation flow instead of normal intake. Client sends "I'd like to book a workshop for 25 people on June 11, 2026" but receives HIL-related message instead of room availability.

**Root Cause:** The `_ensure_event_record()` function in `step1_handler.py` reuses existing events for the same email address. When an existing event had `offer_accepted: True` from a previous booking, new inquiries from the same client would:
1. Match to the old event via `last_event_for_email()`
2. Reuse the event with stale `offer_accepted: True` state
3. Step 4/5 sees `offer_accepted: True` and triggers HIL confirmation flow
4. Wrong response sent to client

**Fix Applied:**
Added `offer_accepted: True` as a terminal condition in `_ensure_event_record()`:
```python
if last_event.get("offer_accepted"):
    should_create_new = True
    trace_db_write(_thread_id(state), "Step1_Intake", "new_event_decision", {
        "reason": "offer_already_accepted",
        "event_id": last_event.get("event_id"),
    })
```
【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1267-L1275】

**Regression Guard:** Once an offer is accepted, any new inquiry from the same client should create a fresh event (even if booking the same date for a different purpose). Debug log should show `db.events.create` with reason `offer_already_accepted`, not `db.events.update`.

### Dev Test Mode - Continue/Reset Prompt for Testing (New Feature - 2025-12-22)
**Purpose:** Testing convenience feature for the development branch. When `DEV_TEST_MODE=1` is set, existing clients at advanced steps get a choice prompt instead of auto-continuing.

**How It Works:**
1. When a message comes in from a client with existing event at step > 1
2. Instead of auto-continuing, returns `action: "dev_choice_required"`
3. Frontend shows options: "Continue at Step X" or "Reset client (delete all data)"
4. User can call `/api/client/continue` or `/api/client/reset`

**Environment Variable:** Set `DEV_TEST_MODE=1` to enable (also set `ENABLE_DANGEROUS_ENDPOINTS=true`)

**Endpoints Added:**
- `POST /api/client/continue` - Continue workflow at current step (reprocesses message with `skip_dev_choice: true`)
- `POST /api/client/reset` - Delete all events/tasks for client (already existed)

**Files Modified:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Dev choice detection
- `backend/workflow_email.py` - Pass `skip_dev_choice` flag through state
- `backend/api/routes/clients.py` - Continue endpoint
- `backend/api/routes/messages.py` - Handle `dev_choice_required` action

**Note:** This feature is ONLY for the testing/frontend branch, not for production deployment.

### Subject Line Date Pollution in Change Detection (Fixed - 2025-12-25)
**Symptoms:** Client at Step 3 with confirmed date and locked room requests a capacity change (e.g., "Actually we're 50 now"). Instead of showing room availability for 50 people, the system asks for date confirmation ("Noted 08.02.2026. Preferred time?").

**Root Cause:** The `_message_text()` function in `step3_handler.py` was combining subject line + body for change detection. The API adds system-generated metadata to follow-up subjects like "Client follow-up (2025-12-24 21:07)". The timestamp in the subject triggered DATE change detection instead of REQUIREMENTS change detection.

**Fix Applied:**
Added `_strip_system_subject()` helper that removes system-generated metadata from subject lines before combining with body:
```python
def _strip_system_subject(subject: str) -> str:
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()
```
【F:backend/workflows/steps/step3_room_availability/trigger/step3_handler.py†L40-L60】

**Regression Guard:** Requirements changes at Step 3 should route to room availability (not Step 2 date confirmation). Test by: confirm date → lock room → send "Actually we're 50 now" → verify room options for 50 people appear (not "Preferred time?").

### Date Change Creating New Event Instead of Updating (Fixed - 2025-12-25)
**Symptoms:** Client at Step 4/5 requests date change (e.g., "Actually, can we change the date to 20.02.2026?"). Instead of updating the existing event and preserving capacity/room, the system creates a NEW event with blank requirements and asks for capacity again.

**Root Cause:** The `_ensure_event_record()` function compared dates: if `new_event_date != existing_event_date`, it set `should_create_new = True`. This didn't distinguish between a genuine NEW inquiry vs a DATE CHANGE request on an existing event.

**Fix Applied:**
Added check for revision signals before deciding to create new event:
```python
is_date_change_request = has_revision_signal(message_text)
if new_date_is_actual and existing_date_is_actual and new_event_date != existing_event_date:
    if is_date_change_request:
        # Date CHANGE on existing event - continue with existing
        pass
    else:
        # Genuine NEW inquiry - create new event
        should_create_new = True
```
【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1330-L1351】

**Regression Guard:** Date change requests (with "change", "switch", "actually", "instead" keywords) should preserve existing event data (participants, room lock, etc.). Test by: complete offer flow → send "change the date to X" → verify capacity/room are preserved for new date.

### Room Change Updating Lock Before Change Detection (Fixed - 2025-12-25)
**Symptoms:** Client at Step 4/5 requests room change (e.g., "Actually, can we switch to Room D instead?"). Instead of routing to Step 3 (room availability) to evaluate the new room, the system triggers Step 2 (date confirmation) and asks for time confirmation.

**Root Cause:** In `step1_handler.py`, when a room choice was selected, the code immediately updated `locked_room_id` to the new room. By the time `detect_change_type_enhanced()` ran, `user_info.room == locked_room_id`, so no ROOM change was detected. The system then detected something else (DATE from metadata) and caused a routing loop between Step 4 and Step 2.

**Fix Applied:**
Added check in `step1_handler.py` to NOT update `locked_room_id` if a different room is already locked:
```python
room_choice_selected = state.extras.pop("room_choice_selected", None)
if room_choice_selected:
    existing_lock = event_entry.get("locked_room_id")
    # If a different room is already locked, DON'T update the lock here.
    # Let the normal workflow continue so change detection can route to Step 3.
    if existing_lock and existing_lock != room_choice_selected:
        print(f"[Step1] Room change detected: {existing_lock} → {room_choice_selected}")
        # Don't return here - let normal flow continue with change detection
    else:
        # Normal room locking logic for first-time selection
        ...
```
【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1067-L1111】

Additionally, `step3_handler.py` was updated to recognize room changes detected via `ChangeType.ROOM` (not just `_room_choice_detected` flag):
```python
room_change_detected_flag = state.user_info.get("_room_choice_detected") or (change_type == ChangeType.ROOM)
```
【F:backend/workflows/steps/step3_room_availability/trigger/step3_handler.py†L334-L339】

**Regression Guard:** Room change requests should route to Step 3 (room availability) and show room options. Test by: complete offer flow with Room A → send "switch to Room D" → verify room availability options appear (not time confirmation).

### Date Change Clears Room Lock + Asks for Time (Fixed - 2025-12-25)
**Symptoms:** Client at Step 4/5 with locked room requests date change (e.g., "Actually, can we change to 20.02.2026?"). Instead of preserving Room A and checking its availability on the new date, the system:
1. Clears `locked_room_id` to null
2. Routes to Step 2 and asks "Preferred time?" instead of proceeding

**Root Cause:** Two separate bugs:
1. **Step 1 intake handler** (line 1177-1186): For DATE changes, it was clearing `locked_room_id` when routing to Step 2, but DATE changes should PRESERVE the room lock so Step 3 can fast-skip if room is still available.
2. **Step 2 handler** (line 1004-1029): When `window.partial` (date without time) and no time hint available, it always asked for time. But for detour cases (room already locked), time should be skipped and filled with defaults.

**Fix Applied:**
1. In `step1_handler.py`: For DATE changes to Step 2, only clear `room_eval_hash` but KEEP `locked_room_id`:
```python
if change_type.value == "date":
    # DATE change to Step 2: KEEP locked_room_id
    update_event_metadata(
        event_entry,
        date_confirmed=False,
        room_eval_hash=None,  # Invalidate for re-verification
        # NOTE: Do NOT clear locked_room_id for date changes
    )
```
【F:backend/workflows/steps/step1_intake/trigger/step1_handler.py†L1177-L1188】

2. In `step2_handler.py`: When room is locked, skip time confirmation and fill with default times:
```python
locked_room = event_entry.get("locked_room_id")
if locked_room:
    # Complete the window with default time and proceed
    default_start = time(14, 0)
    default_end = time(22, 0)
    start_iso, end_iso = build_window_iso(window.iso_date, default_start, default_end)
    window = ConfirmationWindow(...)  # with defaults
```
【F:backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py†L1009-L1027】

**Regression Guard:** Date change with locked room should preserve the room and skip time confirmation. Test by: complete offer flow with Room A → send "change date to X" → verify Room A availability shown on new date (not "Preferred time?" prompt).

### Intent Classification Edge Case - Event Types (Fixed)
**Symptoms:** Messages with event types like "Corporate Dinner" + participant counts were classified as `other` instead of `event_request`, resulting in fallback messages.

**Root Cause:** The `_heuristic_intent_override()` function only checked for narrow event keywords ("workshop", "conference", "meeting", "event") but missed common event types like "dinner", "party", "wedding", "reception", etc.

**Fix Applied:**
1. Added comprehensive `_EVENT_TYPE_TOKENS` tuple covering:
   - Food/catering types: dinner, lunch, breakfast, brunch, banquet, gala, cocktail, reception
   - Event formats: workshop, training, seminar, conference, meeting, presentation
   - Celebrations: wedding, birthday, party, anniversary, corporate/team event
   - German equivalents: abendessen, feier, hochzeit, veranstaltung, tagung, etc.
2. Added `_PARTICIPANT_TOKENS` tuple with EN+DE participant keywords
3. Updated heuristic to also detect numeric participant patterns ("25 guests")

**Files:** `backend/workflows/llm/adapter.py` lines 725-800

**Regression Guard:** Any message with event type + participant count should classify as `event_request`, not fall back to manual review.

---

## Bug Prevention Guidelines

### The "Billing Flow" Pattern
When implementing any special flow state (like billing capture, deposit waiting, site visit), ensure ALL code paths check for it:

**Checklist for any "special flow state":**
1. ✅ **Duplicate message detection** - Bypass for special flow
2. ✅ **Change detection** - Skip date/room/requirements detection
3. ✅ **Step routing** - Force correct step regardless of stored value
4. ✅ **Response key access** - Verify return value structure

**Code pattern (billing flow example):**
```python
in_billing_flow = (
    event_entry.get("offer_accepted")
    and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
)
```

### Common Circular Bug Patterns

**Pattern 1: Stored step gets corrupted**
- **Symptom:** Event at wrong step despite correct flow
- **Cause:** Previous flow set step incorrectly, new flow doesn't correct it
- **Solution:** Force correct step before routing loop

**Pattern 2: Change detection triggers on unrelated data**
- **Symptom:** Billing address triggers room change
- **Cause:** LLM extracts data that differs from stored values
- **Solution:** Skip change detection during special flows

**Pattern 3: Duplicate detection blocks valid messages**
- **Symptom:** Valid input blocked as "duplicate"
- **Cause:** Duplicate check doesn't account for special flows
- **Solution:** Bypass duplicate check during special flows

**Pattern 4: Response key mismatch**
- **Symptom:** KeyError when processing response
- **Cause:** Handler returns nested structure, caller expects flat
- **Solution:** Always verify return value structure with `.get()`

### Adding New Flow States

When adding a new flow state (like a new pre-confirmation gate), add guards to:

1. **`workflow_email.py`**
   - Duplicate message detection (lines ~970-1000)
   - Step correction before routing loop (lines ~1030-1042)

2. **`step1_handler.py`**
   - Change detection guards (lines ~1090-1105)
   - Date change guards (lines ~1156-1160)
   - Room change guards (lines ~1215-1222)

3. **Step handlers (step4/step5)**
   - Confirmation gate checks
   - Response key access with `.get()`

### Testing Special Flows

Always test with:
1. **Fresh event** - New inquiry through full flow
2. **Existing event** - Continue from mid-flow state
3. **Corrupted state** - Event with wrong step value
4. **Duplicate message** - Same message sent twice
5. **Change trigger** - Data that looks like a change request

---

## Test Suite Status

**Last Updated:** 2025-11-27

### Inventory Completed

A comprehensive test suite inventory was performed. See:
- `tests/TEST_INVENTORY.md` — Full listing of all test files with coverage, type, and status
- `tests/TEST_REORG_PLAN.md` — Proposed reorganization and migration actions

### Current State

| Location | Tests | Status |
|----------|-------|--------|
| `tests/specs/` | ~90 | 68 pass, 22 fail |
| `tests/workflows/` | ~75 | 67 pass, 8 fail |
| `tests/gatekeeping/` | 3 | all pass |
| `tests/flows/` | 10 | 5 pass, 5 fail |
| `tests/e2e_v4/` | 2 | all pass |
| `tests/_legacy/` | ~20 | xfail (v3 reference) |
| `backend/tests/smoke/` | 1 | pass |
| `backend/tests_integration/` | 4 | requires live env |

### Legacy Tests

Legacy v3 workflow tests are isolated in `tests/_legacy/` with:
- `pytest.mark.legacy` marker
- `xfail` expectation (retained for regression reference)
- No changes made; these are not run by default

### Failing Tests Requiring Attention

**Priority 1 — Change Propagation (Core v4)**
- `tests/specs/dag/test_change_propagation.py` (4 failures)
- `tests/specs/dag/test_change_scenarios_e2e.py` (5 failures)
- `tests/specs/dag/test_change_integration_e2e.py` (4 failures)

These test the v4 DAG-based change routing. The API may have evolved; expectations need alignment.

**Priority 2 — General Q&A Path**
- `tests/specs/date/test_general_room_qna_*.py` (7 failures)
- `tests/flows/test_flow_specs.py` (5 failures)

Q&A path expectations appear outdated; fixtures need update.

**Priority 3 — Minor**
- `tests/workflows/test_offer_product_operations.py` (1 failure) — quantity update logic
- `tests/workflows/qna/test_verbalizer.py` (1 failure) — fallback format
- `tests/workflows/date/test_confirmation_window_recovery.py` (1 failure) — relative date edge case

### Next Steps

1. **Fix change propagation tests** — These cover core v4 functionality (date/room/requirements detours)
2. **Update Q&A test expectations** — Align with current behavior
3. **Add missing coverage** — Steps 5-7 have limited unit tests
4. **Consolidate structure** — Consider merging `tests/workflows/` into `tests/specs/` per reorganization plan

### Running Tests

```bash
# Activate environment
source scripts/dev/oe_env.sh

# Run default v4 tests
pytest

# Run backend smoke test
pytest backend/tests/smoke/ -m ""

# Run with verbose output
pytest tests/specs/ -v --tb=short

# Run new detection/flow tests
pytest backend/tests/detection/ backend/tests/regression/ backend/tests/flow/ -m "" -v
```

---

## Detection & Flow Tests (New)

**Last Updated:** 2025-11-27

A comprehensive detection test suite was created to cover:
- Q&A detection
- Manager request detection
- Acceptance/confirmation detection
- Detour change propagation
- Shortcut capture
- Gatekeeping (billing + deposit)
- Happy-path flow Steps 1–4
- Regression tests linked to TEAM_GUIDE bugs

See `tests/TEST_MATRIX_detection_and_flow.md` for full test ID matrix.

### Test Locations

| Category | Location | Tests |
|----------|----------|-------|
| Q&A Detection | `backend/tests/detection/test_qna_detection.py` | DET_QNA_001–006 |
| Manager Request | `backend/tests/detection/test_manager_request.py` | DET_MGR_001–006 |
| Acceptance | `backend/tests/detection/test_acceptance.py` | DET_ACCEPT_001–009 |
| Detour Changes | `backend/tests/detection/test_detour_changes.py` | DET_DETOUR_* |
| Shortcuts | `backend/tests/detection/test_shortcuts.py` | DET_SHORT_001–006 |
| Gatekeeping | `backend/tests/detection/test_gatekeeping.py` | DET_GATE_BILL_*, DET_GATE_DEP_* |
| Happy Path Flow | `backend/tests/flow/test_happy_path_step1_to_4.py` | FLOW_1TO4_HAPPY_001 |
| Regression | `backend/tests/regression/test_team_guide_bugs.py` | REG_* |

### Test Results Summary

**Run Date:** 2025-11-27
**Results:** 161 passed, 0 failed

All detection and flow tests pass after the following fixes:

### Detection Logic Fixes (2025-11-27)

1. **Manager Request Detection — "real person" variant (DET_MGR_002)**
   - **Issue:** The phrase "I'd like to speak with a real person" wasn't caught by `_looks_like_manager_request`.
   - **Fix:** Added regex pattern `r"\b(speak|talk|chat)\s+(to|with)\s+(a\s+)?real\s+person\b"` to `_MANAGER_PATTERNS` in `backend/llm/intent_classifier.py:229`.
   - **Test:** `test_DET_MGR_002_real_person` now passes.

2. **Q&A Detection — Parking Policy (DET_QNA_006)**
   - **Issue:** The `parking_policy` Q&A type existed but its keywords didn't match "where can guests park?".
   - **Fix:** Added `" park"` (with leading space) and `"park?"` to the `parking_policy` keywords in `backend/llm/intent_classifier.py:157-158`.
   - **Test:** `test_DET_QNA_006_parking_question` now passes.

### Regression Tests Linked to TEAM_GUIDE Bugs

| Test ID | TEAM_GUIDE Bug | Status |
|---------|----------------|--------|
| `REG_PRODUCT_DUP_001` | Product Additions Causing Duplicates | ✓ Pass |
| `REG_ACCEPT_STUCK_001` | Offer Acceptance Stuck / Not Reaching HIL | ✓ Pass |
| `REG_HIL_DUP_001` | Duplicate HIL sends after offer acceptance | ✓ Pass |
| `REG_DATE_MONTH_001` | Spurious unavailable-date apologies | ✓ Pass |
| `REG_QUOTE_CONF_001` | Quoted confirmation triggering Q&A | ✓ Pass |
| `REG_ROOM_REPEAT_001` | Room choice repeats / manual-review detours | ✓ Pass |
| `REG_BILL_ROOM_001` | Room label as billing address | ✓ Pass |

### Anti-Fallback Assertions

All tests include guards against legacy fallback messages:
```python
FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
]
```

If any test response contains these patterns, it fails with `FALLBACK DETECTED`.

### Running Detection Tests

```bash
# Run all detection/flow tests (bypasses pytest.ini markers)
pytest backend/tests/detection/ backend/tests/regression/ backend/tests/flow/ -m "" -v

# Run specific category
pytest backend/tests/detection/test_acceptance.py -m "" -v

# Run regression tests only
pytest backend/tests/regression/ -m "" -v
```

---

## Safety Sandwich Pattern (LLM Verbalizer)

**Last Updated:** 2025-11-27

The Safety Sandwich pattern provides LLM-powered verbalization of room and offer messages while ensuring all hard facts (dates, prices, room names, participant counts) are preserved.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Safety Sandwich Flow                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Deterministic Engine ─┐                                        │
│   (builds facts bundle) │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  RoomOfferFacts                                          │   │
│   │  - event_date (DD.MM.YYYY)                              │   │
│   │  - participants_count                                    │   │
│   │  - rooms: [{name, status, capacity}]                    │   │
│   │  - menus: [{name, price}]                               │   │
│   │  - total_amount, deposit_amount                         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  LLM Verbalizer (verbalize_room_offer)                  │   │
│   │  - Rewords for empathetic, professional tone            │   │
│   │  - CANNOT alter dates, prices, room names               │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Deterministic Verifier (verify_output)                 │   │
│   │  - Extracts hard facts from LLM output                  │   │
│   │  - Checks: all canonical facts present?                 │   │
│   │  - Checks: any facts invented?                          │   │
│   │  - Returns: VerificationResult(ok, missing, invented)   │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│            ┌────────────┴────────────┐                          │
│            │                         │                          │
│       ok=True                   ok=False                        │
│            │                         │                          │
│            ▼                         ▼                          │
│   Return LLM text            Return fallback text               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/ux/verbalizer_payloads.py` | Facts bundle types (RoomFact, MenuFact, RoomOfferFacts) |
| `backend/ux/verbalizer_safety.py` | Deterministic verifier (extract_hard_facts, verify_output) |
| `backend/ux/safety_sandwich_wiring.py` | Workflow integration helpers |
| `backend/llm/verbalizer_agent.py` | LLM entry point (verbalize_room_offer) |

### Hard Facts (Must Be Preserved)

The verifier extracts and checks these fact types:

| Fact Type | Pattern | Example |
|-----------|---------|---------|
| Dates | `DD.MM.YYYY` | `15.03.2025` |
| Currency | `CHF X` or `CHF X.XX` | `CHF 500`, `CHF 92.50` |
| Room names | Case-insensitive match | `Room A`, `Punkt.Null` |
| Participant counts | Integer in "X participants" context | `30 participants` |
| Time strings | `HH:MM` or `HH:MM–HH:MM` | `14:00–18:00` |

### Verification Rules

1. **Missing Facts:** Every hard fact in the facts bundle MUST appear in LLM output
2. **Invented Facts:** LLM output MUST NOT contain dates/prices not in the bundle
3. **Order Preservation:** Section headers must appear in original order (if applicable)

### Tone Control

The verbalizer respects environment variables:

```bash
# Force plain (deterministic) tone
VERBALIZER_TONE=plain

# Enable empathetic LLM tone
VERBALIZER_TONE=empathetic
# or
EMPATHETIC_VERBALIZER=1
```

Default is `plain` (no LLM, deterministic text only).

### Workflow Integration Points

The Safety Sandwich is wired into:

1. **Step 3 (Room Availability):** `backend/workflows/steps/step3_room_availability/trigger/process.py:412-421`
2. **Step 4 (Offer):** `backend/workflows/steps/step4_offer/trigger/process.py:280-290`

### Tests

```bash
# Run Safety Sandwich tests
pytest backend/tests/verbalizer/ -m "" -v

# Test breakdown:
# - test_safety_sandwich_room_offer.py: 19 tests (facts extraction, verification)
# - test_safety_sandwich_wiring.py: 10 tests (workflow helpers)
```

### Test IDs

| Test ID | Description |
|---------|-------------|
| TEST_SANDWICH_001 | Happy path - valid paraphrase accepted |
| TEST_SANDWICH_002 | Changed price rejected |
| TEST_SANDWICH_003 | Invented date rejected |
| TEST_SANDWICH_004 | WorkflowState integration |
| TEST_SANDWICH_005 | Edge cases (empty, no rooms) |
| TEST_SANDWICH_006 | Hard facts extraction |

---

## Universal Verbalizer (Human-Like UX)

**Last Updated:** 2025-11-27

The Universal Verbalizer transforms ALL client-facing messages into warm, human-like communication that helps clients make decisions easily.

### Design Principles

1. **Sound like a helpful human** - Conversational language, not robotic bullet points
2. **Help clients decide** - Highlight best options with clear reasons, don't just list data
3. **Be concise but complete** - Every fact preserved, wrapped in helpful context
4. **Show empathy** - Acknowledge the client's needs and situation
5. **Guide next steps** - Make it clear what happens next

### Message Transformation Example

**BEFORE (data dump):**
```
Room A - Available - Capacity 50 - Coffee: ✓ - Projector: ✓
Room B - Option - Capacity 80 - Coffee: ✓ - Projector: ✗
```

**AFTER (human-like):**
```
Great news! Room A is available for your event on 15.03.2025 and fits your
30 guests perfectly. It has everything you asked for — the coffee service
and projector are both included.

If you'd like more space, Room B (capacity 80) is also open, though we'd
need to arrange the projector separately. I'd recommend Room A as your
best match.

Just let me know which you prefer, and I'll lock it in for you.
```

### Integration Points

The Universal Verbalizer is integrated at two levels:

1. **`append_footer()`** - Automatically verbalizes body before adding footer
2. **`verbalize_draft_body()`** - Explicit verbalization for messages without footer

### Key Files

| File | Purpose |
|------|---------|
| `backend/ux/universal_verbalizer.py` | Core verbalizer with UX-focused prompts |
| `backend/workflows/common/prompts.py` | Integration helpers (`append_footer`, `verbalize_draft_body`) |

### Tone Control

**Default is now `empathetic`** for human-like UX.

```bash
# Disable verbalization (use deterministic text only)
VERBALIZER_TONE=plain
# or
PLAIN_VERBALIZER=1

# Explicitly enable (this is now the default)
VERBALIZER_TONE=empathetic
```

For CI/testing, set `VERBALIZER_TONE=plain` to get deterministic output.

### Step-Specific Guidance

The verbalizer uses context-aware prompts for each workflow step:

| Step | Focus |
|------|-------|
| Step 2 (Date) | Help client choose confidently, highlight best-fit dates |
| Step 3 (Room) | Lead with recommendation, explain differences clearly |
| Step 4 (Offer) | Make value clear, justify totals, easy to accept |
| Step 5 (Negotiation) | Acknowledge decisions warmly, maintain momentum |
| Step 7 (Confirmation) | Celebrate their choice, make admin feel easy |

### Hard Rules (Never Broken)

Even in empathetic mode, these facts are ALWAYS preserved exactly:

- Dates (DD.MM.YYYY format)
- Prices (CHF X.XX format)
- Room names (case-insensitive match)
- Participant counts
- Time windows

If the LLM output fails verification, the system falls back to deterministic text.
