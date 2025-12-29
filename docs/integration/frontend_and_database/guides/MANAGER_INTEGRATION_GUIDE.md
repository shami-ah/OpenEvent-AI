# Email Workflow Integration Guide
## Manager Edition

**Last Updated:** 2025-12-09

**For:** River (Co-founder)

**Purpose:** Everything you need to decide and do before we launch the email workflow

---

## How to Use This Guide

This guide is organized by priority:

| Part | Content | Action |
|------|---------|--------|
| **Part 1** | UX Decisions | Decisions that shape client experience |
| **Part 2** | Setup Tasks | Things to configure before integration |
| **Part 3** | Technical Decisions | May need dev team input |
| **Part 4** | Later / Nice-to-Have | Can wait until after launch |
| **Part 5** | Reference | Technical details when needed |

**Start with Part 1** - these decisions shape how the system works for your clients.

---

# PART 1: UX Decisions

These decisions affect how clients experience the booking process and how event managers use the platform.

**Terminology:**

- **Event Manager** = The venue staff member using the platform daily
- **Client** = The person booking an event via email

---

## Decision 1: When Is a Room "Reserved"?

**The Question:** At what point in the booking process should a room be blocked on the calendar?

**Why This Matters:**

- Too early = rooms get "stuck" with clients who might not book
- Too late = risk of double-booking or conflicts

### What's Currently Implemented

**Current behavior: Option A (When client selects the room)**

The workflow currently sets status like this:

- **Lead**: From intake through date confirmation
- **Option**: When room is selected (Step 3 → Step 4 transition) — calendar blocked!
- **Confirmed**: When deposit paid (if required) AND manager approved

**Code locations:**

- Room selection → sets `locked_room_id` AND status = Option
- Confirmation → upgrades to Confirmed (or stays Option if awaiting deposit/approval)

### Your Options

When should the room appear as "reserved" (Option) on your calendar?

| Option | When Reserved | Pros | Cons |
|--------|---------------|------|------|
| **A** | When client selects room (current) | Early protection | May hold rooms unnecessarily |
| **B** | When offer is sent | More commitment shown | Small window for conflicts |
| **C** | When client accepts offer | Maximum flexibility | Risk of conflicts during negotiation |
| **D** | When deposit is paid | Strongest commitment | Longest exposure to conflicts |
| **E** | Custom | Describe below | — |

**Your choice:** ☐ A (keep current) / ☐ B / ☐ C / ☐ D / ☐ E: _____________

### Sub-Question: Should "Lead" Show on Calendar?

**Current behavior:** Lead status is invisible on the calendar. Only Option and Confirmed appear.

**This means:** If 3 clients are all discussing Feb 7th (but none has selected a room yet), the calendar shows Feb 7th as completely free.

**Alternative:** Show "Lead interest" on calendar dates

- Event Manager sees "3 leads interested in Feb 7" before anyone selects a room
- Helps with capacity planning and proactive conflict management
- Would need new calendar UI to distinguish Lead vs Option vs Confirmed

**Your choice:** ☐ A (keep current - Lead invisible) / ☐ B (show Lead interest)

---

## Decision 2: What If Two Clients Want the Same Room?

**The Question:** Two clients are interested in Room E on February 7th. What happens?

**Why This Matters:**

- Event Managers need to know when conflicts happen
- Someone needs to decide who "wins"
- Clients need clear communication

### What's Already Built

We implemented two conflict scenarios:

#### SOFT CONFLICT: Both clients have "Option" status

```
Client A: Option on Room E, Feb 7th
Client B: Also selects Room E, Feb 7th → becomes Option too
```

**What happens:**

