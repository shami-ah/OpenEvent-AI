'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';

// Types
interface PromptConfig {
  system_prompt: string;
  step_prompts: Record<string, string>;
}

interface HistoryEntry {
  ts: string;
  config: PromptConfig;
}

// Step metadata with friendly descriptions and examples
const STEP_INFO: Record<string, {
  label: string;
  description: string;
  canChange: string[];
  example: string;
  icon: string;
}> = {
  'system': {
    label: 'Global Tone & Style',
    description: 'Controls the overall voice and personality used in all client messages.',
    canChange: [
      'Communication style (formal vs friendly)',
      'Greeting preferences',
      'Banned words or phrases',
      'Formatting preferences',
    ],
    example: `Use a warm but professional tone. Keep paragraphs short (2-3 sentences). Avoid overly enthusiastic language like "Amazing!" or "Fantastic!"`,
    icon: '🎨',
  },
  '2': {
    label: 'Date Confirmation',
    description: 'When asking clients to choose between available dates.',
    canChange: [
      'How you greet the client',
      'How date options are presented',
      'How you ask for their preference',
    ],
    example: `Keep it concise. Acknowledge the request in one line, then list dates as clear options. Ask directly which works best.`,
    icon: '📅',
  },
  '3': {
    label: 'Room Availability',
    description: 'When presenting room options to clients.',
    canChange: [
      'How you recommend a room',
      'How you compare alternatives',
      'How you ask for next steps',
    ],
    example: `Lead with a clear recommendation and explain why it fits. Compare 1-2 alternatives briefly. End with a direct question.`,
    icon: '🏠',
  },
  '4': {
    label: 'Offer / Quote',
    description: 'When presenting pricing and the offer summary.',
    canChange: [
      'How you introduce the offer',
      'How you summarize value (without changing numbers)',
      'How you ask for confirmation',
    ],
    example: `Open with a short intro, summarize the offer in plain language. End with "Ready to confirm, or would you like to adjust anything?"`,
    icon: '💰',
  },
  '5': {
    label: 'Negotiation',
    description: 'When the client accepts, declines, or asks for changes.',
    canChange: [
      'How you acknowledge their decision',
      'How you confirm next steps',
      'Tone for clarifications',
    ],
    example: `Acknowledge their decision in one sentence. Clearly state what happens next (manager review, deposit, etc.).`,
    icon: '🤝',
  },
  '7': {
    label: 'Confirmation',
    description: 'Final booking confirmation and admin details.',
    canChange: [
      'How you celebrate the booking',
      'How you request remaining details (billing, deposit)',
      'Overall confidence level',
    ],
    example: `Celebrate briefly but professionally. List remaining admin steps in a calm, checklist-style format.`,
    icon: '✅',
  },
};

// Simplified labels for sidebar
const STEP_LABELS: Record<string, string> = {
  '2': 'Date Confirmation',
  '3': 'Room Availability',
  '4': 'Offer',
  '5': 'Negotiation',
  '7': 'Confirmation',
};

// Warning thresholds
const MIN_CONTENT_LENGTH = 20;
const MAX_CONTENT_LENGTH = 5000;

