import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Send, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import DepositSettings from '../components/DepositSettings';

const BACKEND_BASE =
  (import.meta.env.VITE_BACKEND_BASE || 'http://localhost:8000').replace(/\/$/, '');
const API_BASE = `${BACKEND_BASE}/api`;

interface MessageMeta {
  confirmDate?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  meta?: MessageMeta;
  streaming?: boolean;
}

interface EventInfo {
  [key: string]: string;
}

interface DepositInfo {
  deposit_required: boolean;
  deposit_amount?: number | null;
  deposit_vat_included?: number | null;
  deposit_due_date?: string | null;
  deposit_paid: boolean;
  deposit_paid_at?: string | null;
}

interface PendingTaskPayload {
  snippet?: string | null;
  suggested_dates?: string[] | null;
  thread_id?: string | null;
  draft_body?: string | null;
  step_id?: number | null;
  current_step?: number | null;
  event_summary?: {
    client_name?: string | null;
    company?: string | null;
    billing_address?: string | null;
    email?: string | null;
    chosen_date?: string | null;
    locked_room?: string | null;
    offer_total?: number | null;
    deposit_info?: DepositInfo | null;
    current_step?: number | null;
  } | null;
}

interface PendingTask {
  task_id: string;
  type: string;
  client_id?: string | null;
  event_id?: string | null;
  created_at?: string | null;
  notes?: string | null;
  payload?: PendingTaskPayload | null;
}

interface PendingActions {
  type?: string;
  date?: string;
}

interface WorkflowDepositInfo {
  deposit_required: boolean;
  deposit_amount: number | null;
  deposit_due_date: string | null;
  deposit_paid: boolean;
  event_id: string | null;
}

interface WorkflowReply {
  session_id?: string | null;
  workflow_type?: string | null;
  response: string;
  is_complete: boolean;
  event_info?: EventInfo | null;
  pending_actions?: PendingActions | null;
  deposit_info?: DepositInfo | null;
}

function debounce<T extends (...args: unknown[]) => void>(fn: T, delay: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: Parameters<T>) => {
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function requestJSON<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  if (response.status === 204) {
    return {} as T;
  }
  return (await response.json()) as T;
}

async function fetchWorkflowReply(url: string, payload: unknown): Promise<WorkflowReply> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  const decoder = new TextDecoder();
  let buffer = '';
  if (response.body) {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
    }
    buffer += decoder.decode();
  } else {
    buffer = await response.text();
  }

  if (!response.ok) {
    throw new Error(buffer || `Request failed with status ${response.status}`);
  }
  if (!buffer.trim()) {
    return { response: '', is_complete: false };
  }
  try {
    return JSON.parse(buffer) as WorkflowReply;
  } catch (err) {
    console.error('Unable to parse workflow reply', err);
    throw err;
  }
}

function extractEmail(text: string): string {
  const emailRegex = /[\w.-]+@[\w.-]+\.[A-Za-z]{2,}/;
  const match = text.match(emailRegex);
  return match ? match[0] : 'unknown@example.com';
}

function buildMeta(pending: PendingActions | null | undefined): MessageMeta | undefined {
  if (pending?.type === 'confirm_date' && typeof pending.date === 'string') {
    return { confirmDate: pending.date };
  }
  return undefined;
}

function shouldDisplayEventField(key: string, value: string): boolean {
  if (value === 'Not specified' || value === 'none') {
    return false;
  }
  const lowerKey = key.toLowerCase();
  if (lowerKey.includes('room_') && lowerKey.endsWith('_status')) {
    return false;
  }
  return true;
}

