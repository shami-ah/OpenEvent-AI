# Workflow Test Requirements (Logic Only)

This checklist captures production logic behavior for the OpenEvent-AI workflow.
It focuses on functional workflow rules, not security or infra concerns.

## Scope and configuration
- Hybrid mode only: OpenAI for verbalization, Google (Gemini) for extraction/classification.
- No stub provider usage; no implicit provider fallbacks should fire during tests.
- Deterministic engine remains the source of truth; agent layer only affects tone.

## Core workflow invariants
- Workflow never stalls or loops; each turn produces a valid next action or explicit wait state.
- Step progression follows the state machine (Steps 1-7) unless a detour is required.
- Change detection runs before Q&A in every step that supports detours.
- Sequential messages are handled in order; back-to-back detections do not interfere.
- Safety sandwich: LLM outputs are verified against deterministic facts; no hallucinated rooms, prices, or availability.

## Detours and change propagation
- Any confirmed variable can be changed (date, room, requirements, products, commercial terms, deposit, site visit).
- Detours only affect dependent steps according to the DAG; unaffected steps are preserved.
- Caller context (`caller_step`) is set on detour and cleared once the caller regains control.
- Hash guards prevent redundant re-evaluation; when hashes match, the workflow skips unnecessary steps.
- Detours return the client to the exact point they left off, repeating only required steps.
- Detour paths always return a draft or explicit wait response; never silent or empty replies.

## Q&A and shortcut behavior
- General Q&A is available from every step.
- Q&A never mutates workflow state; it uses catalog helpers and deterministic facts.
- Q&A responses include an info link and a clear resume prompt (e.g., "Proceed with <Step>?").
- Two Q&A turns in a row work reliably and can be exited by normal workflow input.
- If a client confirms the current step and asks a general question, answer Q&A first and then resume.
- Shortcut confirmations (multiple gates in one message) set all gate flags and still respect HIL.
- Vague date requests never shortcut to room availability; Step 2 must confirm a concrete date first.

## Verbalization and UX rules
- Every client-facing message routes through the verbalizer (variant but consistent output).
- Messages use readable sections, highlight markdown, and newlines; no LLM "smell".
- No markdown tables or long data blocks in chat/email body.
- Responses summarize and address the client directly; details live behind info links.
- Info links are always present for Q&A and data-heavy responses.

## Detection and classification
- Intent detection, change detection, and Q&A detection work in succession without conflicts.
- Sequential workflow requests (confirm Step N and ask for Step N+1) are treated as normal progression, not Q&A.
- Quoted text in email replies must not trigger false Q&A routing or detours.

## Room matching and availability
- Client preferences are extracted and used for room ranking and matching.
- Room ranking highlights matched vs missing requirements (in debug and client draft).
- If no rooms are available, the agent proactively asks to adjust criteria.
- Explicit room nominations enforce capacity/layout constraints; alternatives are provided when invalid.

## Offers, billing, and confirmation
- Offer drafts are versioned; newer offers supersede older drafts.
- Step 5 counters are limited; exceeding the limit escalates to HIL and holds the step.
- Transition checks (Step 6) only advance when all blockers are resolved.
- Confirmation flow manages deposit and site visit subflows without detouring incorrectly.

## HIL behavior
- HIL tasks are created for step-specific gates (offer send, special requests, too many attempts, confirmations).
- Optional "approve all AI replies" HIL toggle, when enabled, adds a separate approval task.
- HIL tasks appear in the frontend manager queue and are also sent via the API to the manager email.
- Step 3 must never create HIL tasks; its drafts are always `requires_approval=false`.
- No duplicate HIL tasks for the same thread/action.

## Database and persistence
- DB creates/updates/deletes/additions succeed and are reflected in subsequent steps.
- Event status transitions are consistent (Lead -> Option -> Confirmed), with cancellations tracked.
- Requirements, room locks, hashes, and audit entries persist correctly across detours.
- Q&A does not mutate DB state.

## Fallbacks and error handling
- No fallback or silent fallback messages are emitted during test runs.
- Missing LLM access or extraction failures must be treated as test failures (not hidden by fallback).
- Out-of-context or nonsense client messages do not advance workflow state and do not produce a client reply (only HIL/manual review if required).
