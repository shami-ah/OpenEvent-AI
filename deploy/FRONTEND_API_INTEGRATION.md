# Frontend API Integration Guide

Complete reference for connecting **OpeneventGithub** (React frontend) to **OpenEvent-AI** (Python/FastAPI backend).

---

## Quick Reference

| What | Where |
|------|-------|
| **Backend URL** | `http://72.60.135.183:8000` (Hostinger VPS) |
| **Environment Variable** | `VITE_AI_BACKEND_URL` |
| **Authentication** | `X-Team-Id` header for multi-tenancy |
| **Frontend Location** | `/Users/nico/Documents/GitHub/OpeneventGithub/` |
| **Tech Stack** | React 18 + Vite + React Query + TypeScript |

---

## Table of Contents

1. [Environment Setup](#1-environment-setup)
2. [API Client Module](#2-api-client-module)
3. [TypeScript Interfaces](#3-typescript-interfaces)
4. [React Query Hooks](#4-react-query-hooks)
5. [Endpoint Reference by Page](#5-endpoint-reference-by-page)
6. [Error Handling](#6-error-handling)
7. [Full Endpoint Catalog](#7-full-endpoint-catalog)

---

## 1. Environment Setup

### 1.1 Frontend Environment Variable

Add to `OpeneventGithub/.env`:

```bash
# Point to your Python backend
VITE_AI_BACKEND_URL=http://72.60.135.183:8000

# For local development:
# VITE_AI_BACKEND_URL=http://localhost:8000
```

### 1.2 Backend CORS Configuration

Backend `.env` on Hostinger must allow frontend domain:

```bash
ALLOWED_ORIGINS=https://lovable.dev,https://*.lovable.app,http://localhost:8080
```

### 1.3 Multi-Tenancy Header

All authenticated endpoints require the team identifier:

```typescript
const headers = {
  'Content-Type': 'application/json',
  'X-Team-Id': 'your-team-id',  // From Supabase auth context
};
```

---

## 2. API Client Module

Create `/src/lib/aiBackend.ts`:

```typescript
/**
 * API client for the OpenEvent AI backend (Python/FastAPI)
 */

const AI_BACKEND_URL = import.meta.env.VITE_AI_BACKEND_URL || '';

export function isAiBackendConfigured(): boolean {
  return Boolean(AI_BACKEND_URL);
}

export async function aiBackendFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  teamId?: string
): Promise<T> {
  const url = `${AI_BACKEND_URL}${endpoint}`;

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(teamId && { 'X-Team-Id': teamId }),
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new AIBackendError(
      errorBody.detail || `API error: ${response.status}`,
      response.status,
      errorBody
    );
  }

  return response.json();
}

export class AIBackendError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: Record<string, unknown>
  ) {
    super(message);
    this.name = 'AIBackendError';
  }
}
```

---

## 3. TypeScript Interfaces

Create `/src/types/aiBackend.ts`:

```typescript
// ============================================================================
// CONVERSATION FLOW
// ============================================================================

export interface StartConversationRequest {
  client_email: string;
  client_name?: string;
  email_body: string;
}

export interface SendMessageRequest {
  session_id: string;
  message: string;
}

export interface ConfirmDateRequest {
  date: string;  // ISO format: YYYY-MM-DD
}

export interface EventInfo {
  date_email_received?: string;
  event_date?: string;
  name?: string;
  email?: string;
  phone?: string;
  company?: string;
  billing_address?: string;
  start_time?: string;
  end_time?: string;
  preferred_room?: string;
  number_of_participants?: string;
  type_of_event?: string;
  catering_preference?: string;
  billing_amount?: string;
  deposit?: string;
  language?: string;
  additional_info?: string;
  status?: string;
}

export interface PendingAction {
  type: 'workflow_actions' | 'conflict' | 'special_request' | 'missing_product';
  actions?: Array<{
    label: string;
    action: string;
    payload?: Record<string, unknown>;
  }>;
  details?: Record<string, unknown>;
}

export interface DepositInfo {
  deposit_required: boolean;
  deposit_amount?: number;
  deposit_due_date?: string;
  deposit_paid: boolean;
  offer_accepted?: boolean;
  event_id?: string;
}

export interface ProgressStage {
  id: 'date' | 'room' | 'offer' | 'deposit' | 'confirmed';
  label: string;
  status: 'completed' | 'active' | 'pending';
  icon: string;
}

export interface ProgressSummary {
  current_stage: string;
  stages: ProgressStage[];
  percentage: number;
}

export interface ConversationResponse {
  session_id: string;
  workflow_type: 'new_event' | 'standalone_qna' | 'dev_choice' | 'other';
  response: string;
  is_complete: boolean;
  event_info: EventInfo | null;
  pending_actions?: PendingAction | null;
  deposit_info?: DepositInfo | null;
  progress?: ProgressSummary | null;
  dev_choice?: DevChoiceInfo;
}

export interface DevChoiceInfo {
  client_id: string;
  event_id: string;
  current_step: number;
  step_name: string;
  event_date?: string;
  locked_room?: string;
  offer_accepted?: boolean;
  options: string[];
}

export interface ConversationState {
  session_id: string;
  conversation_history: Array<{ role: 'user' | 'assistant'; content: string }>;
  event_info: EventInfo;
  is_complete: boolean;
}

// ============================================================================
// HIL TASKS
// ============================================================================

export interface TaskPayload {
  snippet?: string;
  draft_body?: string;
  suggested_dates?: string[];
  thread_id?: string;
  step_id?: number;
  event_summary?: TaskEventSummary;
}

export interface TaskEventSummary {
  client_name?: string;
  company?: string;
  billing_address?: string;
  email?: string;
  chosen_date?: string;
  locked_room?: string;
  line_items?: string[];
  current_step?: number;
  offer_total?: number;
  deposit_info?: DepositInfo;
}

export type TaskType =
  | 'ai_reply_approval'
  | 'manual_review'
  | 'source_missing_product'
  | 'offer_message'
  | 'room_availability_message'
  | 'date_confirmation_message'
  | 'ask_for_date';

export interface HILTask {
  task_id: string;
  type: TaskType;
  client_id?: string;
  event_id?: string;
  created_at: string;
  notes?: string;
  payload: TaskPayload;
}

export interface TasksResponse {
  tasks: HILTask[];
}

export interface TaskDecisionRequest {
  notes?: string;
  edited_message?: string;
  sourced_product_name?: string;
  sourced_product_price?: string;
}

export interface TaskApprovalResponse {
  task_id: string;
  task_status: 'approved' | 'rejected';
  assistant_reply?: string;
  thread_id?: string;
  event_id?: string;
  review_state: 'approved' | 'rejected';
  advance_to_step?: number;
}

// ============================================================================
// EVENTS
// ============================================================================

export interface Event {
  event_id: string;
  created_at: string;
  status?: string;
  current_step?: number;
  thread_state?: string;
  chosen_date?: string;
  locked_room_id?: string;
  offer_accepted?: boolean;
  event_data?: EventInfo;
  deposit_info?: DepositInfo;
  requirements?: {
    number_of_participants?: number;
    [key: string]: unknown;
  };
  products?: Array<{
    name: string;
    quantity?: number;
    unit_price?: number;
    unit?: 'per_person' | 'per_event';
  }>;
}

export interface EventsResponse {
  total_events: number;
  events: Event[];
}

export interface CancelEventRequest {
  event_id: string;
  confirmation: 'CANCEL';
  reason?: string;
}

export interface CancelEventResponse {
  status: 'cancelled' | 'already_cancelled';
  event_id: string;
  previous_step?: number;
  had_site_visit?: boolean;
  cancellation_type?: 'site_visit' | 'standard';
  archived_at?: string;
}

// ============================================================================
// ACTIVITY LOGGER
// ============================================================================

export interface Activity {
  id: string;
  timestamp: string;
  icon: string;
  title: string;
  detail?: string;
  granularity: 'high' | 'detailed';
}

export interface ActivityResponse {
  activities: Activity[];
  has_more: boolean;
  event_id: string;
  granularity: 'high' | 'detailed';
}

// ============================================================================
// EMAILS
// ============================================================================

export interface SendClientEmailRequest {
  to_email: string;
  to_name: string;
  subject: string;
  body_text: string;
  body_html?: string;
  event_id?: string;
  task_id?: string;
}

export interface SendOfferEmailRequest {
  event_id: string;
  subject?: string;
  custom_message?: string;
}

export interface EmailResponse {
  success: boolean;
  message: string;
  simulated?: boolean;
  to_email?: string;
  subject?: string;
  offer_total?: number;
}

// ============================================================================
// CONFIGURATION
// ============================================================================

export interface GlobalDepositConfig {
  deposit_enabled: boolean;
  deposit_type: 'percentage' | 'fixed';
  deposit_percentage: number;
  deposit_fixed_amount: number;
  deposit_deadline_days: number;
}

export interface HILModeConfig {
  enabled: boolean;
  source?: 'database' | 'environment' | 'default';
  updated_at?: string;
}

export interface LLMProviderConfig {
  intent_provider: 'openai' | 'gemini' | 'stub';
  entity_provider: 'openai' | 'gemini' | 'stub';
  verbalization_provider: 'openai' | 'gemini' | 'stub';
  source?: string;
  updated_at?: string;
}

export interface VenueConfig {
  name?: string;
  city?: string;
  timezone?: string;
  currency_code?: string;
  operating_hours?: { start: number; end: number };
  from_email?: string;
  from_name?: string;
  frontend_url?: string;
  source?: string;
}

export interface SiteVisitConfig {
  blocked_dates: string[];
  default_slots: number[];
  weekdays_only: boolean;
  min_days_ahead: number;
  source?: string;
}

export interface ManagerConfig {
  names: string[];
  source?: string;
}

export interface PromptConfig {
  system_prompt: string;
  step_prompts: Record<number, string>;
}

export interface PromptHistoryEntry {
  ts: string;
  config: PromptConfig;
}

// ============================================================================
// TEST DATA
// ============================================================================

export interface Room {
  room_id: string;
  name: string;
  capacity: number;
  amenities?: string[];
  [key: string]: unknown;
}

export interface CateringMenu {
  name: string;
  slug: string;
  price_per_person: string;
  description?: string;
  courses?: number;
  [key: string]: unknown;
}
```

---

## 4. React Query Hooks

### 4.1 useConversation.ts

Create `/src/hooks/useConversation.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type {
  StartConversationRequest,
  SendMessageRequest,
  ConfirmDateRequest,
  ConversationResponse,
  ConversationState,
} from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useConversation(teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const startConversation = useMutation({
    mutationFn: (data: StartConversationRequest) =>
      aiBackendFetch<ConversationResponse>('/api/start-conversation', {
        method: 'POST',
        body: JSON.stringify(data),
      }, teamId),
    onSuccess: (data) => {
      if (data.session_id) {
        queryClient.setQueryData(['conversation', data.session_id], data);
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const sendMessage = useMutation({
    mutationFn: (data: SendMessageRequest) =>
      aiBackendFetch<ConversationResponse>('/api/send-message', {
        method: 'POST',
        body: JSON.stringify(data),
      }, teamId),
    onSuccess: (data) => {
      if (data.session_id) {
        queryClient.invalidateQueries({ queryKey: ['conversation', data.session_id] });
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const confirmDate = useMutation({
    mutationFn: ({ sessionId, date }: { sessionId: string; date: string }) =>
      aiBackendFetch<ConversationResponse>(
        `/api/conversation/${sessionId}/confirm-date`,
        { method: 'POST', body: JSON.stringify({ date }) },
        teamId
      ),
  });

  const acceptBooking = useMutation({
    mutationFn: (sessionId: string) =>
      aiBackendFetch(`/api/accept-booking/${sessionId}`, { method: 'POST' }, teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['events'] });
      toast({ title: 'Booking accepted' });
    },
  });

  const rejectBooking = useMutation({
    mutationFn: (sessionId: string) =>
      aiBackendFetch(`/api/reject-booking/${sessionId}`, { method: 'POST' }, teamId),
    onSuccess: () => {
      toast({ title: 'Booking rejected' });
    },
  });

  return {
    startConversation,
    sendMessage,
    confirmDate,
    acceptBooking,
    rejectBooking,
  };
}

export function useConversationState(sessionId: string | null, teamId: string) {
  return useQuery({
    queryKey: ['conversation', sessionId],
    queryFn: () =>
      aiBackendFetch<ConversationState>(`/api/conversation/${sessionId}`, {}, teamId),
    enabled: Boolean(sessionId),
    staleTime: 10 * 1000,
  });
}
```

### 4.2 useHILTasks.ts

Create `/src/hooks/useHILTasks.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type {
  TasksResponse,
  TaskDecisionRequest,
  TaskApprovalResponse,
} from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useHILTasks(teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const tasksQuery = useQuery({
    queryKey: ['hil-tasks', teamId],
    queryFn: () => aiBackendFetch<TasksResponse>('/api/tasks/pending', {}, teamId),
    refetchInterval: 30 * 1000,  // Poll every 30s
    staleTime: 10 * 1000,
  });

  const approveTask = useMutation({
    mutationFn: ({ taskId, data }: { taskId: string; data?: TaskDecisionRequest }) =>
      aiBackendFetch<TaskApprovalResponse>(
        `/api/tasks/${taskId}/approve`,
        { method: 'POST', body: JSON.stringify(data || {}) },
        teamId
      ),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['hil-tasks'] });
      queryClient.invalidateQueries({ queryKey: ['events'] });
      toast({
        title: 'Task approved',
        description: result.assistant_reply ? 'Message sent to client.' : 'Task completed.',
      });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const rejectTask = useMutation({
    mutationFn: ({ taskId, notes }: { taskId: string; notes?: string }) =>
      aiBackendFetch<TaskApprovalResponse>(
        `/api/tasks/${taskId}/reject`,
        { method: 'POST', body: JSON.stringify({ notes }) },
        teamId
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hil-tasks'] });
      toast({ title: 'Task rejected' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const cleanupTasks = useMutation({
    mutationFn: (keepThreadId?: string) =>
      aiBackendFetch('/api/tasks/cleanup', {
        method: 'POST',
        body: JSON.stringify({ keep_thread_id: keepThreadId }),
      }, teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hil-tasks'] });
    },
  });

  return {
    tasks: tasksQuery.data?.tasks || [],
    isLoading: tasksQuery.isLoading,
    error: tasksQuery.error,
    refetch: tasksQuery.refetch,
    approveTask,
    rejectTask,
    cleanupTasks,
  };
}
```

### 4.3 useAIEvents.ts

Create `/src/hooks/useAIEvents.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type {
  Event,
  EventsResponse,
  CancelEventRequest,
  CancelEventResponse,
  DepositInfo,
} from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useAIEvents(teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const eventsQuery = useQuery({
    queryKey: ['events', teamId],
    queryFn: () => aiBackendFetch<EventsResponse>('/api/events', {}, teamId),
    staleTime: 30 * 1000,
  });

  const cancelEvent = useMutation({
    mutationFn: (data: CancelEventRequest) =>
      aiBackendFetch<CancelEventResponse>(
        `/api/event/${data.event_id}/cancel`,
        { method: 'POST', body: JSON.stringify(data) },
        teamId
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['events'] });
      toast({ title: 'Event cancelled' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  return {
    events: eventsQuery.data?.events || [],
    total: eventsQuery.data?.total_events || 0,
    isLoading: eventsQuery.isLoading,
    error: eventsQuery.error,
    refetch: eventsQuery.refetch,
    cancelEvent,
  };
}

export function useAIEvent(eventId: string | null, teamId: string) {
  return useQuery({
    queryKey: ['event', eventId, teamId],
    queryFn: () => aiBackendFetch<Event>(`/api/events/${eventId}`, {}, teamId),
    enabled: Boolean(eventId),
    staleTime: 30 * 1000,
  });
}

export function useEventDeposit(eventId: string | null, teamId: string) {
  return useQuery({
    queryKey: ['event-deposit', eventId, teamId],
    queryFn: () =>
      aiBackendFetch<DepositInfo & { event_id: string; current_step: number }>(
        `/api/event/${eventId}/deposit`,
        {},
        teamId
      ),
    enabled: Boolean(eventId),
    staleTime: 30 * 1000,
  });
}

export function usePayDeposit(teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (eventId: string) =>
      aiBackendFetch('/api/event/deposit/pay', {
        method: 'POST',
        body: JSON.stringify({ event_id: eventId }),
      }, teamId),
    onSuccess: (_, eventId) => {
      queryClient.invalidateQueries({ queryKey: ['event-deposit', eventId] });
      queryClient.invalidateQueries({ queryKey: ['events'] });
      toast({ title: 'Deposit marked as paid' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}
```

### 4.4 useAIActivity.ts

Create `/src/hooks/useAIActivity.ts`:

```typescript
import { useQuery } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type { ProgressSummary, ActivityResponse } from '@/types/aiBackend';

export function useEventProgress(eventId: string | null, teamId: string) {
  return useQuery({
    queryKey: ['event-progress', eventId, teamId],
    queryFn: () =>
      aiBackendFetch<ProgressSummary>(`/api/events/${eventId}/progress`, {}, teamId),
    enabled: Boolean(eventId),
    staleTime: 30 * 1000,
  });
}

export function useEventActivity(
  eventId: string | null,
  teamId: string,
  options?: {
    granularity?: 'high' | 'detailed';
    limit?: number;
  }
) {
  const { granularity = 'high', limit = 50 } = options || {};

  return useQuery({
    queryKey: ['event-activity', eventId, granularity, limit, teamId],
    queryFn: () =>
      aiBackendFetch<ActivityResponse>(
        `/api/events/${eventId}/activity?granularity=${granularity}&limit=${limit}`,
        {},
        teamId
      ),
    enabled: Boolean(eventId),
    staleTime: 15 * 1000,
  });
}
```

### 4.5 useAIConfig.ts

Create `/src/hooks/useAIConfig.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type {
  GlobalDepositConfig,
  HILModeConfig,
  VenueConfig,
  SiteVisitConfig,
  ManagerConfig,
  LLMProviderConfig,
} from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

type ConfigKey =
  | 'global-deposit'
  | 'hil-mode'
  | 'venue'
  | 'site-visit'
  | 'managers'
  | 'llm-provider'
  | 'email-format'
  | 'products'
  | 'menus'
  | 'catalog'
  | 'faq';

export function useAIConfigQuery<T>(configKey: ConfigKey, teamId: string) {
  return useQuery({
    queryKey: ['ai-config', configKey, teamId],
    queryFn: () => aiBackendFetch<T>(`/api/config/${configKey}`, {}, teamId),
    staleTime: 60 * 1000,
  });
}

export function useAIConfigMutation<T>(configKey: ConfigKey, teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (data: T) =>
      aiBackendFetch(`/api/config/${configKey}`, {
        method: 'POST',
        body: JSON.stringify(data),
      }, teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-config', configKey] });
      toast({ title: 'Settings saved' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });
}

// Typed convenience hooks
export function useHILMode(teamId: string) {
  const query = useAIConfigQuery<HILModeConfig>('hil-mode', teamId);
  const mutation = useAIConfigMutation<{ enabled: boolean }>('hil-mode', teamId);

  return {
    isEnabled: query.data?.enabled ?? false,
    source: query.data?.source,
    isLoading: query.isLoading,
    toggle: (enabled: boolean) => mutation.mutate({ enabled }),
    isSaving: mutation.isPending,
  };
}

export function useGlobalDeposit(teamId: string) {
  const query = useAIConfigQuery<GlobalDepositConfig>('global-deposit', teamId);
  const mutation = useAIConfigMutation<GlobalDepositConfig>('global-deposit', teamId);

  return {
    config: query.data,
    isLoading: query.isLoading,
    save: mutation.mutate,
    isSaving: mutation.isPending,
  };
}

export function useVenueConfig(teamId: string) {
  const query = useAIConfigQuery<VenueConfig>('venue', teamId);
  const mutation = useAIConfigMutation<Partial<VenueConfig>>('venue', teamId);

  return {
    config: query.data,
    isLoading: query.isLoading,
    save: mutation.mutate,
    isSaving: mutation.isPending,
  };
}
```

### 4.6 useAIPrompts.ts

Create `/src/hooks/useAIPrompts.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type { PromptConfig, PromptHistoryEntry } from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useAIPrompts(teamId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const promptsQuery = useQuery({
    queryKey: ['ai-prompts', teamId],
    queryFn: () => aiBackendFetch<PromptConfig>('/api/config/prompts', {}, teamId),
    staleTime: 30 * 1000,
    retry: 1,
  });

  const historyQuery = useQuery({
    queryKey: ['ai-prompts-history', teamId],
    queryFn: async () => {
      const result = await aiBackendFetch<{ history: PromptHistoryEntry[] }>(
        '/api/config/prompts/history',
        {},
        teamId
      );
      return result.history;
    },
    staleTime: 60 * 1000,
    retry: 1,
  });

  const saveMutation = useMutation({
    mutationFn: (config: PromptConfig) =>
      aiBackendFetch('/api/config/prompts', {
        method: 'POST',
        body: JSON.stringify(config),
      }, teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-prompts'] });
      queryClient.invalidateQueries({ queryKey: ['ai-prompts-history'] });
      toast({
        title: 'Saved',
        description: 'Changes will take effect within 30 seconds.',
      });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const revertMutation = useMutation({
    mutationFn: (index: number) =>
      aiBackendFetch(`/api/config/prompts/revert/${index}`, { method: 'POST' }, teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-prompts'] });
      queryClient.invalidateQueries({ queryKey: ['ai-prompts-history'] });
      toast({ title: 'Restored', description: 'Previous version restored.' });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  return {
    prompts: promptsQuery.data,
    isLoading: promptsQuery.isLoading,
    error: promptsQuery.error,
    history: historyQuery.data || [],
    save: saveMutation.mutate,
    isSaving: saveMutation.isPending,
    revert: revertMutation.mutate,
    isReverting: revertMutation.isPending,
  };
}
```

### 4.7 useEmails.ts

Create `/src/hooks/useEmails.ts`:

```typescript
import { useMutation } from '@tanstack/react-query';
import { aiBackendFetch } from '@/lib/aiBackend';
import type {
  SendClientEmailRequest,
  SendOfferEmailRequest,
  EmailResponse,
} from '@/types/aiBackend';
import { useToast } from '@/hooks/use-toast';

export function useEmails(teamId: string) {
  const { toast } = useToast();

  const sendToClient = useMutation({
    mutationFn: (data: SendClientEmailRequest) =>
      aiBackendFetch<EmailResponse>('/api/emails/send-to-client', {
        method: 'POST',
        body: JSON.stringify(data),
      }, teamId),
    onSuccess: (result) => {
      if (result.simulated) {
        toast({
          title: 'Email queued',
          description: 'Would send in production (SMTP not configured).',
        });
      } else {
        toast({ title: 'Email sent', description: `Sent to ${result.to_email}` });
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  const sendOffer = useMutation({
    mutationFn: (data: SendOfferEmailRequest) =>
      aiBackendFetch<EmailResponse>('/api/emails/send-offer', {
        method: 'POST',
        body: JSON.stringify(data),
      }, teamId),
    onSuccess: (result) => {
      toast({
        title: 'Offer sent',
        description: result.offer_total
          ? `Total: CHF ${result.offer_total.toLocaleString()}`
          : 'Offer email sent.',
      });
    },
    onError: (error: Error) => {
      toast({ title: 'Error', description: error.message, variant: 'destructive' });
    },
  });

  return {
    sendToClient,
    sendOffer,
  };
}
```

---

## 5. Endpoint Reference by Page

### 5.1 Inbox Page (`/inbox`)

| Action | Endpoint | Hook |
|--------|----------|------|
| Start new AI conversation | `POST /api/start-conversation` | `useConversation().startConversation` |
| Send follow-up message | `POST /api/send-message` | `useConversation().sendMessage` |
| Get conversation state | `GET /api/conversation/{id}` | `useConversationState()` |
| Accept booking | `POST /api/accept-booking/{id}` | `useConversation().acceptBooking` |
| Reject booking | `POST /api/reject-booking/{id}` | `useConversation().rejectBooking` |

**Usage Example:**
```typescript
const { startConversation, sendMessage } = useConversation(teamId);

// When email arrives, start AI conversation
const result = await startConversation.mutateAsync({
  client_email: email.from,
  client_name: email.fromName,
  email_body: email.body,
});

// Send follow-up
await sendMessage.mutateAsync({
  session_id: result.session_id,
  message: userReply,
});
```

### 5.2 Tasks Page (`/tasks`)

| Action | Endpoint | Hook |
|--------|----------|------|
| List pending tasks | `GET /api/tasks/pending` | `useHILTasks().tasks` |
| Approve task | `POST /api/tasks/{id}/approve` | `useHILTasks().approveTask` |
| Reject task | `POST /api/tasks/{id}/reject` | `useHILTasks().rejectTask` |
| Cleanup old tasks | `POST /api/tasks/cleanup` | `useHILTasks().cleanupTasks` |
| Send email after approval | `POST /api/emails/send-to-client` | `useEmails().sendToClient` |

**Usage Example:**
```typescript
const { tasks, approveTask } = useHILTasks(teamId);
const { sendToClient } = useEmails(teamId);

// Approve with edits
await approveTask.mutateAsync({
  taskId: task.task_id,
  data: { edited_message: editedDraft, notes: 'Approved with minor edits' },
});

// Then send the email
await sendToClient.mutateAsync({
  to_email: task.payload.event_summary?.email,
  to_name: task.payload.event_summary?.client_name || 'Client',
  subject: 'Re: Your booking inquiry',
  body_text: editedDraft,
  event_id: task.event_id,
  task_id: task.task_id,
});
```

### 5.3 Calendar Page (`/calendar`)

| Action | Endpoint | Hook |
|--------|----------|------|
| List all events | `GET /api/events` | `useAIEvents().events` |
| Get event details | `GET /api/events/{id}` | `useAIEvent()` |
| Get workflow progress | `GET /api/events/{id}/progress` | `useEventProgress()` |
| Get activity log | `GET /api/events/{id}/activity` | `useEventActivity()` |
| Get deposit status | `GET /api/event/{id}/deposit` | `useEventDeposit()` |
| Cancel event | `POST /api/event/{id}/cancel` | `useAIEvents().cancelEvent` |
| Send offer | `POST /api/emails/send-offer` | `useEmails().sendOffer` |

**Usage Example:**
```typescript
const { events } = useAIEvents(teamId);
const { data: progress } = useEventProgress(selectedEventId, teamId);
const { data: activity } = useEventActivity(selectedEventId, teamId, {
  granularity: showDetails ? 'detailed' : 'high',
});

// Display progress bar
<ProgressBar stages={progress?.stages} percentage={progress?.percentage} />

// Display activity timeline
<ActivityTimeline activities={activity?.activities} />
```

### 5.4 Settings Page (`/settings`)

| Action | Endpoint | Hook |
|--------|----------|------|
| Get/Set HIL mode | `GET/POST /api/config/hil-mode` | `useHILMode()` |
| Get/Set deposit config | `GET/POST /api/config/global-deposit` | `useGlobalDeposit()` |
| Get/Set LLM provider | `GET/POST /api/config/llm-provider` | `useAIConfigQuery/Mutation('llm-provider')` |
| Get/Set email format | `GET/POST /api/config/email-format` | `useAIConfigQuery/Mutation('email-format')` |

**Usage Example:**
```typescript
const { isEnabled, toggle, isSaving } = useHILMode(teamId);

<Switch
  checked={isEnabled}
  onCheckedChange={toggle}
  disabled={isSaving}
/>
```

### 5.5 Setup Pages

#### Venue Setup (`/setup/venue`)

| Endpoint | Method | Hook |
|----------|--------|------|
| `/api/config/venue` | GET/POST | `useVenueConfig()` |

#### AI Prompts (`/setup/ai-prompts`)

| Endpoint | Method | Hook |
|----------|--------|------|
| `/api/config/prompts` | GET/POST | `useAIPrompts().prompts/save` |
| `/api/config/prompts/history` | GET | `useAIPrompts().history` |
| `/api/config/prompts/revert/{i}` | POST | `useAIPrompts().revert` |

See [FRONTEND_PROMPTS_EDITOR_CONNECTION.md](./FRONTEND_PROMPTS_EDITOR_CONNECTION.md) for detailed implementation.

#### Site Visit (`/setup/site-visit`)

| Endpoint | Method | Hook |
|----------|--------|------|
| `/api/config/site-visit` | GET/POST | `useAIConfigQuery/Mutation('site-visit')` |

#### Managers (`/setup/managers`)

| Endpoint | Method | Hook |
|----------|--------|------|
| `/api/config/managers` | GET/POST | `useAIConfigQuery/Mutation('managers')` |

### 5.6 Info Pages

| Page | Endpoint | Hook |
|------|----------|------|
| `/info/rooms` | `GET /api/test-data/rooms` | Direct fetch |
| `/info/catering` | `GET /api/test-data/catering` | Direct fetch |
| `/info/qna` | `GET /api/qna` | Direct fetch |
| Snapshot data | `GET /api/snapshots/{id}` | Direct fetch |

---

## 6. Error Handling

### 6.1 Error Response Format

```typescript
// Backend error response
{
  "detail": "Human-readable error message"
}

// For validation errors
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### 6.2 Common HTTP Status Codes

| Status | Meaning | Frontend Action |
|--------|---------|-----------------|
| 200 | Success | Process response |
| 400 | Validation error | Show form errors |
| 401 | Unauthorized | Redirect to login |
| 403 | Forbidden | Show access denied |
| 404 | Not found | Show "not found" state |
| 500 | Server error | Show retry option |

### 6.3 Error Handling Pattern

```typescript
import { AIBackendError } from '@/lib/aiBackend';

try {
  await startConversation.mutateAsync(data);
} catch (error) {
  if (error instanceof AIBackendError) {
    if (error.status === 404) {
      // Handle not found
    } else if (error.status === 400) {
      // Handle validation error
    }
  }
  // Generic error handling
}
```

---

## 7. Full Endpoint Catalog

### 7.1 CRITICAL (MVP) - 10 endpoints

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/start-conversation` | POST | `{client_email, email_body}` | `ConversationResponse` |
| `/api/send-message` | POST | `{session_id, message}` | `ConversationResponse` |
| `/api/conversation/{id}` | GET | - | `ConversationState` |
| `/api/accept-booking/{id}` | POST | - | `{message, event_id}` |
| `/api/reject-booking/{id}` | POST | - | `{message}` |
| `/api/tasks/pending` | GET | - | `{tasks: HILTask[]}` |
| `/api/tasks/{id}/approve` | POST | `TaskDecisionRequest` | `TaskApprovalResponse` |
| `/api/tasks/{id}/reject` | POST | `{notes?}` | `TaskApprovalResponse` |
| `/api/events` | GET | - | `EventsResponse` |
| `/api/events/{id}` | GET | - | `Event` |

### 7.2 HIGH Priority - 12 endpoints

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/events/{id}/progress` | GET | - | `ProgressSummary` |
| `/api/events/{id}/activity` | GET | `?granularity=high&limit=50` | `ActivityResponse` |
| `/api/event/{id}/deposit` | GET | - | `DepositInfo` |
| `/api/event/deposit/pay` | POST | `{event_id}` | Status + workflow state |
| `/api/event/{id}/cancel` | POST | `CancelEventRequest` | `CancelEventResponse` |
| `/api/emails/send-to-client` | POST | `SendClientEmailRequest` | `EmailResponse` |
| `/api/emails/send-offer` | POST | `SendOfferEmailRequest` | `EmailResponse` |
| `/api/config/hil-mode` | GET | - | `HILModeConfig` |
| `/api/config/hil-mode` | POST | `{enabled}` | Status |
| `/api/config/global-deposit` | GET | - | `GlobalDepositConfig` |
| `/api/config/global-deposit` | POST | `GlobalDepositConfig` | Status |
| `/api/config/venue` | GET/POST | `VenueConfig` | `VenueConfig` |

### 7.3 MEDIUM Priority - 20+ endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/config/prompts` | GET/POST | LLM prompt configuration |
| `/api/config/prompts/history` | GET | Prompt version history |
| `/api/config/prompts/revert/{i}` | POST | Revert to previous version |
| `/api/config/llm-provider` | GET/POST | LLM provider routing |
| `/api/config/site-visit` | GET/POST | Site visit scheduling |
| `/api/config/managers` | GET/POST | Manager list for escalation |
| `/api/config/products` | GET/POST | Product autofill settings |
| `/api/config/menus` | GET/POST | Catering menu configuration |
| `/api/config/catalog` | GET/POST | Product-room availability |
| `/api/config/faq` | GET/POST | FAQ entries |
| `/api/config/email-format` | GET/POST | Plain text vs Markdown |
| `/api/config/hil-email` | GET/POST | HIL email notifications |
| `/api/config/pre-filter` | GET/POST | Detection pre-filter mode |
| `/api/config/detection-mode` | GET/POST | Unified vs legacy detection |
| `/api/config/hybrid-enforcement` | GET/POST | Hybrid mode enforcement |
| `/api/config/room-deposit/{id}` | GET/POST | Per-room deposit settings |
| `/api/test-data/rooms` | GET | Room data (dev) |
| `/api/test-data/catering` | GET | Catering menus (dev) |
| `/api/qna` | GET | Q&A data |
| `/api/snapshots/{id}` | GET | Snapshot data |
| `/api/workflow/health` | GET | Health check |

### 7.4 Agent/ChatKit - 4 endpoints (for real-time chat widget)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agent/reply` | POST | Non-streaming JSON response |
| `/api/agent/chatkit/session` | POST | Mint session token |
| `/api/agent/chatkit/respond` | POST | Streaming SSE response |
| `/api/agent/chatkit/upload` | POST | File upload (10MB max) |

**Note:** The main OpenEvent app uses email-based communication (`/api/send-message`), not ChatKit. ChatKit is for embedding real-time chat widgets on public websites.

---

## Related Documentation

- [API_TESTS.md](./API_TESTS.md) - Curl examples for all endpoints
- [FRONTEND_PROMPTS_EDITOR_CONNECTION.md](./FRONTEND_PROMPTS_EDITOR_CONNECTION.md) - Detailed prompts editor integration
- [README.md](./README.md) - Deployment guide

---

*Last updated: 2026-01-28*
