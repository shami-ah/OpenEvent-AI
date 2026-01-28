# Hostinger VPS Deployment Guide

Deploy the OpenEvent AI backend to Hostinger VPS, then connect from Lovable frontend.

---

## Quick Reference

| What you need | Where to find it |
|---------------|------------------|
| **VPS IP Address** | `72.60.135.183` |
| **Backend Port** | `8000` |
| **Lovable env var** | `VITE_BACKEND_BASE=http://72.60.135.183:8000` |
| **API Endpoints** | See table below or [API_TESTS.md](./API_TESTS.md) |
| **Setup script** | `deploy/setup-vps.sh` |
| **Service config** | `deploy/openevent.service` |

### Files in this folder:
```
deploy/
├── README.md                              ← You are here (setup guide)
├── FRONTEND_API_INTEGRATION.md            ← 🆕 COMPLETE frontend integration guide (80+ endpoints)
├── API_TESTS.md                           ← All endpoints with curl examples
├── FRONTEND_PROMPTS_EDITOR_CONNECTION.md  ← Connect prompts editor to OpeneventGithub
├── PROMPTS_EDITOR_INTEGRATION.md          ← Feature overview for prompts editor
├── setup-vps.sh                           ← Run this on VPS to install everything
├── openevent.service                      ← systemd service configuration
├── nginx-openevent.conf                   ← Nginx reverse proxy config
└── update.sh                              ← Quick update script

See also:
├── ../docs/integration/BACKEND_TODO_FOR_FRONTEND.md  ← Backend work needed for full integration
```

---

## Your VPS Info
- **Server:** srv1153474.hstgr.cloud
- **IP:** 72.60.135.183
- **Status:** Active (expires 2026-11-26)

---

## Step-by-Step Setup

### Step 1: SSH into your VPS

```bash
ssh root@72.60.135.183
```

(Use the password from Hostinger panel, or setup SSH keys)

---

### Step 2: Run the Setup Script

```bash
# Install git first
apt update && apt install -y git

# Clone your repo
cd /opt
git clone https://github.com/YOUR_USERNAME/OpenEvent-AI.git openevent
cd openevent

# Make scripts executable and run setup
chmod +x deploy/*.sh
./deploy/setup-vps.sh
```
This installs the pinned backend dependencies from `requirements-dev.txt`.

---

### Step 3: Configure Environment

```bash
nano /opt/openevent/.env
```

Add these values:
```
# ========== HYBRID MODE (recommended) ==========
# Uses BOTH providers for optimal cost/quality:
#   - Gemini: intent detection & entity extraction (cheaper)
#   - OpenAI: client-facing verbalization (higher quality)

OPENAI_API_KEY=sk-your-openai-key-here
GOOGLE_API_KEY=AIza-your-gemini-key-here
AGENT_MODE=gemini

# CORS - Allow Lovable frontend to connect
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,http://localhost:3000
PYTHONDONTWRITEBYTECODE=1
```

**Important:**
- **Both API keys are required** for hybrid mode
- `AGENT_MODE=gemini` sets Gemini for detection; OpenAI is auto-used for verbalization
- If you only have OpenAI, set `AGENT_MODE=openai` (works but costs more)
- `ALLOWED_ORIGINS` enables CORS for Lovable!

---

### Step 4: Update Nginx Config

```bash
nano /etc/nginx/sites-available/openevent
```

Replace `your-domain.com` with either:
- Your domain (e.g., `api.yourdomain.com`)
- Or just use the IP: `72.60.135.183`

Then reload:
```bash
nginx -t && systemctl reload nginx
```

---

### Step 5: Restart Services

```bash
systemctl restart openevent
systemctl status openevent
```

You should see "active (running)".

---

### Step 6: Test the Backend

From your local machine or browser:
```bash
curl http://72.60.135.183:8000/api/workflow/health
```

Should return: `{"status":"ok"}`

---

## Production Mode (IMPORTANT)

When deploying for real clients, switch from dev to production mode:

### Required Environment Variables