- BOTH clients can hold the room as "Option" simultaneously
- Event Manager receives a task notification: "Conflict: Client A and Client B both want Room E on Feb 7"
- Neither client is told about the conflict (Event Manager sees it, clients don't)
- No blocking — both conversations continue normally
- Event Manager should resolve before either tries to confirm

#### HARD CONFLICT: One client tries to CONFIRM while another has Option

```
Client A: Option on Room E, Feb 7th
Client B: Tries to CONFIRM Room E, Feb 7th
```

**What happens:**

1. System automatically blocks Client B's confirmation
2. AI asks Client B: "This room is held by someone else. Do you have a special reason you need it?"
3. If Client B insists (e.g., "it's my wedding anniversary"), Event Manager gets a task to decide
4. Event Manager picks the winner
5. Loser is automatically asked to choose another room (if available) or choose a new date

### Your Options for Soft Conflicts

| Option | Behavior | Best For |
|--------|----------|----------|
| **A** | Notify Event Manager only (current) | Hands-on management |
| **B** | AI suggests alternatives to second client | Proactive conflict resolution |
| **C** | Block second client until first resolves | Strict first-come-first-served |
| **D** | Custom | Describe below |

**Your choice:** ☐ A (current) / ☐ B / ☐ C / ☐ D: _____________

---

## Decision 3: Can a Client Reserve Multiple Rooms?

**The Question:** A client wants to hold both Room A and Room B for the same date. Allow it?

### Common Scenarios

| Scenario | Example |
|----------|---------|
| **Legitimate** | "We need the ceremony room AND the dinner room" |
| **Undecided** | "I can't choose between A and B, can I hold both?" |
| **Separate events** | Client already booked Room A, now wants Room B too |

### What's Currently Implemented

**Current behavior: Option A (One room per event)**

- Each event has one `locked_room_id` (single room, not array)
- To book multiple rooms, client needs multiple events
- No enforcement preventing same client from creating multiple events on same date

### Your Options

| Option | Behavior | Notes |
|--------|----------|-------|
| **A** | One room per event (current) | Simple, clear |
| **B** | Allow multiple rooms per event | Needs schema change |
| **C** | Event Manager approves multi-room | Manual control |
| **D** | Custom | Describe below |

**Your choice:** ☐ A (current) / ☐ B / ☐ C / ☐ D: _____________

---

## Decision 4: How Should the Email Interface Look?

**The Question:** How should the inbox/email view be designed for Event Managers?

**Why This Matters:**

- Event Managers handle multiple clients and bookings
- They need to quickly find conversations and take action
- The interface affects how efficiently they can work

### Interface Style Options

| Option | Style | Description |
|--------|-------|-------------|
| **A** | Chat-style per client | Like WhatsApp, shows all emails in conversation view |
| **B** | Grouped by event | Emails organized by event name + date |
| **C** | Hybrid with views | Toggle between "By Client" / "By Event" / "By Status" |
| **D** | Traditional inbox | Standard email list, filter/search to find conversations |
| **E** | Custom | Describe below |

### Quick Action Buttons

Instead of Event Manager having to write/send emails manually, should we add quick action buttons?

| Button | Action |
|--------|--------|
| ✓ Approve & Send | Send AI draft as-is |
| ✎ Edit & Send | Modify before sending |
| ✗ Reject | Write own response |
| ⏸ Hold | Keep in queue, don't send yet |

**Your choice for interface:** ☐ A / ☐ B / ☐ C / ☐ D / ☐ E: _____________

**Include quick action buttons?** ☐ Yes / ☐ No / ☐ Only some (which?): _____________

---

## Decision 5: How Should Event Manager Approvals Work?

**The Question:** When the AI generates a response, how does the Event Manager approve it?

### MVP Requirement: Human-in-the-Loop (HIL)

**For MVP, EVERY AI message requires Event Manager approval before the client sees it.**

This means:

1. AI generates a response to client email
2. Event Manager sees the draft in their interface
3. Event Manager can:
   - **Approve** → Message is sent to client
   - **Edit** → Modify the message, then send
   - **Reject** → Write their own message instead
4. Only after approval does the client receive anything

### Where Should Approval Happen?

| Option | Location | Pros | Cons |
|--------|----------|------|------|
| **A** | Email interface | See full context | Another screen to check |
| **B** | Tasks section | Centralized approvals | Less email context |
| **C** | Both | Flexible | More complex |
| **D** | Custom | Describe below | — |

### Task Categories (if using Tasks)

If approvals appear in Tasks, which category?

- ☐ Event Tasks
- ☐ Client Follow-ups
- ☐ Email Tasks
- ☐ Invoice Tasks
- ☐ New category: "AI Approvals" (requires frontend work)

**Your choice for approval location:** ☐ A / ☐ B / ☐ C / ☐ D: _____________

**Task category (if applicable):** _____________

---

## Decision 6: Deposit Settings (MVP = Global)

For MVP: Deposits use a **single global setting** that applies to all rooms.

### What's Already Implemented

- Enable/disable deposits for all bookings
- Set percentage (e.g., 30%) or fixed amount (e.g., CHF 500)
- Set payment deadline (e.g., 10 days)

### MVP Question

**Is global deposit okay for launch?**

Most venues have one deposit policy. If yours varies by room (e.g., "Room A requires 50%, Room B requires 20%"), we can add per-room deposits after MVP.

**Your answer:** ☐ Yes, global is fine for MVP / ☐ No, I need per-room before launch

If no, explain: _____________

---

## Decision 7: Product Recommendation Threshold

**The Question:** When the AI recommends products/catering based on client preferences, how confident should it be?

**Current Setting:** 65% match required

**Example:**

- Client says "I'd like vegetarian options and something for coffee breaks"
- AI finds "Vegetarian Menu" is a 70% match → **recommended**
- AI finds "Coffee & Snacks Package" is a 55% match → **not recommended** (below 65%)

### Your Options

| Threshold | Effect |
|-----------|--------|
| **80%** (strict) | Only very close matches, fewer recommendations |
| **65%** (current) | Balanced approach |
| **50%** (lenient) | More recommendations, some may be less relevant |

**Your choice:** ☐ 80% / ☐ 65% (current) / ☐ 50% / ☐ Other: _____________

---

## Decision 8: When Should AI Ask for Help with Room Selection?

**The Question:** After how many failed room availability checks should the AI escalate to Event Manager?

**What "Failed" Means:**

- Client wants Feb 7th → Room A is booked
- Client says "what about Feb 8th?" → Room A still booked
- Client says "Feb 9th?" → still booked…

After this many failed attempts, the AI creates a task for the Event Manager instead of continuing to ping-pong.

**Current Setting:** 3 failed proposals

**Why This Matters:**

- Too low = AI gives up too quickly, Event Manager does manual work
- Too high = Client gets frustrated with many back-and-forth emails

**Your choice:** ☐ 2 / ☐ 3 (current) / ☐ 5 / ☐ Other: _____________

---

## Decision 9: How to Handle Edge Cases

### 9A: First Email Isn't About Booking an Event

**What Happens Now:**

- AI classifies the email with confidence
- If confidence < 85% that it's an event inquiry → AI says "A member of our team will review it shortly" and creates a task for Event Manager
- Event Manager decides if it's a booking or something else

**Example:** Someone emails "What are your opening hours?" — this isn't a booking request, so it goes to Event Manager.

**Is this okay?** ☐ Yes, keep it / ☐ No, I want: _____________

---

### 9B: Nonsense or Out-of-Context Messages

**What Happens Now:** The AI looks at message confidence:

| Confidence | Action |
|------------|--------|
| < 30% | Auto-skip (likely spam/noise) |
| 30-85% | Send to Event Manager for review |
| > 85% | AI processes normally |

**Why This Matters:** Saves money on AI calls for obvious spam/noise, but doesn't miss edge cases.

**Is this okay?** ☐ Yes, keep it / ☐ No, I want: _____________

---

### 9C: Client Cancels Their Booking

**What Happens Now:**

1. AI detects cancellation intent (keywords like "cancel", "nevermind", "no longer interested")
2. Event status is set to Cancelled
3. AI drafts a polite response: "Thank you for letting us know. We've released the date, and we'd be happy to assist with any future events."
4. Draft goes to Event Manager for approval (HIL) before sending
5. Room is released (no longer blocked on calendar)

**What's NOT decided yet:**

- Should we ask for a cancellation REASON?
- Should we offer alternatives (reschedule, different date)?
- Should there be a cancellation fee reference?

**Your preference:**

- ☐ Simple cancellation (current — acknowledge and release)
- ☐ Ask for reason before confirming
- ☐ Offer alternatives before accepting cancellation
- ☐ Other: _____________

---

### 9D: Info Page Links in Emails

**What Happens Now:** Every AI-generated email with details (rooms, menus, offers) includes a link to an "info page" where the client can see the full breakdown.

**Why:** Emails have limited space. The AI summarizes, but the client can click to see everything (room photos, full menu descriptions, price breakdowns).

**Example:** "For full details on our room options, see: View Room Comparison"

**Is this okay?** ☐ Yes, always include info page links / ☐ No, I prefer: _____________

---

# PART 2: Setup Tasks

Things you need to configure before launch.

---

## Task 1: Add Deposit Settings to Rooms (if Decision 6 = B or C)

**What:** Add per-room deposit columns to your rooms table.

**Skip this if:** You chose global-only deposits (Decision 6 = A)

**Steps:**

1. Open Supabase Dashboard → Table Editor → `rooms`
2. Click "New Column" and add:
   - `deposit_required` (type: boolean, default: false)
   - `deposit_percent` (type: int4, nullable)
3. Fill in values for each room

---

## Task 2: Configure the AI Identity

**What:** The AI needs an identity to appear as when creating records and sending emails.

**Why This Matters:** When the AI creates events, sends emails, or logs actions, it needs to be recorded as "someone" in your database. Every record in Supabase requires a `user_id` field.

### Options

| Option | Approach | Recommended? |
|--------|----------|--------------|
| **A** | Use an existing admin user | Not ideal — confuses who did what |
| **B** | Create a dedicated "system" user | ✅ Recommended — clear audit trail |

**If choosing B:**

1. Create a new user account: `workflow@yourdomain.com`
2. This account won't log in — it's just an identity for the AI
3. Go to Supabase → `profiles` table
4. Find this user's row and copy the `id` (UUID)
5. Save this ID: ________________

---

## Task 3: Set Up Email Integration

**What:** Connect the email account that the AI will use to send/receive client messages.

**For MVP:** Before ANY email goes to a client, the Event Manager must approve it (see Decision 5).

**Steps:**

1. Go to Settings → Emails in your frontend
2. Connect your venue's email (IMAP or Gmail OAuth)
3. Set scope to "Team" (all Event Managers on your team can see these emails)
4. Go to Supabase → `email_accounts` table
5. Copy the `id` of this email account: ________________

---

## Task 3b: HIL Email Notifications (READY TO CONFIGURE)

**What:** Send email notifications to Event Manager when HIL tasks need approval.

**Why:** In addition to the frontend Manager Tasks panel, the system can now send email notifications when tasks require approval. This ensures the Event Manager doesn't miss urgent approvals.

**Status:** ✅ IMPLEMENTED (December 2025) - needs SMTP configuration

### How It Works

1. When a HIL task is created (offer approval, date confirmation, etc.)
2. Email notification is sent to the Event Manager
3. Email contains: client name, draft message, event details
4. Manager clicks link to open dashboard and approve/reject
5. This works IN ADDITION to the frontend panel (not instead of)

### Configuration Options

**Option A: Environment Variables**
```bash
EVENT_MANAGER_EMAIL=manager@atelier.ch
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # Use app password for Gmail
HIL_FROM_EMAIL=openevent@atelier.ch
```

**Option B: API Configuration**
```bash
POST /api/config/hil-email
{
  "enabled": true,
  "manager_email": "manager@atelier.ch"
}
```

### For Supabase Integration

The manager email should come from the logged-in user:

```python
# In production, fetch from Supabase auth context:
manager_email = supabase.auth.get_user().email

# The current API endpoint serves as fallback:
POST /api/config/hil-email {"manager_email": manager_email}
```

### Test Email Configuration

```bash
# Send test notification to verify SMTP works
POST /api/config/hil-email/test

# Send test email to specific address
POST /api/emails/test {"to_email": "test@example.com"}
```

### Files to Reference

| File | Purpose |
|------|---------|
| `backend/services/hil_email_notification.py` | Core email service |
| `backend/api/routes/emails.py` | Client email endpoints |
| `backend/api/routes/config.py` | HIL email config endpoints |

---

## Task 4: Document Your Team ID

**What:** We need to identify your venue in the database so the AI accesses the correct rooms, products, and events.

**Current Status:** For MVP, this repo supports **single-tenant** mode (one venue). Multi-tenant support (multiple venues/organizations sharing the platform) is planned for later.

### For MVP (Single Venue)

Since you're the only venue using the system right now, you have two options:

| Option | What to Do | When to Use |
|--------|------------|-------------|
| **A** | Check if `teams` table exists | If your Supabase already has a teams table |
| **B** | Skip for now | If no teams table exists yet |

**If Option A (teams table exists):**

1. Go to Supabase Dashboard → Table Editor
2. Look for a `teams` table
3. If it exists, find your venue's row and copy the `id`: ________________

**If Option B (no teams table):**

- No action needed for MVP
- The AI workflow will operate without team filtering
- We'll add this when multi-tenant support is built

### Future: Multi-Tenant Support

When we add multi-tenant support later, every database query will filter by `team_id` so that:
- Venue A can't see Venue B's data
- Each venue's AI only accesses their own rooms, clients, and events

**For now:** Just note whether the `teams` table exists: ☐ Yes (ID: ________) / ☐ No (skip)

---

## Setup Checklist

Before testing:

- [ ] Deposit settings configured (global or per-room)
- [ ] AI identity user created, ID saved: ________________
- [ ] Email account connected, ID saved: ________________
- [ ] Team ID: ☐ Saved: ________ / ☐ Skipped (no teams table)
- [ ] HIL email notifications: ☐ Configured (SMTP set) / ☐ Skipped (frontend panel only)

---

# PART 3: Technical Decisions

These decisions are more technical. Let's discuss together.

---

## Technical Decision A: Where to Store Conversation Progress

**The Question:** When a client emails back 3 days later, how does the AI know where you left off?

**The Problem:** If our server restarts, or if the client waits days between emails, the AI needs to know:

- "We were on step 3 (room selection)"
- "The date was already confirmed as Feb 7th"
- "We were in the middle of a date change (detour)"

Without persistent storage: The AI would "forget" and might repeat steps or get confused.

### Your Options

| Option | Where | Pros | Cons |
|--------|-------|------|------|
| **A** | In your Supabase (recommended) | Single source of truth | Small schema additions |
| **B** | Separate database | Isolated from your data | More infrastructure |

**If choosing A, we add these columns to `events`:**

- `current_step` (1-7): Which step of the booking process?
- `date_confirmed` (boolean): Has the date been locked?
- `caller_step` (integer): For tracking "detours" when client changes something

**Note:** This is about safety and reliability, not performance. Without this, a server restart would lose conversation state.

**Your choice:** ☐ A (In your Supabase) / ☐ B (Separate database)

---

## Technical Decision B: Hash Columns for Change Detection

**The Question:** Should we track what information has been "locked in" to avoid redundant re-checks?

**What We Already Have:** We capture variables from client messages (name, date, participants, etc.) as they're mentioned.

**What This Adds:** Hash columns let us detect if something CHANGED since last check:

- `requirements_hash` — Hash of (participants, duration, special requirements)
- `room_eval_hash` — Snapshot of requirements when room was checked
- `offer_hash` — Snapshot of offer terms when accepted

**Example:** If client confirms room, asks a Q&A question, then says "yes proceed" — should we re-check room availability? With hashes, we know nothing changed, so we skip the re-check.

**Trade-off:**

| Approach | Behavior |
|----------|----------|
| **With hashes** | Faster, fewer database queries |
| **Without hashes** | Always re-checks everything (safer but slower) |

**Your choice:** ☐ Add hash columns (faster) / ☐ Skip (simpler, always re-check)

---

# PART 4: Later / Nice-to-Have

These can wait until after MVP. Listed by priority.

---

## HIGH PRIORITY (Soon After MVP)

### Mail Thread Grouping View

**What:** Group emails by client or event in the inbox view.

**Why Important:** Without this, Event Managers see a flat list of emails and have to manually find related conversations.

**Already Have:** Basic email storage with `client_id` and `event_id` links.

**Needs:** Frontend UI to group/display by these fields.

---

### Progress Indicator per Conversation

**What:** Show "Step 3 of 7: Room Selection" on each client conversation.

**Why Important:** Event Manager can quickly see where each booking stands without reading the entire thread.

**Where:** In the email/chat interface, next to or above each conversation.

**Already Have:** Backend tracks `current_step` (if Technical Decision A = Add columns).

**Needs:** Frontend component to display it.

---

### Deposit Status Badge

**What:** Show "Deposit Pending" / "Deposit Paid" badge on offers and events.

**Why Important:** Quick visibility into which bookings need deposit follow-up.

**Already Have:** `offers.deposit_paid_at` field (null = unpaid, timestamp = paid).

**Needs:** Frontend badge component.

---

## MEDIUM PRIORITY

### Per-Room Deposits

**What:** Different deposit requirements per room (e.g., "Room A = 50%, Room B = 20%")

**MVP uses:** Global deposit setting (same for all rooms)

**Needs:**

- Add `deposit_required`, `deposit_percent` columns to rooms table
- Frontend UI to edit per-room deposits
- Backend logic to check room-level override before global

---

### Per-Room Site Visit Settings

**What:** Enable/disable site visits per room (e.g., "Room A allows visits, Room B doesn't")

**MVP uses:** Global site visit setting (same for all rooms)

**Needs:**

- Add `allow_site_visit` column to rooms table
- Frontend toggle per room
- Backend logic to check room-level setting

---

### Site Visit Scheduling

**What:** Let clients request venue tours, AI schedules them.

**Already Have:** Backend logic for detecting and handling site visit requests.

**Options for Storage:**

| Option | Approach |
|--------|----------|
| **A** | New `site_visits` table |
| **B** | Flag on events table |

**Recommendation:** Option A is cleaner if site visits have their own workflow (reschedule, cancel, etc.).

**Needs:**

- If Option A: New Supabase table + frontend UI to view/manage visits
- If Option B: Just a boolean column + minor UI changes

---

### Info Pages for Clients

**What:** Links in emails that clients can click to see detailed info (room comparison, offer breakdown, FAQs).

**Already Have:**

- Backend generates snapshot data
- Test pages in this repo (`/info/rooms`, `/info/catering`)

**Needs:**

- Design review to match openevent.io branding
- Integration with your frontend routing
- Decision on public vs authenticated access

---

### Client Status Handling

**What:** Your database has `status` on both clients AND events. Should we simplify?

**The Issue:** A client can have multiple events with different statuses (e.g., confirmed wedding + pending corporate event).

**Options:**

| Option | Behavior |
|--------|----------|
| Keep both | Manually manage, no changes |
| Auto-calculate | Client status = highest of their event statuses |
| Remove client status | Only track on events (simpler) |

**Your choice:** ☐ Keep both / ☐ Auto-calculate / ☐ Remove client status

---

## LOWER PRIORITY (Future)

### Multiple-Day Events

**What:** Allow booking a room for a date RANGE (e.g., Feb 7-9) instead of single day.

**Impact:** Affects date confirmation, availability checking, offer calculation.

**Needs:** Schema changes, workflow updates, frontend date range picker.

---

### AI Personalization from Client History

**What:** AI remembers client preferences from past bookings (e.g., "John always prefers Room A and vegetarian menus").

**Already Have:** Conversation history is stored in `emails` table.

**Needs:**

- Preference extraction and storage (new table or JSONB field)
- LLM prompt modifications to use preferences
- UI to view/edit client preferences

---

### Event Manager Manual Override Form

**What:** If Event Manager resolves something outside the AI (phone call, in-person), how do they tell the AI?

**Example:** "I called John, he confirmed Feb 7th verbally" → AI should skip date confirmation.

**Options:**

- Form to set workflow state manually
- Notes field that AI parses
- AI detects from Event Manager's sent emails

**Your choice:** ☐ Form / ☐ Notes / ☐ Detection / ☐ Skip for now

---

### Email Categories and Filtering

**What:** Categorize AI-generated emails and tasks for better organization.

**Why:** Event Managers may want to filter tasks by type (e.g., "show me all conflict resolutions" or "all pending cancellations").

**Proposed Categories:**

| Category | When Used |
|----------|-----------|
| `workflow_normal` | Standard booking steps (date confirm, room selection, offer) |
| `conflict_resolution` | Soft or hard room conflicts to resolve |
| `special_request` | Client made unusual request needing human judgment |
| `cancellation` | Client cancellation handling |
| `nonsense_review` | Low-confidence messages sent to Event Manager |
| `negotiation` | Counter-offers, price discussions |
| `site_visit` | Site visit scheduling |

**Implementation:** Add `email_category` field to tasks or emails table.

**Your interest:** ☐ Want this soon / ☐ Can wait / ☐ Not needed

---

### Advanced Customization

- **Room Rules Editor:** Custom logic like "prefer Room A for corporate events 50+"
- **Prompt Customization:** Change AI's tone and style per venue
- **Custom Email Links:** Add links to your website in workflow emails

---

# PART 5: Reference

Technical details for when you or the dev team need specifics.

---

## What Already Exists (No Changes Needed)

### Existing Deposit Fields on Offers

Your `offers` table already has:

- `deposit_enabled`, `deposit_type`, `deposit_percentage`
- `deposit_fixed_amount`, `deposit_amount`
- `deposit_paid_at` (null = unpaid, has date = paid)
- `deposit_deadline_days`

The AI uses these! We just need to know deposit requirements (global or per-room).

---

### Status Values

Both workflow and database use:

| Status | Meaning |
|--------|---------|
| `lead` | New inquiry, not yet engaged |
| `option` | Negotiating, room provisionally held |
| `confirmed` | Booking confirmed, deposit paid (if required) |
| `cancelled` | Lost or cancelled |

---

## Field Name Mappings

The AI workflow code uses some different names internally than your database. This section documents those mappings so the dev team knows what to translate.

**Why:** When we connect the workflow to your Supabase, we need to convert between these names.

| Workflow (Internal) | Supabase (Database) |
|---------------------|---------------------|
| `organization` | `company` |
| `chosen_date` | `event_date` |
| `number_of_participants` | `attendees` |
| `locked_room_id` | `rooms` (array) |
| `Lead` | `lead` |
| `Option` | `option` |
| `Confirmed` | `confirmed` |

---

# Checklists

## MVP Decisions

### Part 1: UX Decisions

| Decision | Options | Your Choice |
|----------|---------|-------------|
| **1. When Reserved** | A (current) / B / C / D / E | |
| **1 sub. Lead visible?** | A (invisible) / B (visible) | |
| **2. Conflict Handling** | A (current) / B / C / D | |
| **3. Multiple Rooms** | A (current) / B / C / D | |
| **4. Email Interface** | A / B / C / D / E | |
| **4 sub. Quick Buttons?** | Yes / No / Some | |
| **5. Approval Flow** | A / B / C / D | |
| **5 sub. Task Category** | (if applicable) | |
| **6. Deposits (Global OK?)** | Yes / No | |
| **7. Product Match %** | 80 / 65 / 50 / Other | |
| **8. Room HIL Threshold** | 2 / 3 / 5 / Other | |
| **9A. Non-event emails** | Keep / Change | |
| **9B. Nonsense handling** | Keep / Change | |
| **9C. Cancellation flow** | Simple / Ask reason / Offer alternatives | |
| **9D. Info page links** | Keep / Change | |

### Part 3: Technical Decisions

| Decision | Options | Your Choice |
|----------|---------|-------------|
| **A. State Storage** | A (Supabase) / B (Separate) | |
| **B. Hash Columns** | Add / Skip | |

---

## Setup Completed

- [ ] Deposit settings configured (global or per-room)
- [ ] AI identity user created
  - ID: ________________
- [ ] Email account connected
  - ID: ________________
- [ ] Team ID: ☐ Saved: ________ / ☐ Skipped (no teams table for MVP)
- [ ] (If Tech A = Add) Workflow columns added to events

---

## Post-MVP Priority List

### High Priority (Soon)

- [ ] Mail thread grouping view (Frontend)
- [ ] Progress indicator per conversation (Frontend)
- [ ] Deposit status badges (Frontend)

### Medium Priority

- [ ] Site visit scheduling (Backend + Frontend)
- [ ] Info pages integration with openevent.io design (Frontend)
- [ ] Client status handling decision

### Lower Priority (Future)

- [ ] Multiple-day event support
- [ ] AI personalization from client history
- [ ] Event Manager manual override form
- [ ] Email categories and filtering
- [ ] Advanced customization features

---

*Document version: 8.1 | Last updated: 2025-12-10*

**Questions?** Ask the dev team!