function highlightImportantValues(text: string): string {
  let result = text.replace(/\b(Room\s+[A-Z])\b/gi, '**$1**');
  result = result.replace(/\b(\d{1,2}\.\d{1,2}\.\d{4})\b/g, '**$1**');
  result = result.replace(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\b/gi, '**$1 $2 $3 $4**');
  result = result.replace(/\b(CHF\s*[\d,.']+)\b/gi, '**$1**');
  result = result.replace(/\b(\d+)\s+(guests?|participants?|people|persons?)\b/gi, '**$1 $2**');
  return result;
}

function renderMessageContent(content: string): React.ReactNode {
  const highlightedContent = highlightImportantValues(content);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={{
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 underline hover:text-blue-800"
          >
            {children}
          </a>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-blue-700">{children}</strong>
        ),
        em: ({ children }) => (
          <em className="italic">{children}</em>
        ),
        p: ({ children }) => (
          <p className="mb-2 last:mb-0">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>
        ),
        li: ({ children }) => (
          <li className="ml-2">{children}</li>
        ),
        h1: ({ children }) => (
          <h1 className="text-lg font-bold mb-2">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-base font-bold mb-2">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-sm font-bold mb-1">{children}</h3>
        ),
        hr: () => (
          <hr className="my-3 border-gray-300" />
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full border-collapse border border-gray-300 text-sm">
              {children}
            </table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-blue-50">{children}</thead>
        ),
        tbody: ({ children }) => (
          <tbody className="divide-y divide-gray-200">{children}</tbody>
        ),
        tr: ({ children }) => (
          <tr className="hover:bg-gray-50">{children}</tr>
        ),
        th: ({ children }) => (
          <th className="border border-gray-300 px-3 py-2 text-left font-semibold text-gray-700 bg-blue-100">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border border-gray-300 px-3 py-2 text-gray-800">
            {children}
          </td>
        ),
      }}
    >
      {highlightedContent}
    </ReactMarkdown>
  );
}

export default function ChatPage() {
  const isMountedRef = useRef(true);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const [searchParams] = useSearchParams();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workflowType, setWorkflowType] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draftInput, setDraftInput] = useState('');
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [eventInfo, setEventInfo] = useState<EventInfo | null>(null);
  const [tasks, setTasks] = useState<PendingTask[]>([]);
  const [taskActionId, setTaskActionId] = useState<string | null>(null);
  const [taskNotes, setTaskNotes] = useState<Record<string, string>>({});
  const [taskEditedMessages, setTaskEditedMessages] = useState<Record<string, string>>({});
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [resetClientLoading, setResetClientLoading] = useState(false);
  const [clientEmail, setClientEmail] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(false);
  const [isUserNearBottom, setIsUserNearBottom] = useState(true);
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [debugEnabled, setDebugEnabled] = useState(false);
  const [depositPayingFor, setDepositPayingFor] = useState<string | null>(null);
  const [hilToggleEnabled, setHilToggleEnabled] = useState<boolean | null>(null);
  const [sessionDepositInfo, setSessionDepositInfo] = useState<WorkflowDepositInfo | null>(null);

  const inputDebounce = useMemo(() => debounce((value: string) => setInputText(value), 80), []);

  useEffect(() => {
    const param = searchParams.get('debug');
    if (param && ['1', 'true'].includes(param.toLowerCase())) {
      try {
        localStorage.setItem('debug', '1');
      } catch {
        // no-op
      }
      setDebugEnabled(true);
      return;
    }
    if (param && ['0', 'false'].includes(param.toLowerCase())) {
      try {
        localStorage.removeItem('debug');
      } catch {
        // no-op
      }
      setDebugEnabled(false);
      return;
    }
    try {
      const stored = localStorage.getItem('debug');
      setDebugEnabled(stored === '1');
    } catch {
      setDebugEnabled(false);
    }
  }, [searchParams]);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    try {
      localStorage.setItem('lastThreadId', sessionId);
      window.dispatchEvent(
        new StorageEvent('storage', { key: 'lastThreadId', newValue: sessionId })
      );
    } catch {
      // ignore storage issues
    }
  }, [sessionId]);

  const appendMessage = useCallback((message: Omit<Message, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setMessages((prev) => [...prev, { ...message, id }]);
    return id;
  }, []);

  const updateMessageAt = useCallback((messageId: string, updater: (msg: Message) => Message) => {
    setMessages((prev) => {
      const index = prev.findIndex((msg) => msg.id === messageId);
      if (index === -1) {
        return prev;
      }
      const updated = updater(prev[index]);
      if (updated === prev[index]) {
        return prev;
      }
      const next = [...prev];
      next[index] = updated;
      return next;
    });
  }, []);

  const stopStreaming = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const streamMessageContent = useCallback(
    (messageId: string, fullText: string) =>
      new Promise<void>((resolve) => {
        stopStreaming();
        if (!fullText) {
          updateMessageAt(messageId, (msg) => ({ ...msg, content: '', streaming: false }));
          resolve();
          return;
        }
        const chunkSize = Math.max(2, Math.ceil(fullText.length / 40));
        let cursor = 0;
        const step = () => {
          cursor = Math.min(fullText.length, cursor + chunkSize);
          const nextSlice = fullText.slice(0, cursor);
          updateMessageAt(messageId, (msg) => ({ ...msg, content: nextSlice, streaming: cursor < fullText.length }));
          if (cursor < fullText.length) {
            rafRef.current = requestAnimationFrame(step);
          } else {
            rafRef.current = null;
            resolve();
          }
        };
        rafRef.current = requestAnimationFrame(step);
      }),
    [stopStreaming, updateMessageAt]
  );

  const removeMessage = useCallback((messageId: string) => {
    setMessages((prev) => prev.filter((msg) => msg.id !== messageId));
  }, []);

  const handleAssistantReply = useCallback(
    async (messageId: string, reply: WorkflowReply) => {
      const responseText = reply.response || '';

      if (!responseText.trim()) {
        removeMessage(messageId);
      } else {
        await streamMessageContent(messageId, responseText);
        updateMessageAt(messageId, (msg) => ({
          ...msg,
          streaming: false,
          timestamp: new Date(),
          meta: buildMeta(reply.pending_actions) ?? msg.meta,
        }));
      }

      if (reply.workflow_type) {
        setWorkflowType(reply.workflow_type);
      }
      if (reply.session_id !== undefined) {
        setSessionId(reply.session_id ?? null);
      }
      if (reply.event_info !== undefined) {
        setEventInfo(reply.event_info ?? null);
      }
      if (reply.deposit_info) {
        setSessionDepositInfo({
          deposit_required: reply.deposit_info.deposit_required,
          deposit_amount: reply.deposit_info.deposit_amount ?? null,
          deposit_due_date: reply.deposit_info.deposit_due_date ?? null,
          deposit_paid: reply.deposit_info.deposit_paid,
          event_id: (reply.deposit_info as Record<string, unknown>).event_id as string ?? null,
        });
      }
      setIsComplete(reply.is_complete);
    },
    [streamMessageContent, updateMessageAt, removeMessage]
  );

  const refreshTasks = useCallback(async () => {
    try {
      const data = await requestJSON<{ tasks: PendingTask[] }>(`${API_BASE}/tasks/pending`);
      if (!isMountedRef.current) {
        return;
      }
      setTasks(Array.isArray(data.tasks) ? data.tasks : []);
    } catch (error) {
      if (isMountedRef.current) {
        console.warn('Tasks polling failed (backend offline?):', error);
      }
    }
  }, []);

  const clearResolvedTasks = useCallback(async () => {
    setCleanupLoading(true);
    try {
      await requestJSON(`${API_BASE}/tasks/cleanup`, {
        method: 'POST',
        body: JSON.stringify({ keep_thread_id: sessionId ?? null }),
      });
      await refreshTasks();
    } catch (error) {
      console.error('Error clearing tasks:', error);
      alert('Error clearing tasks. Please try again.');
    } finally {
      setCleanupLoading(false);
    }
  }, [refreshTasks, sessionId]);

  const resetClientData = useCallback(async () => {
    if (!clientEmail) {
      alert('No client email set. Start a conversation first.');
      return;
    }
    const confirmed = window.confirm(
      `Reset data for "${clientEmail}"?\n\nThis will delete:\n- This client's profile\n- This client's events\n- This client's tasks\n\nOther clients are not affected. This cannot be undone.`
    );
    if (!confirmed) return;

    setResetClientLoading(true);
    try {
      const result = await requestJSON<{
        email: string;
        client_deleted: boolean;
        events_deleted: number;
        tasks_deleted: number;
      }>(`${API_BASE}/client/reset`, {
        method: 'POST',
        body: JSON.stringify({ email: clientEmail }),
      });
      setSessionId(null);
      setMessages([]);
      setEventInfo(null);
      setHasStarted(false);
      setDraftInput('');
      setClientEmail(null);
      await refreshTasks();
      alert(
        `Client reset complete:\n- Events deleted: ${result.events_deleted}\n- Tasks deleted: ${result.tasks_deleted}`
      );
    } catch (error) {
      console.error('Error resetting client:', error);
      alert('Error resetting client data. Please try again.');
    } finally {
      setResetClientLoading(false);
    }
  }, [clientEmail, refreshTasks]);

  const fetchHilStatus = useCallback(async () => {
    try {
      const data = await requestJSON<{ hil_all_replies_enabled: boolean }>(`${API_BASE}/workflow/hil-status`);
      setHilToggleEnabled(data.hil_all_replies_enabled);
    } catch (err) {
      console.warn('Failed to fetch HIL status:', err);
      setHilToggleEnabled(false);
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    let cancelled = false;
    const checkHealth = async () => {
      try {
        await requestJSON(`${API_BASE}/workflow/health`);
        if (!cancelled) {
          setBackendHealthy(true);
          setBackendError(null);
        }
      } catch {
        if (!cancelled) {
          setBackendHealthy(false);
          setBackendError(
            `Cannot reach backend at ${API_BASE}. Make sure the backend is running.`
          );
        }
      }
    };
    checkHealth().then(() => {
      if (backendHealthy !== false) {
        refreshTasks().catch(() => undefined);
        fetchHilStatus().catch(() => undefined);
      }
    });
    const healthInterval = window.setInterval(() => {
      checkHealth().catch(() => undefined);
    }, 15000);
    const tasksInterval = window.setInterval(() => {
      if (backendHealthy) {
        refreshTasks().catch(() => undefined);
      }
    }, 5000);
    return () => {
      isMountedRef.current = false;
      stopStreaming();
      cancelled = true;
      window.clearInterval(healthInterval);
      window.clearInterval(tasksInterval);
    };
  }, [refreshTasks, stopStreaming, backendHealthy, fetchHilStatus]);

  useEffect(() => {
    if (!isUserNearBottom) {
      return;
    }
    const container = threadRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, isUserNearBottom]);

  const handleInputChange = useCallback(
    (value: string) => {
      setDraftInput(value);
      inputDebounce(value);
    },
    [inputDebounce]
  );

  const handleThreadScroll = useMemo(
    () =>
      debounce((element: HTMLDivElement) => {
        const { scrollTop, scrollHeight, clientHeight } = element;
        const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
        setIsUserNearBottom(distanceFromBottom < 32);
      }, 120),
    []
  );

  const startConversation = useCallback(async () => {
    const trimmed = draftInput.trim();
    if (!trimmed) {
      return;
    }
    setIsLoading(true);
    const email = extractEmail(trimmed);
    setClientEmail(email);
    setMessages(() => []);
    appendMessage({
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
    });
    setHasStarted(true);
    setIsComplete(false);
    setEventInfo(null);

    const assistantId = appendMessage({
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      streaming: true,
    });

    try {
      const reply = await fetchWorkflowReply(`${API_BASE}/start-conversation`, {
        email_body: trimmed,
        client_email: email,
      });
      await handleAssistantReply(assistantId, reply);
      if (reply.session_id) {
        setSessionId(reply.session_id);
      }
      refreshTasks().catch(() => undefined);
    } catch (error) {
      console.error('Error starting conversation:', error);
      updateMessageAt(assistantId, (msg) => ({
        ...msg,
        streaming: false,
        content: `Error connecting to backend at ${BACKEND_BASE}. Make sure the backend is running.`,
      }));
    } finally {
      setDraftInput('');
      setInputText('');
      setIsLoading(false);
    }
  }, [appendMessage, draftInput, handleAssistantReply, refreshTasks, updateMessageAt]);

  const sendMessage = useCallback(async () => {
    const trimmed = draftInput.trim();
    if (!trimmed || !sessionId) {
      return;
    }
    setIsLoading(true);
    const userMessage: Omit<Message, 'id'> = {
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
    };
    appendMessage(userMessage);

    const assistantId = appendMessage({
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      streaming: true,
    });

    setDraftInput('');
    setInputText('');

    try {
      const reply = await fetchWorkflowReply(`${API_BASE}/send-message`, {
        session_id: sessionId,
        message: trimmed,
      });
      await handleAssistantReply(assistantId, reply);
      refreshTasks().catch(() => undefined);
    } catch (error) {
      console.error('Error sending message:', error);
      updateMessageAt(assistantId, (msg) => ({
        ...msg,
        streaming: false,
        content: 'Error sending message. Please try again.',
      }));
    } finally {
      setIsLoading(false);
    }
  }, [appendMessage, draftInput, handleAssistantReply, refreshTasks, sessionId, updateMessageAt]);

  const handleTaskAction = useCallback(
    async (task: PendingTask, decision: 'approve' | 'reject') => {
      if (!task.task_id) {
        return;
      }
      setTaskActionId(task.task_id);
      try {
        const isAiReplyApproval = task.type === 'ai_reply_approval';
        const editedMessage = isAiReplyApproval ? taskEditedMessages[task.task_id] : undefined;

        const response = await fetch(`${API_BASE}/tasks/${task.task_id}/${decision}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({
            notes: taskNotes[task.task_id] || undefined,
            edited_message: editedMessage || undefined,
          }),
        });

        if (response.status === 404) {
          console.warn(`Task ${task.task_id} no longer pending; removing from list.`);
          await refreshTasks();
          return;
        }

        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Request failed with status ${response.status}`);
        }

        if (response.status !== 204) {
          const result = (await response.json()) as {
            task_status?: string;
            review_state?: string;
            thread_id?: string | null;
            assistant_reply?: string;
          };
          if (sessionId && result?.thread_id === sessionId && result.assistant_reply) {
            appendMessage({ role: 'assistant', content: result.assistant_reply, timestamp: new Date() });
          }
        }
        await refreshTasks();
      } catch (error) {
        console.error(`Error updating task (${decision}):`, error);
        alert('Error updating task. Please try again.');
      } finally {
        setTaskActionId(null);
      }
    },
    [appendMessage, refreshTasks, sessionId, taskNotes, taskEditedMessages]
  );

  const handleConfirmDate = useCallback(
    async (date: string, messageId: string) => {
      if (!sessionId || !date) {
        return;
      }
      setIsLoading(true);
      try {
        const reply = await fetchWorkflowReply(`${API_BASE}/conversation/${sessionId}/confirm-date`, {
          date,
        });
        updateMessageAt(messageId, (msg) => {
          if (!msg.meta?.confirmDate) {
            return msg;
          }
          const nextMeta = { ...msg.meta };
          delete nextMeta.confirmDate;
          return { ...msg, meta: Object.keys(nextMeta).length ? nextMeta : undefined };
        });
        const assistantId = appendMessage({
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          streaming: true,
        });
        await handleAssistantReply(assistantId, reply);
      } catch (error) {
        console.error('Error confirming date:', error);
        alert('Error confirming date. Please try again.');
      } finally {
        setIsLoading(false);
      }
    },
    [appendMessage, handleAssistantReply, sessionId, updateMessageAt]
  );

  const handleChangeDate = useCallback(
    (messageId: string) => {
      appendMessage({
        role: 'assistant',
        content: 'No problem - please share another date that works for you.',
        timestamp: new Date(),
      });
      updateMessageAt(messageId, (msg) => {
        if (!msg.meta?.confirmDate) {
          return msg;
        }
        const nextMeta = { ...msg.meta };
        delete nextMeta.confirmDate;
        return { ...msg, meta: Object.keys(nextMeta).length ? nextMeta : undefined };
      });
    },
    [appendMessage, updateMessageAt]
  );

  const acceptBooking = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    try {
      const response = await requestJSON<{ filename: string }>(`${API_BASE}/accept-booking/${sessionId}`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      alert(`Booking accepted! Saved to: ${response.filename}`);
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
    } catch (error) {
      console.error('Error accepting booking:', error);
      alert('Error accepting booking');
    }
  }, [sessionId]);

  const rejectBooking = useCallback(async () => {
    if (!sessionId) {
      return;
    }
    try {
      await requestJSON(`${API_BASE}/reject-booking/${sessionId}`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      alert('Booking rejected');
      setSessionId(null);
      setMessages([]);
      setIsComplete(false);
      setEventInfo(null);
      setHasStarted(false);
    } catch (error) {
      console.error('Error rejecting booking:', error);
      alert('Error rejecting booking');
    }
  }, [sessionId]);

  const handlePayDeposit = useCallback(
    async (eventId: string, depositAmount: number) => {
      setDepositPayingFor(eventId);
      try {
        await requestJSON(`${API_BASE}/event/deposit/pay`, {
          method: 'POST',
          body: JSON.stringify({ event_id: eventId }),
        });
        await refreshTasks();
        setSessionDepositInfo((prev) => prev ? { ...prev, deposit_paid: true } : null);
        alert(
          `Deposit of CHF ${depositAmount.toLocaleString('de-CH', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })} marked as paid. You can now proceed with the confirmation.`
        );
      } catch (error) {
        console.error('Error paying deposit:', error);
        alert('Error processing deposit payment. Please try again.');
      } finally {
        setDepositPayingFor(null);
      }
    },
    [refreshTasks]
  );

  const handleKeyPress = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!hasStarted) {
          startConversation().catch(() => undefined);
        } else {
          sendMessage().catch(() => undefined);
        }
      }
    },
    [hasStarted, sendMessage, startConversation]
  );

  const visibleMessages = useMemo(() => {
    const sliceStart = Math.max(0, messages.length - 60);
    return messages.slice(sliceStart);
  }, [messages]);

  const assistantTyping = useMemo(() => isLoading || messages.some((msg) => msg.streaming), [isLoading, messages]);

  const filteredEventInfo = useMemo(() => {
    if (!eventInfo || !isComplete) {
      return [] as Array<[string, string]>;
    }
    return Object.entries(eventInfo).filter(([key, value]) => shouldDisplayEventField(key, value));
  }, [eventInfo, isComplete]);

  const unpaidDepositInfo = useMemo(() => {
    for (const task of tasks) {
      const eventSummary = task.payload?.event_summary;
      const depositInfo = eventSummary?.deposit_info;
      const currentStep = eventSummary?.current_step ?? 1;
      if (currentStep >= 4 && depositInfo?.deposit_required && !depositInfo.deposit_paid) {
        return {
          amount: depositInfo.deposit_amount ?? 0,
          dueDate: depositInfo.deposit_due_date,
          eventId: task.event_id,
        };
      }
    }
    if (sessionDepositInfo?.deposit_required && !sessionDepositInfo.deposit_paid) {
      return {
        amount: sessionDepositInfo.deposit_amount ?? 0,
        dueDate: sessionDepositInfo.deposit_due_date,
        eventId: sessionDepositInfo.event_id,
      };
    }
    return null;
  }, [tasks, sessionDepositInfo]);

  const canConfirmBooking = !unpaidDepositInfo;

  const sessionTasks = useMemo(() => {
    if (!sessionId) return [];
    return tasks.filter((task) => task.payload?.thread_id === sessionId);
  }, [tasks, sessionId]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#bcdfff] via-[#dff0ff] to-[#f7fbff] p-4">
      {/* Header */}
      <div className="mx-auto max-w-[1800px] mb-4">
        <div className="rounded-2xl shadow-xl p-4 border border-[#c4dafc] bg-[#edf4ff]">
          <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-3">
            OpenEvent - AI Event Manager
          </h1>
          <p className="text-gray-600 mt-1 text-sm">
            {!hasStarted
              ? 'Paste a client email below to start the conversation'
              : 'Conversation in progress with Shami, Event Manager'}
          </p>
          {workflowType && (
            <span className="mt-2 inline-block px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
              Workflow: {workflowType}
            </span>
          )}
        </div>
        {backendHealthy === false && (
          <div className="mt-2 p-3 bg-red-50 border border-red-300 text-red-700 rounded">
            Backend unreachable: {backendError || `Failed to fetch ${API_BASE}`}
          </div>
        )}
      </div>

      {/* Two-Column Layout */}
      <div className="mx-auto max-w-[1800px] flex gap-6">
        {/* LEFT COLUMN: Client Chat */}
        <div className="flex-1 min-w-0">
          <div className="bg-gradient-to-b from-[#d2e7ff] to-[#99c2ff] rounded-t-2xl p-3">
            <h2 className="text-white font-bold text-lg flex items-center gap-2">
              Client Chat
            </h2>
            <p className="text-blue-100 text-xs">Messages between client and AI assistant</p>
          </div>
          <div
            ref={threadRef}
            className="bg-[#e9f2ff] shadow-xl border border-[#c4dafc]"
            style={{ height: '500px', overflowY: 'auto' }}
            onScroll={(event) => handleThreadScroll(event.currentTarget)}
          >
            <div className="p-4 space-y-4">
              {visibleMessages.length === 0 && (
                <div className="text-center py-16 text-gray-400">
                  <p className="text-lg">No messages yet...</p>
                  <p className="text-sm mt-2">Start by pasting a client inquiry email below</p>
                </div>
              )}

              {visibleMessages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                    <div
                      className={`text-xs font-semibold mb-1 ${
                        msg.role === 'user' ? 'text-right text-blue-600' : 'text-left text-gray-600'
                      }`}
                    >
                      {msg.role === 'user' ? 'Client' : 'Shami'}
                    </div>
                    <div
                      className={`rounded-2xl px-4 py-3 shadow-sm ${
                        msg.role === 'user'
                          ? 'bg-blue-500 text-white'
                          : 'bg-[#eaf1ff] text-gray-800 border border-[#cddfff]'
                      } ${msg.streaming ? 'animate-pulse' : ''}`}
                    >
                      <div className="text-sm leading-relaxed">{renderMessageContent(msg.content)}</div>
                      {msg.role === 'assistant' && msg.meta?.confirmDate && (
                        <div className="flex gap-2 mt-3">
                          <button
                            onClick={() => handleConfirmDate(msg.meta?.confirmDate ?? '', msg.id)}
                            disabled={isLoading || !sessionId}
                            className="px-3 py-1 text-xs font-semibold rounded bg-green-600 text-white disabled:bg-gray-300"
                          >
                            Confirm date
                          </button>
                          <button
                            onClick={() => handleChangeDate(msg.id)}
                            disabled={isLoading}
                            className="px-3 py-1 text-xs font-semibold rounded border border-gray-400 text-gray-700 hover:bg-gray-200"
                          >
                            Change date
                          </button>
                        </div>
                      )}
                      <div className={`${msg.role === 'user' ? 'text-blue-100' : 'text-gray-500'} text-xs mt-2`}>
                        {msg.timestamp.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {assistantTyping && (
                <div className="flex justify-start">
                  <div className="bg-[#eaf1ff] rounded-2xl px-4 py-3 border border-[#cddfff]">
                    <div className="flex items-center gap-2 text-gray-600">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span className="text-sm">Shami is typing...</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Deposit Payment Section */}
          {unpaidDepositInfo && !isComplete && (
            <div className="bg-gradient-to-r from-yellow-50 to-orange-50 p-4 border-x border-gray-200">
              <div className="text-center">
                <p className="font-semibold text-yellow-800 mb-2">
                  Deposit Required: CHF {unpaidDepositInfo.amount.toLocaleString('de-CH', { minimumFractionDigits: 2 })}
                </p>
                <p className="text-sm text-yellow-700 mb-3">
                  Pay the deposit to confirm your booking
                </p>
                {unpaidDepositInfo.eventId && (
                  <button
                    onClick={() => handlePayDeposit(unpaidDepositInfo.eventId!, unpaidDepositInfo.amount)}
                    disabled={depositPayingFor === unpaidDepositInfo.eventId}
                    className="px-6 py-2 bg-yellow-600 text-white rounded-xl font-semibold hover:bg-yellow-700 disabled:opacity-50 transition shadow-md"
                  >
                    {depositPayingFor === unpaidDepositInfo.eventId ? 'Processing...' : 'Pay Deposit'}
                  </button>
                )}
              </div>
            </div>
          )}

          {isComplete && (
            <div className="bg-gradient-to-r from-green-50 to-blue-50 p-4 border border-[#c4dafc]">
              <div className="text-center mb-3">
                <p className="font-semibold text-gray-800">Ready to finalize your booking!</p>
              </div>
              <div className="flex gap-3 justify-center">
                <button
                  onClick={acceptBooking}
                  disabled={isLoading || !canConfirmBooking}
                  className={`flex items-center gap-2 px-6 py-2 ${
                    canConfirmBooking ? 'bg-green-500 hover:bg-green-600' : 'bg-gray-300'
                  } text-white rounded-xl font-bold shadow-lg`}
                >
                  <CheckCircle className="w-5 h-5" />
                  Accept
                </button>
                <button
                  onClick={rejectBooking}
                  disabled={isLoading}
                  className="flex items-center gap-2 px-6 py-2 bg-red-500 hover:bg-red-600 text-white rounded-xl font-bold shadow-lg"
                >
                  <XCircle className="w-5 h-5" />
                  Reject
                </button>
              </div>
            </div>
          )}

          <div className="bg-[#e8f1ff] rounded-b-2xl shadow-lg p-4 border border-[#c4dafc]">
            <div className="flex gap-3">
              <textarea
                value={draftInput}
                onChange={(e) => handleInputChange(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder={!hasStarted ? "Paste the client's email here to start..." : 'Type your response as the client...'}
                className="flex-1 resize-none border border-[#89aef5] rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-[#3f78e0] text-sm bg-[#c3d5ff] text-gray-900"
                rows={3}
                disabled={isLoading || isComplete}
              />
              <button
                onClick={!hasStarted ? () => startConversation().catch(() => undefined) : () => sendMessage().catch(() => undefined)}
                disabled={isLoading || isComplete || !draftInput.trim()}
                className="px-6 py-3 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-300 text-white rounded-xl font-semibold shadow-md flex items-center gap-2"
              >
                {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                Send
              </button>
            </div>
            <div className="text-xs text-gray-500 mt-2">Press Enter to send - Shift+Enter for new line</div>
          </div>

          {filteredEventInfo.length > 0 && (
            <div className="mt-4 bg-[#f2f6ff] rounded-2xl shadow-lg p-4 border border-[#d3e4ff]">
              <h3 className="font-bold text-gray-800 mb-3">Information Collected</h3>
              <div className="grid grid-cols-2 gap-2 text-sm">
                {filteredEventInfo.map(([key, value]) => (
                  <div key={key} className="flex flex-col">
                    <span className="text-gray-500 text-xs uppercase">{key.replace(/_/g, ' ')}</span>
                    <span className="font-semibold text-gray-800">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Manager Section */}
        {hilToggleEnabled && (
          <div className="w-[500px] flex-shrink-0">
            <div className="bg-gradient-to-b from-[#7fc2ff] to-[#4d8ef5] rounded-t-2xl p-3">
              <h2 className="text-white font-bold text-lg flex items-center gap-2">
                Manager - AI Reply Approval
                {hilToggleEnabled && <span className="px-2 py-0.5 bg-green-500 rounded text-xs">ON</span>}
              </h2>
              <p className="text-green-100 text-xs">Review and approve AI responses before they reach clients</p>
            </div>
            <div
              className="bg-[#f9fbff] shadow-xl border border-[#c4dafc] rounded-b-2xl"
              style={{ minHeight: '400px', maxHeight: '500px', overflowY: 'auto' }}
            >
              <div className="p-4 space-y-4">
                {sessionTasks.length === 0 ? (
                  <div className="text-center py-16 text-gray-400">
                    <div className="text-4xl mb-3">No pending approvals</div>
                    <p className="text-sm mt-2">
                      {!sessionId
                        ? 'Start a conversation to see AI reply approvals here'
                        : 'AI-generated replies will appear here for your approval'}
                    </p>
                  </div>
                ) : (
                  sessionTasks.map((task) => {
                    const draftBody = task.payload?.draft_body ? task.payload.draft_body.trim() : '';
                    const eventSummary = task.payload?.event_summary;
                    const isAiReplyApproval = task.type === 'ai_reply_approval';
                    const canAction = ['ask_for_date', 'manual_review', 'offer_message', 'room_availability_message', 'date_confirmation_message', 'ai_reply_approval'].includes(task.type);

                    return (
                      <div key={task.task_id} className="p-4 bg-[#f3f7ff] border-2 border-[#c9dcff] rounded-xl">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-bold text-[#2b5ea8] uppercase">{task.type.replace(/_/g, ' ')}</span>
                          <span className="text-xs text-[#4874c0]">Step {task.payload?.step_id || '?'}</span>
                        </div>
                        {eventSummary && (
                          <div className="text-xs text-gray-600 mb-3 space-y-1">
                            {eventSummary.client_name && <div>Contact: {eventSummary.client_name}</div>}
                            {eventSummary.email && <div>Email: {eventSummary.email}</div>}
                            {eventSummary.chosen_date && <div>Date: {eventSummary.chosen_date}</div>}
                            <div className={eventSummary.billing_address ? '' : 'text-orange-600 font-medium'}>
                              Billing: {eventSummary.billing_address || 'Please provide before confirming'}
                            </div>
                          </div>
                        )}

                        {isAiReplyApproval && draftBody && (
                          <div className="mt-2">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs font-semibold text-green-800">AI-Generated Message:</span>
                              <span className="text-xs text-green-600">Edit before approving</span>
                            </div>
                            <textarea
                              value={taskEditedMessages[task.task_id] ?? draftBody}
                              onChange={(e) =>
                                setTaskEditedMessages((prev) => ({
                                  ...prev,
                                  [task.task_id!]: e.target.value,
                                }))
                              }
                              className="w-full text-sm p-3 border-2 border-green-300 rounded-lg bg-white font-mono"
                              rows={Math.min(10, Math.max(4, draftBody.split('\n').length + 1))}
                            />
                            {taskEditedMessages[task.task_id] && taskEditedMessages[task.task_id] !== draftBody && (
                              <div className="mt-1 text-xs text-orange-600 font-semibold">Modified from original</div>
                            )}
                          </div>
                        )}

                        {!isAiReplyApproval && draftBody && (
                          <details className="mt-2">
                            <summary className="text-xs text-gray-700 cursor-pointer">View details</summary>
                            <pre className="mt-1 text-xs bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap max-h-32 overflow-auto">
                              {draftBody}
                            </pre>
                          </details>
                        )}

                        {canAction && (
                          <div className="mt-4">
                            <textarea
                              value={taskNotes[task.task_id] || ''}
                              onChange={(e) =>
                                setTaskNotes((prev) => ({ ...prev, [task.task_id!]: e.target.value }))
                              }
                              placeholder="Optional manager notes..."
                              className="w-full text-xs p-2 border border-[#c4dafc] rounded-md mb-3 bg-white"
                              rows={2}
                            />
                            <div className="flex gap-3">
                              <button
                                onClick={() => handleTaskAction(task, 'approve')}
                                disabled={taskActionId === task.task_id}
                                className="flex-1 px-4 py-2 text-sm font-bold rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:bg-gray-300"
                              >
                                {taskActionId === task.task_id ? 'Sending...' : 'Approve & Send'}
                              </button>
                              <button
                                onClick={() => handleTaskAction(task, 'reject')}
                                disabled={taskActionId === task.task_id}
                                className="px-4 py-2 text-sm font-bold rounded-lg border-2 border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50"
                              >
                                Discard
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Debug Info */}
      {debugEnabled && (
        <div className="mx-auto max-w-[1800px] mt-4 p-4 bg-yellow-50 border-2 border-yellow-400 rounded-lg">
          <h3 className="font-bold text-lg mb-2">DEBUG INFO</h3>
          <div className="grid grid-cols-2 gap-2 text-sm font-mono">
            <div>sessionId: <span className="font-bold">{sessionId || 'null'}</span></div>
            <div>isComplete: <span className="font-bold text-red-600">{isComplete ? 'TRUE' : 'FALSE'}</span></div>
            <div>isLoading: <span className="font-bold">{isLoading ? 'TRUE' : 'FALSE'}</span></div>
            <div>hasStarted: <span className="font-bold">{hasStarted ? 'TRUE' : 'FALSE'}</span></div>
            <div>workflowType: <span className="font-bold">{workflowType || 'null'}</span></div>
            <div>messages: <span className="font-bold">{messages.length}</span></div>
            <div>debouncedInputLength: <span className="font-bold">{inputText.trim().length}</span></div>
          </div>
        </div>
      )}

      {/* Manager Settings Section */}
      <div className="mx-auto max-w-[1800px] mt-4 flex gap-4">
        <div className="flex-1">
          <DepositSettings compact />
        </div>
        <div className="flex gap-2 items-start">
          <button
            onClick={() => clearResolvedTasks().catch(() => undefined)}
            disabled={cleanupLoading || tasks.length === 0}
            className="px-3 py-2 text-xs font-semibold rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition"
          >
            {cleanupLoading ? 'Clearing...' : 'Clear Tasks'}
          </button>
          <button
            onClick={() => resetClientData().catch(() => undefined)}
            disabled={resetClientLoading || !clientEmail}
            className="px-3 py-2 text-xs font-semibold rounded-lg border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition"
            title={clientEmail ? `Reset data for ${clientEmail}` : 'Start a conversation first'}
          >
            {resetClientLoading ? 'Resetting...' : 'Reset Client'}
          </button>
        </div>
      </div>
    </div>
  );
}
