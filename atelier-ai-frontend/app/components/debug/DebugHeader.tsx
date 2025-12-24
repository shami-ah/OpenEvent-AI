'use client';

import Link from 'next/link';
import { ReactNode } from 'react';
import ThreadSelector, { useThreadId } from './ThreadSelector';

interface DebugHeaderProps {
  title: string;
  icon?: ReactNode;
  children?: ReactNode;
}

// Default bug icon
function BugIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 12.75c1.148 0 2.278.08 3.383.237 1.037.146 1.866.966 1.866 2.013 0 3.728-2.35 6.75-5.25 6.75S6.75 18.728 6.75 15c0-1.046.83-1.867 1.866-2.013A24.204 24.204 0 0112 12.75zm0 0c2.883 0 5.647.508 8.207 1.44a23.91 23.91 0 01-1.152 6.06M12 12.75c-2.883 0-5.647.508-8.208 1.44.125 2.104.52 4.136 1.153 6.06M12 12.75a2.25 2.25 0 002.248-2.354M12 12.75a2.25 2.25 0 01-2.248-2.354M12 8.25c.995 0 1.971-.08 2.922-.236.403-.066.74-.358.795-.762a3.778 3.778 0 00-.399-2.25M12 8.25c-.995 0-1.97-.08-2.922-.236-.402-.066-.74-.358-.795-.762a3.734 3.734 0 01.4-2.253M12 8.25a2.25 2.25 0 00-2.248 2.146M12 8.25a2.25 2.25 0 012.248 2.146M8.683 5a6.032 6.032 0 01-1.155-1.002c.07-.63.27-1.222.574-1.747m.581 2.749A3.75 3.75 0 0115.318 5m0 0c.427-.283.815-.62 1.155-.999a4.471 4.471 0 00-.575-1.752M4.921 6a24.048 24.048 0 00-.392 3.314c1.668.546 3.416.914 5.223 1.082M19.08 6c.205 1.08.337 2.187.392 3.314a23.882 23.882 0 01-5.223 1.082" />
    </svg>
  );
}

function BackArrowIcon() {
  return (
    <svg className="w-4.5 h-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

export default function DebugHeader({ title, icon, children }: DebugHeaderProps) {
  const threadId = useThreadId();

  return (
    <header className="mb-7">
      {/* Top bar with back button and thread selector */}
      <div className="flex flex-wrap gap-4 items-center justify-between mb-5">
        <Link
          href={threadId ? `/debug?thread=${encodeURIComponent(threadId)}` : '/debug'}
          className="inline-flex items-center gap-2.5 text-sm text-slate-400 hover:text-slate-200 transition-colors no-underline"
        >
          <span className="p-2 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
            <BackArrowIcon />
          </span>
          <span>Back to Dashboard</span>
        </Link>
        <ThreadSelector />
      </div>

      {/* Title section */}
      <div className="flex items-center gap-4">
        <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-slate-700/50 to-slate-800/50 border border-slate-700/50 text-slate-400">
          {icon || <BugIcon />}
        </div>
        <div className="flex-1">
          <h1 className="text-3xl font-bold text-slate-100 m-0 tracking-tight">{title}</h1>
        </div>
        {children}
      </div>
    </header>
  );
}

// Layout wrapper for debug subpages
interface DebugLayoutProps {
  title: string;
  icon?: ReactNode;
  headerContent?: ReactNode;
  children: ReactNode;
}

export function DebugLayout({ title, icon, headerContent, children }: DebugLayoutProps) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 font-sans">
      <div className="relative max-w-7xl mx-auto px-6 py-8">
        <DebugHeader title={title} icon={icon}>
          {headerContent}
        </DebugHeader>
        <main>{children}</main>
      </div>
    </div>
  );
}
