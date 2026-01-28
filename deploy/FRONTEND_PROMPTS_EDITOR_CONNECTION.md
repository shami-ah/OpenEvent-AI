# Connecting the Prompts Editor to the Main Frontend

This guide explains how to add the AI Message Customization feature to the OpeneventGithub production frontend.

## Architecture Overview

Your system has **two separate frontends**:

```
┌─────────────────────────────────────┐     ┌─────────────────────────────────────┐
│  Main Frontend (OpeneventGithub)    │     │  Test Frontend (atelier-ai-frontend)│
│  /Users/nico/Documents/GitHub/      │     │  OpenEvent-AI/atelier-ai-frontend/  │
│  OpeneventGithub/                   │     │                                     │
│                                     │     │  • Debug/admin tools                │
│  • Vite + React 18 + TypeScript     │     │  • Next.js 15                       │
│  • shadcn-ui + Tailwind CSS         │     │  • Prompts editor at /admin/prompts │
│  • Uses Supabase directly           │     │  • Connects to Python backend       │
│  • React Query for state            │     │  • Used for local testing only      │
└─────────────────────────────────────┘     └─────────────────────────────────────┘
                  │                                      │
                  │                                      │
                  ▼                                      ▼
          ┌─────────────┐                    ┌─────────────────────┐
          │  Supabase   │                    │  Python Backend     │
          │  (Database) │◄───────────────────│  (FastAPI/Hostinger)│
          └─────────────┘                    └─────────────────────┘
```

## OpeneventGithub Frontend Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 18.3.1 | UI framework |
| TypeScript | 5.5.3 | Type safety |
| Vite | 5.4.1 | Build tool (dev port 8080) |
| shadcn-ui | Latest | UI components |
| Tailwind CSS | 3.4.11 | Styling |
| React Query | 5.90.2 | Server state management |
| React Router DOM | 6.26.2 | Client routing |
| React Hook Form | 7.53.0 | Form handling |
| Zod | Latest | Validation |

## Two Integration Options

---

## Option A: Link to Admin Frontend (Recommended for Quick Deploy)

Deploy the test frontend (`atelier-ai-frontend`) and link to it from your main app.

### Step 1: Deploy Admin Frontend

```bash
cd OpenEvent-AI/atelier-ai-frontend
vercel --prod
```

**Environment variables needed:**
```
NEXT_PUBLIC_BACKEND_BASE=https://your-hostinger-backend.com
NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED=true
```

### Step 2: Add Link in Main Settings

In `OpeneventGithub/src/pages/PreferencesSettings.tsx`, add a card:

```tsx
// Add import at top
import { Sparkles, ExternalLink } from "lucide-react";

// In the settings content area, add:
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

---

## Option B: Native Integration (Full Experience)

Embed the prompts editor directly in OpeneventGithub. This provides the best UX.

### File Locations Summary

| What | Location in OpeneventGithub |
|------|----------------------------|
| New Page | `/src/pages/AIPromptsSetup.tsx` (create) |
| API Client | `/src/lib/aiBackend.ts` (create) |
| Custom Hook | `/src/hooks/useAIPrompts.ts` (create) |
| Route Config | `/src/App.tsx` line ~120 |
| Permission Config | `/src/lib/permissions/config.ts` line ~77 |
| Sidebar (optional) | `/src/components/AppSidebar.tsx` line ~55 |

---

### Step 1: Backend - Enable Feature Flag

On your Hostinger server:

```bash
# Add to /opt/openevent/.env
PROMPTS_EDITOR_ENABLED=true
```

Then restart: `systemctl restart openevent`

---

### Step 2: Frontend - Add Environment Variable

In `OpeneventGithub/.env`:

```bash
# Point to your Python backend
VITE_AI_BACKEND_URL=https://your-hostinger-backend.com

# For local development:
# VITE_AI_BACKEND_URL=http://localhost:8000
```

---

### Step 3: Create API Client

Create `/src/lib/aiBackend.ts`:

```typescript
/**
 * API client for the AI backend (Python/FastAPI)
 * Used for prompts editor and other AI configuration
 */

