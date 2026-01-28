# AI Message Customization (Prompts Editor)

This feature allows event managers to customize how the AI communicates with clients - adjusting tone, style, and phrasing without affecting the underlying workflow logic.

## Quick Start for Managers

1. Navigate to `/admin/prompts` in your browser
2. Select a workflow step from the sidebar (e.g., "Date Confirmation")
3. Read the tips panel to understand what you can safely change
4. Edit the guidance text or click "Use this example" to start with a template
5. Click "Save Changes" - updates take effect within 30 seconds

## Feature Overview

### What It Does
- Adjusts tone and formatting of AI messages (formal vs friendly, short vs detailed)
- Per-step customization for each stage of the booking workflow
- Does NOT change what information is shown (dates, prices, rooms always appear correctly)

### What You Can Change Per Step

| Step | Example Changes |
|------|-----------------|
| **Date Confirmation** | How dates are presented, greeting style |
| **Room Availability** | How rooms are recommended and compared |
| **Offer** | How the quote is introduced and summarized |
| **Negotiation** | Tone for acceptance/decline responses |
| **Confirmation** | How final details are communicated |

### What Stays Fixed (Cannot Change)
- Actual dates, prices, and room names (always accurate)
- Which information is included (all relevant data appears)
- Workflow logic (what happens when client accepts, etc.)

## Safe Example Guidance

### Step 2: Date Confirmation
```
Keep it concise. Acknowledge the request in one line, then list dates as clear options. Ask directly which works best.
```

### Step 3: Room Availability
```
Lead with a clear recommendation and explain why it fits. Compare 1-2 alternatives briefly. End with a direct question.
```

### Step 4: Offer
```
Open with a short intro, summarize the offer in plain language. End with "Ready to confirm, or would you like to adjust anything?"
```

### Step 5: Negotiation
```
Acknowledge their decision in one sentence. Clearly state what happens next (manager review, deposit, etc.).
```

### Step 7: Confirmation
```
Celebrate briefly but professionally. List remaining admin steps in a calm, checklist-style format.
```

## Feature Flags

Enable both flags to activate the editor:

| Flag | Location | Purpose |
|------|----------|---------|
| `PROMPTS_EDITOR_ENABLED=true` | Backend env | Enables API endpoints |
| `NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED=true` | Frontend env | Enables UI |

If either flag is missing, the feature is disabled and endpoints return 404.

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config/prompts` | Get current prompts (merged with defaults) |
| POST | `/api/config/prompts` | Save new prompts |
| GET | `/api/config/prompts/history` | Get version history |
| POST | `/api/config/prompts/revert/{index}` | Restore a previous version |

### Example: Get Current Prompts
```bash
curl -s "${BACKEND_BASE}/api/config/prompts"
```

### Example: Save Prompts
```bash
curl -s -X POST "${BACKEND_BASE}/api/config/prompts" \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "Your global style guidance here...",
    "step_prompts": {
      "2": "Date confirmation guidance...",
      "3": "Room availability guidance...",
      "4": "Offer guidance...",
      "5": "Negotiation guidance...",
      "7": "Confirmation guidance..."
    }
  }'
```

## UI Features

The improved editor includes:

- **Contextual help panel** - Shows what's safe to change for each step
- **Example templates** - One-click to load a starting template
- **Character counter** - Warns if content is too short or long
- **Modified indicator** - Shows which prompts have unsaved changes
- **Reset button** - Restore to original without losing other changes
- **Version history** - View and restore previous configurations

## Technical Details

### How It Works

1. Manager edits guidance text in the UI
2. Backend stores overrides in `config.prompts` (DB or JSON file)
3. Universal verbalizer loads prompts with 30-second cache
4. LLM uses the guidance when generating client messages
5. Fact verification ensures dates/prices/rooms are never altered

### Affected Code Paths

- `ux/universal_verbalizer.py` - Loads and applies prompts
- `api/routes/config.py` - API endpoints
- Frontend: `app/admin/prompts/page.tsx`, `app/components/admin/PromptsEditor.tsx`

### NOT Affected

- Q&A responses (structured tables, INFO blocks)
- Safety-sandwich verbalizer (room/offer fact verification)
- Step handlers' deterministic copy
- Detection/extraction logic

## Persistence

- **Default**: Stored in JSON database file
- **Vercel**: Uses `/tmp/events_database.json` (ephemeral - may reset on redeploy)
- **Production**: Configure Supabase for durable storage

## Rollback Plan

If something goes wrong:

1. **Quick**: Use "Restore" in version history
2. **API**: `POST /api/config/prompts/revert/0` (restore most recent backup)
3. **Nuclear**: Delete `config.prompts` from database

## Checklist Before Enabling

- [ ] Both feature flags set in target environment
- [ ] Admin authentication guard added (if not already present)
- [ ] Tested version history and restore in staging
- [ ] Confirmed durable storage (if using Vercel)
- [ ] Manager briefed on safe vs unsafe changes
