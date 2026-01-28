# API Endpoint Tests

All endpoints tested without frontend.

**Last updated:** 2026-01-28 (full audit: added emails, cancel, config, agent/chatkit endpoints; total: 70+)

---

## Authentication

Most endpoints require the `X-Team-Id` header for multi-tenancy:

```bash
# Required header for authenticated endpoints
-H "X-Team-Id: your-team-id"
```

**Public endpoints (no auth required):**
- `GET /` - Root health check
- `GET /api/workflow/health` - Workflow health

---

## How to Run Tests

```bash
# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Run tests (in another terminal)
curl http://localhost:8000/api/workflow/health
```

---

## Test Results

### SECTION 1: Health & Status

---

### TEST 1: GET / (Root Health)
```
INPUT:    curl http://localhost:8000/
EXPECTED: {status, active_conversations, total_saved_events}
OUTPUT:   {"status":"ok","active_conversations":3,"total_saved_events":12}
RESULT:   PASS
```

---

### TEST 2: GET /api/workflow/health
```
INPUT:    curl http://localhost:8000/api/workflow/health
EXPECTED: {"ok": true, "db_path": "..."}
OUTPUT:   {"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
RESULT:   PASS
```

---

### TEST 3: GET /api/workflow/hil-status
```
INPUT:    curl http://localhost:8000/api/workflow/hil-status
EXPECTED: {"hil_all_replies_enabled": boolean}
OUTPUT:   {"hil_all_replies_enabled":false}
RESULT:   PASS
```

---

### SECTION 2: Conversation Flow

---

### TEST 4: POST /api/start-conversation
```
INPUT:    curl -X POST http://localhost:8000/api/start-conversation \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"client_email":"test@test.com","client_name":"Test User","email_body":"Book room for 25 people on April 10, 2025"}'

EXPECTED: {session_id, response, event_info, pending_actions}

OUTPUT:   {
            "session_id": "9daefa5a-1a42-49ef-9062-948e56d2c6ef",
            "workflow_type": "new_event",
            "response": "Availability overview\n\nDate options for April...",
            "is_complete": false,
            "event_info": {
              "number_of_participants": "25",
              "email": "test@test.com",
              ...
            },
            "pending_actions": {...}
          }

RESULT:   PASS
```

---

### TEST 5: POST /api/send-message
```
INPUT:    curl -X POST http://localhost:8000/api/send-message \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"session_id":"9daefa5a-1a42-49ef-9062-948e56d2c6ef","message":"Let us do December 17"}'

EXPECTED: {session_id, response, event_info}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "response": "Noted 17.12.2025. Preferred time? Examples: 14-18, 18-22.",
            "event_info": {
              "event_date": "17.12.2025",
              ...
            }
          }

RESULT:   PASS
```

---

### TEST 6: GET /api/conversation/{session_id}
```
INPUT:    curl http://localhost:8000/api/conversation/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "X-Team-Id: team-demo"

EXPECTED: {session_id, messages, event_info, current_step}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "messages": [...],
            "event_info": {...},
            "current_step": 2
          }

RESULT:   PASS
```

---

### TEST 7: POST /api/conversation/{session_id}/confirm-date
```
INPUT:    curl -X POST http://localhost:8000/api/conversation/9daefa5a-1a42-49ef-9062-948e56d2c6ef/confirm-date \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"confirmed_date": "2025-12-17"}'

EXPECTED: {status, event_info}
RESULT:   PASS (confirms selected date)
```

---

### TEST 8: POST /api/accept-booking/{session_id}
```
INPUT:    curl -X POST http://localhost:8000/api/accept-booking/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", event_id, message}

NOTES:    Saves the booking to database and marks event as confirmed.
RESULT:   PASS
```

---

### TEST 9: POST /api/reject-booking/{session_id}
```
INPUT:    curl -X POST http://localhost:8000/api/reject-booking/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", message}

NOTES:    Discards the booking without saving.
RESULT:   PASS
```

---

### SECTION 3: Task Management (HIL)

---

### TEST 10: GET /api/tasks/pending
```
INPUT:    curl http://localhost:8000/api/tasks/pending \
            -H "X-Team-Id: team-demo"

EXPECTED: {"tasks": [...]}
OUTPUT:   {"tasks": [...]} (returns list of pending HIL tasks)
RESULT:   PASS
```

---

### TEST 11: POST /api/tasks/{task_id}/approve
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/approve \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"notes":"Approved by manager","edited_message":"Optional edited text"}'

EXPECTED: {task_id, task_status: "approved", assistant_reply, thread_id, event_id}

OUTPUT:   {
            "task_id": "...",
            "task_status": "approved",
            "assistant_reply": "The approved message...",
            "thread_id": "...",
            "event_id": "..."
          }

RESULT:   PASS
```

---

### TEST 12: POST /api/tasks/{task_id}/reject
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/reject \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"notes":"Rejected - needs revision"}'

EXPECTED: {task_id, task_status: "rejected", ...}
RESULT:   PASS
```

---

### TEST 13: POST /api/tasks/cleanup
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/cleanup \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", removed_count: number}