const AI_BACKEND_URL = import.meta.env.VITE_AI_BACKEND_URL || '';

export interface PromptConfig {
  system_prompt: string;
  step_prompts: Record<string, string>;
}

export interface HistoryEntry {
  ts: string;
  config: PromptConfig;
}

export async function getPrompts(): Promise<PromptConfig> {
  const res = await fetch(`${AI_BACKEND_URL}/api/config/prompts`);
  if (!res.ok) {
    if (res.status === 404) throw new Error('Prompts editor not enabled on backend');
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

---

### Step 4: Create React Query Hook

Create `/src/hooks/useAIPrompts.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getPrompts, savePrompts, getPromptsHistory, revertPrompts, PromptConfig } from '@/lib/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useAIPrompts() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const promptsQuery = useQuery({
    queryKey: ['ai-prompts'],
    queryFn: getPrompts,
    staleTime: 30 * 1000, // 30 seconds (matches backend cache)
    retry: 1,
  });

  const historyQuery = useQuery({
    queryKey: ['ai-prompts-history'],
    queryFn: getPromptsHistory,
    staleTime: 60 * 1000,
    retry: 1,
  });

  const saveMutation = useMutation({
    mutationFn: savePrompts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-prompts'] });
      queryClient.invalidateQueries({ queryKey: ['ai-prompts-history'] });
      toast({
        title: 'Saved',
        description: 'Changes will take effect within 30 seconds.',
      });
    },
    onError: (error: Error) => {
      toast({
        title: 'Error',
        description: error.message,
        variant: 'destructive',
      });
    },
  });

  const revertMutation = useMutation({
    mutationFn: revertPrompts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-prompts'] });
      queryClient.invalidateQueries({ queryKey: ['ai-prompts-history'] });
      toast({
        title: 'Restored',
        description: 'Previous version restored.',
      });
    },
    onError: (error: Error) => {
      toast({
        title: 'Error',
        description: error.message,
        variant: 'destructive',
      });
    },
  });

  return {
    prompts: promptsQuery.data,
    isLoading: promptsQuery.isLoading,
    error: promptsQuery.error,
    history: historyQuery.data,
    save: saveMutation.mutate,
    isSaving: saveMutation.isPending,
    revert: revertMutation.mutate,
    isReverting: revertMutation.isPending,
  };
}
```

---

### Step 5: Add Route Permission

In `/src/lib/permissions/config.ts`, add to the routes array (~line 77):

```typescript
const routes: RoutePermission[] = [
  // ... existing routes
  { path: '/setup/ai-prompts', allowedRoles: ['owner', 'admin'] },
];
```

---

### Step 6: Create the Page Component

Create `/src/pages/AIPromptsSetup.tsx`:

```tsx
import { useState, useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, Save, RotateCcw, Info, History } from "lucide-react";
import { usePermissions } from "@/hooks/usePermissions";
import { useAIPrompts } from '@/hooks/useAIPrompts';
import { isAiBackendConfigured, PromptConfig } from '@/lib/aiBackend';

const STEP_INFO: Record<string, { label: string; icon: string; hint: string }> = {
  '2': { label: 'Date Confirmation', icon: '📅', hint: 'How dates are presented to clients' },
  '3': { label: 'Room Availability', icon: '🏠', hint: 'How rooms are recommended' },
  '4': { label: 'Offer', icon: '💰', hint: 'How quotes are presented' },
  '5': { label: 'Negotiation', icon: '🤝', hint: 'How responses to decisions are written' },
  '7': { label: 'Confirmation', icon: '✅', hint: 'How final confirmations are communicated' },
};

const AIPromptsSetup = () => {
  const { hasAtLeastRole, isLoading: permLoading } = usePermissions();
  const { prompts, isLoading, error, save, isSaving, history, revert } = useAIPrompts();
  const [localConfig, setLocalConfig] = useState<PromptConfig | null>(null);
  const [activeStep, setActiveStep] = useState('2');
  const [showHistory, setShowHistory] = useState(false);

  // Sync prompts to local state for editing
  useEffect(() => {
    if (prompts) {
      setLocalConfig(prompts);
    }
  }, [prompts]);

  // Permission check
  if (!permLoading && !hasAtLeastRole('admin')) {
    return <Navigate to="/access-denied" replace />;
  }

  // Backend not configured
  if (!isAiBackendConfigured()) {
    return (
      <Card className="max-w-2xl mx-auto mt-8">
        <CardContent className="py-8">
          <Alert variant="destructive">
            <AlertDescription>
              AI backend not configured. Add <code>VITE_AI_BACKEND_URL</code> to your .env file.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  // Loading state
  if (isLoading || permLoading) {
    return (
      <Card className="max-w-2xl mx-auto mt-8">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (error) {
    return (
      <Card className="max-w-2xl mx-auto mt-8">
        <CardContent className="py-8">
          <Alert variant="destructive">
            <AlertDescription>{(error as Error).message}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  const handleChange = (step: string, value: string) => {
    if (!localConfig) return;
    setLocalConfig({
      ...localConfig,
      step_prompts: { ...localConfig.step_prompts, [step]: value },
    });
  };

  const handleSave = () => {
    if (localConfig) {
      save(localConfig);
    }
  };

  const handleReset = () => {
    if (prompts) {
      setLocalConfig(prompts);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">AI Message Style</h1>
          <p className="text-muted-foreground">
            Customize how the AI writes to your clients. Changes affect tone, not data accuracy.
          </p>
        </div>
        <Button variant="outline" onClick={() => setShowHistory(!showHistory)}>
          <History className="h-4 w-4 mr-2" />
          {showHistory ? 'Hide' : 'Show'} History
        </Button>
      </div>

      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          You can change how the AI phrases things, but dates, prices, and room names always stay accurate.
        </AlertDescription>
      </Alert>

      {showHistory && history && history.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Version History</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {history.slice(0, 5).map((entry, idx) => (
                <div key={idx} className="flex items-center justify-between p-2 bg-muted rounded">
                  <span className="text-sm">{new Date(entry.ts).toLocaleString()}</span>
                  <Button size="sm" variant="ghost" onClick={() => revert(idx)}>
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Step-by-Step Guidance</CardTitle>
          <CardDescription>
            Select a workflow step and customize the AI's communication style.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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
                  value={localConfig?.step_prompts?.[key] || ''}
                  onChange={(e) => handleChange(key, e.target.value)}
                  rows={6}
                  placeholder={`Enter guidance for ${info.label}...`}
                />
                <p className="text-xs text-muted-foreground">
                  {(localConfig?.step_prompts?.[key] || '').length} characters
                </p>
              </TabsContent>
            ))}
          </Tabs>

          <div className="flex justify-end gap-2 pt-4 border-t">
            <Button variant="outline" onClick={handleReset}>
              <RotateCcw className="h-4 w-4 mr-2" />
              Reset
            </Button>
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default AIPromptsSetup;
```

---

### Step 7: Add Route to App.tsx

In `/src/App.tsx` (~line 120, in the routes section):

```tsx
import AIPromptsSetup from "./pages/AIPromptsSetup";

// Add inside <Routes>:
<Route path="/setup/ai-prompts" element={
  <ProtectedRoute>
    <Layout>
      <AIPromptsSetup />
    </Layout>
  </ProtectedRoute>
} />
```

---

### Step 8: Add to Sidebar (Optional)

In `/src/components/AppSidebar.tsx` (~line 55), add to `allSetupItems`:

```tsx
import { Sparkles } from "lucide-react";

const allSetupItems = [
  // ... existing items
  { title: "AI Prompts", url: "/setup/ai-prompts", icon: Sparkles },
];
```

---

## CORS Configuration

Backend CORS must allow the frontend domain. In `/opt/openevent/.env`:

```bash
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,https://your-production-domain.com
```

---

## Environment Variables Summary

### Backend (Python/Hostinger)
| Variable | Value | Purpose |
|----------|-------|---------|
| `PROMPTS_EDITOR_ENABLED` | `true` | Enables API endpoints |
| `ALLOWED_ORIGINS` | `https://your-domain.com` | CORS for frontend |

### Frontend (OpeneventGithub)
| Variable | Value | Purpose |
|----------|-------|---------|
| `VITE_AI_BACKEND_URL` | `https://your-backend.com` | Points to Python backend |

---

## Deployment Checklist

### Backend
- [ ] `PROMPTS_EDITOR_ENABLED=true` in .env
- [ ] CORS allows frontend domain
- [ ] Test: `curl https://backend/api/config/prompts` returns 200

### Frontend
- [ ] `VITE_AI_BACKEND_URL` set in .env
- [ ] Created `/src/lib/aiBackend.ts`
- [ ] Created `/src/hooks/useAIPrompts.ts`
- [ ] Created `/src/pages/AIPromptsSetup.tsx`
- [ ] Added route to `/src/App.tsx`
- [ ] Added permission to `/src/lib/permissions/config.ts`
- [ ] (Optional) Added sidebar item

### Testing
- [ ] Can load prompts as admin
- [ ] Cannot access as non-admin (redirects to /access-denied)
- [ ] Can save changes
- [ ] Changes appear in AI responses within 30 seconds
- [ ] Version history loads
- [ ] Can restore previous version

---

## Testing Environment Toggle

To keep both environments working:

### Local Development (Test Frontend)
```bash
# In OpenEvent-AI/atelier-ai-frontend/
npm run dev  # Runs on localhost:3000
```
Backend auto-connects to `http://localhost:8000`

### Local Development (Production Frontend)
```bash
# In OpeneventGithub/
npm run dev  # Runs on localhost:8080
```
Uses `VITE_AI_BACKEND_URL` from `.env` (can point to localhost:8000 or production)

### Toggle Script

Create `OpeneventGithub/scripts/toggle-backend.sh`:
```bash
#!/bin/bash
# Toggle between local and production backend

if [ "$1" = "local" ]; then
  sed -i '' 's|^VITE_AI_BACKEND_URL=.*|VITE_AI_BACKEND_URL=http://localhost:8000|' .env
  echo "Switched to LOCAL backend"
elif [ "$1" = "prod" ]; then
  sed -i '' 's|^VITE_AI_BACKEND_URL=.*|VITE_AI_BACKEND_URL=https://your-hostinger-backend.com|' .env
  echo "Switched to PRODUCTION backend"
else
  echo "Usage: ./scripts/toggle-backend.sh [local|prod]"
fi
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 404 on `/api/config/prompts` | Enable `PROMPTS_EDITOR_ENABLED=true` on backend |
| CORS error | Add frontend domain to `ALLOWED_ORIGINS` |
| Changes not appearing | Wait 30 seconds (cache TTL) or restart backend |
| "AI backend not configured" | Add `VITE_AI_BACKEND_URL` to frontend .env |
| "Access denied" | User must have admin or owner role |
| Route not found | Ensure route is added to App.tsx inside `<Routes>` |

---

## Key OpeneventGithub Patterns Used

This integration follows existing patterns in the codebase:

| Pattern | Example From | Applied To |
|---------|--------------|------------|
| React Query hooks | `useEmails.ts` | `useAIPrompts.ts` |
| Permission checks | `usePermissions()` | Admin-only access |
| Route guards | `ProtectedRoute` | Page protection |
| Toast notifications | `useToast()` | Save/error feedback |
| Card-based layout | `PreferencesSettings.tsx` | Page structure |
| Tabs component | Settings tabs | Step selection |
| Environment variables | `VITE_SUPABASE_URL` | `VITE_AI_BACKEND_URL` |
