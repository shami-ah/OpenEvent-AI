# Backend TODO for OpeneventGithub Frontend Integration

This document tracks backend work needed to fully support the OpeneventGithub production frontend.

## Current Status

| Feature | Backend Status | Frontend Ready |
|---------|----------------|----------------|
| Prompts Editor API | Done | Docs ready |
| CORS Configuration | Done | - |
| Auth Headers | Partial | Needed |
| Team Context | TODO | Required |
| Supabase Integration | TODO | Required |

---

## Priority 1: Team Context Support (Required)

The OpeneventGithub frontend is **multi-tenant** - every request includes a `team_id` to scope data.

### Current Backend Behavior
- Uses `X-Team-Id` header for tenant isolation
- Stores data in JSON file per tenant

### Required Changes

#### 1. Accept Team ID from Frontend Auth Token

OpeneventGithub sends Supabase auth tokens. The backend should:

```python
# In api/routes/config.py or a middleware

from fastapi import Header, Depends
import jwt

async def get_team_context(
    authorization: str = Header(None),
    x_team_id: str = Header(None, alias="X-Team-Id")
) -> str:
    """
    Extract team_id from either:
    1. X-Team-Id header (current method, for testing)
    2. Supabase JWT token (production method)
    """
    if x_team_id:
        return x_team_id

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        # Decode Supabase JWT (no verification needed for team_id extraction)
        payload = jwt.decode(token, options={"verify_signature": False})
        # OpeneventGithub stores selected team in user metadata or passes separately
        return payload.get("team_id") or x_team_id

    return "default"  # Fallback for testing
```

#### 2. Update All Config Endpoints

Each `/api/config/*` endpoint should scope by team:

```python
@router.get("/api/config/prompts")
async def get_prompts(team_id: str = Depends(get_team_context)):
    # Load prompts for this team only
    return load_config(f"prompts.{team_id}")
```

**Files to update:**
- `api/routes/config.py` - All config endpoints
- `api/routes/events.py` - Events list/detail
- `api/routes/tasks.py` - HIL tasks

---

## Priority 2: Supabase Integration (Required for Production)

OpeneventGithub uses Supabase for all data. For full integration:

### Option A: Keep JSON + Sync (Simpler)
Keep current JSON storage, sync to Supabase periodically.

```python
# After saving to JSON, also sync to Supabase
async def sync_to_supabase(team_id: str, config_key: str, data: dict):
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    await supabase.table("ai_config").upsert({
        "team_id": team_id,
        "config_key": config_key,
        "data": data,
        "updated_at": datetime.now().isoformat()
    }).execute()
```

### Option B: Full Supabase Storage (Recommended)
Replace JSON storage with Supabase queries.

**Required Supabase table:**
```sql
CREATE TABLE ai_config (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    team_id UUID REFERENCES teams(id),
    config_key TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, config_key)
);

-- Enable RLS
ALTER TABLE ai_config ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only access their team's config
CREATE POLICY "Team members can access their config"
ON ai_config FOR ALL
USING (team_id IN (
    SELECT team_id FROM team_members_new
    WHERE user_id = auth.uid() AND invitation_status = 'active'
));
```

**Backend changes:**
```python
# New: api/storage/supabase_storage.py
from supabase import create_client

class SupabaseConfigStorage:
    def __init__(self):
        self.client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_KEY")  # Service key for backend
        )

    async def get(self, team_id: str, key: str) -> dict:
        result = await self.client.table("ai_config")\
            .select("data")\
            .eq("team_id", team_id)\
            .eq("config_key", key)\
            .single()\
            .execute()
        return result.data["data"] if result.data else {}

    async def set(self, team_id: str, key: str, data: dict):
        await self.client.table("ai_config").upsert({
            "team_id": team_id,
            "config_key": key,
            "data": data,
            "updated_at": datetime.now().isoformat()
        }).execute()
```

**Environment variables needed:**
```bash
SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...  # Service role key (NOT the anon key)
```

---

## Priority 3: Authentication Middleware (Security)

For production, verify Supabase JWT tokens.

### Add JWT Verification Middleware

```python
# api/middleware/auth.py
from fastapi import Request, HTTPException
from supabase import create_client
import os

async def verify_supabase_token(request: Request):
    """Verify the Supabase JWT token for protected routes."""
    if os.getenv("AUTH_ENABLED") != "1":
        return  # Skip in development

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    token = auth_header.split(" ")[1]

    # Verify with Supabase
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_ANON_KEY")
    )

    try:
        user = supabase.auth.get_user(token)
        request.state.user = user
        request.state.user_id = user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### Apply to Routes

```python
# In api/routes/config.py
from api.middleware.auth import verify_supabase_token

