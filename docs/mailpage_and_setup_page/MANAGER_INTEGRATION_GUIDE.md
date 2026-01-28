# Email Workflow Integration Guide - Manager Edition

**Last Updated:** 2025-12-08
**Audience:** CO / Manager
**Purpose:** What you need to do to prepare for email workflow integration

---

# SCOPE DECISIONS: What's In YOUR MVP?

The lists below show what's **required** for launch vs what **can wait**. However, you may want to include some "LATER" items in your MVP. Use this section to decide.

## Optional Features - Include in MVP?

Check the items you want included in the initial launch:

| Feature | Default | Include in MVP? | Notes |
|---------|---------|-----------------|-------|
| **Site visit scheduling** | LATER | ☐ Yes / ☐ No | Track venue tour requests. Can use tasks/notes instead. |
| **Seating layout field** | LATER | ☐ Yes / ☐ No | Capture in notes field if not included. |
| **Preferred room field** | LATER | ☐ Yes / ☐ No | Capture in notes field if not included. |
| **Client preference history** | LATER | ☐ Yes / ☐ No | Enables personalization. Nice-to-have. |
| **Mail thread view** | LATER | ☐ Yes / ☐ No | Frontend enhancement for conversation view. |
| **HIL approval buttons** | LATER | ☐ Yes / ☐ No | Accept/Reject in mail thread for workflow decisions. |
| **Workflow step indicator** | LATER | ☐ Yes / ☐ No | Shows progress in event detail. |
| **Deposit status badge** | LATER | ☐ Yes / ☐ No | Quick visual for paid/pending. |
| **Room rules editor** | LATER | ☐ Yes / ☐ No | Custom rules for room selection logic. |
| **Workflow prompt editor** | LATER | ☐ Yes / ☐ No | Customize LLM tone and responses. |
| **Custom links in emails** | LATER | ☐ Yes / ☐ No | Add links to room pages, etc. in workflow emails. |
| **Info pages for clients** | LATER | ☐ Yes / ☐ No | Data transparency pages showing LLM reasoning. |

**Note:** If you check "Yes" for any item, that item moves to the MVP checklist and implementation phases below.

---

# QUICK START: What Can You Do RIGHT NOW?

While the email workflow is being developed, you can already:

| Task | Where | Time | Impact |
|------|-------|------|--------|
| 1. Add deposit settings to rooms | Supabase | 15 min | Enables deposit calculation |
| 2. Fill in room capacities | Supabase | 15 min | Enables room matching |
| 3. Review your product catalog | Supabase | 30 min | Ensures products ready for offers |
| 4. Make 4 decisions (see Part 3) | This doc | 15 min | Unblocks development |

**Do these first** - they don't depend on anything else and help integration go smoothly.

---

# PART 1: MVP vs LATER

## What's MVP (Must Have for Launch)

| Item | Type | Why Critical |
|------|------|--------------|
| Deposit settings on rooms | Supabase | Workflow calculates deposits from this |
| Workflow state storage decision | Decision | Affects database design |
| Mail thread UX decision | Decision | Frontend team needs this |
| System user + team_id config | Config | Workflow needs identity to operate |

## What's LATER (Can Add After Launch)

| Item | Type | Why Deferred |
|------|------|--------------|
| Client preference history | Supabase + Frontend | Nice for personalization, not blocking |
| Site visits table | Supabase | Feature can be added incrementally |
| Seating layout field | Supabase | Can capture in notes for now |
| Client status auto-update | Logic | Current manual approach works |
| Analytics dashboard | Frontend | Post-launch optimization |

---

# PART 2: ALL CHANGES NEEDED

## 2A. SUPABASE CHANGES

### MVP: Add to `rooms` table

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `deposit_required` | boolean | false | Does this room require deposit? |
| `deposit_percent` | integer | null | What percentage (e.g., 30 = 30%) |

**How to add:**
1. Supabase Dashboard → Table Editor → `rooms`
2. Click "New Column"
3. Add `deposit_required`: type `bool`, default `false`
4. Add `deposit_percent`: type `int4`, nullable

**Then fill in values:**
| Room | deposit_required | deposit_percent |
|------|------------------|-----------------|
| Large Event Hall | true | 30 |
| Meeting Room A | false | null |
| Rooftop Terrace | true | 50 |

---

### MVP (if Option A chosen): Add to `events` table

