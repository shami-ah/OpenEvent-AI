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
├── README.md           ← You are here (setup guide)
├── API_TESTS.md        ← All endpoints with curl examples
├── setup-vps.sh        ← Run this on VPS to install everything
└── openevent.service   ← systemd service configuration
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
This installs the pinned backend dependencies from `requirements-dev`.

---

### Step 3: Configure Environment

```bash
nano /opt/openevent/.env
```

Add these values:
```
OPENAI_API_KEY=sk-your-actual-key-here
AGENT_MODE=openai
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,http://localhost:3000
PYTHONDONTWRITEBYTECODE=1
```

**Important:** The `ALLOWED_ORIGINS` line enables CORS for Lovable!

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

## Connect Lovable Frontend

Once the backend is running, tell your colleague:

**In Lovable project settings, add environment variable:**
```
VITE_BACKEND_BASE=http://72.60.135.183:8000
```

That's it! The frontend will now call your Hostinger backend.

---

## API Endpoints (Already Implemented)

These endpoints are ready to use. **For detailed curl examples and test results, see [API_TESTS.md](./API_TESTS.md)**.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/start-conversation` | POST | Start new chat |
| `/api/send-message` | POST | Send message to agent |
| `/api/tasks/pending` | GET | Get HIL tasks for manager |
| `/api/tasks/{id}/approve` | POST | Approve HIL task |
| `/api/tasks/{id}/reject` | POST | Reject HIL task |
| `/api/tasks/cleanup` | POST | Clear old tasks |
| `/api/workflow/health` | GET | Health check |
| `/api/workflow/hil-status` | GET | HIL toggle status |
| `/api/config/global-deposit` | GET/POST | Deposit settings |
| `/api/event/deposit/pay` | POST | Pay deposit (simulation) |
| `/api/event/{id}/deposit` | GET | Get deposit status |
| `/api/qna` | GET | Q&A data |
| `/api/test-data/rooms` | GET | Room data |
| `/api/snapshots/{id}` | GET | Snapshot data |

**Backend source references (for quick edits)**  
All endpoints above live in `backend/main.py`:

- Conversation entry points: `/api/start-conversation` and `/api/send-message` around lines 721–998.
- Manager task endpoints: `/api/tasks/pending`, `/api/tasks/{task_id}/approve`, `/api/tasks/{task_id}/reject`, `/api/tasks/cleanup` around lines 1001–1190.
- Health + HIL toggles: `/api/workflow/health` and `/api/workflow/hil-status` around lines 1726–1743.
- Config/deposit flow: `/api/config/global-deposit` (GET/POST) near lines 1762–1811, `/api/event/deposit/pay` and `/api/event/{event_id}/deposit` around lines 1903–2009.
- Test data + reference endpoints: `/api/test-data/rooms`, `/api/test-data/catering`, `/api/qna`, and `/api/snapshots/*` around lines 1495–1710.

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
