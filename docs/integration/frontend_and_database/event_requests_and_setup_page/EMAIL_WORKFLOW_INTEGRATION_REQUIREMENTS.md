# Email Workflow Integration Requirements

**Generated:** 2025-12-08
**Purpose:** Define all changes needed for email workflow to integrate with main OpenEvent project

---

## Executive Summary

This document identifies what needs to change for the email workflow to integrate with the main OpenEvent project.

**Key Finding:** The main project is **multi-tenant** (team-based) and has a deposit system already in place.

---

# PART A: EMAIL WORKFLOW CODE CHANGES

These are changes you need to make in the email workflow code - **no Supabase changes required**.

---

## A1. Column Name Renames (Use Different Name)

| Email Workflow Uses | Change To | Table | Notes |
|---------------------|-----------|-------|-------|
| `organization` | `company` | clients | Different column name |
| `chosen_date` | `event_date` | events | Different column name |
| `number_of_participants` | `attendees` | events | Different column name |
| `capacity_max` | `capacity` | rooms | Different column name |
| Task `type` | Task `category` | tasks | Different column name |
| `resolved_at` | `completed_at` | tasks | Different column name |
| `deposit_paid` (boolean) | `deposit_paid_at` (timestamp) | offers | Check `is not null` |
| `deposit_status` | `payment_status` | offers | Different column name |
| `accepted_at` | `confirmed_at` | offers | Different column name |

---

## A2. ID Format Changes (UUID instead of string)

| Email Workflow Uses | Change To | Notes |
|---------------------|-----------|-------|
| `client_id` = email string | UUID | Lookup client by email, use returned UUID |
| `room_id` = "room-a" string | UUID | Use actual room UUID from database |
| `product_id` = "menu-1" string | UUID | Use actual product UUID from database |

**Example - Client lookup:**
```python
# BEFORE: Using email as client_id
client_id = email.lower()

# AFTER: Lookup by email, use UUID
client = await supabase.from("clients").select("id").eq("email", email.lower()).single()
client_id = client["id"]  # UUID
```

---

## A3. Array Format Changes

| Email Workflow Uses | Change To | Notes |
|---------------------|-----------|-------|
| `locked_room_id` (single string) | `room_ids` (string array) | Use `[room_id]` format |
| `features` (JSONB object) | `amenities` (string array) | Flat array of strings |
| `equipment` (JSONB object) | `amenities` (string array) | Merged into same array |

**Example:**
```python
# BEFORE
event["locked_room_id"] = "uuid-here"

# AFTER
event["room_ids"] = ["uuid-here"]
```

---

## A4. Required Fields (Must Provide)

When creating records, these fields are **required** by the main project:

### Clients
```python
{
    "name": str,       # REQUIRED
    "team_id": uuid,   # REQUIRED - get from config
    "user_id": uuid,   # REQUIRED - system user ID
}
```

### Events
```python
{
    "title": str,        # REQUIRED - generate: f"Event for {client_name}"
    "event_date": str,   # REQUIRED
    "start_time": str,   # REQUIRED - e.g. "09:00:00"
    "end_time": str,     # REQUIRED - e.g. "17:00:00"
    "team_id": uuid,     # REQUIRED
    "user_id": uuid,     # REQUIRED
}
```

### Offers
```python
{
    "offer_number": str,  # REQUIRED - generate unique number
    "subject": str,       # REQUIRED - e.g. "Event Offer - {title}"
    "offer_date": str,    # REQUIRED - today's date
    "user_id": uuid,      # REQUIRED
}
```

### Tasks
```python
{
    "title": str,      # REQUIRED
    "category": str,   # REQUIRED (not "type")
    "team_id": uuid,   # REQUIRED
    "user_id": uuid,   # REQUIRED
}
```

---

## A5. Room Capacity Mapping

Main project has layout-specific capacity columns instead of JSONB:

| Email Workflow | Main Project Column |
|----------------|---------------------|
| `layouts["theatre"]` | `theater_capacity` |
| `layouts["cocktail"]` | `cocktail_capacity` |
| `layouts["dinner"]` | `seated_dinner_capacity` |
| `layouts["standing"]` | `standing_capacity` |
| Default max | `capacity` |

---

## A6. Product Category

| Email Workflow | Main Project |
|----------------|--------------|
| `category` (string like "catering") | `category_id` (UUID FK to `product_categories`) |

You need to lookup category by name to get the UUID, or filter products differently.

---

# PART B: SUPABASE CHANGES REQUIRED

These are columns/tables that **must** be added to Supabase.

---

## B1. Columns to ADD to `events` Table

| Column | Type | Purpose | Required? |
|--------|------|---------|-----------|
| `seating_layout` | TEXT | Theatre, U-shape, boardroom, etc. | Optional |
| `preferred_room` | TEXT | Client's room preference | Optional |

**Note:** `attendees` and `notes` already exist and can be used for participants and special requirements.

---

## B2. Columns to ADD to `rooms` Table

| Column | Type | Purpose |
|--------|------|---------|
| `deposit_required` | BOOLEAN | Whether room requires deposit |
| `deposit_percent` | INT | Deposit percentage (e.g., 30) |

