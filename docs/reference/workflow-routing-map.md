# Workflow Routing Map (current backend code)

> **ARCHITECTURAL SOURCE OF TRUTH:** For behavioral rules, invariants (Confirm-Anytime, Capture-Anytime), and the "Law" of the system, refer to **`docs/architecture/MASTER_ARCHITECTURE_SHEET.md`**.
> Use *this* file (`workflow-routing-map.md`) as a practical debugging map for "where does the code go right now".

Purpose
- Provide a practical “where does this message go?” map for debugging routing bugs.
- Document what the code does today (not the desired architecture).

Core entrypoint
- `backend/workflow_email.py::process_msg()` is the single orchestration function:
  - Loads DB → Step1 intake → pre-route pipeline → routing loop → finalize output.

## State fields that control routing (the ones to print first)

Event state (`state.event_entry`)
- `current_step` (2–7) — which step handler the router will dispatch next.
- `caller_step` — detour return target; indicates “we temporarily jumped back”.
- `thread_state` — UX/ops state (Awaiting Client, Waiting on HIL, etc.).
- Step2/date: `chosen_date`, `date_confirmed`, `requested_window.{start,end,tz,hash}`
- Step3/room: `locked_room_id`, `room_eval_hash`
- Requirements: `requirements`, `requirements_hash`
- Offer: `offer_status`, `offer_hash`, `offer_gate_ready`
- Billing flow gate: `billing_requirements.awaiting_billing_for_accept`
- Deposit: `deposit_state`, `deposit_info` (schema drift exists)
- Site visit: `site_visit_state`

Per-message state (`state.user_info`, `state.extras`)
- `state.user_info`: extracted entities (date, room, participants, billing, etc.)
- `state.extras["unified_detection"]`: unified detection output dict (if enabled)
- `state.extras["pre_filter"]`: regex signals

## End-to-end pipeline (high level)

```mermaid
flowchart TD
  A[process_msg: load_db + state init] --> B[Step1 intake: step1_intake.process]
  B --> C[Pre-route pipeline: run_pre_route_pipeline]
  C -->|early return| Z[Finalize + return]
  C --> D[Router loop: run_routing_loop]
  D -->|halted| Z
  D -->|loop complete| E[Empty reply guard (Step3-5 only)]
  E --> Z
```

## Step 1 (Intake) routing effects

Where Step1 mutates routing-relevant state
- Creates or reuses an event record (`last_event_for_email`, `_ensure_event_record`).
- Sets/updates `requirements` + `requirements_hash` from extracted user info.
- May set `current_step` directly in special cases (e.g., early room-choice capture path).
- Runs change detection and can detour via `detect_change_type_enhanced` + `route_change_on_updated_variable`.
- Legacy fallback still exists: a differing extracted `event_date` can trigger a detour to Step2 even without revision signals (this is a known risk; see `docs/workflow-generalization-review.md`).

What Step1 does NOT do (today)
- It does not run the pre-route “out-of-context” logic (that happens after Step1).
- It does not run smart shortcuts (pre-route does).

## Pre-route pipeline (runs after Step1, before router)

Location: `backend/workflows/runtime/pre_route.py::run_pre_route_pipeline()`

Order matters (this is the actual order)
1) Unified pre-filter + LLM detection (`run_unified_pre_filter`)
2) Manager escalation handling (`handle_manager_escalation`) → creates HIL task, halts
3) Out-of-context filter (`check_out_of_context`) → may halt with `out_of_context_ignored`
4) Duplicate detection (`check_duplicate_message`) → may halt with `duplicate_message`
5) If intake already halted → finalize/return
6) Guards (`evaluate_pre_route_guards`) — only steps 2–4 are guarded; deposit bypass can force Step5
7) Smart shortcuts (`maybe_run_smart_shortcuts`) — can mutate state and either halt or continue
8) Billing flow step correction (`correct_billing_flow_step`) — forces Step5 when billing flow active

### Out-of-context (OOC) rules (current code)

Location: `backend/workflows/runtime/pre_route.py::is_out_of_context()`

Key idea in code today
- A detected intent can be treated as invalid for the current step and the whole message is silently ignored.

Static map (hardcoded)
- `INTENT_VALID_STEPS`:
  - `confirm_date`, `confirm_date_partial` → step 2 only
  - `accept_offer`, `decline_offer`, `counter_offer` → steps 4–5 only
- `ALWAYS_VALID_INTENTS`: change intents, manager request, general_qna, etc.

Debug consequence
- If unified detection misclassifies “Room B sounds perfect” as `confirm_date` at step 4/5/7, the message can be dropped *before* routing/shortcuts/capture.

