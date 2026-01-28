# AI Activity Logger - Integration Guide

## Overview

The AI Activity Logger provides visibility into what the AI did during each booking workflow. Designed for managers to trace event history and investigate issues.

---

## Quick Summary

| Aspect | Details |
|--------|---------|
| **API Cost** | **$0** - No additional LLM calls |
| **Storage** | ~10KB per event max (50 activities × 200 bytes) |
| **Persistence** | Stored in event database, survives restarts |
| **Timestamps** | Local timezone (not UTC) |

---

## Two Granularity Levels

Both levels are **manager-focused** (no technical debugging info).

### Coarse (High) - Main Milestones

Default view showing key business events:

| Category | Activities |
|----------|-----------|
| **CRM** | Client saved to CRM |
| **Calendar** | Event created (with status) |
| **Room Status** | Lead → Option → Confirmed → Cancelled |
| **Detours** | Date changed, Room changed, Participants changed, Products changed |
| **Requests** | Special requests noted |
| **Site Visit** | Site visit booked, Site visit completed |
| **Offer** | Offer sent, Offer accepted, Offer rejected, Price updated |
| **Deposit** | Deposit required, Deposit paid, Deposit updated, Billing updated |
| **Verification Failures** | Date denied, Room denied, Date conflict, Room conflict, Capacity exceeded |

### Fine (Detailed) - Investigation View

"Show More Details" for manager investigation:

| Category | Activities |
|----------|-----------|
| **Workflow Progress** | Processing inquiry, Confirming date, Checking availability, Preparing offer, Negotiation, Deposit processing, Finalizing |
| **Date Details** | Date confirmed, Dates suggested, Date checked |
| **Room Details** | Rooms checked (count), Room selected, Room reserved, Room released |
| **User Preferences** | Event type, Preferred date, Expected guests, Preferred room, Catering, Room setup, Equipment, Timing, Budget, Notes |
| **Contact Info** | Name, Email, Phone, Company, Address |
| **Manager Review** | Awaiting review, Approved, Edited response, Rejected |
| **Communication** | Email sent/received, Message sent/received |
| **Verification Checks** | Availability checked, Capacity checked, Pricing calculated |

---

## API Endpoints

### Progress Bar

```
GET /api/events/{event_id}/progress
```

Response:
```json
{
  "current_stage": "room",
  "stages": [
    {"id": "date", "label": "Date", "status": "completed", "icon": "📅"},
    {"id": "room", "label": "Room", "status": "active", "icon": "🏢"},
    {"id": "offer", "label": "Offer", "status": "pending", "icon": "📄"},
    {"id": "deposit", "label": "Deposit", "status": "pending", "icon": "💳"},
    {"id": "confirmed", "label": "Confirmed", "status": "pending", "icon": "✅"}
  ],
  "percentage": 40
}
```

### Activity Log

```
GET /api/events/{event_id}/activity?granularity=high&limit=50
```

Parameters:
- `granularity`: `high` (default, main milestones) or `detailed` (investigation view)
- `limit`: Max activities (default 50, max 200)

Response:
```json
{
  "activities": [
    {
      "id": "act_1706450000000",
      "timestamp": "2026-01-28T10:30:00",
      "icon": "📄",
      "title": "Offer Sent",
      "detail": "€500",
      "granularity": "high"
    }
  ],
  "has_more": false,
  "granularity": "high"
}
```

### Progress in Send-Message Response

The `/api/send-message` response now includes:
```json
{
  "response": "...",
  "progress": {
    "current_stage": "room",
    "percentage": 40
  }
}
```

---

## Cost Analysis

### API Costs: ZERO

The activity logger has **no additional API costs**:
- ✅ No extra LLM calls
- ✅ No external API calls
- ✅ Pure local logging (timestamp + strings)

### Storage Costs

| Scale | Monthly Events | Annual Storage | Action Needed |
|-------|----------------|----------------|---------------|
| Small | < 100 | ~5 MB | None |
| Medium | 100-1,000 | ~50 MB | None |
| Large | 1,000-10,000 | ~500 MB | Monitor |
| Enterprise | > 10,000 | > 5 GB | Consider archiving |

**Calculation:**
- ~200 bytes per activity
- Max 50 activities per event
- ~10 KB per event maximum

### When to Optimize

| Threshold | Recommendation |
|-----------|----------------|
| < 1,000 events/month | No action needed |
| 1,000-10,000 events/month | Monitor database size quarterly |
| > 10,000 events/month | Move to separate table, archive > 90 days |

---

## Supabase Integration

### Current: Embedded in Event Record

Activities stored in `events.activity_log` (JSONB array):

```sql
-- No schema change needed
-- activity_log is stored as JSONB in the event record
-- Example: {"activity_log": [{"icon": "📅", "title": "Date Confirmed", ...}]}
```

**Pros:**
- No new table
- No extra queries
- Simple implementation

**Cons:**
- Limited to ~50 activities per event
- Can't query activities independently

### Future: Separate Table (If Needed at Scale)

Only needed if:
- More than 10,000 events/month
- Need to query activities independently (e.g., "all offers sent today")
- Need activity analytics dashboard

```sql
CREATE TABLE event_activities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID REFERENCES events(id) ON DELETE CASCADE,
  timestamp TIMESTAMPTZ NOT NULL,
  icon TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT DEFAULT '',
  granularity TEXT NOT NULL CHECK (granularity IN ('high', 'detailed')),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for fast lookups by event
CREATE INDEX idx_activities_event_id ON event_activities(event_id);

-- Index for time-based queries
CREATE INDEX idx_activities_timestamp ON event_activities(timestamp DESC);

-- Index for granularity filtering
CREATE INDEX idx_activities_granularity ON event_activities(granularity);
```