export default function PromptsEditor() {
  const [config, setConfig] = useState<PromptConfig | null>(null);
  const [originalConfig, setOriginalConfig] = useState<PromptConfig | null>(null);
  const [activeTab, setActiveTab] = useState<'system' | string>('2'); // Start on Step 2, not system
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showHelp, setShowHelp] = useState(true);
  const [notification, setNotification] = useState<{ type: 'success' | 'error' | 'warning'; message: string } | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts`);
      if (!res.ok) throw new Error('Failed to load configuration');
      const data = await res.json();
      setConfig(data);
      setOriginalConfig(JSON.parse(JSON.stringify(data))); // Deep clone for reset
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Could not load prompts.' });
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts/history`);
      if (!res.ok) throw new Error('Failed to load history');
      const data = await res.json();
      setHistory(data.history);
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  useEffect(() => {
    if (showHistory) {
      fetchHistory();
    }
  }, [showHistory, fetchHistory]);

  // Check if current prompt has been modified from original
  const hasChanges = useMemo(() => {
    if (!config || !originalConfig) return false;
    if (activeTab === 'system') {
      return config.system_prompt !== originalConfig.system_prompt;
    }
    return config.step_prompts[activeTab] !== originalConfig.step_prompts[activeTab];
  }, [config, originalConfig, activeTab]);

  const handleSave = async () => {
    if (!config) return;

    // Validate before saving
    const currentValue = activeTab === 'system' ? config.system_prompt : config.step_prompts[activeTab];
    if (currentValue && currentValue.length < MIN_CONTENT_LENGTH) {
      setNotification({ type: 'warning', message: 'Content seems very short. Are you sure you want to save?' });
      // Continue anyway after warning
    }

    setSaving(true);
    setNotification(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (!res.ok) {
        const errText = await res.text();
        console.error('Save failed:', res.status, errText);
        throw new Error(`Failed to save: ${res.status} ${errText}`);
      }
      setNotification({ type: 'success', message: 'Changes saved! They will take effect within 30 seconds.' });
      setOriginalConfig(JSON.parse(JSON.stringify(config))); // Update original after save
      if (showHistory) fetchHistory();
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Failed to save. Please try again.' });
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = async (index: number) => {
    if (!confirm('Restore this previous version? Your current changes will be saved to history first.')) return;
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/prompts/revert/${index}`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to revert');
      await fetchConfig();
      await fetchHistory();
      setNotification({ type: 'success', message: 'Restored previous version.' });
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Failed to restore.' });
    }
  };

  const handleResetToDefault = () => {
    if (!originalConfig || !config) return;
    if (!confirm('Reset this prompt to its original value? Unsaved changes will be lost.')) return;

    if (activeTab === 'system') {
      setConfig({ ...config, system_prompt: originalConfig.system_prompt });
    } else {
      setConfig({
        ...config,
        step_prompts: {
          ...config.step_prompts,
          [activeTab]: originalConfig.step_prompts[activeTab],
        },
      });
    }
    setNotification({ type: 'success', message: 'Reset to original. Click Save to apply.' });
  };

  const handleTextChange = (val: string) => {
    if (!config) return;
    // Clear notification on edit
    if (notification?.type === 'warning') setNotification(null);

    if (activeTab === 'system') {
      setConfig({ ...config, system_prompt: val });
    } else {
      setConfig({
        ...config,
        step_prompts: {
          ...config.step_prompts,
          [activeTab]: val,
        },
      });
    }
  };

  const handleUseExample = () => {
    const info = STEP_INFO[activeTab];
    if (info?.example) {
      handleTextChange(info.example);
      setNotification({ type: 'success', message: 'Example loaded. Customize it, then click Save.' });
    }
  };

  if (!config) {
    return (
      <div className="p-8 text-center text-slate-500">
        <div className="animate-pulse">Loading configuration...</div>
      </div>
    );
  }

  const activeValue = activeTab === 'system' ? config.system_prompt : config.step_prompts[activeTab] || '';
  const stepInfo = STEP_INFO[activeTab] || STEP_INFO['system'];
  const charCount = activeValue.length;
  const isContentShort = charCount > 0 && charCount < MIN_CONTENT_LENGTH;
  const isContentLong = charCount > MAX_CONTENT_LENGTH;

  return (
    <div className="flex flex-col h-[calc(100vh-100px)] gap-4">
      {/* Header */}
      <div className="flex items-center justify-between bg-slate-800/50 p-4 rounded-xl border border-slate-700">
        <div>
          <h2 className="text-xl font-bold text-slate-100">AI Message Customization</h2>
          <p className="text-sm text-slate-400">Adjust how the AI writes to your clients</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowHelp(!showHelp)}
            className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
              showHelp
                ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
                : 'bg-transparent border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
            title="Toggle guidance panel"
          >
            {showHelp ? '💡 Hide Tips' : '💡 Show Tips'}
          </button>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
              showHistory
                ? 'bg-slate-700 border-slate-600 text-slate-200'
                : 'bg-transparent border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
          >
            📜 History
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className={`px-6 py-2 rounded-lg text-sm font-bold text-white transition-all ${
              saving
                ? 'bg-blue-600/50 cursor-wait'
                : 'bg-blue-600 hover:bg-blue-500 shadow-lg shadow-blue-500/20'
            }`}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* Notification */}
      {notification && (
        <div className={`p-3 rounded-lg border flex items-center gap-2 ${
          notification.type === 'success'
            ? 'bg-green-500/10 border-green-500/20 text-green-400'
            : notification.type === 'warning'
            ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
            : 'bg-red-500/10 border-red-500/20 text-red-400'
        }`}>
          <span>{notification.type === 'success' ? '✓' : notification.type === 'warning' ? '⚠️' : '✕'}</span>
          {notification.message}
          <button
            onClick={() => setNotification(null)}
            className="ml-auto text-slate-400 hover:text-slate-200"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Content */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* Sidebar - Simplified */}
        <div className="w-56 flex flex-col gap-1 overflow-y-auto bg-slate-800/30 rounded-xl p-3 border border-slate-700/50">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 py-2">
            Workflow Steps
          </div>
          {Object.entries(config.step_prompts)
            .sort(([a], [b]) => parseInt(a) - parseInt(b))
            .map(([stepKey]) => {
              const info = STEP_INFO[stepKey];
              return (
                <button
                  key={stepKey}
                  onClick={() => setActiveTab(stepKey)}
                  className={`text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
                    activeTab === stepKey
                      ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30'
                      : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
                  }`}
                >
                  <span className="text-base">{info?.icon || '📝'}</span>
                  <span>{STEP_LABELS[stepKey] || `Step ${stepKey}`}</span>
                </button>
              );
            })}

          <div className="h-px bg-slate-700/50 my-2" />

          <button
            onClick={() => setActiveTab('system')}
            className={`text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
              activeTab === 'system'
                ? 'bg-purple-600/20 text-purple-300 border border-purple-500/30'
                : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
            }`}
          >
            <span className="text-base">🎨</span>
            <span>Global Style</span>
          </button>

          <div className="mt-auto pt-4">
            <div className="text-xs text-slate-500 px-2">
              Changes apply within 30 seconds after saving.
            </div>
          </div>
        </div>

        {/* Editor Area */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          {/* Help Panel - Collapsible */}
          {showHelp && (
            <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
              <div className="flex items-start gap-3">
                <span className="text-2xl">{stepInfo.icon}</span>
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-amber-200 text-sm mb-1">{stepInfo.label}</h3>
                  <p className="text-xs text-slate-400 mb-3">{stepInfo.description}</p>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <h4 className="text-xs font-semibold text-slate-300 mb-2">✓ Safe to Change</h4>
                      <ul className="text-xs text-slate-400 space-y-1">
                        {stepInfo.canChange.map((item, i) => (
                          <li key={i}>• {item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <h4 className="text-xs font-semibold text-slate-300 mb-2">Example Guidance</h4>
                      <div className="text-xs text-slate-400 bg-slate-800/50 rounded p-2 font-mono">
                        {stepInfo.example}
                      </div>
                      <button
                        onClick={handleUseExample}
                        className="mt-2 text-xs text-blue-400 hover:text-blue-300 underline"
                      >
                        Use this example as starting point
                      </button>
                    </div>
                  </div>

                  <div className="mt-3 pt-3 border-t border-amber-500/10">
                    <p className="text-xs text-amber-400/80">
                      <strong>Remember:</strong> You can change tone and phrasing, but dates, prices, and room names
                      will always appear exactly as the system provides them.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Editor */}
          <div className="flex-1 flex flex-col bg-slate-900 rounded-xl border border-slate-700 overflow-hidden min-h-0">
            <div className="bg-slate-800/50 px-4 py-3 border-b border-slate-700 flex justify-between items-center flex-shrink-0">
              <div className="flex items-center gap-3">
                <span className="text-lg">{stepInfo.icon}</span>
                <div>
                  <span className="text-sm font-medium text-slate-200">
                    {stepInfo.label}
                  </span>
                  {hasChanges && (
                    <span className="ml-2 text-xs text-amber-400">• Modified</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {hasChanges && (
                  <button
                    onClick={handleResetToDefault}
                    className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded border border-slate-700 hover:border-slate-600"
                  >
                    Reset
                  </button>
                )}
                <span className={`text-xs ${
                  isContentShort ? 'text-amber-400' :
                  isContentLong ? 'text-red-400' :
                  'text-slate-500'
                }`}>
                  {charCount.toLocaleString()} chars
                </span>
              </div>
            </div>
            <textarea
              value={activeValue}
              onChange={(e) => handleTextChange(e.target.value)}
              placeholder="Enter your guidance for this step..."
              className={`flex-1 bg-transparent p-4 text-slate-300 text-sm resize-none focus:outline-none leading-relaxed ${
                activeTab === 'system' ? 'font-mono text-xs' : ''
              }`}
              spellCheck={true}
            />
            {(isContentShort || isContentLong) && (
              <div className={`px-4 py-2 text-xs border-t ${
                isContentShort ? 'bg-amber-500/5 border-amber-500/20 text-amber-400' :
                'bg-red-500/5 border-red-500/20 text-red-400'
              }`}>
                {isContentShort && '⚠️ This seems short. Consider adding more context for better results.'}
                {isContentLong && '⚠️ This is quite long. Consider being more concise.'}
              </div>
            )}
          </div>
        </div>

        {/* History Panel */}
        {showHistory && (
          <div className="w-72 bg-slate-800/50 rounded-xl border border-slate-700 flex flex-col overflow-hidden">
            <div className="p-3 border-b border-slate-700 bg-slate-800">
              <h3 className="font-semibold text-slate-200 text-sm">Version History</h3>
              <p className="text-xs text-slate-400">Click "Restore" to go back to a previous version</p>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
              {history.length === 0 ? (
                <div className="text-sm text-slate-500 text-center py-8">
                  No history yet.<br/>
                  <span className="text-xs">History is saved each time you make changes.</span>
                </div>
              ) : (
                history.map((entry, idx) => {
                  const date = new Date(entry.ts);
                  const isToday = date.toDateString() === new Date().toDateString();
                  return (
                    <div key={idx} className="bg-slate-900 border border-slate-700 rounded-lg p-3 hover:border-slate-600 transition-colors">
                      <div className="flex justify-between items-start mb-2">
                        <div>
                          <span className="text-xs text-slate-300 font-medium">
                            {isToday ? 'Today' : date.toLocaleDateString()}
                          </span>
                          <span className="text-xs text-slate-500 ml-2">
                            {date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        <button
                          onClick={() => handleRevert(idx)}
                          className="text-xs bg-slate-800 hover:bg-slate-700 text-blue-400 px-2 py-1 rounded border border-slate-700 transition-colors"
                        >
                          Restore
                        </button>
                      </div>
                      <div className="text-xs text-slate-500">
                        {Object.keys(entry.config.step_prompts).length} step prompts
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
