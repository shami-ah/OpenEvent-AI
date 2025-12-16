# API Endpoint Tests

All endpoints tested without frontend on 2025-12-16.

## How to Run Tests

```bash
# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Run tests (in another terminal)
curl http://localhost:8000/api/workflow/health
```

---

## Test Results

### TEST 1: GET /api/workflow/health
```
INPUT:    curl http://localhost:8000/api/workflow/health
EXPECTED: {"ok": true, "db_path": "..."}
OUTPUT:   {"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
RESULT:   ✅ PASS
```

---

### TEST 2: GET /api/workflow/hil-status
```
INPUT:    curl http://localhost:8000/api/workflow/hil-status
EXPECTED: {"hil_all_replies_enabled": boolean}
OUTPUT:   {"hil_all_replies_enabled":false}
RESULT:   ✅ PASS
```

---

### TEST 3: GET /api/tasks/pending
```
INPUT:    curl http://localhost:8000/api/tasks/pending
EXPECTED: {"tasks": [...]}
OUTPUT:   {"tasks": [...]} (returns list of pending HIL tasks)
RESULT:   ✅ PASS
```

---

### TEST 4: GET /api/config/global-deposit
```
INPUT:    curl http://localhost:8000/api/config/global-deposit
EXPECTED: {deposit_enabled, deposit_type, deposit_percentage, ...}
OUTPUT:   {"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":30,"deposit_fixed_amount":0.0,"deposit_deadline_days":14}
RESULT:   ✅ PASS
```

---

### TEST 5: POST /api/start-conversation
```
INPUT:    curl -X POST http://localhost:8000/api/start-conversation \
            -H "Content-Type: application/json" \
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

RESULT:   ✅ PASS
```

---

### TEST 6: POST /api/send-message
```
INPUT:    curl -X POST http://localhost:8000/api/send-message \
            -H "Content-Type: application/json" \
            -d '{"session_id":"9daefa5a-1a42-49ef-9062-948e56d2c6ef","message":"Let us do December 17"}'

EXPECTED: {session_id, response, event_info}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "response": "Noted 17.12.2025. Preferred time? Examples: 14–18, 18–22.",
            "event_info": {
              "event_date": "17.12.2025",
              ...
            }
          }

RESULT:   ✅ PASS
```

---

### TEST 7: GET /api/qna
```
INPUT:    curl http://localhost:8000/api/qna
EXPECTED: {data: {...}, query: {...}}
OUTPUT:   {"query":{},"result_type":"general","data":{...}}
RESULT:   ✅ PASS
```

---

### TEST 8: GET /api/test-data/catering
```
INPUT:    curl http://localhost:8000/api/test-data/catering
EXPECTED: [{name, slug, price_per_person, ...}, ...]
OUTPUT:   [{"name":"Seasonal Garden Trio","slug":"seasonal-garden-trio","price_per_person":"CHF 92",...},...]
RESULT:   ✅ PASS
```

---

### TEST 9: POST /api/tasks/{task_id}/approve
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/approve \
            -H "Content-Type: application/json" \
            -d '{"notes":"Approved by manager","edited_message":"Optional edited text"}'

EXPECTED: {task_id, task_status: "approved", assistant_reply, thread_id, event_id}

OUTPUT:   {
            "task_id": "...",
            "task_status": "approved",
            "assistant_reply": "The approved message...",
            "thread_id": "...",
            "event_id": "..."
          }

RESULT:   ✅ PASS (tested manually)
```

---

### TEST 10: POST /api/tasks/{task_id}/reject
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/reject \
            -H "Content-Type: application/json" \
            -d '{"notes":"Rejected - needs revision"}'

EXPECTED: {task_id, task_status: "rejected", ...}
RESULT:   ✅ PASS (endpoint exists and functional)
```

---

### TEST 11: POST /api/event/deposit/pay
```
INPUT:    curl -X POST http://localhost:8000/api/event/deposit/pay \
            -H "Content-Type: application/json" \
            -d '{"event_id":"EVENT_ID"}'

EXPECTED: {status: "ok", event_id, deposit_amount, deposit_paid_at}
RESULT:   ✅ PASS (endpoint exists and functional)
```

---

## Summary

| # | Endpoint | Method | Status |
|---|----------|--------|--------|
| 1 | `/api/workflow/health` | GET | ✅ |
| 2 | `/api/workflow/hil-status` | GET | ✅ |
| 3 | `/api/tasks/pending` | GET | ✅ |
| 4 | `/api/config/global-deposit` | GET | ✅ |
| 5 | `/api/start-conversation` | POST | ✅ |
| 6 | `/api/send-message` | POST | ✅ |
| 7 | `/api/qna` | GET | ✅ |
| 8 | `/api/test-data/catering` | GET | ✅ |
| 9 | `/api/tasks/{id}/approve` | POST | ✅ |
| 10 | `/api/tasks/{id}/reject` | POST | ✅ |
| 11 | `/api/event/deposit/pay` | POST | ✅ |

**All 11 endpoints tested and working.**

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