Add these to `/opt/openevent/.env`:

```bash
# ========== PRODUCTION MODE ==========
ENV=prod                      # Hides debug routes, removes db_path from health endpoint
AUTH_ENABLED=1                # Requires API key for all endpoints (except health)
TENANT_HEADER_ENABLED=0       # Disables header-based tenant switching

# ========== RATE LIMITING (optional) ==========
# Limits requests per IP to prevent abuse. Uses in-memory storage.
# For multi-worker deployments, use Redis instead (see docs).
RATE_LIMIT_ENABLED=1          # Enable rate limiting
RATE_LIMIT_RPS=10             # Requests per second per IP (10 = 36,000/hour)
RATE_LIMIT_BURST=30           # Burst allowance for page loads

# ========== ERROR ALERTING (optional) ==========
# Get notified when AI fails and falls back to manual review
# ⚠️  PRIVACY NOTE: Alert emails include client message content (PII)
#    Only add trusted internal staff to ALERT_EMAIL_RECIPIENTS
ALERT_EMAIL_RECIPIENTS=ops@openevent.com,dev@openevent.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASS=your-smtp-password
```

### Quick Toggle Script

```bash
# Switch to production mode
nano /opt/openevent/.env
# Add: ENV=prod AUTH_ENABLED=1 TENANT_HEADER_ENABLED=0 RATE_LIMIT_ENABLED=1
systemctl restart openevent

# Verify production mode
curl http://72.60.135.183:8000/api/workflow/health
# Should return: {"ok": true}  (no db_path in prod)

curl http://72.60.135.183:8000/api/events
# Should return: 401 Unauthorized (auth required in prod)
```

### Production Checklist

- [ ] `ENV=prod` set
- [ ] `AUTH_ENABLED=1` set
- [ ] `RATE_LIMIT_ENABLED=1` set (optional but recommended)
- [ ] `TENANT_HEADER_ENABLED=0` set (never enable in prod)
- [ ] API keys configured (OPENAI + GOOGLE for hybrid mode)
- [ ] CORS origins set to your frontend domains only
- [ ] (Optional) Error alerting configured with SMTP
- [ ] Test: trigger a fallback and verify no client sees the error

### Security Notes

| Setting | Dev | Prod | Why |
|---------|-----|------|-----|
| `ENV` | dev | **prod** | Hides debug routes, db paths |
| `AUTH_ENABLED` | 0 | **1** | Protects API from public access |
| `RATE_LIMIT_ENABLED` | 0 | **1** | Prevents API abuse (10 req/sec default) |
| `TENANT_HEADER_ENABLED` | 1 | **0** | Header spoofing risk |

---

## Connect Lovable Frontend

Once the backend is running, tell your colleague:

**In Lovable project settings, add environment variable:**
```
VITE_BACKEND_BASE=http://72.60.135.183:8000
```

That's it! The frontend will now call your Hostinger backend.

---

## API Endpoints (80 Total)

**For detailed curl examples and test results, see [API_TESTS.md](./API_TESTS.md)**.