NOTES:    Removes resolved/old tasks from the pending list.
RESULT:   PASS
```

---

### SECTION 4: Event Management

---

### TEST 14: GET /api/events
```
INPUT:    curl http://localhost:8000/api/events \
            -H "X-Team-Id: team-demo"

EXPECTED: {events: [{event_id, client_email, event_date, status, ...}, ...]}

NOTES:    Lists all saved events for the team.
RESULT:   PASS
```

---

### TEST 15: GET /api/events/{event_id}
```
INPUT:    curl http://localhost:8000/api/events/evt_abc123 \
            -H "X-Team-Id: team-demo"

EXPECTED: {event_id, client_email, event_date, status, requirements, ...}

NOTES:    Returns full event details.
RESULT:   PASS
```

---

### TEST 16: GET /api/event/{event_id}/deposit
```
INPUT:    curl http://localhost:8000/api/event/evt_abc123/deposit \
            -H "X-Team-Id: team-demo"

EXPECTED: {event_id, deposit_required, deposit_amount, deposit_paid, deposit_due_date}

NOTES:    Returns deposit status for an event.
RESULT:   PASS
```

---

### TEST 17: POST /api/event/deposit/pay
```
INPUT:    curl -X POST http://localhost:8000/api/event/deposit/pay \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"event_id":"evt_abc123"}'

EXPECTED: {status: "ok", event_id, deposit_amount, deposit_paid_at}

NOTES:    Marks deposit as paid and triggers workflow continuation.
RESULT:   PASS
```

---

### TEST 17b: GET /api/events/{event_id}/progress
```
INPUT:    curl http://localhost:8000/api/events/evt_abc123/progress \
            -H "X-Team-Id: team-demo"

