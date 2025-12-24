'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

interface ThreadSelectorProps {
  onThreadChange?: (threadId: string | null) => void;
  className?: string;
}

function LinkIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}

export default function ThreadSelector({ onThreadChange, className = '' }: ThreadSelectorProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryThreadId = searchParams.get('thread') || '';
  const [threadId, setThreadId] = useState<string>(queryThreadId);
  const [manualId, setManualId] = useState<string>(queryThreadId);

  // Sync from query param or localStorage
  useEffect(() => {
    if (queryThreadId) {
      setThreadId(queryThreadId);
      setManualId(queryThreadId);
      onThreadChange?.(queryThreadId);
      return;
    }
    try {
      const stored = localStorage.getItem('lastThreadId');
      if (stored) {
        setThreadId(stored);
        setManualId(stored);
        onThreadChange?.(stored);
      }
    } catch {
      // ignore storage errors
    }
  }, [queryThreadId, onThreadChange]);

  // Poll for localStorage changes (cross-tab sync)
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === 'lastThreadId' && event.newValue) {
        setThreadId(event.newValue);
        setManualId(event.newValue);
        onThreadChange?.(event.newValue);
      }
    };
    window.addEventListener('storage', handleStorage);

    const interval = window.setInterval(() => {
      try {
        const stored = localStorage.getItem('lastThreadId');
        if (stored && stored !== threadId) {
          setThreadId(stored);
          setManualId(stored);
          onThreadChange?.(stored);
        }
      } catch {
        // ignore
      }
    }, 2000);

    return () => {
      window.removeEventListener('storage', handleStorage);
      window.clearInterval(interval);
    };
  }, [threadId, onThreadChange]);

  const handleAttach = useCallback(() => {
    setThreadId(manualId);
    onThreadChange?.(manualId || null);
    // Update URL with thread param
    if (manualId) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('thread', manualId);
      router.replace(`?${params.toString()}`);
    }
  }, [manualId, onThreadChange, router, searchParams]);

  return (
    <div className={`flex items-center gap-3.5 ${className}`}>
      <div className="flex items-center gap-2 text-slate-500">
        <LinkIcon />
        <span className="text-sm font-medium">Thread</span>
      </div>
      <div className="flex items-center">
        <input
          value={manualId}
          onChange={(event) => setManualId(event.target.value)}
          placeholder="Enter thread ID..."
          className="bg-slate-800/50 border border-slate-700 rounded-l-xl px-4 py-2.5 text-sm text-slate-100 min-w-[200px] outline-none focus:border-purple-500/50 focus:bg-slate-800 transition-all placeholder:text-slate-600"
        />
        <button
          type="button"
          onClick={handleAttach}
          className="px-4 py-2.5 text-sm font-medium bg-purple-500/10 border border-purple-500/30 border-l-0 rounded-r-xl text-purple-400 hover:bg-purple-500/20 transition-all"
        >
          Attach
        </button>
      </div>
      {threadId && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400">
          <CheckIcon />
          <span className="text-xs font-medium">Connected</span>
        </div>
      )}
    </div>
  );
}

export function useThreadId(): string | null {
  const searchParams = useSearchParams();
  const queryThreadId = searchParams.get('thread') || '';
  const [threadId, setThreadId] = useState<string | null>(queryThreadId || null);

  useEffect(() => {
    if (queryThreadId) {
      setThreadId(queryThreadId);
      return;
    }
    try {
      const stored = localStorage.getItem('lastThreadId');
      if (stored) {
        setThreadId(stored);
      }
    } catch {
      // ignore
    }
  }, [queryThreadId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      try {
        const stored = localStorage.getItem('lastThreadId');
        if (stored && stored !== threadId) {
          setThreadId(stored);
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => window.clearInterval(interval);
  }, [threadId]);

  return threadId;
}
