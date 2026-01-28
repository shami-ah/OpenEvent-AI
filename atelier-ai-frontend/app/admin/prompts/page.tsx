'use client';

import { Suspense } from 'react';
import { DebugLayout } from '../../components/debug/DebugHeader';
import PromptsEditor from '../../components/admin/PromptsEditor';

const PROMPTS_EDITOR_ENABLED =
  (process.env.NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED || '').trim().toLowerCase() === 'true' ||
  (process.env.NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED || '').trim() === '1';

function ConfigIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  );
}

function PromptsPageContent() {
  return (
    <DebugLayout
      title="AI Message Customization"
      icon={<ConfigIcon />}
    >
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
        <PromptsEditor />
      </div>
    </DebugLayout>
  );
}

function DisabledPage() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center max-w-md mx-auto p-8">
        <div className="text-4xl mb-4">🔒</div>
        <h1 className="text-xl font-semibold text-slate-200 mb-2">Feature Not Enabled</h1>
        <p className="text-slate-400 text-sm mb-4">
          The AI message customization feature is not currently enabled.
        </p>
        <p className="text-slate-500 text-xs">
          Contact your administrator to enable <code className="bg-slate-800 px-1 rounded">NEXT_PUBLIC_PROMPTS_EDITOR_ENABLED</code>
        </p>
      </div>
    </div>
  );
}

export default function PromptsPage() {
  if (!PROMPTS_EDITOR_ENABLED) {
    return <DisabledPage />;
  }

  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400 animate-pulse">Loading editor...</div>
      </div>
    }>
      <PromptsPageContent />
    </Suspense>
  );
}
