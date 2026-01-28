# Connecting the Prompts Editor to the Main Frontend

This guide explains how to add the AI Message Customization feature to your OpenEvent setup.

## Architecture Overview

Your system has **two separate frontends**:

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│  Main Frontend (Lovable/Vite)   │     │  Admin Frontend (Next.js)       │
│  OpeneventGithub repo           │     │  atelier-ai-frontend/           │
│                                 │     │                                 │
│  • Client-facing app            │     │  • Debug/admin tools            │
│  • Uses Supabase directly       │     │  • Prompts editor at /admin/    │
│  • No Python backend calls      │     │  • Connects to Python backend   │
└─────────────────────────────────┘     └─────────────────────────────────┘
                  │                                      │
                  │                                      │
                  ▼                                      ▼
          ┌─────────────┐                    ┌─────────────────────┐
          │  Supabase   │                    │  Python Backend     │
          │  (Database) │◀───────────────────│  (FastAPI/Hostinger)│
          └─────────────┘                    └─────────────────────┘
```

## Two Integration Options

---

## Option A: Link to Admin Frontend (Recommended - Simplest)

Deploy the admin frontend (`atelier-ai-frontend`) and link to it from your main app.

### Step 1: Deploy Admin Frontend

The admin frontend is at `OpenEvent-AI/atelier-ai-frontend/`. Deploy it:

**For Vercel:**
```bash
cd atelier-ai-frontend
vercel --prod
```

**Environment variables needed:**
```
NEXT_PUBLIC_BACKEND_BASE=https://your-hostinger-backend.com
NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED=true
```

### Step 2: Add Link in Main Settings

In `OpeneventGithub/src/pages/PreferencesSettings.tsx`, add a card that links out:

```tsx
// In the settings tabs, add:
<Card>
  <CardHeader>
    <CardTitle className="flex items-center gap-2">
      <Sparkles className="h-5 w-5" />
      AI Message Style
    </CardTitle>
    <CardDescription>
      Customize how the AI writes to your clients
    </CardDescription>
  </CardHeader>
  <CardContent>
    <Button asChild>
      <a
        href="https://your-admin-frontend.vercel.app/admin/prompts"
        target="_blank"
        rel="noopener noreferrer"
      >
        <ExternalLink className="h-4 w-4 mr-2" />
        Open AI Style Editor
      </a>
    </Button>
  </CardContent>
</Card>
```

**That's it!** The prompts editor is already built in the admin frontend.

---

## Option B: Embed in Main Frontend (More Work)

If you prefer everything in one app, add the prompts editor directly.

### Quick Setup Steps

### 1. Backend: Enable Feature Flag

On your Hostinger server (or wherever the Python backend runs):

```bash
# Add to environment variables
PROMPTS_EDITOR_ENABLED=true
```

### 2. Frontend: Add Backend URL

In `/Users/nico/Documents/GitHub/OpeneventGithub/.env`:

```bash
# Add this line - point to your Python backend
VITE_AI_BACKEND_URL=https://your-hostinger-backend.com
```

For local development:
```bash
VITE_AI_BACKEND_URL=http://localhost:8000
```

### 3. Frontend: Create API Client

Create a new file: `src/lib/aiBackend.ts`

```typescript
/**
 * API client for the AI backend (Python/FastAPI)
 * Used for prompts editor and other AI configuration
 */

const AI_BACKEND_URL = import.meta.env.VITE_AI_BACKEND_URL || '';

interface PromptConfig {
  system_prompt: string;
  step_prompts: Record<string, string>;
}

interface HistoryEntry {
  ts: string;
  config: PromptConfig;
}

export async function getPrompts(): Promise<PromptConfig> {
  const res = await fetch(`${AI_BACKEND_URL}/api/config/prompts`);
  if (!res.ok) {
    if (res.status === 404) throw new Error('Prompts editor not enabled');
    throw new Error('Failed to load prompts');
  }
  return res.json();
}

export async function savePrompts(config: PromptConfig): Promise<void> {
  const res = await fetch(`${AI_BACKEND_URL}/api/config/prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('Failed to save prompts');
}

export async function getPromptsHistory(): Promise<HistoryEntry[]> {
  const res = await fetch(`${AI_BACKEND_URL}/api/config/prompts/history`);
  if (!res.ok) throw new Error('Failed to load history');
  const data = await res.json();
  return data.history;
}

export async function revertPrompts(index: number): Promise<void> {
  const res = await fetch(`${AI_BACKEND_URL}/api/config/prompts/revert/${index}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to revert');
}

export function isAiBackendConfigured(): boolean {
  return Boolean(AI_BACKEND_URL);
}
```

### 4. Frontend: Add to Settings Page

**Option A: Add as new tab in PreferencesSettings.tsx**

In the existing tabs, add a new "AI Style" tab:

```tsx
// At top of file, add import
import { AIStyleTab } from '@/components/settings/AIStyleTab';

// In the tabs list (around line 60), add:
const canViewAIStyle = hasAtLeastRole('admin');

// In TabsList (around line 200), add:
{canViewAIStyle && (
  <TabsTrigger value="ai-style">
    <Sparkles className="h-4 w-4 mr-2" />
    AI Style
  </TabsTrigger>
)}

// In TabsContent area, add:
{canViewAIStyle && (
  <TabsContent value="ai-style">
    <AIStyleTab />
  </TabsContent>
)}
```

**Option B: New standalone page (simpler)**

Add a new route in `App.tsx`:
```tsx
import AIStyleSettings from "./pages/AIStyleSettings";

// In routes:
<Route path="/settings/ai-style" element={
  <ProtectedRoute>
    <Layout>
      <AIStyleSettings />
    </Layout>
  </ProtectedRoute>
} />
```

### 5. Frontend: Create the Component

Create `src/components/settings/AIStyleTab.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, Save, RotateCcw, Info } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { getPrompts, savePrompts, getPromptsHistory, revertPrompts, isAiBackendConfigured } from '@/lib/aiBackend';