Planned mitigation (recommended)
- Add a gate-aware confirmation arbiter that runs before OOC:
  - Treat confirmation as one generic signal (not separate `confirm_date` / `accept_offer` / etc.).
  - Resolve the confirmation target from gate state + entities:
    - room pending + “Room B” → room confirmation (Step3 owner)
    - offer pending + “sounds good / proceed” → offer acceptance (Step4/5 owner)
    - date pending + date/time mentioned → date confirmation (Step2 owner)
  - If the target gate is already verified → NO-OP (do not drop the message; keep processing capture/QnA).
- Details: see `docs/workflow-generalization-review.md` (“Unified confirmation handler” + “Prevent Out-of-Context From Overriding Confirmations” plan).

## Router loop (Steps 2–7)

Location: `backend/workflows/runtime/router.py::run_routing_loop()`

Core rules
- Loops up to `max_iterations=6`.
- Dispatch table:
  - Step2: `backend/workflows/steps/step2_date_confirmation.process`
  - Step3: `backend/workflows/steps/step3_room_availability.process`
  - Step4: `backend/workflows/steps/step4_offer.trigger.process`
  - Step5: `backend/workflows/steps/step5_negotiation.process`
  - Step6: `backend/workflows/steps/step6_transition.process`
  - Step7: `backend/workflows/steps/step7_confirmation.trigger.process`

Special intercept that runs at ANY step (2–7)
- Site visit intercept:
  - If `is_site_visit_active(event_entry)` OR `is_site_visit_intent(detection)` → `handle_site_visit_request(...)`
  - Can halt (reply) or continue.

## Deterministic guard forcing (Steps 2–4)

Location: `backend/workflow/guards.py::evaluate()`

Guard outcomes
- If Step2 required → force `current_step=2`
- Else if Step3 required → force `current_step=3`
- Else if Step4 required → force `current_step=4`

Important limitations (today)
- Guards do not enforce Step5/6/7 readiness.
- Billing flow bypass: when `billing_requirements.awaiting_billing_for_accept=True`, guard forcing is skipped.
- Deposit bypass: `deposit_just_paid` can force Step5.

## Change-propagation routing matrix (DAG detours)

Location: `backend/workflows/change_propagation.py::route_change_on_updated_variable()`

```text
DATE          -> Step 2   (and Step 3 may run after Step 2)
ROOM          -> Step 3
REQUIREMENTS  -> Step 3   (or fast-skip back to caller if hashes match)
PRODUCTS      -> Step 4   (products mini-flow)
COMMERCIAL    -> Step 5
DEPOSIT       -> Step 7
SITE_VISIT    -> Step 7
CLIENT_INFO   -> stay on current_step
```

Where it’s used today
- Step1, Step3, Step4 use enhanced change detection + this routing.
- Step5 and Step7 have their own structural change detectors (separate logic).

## HIL task creation and action routing (current code)

Location: `backend/workflow_email.py::_finalize_output()` + `backend/workflows/runtime/hil_tasks.py::enqueue_hil_tasks()`

How HIL tasks are created today
- Any step can add `state.draft_messages`.
- `_finalize_output` calls `enqueue_hil_tasks(state, event_entry)` if drafts exist.
- `enqueue_hil_tasks` only creates tasks for step numbers `{2,3,4,5}` (Step6/7 are currently skipped).

Debug consequence
- Step6/7 can set `requires_approval=True` but still produce no task/action for HIL review.
- Multi-tenancy (`TENANT_HEADER_ENABLED=1`) currently breaks approvals:
  - `GET /api/tasks/pending` is tenant-aware (uses `backend.workflow_email.load_db()` → `events_{team_id}.json`).
  - `POST /api/tasks/{id}/approve` / `reject` call `approve_task_and_send()` / `reject_task_and_send()` which default to `events_database.json` unless a tenant-aware `db_path` is passed.
  - Frontend approvals also omit tenant headers in `atelier-ai-frontend/app/page.tsx::handleTaskAction`, so even after backend fixes, headers must be included.

## “Why did the router go there?” debugging checklist

1) Inspect event routing fields
- `current_step`, `caller_step`, `thread_state`, plus `audit[-5:]`

2) Check pre-route early exits
- `action == out_of_context_ignored` → unified intent mismatch with `INTENT_VALID_STEPS`
- `action == duplicate_message` → message identical to previous
- `action == manager_escalation` → unified `is_manager_request=True`

3) Check guards and forced-step decisions
- For step regressions to 2/3/4, verify:
  - `date_confirmed`, `locked_room_id`, `requirements_hash` vs `room_eval_hash`, `offer_status`

4) Check step-local detours
- Step5 / Step7 structural change detection can override DAG rules.

5) Confirm whether shortcuts fired
- Look for `action == smart_shortcut_processed` or trace subloop `shortcut`.

Related docs
- Known high-risk routing bugs + regression probes: `docs/workflow-generalization-review.md`
