'use client';

import { Suspense } from 'react';
import { DebugLayout } from '../../components/debug/DebugHeader';
import PromptsEditor from '../../components/admin/PromptsEditor';

function ConfigIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 110-9h.75c.704 0 1.397-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.561.309 1.193.074 1.77-.236.576-.592.986-1.193 1.08-.73.113-1.45.19-2.16.19a4.5 4.5 0 01-4.5-4.5c0-.71.077-1.43.19-2.16.093-.601.502-.957 1.079-1.194a2.628 2.628 0 011.77.075c.891.4 1.821.732 2.783.985m-9.18 0c-.06-.688-.09-1.386-.09-2.09V7.5a4.5 4.5 0 119 0v.75c0 .704-.03 1.397-.09 2.09m9.18 0a3 3 0 01-.985 2.783 2.628 2.628 0 01-1.77.074c-.576-.236-.986-.592-1.08-1.193a41.905 41.905 0 01-.19-2.16 4.5 4.5 0 014.5-4.5c.71 0 1.43.077 2.16.19.601.093.957.502 1.194 1.079a2.628 2.628 0 01-.075 1.77c-.4.891-.732 1.821-.985 2.783m0 9.18c.688.06 1.386.09 2.09.09h.75a4.5 4.5 0 110 9h-.75c-.704 0-1.397.03-2.09.09m-9.18 0c-.253-.962-.584-1.892-.985-2.783-.247-.561-.309-1.193-.074-1.77.236-.576.592-.986 1.193-1.08.73-.113 1.45-.19 2.16-.19a4.5 4.5 0 014.5 4.5c0 .71-.077 1.43-.19 2.16-.093.601-.502.957-1.079 1.194a2.628 2.628 0 01-1.77-.075c-.891-.4-1.821-.732-2.783-.985" />
    </svg>
  );
}

function PromptsPageContent() {
  return (
    <DebugLayout
      title="Configuration"
      icon={<ConfigIcon />}
    >
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
        <PromptsEditor />
      </div>
    </DebugLayout>
  );
}

export default function PromptsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400">Loading editor...</div>
      </div>
    }>
      <PromptsPageContent />
    </Suspense>
  );
}