EXPECTED: {
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

NOTES:    Returns workflow progress bar state. Maps 7-step workflow to 5 visual stages.
          Stage status: "completed" | "active" | "pending"
RESULT:   PASS
```

---

### TEST 17c: GET /api/events/{event_id}/activity (Coarse)
```
INPUT:    curl "http://localhost:8000/api/events/evt_abc123/activity?granularity=high&limit=20" \
            -H "X-Team-Id: team-demo"

EXPECTED: {
  "activities": [
    {
      "id": "act_1706450000000",
      "timestamp": "2026-01-28T10:30:00",
      "icon": "📄",
      "title": "Offer Sent",
      "detail": "€1,500",
      "granularity": "high"
    }
  ],
  "has_more": false,
  "granularity": "high"
}

NOTES:    Returns AI activity log. Default granularity=high shows main milestones only.
          Timestamps are LOCAL timezone (not UTC).
          Activities persist in database (survives restarts).
RESULT:   PASS
```

---

### TEST 17d: GET /api/events/{event_id}/activity (Fine/Detailed)
```
INPUT:    curl "http://localhost:8000/api/events/evt_abc123/activity?granularity=detailed&limit=50" \
            -H "X-Team-Id: team-demo"

EXPECTED: {
  "activities": [
    {"icon": "📄", "title": "Preparing Offer", "granularity": "detailed", ...},
    {"icon": "👤", "title": "Name Captured", "detail": "John Smith", "granularity": "detailed", ...},
    {"icon": "📧", "title": "Email Captured", "detail": "john@example.com", "granularity": "detailed", ...},
    {"icon": "📄", "title": "Offer Sent", "detail": "€1,500", "granularity": "high", ...}
  ],
  "has_more": false,
  "granularity": "detailed"
}

NOTES:    granularity=detailed shows breakdown of each milestone.
          Fine view includes: contact info captured, rooms checked, manager actions, etc.
          Both high and detailed activities are manager-focused (no technical debugging).
RESULT:   PASS
```

---

### SECTION 5: Configuration

---

### TEST 18: GET /api/config/global-deposit
```
INPUT:    curl http://localhost:8000/api/config/global-deposit \
            -H "X-Team-Id: team-demo"

EXPECTED: {deposit_enabled, deposit_type, deposit_percentage, ...}
OUTPUT:   {"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":30,"deposit_fixed_amount":0.0,"deposit_deadline_days":14}
RESULT:   PASS
```

---

### TEST 19: POST /api/config/global-deposit
```
INPUT:    curl -X POST http://localhost:8000/api/config/global-deposit \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":25,"deposit_deadline_days":7}'

EXPECTED: {status: "ok", config: {...}}

NOTES:    Updates global deposit configuration for all offers.
RESULT:   PASS
```

---

### TEST 20: GET /api/config/hil-mode
```
INPUT:    curl http://localhost:8000/api/config/hil-mode \
            -H "X-Team-Id: team-demo"

EXPECTED: {enabled: boolean, source: "database"|"environment"|"default"}

OUTPUT:   {"enabled":false,"source":"default"}

NOTES:    Returns current HIL mode status and where the setting comes from.
          Priority: database > environment variable > default (false)
RESULT:   PASS
```

---

### TEST 21: POST /api/config/hil-mode
```
INPUT:    curl -X POST http://localhost:8000/api/config/hil-mode \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"enabled": true}'

EXPECTED: {status: "ok", enabled: boolean, message: "..."}

OUTPUT:   {
            "status": "ok",
            "enabled": true,
            "message": "HIL mode enabled. All AI replies now require manager approval."
          }

NOTES:    When enabled, ALL AI-generated replies go to the "AI Reply Approval"
          queue for manager review before being sent to clients.
          This is RECOMMENDED for production.
RESULT:   PASS
```

---

### TEST 22: GET /api/config/prompts
```
INPUT:    curl http://localhost:8000/api/config/prompts \
            -H "X-Team-Id: team-demo"

EXPECTED: {system_prompt, step_prompts: {...}, last_updated}

NOTES:    Returns current LLM prompt configurations.
RESULT:   PASS
```

---

### TEST 23: POST /api/config/prompts
```
INPUT:    curl -X POST http://localhost:8000/api/config/prompts \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"system_prompt":"You are a helpful venue booking assistant...","step_prompts":{...}}'

EXPECTED: {status: "ok", version: number}

NOTES:    Saves new prompt configuration. Previous version is archived.
RESULT:   PASS
```

---

### TEST 24: GET /api/config/prompts/history
```
INPUT:    curl http://localhost:8000/api/config/prompts/history \
            -H "X-Team-Id: team-demo"

EXPECTED: {history: [{version, timestamp, changes}, ...]}

NOTES:    Returns last 50 prompt configuration versions.
RESULT:   PASS
```

---

### TEST 25: POST /api/config/prompts/revert/{index}
```
INPUT:    curl -X POST http://localhost:8000/api/config/prompts/revert/3 \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", reverted_to_version: number}

NOTES:    Reverts to a previous prompt configuration version.
RESULT:   PASS
```

---

### SECTION 6: Test Data & Q&A

---

### TEST 26: GET /api/qna
```
INPUT:    curl http://localhost:8000/api/qna
EXPECTED: {data: {...}, query: {...}}
OUTPUT:   {"query":{},"result_type":"general","data":{...}}
RESULT:   PASS
```

---

### TEST 27: GET /api/test-data/rooms
```
INPUT:    curl http://localhost:8000/api/test-data/rooms

EXPECTED: [{room_id, name, capacity, amenities, ...}, ...]

NOTES:    Returns room availability data for test pages.
RESULT:   PASS
```

---

### TEST 28: GET /api/test-data/catering
```
INPUT:    curl http://localhost:8000/api/test-data/catering
EXPECTED: [{name, slug, price_per_person, ...}, ...]
OUTPUT:   [{"name":"Seasonal Garden Trio","slug":"seasonal-garden-trio","price_per_person":"CHF 92",...},...]
RESULT:   PASS
```

---

### TEST 29: GET /api/test-data/catering/{menu_slug}
```
INPUT:    curl http://localhost:8000/api/test-data/catering/seasonal-garden-trio

EXPECTED: {name, slug, price_per_person, description, courses, ...}

NOTES:    Returns specific catering menu details.
RESULT:   PASS
```

---

### TEST 30: GET /api/test-data/qna (Legacy)
```
INPUT:    curl http://localhost:8000/api/test-data/qna

EXPECTED: {...}

NOTES:    Legacy Q&A endpoint. Use /api/qna instead.
RESULT:   PASS
```

---

### SECTION 7: Snapshots

---

### TEST 31: GET /api/snapshots
```
INPUT:    curl http://localhost:8000/api/snapshots \
            -H "X-Team-Id: team-demo"

EXPECTED: {snapshots: [{snapshot_id, type, created_at, ...}, ...]}

QUERY PARAMS:
  - type: Filter by snapshot type
  - event_id: Filter by event ID
  - limit: Max results (default: 50)

RESULT:   PASS
```

---

### TEST 32: GET /api/snapshots/{snapshot_id}
```
INPUT:    curl http://localhost:8000/api/snapshots/snap_abc123 \
            -H "X-Team-Id: team-demo"

EXPECTED: {snapshot_id, type, data, metadata, created_at}

NOTES:    Returns full snapshot with page data.
RESULT:   PASS
```

---

### TEST 33: GET /api/snapshots/{snapshot_id}/data
```
INPUT:    curl http://localhost:8000/api/snapshots/snap_abc123/data \
            -H "X-Team-Id: team-demo"

EXPECTED: {...data payload only...}

NOTES:    Returns only the data payload, no metadata.
RESULT:   PASS
```

---

### SECTION 8: Debug (Conditional)

**Requires:** `DEBUG_TRACE_ENABLED=true` environment variable

---

### TEST 34: GET /api/debug/threads/{thread_id}
```
INPUT:    curl http://localhost:8000/api/debug/threads/9daefa5a-1a42-49ef-9062-948e56d2c6ef

EXPECTED: {thread_id, events, state, ...}

QUERY PARAMS:
  - granularity: "logic" or other levels

NOTES:    Full debug trace for a conversation thread.
RESULT:   PASS (when DEBUG_TRACE_ENABLED=true)
```

---

### TEST 35: GET /api/debug/threads/{thread_id}/timeline
```
INPUT:    curl "http://localhost:8000/api/debug/threads/THREAD_ID/timeline?granularity=logic"

EXPECTED: {timeline: [{timestamp, event_type, data}, ...]}

QUERY PARAMS:
  - granularity: Filter level
  - kinds: Comma-separated event types
  - as_of_ts: Filter by timestamp

RESULT:   PASS
```

---

### TEST 36: GET /api/debug/threads/{thread_id}/timeline/download
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/timeline/download

EXPECTED: JSONL file download

NOTES:    Downloads timeline as JSONL file.
RESULT:   PASS
```

---

### TEST 37: GET /api/debug/threads/{thread_id}/timeline/text
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/timeline/text

EXPECTED: Plain text timeline

NOTES:    Human-readable text format.
RESULT:   PASS
```

---

### TEST 38: GET /api/debug/threads/{thread_id}/report
```
INPUT:    curl "http://localhost:8000/api/debug/threads/THREAD_ID/report?persist=true"

EXPECTED: {report: {...}, report_id}

NOTES:    Comprehensive debug report. Use persist=true to save.
RESULT:   PASS
```

---

### TEST 39: GET /api/debug/threads/{thread_id}/llm-diagnosis
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/llm-diagnosis

EXPECTED: {diagnosis: {...}}

NOTES:    LLM-optimized diagnosis for debugging issues.
RESULT:   PASS
```

---

### TEST 40: GET /api/debug/live
```
INPUT:    curl http://localhost:8000/api/debug/live

EXPECTED: {active_threads: [thread_id, ...]}

NOTES:    Lists thread IDs with active live logs.
RESULT:   PASS
```

---

### TEST 41: GET /api/debug/threads/{thread_id}/live
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/live

EXPECTED: {log_content: "..."}

NOTES:    Live log content for real-time debugging.
RESULT:   PASS
```

---

### SECTION 9: Dev-Only Utilities

**Requires:** `ENABLE_DANGEROUS_ENDPOINTS=true` environment variable

**WARNING:** These endpoints are disabled by default for security.

---

### TEST 42: POST /api/client/reset (DEV ONLY)
```
INPUT:    curl -X POST http://localhost:8000/api/client/reset \
            -H "Content-Type: application/json" \
            -d '{"email":"test@test.com"}'

EXPECTED: {status: "ok", deleted_events: number, deleted_tasks: number}

NOTES:    Resets all client data by email. DEV/TEST ONLY.
RESULT:   PASS (when ENABLE_DANGEROUS_ENDPOINTS=true)
```

---

### TEST 43: POST /api/client/continue (DEV ONLY)
```
INPUT:    curl -X POST http://localhost:8000/api/client/continue \
            -H "Content-Type: application/json" \
            -d '{"session_id":"..."}'

EXPECTED: {status: "ok"}

NOTES:    Continues workflow bypassing dev choice prompt. DEV ONLY.
RESULT:   PASS (when ENABLE_DANGEROUS_ENDPOINTS=true)
```

---

### SECTION 10: Email Sending

**Route file:** `api/routes/emails.py` (prefix: `/api/emails`)

---

### TEST 44: POST /api/emails/send-to-client
```
INPUT:    curl -X POST http://localhost:8000/api/emails/send-to-client \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"to_email":"client@test.com","to_name":"Test Client","subject":"Booking confirmation","body_text":"Your room is confirmed.","event_id":"evt_abc123","task_id":"task_123"}'

EXPECTED: {success: true, message: "...", to_email, subject}

NOTES:    Called AFTER HIL approval to send actual email to client.
          Returns simulated=true when SMTP not configured.
          Applies plain text conversion if email-format config is set.
RESULT:   PASS
```

---

### TEST 45: POST /api/emails/send-offer
```
INPUT:    curl -X POST http://localhost:8000/api/emails/send-offer \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"event_id":"evt_abc123","subject":"Event Offer - 17.12.2025","custom_message":"Looking forward to your event!"}'

EXPECTED: {success: true, message: "...", offer_total: number}

NOTES:    Composes and sends an offer email using event data.
          Event must exist and have client email.
          Returns simulated=true when SMTP not configured.
RESULT:   PASS
```

---

### TEST 46: POST /api/emails/test
```
INPUT:    curl -X POST http://localhost:8000/api/emails/test \
            -H "Content-Type: application/json" \
            -d '{"to_email":"admin@test.com","to_name":"Admin"}'

EXPECTED: {success: true} or {success: false, error: "SMTP not configured..."}

NOTES:    Verifies SMTP configuration by sending a test email.
          Requires ENABLE_TEST_ENDPOINTS=true.
RESULT:   PASS (when ENABLE_TEST_ENDPOINTS=true)
```

---

### SECTION 11: Event Cancellation

**Route file:** `api/routes/events.py`

---

### TEST 47: POST /api/event/{event_id}/cancel
```
INPUT:    curl -X POST http://localhost:8000/api/event/evt_abc123/cancel \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"event_id":"evt_abc123","confirmation":"CANCEL","reason":"Client changed plans"}'

EXPECTED: {status: "cancelled", event_id, previous_step, had_site_visit, cancellation_type, archived_at}

NOTES:    Manager action. Confirmation must be exactly "CANCEL" (case-sensitive).
          Event is archived (not deleted) for audit trail.
          cancellation_type is "site_visit" if step >= 7, otherwise "standard".
          Returns {status: "already_cancelled"} if already cancelled.
RESULT:   PASS
```

---

### SECTION 12: Configuration (Extended)

**Route file:** `api/routes/config.py` (prefix: `/api/config`)

All config endpoints follow GET (read) / POST (write) pattern.

---

### TEST 48: GET /api/config/email-format
```
INPUT:    curl http://localhost:8000/api/config/email-format \
            -H "X-Team-Id: team-demo"

EXPECTED: {plain_text: boolean, source: "environment"|"default"}

NOTES:    Controls whether client emails strip Markdown formatting.
RESULT:   PASS
```

---

### TEST 49: POST /api/config/email-format
```
INPUT:    curl -X POST http://localhost:8000/api/config/email-format \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"plain_text": true}'

EXPECTED: {status: "ok", message: "..."}

NOTES:    Info endpoint - actual setting controlled via EMAIL_PLAIN_TEXT env var.
RESULT:   PASS
```

---

### TEST 50: GET /api/config/llm-provider
```
INPUT:    curl http://localhost:8000/api/config/llm-provider \
            -H "X-Team-Id: team-demo"

EXPECTED: {intent_provider, entity_provider, verbalization_provider, available_providers: [...]}

NOTES:    Shows which LLM handles intent/entity/verbalization.
          Default hybrid: Gemini for detection, OpenAI for verbalization.
RESULT:   PASS
```

---

### TEST 51: POST /api/config/llm-provider
```
INPUT:    curl -X POST http://localhost:8000/api/config/llm-provider \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"intent_provider":"gemini","entity_provider":"gemini","verbalization_provider":"openai"}'

EXPECTED: {status: "ok", ...}

NOTES:    Valid providers: "openai", "gemini", "stub"
RESULT:   PASS
```

---

### TEST 52: GET /api/config/hybrid-enforcement
```
INPUT:    curl http://localhost:8000/api/config/hybrid-enforcement \
            -H "X-Team-Id: team-demo"

EXPECTED: {enabled: boolean, ...}

NOTES:    Shows whether hybrid mode enforcement is active.
RESULT:   PASS
```

---

### TEST 53: POST /api/config/hybrid-enforcement
```
INPUT:    curl -X POST http://localhost:8000/api/config/hybrid-enforcement \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"enabled": true}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 54: GET /api/config/pre-filter
```
INPUT:    curl http://localhost:8000/api/config/pre-filter \
            -H "X-Team-Id: team-demo"

EXPECTED: {mode: "enhanced"|"legacy", ...}

NOTES:    "enhanced" = full keyword detection + signal flags.
          "legacy" = basic duplicate detection only.
RESULT:   PASS
```

---

### TEST 55: POST /api/config/pre-filter
```
INPUT:    curl -X POST http://localhost:8000/api/config/pre-filter \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"mode": "enhanced"}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 56: GET /api/config/detection-mode
```
INPUT:    curl http://localhost:8000/api/config/detection-mode \
            -H "X-Team-Id: team-demo"

EXPECTED: {mode: "unified"|"legacy", ...}

NOTES:    "unified" = new LLM-first detection pipeline.
          "legacy" = older keyword-based detection.
RESULT:   PASS
```

---

### TEST 57: POST /api/config/detection-mode
```
INPUT:    curl -X POST http://localhost:8000/api/config/detection-mode \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"mode": "unified"}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 58: GET /api/config/hil-email
```
INPUT:    curl http://localhost:8000/api/config/hil-email \
            -H "X-Team-Id: team-demo"

EXPECTED: {smtp_host, smtp_port, smtp_user, from_email, from_name, ...}

NOTES:    HIL email notification settings (how the system emails managers).
RESULT:   PASS
```

---

### TEST 59: POST /api/config/hil-email
```
INPUT:    curl -X POST http://localhost:8000/api/config/hil-email \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"smtp_host":"smtp.example.com","smtp_port":587,"smtp_user":"user@example.com","from_email":"noreply@example.com","from_name":"OpenEvent"}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 60: POST /api/config/hil-email/test
```
INPUT:    curl -X POST http://localhost:8000/api/config/hil-email/test \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"to_email":"admin@test.com"}'

EXPECTED: {success: true|false, message: "..."}

NOTES:    Sends a test HIL notification email to verify SMTP settings.
RESULT:   PASS
```

---

### TEST 61: GET /api/config/venue
```
INPUT:    curl http://localhost:8000/api/config/venue \
            -H "X-Team-Id: team-demo"

EXPECTED: {name, city, timezone, ...}

NOTES:    Venue identity settings used in all client communications.
RESULT:   PASS
```

---

### TEST 62: POST /api/config/venue
```
INPUT:    curl -X POST http://localhost:8000/api/config/venue \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"name":"Grand Hotel","city":"Zurich","timezone":"Europe/Zurich"}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 63: GET /api/config/site-visit
```
INPUT:    curl http://localhost:8000/api/config/site-visit \
            -H "X-Team-Id: team-demo"

EXPECTED: {blocked_dates: [...], slots: [...], weekday_rules: {...}}

NOTES:    Site visit scheduling configuration (Step 7).
RESULT:   PASS
```

---

### TEST 64: POST /api/config/site-visit
```
INPUT:    curl -X POST http://localhost:8000/api/config/site-visit \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"blocked_dates":["2025-12-25"],"slots":["10:00","14:00"]}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 65: GET /api/config/managers
```
INPUT:    curl http://localhost:8000/api/config/managers \
            -H "X-Team-Id: team-demo"

EXPECTED: {managers: [{name, email, ...}, ...]}

NOTES:    Manager list for escalation and HIL routing.
RESULT:   PASS
```

---

### TEST 66: POST /api/config/managers
```
INPUT:    curl -X POST http://localhost:8000/api/config/managers \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"managers":[{"name":"John","email":"john@venue.com"}]}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 67: GET /api/config/products
```
INPUT:    curl http://localhost:8000/api/config/products \
            -H "X-Team-Id: team-demo"

EXPECTED: {autofill_threshold: number, ...}

NOTES:    Product autofill settings (when to auto-add products to offers).
RESULT:   PASS
```

---

### TEST 68: POST /api/config/products
```
INPUT:    curl -X POST http://localhost:8000/api/config/products \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"autofill_threshold":0.8}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 69: GET /api/config/menus
```
INPUT:    curl http://localhost:8000/api/config/menus \
            -H "X-Team-Id: team-demo"

EXPECTED: {menus: [...]}

NOTES:    Catering menu settings.
RESULT:   PASS
```

---

### TEST 70: POST /api/config/menus
```
INPUT:    curl -X POST http://localhost:8000/api/config/menus \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"menus":[...]}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 71: GET /api/config/catalog
```
INPUT:    curl http://localhost:8000/api/config/catalog \
            -H "X-Team-Id: team-demo"

EXPECTED: {catalog: {...}}

NOTES:    Product-room availability mapping.
RESULT:   PASS
```

---

### TEST 72: POST /api/config/catalog
```
INPUT:    curl -X POST http://localhost:8000/api/config/catalog \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"catalog":{...}}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### TEST 73: GET /api/config/faq
```
INPUT:    curl http://localhost:8000/api/config/faq \
            -H "X-Team-Id: team-demo"

EXPECTED: {faq: [...]}

NOTES:    FAQ entries for Q&A engine.
RESULT:   PASS
```

---

### TEST 74: POST /api/config/faq
```
INPUT:    curl -X POST http://localhost:8000/api/config/faq \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"faq":[...]}'

EXPECTED: {status: "ok", ...}
RESULT:   PASS
```

---

### SECTION 13: Agent / ChatKit Endpoints (Real-Time Streaming)

**Route file:** `api/agent_router.py` (prefix: `/api/agent`)

**Purpose:** These endpoints enable **real-time streaming chat** as an alternative to the
email-based workflow. They use the same workflow engine but deliver responses as SSE streams.

#### Current Usage

| Frontend | API Used | Why |
|----------|----------|-----|
| **Main OpenEvent App** (production) | `/api/send-message` | Email-based workflow; async, not real-time |
| **Test Frontend** (`atelier-ai-frontend/`) | `/api/send-message` | Manager dashboard testing |
| **Test Frontend** `/agent` page | `/api/agent/chatkit/*` | Streaming demo with ChatKit library |

**The main production app uses email-based communication, not real-time chat.**
ChatKit endpoints exist for:
1. The `/agent` demo page in the test frontend
2. Future use: embedded chat widgets on public websites

#### When to use which?

| Use Case | Endpoint | Why |
|----------|----------|-----|
| Email workflow (production) | `/api/send-message` | JSON, async processing |
| Manager dashboard testing | `/api/send-message` | JSON, complete responses |
| Real-time chat widget | `/api/agent/chatkit/respond` | SSE streaming, tokens appear live |
| Programmatic/webhook access | `/api/agent/reply` | JSON, non-streaming |

**Both paths hit the same workflow engine** — the difference is response format:
- `/api/send-message` → waits for entire workflow, returns JSON
- `/api/agent/chatkit/respond` → streams tokens as LLM generates them (SSE)

---

### TEST 75: POST /api/agent/reply
```
INPUT:    curl -X POST http://localhost:8000/api/agent/reply \
            -H "Content-Type: application/json" \
            -d '{"thread_id":"abc123","message":"Book a room for 20 people","from_email":"client@test.com"}'

EXPECTED: {thread_id, response, requires_hil, action, payload}

NOTES:    Non-streaming JSON response. Use for programmatic access.
          Tries: OpenAI Agents SDK → OpenAI Chat API → Deterministic Workflow (fallback).
RESULT:   PASS
```

---

### TEST 76: POST /api/agent/chatkit/session
```
INPUT:    curl -X POST http://localhost:8000/api/agent/chatkit/session \
            -H "Content-Type: application/json" \
            -d '{"from_email":"client@test.com"}'

EXPECTED: {client_secret: "random-token-xyz"}

NOTES:    Mints ephemeral auth token for ChatKit widget initialization.
          Token is not persisted — backend authenticates on thread_id instead.
          Required by @openai/chatkit-react library.
RESULT:   PASS
```

---

### TEST 77: POST /api/agent/chatkit/respond
```
INPUT:    curl -X POST http://localhost:8000/api/agent/chatkit/respond \
            -H "Content-Type: application/json" \
            -d '{"thread_id":"abc123","text":"I need a room for April 10"}'

EXPECTED: StreamingResponse (SSE format: data: {"delta": "text"}\n\n)

NOTES:    Streams tokens in real-time as LLM generates them.
          Uses step-aware agent runner with tool gating per workflow step.
          Falls back to deterministic workflow if OpenAI unavailable.
RESULT:   PASS
```

---

### TEST 78: POST /api/agent/chatkit/upload
```
INPUT:    curl -X POST http://localhost:8000/api/agent/chatkit/upload \
            -H "Content-Type: multipart/form-data" \
            -F "file=@document.pdf" \
            -F "thread_id=abc123"

EXPECTED: {file_name, content_type, size}

NOTES:    File upload for ChatKit conversations. Max 10MB (configurable via MAX_UPLOAD_SIZE_MB).
          Allowed types: images (jpeg/png/gif/webp), PDF, text, CSV, JSON.
          Currently returns metadata only — file handling is a placeholder for future features.
RESULT:   PASS
```

---

## Summary

### Core Endpoints (Always Available)

| # | Endpoint | Method | Category | Notes |
|---|----------|--------|----------|-------|
| 1 | `/` | GET | Health | Root status |
| 2 | `/api/workflow/health` | GET | Health | Workflow health |
| 3 | `/api/workflow/hil-status` | GET | Health | HIL toggle status |
| 4 | `/api/start-conversation` | POST | Conversation | Start workflow |
| 5 | `/api/send-message` | POST | Conversation | Continue chat |
| 6 | `/api/conversation/{id}` | GET | Conversation | Get state |
| 7 | `/api/conversation/{id}/confirm-date` | POST | Conversation | Confirm date |
| 8 | `/api/accept-booking/{id}` | POST | Conversation | Accept booking |
| 9 | `/api/reject-booking/{id}` | POST | Conversation | Reject booking |
| 10 | `/api/tasks/pending` | GET | Tasks | List pending |
| 11 | `/api/tasks/{id}/approve` | POST | Tasks | Approve task |
| 12 | `/api/tasks/{id}/reject` | POST | Tasks | Reject task |
| 13 | `/api/tasks/cleanup` | POST | Tasks | Clean old tasks |
| 14 | `/api/events` | GET | Events | List events |
| 15 | `/api/events/{id}` | GET | Events | Get event |
| 16 | `/api/event/{id}/deposit` | GET | Events | Deposit status |
| 17 | `/api/event/deposit/pay` | POST | Events | Mark paid (test only) |
| 17b | `/api/events/{id}/progress` | GET | Activity | Workflow progress bar |
| 17c | `/api/events/{id}/activity` | GET | Activity | AI activity log |
| 18 | `/api/event/{id}/cancel` | POST | Events | Cancel event |
| 19 | `/api/emails/send-to-client` | POST | Emails | Send email after HIL approval |
| 20 | `/api/emails/send-offer` | POST | Emails | Send offer email |
| 21 | `/api/config/global-deposit` | GET | Config | Get deposit cfg |
| 22 | `/api/config/global-deposit` | POST | Config | Set deposit cfg |
| 23 | `/api/config/hil-mode` | GET | Config | Get HIL mode |
| 24 | `/api/config/hil-mode` | POST | Config | Toggle HIL |
| 25 | `/api/config/email-format` | GET | Config | Get email format |
| 26 | `/api/config/email-format` | POST | Config | Set email format |
| 27 | `/api/config/llm-provider` | GET | Config | Get LLM providers |
| 28 | `/api/config/llm-provider` | POST | Config | Set LLM providers |
| 29 | `/api/config/hybrid-enforcement` | GET | Config | Get hybrid enforcement |
| 30 | `/api/config/hybrid-enforcement` | POST | Config | Set hybrid enforcement |
| 31 | `/api/config/pre-filter` | GET | Config | Get pre-filter mode |
| 32 | `/api/config/pre-filter` | POST | Config | Set pre-filter mode |
| 33 | `/api/config/detection-mode` | GET | Config | Get detection mode |
| 34 | `/api/config/detection-mode` | POST | Config | Set detection mode |
| 35 | `/api/config/prompts` | GET | Config | Get prompts |
| 36 | `/api/config/prompts` | POST | Config | Set prompts |
| 37 | `/api/config/prompts/history` | GET | Config | Prompt history |
| 38 | `/api/config/prompts/revert/{idx}` | POST | Config | Revert prompts |
| 39 | `/api/config/hil-email` | GET | Config | Get HIL email cfg |
| 40 | `/api/config/hil-email` | POST | Config | Set HIL email cfg |
| 41 | `/api/config/hil-email/test` | POST | Config | Test HIL email |
| 42 | `/api/config/venue` | GET | Config | Get venue settings |
| 43 | `/api/config/venue` | POST | Config | Set venue settings |
| 44 | `/api/config/site-visit` | GET | Config | Get site visit cfg |
| 45 | `/api/config/site-visit` | POST | Config | Set site visit cfg |
| 46 | `/api/config/managers` | GET | Config | Get managers |
| 47 | `/api/config/managers` | POST | Config | Set managers |
| 48 | `/api/config/products` | GET | Config | Get product cfg |
| 49 | `/api/config/products` | POST | Config | Set product cfg |
| 50 | `/api/config/menus` | GET | Config | Get menus cfg |
| 51 | `/api/config/menus` | POST | Config | Set menus cfg |
| 52 | `/api/config/catalog` | GET | Config | Get catalog cfg |
| 53 | `/api/config/catalog` | POST | Config | Set catalog cfg |
| 54 | `/api/config/faq` | GET | Config | Get FAQ cfg |
| 55 | `/api/config/faq` | POST | Config | Set FAQ cfg |
| 56 | `/api/snapshots` | GET | Snapshots | List |
| 57 | `/api/snapshots/{id}` | GET | Snapshots | Get snapshot |
| 58 | `/api/snapshots/{id}/data` | GET | Snapshots | Data only |
| 59 | `/api/qna` | GET | Data | Q&A queries |
| 60 | `/api/test-data/rooms` | GET | Data | Room data |
| 61 | `/api/test-data/catering` | GET | Data | Catering menus |
| 62 | `/api/test-data/catering/{slug}` | GET | Data | Menu details |
| 63 | `/api/test-data/qna` | GET | Data | Legacy Q&A |
| 64 | `/api/config/room-deposit/{id}` | GET | Config | Room deposit cfg |
| 65 | `/api/config/room-deposit/{id}` | POST | Config | Set room deposit |

### Agent / ChatKit Endpoints (Always Available)

| # | Endpoint | Method | Notes |
|---|----------|--------|-------|
| 66 | `/api/agent/reply` | POST | Non-streaming JSON response |
| 67 | `/api/agent/chatkit/session` | POST | Mint session token |
| 68 | `/api/agent/chatkit/respond` | POST | Streaming SSE response |
| 69 | `/api/agent/chatkit/upload` | POST | File upload (10MB max) |

### Debug Endpoints (ENV=dev + DEBUG_TRACE_ENABLED=true)

| # | Endpoint | Method | Notes |
|---|----------|--------|-------|
| 70 | `/api/debug/threads/{id}` | GET | Full trace |
| 71 | `/api/debug/threads/{id}/timeline` | GET | Timeline events |
| 72 | `/api/debug/threads/{id}/timeline/download` | GET | JSONL download |
| 73 | `/api/debug/threads/{id}/timeline/text` | GET | Text format |
| 74 | `/api/debug/threads/{id}/report` | GET | Debug report |
| 75 | `/api/debug/threads/{id}/llm-diagnosis` | GET | LLM diagnosis |
| 76 | `/api/debug/live` | GET | Active threads |
| 77 | `/api/debug/threads/{id}/live` | GET | Live logs |

### Dev-Only Endpoints (ENABLE_DANGEROUS_ENDPOINTS=true)

| # | Endpoint | Method | Notes |
|---|----------|--------|-------|
| 78 | `/api/client/reset` | POST | Reset client data |
| 79 | `/api/client/continue` | POST | Bypass dev prompt |
| 80 | `/api/emails/test` | POST | Test SMTP config |

**Total: 80 documented endpoints** (65 core + 4 agent/chatkit + 8 debug + 3 dev-only)

---

## Quick Verification After Deployment

After deploying to Hostinger, run this to verify:

```bash
# From your local machine
curl http://72.60.135.183:8000/api/workflow/health

# Expected response:
{"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
```

If you get this response, the backend is running correctly!

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENV` | `dev` or `prod` — controls debug/test-data router registration | `prod` |
| `DEBUG_TRACE_ENABLED` | Enable debug trace endpoints | `false` |
| `ENABLE_DANGEROUS_ENDPOINTS` | Enable dev-only reset/continue endpoints | `false` |
| `ENABLE_TEST_ENDPOINTS` | Enable test endpoints (deposit pay, email test) | `false` |
| `HIL_ALL_REPLIES` | Default HIL mode (can override via API) | `false` |
| `AUTH_ENABLED` | Require API key for all endpoints | `0` |
| `EMAIL_PLAIN_TEXT` | Strip Markdown from client emails | `false` |
| `ALLOWED_ORIGINS` | CORS allowed origins (comma-separated) | localhost + lovable |