@router.get("/api/config/prompts")
async def get_prompts(
    request: Request,
    _: None = Depends(verify_supabase_token),
    team_id: str = Depends(get_team_context)
):
    # Request now has request.state.user_id
    ...
```

---

## Priority 4: Admin Role Verification

OpeneventGithub checks roles client-side, but backend should also verify.

### Role Check Helper

```python
async def require_admin_role(
    request: Request,
    team_id: str = Depends(get_team_context)
) -> bool:
    """Verify user has admin or owner role for this team."""
    user_id = request.state.user_id

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Check team_members_new table
    result = await supabase.table("team_members_new")\
        .select("role")\
        .eq("team_id", team_id)\
        .eq("user_id", user_id)\
        .eq("invitation_status", "active")\
        .single()\
        .execute()

    if not result.data:
        # Check if user is team owner
        team = await supabase.table("teams")\
            .select("owner_id")\
            .eq("id", team_id)\
            .single()\
            .execute()

        if team.data and team.data["owner_id"] == user_id:
            return True

        raise HTTPException(status_code=403, detail="Admin role required")

    role = result.data["role"]
    if role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin role required")

    return True
```

### Apply to Admin-Only Endpoints

```python
@router.post("/api/config/prompts")
async def save_prompts(
    config: PromptConfig,
    _: bool = Depends(require_admin_role),  # Must be admin
    team_id: str = Depends(get_team_context)
):
    ...
```

---

## Implementation Checklist

### Phase 1: Team Context (Enables Basic Integration)
- [ ] Add `get_team_context` dependency to extract team_id
- [ ] Update `/api/config/prompts` GET to scope by team
- [ ] Update `/api/config/prompts` POST to scope by team
- [ ] Update `/api/config/prompts/history` to scope by team
- [ ] Update `/api/config/prompts/revert` to scope by team
- [ ] Test with X-Team-Id header

### Phase 2: Supabase Storage (Enables Persistence)
- [ ] Create `ai_config` table in Supabase
- [ ] Add RLS policies
- [ ] Create `SupabaseConfigStorage` class
- [ ] Replace JSON storage calls with Supabase calls
- [ ] Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` to .env
- [ ] Test config persistence across restarts

### Phase 3: Auth Verification (Enables Security)
- [ ] Add JWT verification middleware
- [ ] Add `require_admin_role` dependency
- [ ] Apply auth to all config endpoints
- [ ] Test with real Supabase tokens
- [ ] Document auth flow in API_TESTS.md

### Phase 4: Full API Scoping
- [ ] Scope `/api/events` by team_id
- [ ] Scope `/api/tasks/*` by team_id
- [ ] Scope `/api/config/*` (all endpoints) by team_id
- [ ] Update activity logger to include team_id
- [ ] Test multi-tenant isolation

---

## Testing Strategy

### Local Testing (Current Test Frontend)
```bash
# Use X-Team-Id header
curl -H "X-Team-Id: test-team" http://localhost:8000/api/config/prompts
```

### Integration Testing (OpeneventGithub)
```bash
# Use Supabase token
TOKEN=$(get_supabase_token)  # From browser devtools or test script
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Team-Id: actual-team-uuid" \
     http://localhost:8000/api/config/prompts
```

### Production Testing
```bash
# Same as integration, but against Hostinger
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Team-Id: $TEAM_ID" \
     https://your-hostinger-backend.com/api/config/prompts
```

---

## Environment Variables Summary

### Development (.env)
```bash
# Current
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
PROMPTS_EDITOR_ENABLED=true

# Add for Supabase integration
SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...  # Service role key
```

### Production (/opt/openevent/.env)
```bash
# Required
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
PROMPTS_EDITOR_ENABLED=true
AUTH_ENABLED=1
ENV=prod

# Supabase
SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# CORS
ALLOWED_ORIGINS=https://your-production-domain.com
```

---

## Notes

### Why X-Team-Id Header Still Works
The frontend sends both:
1. `Authorization: Bearer <supabase_token>` - For user identity
2. `X-Team-Id: <team_uuid>` - For selected team context

This is because a user can belong to multiple teams and switch between them. The selected team is tracked client-side and sent with each request.

### Backwards Compatibility
All changes should be backwards compatible:
- If no auth header, fall back to X-Team-Id header
- If no X-Team-Id, use "default" tenant
- Test frontend continues to work without Supabase tokens