Only if you choose Option A for workflow state storage:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `current_step` | integer | 1 | Workflow step (1-7) |
| `date_confirmed` | boolean | false | Is event date locked? |

**Optional performance columns:**
| Column | Type | Purpose |
|--------|------|---------|
| `caller_step` | integer | For workflow detours |
| `requirements_hash` | text | Caching optimization |
| `room_eval_hash` | text | Caching optimization |
| `offer_hash` | text | Caching optimization |

---

### LATER: Add to `events` table

| Column | Type | Purpose |
|--------|------|---------|
| `seating_layout` | text | Theatre, U-shape, etc. |
| `preferred_room` | text | Client's stated preference |

*Can skip for MVP - workflow can put this info in `notes` field instead.*

---

### LATER: Create `site_visits` table

For venue tour scheduling:

```sql
CREATE TABLE site_visits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    user_id UUID NOT NULL,
    status TEXT DEFAULT 'idle',
    requested_date DATE,
    confirmed_date DATE,
    confirmed_time TIME,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Future enhancement:** Site visits will work similarly to deposits:
- **Phase 1:** Global setting (e.g., "all rooms require site visit for 50+ people")
- **Phase 2:** Per-room override (e.g., "Rooftop always requires site visit")

*Can skip for MVP - site visits can be tracked via tasks or notes. If you want this in MVP, check "Yes" in the Scope Decisions section above.*

---

### LATER: Create `client_preference_history` table

For tracking client preferences over time:

```sql
CREATE TABLE client_preference_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id),
    team_id UUID REFERENCES teams(id),
    extracted_at TIMESTAMP DEFAULT NOW(),
    preferences JSONB NOT NULL,
    source_email_id UUID REFERENCES emails(id),
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Example preferences stored:**
```json
{
  "language": "de",
  "typical_event_size": "50-100",
  "preferred_room_type": "large with natural light",
  "dietary_notes": "vegetarian options",
  "parking_required": true
}
```

*Can skip for MVP - personalization is a future feature.*

---

## 2B. FRONTEND CHANGES

### MVP: No Frontend Changes Required

The existing frontend already has everything needed:
- Events can be created/viewed
- Clients can be managed
- Offers can be generated
- Tasks work for HIL (human-in-loop) approvals

### LATER: Frontend Additions

| Feature | Where | Purpose |
|---------|-------|---------|
| **Mail thread view** | Inbox page | Show conversations grouped by client or event |
| **HIL approval buttons** | Mail thread | Accept/Reject buttons for workflow decisions |
| **Workflow step indicator** | Event detail | Show "Step 3 of 7: Room Selection" |
| **Site visit scheduling** | Event detail | Book venue tours |
| **Preference history view** | Client detail | Show extracted preferences over time |
| **Deposit status badge** | Offers list | Quick view of deposit paid/pending |
| **Room rules editor** | Setup/Rooms | Custom rules for room selection logic |
| **Workflow prompt editor** | Setup/Knowledge | Customize LLM behavior for your clients |
| **Custom link manager** | Setup/Knowledge | Add links to include in workflow emails |
| **Info page viewer** | Public pages | Data transparency pages for clients |

**Mail Thread View (Priority for LATER):**
- Group emails by `client_id` or `event_id`
- Show conversation thread
- Allow continuing conversation
- Display workflow status
- **HIL Decisions:** Show Accept/Reject buttons when workflow needs manager approval

