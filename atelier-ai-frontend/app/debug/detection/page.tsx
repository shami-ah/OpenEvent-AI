'use client';

import { Suspense } from 'react';
import { useThreadId } from '../../components/debug/ThreadSelector';
import { DebugLayout } from '../../components/debug/DebugHeader';
import DetectionView from '../../components/debug/DetectionView';

// Detection icon
function DetectionIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function DetectionPageContent() {
  const threadId = useThreadId();

  return (
    <DebugLayout
      title="Detection View"
      icon={<DetectionIcon />}
    >
      <div className="flex flex-col gap-6">
        {/* Main content */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
          <DetectionView threadId={threadId} />
        </div>

        {/* Info card */}
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-5">
          <div className="flex items-start gap-4">
            <div className="p-2.5 rounded-xl bg-blue-500/20 text-blue-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
              </svg>
            </div>
            <div>
              <h3 className="font-semibold text-blue-400 mb-3 text-base">How to read this view</h3>
              <ul className="list-none m-0 p-0 flex flex-col gap-2.5">
                <li className="flex items-start gap-2.5 text-sm text-slate-300">
                  <span className="text-blue-400 mt-0.5">•</span>
                  <span><strong className="font-semibold text-slate-200">Click any row</strong> to expand and see full details</span>
                </li>
                <li className="flex items-start gap-2.5 text-sm text-slate-300">
                  <span className="text-blue-400 mt-0.5">•</span>
                  <span><strong className="font-semibold text-slate-200">Matched Patterns</strong> show which keywords/regex triggered the classification</span>
                </li>
                <li className="flex items-start gap-2.5 text-sm text-slate-300">
                  <span className="text-blue-400 mt-0.5">•</span>
                  <span><strong className="font-semibold text-slate-200">Alternatives</strong> show other classifications that were considered</span>
                </li>
                <li className="flex items-start gap-2.5 text-sm text-slate-300">
                  <span className="text-blue-400 mt-0.5">•</span>
                  <span><strong className="font-semibold text-slate-200">Confidence</strong> percentage indicates LLM certainty (when available)</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </DebugLayout>
  );
}

export default function DetectionPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950 text-slate-100 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading detection view...</span>
        </div>
      </div>
    }>
      <DetectionPageContent />
    </Suspense>
  );
}