const STEP_INFO = {
  '2': { label: 'Date Confirmation', icon: '📅', hint: 'How dates are presented to clients' },
  '3': { label: 'Room Availability', icon: '🏠', hint: 'How rooms are recommended' },
  '4': { label: 'Offer', icon: '💰', hint: 'How quotes are presented' },
  '5': { label: 'Negotiation', icon: '🤝', hint: 'How responses to decisions are written' },
  '7': { label: 'Confirmation', icon: '✅', hint: 'How final confirmations are communicated' },
};

export function AIStyleTab() {
  const [config, setConfig] = useState<any>(null);
  const [activeStep, setActiveStep] = useState('2');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  const loadConfig = useCallback(async () => {
    if (!isAiBackendConfigured()) {
      setError('AI backend not configured. Add VITE_AI_BACKEND_URL to .env');
      setLoading(false);
      return;
    }
    try {
      const data = await getPrompts();
      setConfig(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await savePrompts(config);
      toast({ title: 'Saved', description: 'Changes will take effect within 30 seconds.' });
    } catch (err: any) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (step: string, value: string) => {
    setConfig((prev: any) => ({
      ...prev,
      step_prompts: { ...prev.step_prompts, [step]: value },
    }));
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-8">
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Message Style</CardTitle>
        <CardDescription>
          Customize how the AI writes to your clients. Changes affect tone and phrasing, not the actual information shown.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            You can change how the AI phrases things, but dates, prices, and room names always stay accurate.
          </AlertDescription>
        </Alert>

        <Tabs value={activeStep} onValueChange={setActiveStep}>
          <TabsList className="grid grid-cols-5 w-full">
            {Object.entries(STEP_INFO).map(([key, info]) => (
              <TabsTrigger key={key} value={key} className="text-xs">
                {info.icon} {info.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {Object.entries(STEP_INFO).map(([key, info]) => (
            <TabsContent key={key} value={key} className="space-y-3">
              <p className="text-sm text-muted-foreground">{info.hint}</p>
              <Textarea
                value={config?.step_prompts?.[key] || ''}
                onChange={(e) => handleChange(key, e.target.value)}
                rows={6}
                placeholder={`Enter guidance for ${info.label}...`}
              />
            </TabsContent>
          ))}
        </Tabs>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={loadConfig}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            Save Changes
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
```

## CORS Configuration

If the frontend and backend are on different domains, enable CORS on the backend.

In `app.py` (Python backend), ensure CORS is configured:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev
        "https://your-frontend-domain.com",  # Production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Environment Variables Summary

### Backend (Python/Hostinger)
| Variable | Value | Purpose |
|----------|-------|---------|
| `PROMPTS_EDITOR_ENABLED` | `true` | Enables the API endpoints |

### Frontend (Lovable/Vercel)
| Variable | Value | Purpose |
|----------|-------|---------|
| `VITE_AI_BACKEND_URL` | `https://your-backend.com` | Points to Python backend |

## Deployment Checklist

- [ ] Backend: Set `PROMPTS_EDITOR_ENABLED=true`
- [ ] Backend: Verify CORS allows frontend domain
- [ ] Backend: Test `/api/config/prompts` returns 200
- [ ] Frontend: Add `VITE_AI_BACKEND_URL` to .env
- [ ] Frontend: Create `src/lib/aiBackend.ts`
- [ ] Frontend: Add AIStyleTab component
- [ ] Frontend: Wire into settings page or create new route
- [ ] Test: Can load prompts
- [ ] Test: Can save changes
- [ ] Test: Changes appear in AI responses within 30 seconds

## Admin-Only Access

The component should only be visible to admins. The example code uses:
```tsx
const canViewAIStyle = hasAtLeastRole('admin');
```

This uses the existing `usePermissions` hook from the frontend.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 404 on `/api/config/prompts` | Enable `PROMPTS_EDITOR_ENABLED=true` on backend |
| CORS error | Add frontend domain to backend CORS config |
| Changes not appearing | Wait 30 seconds (cache TTL) or restart backend |
| "AI backend not configured" | Add `VITE_AI_BACKEND_URL` to frontend .env |

## Alternative: Embed in atelier-ai-frontend

If you prefer to keep the prompts editor in the `atelier-ai-frontend` subfolder (where it already exists), you can:

1. Deploy `atelier-ai-frontend` as a separate app
2. Link to it from the main settings page with `target="_blank"`
3. Use the existing `/admin/prompts` route

This keeps the code separate but requires deploying two frontend apps.