**Migration Path:**
1. Create new table
2. Run migration script to copy existing `activity_log` arrays
3. Update `activity/persistence.py` to use Supabase adapter
4. Remove `activity_log` from event records after verification

---

## Integration Points

Activities are logged automatically for step transitions. Additional workflow events have hooks:

### Implemented (2026-01-28)

| Activity Key | Location | Status |
|--------------|----------|--------|
| `step_*_entered` | `workflows/io/database.py::update_event_metadata()` | ✅ Auto-logged |
| `status_*` | `workflows/io/database.py::update_event_metadata()` | ✅ Auto-logged |
| `date_confirmed` | `confirmation_flow.py:522` | ✅ Hooked |
| `date_denied` | `step2_handler.py:1031` | ✅ Hooked |
| `room_denied` | `step3_handler.py:1029` | ✅ Hooked |
| `offer_sent` | `step4_handler.py` | ✅ Hooked |
| `offer_accepted` | `step5_handler.py:899` | ✅ Hooked |
| `offer_rejected` | `step5_handler.py:1223` | ✅ Hooked |
| `status_cancelled` | `events.py:414` + `step7_handler.py:604` | ✅ Hooked |
| `deposit_paid` | `events.py:127` | ✅ Hooked |
| `date_changed` | `workflows/runtime/pre_route.py:685` (detour detection) | ✅ Hooked |
| `room_changed` | `workflows/runtime/pre_route.py:687` (detour detection) | ✅ Hooked |
| `site_visit_booked` | `workflows/common/site_visit_state.py:272` | ✅ Hooked |
| `event_created` | `workflows/io/database.py:389` | ✅ Hooked |
| `client_saved` | `workflows/io/database.py:241` | ✅ Hooked |

### Remaining (TODO)

| Activity Key | Where to Hook | Priority |
|--------------|---------------|----------|
| `deposit_set` | `workflows/steps/step4_offer/` when deposit configured | Low |
| `hil_*` | `workflows/runtime/hil_tasks.py` | Low |

---

## How to Add Activity Logging

### 1. Simple Activity

```python
from activity.persistence import log_workflow_activity

# In your workflow code:
log_workflow_activity(
    event_entry,
    "offer_sent",
    amount="€1,500"
)
```

### 2. Custom Activity

```python
from activity.persistence import log_activity

log_activity(
    event_entry,
    icon="🎉",
    title="Custom Milestone",
    detail="Additional context",
    granularity="high"  # or "detailed"
)
```

### 3. Adding New Activity Types

1. Add to `activity/persistence.py` WORKFLOW_ACTIVITIES:
```python
"new_activity": ("🎯", "Title Template", "{variable}"),
```

2. If it's a main milestone, add to COARSE_ACTIVITIES:
```python
COARSE_ACTIVITIES = {
    ...,
    "new_activity",
}
```

---

## Frontend Integration

### Progress Bar Component

```tsx
const ProgressBar = ({ eventId }: { eventId: string }) => {
  const { data } = useSWR(`/api/events/${eventId}/progress`);

  return (
    <div className="flex gap-2">
      {data?.stages.map(stage => (
        <div
          key={stage.id}
          className={`flex items-center gap-1 ${
            stage.status === 'completed' ? 'text-green-600' :
            stage.status === 'active' ? 'text-blue-600' :
            'text-gray-400'
          }`}
        >
          <span>{stage.icon}</span>
          <span>{stage.label}</span>
        </div>
      ))}
    </div>
  );
};
```

### Activity Feed Component

```tsx
const ActivityFeed = ({ eventId }: { eventId: string }) => {
  const [showDetails, setShowDetails] = useState(false);
  const granularity = showDetails ? 'detailed' : 'high';

  const { data } = useSWR(
    `/api/events/${eventId}/activity?granularity=${granularity}`
  );

  return (
    <div>
      <button onClick={() => setShowDetails(!showDetails)}>
        {showDetails ? 'Show Less' : 'Show More Details'}
      </button>

      <ul>
        {data?.activities.map(activity => (
          <li key={activity.id} className="flex gap-2">
            <span>{activity.icon}</span>
            <div>
              <strong>{activity.title}</strong>
              {activity.detail && <p>{activity.detail}</p>}
              <time>{activity.timestamp}</time>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};
```

### Timestamps

All timestamps are in **local timezone** (ISO format: `YYYY-MM-DDTHH:MM:SS`).
No `Z` suffix - display as-is or format with your preferred library.

---

## Files Reference

| File | Purpose |
|------|---------|
| `activity/__init__.py` | Module exports |
| `activity/types.py` | Activity, Progress, ProgressStage dataclasses |
| `activity/progress.py` | Step → stage mapping (1-7 → 5 stages) |
| `activity/persistence.py` | Database logging, retrieval, activity definitions |
| `activity/transformer.py` | Real-time trace → activity (for debugging) |
| `api/routes/activity.py` | REST endpoints |
| `tests/unit/test_activity.py` | Unit tests (27 tests) |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-01-28 | Additional hooks: date_changed, room_changed, site_visit_booked, event_created, client_saved |
| 2026-01-28 | Workflow hooks: date_confirmed, date_denied, room_denied, offer_sent, deposit_paid |
| 2026-01-28 | Fixed: date_confirmed now "high" granularity (was incorrectly "detailed") |
| 2026-01-28 | Fixed: deposit_required template (removed missing due_date placeholder) |
| 2026-01-28 | Initial implementation with two granularity levels |