### Authentication
Most endpoints require the `X-Team-Id` header for multi-tenancy:
```bash
curl -H "X-Team-Id: your-team-id" http://72.60.135.183:8000/api/...
```

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/start-conversation` | POST | Start new chat |
| `/api/send-message` | POST | Send message to agent |
| `/api/conversation/{id}` | GET | Get conversation state |
| `/api/conversation/{id}/confirm-date` | POST | Confirm selected date |
| `/api/accept-booking/{id}` | POST | Accept booking |
| `/api/reject-booking/{id}` | POST | Reject booking |
| `/api/tasks/pending` | GET | Get HIL tasks for manager |
| `/api/tasks/{id}/approve` | POST | Approve HIL task |
| `/api/tasks/{id}/reject` | POST | Reject HIL task |
| `/api/tasks/cleanup` | POST | Clear old tasks |
| `/api/events` | GET | List all events |
| `/api/events/{id}` | GET | Get event details |
| `/api/event/{id}/cancel` | POST | Cancel event booking |
| `/api/event/{id}/deposit` | GET | Get deposit status |
| `/api/event/deposit/pay` | POST | Pay deposit (test only) |
| `/api/events/{id}/progress` | GET | Get workflow progress bar |
| `/api/events/{id}/activity` | GET | Get AI activity log |
| `/api/emails/send-to-client` | POST | Send email after HIL approval |
| `/api/emails/send-offer` | POST | Send offer email |
| `/api/workflow/health` | GET | Health check |
| `/api/workflow/hil-status` | GET | HIL toggle status |
| `/api/config/global-deposit` | GET/POST | Deposit settings |
| `/api/config/hil-mode` | GET/POST | HIL mode toggle |
| `/api/config/prompts` | GET/POST | LLM prompt config |
| `/api/config/llm-provider` | GET/POST | LLM provider routing |
| `/api/config/venue` | GET/POST | Venue identity settings |
| `/api/config/site-visit` | GET/POST | Site visit scheduling |
| `/api/config/managers` | GET/POST | Manager list |
| `/api/config/products` | GET/POST | Product autofill config |
| `/api/config/menus` | GET/POST | Catering menus config |
| `/api/config/catalog` | GET/POST | Product-room catalog |
| `/api/config/faq` | GET/POST | FAQ entries |
| `/api/config/email-format` | GET/POST | Plain text vs Markdown |
| `/api/config/hil-email` | GET/POST | HIL email notifications |
| `/api/config/pre-filter` | GET/POST | Pre-filter mode |
| `/api/config/detection-mode` | GET/POST | Detection mode |
| `/api/qna` | GET | Q&A data (dev-mode only) |
| `/api/test-data/rooms` | GET | Room data (dev-mode only) |
| `/api/test-data/catering` | GET | Catering menus (dev-mode only) |
| `/api/snapshots/{id}` | GET | Snapshot data |

See [API_TESTS.md](./API_TESTS.md) for full list of 78 endpoints with curl examples.

### AI Activity Logger

The Activity Logger provides visibility into what the AI did during each booking workflow. Designed for managers to trace event history and investigate issues.

#### Endpoints

```bash
# Get workflow progress bar
GET /api/events/{event_id}/progress