**Manager Customization Features (LATER):**
- **Room Rules:** Add custom rules for room selection (e.g., "Always suggest Room A for corporate events over 50 people")
- **Prompt Customization:** Modify how the LLM responds to match your venue's tone and style
- **Custom Links:** Add links to emails (e.g., link to your website's room detail page during availability step)

**Info Pages for Clients (LATER):**

The workflow sends concise email responses, but clients may want more detail. Info pages solve this:

| Page Type | Content | Example Use |
|-----------|---------|-------------|
| **Room recommendations** | All rooms evaluated, why each was/wasn't recommended | "See all available rooms" link |
| **Q&A detail** | Full answers to common questions | "Learn more about parking" link |
| **Offer breakdown** | Detailed pricing, what's included | "View full offer details" link |
| **Availability calendar** | Visual room availability | "Check other dates" link |

**How it works:**
1. Workflow generates detailed data (e.g., room evaluations with scores and reasoning)
2. Data is stored in `page_snapshots` table
3. Client receives email with link: `yourdomain.com/info/abc123`
4. Link shows the full data the LLM used to make its recommendation
5. **Links do NOT expire** - client can revisit anytime

**Why this matters:**
- Email stays short and readable
- Client can drill down if they want details
- Full transparency on how recommendations were made
- No information is hidden - just organized better

---

## 2C. CONFIGURATION NEEDED

### MVP: Required Configuration

| Item | What You Provide | Where to Find It |
|------|------------------|------------------|
| **Team ID** | UUID of the team | Supabase → teams table → copy `id` |
| **System User ID** | UUID for workflow | Create user "workflow@system", copy `id` from profiles |
| **Email Account ID** | UUID of email account | After setting up IMAP/Gmail in Settings |

**Create System User:**
1. Register a new account: `workflow@yourdomain.com`
2. Go to Supabase → profiles table
3. Copy the `user_id` for this account
4. This becomes the workflow's identity

---

# PART 3: DECISIONS NEEDED

## Decision 1: Workflow State Storage (MVP)

**Question:** Where should the workflow track "which step are we on"?

| Option | Description | Effort | Recommendation |
|--------|-------------|--------|----------------|
| **A) Supabase** | Add columns to events table | Low | **Recommended for MVP** |
| **B) Separate DB** | Workflow has own database | Medium | Cleaner but more complex |
| **C) Reconstruct** | Figure out from email history | High | Too slow for MVP |

**If you choose A:**
- Add `current_step` and `date_confirmed` to events table
- Workflow reads/writes these directly
- You can see workflow state in Supabase

**If you choose B:**
- No Supabase changes needed
- Workflow manages its own state
- State not visible in your database

**Your choice:** ☐ A (Supabase) / ☐ B (Separate) / ☐ C (Reconstruct)

---

## Decision 2: Mail Thread Organization (LATER but decide now)

**Question:** How should the inbox show email conversations?

| Option | Description | When to Use |
|--------|-------------|-------------|
| **A) By Client** | One thread per client | Relationship-focused |
| **B) By Event** | One thread per booking | Transaction-focused |
| **C) Hybrid** | Client list → Events → Thread | Most flexible |

**Example:** John has 3 bookings
- Option A: One "John" thread with all emails
- Option B: Three separate threads
- Option C: Click John → see 3 bookings → click one

**Your choice:** ☐ A (Client) / ☐ B (Event) / ☐ C (Hybrid)

---

## Decision 3: Client Status Handling (LATER)

**Question:** Your database has status on both clients AND events. Should we change this?

**Current state:**
- `clients.status` = lead/option/confirmed/cancelled
- `events.status` = lead/option/confirmed/cancelled

**The issue:** A client can have multiple events with different statuses. So client-level status doesn't quite make sense.

| Option | Description | Effort |
|--------|-------------|--------|
| **A) Keep as-is** | Manually manage both | None |
| **B) Auto-derive** | Client status = max of their events | Low |
| **C) Remove client status** | Only track on events | Medium |

**Your choice:** ☐ A (Keep) / ☐ B (Auto-derive) / ☐ C (Remove)

---

## Decision 4: HIL (Human-in-Loop) UX (LATER)

**Question:** How should Accept/Reject work when the workflow needs manager approval?

**Context:** The workflow may need manager approval before sending certain responses (e.g., confirming a booking, sending an offer). Currently this creates a Task. But with mail thread view, we can embed approval buttons directly in the conversation.

| Option | Description | When to Use |
|--------|-------------|-------------|
| **A) Tasks only** | HIL creates task, manager approves in Tasks page | Simpler, works with existing UI |
| **B) Inline buttons** | Accept/Reject buttons in mail thread | More integrated, faster workflow |
| **C) Both** | Buttons in thread + task as backup | Most flexible, more dev work |

**If you choose B or C:**
- What happens on Accept? → Workflow continues, sends response
- What happens on Reject? → Manager can edit response, or cancel entirely
- Should manager be able to edit before accepting?

**Your choice:** ☐ A (Tasks) / ☐ B (Inline) / ☐ C (Both)

**Additional options if B or C:**
- [ ] Allow editing before accept
- [ ] Show preview of what will be sent
- [ ] Add comment field for rejection reason

---

# PART 4: IMPLEMENTATION ORDER

