 # Detection Interference Ideas (Not Implemented)

Status: ideas only. No code changes in this document.

Scope: highlight remaining detection conflicts (especially regex/keyword) and propose low-cost fixes. Preference is reuse of existing unified detection outputs to avoid extra LLM calls.

## Already implemented in this branch

These are fixes applied while investigating the issue (not ideas):

- OOC guard now requires intent evidence before blocking (date/accept/reject/counter), reducing false OOC on short confirmations.
- OOC guard bypasses when billing details are present (user_info, unified detection, or pre-filter billing signal).
- Step 4/5 confirmations are treated as in-context even when unified intent mislabels as `confirm_date`.
- Added regression tests for OOC confirmation bypass + explicit acceptance at wrong step:
  - `tests/specs/prelaunch/test_prelaunch_regressions.py`
  - `test_out_of_context_should_not_block_offer_confirmation`
  - `test_out_of_context_should_still_trigger_on_strong_acceptance`
- Files touched: `workflows/runtime/pre_route.py`, `tests/specs/prelaunch/test_prelaunch_regressions.py`

## Cost model (hybrid)

Source: `docs/internal/LLM_EXTRACTION_ARCHITECTURE.md`

- Intent LLM (Gemini): ~$0.00125 per call
- Entity LLM (Gemini): ~$0.002 per call
- Verbalization (OpenAI): ~$0.015 per call
- Estimated cost per event: ~$0.08 (hybrid)

Notes:
- Unified detection is already called once per inbound message in `DETECTION_MODE=unified`.
- If we only consume the existing unified detection output, delta cost is ~$0.00.
- If we add a new LLM call, delta per event is:
  - `extra_calls_per_event * cost_per_call`
  - Example: +1 call on each of 10 client messages
    - Gemini intent-style: +$0.0125 per event
    - Gemini entity-style: +$0.02 per event

## Weaknesses and ideas

### 1) Step1 offer acceptance can misfire on room confirmation (non-LLM)

- Current detection: `looks_like_offer_acceptance()` in `workflows/steps/step1_intake/trigger/gate_confirmation.py`
- Risk: "Room A sounds good" can be interpreted as offer acceptance and jump to Step 5 HIL.
- Idea (no cost):
  - Require context: `current_step >= 4` AND `event_entry.current_offer_id` present.
  - Require acceptance evidence from unified detection (`is_acceptance`) or pre-filter acceptance signal.
  - Reject if message contains room selection tokens without explicit offer language.
- Optional LLM upgrade (higher cost):
  - Add a dedicated acceptance classifier call for step >= 3 messages.
  - Cost impact: +$0.00125 per call (Gemini intent) per applicable message.

### 2) Step1 room choice detection can treat questions as selections (non-LLM)

- Current detection: `detect_room_choice()` in `workflows/steps/step1_intake/trigger/room_detection.py`
- Risk: "Is Room A available?" auto-locks a room and skips availability step.
- Idea (no cost):
  - Add a question guard ("?" or unified `is_question`) before accepting room choice.
  - Require confirmation signal (pre-filter confirmation or unified `is_confirmation`).
- Optional LLM upgrade (higher cost):
  - Use unified detection `room_preference` + `is_question` to disambiguate. This is already available, so no extra calls.

### 3) Step1 regex date fallback uses quoted history (non-LLM)

- Current detection: regex date fallback in `workflows/steps/step1_intake/trigger/step1_handler.py`
- Risk: quoted email history containing a date can trigger date confirmation or smart shortcut.
- Idea (no cost):
  - Strip quoted lines before regex date parsing.
  - Reuse existing quote normalization helper if available.

### 4) Smart shortcuts parse quoted history (non-LLM)

- Current detection: planner parsing in `workflows/planner/smart_shortcuts.py` and `workflows/planner/date_handler.py`
- Risk: quoted dates/rooms cause unintended shortcut routing.
- Idea (no cost):
  - Normalize or strip quoted sections before planner intent parsing.
  - Require explicit action verbs to activate shortcuts.

### 5) Step7 confirm vs site-visit ordering (non-LLM)

- Current detection: keyword order in `workflows/steps/step7_confirmation/trigger/classification.py`
- Risk: "Yes, can we visit next week?" can be treated as confirm instead of site visit.
- Idea (no cost):
  - Prioritize site-visit intent when `site_visit_state.status == proposed`.
  - If unified detection `qna_types` contains `site_visit_request`, route to site visit before confirm.

### 6) Acceptance regex is permissive (non-LLM)

- Current detection: `matches_acceptance_pattern()` in `detection/response/matchers.py`
- Risk: standalone words like "good" or "great" can be interpreted as offer acceptance.
- Idea (no cost):
  - Remove standalone tokens and require an offer-related phrase ("offer", "proposal", "price").
  - Or require unified `is_acceptance` before accepting regex match.

### 7) General Q&A heuristics override LLM (hybrid, heuristic-dominant)

- Current detection: `detect_general_room_query()` in `detection/qna/general_qna.py`
- Risk: heuristic `is_general` is OR-ed with LLM result, so heuristics can cause false positives even when LLM says not general.
- Idea (no cost):
  - Allow LLM to veto borderline heuristic matches (LLM only when heuristics are weak).
  - This can reduce false positives without adding calls.
- Optional LLM upgrade (higher cost):
  - Always use LLM for Q&A classification.
  - Cost impact depends on provider; current classifier uses OpenAI (model cost not documented here).

### 8) Product add/remove keyword collisions (non-LLM)

- Current detection: `PRODUCT_ADD_KEYWORDS` / `PRODUCT_REMOVE_KEYWORDS` in `workflows/steps/step1_intake/trigger/keyword_matching.py`
- Risk: "include" or "no" can match in unrelated contexts and trigger product updates.
- Idea (no cost):
  - Require add/remove verbs within a tight window around a known product token.
  - Gate with unified entity extraction: only apply when `products_add` or `products_remove` is present.

## Cost impact summary (delta per event)

- Reusing unified detection outputs: ~+$0.00
- Adding a new intent-style LLM call per client message:
  - +$0.00125 per message (Gemini intent)
  - Example (10 client messages): +$0.0125 per event
- Adding a new entity-style LLM call per client message:
  - +$0.002 per message (Gemini entity)
  - Example (10 client messages): +$0.02 per event
- General Q&A LLM classifier cost: depends on OpenAI model and tokens (not documented in repo)

## Recommendation (lowest cost, highest robustness)

1) Keep regex for extraction, but gate high-impact routing with unified detection outputs already produced.
2) Normalize/strip quoted history before any regex-driven routing (date, room, shortcut).
3) Tighten acceptance detection to require offer context rather than generic praise.
4) Adjust Step7 site-visit precedence without adding any LLM call.