---

## B3. New Tables to CREATE

### `site_visits` (for venue tours)
```sql
CREATE TABLE site_visits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    user_id UUID NOT NULL,
    status TEXT DEFAULT 'idle',  -- idle, proposed, scheduled, completed, cancelled
    requested_date DATE,
    confirmed_date DATE,
    confirmed_time TIME,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### `page_snapshots` (for persistent info links) - Optional
```sql
CREATE TABLE page_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,  -- 'room_eval', 'qa', 'offer', 'availability'
    data JSONB NOT NULL,
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    created_at TIMESTAMP DEFAULT NOW()
    -- NOTE: No expires_at - links should NOT expire
);
```

---

# PART C: WORKFLOW STATE - WHERE TO STORE?

**Question:** The email workflow plan mentions these columns:
- `current_step` (1-7)
- `caller_step` (for detours)
- `requirements_hash`, `room_eval_hash`, `offer_hash`
- `date_confirmed`, `transition_ready`, `decision`
- `thread_state`

**These are workflow-internal state.** Options:

| Option | Where to Store | Pros | Cons |
|--------|----------------|------|------|
| **A) In main Supabase** | Add columns to `events` | Single source of truth, visible in frontend | Pollutes main schema |
| **B) Separate workflow DB** | Email workflow's own database | Clean separation | Two databases to sync |
| **C) Reconstruct from history** | Derive from conversation each time | No persistence needed | More compute per request |

### Recommendation

**Option A or B** - these values need to persist between emails:
- `current_step`: Must know where conversation left off
- `caller_step`: Must remember where to return after detour
- Hash values: Must persist to avoid redundant re-evaluation

**If you choose Option A (store in main Supabase):**
```sql
-- Add to events table
ALTER TABLE events ADD COLUMN IF NOT EXISTS current_step INT DEFAULT 1;
ALTER TABLE events ADD COLUMN IF NOT EXISTS caller_step INT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS date_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS requirements_hash TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS room_eval_hash TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS offer_hash TEXT;
```

**If you choose Option B (separate workflow DB):** Keep these in the email workflow's own storage, don't add to main Supabase.

---

# PART D: GOOD NEWS - EXISTING FEATURES

## D1. Deposit System Already Exists!

The `offers` table already has:

| Column | Type | Use |
|--------|------|-----|
| `deposit_enabled` | boolean | Whether deposit required |
| `deposit_type` | string | "percentage" or "fixed" |
| `deposit_percentage` | number | e.g., 30 for 30% |
| `deposit_fixed_amount` | number | Fixed CHF amount |
| `deposit_amount` | number | Calculated deposit |
| `deposit_paid_at` | timestamp | When paid (null = unpaid) |
| `deposit_deadline_days` | number | Days until due |

**No need to create a deposits table!**

## D2. Messages Can Use `emails` Table

Main project has an `emails` table with:
- `event_id`, `client_id` (can link to workflow)
- `body_text`, `body_html`
- `is_sent` (true = outgoing, false = incoming)
- `from_email`, `to_email`

You can store conversation history here instead of creating a separate `messages` table.

---

# PART E: QUICK REFERENCE CHECKLIST

## Email Workflow Code Changes
- [ ] Rename `organization` → `company`
- [ ] Rename `chosen_date` → `event_date`
- [ ] Rename `number_of_participants` → `attendees`
- [ ] Rename `capacity_max` → `capacity`
- [ ] Rename task `type` → `category`
- [ ] Use UUIDs for client_id, room_id, product_id (not string slugs)
- [ ] Use `room_ids` array instead of `locked_room_id` string
- [ ] Use `amenities` array instead of `features`/`equipment` JSONB
- [ ] Add `team_id` to all operations
- [ ] Add `user_id` to all operations
- [ ] Generate `title` for events
- [ ] Generate `offer_number` for offers
- [ ] Provide `start_time`/`end_time` for events
- [ ] Check `deposit_paid_at is not null` instead of `deposit_paid == true`

## Supabase Schema Additions
- [ ] Add `seating_layout` to events (optional)
- [ ] Add `preferred_room` to events (optional)
- [ ] Add `deposit_required` to rooms
- [ ] Add `deposit_percent` to rooms
- [ ] Create `site_visits` table
- [ ] **DECIDE:** Add workflow columns to events OR keep in separate workflow DB

## Configuration Needed
- [ ] Create system user for email workflow → get `user_id`
- [ ] Determine which `team_id`(s) workflow will operate on
- [ ] Create email account for workflow → get `email_account_id`

---

# PART F: OPEN DECISIONS & CLARIFICATIONS

## F1. Client Preferences - Store with Timestamps

Preferences change over time. Store as history, not single value:

```sql
-- Recommended: Separate table for preference history
CREATE TABLE client_preference_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id),
    team_id UUID REFERENCES teams(id),
    extracted_at TIMESTAMP DEFAULT NOW(),
    preferences JSONB NOT NULL,
    source_email_id UUID REFERENCES emails(id),  -- Which email it came from
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_client_prefs ON client_preference_history(client_id, extracted_at DESC);
```

**Example preferences JSONB:**
```json
{
  "language": "de",
  "typical_event_size": "50-100",
  "preferred_room_type": "large with natural light",
  "dietary_notes": "vegetarian options needed",
  "parking_required": true
}
```

---

## F2. Status Clarification (VERIFIED)

**VERIFIED FROM SCHEMA:** Both use similar enums!

| Enum | Values |
|------|--------|
| `client_status` | `lead`, `option`, `confirmed`, `cancelled` |
| `event_status_enum` | `lead`, `option`, `confirmed`, `cancelled`, `blocked` |

**Status exists at TWO levels:**

| Field | Meaning | How Used |
|-------|---------|----------|
| `clients.status` | Client's **overall pipeline status** | Where they are in your sales funnel |
| `events.status` | **Booking** status for specific event | Status of that particular booking |

**Example:**
- Client status = `confirmed` (they are an active customer)
- But their events could be:
  - Event A: `confirmed` (completed booking)
  - Event B: `option` (pending deposit)
  - Event C: `lead` (new inquiry)

**For the email workflow:**
- Track **booking status** on `events.status` (per booking)
- Optionally update `clients.status` to reflect their overall engagement (e.g., once any booking is confirmed, client becomes `confirmed`)

**ARCHITECTURAL QUESTION:** Why does `clients.status` exist?

The `events` table already IS the join that tracks bookings:
```
events = { client_id, room_ids, event_date, status }
```

So `clients.status` seems **redundant** - the booking status belongs on `events`, not `clients`.

**Possible reasons it exists:**
1. **MVP simplification** - Early version assumed 1 client = 1 booking
2. **CRM convenience** - Quick pipeline view without joining events
3. **Legacy/redundant** - Should be derived from events

**Options:**
- **A) Keep as-is**: Manually update `clients.status` (current behavior)
- **B) Derive it**: Auto-calculate from max(events.status) for that client
- **C) Remove it**: Only use `events.status` for bookings (cleaner architecture)

**For email workflow:** Use `events.status` for booking status. Ignore `clients.status` or keep in sync if needed.

---

## F3. OPEN DECISION: Frontend Mail Thread UX

**Question:** How should the manager's inbox organize conversations?

| Option | Description |
|--------|-------------|
| **A) Thread per Client** | One conversation window per client, all their events mixed |
| **B) Thread per Event** | One conversation window per booking (cleaner separation) |
| **C) Hybrid** | Client list → click to see their events → click event to see that thread |

**Current `emails` table supports all via:**
- `client_id` → group by client
- `event_id` → group by booking
- `thread_id` → native email threading

**TO DECIDE:**
- [ ] Which thread model for manager inbox?
- [ ] How to handle client with multiple concurrent bookings?
- [ ] Should completed events archive their threads?

---

## F4. OPEN DECISION: HIL (Human-in-Loop) UX

**Question:** How should Accept/Reject work when workflow needs manager approval?

| Option | Description |
|--------|-------------|
| **A) Tasks only** | HIL creates task, manager approves in Tasks page |
| **B) Inline buttons** | Accept/Reject buttons in mail thread view |
| **C) Both** | Buttons in thread + task as backup |

**TO DECIDE:**
- [ ] Which approach for manager approvals?
- [ ] Should manager be able to edit before accepting?
- [ ] Preview of what will be sent?

---

## F5. FUTURE FEATURES: Manager Customization

These features allow managers to customize workflow behavior:

| Feature | Purpose | Storage Location |
|---------|---------|------------------|
| **Room Rules** | Custom logic for room selection | `knowledge_base` or new table |
| **Prompt Customization** | Modify LLM tone/style | `knowledge_base` or config |
| **Custom Links** | Add links to workflow emails | Config per team |

**Example Room Rule:**
```json
{
  "rule": "prefer_room_a_for_corporate",
  "condition": "event_type == 'corporate' AND attendees > 50",
  "action": "prioritize",
  "room_id": "uuid-of-room-a"
}
```

---

## F6. FUTURE FEATURES: Info Pages for Clients

Data transparency pages that show clients what the LLM used for decisions:

| Page Type | Content |
|-----------|---------|
| Room recommendations | All rooms evaluated with scores and reasoning |
| Q&A detail | Full answers to common questions |
| Offer breakdown | Detailed pricing, what's included |
| Availability calendar | Visual room availability |

**Storage:**
```sql
-- LATER: Create page_snapshots table
CREATE TABLE page_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,  -- 'room_eval', 'qa', 'offer', 'availability'
    data JSONB NOT NULL,
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    created_at TIMESTAMP DEFAULT NOW(),
    -- NOTE: No expires_at - links should NOT expire
);
```

**How it works:**
1. Workflow generates detailed data during processing
2. Data stored in `page_snapshots`
3. Email includes link: `yourdomain.com/info/{snapshot_id}`
4. Client clicks link → sees full reasoning
5. Links are permanent (no expiry)

---

*Document ends here. Last updated: 2025-12-08*