## Phase 1: Do Now (While Workflow Being Built)

```
Week 1:
├── 1. Add deposit columns to rooms table (15 min)
├── 2. Fill in deposit values for each room (15 min)
├── 3. Review room capacities are correct (15 min)
├── 4. Review product catalog is complete (30 min)
└── 5. Make Decision 1 (workflow state) (10 min)

Week 2:
├── 6. If Decision 1 = A: Add workflow columns to events
├── 7. Create system user account
├── 8. Set up email account for workflow
└── 9. Document team_id, user_id, email_account_id
```

## Phase 2: Integration Testing

```
├── 10. Test workflow with single client
├── 11. Verify events created correctly
├── 12. Verify offers generated correctly
├── 13. Test deposit calculations
└── 14. Make Decision 2 (mail threads) if not done
```

## Phase 3: After MVP Launch

```
├── 15. Add seating_layout field if needed
├── 16. Create site_visits table
├── 17. Create client_preference_history table
├── 18. Build mail thread view in frontend
├── 19. Add workflow step indicator
└── 20. Implement Decision 3 (client status)
```

---

# PART 5: CHECKLIST

## Supabase Checklist

**MVP (Do Now):**
- [ ] Add `deposit_required` to rooms table
- [ ] Add `deposit_percent` to rooms table
- [ ] Set deposit values for each room
- [ ] Verify all rooms have correct capacity values
- [ ] If Decision 1 = A: Add `current_step` to events
- [ ] If Decision 1 = A: Add `date_confirmed` to events

**LATER:**
- [ ] Add `seating_layout` to events table
- [ ] Add `preferred_room` to events table
- [ ] Create `site_visits` table
- [ ] Create `client_preference_history` table

## Configuration Checklist

**MVP:**
- [ ] Create system user account (e.g., workflow@system)
- [ ] Document the system user's `user_id` (UUID)
- [ ] Document your `team_id` (UUID)
- [ ] Set up email account for workflow
- [ ] Document the `email_account_id` (UUID)

## Decision Checklist

**MVP:**
- [ ] Decision 1: Workflow state storage = ________

**LATER:**
- [ ] Decision 2: Mail thread organization = ________
- [ ] Decision 3: Client status handling = ________
- [ ] Decision 4: HIL UX (Accept/Reject) = ________

---

# PART 6: REFERENCE

## What Already Exists (No Changes Needed)

| Feature | Table | Status |
|---------|-------|--------|
| Client management | clients | Ready |
| Event/booking management | events | Ready |
| Offer generation | offers | Ready |
| Deposit fields on offers | offers | Ready (deposit_enabled, deposit_type, etc.) |
| Product catalog | products | Ready |
| Room data | rooms | Needs deposit columns added |
| Email storage | emails | Ready |
| Task management | tasks | Ready (for HIL approvals) |

## What Workflow Creates

| Entity | Required Fields | Notes |
|--------|-----------------|-------|
| Client | name, team_id, user_id | Looked up by email first |
| Event | title, event_date, start_time, end_time, team_id, user_id | Created per booking |
| Offer | offer_number, subject, offer_date, user_id | With line items |
| Task | title, category, team_id, user_id | For HIL approvals |
| Email | from_email, to_email, subject, body_text | Conversation history |

## Field Mappings (For Reference)

The workflow uses slightly different names internally. These are already being adjusted:

| Workflow Internal | Your Database |
|-------------------|---------------|
| organization | company |
| chosen_date | event_date |
| number_of_participants | attendees |
| locked_room_id | room_ids (array) |
| capacity_max | capacity |

---

# APPENDIX: Why Each Change Matters

## Why deposit on rooms?

The workflow needs to know:
- "Should I calculate a deposit for this room?" → `deposit_required`
- "How much?" → `deposit_percent`

Without this, offers won't include deposit requirements.

## Why workflow state columns?

When a client sends a follow-up email 3 days later, the workflow needs to know:
- "Where were we in the conversation?" → `current_step`
- "Did they already confirm the date?" → `date_confirmed`

Without this, the workflow starts from scratch each time.

## Why system user?

Every database record needs a `user_id`. The workflow is automated, so it needs an identity. The system user is that identity.

## Why team_id?

Your database is multi-tenant. Every query filters by team. The workflow needs to know which team's data to access.

---

*Questions? Contact the development team.*