# Get activity log
GET /api/events/{event_id}/activity?granularity=high&limit=50
```

#### Progress Bar Response

Shows the 5-stage workflow: Date → Room → Offer → Deposit → Confirmed

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

#### Activity Log Response

```json
{
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
```

#### Two Granularity Levels

Both are **manager-focused** (no technical debugging info).

| Parameter | What It Shows | Use Case |
|-----------|---------------|----------|
| `?granularity=high` | Main business milestones | Default manager view |
| `?granularity=detailed` | Breakdown of each milestone | "Show More Details" investigation |

**How they relate:** Fine (detailed) is a breakdown of coarse (high). When you see "Offer Sent" in coarse view, switching to fine shows you the steps that led to that milestone.

**Example: Coarse vs Fine View**

```
COARSE VIEW (Main Milestones)          FINE VIEW (Show More Details)
─────────────────────────────          ───────────────────────────────
📅 Date Confirmed: March 15            📅 Confirming Date
                                       📅 Dates Suggested: March 15, 18, 20
                                       📅 Date Confirmed: March 15

🏢 Room Selected: Grand Ballroom       🏢 Checking Availability
                                       🏢 Rooms Checked: 3 available
                                       🏢 Room Selected: Grand Ballroom
                                       🔒 Room Reserved: Grand Ballroom

📄 Offer Sent: €1,500                  📄 Preparing Offer
                                       👤 Name Captured: John Smith
                                       📧 Email Captured: john@example.com
                                       📄 Offer Sent: €1,500
```

#### Coarse Activities (Main Milestones)

| Category | Activities |
|----------|-----------|
| CRM | Client saved to CRM |
| Calendar | Event created (with status) |
| Room Status | Lead → Option → Confirmed → Cancelled |
| Detours | Date/Room/Participants/Products changed |
| Site Visit | Site visit booked/completed |
| Offer | Offer sent/accepted/rejected, Price updated |
| Deposit | Deposit required/paid/updated, Billing updated |
| Verification Failures | Date denied, Room denied, Conflicts, Capacity exceeded |

#### Fine Activities (Investigation Details)

All coarse activities PLUS:

| Category | Activities |
|----------|-----------|
| Workflow | Processing inquiry, Confirming date, Checking availability... |
| Date | Dates suggested, Date checked |
| Room | Rooms checked (count), Room selected, Room reserved/released |
| User Preferences | Event type, Preferred date, Guests, Room, Catering, Setup, Equipment, Timing, Budget |
| Contact | Name/Email/Phone/Company/Address |
| Manager | Awaiting review, Approved, Edited response |
| Communication | Email/Message sent/received |
| Verification | Availability/Capacity/Pricing checks |

#### Frontend Integration Example

```tsx
// Progress bar
const { data: progress } = useSWR(`/api/events/${eventId}/progress`);

// Activity feed with toggle
const [showDetails, setShowDetails] = useState(false);
const granularity = showDetails ? 'detailed' : 'high';
const { data: activities } = useSWR(
  `/api/events/${eventId}/activity?granularity=${granularity}`
);
```

#### Cost Impact

- **API Cost:** $0 (no additional LLM calls)
- **Storage:** ~10KB per event max
- Timestamps are in **local timezone** (not UTC)

For full integration docs, see `docs/integration/ACTIVITY_LOGGER_INTEGRATION.md`.

### Two Ways to Send Messages: Which One to Use?

The backend has **two parallel messaging paths**. Both reach the same workflow engine, but they serve different purposes:

| Aspect | `/api/send-message` | `/api/agent/chatkit/respond` |
|--------|---------------------|------------------------------|
| **Response format** | JSON (complete response) | SSE streaming (tokens appear in real-time) |
| **Best for** | Manager dashboards, testing, batch processing | Client-facing chat widgets |
| **Waits for** | Entire workflow to finish | Streams as LLM generates |
| **Session init** | `POST /api/start-conversation` | `POST /api/agent/chatkit/session` |

**When to use `/api/send-message`:**
- Building a manager dashboard where you need the full response at once
- Backend-to-backend integrations (webhooks, email processors)
- Testing or debugging workflows
- Any case where you show the response all at once, not streaming

**When to use `/api/agent/chatkit/*`:**
- Building a client-facing chat widget (like the `/agent` page)
- You want text to stream in real-time as the AI generates it
- You're using OpenAI's ChatKit React library
- You need file upload support in the chat

#### Example: Manager Dashboard Flow (JSON)
```bash
# 1. Start conversation
curl -X POST http://localhost:8000/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"client_email":"client@test.com","email_body":"Book room for 20 people on April 10"}'
# Returns: {"session_id": "abc-123", "response": "Here are available dates...", ...}

# 2. Send follow-up messages
curl -X POST http://localhost:8000/api/send-message \
  -H "Content-Type: application/json" \
  -d '{"session_id":"abc-123","message":"Let us do April 10"}'
# Returns: {"response": "Great, April 10 is confirmed...", ...}
```

#### Example: Client Chat Widget Flow (Streaming)
```bash
# 1. Get session token (for ChatKit initialization)
curl -X POST http://localhost:8000/api/agent/chatkit/session \
  -H "Content-Type: application/json" \
  -d '{"from_email":"client@test.com"}'
# Returns: {"client_secret": "random-token-xyz"}

# 2. Send messages (returns SSE stream)
curl -X POST http://localhost:8000/api/agent/chatkit/respond \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"abc-123","text":"Book room for 20 people"}'
# Returns: data: {"delta": "Here"}
#          data: {"delta": " are"}
#          data: {"delta": " available"}
#          data: {"delta": " dates..."}
```

**In short:** Use `/api/send-message` for manager tools. Use `/api/agent/chatkit/respond` for client-facing real-time chat.

### Understanding the Frontend Architecture

There are **two different frontends** that interact with this backend:

#### 1. Main OpenEvent Application (Production) - OpeneventGithub

**Location:** `/Users/nico/Documents/GitHub/OpeneventGithub/`

**Tech stack:** React 18 + TypeScript + Vite + shadcn-ui + React Query + Supabase

**What it includes:**
- `/inbox` - Email management (IMAP/Gmail integration)
- `/calendar` - Event scheduling
- `/crm` - Client management
- `/offers` - Quote generation
- `/tasks` - Task/HIL management
- `/setup/*` - Venue, rooms, products configuration
- `/settings` - User preferences, team management

**API usage:** Uses `/api/send-message` for AI email processing. Email arrives in Inbox → AI processes → Manager reviews via Tasks → Response sent.

**Integration docs:** See [FRONTEND_PROMPTS_EDITOR_CONNECTION.md](./FRONTEND_PROMPTS_EDITOR_CONNECTION.md) for connecting new features.

#### 2. Test/Demo Frontend (`atelier-ai-frontend/`)

**Location:** `OpenEvent-AI/atelier-ai-frontend/`

This is a **test harness** in this repository for backend development. It's NOT the production frontend.

| Page | Purpose | API Used |
|------|---------|----------|
| `page.tsx` (root `/`) | Manager dashboard for testing workflows | `/api/send-message` (JSON) |
| `agent/page.tsx` (`/agent`) | ChatKit streaming demo | `/api/agent/chatkit/*` (SSE) |
| `debug/` | Debug panel for traces | `/api/debug/*` |
| `info/` | Room/Q&A data display | `/api/test-data/*`, `/api/qna` |

#### When is ChatKit actually used?

**Currently:** Only in the test frontend's `/agent` page, which demonstrates real-time streaming with OpenAI's ChatKit library.

**Potential future use:** If you want to embed a chat widget on a public-facing website where clients can inquire about bookings in real-time (like a website chat bubble), you would use the ChatKit endpoints.

**Production workflow:** The main OpenEvent app uses email-based communication. Clients email the venue → Email lands in Inbox → AI processes via `/api/send-message` → Manager reviews in Tasks panel → Response emailed back to client. No streaming needed because it's not real-time chat.

**Backend source references (for quick edits)**
Endpoints are organized in modular route files under `api/routes/`:

| Route File | Endpoints | Registration |
|------------|-----------|--------------|
| `messages.py` | `/api/start-conversation`, `/api/send-message`, `/api/conversation/*`, `/api/accept-booking/*`, `/api/reject-booking/*` | Always |
| `tasks.py` | `/api/tasks/pending`, `/api/tasks/{id}/approve`, `/api/tasks/{id}/reject`, `/api/tasks/cleanup` | Always |
| `events.py` | `/api/events`, `/api/events/{id}`, `/api/event/{id}/deposit`, `/api/event/deposit/pay`, `/api/event/{id}/cancel` | Always |
| `emails.py` | `/api/emails/send-to-client`, `/api/emails/send-offer`, `/api/emails/test` | Always |
| `config.py` | `/api/config/*` (deposit, HIL, prompts, venue, site-visit, managers, products, menus, catalog, faq, llm-provider, email-format, hil-email, pre-filter, detection-mode, hybrid-enforcement, room-deposit) | Always |
| `workflow.py` | `/api/workflow/health`, `/api/workflow/hil-status` | Always |
| `snapshots.py` | `/api/snapshots`, `/api/snapshots/{id}`, `/api/snapshots/{id}/data` | Always |
| `test_data.py` | `/api/test-data/rooms`, `/api/test-data/catering`, `/api/test-data/catering/{slug}`, `/api/test-data/qna`, `/api/qna` | Always |
| `agent_router.py` | `/api/agent/reply`, `/api/agent/chatkit/session`, `/api/agent/chatkit/respond`, `/api/agent/chatkit/upload` | Always |
| `debug.py` | `/api/debug/threads/{id}`, `/api/debug/threads/{id}/timeline`, `/api/debug/live`, etc. | **Dev only** |
| `clients.py` | `/api/client/reset`, `/api/client/continue` | Always (guarded by env var) |

---

## Useful Commands

```bash
# Check if service is running
systemctl status openevent

# View live logs
journalctl -u openevent -f

# Restart after changes
systemctl restart openevent

# Update from GitHub
cd /opt/openevent && git pull && systemctl restart openevent

# Check what's using port 8000
lsof -i :8000
```

---

## Troubleshooting

### Backend won't start
```bash
# Check logs
journalctl -u openevent -n 100 --no-pager

# Common issues:
# - Missing OPENAI_API_KEY in .env
# - Python dependencies not installed
# - Port 8000 already in use
```

### CORS errors from Lovable
Make sure `.env` has:
```
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app
```
Then restart: `systemctl restart openevent`

### Permission errors
```bash
chown -R root:root /opt/openevent
```

### Can't connect from Lovable
1. Check backend is running: `systemctl status openevent`
2. Check firewall allows port 8000: `ufw allow 8000`
3. Test from local: `curl http://72.60.135.183:8000/api/workflow/health`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LOVABLE                              │
│                 (Your colleague's frontend)             │
│                                                         │
│   VITE_BACKEND_BASE = http://72.60.135.183:8000        │
└─────────────────────────┬───────────────────────────────┘
                          │ API calls (fetch)
                          ▼
┌─────────────────────────────────────────────────────────┐
│               HOSTINGER VPS (72.60.135.183)             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  uvicorn (:8000)                                │   │
│  │  FastAPI backend                                │   │
│  │  - /api/send-message                            │   │
│  │  - /api/tasks/pending                           │   │
│  │  - /api/tasks/{id}/approve                      │   │
│  │  - etc.                                         │   │
│  └─────────────────────────────────────────────────┘   │
│                          │                              │
│                          ▼                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │  events_database.json                           │   │
│  │  (workflow state, events, tasks)                │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Optional: Setup SSL (HTTPS)

If you have a domain pointed to your VPS:

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d api.yourdomain.com
```

Then update Lovable to use `https://` instead of `http://`.

---

## Rate Limiting

The API includes built-in rate limiting to prevent abuse.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `0` | Set to `1` to enable |
| `RATE_LIMIT_RPS` | `50` | Requests per second per IP |
| `RATE_LIMIT_BURST` | `100` | Burst allowance for page loads |
| `RATE_LIMIT_EXEMPT_PATHS` | `/api/workflow/health,...` | Comma-separated paths to skip |

### Recommended Settings

| Environment | RPS | Burst | Why |
|-------------|-----|-------|-----|
| **Development** | 50 | 100 | Generous - won't affect testing |
| **Production** | 10 | 30 | Prevents abuse while allowing normal use |
| **High-security** | 5 | 10 | For public-facing APIs |

### How It Works

```
Request comes in
    ↓
Is path exempt? (/health, /docs) → Allow
    ↓
Count requests from this IP in last second
    ↓
Under limit? → Allow
Over limit? → 429 Too Many Requests
```

### Multi-Worker Deployments

By default, rate limits use **in-memory storage** - each worker tracks limits independently.
For multiple uvicorn workers, requests could exceed limits (each worker has its own counter).

**Options:**
1. **Single worker** (default): In-memory is fine
2. **Multiple workers**: Use Redis for shared counters:
   ```python
   # In rate_limit.py, change storage_uri:
   storage_uri="redis://localhost:6379"
   ```

### Testing Rate Limits

```bash
# Trigger rate limit (run in rapid succession)
for i in {1..100}; do curl -s http://localhost:8000/api/events > /dev/null & done

# Check if you get 429 response
curl -i http://localhost:8000/api/events
# HTTP/1.1 429 Too Many Requests
# {"error": "rate_limit_exceeded", "detail": "Rate limit exceeded...", "retry_after": 1}
```
