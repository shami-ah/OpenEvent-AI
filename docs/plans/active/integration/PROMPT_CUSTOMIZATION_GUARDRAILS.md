# Prompt Customization Guardrails

## Overview

This document defines the safety boundaries for the AI message customization feature. The goal is to let non-technical event managers adjust AI communication style without breaking workflow functionality or data accuracy.

## The Golden Rule

**Prompts control HOW the AI says things, not WHAT it says.**

- Dates, prices, and room names are always injected from the system
- Fact verification catches any LLM attempts to alter or invent data
- Workflow logic (step progression, gating, routing) is unaffected

## What Managers CAN Safely Change

### Per-Step Customization

| Step | Safe to Change | Example |
|------|---------------|---------|
| **Step 2: Date Confirmation** | Greeting style, how options are listed, question phrasing | "List dates briefly, ask which works best" |
| **Step 3: Room Availability** | Recommendation wording, comparison style, call-to-action | "Lead with a clear recommendation, explain why" |
| **Step 4: Offer** | Intro framing, value summary tone, confirmation question | "Keep it simple, end with 'Ready to confirm?'" |
| **Step 5: Negotiation** | Acceptance/decline tone, how next steps are communicated | "Acknowledge briefly, state next step clearly" |
| **Step 7: Confirmation** | Celebration tone, how admin details are requested | "Celebrate briefly, list steps calmly" |

### Global Style (System Prompt)

- Communication style (formal vs friendly)
- Paragraph length preferences
- Banned words or phrases ("Amazing!", "Delve", etc.)
- Formatting preferences (bold usage, bullet points)

## What Managers CANNOT Change

These are protected by system design:

1. **Hard Facts** - Dates, prices, room names, participant counts
2. **Product Units** - "per person" vs "per event" (verified by fact checker)
3. **Workflow Logic** - Step progression, gating, routing decisions
4. **Detection/Extraction** - How client messages are interpreted
5. **Structured Content** - Q&A tables, INFO blocks, NEXT STEP markers

## Technical Safeguards

### Fact Verification (`_verify_facts`)

After every LLM verbalization:
1. All dates from context must appear in output
2. All prices must appear with correct amounts
3. All room names must appear
4. Product units cannot be swapped
5. Invented dates/amounts are detected and rejected

### Prompt Isolation

The customizable prompts only affect:
- `ux/universal_verbalizer.py` → `_build_prompt()`
- Messages going through `verbalize_message()` or `verbalize_step_message()`

They do NOT affect:
- `workflows/qna/verbalizer.py` - Structured Q&A
- `llm/verbalizer_agent.py` - Safety sandwich
- `detection/*` - Intent/entity extraction
- `workflows/steps/**/trigger/*.py` - Step handler logic

### Cache TTL

Prompts are cached for 30 seconds. Changes take effect within this window without requiring a restart.

## Example Safe Guidance

### Step 2: Date Confirmation
```
Keep it concise. Acknowledge the request in one line, then list dates as
clear options. Ask directly which works best.
```

### Step 3: Room Availability
```
Lead with a clear recommendation and explain why it fits. Compare 1-2
alternatives briefly. End with a direct question.
```

### Step 4: Offer
```
Open with a short intro, summarize the offer in plain language.
End with "Ready to confirm, or would you like to adjust anything?"
```

### Step 5: Negotiation
```
Acknowledge their decision in one sentence. Clearly state what happens
next (manager review, deposit, etc.).
```

### Step 7: Confirmation
```
Celebrate briefly but professionally. List remaining admin steps in a
calm, checklist-style format.
```

## Example UNSAFE Guidance (Don't Do This)

```
❌ BAD: "Always show the cheapest option first"
   (Changes what information is shown)

❌ BAD: "Round all prices to the nearest hundred"
   (Alters factual data)

❌ BAD: "If the client seems uncertain, suggest a site visit"
   (Adds conditional logic the AI shouldn't control)

❌ BAD: "Don't mention the deposit requirement"
   (Removes required information)
```

## Risk Checklist (Before Enabling)

- [ ] Both feature flags enabled (`PROMPTS_EDITOR_ENABLED`, `NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED`)
- [ ] Admin authentication guard in place
- [ ] Version history tested in staging
- [ ] Durable storage confirmed (not just `/tmp` on Vercel)
- [ ] Manager understands safe vs unsafe changes

## Rollback

If AI responses become problematic:

1. **UI**: Click "Restore" on a previous version in history
2. **API**: `POST /api/config/prompts/revert/0`
3. **Emergency**: Delete `config.prompts` from database

## Implementation Files

| File | Purpose |
|------|---------|
| `ux/universal_verbalizer.py` | Loads prompts, applies to verbalization |
| `api/routes/config.py` | API endpoints for CRUD |
| `PromptsEditor.tsx` | Frontend editor UI |
| `page.tsx` (admin/prompts) | Page wrapper with feature flag check |

## Future Considerations

- **Preview feature**: Show sample output before saving
- **A/B testing**: Compare different prompt styles
- **Per-client customization**: Different tones for different client types
- **Analytics**: Track which prompts perform best
